"""Cleaning: fix each known defect and say what was fixed (spec.md "Cleaning operations").

Every cleaner takes a Document, edits its blocks in place, and returns a
short human-readable description of what it changed (or None if it changed
nothing). The descriptions become the "cleaned" decision's reason, so the
decision log explains itself: "stripped UTF-8 BOM; normalised whitespace".

After cleaning, the near-empty rule (spec decision rule 6) may drop the
document instead.
"""

from __future__ import annotations

import math
import re

from golden import normalise
from models import Block, Decision, Document

# ---------------------------------------------------------------- encoding (from the loader)


def note_encoding(doc: Document, params: dict) -> str | None:
    """Decoding happens in the loader (nothing can be parsed before it); report it here."""
    info = doc.decision.details.get("load", {})
    notes = []
    if info.get("bom"):
        notes.append("stripped UTF-8 BOM")
    if info.get("utf8_failed"):
        guess = info.get("detector_guess")
        notes.append(f"decoded as {info['encoding']} (not valid UTF-8"
                     + (f"; detector guessed {guess}" if guess and guess != info["encoding"] else "") + ")")
    if info.get("converter") == "striprtf":
        notes.append("converted legacy RTF to text")
    angles = info.get("skew_angles")
    if info.get("parser") == "layout" and angles is None:  # a PDF with a real text layer
        notes.append("layout parser: reading order recovered, running headers/footers excluded as page furniture")
    if info.get("parser") == "layout" and angles is not None:  # an image-only scan
        note = "OCR + table extraction on image-only scan (layout parser)"
        rotated = [a for a in angles if abs(a) >= info["options"]["deskew_min_degrees"]]
        notes.append(note + (f"; deskewed {', '.join(f'{a:+.1f}' for a in rotated)} deg" if rotated else ""))
    return "; ".join(notes) or None


# ---------------------------------------------------------------- mojibake

_MOJIBAKE = re.compile(r"â€.|Ã.|Â(?=\W)")


def fix_mojibake(doc: Document, params: dict) -> str | None:
    """Repair text that was UTF-8, mis-read as cp1252, and saved again ("â€™" -> "’").

    ftfy.fix_encoding only undoes encoding mix-ups; unlike ftfy.fix_text it
    doesn't also straighten curly quotes or rewrite other characters.
    """
    import ftfy

    found = 0
    for block in doc.blocks:
        n = len(_MOJIBAKE.findall(block.text))
        if n:
            block.text = ftfy.fix_encoding(block.text)
            found += n
    return f"repaired {found} mojibake sequences" if found else None


# ---------------------------------------------------------------- tracked changes

_DELETED = re.compile(r"\s*\[DELETED:[^\]]*\]")


def remove_tracked_changes(doc: Document, params: dict) -> str | None:
    """"[DELETED: ...]" fragments are old text that Word left behind, often with
    values that conflict with the current ones. Remove them entirely."""
    removed = 0
    for block in doc.blocks:
        removed += len(_DELETED.findall(block.text))
        block.text = _DELETED.sub("", block.text)
    return f"removed {removed} tracked-change leftovers" if removed else None


# ---------------------------------------------------------------- HTML boilerplate


def _is_boilerplate(hint: str, params: dict) -> bool:
    for part in hint.split(" > "):
        tag = re.split(r"[.#]", part, maxsplit=1)[0]
        names = part[len(tag):].lower()
        if tag in params["html_boilerplate_tags"]:
            return True
        if any(word in names for word in params["html_boilerplate_names"]):
            return True
    return False


def remove_html_boilerplate(doc: Document, params: dict) -> str | None:
    if doc.format != "html":
        return None
    kept = [b for b in doc.blocks if not _is_boilerplate(b.source_hint, params)]
    removed = len(doc.blocks) - len(kept)
    doc.blocks = kept
    return f"removed {removed} boilerplate blocks (nav, cookie banner, sidebar, footer, ...)" if removed else None


# ---------------------------------------------------------------- email structure

_EMAIL_HEADER_LINE = re.compile(r"^(-{3,}\s*Original Message\s*-{3,}|(From|Sent|To|Cc|Subject):.*)$", re.I)


def clean_email(doc: Document, params: dict) -> str | None:
    """Unquote replies, drop per-message address headers, disclaimers and repeats.

    Quoted (">") lines are *unquoted*, not dropped: in this thread the
    member's original complaint exists only as a quoted reply.
    """
    if doc.format != "eml":
        return None
    counts = {"unquoted": 0, "headers": 0, "disclaimers": 0, "repeats": 0}
    seen: set[str] = set()
    kept = []
    for block in doc.blocks:
        lines = []
        for line in block.text.splitlines():
            if line.lstrip().startswith(">"):
                line = re.sub(r"^\s*(>\s?)+", "", line)
                counts["unquoted"] += 1
            if _EMAIL_HEADER_LINE.match(line.strip()):
                counts["headers"] += 1
                continue
            # A disclaimer is one long line, sometimes glued to a signature
            # ("Sent from my phone" + disclaimer), so match lines, not paragraphs.
            if line.strip().startswith(tuple(params["email_disclaimer_prefixes"])):
                counts["disclaimers"] += 1
                continue
            lines.append(line)
        # A quoted blank line is a bare ">", so the loader saw the whole quoted
        # message as one paragraph. Unquoted, those are real paragraph breaks.
        for para in re.split(r"\n\s*\n", "\n".join(lines)):
            text = "\n".join(ln for ln in para.splitlines() if ln.strip())
            if not text:
                continue
            key = normalise(text)
            if key in seen:  # repeated signature block, repeated sign-off
                counts["repeats"] += 1
                continue
            seen.add(key)
            kept.append(Block(type=block.type, text=text, level=block.level, section_path=block.section_path))
    doc.blocks = kept
    return ("email: unquoted {unquoted} reply lines, removed {headers} address-header lines, "
            "{disclaimers} disclaimers, {repeats} repeated blocks").format(**counts)


# ---------------------------------------------------------------- PDF running header / footer


def remove_running_lines(doc: Document, params: dict) -> str | None:
    """Remove lines that repeat in the top or bottom band of most pages.

    Digits are masked before comparing, so "Page 1 of 3" and "Page 2 of 3"
    count as the same line. (Docling already drops page furniture, so this
    mainly matters for the naive parser.)
    """
    if doc.format != "pdf":
        return None
    pages = sorted({b.page for b in doc.blocks if b.page})
    if len(pages) < 2:
        return None
    band = params["running_line_band"]

    def key(line: str) -> str:
        return re.sub(r"\d+", "#", normalise(line))

    pages_with: dict[str, set[int]] = {}
    for page in pages:
        lines = [ln for b in doc.blocks if b.page == page for ln in b.text.splitlines() if ln.strip()]
        for line in lines[:band] + lines[-band:]:
            pages_with.setdefault(key(line), set()).add(page)
    threshold = max(2, math.ceil(params["running_line_min_page_share"] * len(pages)))
    running = {k for k, p in pages_with.items() if len(p) >= threshold}
    if not running:
        return None
    removed = 0
    for block in doc.blocks:
        lines = block.text.splitlines()
        kept = [ln for ln in lines if key(ln) not in running]
        removed += len(lines) - len(kept)
        block.text = "\n".join(kept)
    doc.blocks = [b for b in doc.blocks if b.text.strip() or b.type == "figure_caption"]
    return f"removed running header/footer ({removed} lines over {len(pages)} pages)"


# ---------------------------------------------------------------- whitespace


def normalise_whitespace(doc: Document, params: dict) -> str | None:
    """CRLF/CR -> LF, NBSP and tabs -> space, runs of spaces -> one space."""
    changed = {"line endings": 0, "non-breaking spaces": 0, "tabs": 0, "repeated spaces": 0}
    for block in doc.blocks:
        text = block.text
        changed["line endings"] += text.count("\r")
        changed["non-breaking spaces"] += text.count(" ") + text.count(" ")
        changed["tabs"] += text.count("\t")
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = text.replace(" ", " ").replace(" ", " ").replace("\t", " ")
        new_lines = []
        for line in text.split("\n"):
            collapsed = re.sub(r" {2,}", " ", line).strip()
            changed["repeated spaces"] += collapsed != line.strip()
            new_lines.append(collapsed)
        block.text = "\n".join(new_lines).strip()
    doc.blocks = [b for b in doc.blocks if b.text or b.type == "figure_caption"]
    parts = [name for name, n in changed.items() if n]
    return f"normalised whitespace ({', '.join(parts)})" if parts else None


CLEANERS = [
    note_encoding,
    fix_mojibake,
    remove_tracked_changes,
    remove_html_boilerplate,
    clean_email,
    remove_running_lines,
    normalise_whitespace,
]


def near_empty_reason(doc: Document, params: dict) -> str | None:
    """Spec decision rule 6: too few words, or a short placeholder document."""
    words = len(doc.text.split())
    text = normalise(doc.text)
    placeholder = next((p for p in params["placeholder_phrases"] if re.search(rf"\b{re.escape(p)}\b", text)), None)
    if words < params["near_empty_min_words"]:
        return f"near-empty: {words} words" + (f"; placeholder text (\"{placeholder}\")" if placeholder else "")
    # A long document that merely mentions "TBD" somewhere is not a placeholder.
    if placeholder and words < params["placeholder_max_words"]:
        return f"near-empty: {words} words; placeholder text (\"{placeholder}\")"
    return None


def clean_document(doc: Document, params: dict) -> Document:
    """Run every cleaner, then decide: cleaned, or dropped as near-empty."""
    fixes = [f for cleaner in CLEANERS if (f := cleaner(doc, params))]
    doc.rebuild_text()
    details = {**doc.decision.details, "fixes": fixes, "words": len(doc.text.split())}
    reason = near_empty_reason(doc, params)
    if reason:
        doc.decision = Decision(status="dropped", reason=reason, stage="clean", details=details)
    else:
        doc.decision = Decision(status="cleaned", reason="; ".join(fixes) or f"no defects found; standard .{doc.format} extraction",
                                stage="clean", details=details)
    return doc
