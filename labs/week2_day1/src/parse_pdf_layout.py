"""Layout-aware PDF parser: Docling (OCR + reading order + table structure).

Maps Docling's document tree to our Blocks (spec.md "Parsers"):
  title / section_header -> heading (with a section path for chunker B)
  text / paragraph / caption / footnote / ... -> paragraph
  list_item -> list_item
  table -> table, header row first, one row per line, cells joined by " | "
  picture -> figure_caption with an empty text and the crop saved to disk;
             milestone 3's captioner fills in the text.
Running page headers and footers are Docling "furniture" and are left out.

Docling is slow (model loading + OCR), so results are cached per
(file hash, parser options). A rerun with the same file and options is instant.

Spike (milestone 2):  uv run python src/parse_pdf_layout.py --spike
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import time
from importlib.metadata import version
from pathlib import Path

from config import CORPUS_DIR, LAB_DIR, RUNS_DIR, SOURCE_CATALOG_PATH, STAGE_CACHE_DIR
from models import Block

PARSER_VERSION = "2"  # 2: figures carry their linked caption (figure_label)
CACHE_DIR = STAGE_CACHE_DIR / "parse_layout"
FIGURE_DIR = STAGE_CACHE_DIR / "figures"

DEFAULT_OPTIONS = {
    "ocr_engine": "ocrmac",  # Apple Vision; "rapidocr" is the portable fallback
    "images_scale": 2.0,  # render scale for picture crops (2.0 = 144 dpi)
    "table_mode": "accurate",
    "do_cell_matching": True,
    # Straighten image-only scans before Docling sees them. Without it the
    # mortgage notice's 3-degree skew shifted its APR column down one row
    # (milestone 2 spike). Digital PDFs are never touched: re-rasterising
    # would throw away their real text layer.
    "deskew": True,
    "deskew_dpi": 200,
    "deskew_max_degrees": 5.0,
    # Rotating resamples the image and softens glyphs: straightening the
    # fee schedule's 1.4-degree tilt turned "ATM" into "AT". Docling copes
    # with small tilts, so only pages at or beyond this angle are rotated.
    "deskew_min_degrees": 2.0,
}

_TEXT_LABELS = {"text", "paragraph", "caption", "footnote", "reference", "handwritten_text", "code", "formula"}

_converters: dict[str, object] = {}  # one Docling converter per options set; loading models is slow


def file_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _options_key(options: dict) -> str:
    blob = json.dumps({"parser_version": PARSER_VERSION, **options}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


def _converter(options: dict):
    key = _options_key(options)
    if key in _converters:
        return _converters[key]

    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import (
        OcrMacOptions,
        PdfPipelineOptions,
        RapidOcrOptions,
        TableFormerMode,
    )
    from docling.document_converter import DocumentConverter, PdfFormatOption

    ocr = {
        "ocrmac": lambda: OcrMacOptions(),
        "rapidocr": lambda: RapidOcrOptions(backend="onnxruntime"),
    }[options["ocr_engine"]]()
    pipeline = PdfPipelineOptions(
        do_ocr=True,
        ocr_options=ocr,
        do_table_structure=True,
        generate_picture_images=True,
        images_scale=options["images_scale"],
    )
    pipeline.table_structure_options.mode = TableFormerMode(options["table_mode"])
    pipeline.table_structure_options.do_cell_matching = options["do_cell_matching"]
    converter = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline)})
    _converters[key] = converter
    return converter


def _skew_angle(image, max_degrees: float, step: float = 0.1) -> float:
    """Rotation (degrees) that makes the text lines horizontal.

    Projection-profile method: rotate the ink mask through candidate angles
    and keep the one whose row sums are "spikiest" (highest variance), which
    happens when every text line falls into as few pixel rows as possible.
    """
    import numpy as np
    from PIL import Image

    small = image.convert("L").resize((image.width // 2, image.height // 2))
    ink = Image.fromarray(((np.asarray(small) < 128) * 255).astype("uint8"))
    best_angle, best_score = 0.0, -1.0
    for angle in np.arange(-max_degrees, max_degrees + step / 2, step):
        rotated = np.asarray(ink.rotate(float(angle), resample=Image.BILINEAR, fillcolor=0), dtype=np.float32)
        score = float(np.var(rotated.sum(axis=1)))
        if score > best_score:
            best_angle, best_score = round(float(angle), 1), score
    return best_angle


def _deskewed_copy(path: Path, sha: str, options: dict) -> tuple[Path, list[float] | None]:
    """For an image-only PDF, write a straightened copy and return its path
    and the per-page angles. Any PDF with a text layer is returned unchanged."""
    import io

    import pymupdf
    from PIL import Image

    with pymupdf.open(path) as pdf:
        if any(page.get_text("text").strip() for page in pdf):
            return path, None
        images, angles = [], []
        for page in pdf:
            pix = page.get_pixmap(dpi=options["deskew_dpi"])
            images.append(Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB"))
            angles.append(_skew_angle(images[-1], options["deskew_max_degrees"]))
        if all(abs(a) < options["deskew_min_degrees"] for a in angles):
            return path, angles  # measured, but too small to be worth resampling
        out = pymupdf.open()
        for page, image, angle in zip(pdf, images, angles):
            if abs(angle) >= options["deskew_min_degrees"]:
                image = image.rotate(angle, resample=Image.BICUBIC, fillcolor=(255, 255, 255))
            buf = io.BytesIO()
            image.save(buf, format="PNG")
            new_page = out.new_page(width=page.rect.width, height=page.rect.height)
            new_page.insert_image(new_page.rect, stream=buf.getvalue())
    deskewed = STAGE_CACHE_DIR / "deskewed" / f"{sha}.pdf"
    deskewed.parent.mkdir(parents=True, exist_ok=True)
    out.save(deskewed)
    out.close()
    return deskewed, angles


def _table_rows(item, doc) -> list[str]:
    """Header row first, then one line per row, cells joined by " | "."""
    df = item.export_to_dataframe(doc=doc)
    header = [str(c).strip() for c in df.columns]
    rows = []
    # Docling numbers the columns 0..n when it found no header row.
    if not all(h.isdigit() for h in header):
        rows.append(" | ".join(header))
    for _, row in df.iterrows():
        rows.append(" | ".join(str(v).strip() for v in row.tolist()))
    return rows


def _to_blocks(doc, sha: str) -> list[Block]:
    from docling_core.types.doc import PictureItem, TableItem

    blocks: list[Block] = []
    headings: list[tuple[int, str]] = []  # (level, text) stack for section_path
    figure_n = 0
    for item, _depth in doc.iterate_items():
        label = item.label.value  # a DocItemLabel, e.g. "section_header"
        page = item.prov[0].page_no if getattr(item, "prov", None) else None
        section_path = [text for _, text in headings]

        if label in ("title", "section_header"):
            text = item.text.strip()
            if not text:
                continue
            level = 1 if label == "title" else item.level + 1
            while headings and headings[-1][0] >= level:
                headings.pop()
            blocks.append(Block(type="heading", text=text, level=level, page=page,
                                section_path=[t for _, t in headings]))
            headings.append((level, text))
        elif isinstance(item, TableItem):
            rows = _table_rows(item, doc)
            if rows:
                blocks.append(Block(type="table", text="\n".join(rows), page=page, section_path=section_path))
        elif isinstance(item, PictureItem):
            figure_n += 1
            image = item.get_image(doc)
            image_ref = ""
            if image is not None:
                FIGURE_DIR.mkdir(parents=True, exist_ok=True)
                crop = FIGURE_DIR / f"{sha[:16]}_p{page}_fig{figure_n}.png"
                image.save(crop)
                image_ref = str(crop.relative_to(LAB_DIR))
            # Docling links a printed "Figure N. ..." caption to real figures;
            # signatures, stamps and logos have none. The captioner's
            # governance gate relies on this (spec "Figure captioning").
            blocks.append(Block(type="figure_caption", text="", page=page, section_path=section_path,
                                generated=True, image_ref=image_ref,
                                figure_label=item.caption_text(doc).strip()))
        elif label == "list_item":
            text = item.text.strip()
            if text:
                blocks.append(Block(type="list_item", text=text, page=page, section_path=section_path))
        elif label in _TEXT_LABELS:
            text = item.text.strip()
            if text:
                blocks.append(Block(type="paragraph", text=text, page=page, section_path=section_path))
        # page_header / page_footer are furniture and never reach here.
    return blocks


def parse_blocks(path: str | Path, options: dict | None = None) -> tuple[list[Block], dict]:
    """Return (blocks, info), from the cache when this file + options were seen before."""
    options = {**DEFAULT_OPTIONS, **(options or {})}
    sha = file_sha256(path)
    cache_file = CACHE_DIR / f"{sha}__{_options_key(options)}.json"
    if cache_file.exists():
        cached = json.loads(cache_file.read_text(encoding="utf-8"))
        if "error" in cached:  # a known-broken file: don't start Docling just to fail again
            raise ValueError(cached["error"])
        return [Block.from_dict(b) for b in cached["blocks"]], {**cached["info"], "cache_hit": True}

    started = time.perf_counter()
    source, skew_angles = Path(path), None
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        if options["deskew"]:
            source, skew_angles = _deskewed_copy(source, sha, options)
        result = _converter(options).convert(str(source))
    except Exception as exc:  # Docling / PyMuPDF raise many types on broken PDFs
        error = f"{type(exc).__name__}: {str(exc).splitlines()[0][:200]}"
        cache_file.write_text(json.dumps({"error": error}), encoding="utf-8")
        raise ValueError(error) from exc
    blocks = _to_blocks(result.document, sha)
    info = {
        "parser": "layout",
        "parser_version": PARSER_VERSION,
        "docling_version": version("docling"),
        "options": options,
        "skew_angles": skew_angles,  # None = had a text layer, not deskewed
        "pages": len(result.document.pages),
        "seconds": round(time.perf_counter() - started, 2),
    }
    cache_file.write_text(
        json.dumps({"blocks": [b.__dict__ for b in blocks], "info": info}, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    return blocks, {**info, "cache_hit": False}


# ----------------------------------------------------------------- spike

SPIKE_DOCS = [
    "fee_schedule_2026",
    "deposit_rate_sheet_2026q3",
    "auto_loan_comparison",
    "mortgage_heloc_rate_notice",
    "newsletter_summer_2026",
]


def _quotes_by_doc() -> dict[str, list[tuple[str, object]]]:
    """doc_id -> unique (query type, Location) pairs across the golden set."""
    from golden import load_golden_set, normalise

    out: dict[str, dict[str, tuple[str, object]]] = {}
    for q in load_golden_set().queries:
        for loc in q.expected:
            out.setdefault(loc.doc_id, {}).setdefault(normalise(loc.quote), (q.type, loc))
    return {doc_id: list(v.values()) for doc_id, v in out.items()}


def _table_row_accuracy(parsed_text: str, doc_id: str) -> tuple[int, int]:
    """(exact rows found, rows in ground truth) for every " | " table row.

    Stricter than quote survival: all_tokens only needs the words somewhere
    in the text, so a column shifted by one row still "survives". Here the
    whole row (label and every cell, in order) has to come out intact.
    """
    from config import GROUND_TRUTH_DIR
    from golden import normalise

    def rows(text: str) -> list[str]:
        return [" | ".join(c.strip() for c in normalise(line).split("|")) for line in text.splitlines() if "|" in line]

    truth = rows((GROUND_TRUTH_DIR / f"{doc_id}.txt").read_text(encoding="utf-8"))
    parsed = set(rows(parsed_text))
    return sum(r in parsed for r in truth), len(truth)


def run_spike(options: dict | None = None, captions: str = "off") -> None:
    import parse_pdf_naive
    from captioning import apply_captions
    from golden import matches

    with open(SOURCE_CATALOG_PATH, encoding="utf-8", newline="") as f:
        catalog = {r["doc_id"]: r for r in csv.DictReader(f)}
    quotes = _quotes_by_doc()
    out_dir = RUNS_DIR / "spike"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"{'doc_id':28s} {'naive':>6s} {'layout':>7s}  {'figure':>6s}  {'secs':>5s}  tables  figures"
          f"  exact table rows  skew")
    totals = {"naive": 0, "layout": 0, "n": 0, "fig": 0, "n_fig": 0}
    for doc_id in SPIKE_DOCS:
        path = CORPUS_DIR / catalog[doc_id]["filename"]
        naive_blocks, _ = parse_pdf_naive.parse_blocks(path)
        layout_blocks, info = parse_blocks(path, options)
        apply_captions(layout_blocks, doc_id=doc_id, sensitivity=catalog[doc_id]["sensitivity"], mode=captions)
        texts = {
            "naive": "\n\n".join(b.text for b in naive_blocks if b.text),
            "layout": "\n\n".join(b.text for b in layout_blocks if b.text),
        }
        for parser, text in texts.items():
            (out_dir / f"{doc_id}.{parser}.txt").write_text(text, encoding="utf-8")

        doc_quotes = quotes.get(doc_id, [])
        text_quotes = [loc for qtype, loc in doc_quotes if qtype != "figure"]
        figure_quotes = [loc for qtype, loc in doc_quotes if qtype == "figure"]
        n_figure = len(figure_quotes)
        fig_found = sum(matches(texts["layout"], loc) for loc in figure_quotes)
        totals["fig"] += fig_found
        totals["n_fig"] += n_figure
        survived = {p: sum(matches(t, loc) for loc in text_quotes) for p, t in texts.items()}
        n = len(text_quotes)
        totals["naive"] += survived["naive"]
        totals["layout"] += survived["layout"]
        totals["n"] += n
        n_tables = sum(b.type == "table" for b in layout_blocks)
        n_figs = sum(b.type == "figure_caption" for b in layout_blocks)
        secs = "cache" if info["cache_hit"] else f"{info['seconds']:.1f}"
        exact, n_rows = _table_row_accuracy(texts["layout"], doc_id)
        rows = f"{exact}/{n_rows}" if n_rows else "-"
        skew = ",".join(f"{a:+.1f}" for a in info["skew_angles"]) if info.get("skew_angles") else "-"
        print(f"{doc_id:28s} {survived['naive']:>3d}/{n:<2d} {survived['layout']:>4d}/{n:<2d}  "
              f"{f'{fig_found}/{n_figure}' if n_figure else '-':>6s}  {secs:>5s}  {n_tables:>6d}  {n_figs:>7d}  {rows:>16s}  {skew}")
        for loc in text_quotes:
            if not matches(texts["layout"], loc):
                print(f"    lost by layout: {loc.match}: {loc.quote!r}")
    print(f"\nnon-figure quote survival: naive {totals['naive']}/{totals['n']}, "
          f"layout {totals['layout']}/{totals['n']}")
    print(f"figure quote survival (captions {captions}): {totals['fig']}/{totals['n_fig']}")
    print(f"parsed text written to {out_dir.relative_to(LAB_DIR)}/<doc_id>.<parser>.txt")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--spike", action="store_true", help="parse the 5 hard PDFs and print quote survival")
    ap.add_argument("--ocr-engine", choices=["ocrmac", "rapidocr"], default=DEFAULT_OPTIONS["ocr_engine"])
    ap.add_argument("--images-scale", type=float, default=DEFAULT_OPTIONS["images_scale"])
    ap.add_argument("--no-deskew", action="store_true", help="skip straightening image-only scans")
    ap.add_argument("--captions", choices=["off", "online", "offline"], default="off",
                    help="fill figure blocks from the caption cache (online may call the API)")
    args = ap.parse_args()
    if not args.spike:
        ap.print_help()
        sys.exit(1)
    run_spike({"ocr_engine": args.ocr_engine, "images_scale": args.images_scale, "deskew": not args.no_deskew},
              captions=args.captions)
