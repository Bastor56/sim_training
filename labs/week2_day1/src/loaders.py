"""Per-format loaders: raw file -> list of Blocks, plus what the loader noticed.

Loaders only *read*. They decode bytes and recover structure (headings,
lists, tables) but don't decide what is boilerplate or junk. That's the
cleaning stage (milestone 6), which gets each block's `source_hint` (the
HTML tags/classes above it) and the loader's `info` (encoding used, BOM
found, ...) so it can explain every fix it makes.

One exception: <script>/<style> contents are code, not text, so the HTML
loader never emits them.

Every loader returns (blocks, info). A file that can't be read raises
LoadError, which the pipeline turns into a "quarantined" decision.
"""

from __future__ import annotations

import csv
import email
import email.policy
import io
import re
from pathlib import Path

from models import Block

HEADING_MAX_CHARS = 80


class LoadError(Exception):
    """The file could not be read or parsed at all."""


# ---------------------------------------------------------------- decoding

FALLBACK_ENCODINGS = ("cp1252",)  # what Windows tools write when they don't write UTF-8


def decode_bytes(raw: bytes) -> tuple[str, dict]:
    """Strict UTF-8, then Windows-1252, then (only if both fail) a detector's guess.

    Why not trust the detector first: on the privacy notice charset_normalizer
    guessed cp775 (a Baltic code page) and would have garbled every smart
    quote. Its guess is still recorded, so the log shows the disagreement.

    A UTF-8 byte-order mark is removed and recorded. Mojibake inside valid
    UTF-8 ("â€™") is *not* fixed here: the bytes are valid, the text is
    wrong, and repairing it is a cleaning decision.
    """
    info: dict = {"bom": raw.startswith(b"\xef\xbb\xbf")}
    try:
        info["encoding"] = "utf-8"
        return raw.decode("utf-8-sig"), info
    except UnicodeDecodeError:
        info["utf8_failed"] = True

    from charset_normalizer import from_bytes

    best = from_bytes(raw).best()
    info["detector_guess"] = best.encoding if best else None
    for encoding in FALLBACK_ENCODINGS:
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError:
            continue
        info["encoding"] = encoding
        return text, info
    if best is None:
        raise LoadError("undecodable: not UTF-8 or cp1252, and no encoding detected")
    info["encoding"] = best.encoding
    return str(best), info


# ---------------------------------------------------------------- shared helpers

_NUMBERED_HEADING = re.compile(r"^\d{1,2}(\.\d{1,2})*\.?\s+\S")


def _looks_like_heading(line: str) -> bool:
    """Plain-text heading rule (spec "Chunking"): a numbered line like "3. Fees",
    a short ALL-CAPS line, or a short line that doesn't end like a sentence."""
    line = line.strip()
    if not line or len(line) > HEADING_MAX_CHARS or line.startswith(("-", "*", ">", "•")):
        return False
    if _NUMBERED_HEADING.match(line) and not line.endswith("."):
        return True
    letters = [c for c in line if c.isalpha()]
    if letters and all(c.isupper() for c in letters) and len(letters) >= 4:
        return True
    return line[-1] not in ".,;:" and not any(ch.isdigit() for ch in line[:1]) and len(line.split()) <= 8


def assign_section_paths(blocks: list[Block]) -> list[Block]:
    """Set each block's section_path from the headings above it."""
    stack: list[tuple[int, str]] = []
    for block in blocks:
        if block.type == "heading":
            level = block.level or 2
            while stack and stack[-1][0] >= level:
                stack.pop()
            block.section_path = [t for _, t in stack]
            stack.append((level, block.text))
        else:
            block.section_path = [t for _, t in stack]
    return blocks


def _table_block(rows: list[list[str]], **kwargs) -> Block:
    return Block(type="table", text="\n".join(" | ".join(c.strip() for c in row) for row in rows), **kwargs)


def _text_to_blocks(text: str) -> list[Block]:
    """Plain text: blank-line paragraphs, "- " list items, "a|b|" table rows,
    heading heuristic for one-line paragraphs. The first heading is the title."""
    blocks: list[Block] = []
    for para in re.split(r"\n\s*\n", text):
        lines = [ln for ln in para.splitlines() if ln.strip()]
        if not lines:
            continue
        if all("|" in ln for ln in lines) and len(lines) >= 2:
            blocks.append(_table_block(_strip_table_cells(lines)))
            continue
        # A table can start right after a heading line with no blank line between (RTF).
        if len(lines) >= 3 and "|" not in lines[0] and all("|" in ln for ln in lines[1:]):
            blocks.extend(_text_to_blocks(lines[0]))
            blocks.append(_table_block(_strip_table_cells(lines[1:])))
            continue
        if all(ln.lstrip().startswith(("- ", "* ", "• ")) for ln in lines):
            blocks.extend(Block(type="list_item", text=ln.strip()) for ln in lines)
            continue
        if len(lines) == 1 and _looks_like_heading(lines[0]):
            level = 1 if not any(b.type == "heading" for b in blocks) else 2
            blocks.append(Block(type="heading", text=lines[0].strip(), level=level))
            continue
        blocks.append(Block(type="paragraph", text="\n".join(ln.rstrip() for ln in lines)))
    return blocks


def _strip_table_cells(rows_text: list[str]) -> list[list[str]]:
    rows = []
    for ln in rows_text:
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        rows.append(cells)
    return rows


# ---------------------------------------------------------------- per format

def load_md(path: Path) -> tuple[list[Block], dict]:
    text, info = decode_bytes(path.read_bytes())
    blocks: list[Block] = []
    para: list[str] = []
    table: list[str] = []

    def flush():
        if para:
            blocks.append(Block(type="paragraph", text="\n".join(para)))
            para.clear()
        if table:
            rows = [r for r in _strip_table_cells(table) if not all(set(c) <= set("-: ") for c in r)]
            blocks.append(_table_block(rows))
            table.clear()

    for line in text.splitlines():
        stripped = line.strip()
        heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if not stripped:
            flush()
        elif heading:
            flush()
            blocks.append(Block(type="heading", text=heading.group(2).strip(), level=len(heading.group(1))))
        elif stripped.startswith("|"):
            if para:
                flush()
            table.append(stripped)
        elif re.match(r"^([-*+]|\d+[.)])\s+", stripped):
            flush()
            blocks.append(Block(type="list_item", text=stripped))
        else:
            if table:
                flush()
            para.append(line.rstrip())
    flush()
    return blocks, info


def load_txt(path: Path) -> tuple[list[Block], dict]:
    text, info = decode_bytes(path.read_bytes())
    return _text_to_blocks(text), info


def load_rtf(path: Path) -> tuple[list[Block], dict]:
    from striprtf.striprtf import rtf_to_text

    raw = path.read_bytes()
    try:
        # RTF is 7-bit ASCII; non-ASCII characters are \'xx escapes in the
        # declared code page (\ansicpg1252), which striprtf decodes.
        text = rtf_to_text(raw.decode("ascii"), encoding="cp1252")
    except UnicodeDecodeError as exc:
        raise LoadError(f"RTF is not 7-bit ASCII: {exc}") from exc
    # striprtf ends each RTF paragraph (\\par) with a single newline, so give
    # every line its own paragraph, keeping consecutive table rows together.
    paragraphs: list[str] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        if "|" in line and paragraphs and "|" in paragraphs[-1].splitlines()[-1]:
            paragraphs[-1] += "\n" + line
        else:
            paragraphs.append(line)
    return _text_to_blocks("\n\n".join(paragraphs)), {"encoding": "ascii+cp1252 escapes", "converter": "striprtf"}


_HTML_SKIP = {"script", "style", "noscript", "template", "link", "meta", "head"}
_HTML_BLOCKS = {"h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "dt", "dd", "summary", "blockquote"}


def _hint(el) -> str:
    """The element's ancestry as "tag.class > tag.class", nearest last."""
    parts = []
    for node in [el, *el.parents]:
        if node.name in (None, "[document]", "html", "body"):
            continue
        classes = ".".join(node.get("class", []))
        ident = f"#{node['id']}" if node.get("id") else ""
        parts.append(f"{node.name}{ident}{'.' + classes if classes else ''}")
    return " > ".join(reversed(parts))


def load_html(path: Path) -> tuple[list[Block], dict]:
    from bs4 import BeautifulSoup, NavigableString, Tag

    text, info = decode_bytes(path.read_bytes())
    soup = BeautifulSoup(text, "html.parser")
    blocks: list[Block] = []

    def clean(s: str) -> str:
        return " ".join(s.split())

    def walk(el: Tag) -> None:
        for child in el.children:
            if isinstance(child, NavigableString):
                continue
            if not isinstance(child, Tag) or child.name in _HTML_SKIP:
                continue
            name = child.name
            if name in _HTML_BLOCKS:
                content = clean(child.get_text(" "))
                if not content:
                    continue
                if name[0] == "h" and name[1:].isdigit():
                    blocks.append(Block(type="heading", text=content, level=int(name[1]), source_hint=_hint(child)))
                elif name == "li":
                    blocks.append(Block(type="list_item", text=content, source_hint=_hint(child)))
                else:
                    blocks.append(Block(type="paragraph", text=content, source_hint=_hint(child)))
            elif name == "tr" and not child.find("table"):
                cells = [clean(c.get_text(" ")) for c in child.find_all(["td", "th"], recursive=False)]
                if any(cells):
                    blocks.append(_table_block([cells], source_hint=_hint(child)))
            elif name == "div" and not child.find(list(_HTML_BLOCKS) + ["div", "table", "ul", "ol"]):
                # Leaf <div> holding text directly, e.g. an accordion header.
                content = clean(child.get_text(" "))
                if content:
                    blocks.append(Block(type="paragraph", text=content, source_hint=_hint(child)))
            else:
                walk(child)

    walk(soup.body or soup)
    # Merge consecutive single-row table blocks from the same table.
    merged: list[Block] = []
    for b in blocks:
        if merged and b.type == merged[-1].type == "table" and b.source_hint == merged[-1].source_hint:
            merged[-1].text += "\n" + b.text
        else:
            merged.append(b)
    info["title"] = clean(soup.title.get_text()) if soup.title else ""
    return merged, info


def load_docx(path: Path) -> tuple[list[Block], dict]:
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    try:
        document = docx.Document(str(path))
    except Exception as exc:  # python-docx raises several types for broken files
        raise LoadError(f"unreadable docx: {exc}") from exc

    blocks: list[Block] = []
    list_counter = 0
    # Walk the body in order, so tables stay where they are in the document.
    for child in document.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "tbl":
            table = Table(child, document)
            blocks.append(_table_block([[c.text for c in row.cells] for row in table.rows]))
            list_counter = 0
        elif tag == "p":
            para = Paragraph(child, document)
            text, style = para.text.strip(), (para.style.name if para.style is not None else "")
            if not text:
                continue
            if style == "Title":
                blocks.append(Block(type="heading", text=text, level=1))
            elif style.startswith("Heading"):
                level = int(style.split()[-1]) + 1 if style.split()[-1].isdigit() else 2
                blocks.append(Block(type="heading", text=text, level=level))
            elif style.startswith("List Number"):
                # Word stores the number in the numbering definition, not the
                # text; keep it as text so "step 3" stays findable.
                list_counter += 1
                blocks.append(Block(type="list_item", text=f"{list_counter}. {text}"))
                continue
            elif style.startswith("List"):
                blocks.append(Block(type="list_item", text=f"- {text}"))
            else:
                blocks.append(Block(type="paragraph", text=text))
            list_counter = 0
    return blocks, {"styles": "Title/Heading N/List Number/List Bullet"}


def load_eml(path: Path) -> tuple[list[Block], dict]:
    """Subject and Date, then the plain-text body as paragraphs. Address
    headers (From/To/Cc) are metadata about people, not document content."""
    message = email.message_from_bytes(path.read_bytes(), policy=email.policy.default)
    part = message.get_body(preferencelist=("plain", "html"))
    if part is None:
        raise LoadError("email has no text body")
    body = part.get_content()
    blocks = [
        Block(type="heading", text=str(message["Subject"] or "(no subject)"), level=1),
        Block(type="paragraph", text=f"Date: {message['Date']}"),
    ]
    for para in re.split(r"\n\s*\n", body):
        lines = [ln.rstrip() for ln in para.splitlines() if ln.strip()]
        if lines:
            blocks.append(Block(type="paragraph", text="\n".join(lines)))
    return blocks, {"content_type": part.get_content_type(), "charset": part.get_content_charset()}


def load_csv(path: Path) -> tuple[list[Block], dict]:
    raw = path.read_bytes()
    if not raw:
        return [], {"bytes": 0}
    text, info = decode_bytes(raw)
    rows = [row for row in csv.reader(io.StringIO(text)) if any(c.strip() for c in row)]
    return ([_table_block(rows)] if rows else []), info


def load_pdf(path: Path, parser: str) -> tuple[list[Block], dict]:
    if parser == "naive":
        import parse_pdf_naive

        load = parse_pdf_naive.parse_blocks
    elif parser == "layout":
        import parse_pdf_layout

        load = parse_pdf_layout.parse_blocks
    else:
        raise ValueError(f"unknown parser {parser!r}")
    try:
        return load(path)
    except Exception as exc:  # PyMuPDF / Docling raise many types on broken PDFs
        raise LoadError(f"unreadable pdf: {type(exc).__name__}: {exc}") from exc


LOADERS = {
    "md": load_md,
    "txt": load_txt,
    "rtf": load_rtf,
    "html": load_html,
    "docx": load_docx,
    "eml": load_eml,
    "csv": load_csv,
}


def file_format(path: Path) -> str:
    fmt = path.suffix.lower().lstrip(".")
    return "html" if fmt == "htm" else fmt


def load_blocks(path: Path, parser: str = "layout") -> tuple[list[Block], dict]:
    """Dispatch on file extension. The parser choice only affects PDFs."""
    fmt = file_format(path)
    if fmt == "pdf":
        blocks, info = load_pdf(path, parser)
    elif fmt in LOADERS:
        blocks, info = LOADERS[fmt](path)
    else:
        raise LoadError(f"no loader for .{fmt} files")
    if fmt != "pdf":  # the layout parser already builds its own section paths
        assign_section_paths(blocks)
    return blocks, {"format": fmt, **info}
