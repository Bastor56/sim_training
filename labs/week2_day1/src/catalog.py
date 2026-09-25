"""Source catalog: the stand-in for Harbor's document management system.

Tenant, sensitivity, version and effective date come from here, never from
guessing at a document's text (spec.md "Source catalog"). The pipeline never
reads the dataset's _answer_key/.
"""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path

from config import SOURCE_CATALOG_PATH
from models import Decision, Document

CATALOG_FIELDS = ("title", "tenant", "sensitivity", "version", "effective_date", "superseded_by")


def load_catalog(path: Path = SOURCE_CATALOG_PATH) -> dict[str, dict[str, str]]:
    """filename -> catalog row."""
    with open(path, encoding="utf-8", newline="") as f:
        return {row["filename"]: row for row in csv.DictReader(f)}


def new_document(path: Path, catalog: dict[str, dict[str, str]], parser: str) -> Document:
    """An empty, pending Document for one corpus file, with its catalog metadata.

    A file missing from the catalog gets a placeholder doc_id; the load
    stage quarantines it ("unknown provenance") rather than guessing labels.
    """
    from loaders import file_format

    row = catalog.get(path.name)
    return Document(
        doc_id=row["doc_id"] if row else f"uncatalogued::{path.name}",
        source_filename=path.name,
        source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        format=file_format(path),
        catalog={k: row[k] for k in CATALOG_FIELDS} if row else {},
        parser=parser,
        decision=Decision(),
    )
