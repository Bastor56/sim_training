"""The data shapes every pipeline stage passes around (spec.md "Data shapes").

All plain dataclasses that round-trip through JSON, so any stage's output can
be cached to disk, opened in an editor, and fed to the next stage later.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Literal

DecisionStatus = Literal["cleaned", "quarantined", "dropped", "pending"]
BlockType = Literal["heading", "paragraph", "list_item", "table", "figure_caption"]
ParserName = Literal["naive", "layout"]


@dataclass
class Decision:
    status: DecisionStatus = "pending"
    reason: str = ""
    stage: str = ""  # which stage decided: "load", "parse", "clean", "dedupe"
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in ("cleaned", "quarantined", "dropped", "pending"):
            raise ValueError(f"unknown decision status {self.status!r}")
        # "Never a silent skip": rejecting a document requires saying why.
        if self.status in ("quarantined", "dropped") and not self.reason:
            raise ValueError(f"a {self.status} decision needs a reason")

    @property
    def is_active(self) -> bool:
        """True if later stages should keep processing this document."""
        return self.status in ("pending", "cleaned")


@dataclass
class Block:
    type: BlockType
    text: str  # tables: one row per line, cells joined by " | "
    level: int | None = None  # heading level, 1 = title
    page: int | None = None  # 1-based, when the source has pages
    section_path: list[str] = field(default_factory=list)
    generated: bool = False  # True only for model-written captions
    image_ref: str = ""  # figures only: PNG crop (relative to the lab dir) sent for captioning
    figure_label: str = ""  # figures only: the printed "Figure N. ..." caption the parser linked to it
    source_hint: str = ""  # where the block came from, e.g. HTML "footer.site-footer > p.legal"; cleaning uses it

    @classmethod
    def from_dict(cls, d: dict) -> Block:
        return cls(**d)


@dataclass
class Document:
    doc_id: str
    source_filename: str
    source_sha256: str
    format: str  # "pdf", "docx", "md", "html", "txt", "rtf", "eml", "csv"
    catalog: dict[str, str]  # title, tenant, sensitivity, version, effective_date, superseded_by
    parser: ParserName = "layout"
    blocks: list[Block] = field(default_factory=list)
    text: str = ""  # blocks joined with "\n\n"; char offsets refer to this string
    decision: Decision = field(default_factory=Decision)
    history: list[str] = field(default_factory=list)
    pii_spans: list[dict] = field(default_factory=list)  # {type, start, end, value_sha256}

    def rebuild_text(self) -> None:
        """Recompute `text` from `blocks`, after a stage edits the blocks.

        Blocks with no text yet (a figure awaiting its caption) are skipped.
        """
        self.text = "\n\n".join(b.text for b in self.blocks if b.text)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Document:
        d = dict(d)
        d["blocks"] = [Block.from_dict(b) for b in d.get("blocks", [])]
        d["decision"] = Decision(**d.get("decision", {}))
        return cls(**d)


@dataclass
class Chunk:
    chunk_id: str  # "{doc_id}::{parser}::{chunker}::{index:04d}"
    text: str  # what gets embedded, BM25-indexed and matched against golden quotes
    metadata: dict[str, str | int | float | bool]
    embedding: list[float] | None = None

    @staticmethod
    def make_id(doc_id: str, parser: str, chunker: str, index: int) -> str:
        return f"{doc_id}::{parser}::{chunker}::{index:04d}"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Chunk:
        return cls(**d)


def write_jsonl(path: str | Path, items: Iterable[Document | Chunk]) -> None:
    """One JSON object per line; sorted keys so identical data gives identical bytes."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item.to_dict(), ensure_ascii=False, sort_keys=True))
            f.write("\n")


def read_jsonl(path: str | Path, cls: type[Document] | type[Chunk]) -> list:
    with open(path, encoding="utf-8") as f:
        return [cls.from_dict(json.loads(line)) for line in f if line.strip()]
