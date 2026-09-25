"""Naive PDF parser: PyMuPDF's plain text layer, one paragraph block per page.

This is the baseline the layout-aware parser has to beat (spec.md "Parsers").
On an image-only scan there is no text layer, so every page comes back empty;
on the two-column newsletter the text comes back in content-stream order,
which interleaves the columns.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf

from models import Block

PARSER_VERSION = "1"


def parse_blocks(path: str | Path) -> tuple[list[Block], dict]:
    """Return (blocks, info). Raises if the PDF can't be opened or has no pages."""
    blocks: list[Block] = []
    pages_without_text = 0
    with pymupdf.open(path) as pdf:
        if pdf.page_count == 0:
            raise ValueError("PDF has 0 pages")
        for page in pdf:
            text = page.get_text("text").strip()
            if text:
                blocks.append(Block(type="paragraph", text=text, page=page.number + 1))
            else:
                pages_without_text += 1
        page_count = pdf.page_count
    info = {
        "parser": "naive",
        "parser_version": PARSER_VERSION,
        "pymupdf_version": pymupdf.VersionBind,
        "pages": page_count,
        "pages_without_text": pages_without_text,
    }
    return blocks, info
