"""The ingestion pipeline's stages and the decision log (spec.md "Stage interface").

Rules every stage follows:
  1. Documents are never removed from the list. A stage that rejects a
     document sets its Decision (with a reason) and passes it on; later
     stages skip anything that isn't active. So the decision log is simply
     the final list, and nothing can be skipped silently.
  2. A stage's output depends only on its input documents and its params.
  3. Each stage's output is cached at cache/stages/<stage>/<cache key>.jsonl,
     so a rerun only recomputes the stages whose inputs or params changed.

Stages (milestone 10): load -> clean -> dedupe -> scrub -> chunk -> embed -> index.
The chunk stage turns Documents into Chunks; every kept document must yield at least one.
The index stage writes a Chroma collection and a BM25 pickle, each tagged with its cache key.
"""

from __future__ import annotations

import copy
import csv
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from captioning import apply_captions
from catalog import load_catalog, new_document
from cleaning import clean_document
from config import CAPTION_CACHE_DIR, CORPUS_DIR, DEFAULT_PARAMS, INDEX_DIR, RUNS_DIR, STAGE_CACHE_DIR, load_manifest
from dedupe import drop_exact_duplicates, drop_near_duplicates
from loaders import LoadError, load_blocks
from chunking import make_chunker
from embedding import embed_passages, embedding_identity
from index import BM25Index, ChromaIndex, collection_name
from models import Chunk, Decision, Document, read_jsonl, write_jsonl
from pii import scrub_document

STAGES = ["load", "clean", "dedupe", "scrub", "chunk", "embed", "index"]


def stage_load(parser: str, captions: str = "offline", corpus_dir: Path = CORPUS_DIR) -> list[Document]:
    """Decision rules 1-5: no catalog entry, empty file, exact duplicate,
    unreadable file, and (naive parser only) pages with no text layer.

    Figures found by the layout parser are captioned here (cache-first;
    "offline" never calls the API and fails on a cache miss)."""
    catalog = load_catalog()
    docs = [new_document(path, catalog, parser) for path in sorted(corpus_dir.iterdir()) if path.is_file()]
    for doc in docs:
        path = corpus_dir / doc.source_filename
        if not doc.catalog:  # rule 1
            doc.decision = Decision("quarantined", "unknown provenance: no catalog entry", "load")
        elif path.stat().st_size == 0:  # rule 2
            doc.decision = Decision("dropped", "empty file (0 bytes)", "load", {"bytes": 0})
    drop_exact_duplicates(docs)  # rule 3, before parsing: a copy costs nothing
    for doc in docs:
        if not doc.decision.is_active:
            continue
        try:
            doc.blocks, info = load_blocks(corpus_dir / doc.source_filename, parser)
        except LoadError as exc:  # rule 4
            doc.decision = Decision("quarantined", f"{exc}; route to manual review", "parse")
            continue
        # Runtime bookkeeping (was the parse cached? how long did it take?) isn't
        # document content: keeping it would make identical runs differ byte-wise.
        doc.decision.details["load"] = {k: v for k, v in info.items() if k not in ("cache_hit", "seconds")}
        apply_captions(doc.blocks, doc_id=doc.doc_id, sensitivity=doc.catalog["sensitivity"], mode=captions)
        doc.rebuild_text()
        doc.history.append(f"load:{parser}")
        if info.get("pages_without_text"):  # rule 5 (naive parser only)
            doc.decision = Decision(
                "quarantined",
                f"no text layer on {info['pages_without_text']} of {info['pages']} pages; needs OCR (naive parser)",
                "parse", doc.decision.details,
            )
    return docs


def stage_clean(docs: list[Document], params: dict) -> list[Document]:
    """Rules 6 and 8: dropped as near-empty, or cleaned with the fixes listed."""
    for doc in docs:
        if doc.decision.is_active:
            clean_document(doc, params)
            doc.history.append("clean")
    return docs


def stage_dedupe(docs: list[Document], params: dict) -> list[Document]:
    """Rule 7: near-duplicates of an earlier-kept document."""
    pairs = drop_near_duplicates(docs, params)
    for doc in docs:
        if doc.decision.is_active:
            doc.history.append("dedupe")
            # Record the closest other document, so "why wasn't this a duplicate?" has an answer.
            closest = next(((a if b == doc.doc_id else b, s) for a, b, s in pairs if doc.doc_id in (a, b)), None)
            if closest:
                doc.decision.details["closest_doc"] = {"doc_id": closest[0], "jaccard": closest[1]}
    return docs


def stage_scrub(docs: list[Document], params: dict) -> list[Document]:
    """Redact PII in every kept document, whatever its sensitivity label, before chunking."""
    for doc in docs:
        if doc.decision.is_active:
            scrub_document(doc, params)
            doc.history.append("scrub")
    return docs


def stage_embed(chunks: list[Chunk], params: dict) -> list[Chunk]:
    """Embed every chunk (scrubbed text only: this runs after the scrub stage)."""
    vectors = embed_passages([c.text for c in chunks], params)
    identity = embedding_identity()
    for chunk, vector in zip(chunks, vectors):
        chunk.embedding = vector
        chunk.metadata.update(identity)
    return chunks


def stage_index(chunks: list[Chunk], params: dict, key: str, index_dir: Path = INDEX_DIR) -> list[Chunk]:
    """(Re)build the Chroma collection and the BM25 index for this parser x chunker."""
    vector = ChromaIndex(params["name"], path=index_dir / "chroma")
    vector.create(cache_key=key)
    vector.add(chunks)
    BM25Index(params["name"], path=index_dir / "bm25", params=params["bm25"]).build(chunks, cache_key=key)
    return chunks


def index_is_current(params: dict, key: str, index_dir: Path = INDEX_DIR) -> bool:
    return (ChromaIndex(params["name"], path=index_dir / "chroma").cache_key() == key
            and BM25Index(params["name"], path=index_dir / "bm25", params=params["bm25"]).cache_key() == key)


def write_decision_log(docs: list[Document], run_dir: Path) -> Path:
    path = run_dir / "decisions.csv"
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["filename", "doc_id", "parser", "status", "stage", "reason"])
        for doc in sorted(docs, key=lambda d: d.source_filename):
            writer.writerow([doc.source_filename, doc.doc_id, doc.parser, doc.decision.status,
                             doc.decision.stage, doc.decision.reason])
    return path


# Bump a stage's version when its code changes what it outputs: that changes
# its cache key (and every later stage's), so stale cached output is never reused.
STAGE_VERSIONS = {"load": "2", "clean": "1", "dedupe": "1", "scrub": "1", "chunk": "1", "embed": "1", "index": "1"}  # load 2: no runtime fields


def corpus_fingerprint(corpus_dir: Path = CORPUS_DIR) -> str:
    """Hash of every corpus file's name and bytes: any edit to the corpus changes it."""
    h = hashlib.sha256()
    for path in sorted(corpus_dir.iterdir()):
        if path.is_file():
            h.update(path.name.encode() + b"\0" + hashlib.sha256(path.read_bytes()).digest())
    return h.hexdigest()


def cache_key(stage: str, params: dict, input_key: str) -> str:
    """sha256(stage + version + sorted params + the previous stage's key).

    Chaining the keys means a change anywhere upstream changes every key
    after it, while a change to one stage leaves the earlier keys (and
    their cached output) untouched.
    """
    blob = json.dumps({"stage": stage, "version": STAGE_VERSIONS[stage], "params": params, "input": input_key},
                      sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def _stage_plan(parser: str, captions: str, chunker: str, params: dict) -> list[tuple[str, dict, Callable]]:
    """(stage name, params that affect its output, function) in pipeline order."""
    import parse_pdf_layout

    load_params = {
        "parser": parser,
        "caption": params["caption"],
        # What the layout parser and captioner would produce is part of the load output.
        "layout_parser_version": parse_pdf_layout.PARSER_VERSION,
        "layout_options": parse_pdf_layout.DEFAULT_OPTIONS,
        "captions_cached": sorted(p.name for p in CAPTION_CACHE_DIR.glob("*.json")),
    }
    return [
        ("load", load_params, lambda docs, p: stage_load(parser, captions)),
        ("clean", params["clean"], stage_clean),
        ("dedupe", params["dedupe"], stage_dedupe),
        ("scrub", params["scrub"], stage_scrub),
        ("chunk", {"chunker": chunker, **params[chunker]}, lambda docs, p: make_chunker(chunker, params[chunker]).chunk(docs)),
        ("embed", {**params["embed"], **embedding_identity()}, stage_embed),
        ("index", {"name": collection_name(parser, chunker), "bm25": params["bm25"]}, stage_index),
    ]


CHUNK_STAGES = ("chunk", "embed", "index")  # stages whose output is chunks, not documents


def _pip_freeze() -> list[str]:
    try:
        out = subprocess.run(["uv", "pip", "freeze", "--python", sys.executable],
                             capture_output=True, text=True, timeout=60, check=True).stdout
        return out.splitlines()
    except (OSError, subprocess.SubprocessError):
        return ["(uv pip freeze unavailable)"]


def run_ingestion(
    parser: str,
    chunker: str = "B_structure",
    stop_after: str = STAGES[-1],
    captions: str = "offline",
    run_dir: Path | None = None,
    params: dict | None = None,
    from_stage: str | None = None,
    cache_dir: Path = STAGE_CACHE_DIR,
    index_dir: Path = INDEX_DIR,
) -> tuple[list[Document], Path]:
    """Run the stages in order, reusing cached output wherever the cache key matches.

    from_stage: recompute this stage and everything after it, even on a cache hit.
    Writes decisions.csv, documents.jsonl, chunks.jsonl and config.json to the run folder.
    """
    params = copy.deepcopy(params or DEFAULT_PARAMS)
    run_dir = run_dir or RUNS_DIR / f"{datetime.now():%Y%m%d-%H%M%S}_{parser}_{chunker}"
    run_dir.mkdir(parents=True, exist_ok=True)
    force_from = STAGES.index(from_stage) if from_stage else len(STAGES)

    docs: list[Document] = []
    chunks: list[Chunk] = []
    input_key = corpus_fingerprint()
    stage_log = []
    for i, (name, stage_params, fn) in enumerate(_stage_plan(parser, captions, chunker, params)):
        if i > STAGES.index(stop_after):
            break
        key = cache_key(name, stage_params, input_key)
        cache_file = cache_dir / name / f"{key}.jsonl"
        started = time.perf_counter()
        if name == "index":
            hit = index_is_current(stage_params, key, index_dir) and i < force_from
            if not hit:
                chunks = fn(chunks, stage_params, key, index_dir)
        else:
            hit = cache_file.exists() and i < force_from
        if name == "index":
            pass
        elif hit and name in CHUNK_STAGES:
            chunks = read_jsonl(cache_file, Chunk)
        elif name == "embed":
            chunks = fn(chunks, stage_params)
            write_jsonl(cache_file, chunks)
        elif hit:
            docs = read_jsonl(cache_file, Document)
        elif name == "chunk":
            chunks = fn(docs, stage_params)
            chunked = {c.metadata["doc_id"] for c in chunks}
            missing = [d.doc_id for d in docs if d.decision.is_active and d.doc_id not in chunked]
            if missing:  # a kept document with no chunks would be a silent skip
                raise RuntimeError(f"no chunks produced for: {missing}")
            write_jsonl(cache_file, chunks)
        else:
            n_in = len(docs)
            docs = fn(docs, stage_params)
            if name != "load" and len(docs) != n_in:  # rule 1: never drop a document from the list
                raise RuntimeError(f"stage {name} changed the document count ({n_in} -> {len(docs)})")
            write_jsonl(cache_file, docs)
        stage_log.append({"stage": name, "cache_key": key, "cache_hit": hit, "documents": len(docs),
                          **({"chunks": len(chunks)} if name in CHUNK_STAGES else {}),
                          "seconds": round(time.perf_counter() - started, 2)})
        input_key = key

    # A decision still "pending" here means a stage forgot to decide: fail loudly.
    undecided = [d.source_filename for d in docs if d.decision.status == "pending" and stop_after != "load"]
    if undecided:
        raise RuntimeError(f"documents with no decision: {undecided}")
    write_jsonl(run_dir / "documents.jsonl", docs)
    write_decision_log(docs, run_dir)
    if chunks:
        # The run folder keeps chunk text + metadata; vectors live in the stage cache and Chroma.
        write_jsonl(run_dir / "chunks.jsonl", [Chunk(c.chunk_id, c.text, c.metadata) for c in chunks])
    config = {
        "parser": parser,
        "chunker": chunker,
        "captions_mode": captions,
        "stop_after": stop_after,
        "from_stage": from_stage,
        "stages": stage_log,
        "params": params,
        "corpus_fingerprint": corpus_fingerprint(),
        "corpus_files": {d.source_filename: d.source_sha256 for d in docs},
        "models": load_manifest()["models"],
        "packages": _pip_freeze(),
    }
    (run_dir / "config.json").write_text(json.dumps(config, indent=2, default=str), encoding="utf-8")
    return docs, run_dir
