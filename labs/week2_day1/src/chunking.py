"""Two chunking strategies behind one interface (spec.md "Chunking strategies").

A_fixed      fixed-size windows over Document.text with overlap. Ignores
             structure: a table row or a policy clause can be cut in half.
B_structure  one section (heading + its blocks) at a time; long sections are
             packed at block boundaries, tables are kept whole (or split by
             rows with the header repeated), and the section path is
             prefixed so a chunk carries the context it lacks on its own.

Both fill the full chunk metadata schema. `char_start`/`char_end` always
point into Document.text; for B the chunk text is the section-path prefix
plus exactly that slice (except a split table piece, whose repeated header
row isn't contiguous).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from models import Block, Chunk, Document


@dataclass
class _Span:
    """A block's position in Document.text."""

    block: Block
    start: int
    end: int


def _block_spans(doc: Document) -> list[_Span]:
    """Offsets of each text-bearing block in Document.text ("\\n\\n"-joined)."""
    spans, pos = [], 0
    for block in doc.blocks:
        if not block.text:
            continue
        spans.append(_Span(block, pos, pos + len(block.text)))
        pos += len(block.text) + 2
    assert pos - 2 == len(doc.text) or not spans, f"{doc.doc_id}: blocks don't rebuild Document.text"
    return spans


def _section_path(block: Block) -> list[str]:
    """Headings above a block, including the block itself if it is a heading."""
    return [*block.section_path, block.text] if block.type == "heading" else list(block.section_path)


def _metadata(doc: Document, chunker: str, params: dict, index: int, start: int, end: int,
              spans: list[_Span], text: str) -> dict:
    inside = [s for s in spans if s.start < end and s.end > start] or spans[:1]
    pages = [s.block.page for s in inside if s.block.page]
    first = inside[0].block
    cat = doc.catalog
    # Chroma metadata must be str/int/float/bool: "missing" is "" or -1, never None.
    return {
        "chunk_id": Chunk.make_id(doc.doc_id, doc.parser, chunker, index),
        "doc_id": doc.doc_id,
        "source_filename": doc.source_filename,
        "title": cat.get("title", ""),
        "chunk_index": index,
        "char_start": start,
        "char_end": end,
        "page_start": min(pages) if pages else -1,
        "page_end": max(pages) if pages else -1,
        "section_path": " > ".join(_section_path(first)),
        "tenant": cat.get("tenant", ""),
        "sensitivity": cat.get("sensitivity", ""),
        "version": cat.get("version", ""),
        "effective_date": cat.get("effective_date", ""),
        "superseded_by": cat.get("superseded_by", ""),
        "is_current": not cat.get("superseded_by"),
        "parser": doc.parser,
        "chunker": chunker,
        "chunker_params": json.dumps(params, sort_keys=True),
        "contains_generated_text": any(s.block.generated for s in inside),
        "pii_redactions": text.count("[REDACTED-"),
    }


def _windows(text: str, offset: int, size: int, overlap: int, backoff: int) -> list[tuple[int, int]]:
    """(start, end) windows of at most `size` chars that never cut a word.

    Each window ends at the last whitespace within `backoff` chars of the size
    limit; the next one starts `overlap` chars earlier, moved forward to the
    start of a word.
    """
    out, start, n = [], 0, len(text)
    while start < n:
        end = min(start + size, n)
        if end < n:
            cut = max(text.rfind(" ", end - backoff, end + 1), text.rfind("\n", end - backoff, end + 1))
            if cut > start:
                end = cut
        # Trim whitespace so the window is exactly text[start:end].
        s, e = start, end
        while s < e and text[s].isspace():
            s += 1
        while e > s and text[e - 1].isspace():
            e -= 1
        if e > s:
            out.append((offset + s, offset + e))
        if end >= n:
            break
        nxt = max(end - overlap, start + 1)
        while nxt < end and not text[nxt - 1].isspace():  # don't start mid-word
            nxt += 1
        start = nxt
    return out


class FixedChunker:
    """A_fixed: ~200-token windows with 150-char overlap, structure ignored."""

    name = "A_fixed"

    def __init__(self, params: dict):
        self.params = params

    def chunk(self, docs: list[Document]) -> list[Chunk]:
        p = self.params
        backoff = int(re.search(r"\d+", p["boundary"]).group())
        chunks = []
        for doc in docs:
            if not doc.decision.is_active:
                continue
            spans = _block_spans(doc)
            for i, (s, e) in enumerate(_windows(doc.text, 0, p["size_chars"], p["overlap_chars"], backoff)):
                text = doc.text[s:e]
                chunks.append(Chunk(Chunk.make_id(doc.doc_id, doc.parser, self.name, i), text,
                                    _metadata(doc, self.name, p, i, s, e, spans, text)))
        return chunks


class StructureChunker:
    """B_structure: heading-bounded sections, whole tables, section-path prefix."""

    name = "B_structure"

    def __init__(self, params: dict):
        self.params = params

    def _sections(self, spans: list[_Span]) -> list[list[_Span]]:
        """A new section starts at every heading. A section shorter than
        min_chars (a title, a subtitle) is merged into the one after it."""
        sections: list[list[_Span]] = []
        for span in spans:
            if span.block.type == "heading" or not sections:
                sections.append([span])
            else:
                sections[-1].append(span)
        merged: list[list[_Span]] = []
        carry: list[_Span] = []
        for i, section in enumerate(sections):
            section = carry + section
            is_last = i == len(sections) - 1
            if section[-1].end - section[0].start < self.params["min_chars"] and not is_last:
                carry = section
                continue
            merged.append(section)
            carry = []
        if carry:
            merged.append(carry)
        return merged

    def _units(self, section: list[_Span], text: str) -> list[tuple[int, int, str | None]]:
        """Packing units: (start, end, override text). Override text is only set
        for pieces of a table too big to keep whole (header row repeated)."""
        p, units = self.params, []
        for span in section:
            length = span.end - span.start
            if span.block.type == "table":
                if length <= p["table_max_chars"]:
                    units.append((span.start, span.end, None))
                    continue
                rows = span.block.text.split("\n")
                header, pos, piece = rows[0], span.start + len(rows[0]) + 1, []
                piece_start = pos
                for row in rows[1:]:
                    if piece and len(header) + sum(len(r) + 1 for r in piece) + len(row) > p["table_max_chars"]:
                        units.append((piece_start, pos - 1, "\n".join([header, *piece])))
                        piece, piece_start = [], pos
                    piece.append(row)
                    pos += len(row) + 1
                units.append((piece_start, pos - 1, "\n".join([header, *piece])))
            elif length > p["max_chars"]:  # a very long paragraph: split between words, no overlap
                units.extend((s, e, None) for s, e in
                             _windows(text[span.start:span.end], span.start, p["max_chars"], 0, 200))
            else:
                units.append((span.start, span.end, None))
        return units

    def chunk(self, docs: list[Document]) -> list[Chunk]:
        p = self.params
        chunks = []
        for doc in docs:
            if not doc.decision.is_active:
                continue
            spans = _block_spans(doc)
            index = 0
            for section in self._sections(spans):
                groups: list[list[tuple[int, int, str | None]]] = []
                for unit in self._units(section, doc.text):
                    fits = groups and groups[-1][-1][2] is None and unit[2] is None and \
                        unit[1] - groups[-1][0][0] <= p["max_chars"]
                    if fits:
                        groups[-1].append(unit)
                    else:
                        groups.append([unit])
                for group in groups:
                    start, end = group[0][0], group[-1][1]
                    body = group[0][2] if group[0][2] is not None else doc.text[start:end]
                    first = next(s.block for s in spans if s.end > start)
                    # Prefix the headings *above* the chunk's first block (a leading
                    # heading is already the chunk's first line).
                    path = first.section_path if first.type == "heading" else _section_path(first)
                    prefix = " > ".join(path) + "\n" if p["prefix_section_path"] and path else ""
                    text = prefix + body
                    meta = _metadata(doc, self.name, p, index, start, end, spans, text)
                    meta["prefix_chars"] = len(prefix)
                    chunks.append(Chunk(Chunk.make_id(doc.doc_id, doc.parser, self.name, index), text, meta))
                    index += 1
        return chunks


CHUNKERS = {"A_fixed": FixedChunker, "B_structure": StructureChunker}


def make_chunker(name: str, params: dict):
    return CHUNKERS[name](params)
