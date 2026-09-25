"""CLI: run the ingestion pipeline for one or both parsers.

    uv run python src/ingest.py --parser layout --stop-after dedupe
    uv run python src/ingest.py --parser all --chunker all

Writes runs/<timestamp>_<parser>/decisions.csv (one row per corpus file,
with its decision and reason), documents.jsonl (the documents as they left
the last stage) and config.json (params, cache keys, model revisions,
corpus hashes, package versions). Stages whose inputs and params haven't
changed are read from cache/stages/ instead of recomputed.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter

from pipeline import STAGES, run_ingestion


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--parser", choices=["naive", "layout", "all"], default="layout")
    ap.add_argument("--chunker", choices=["A_fixed", "B_structure", "all"], default="B_structure")
    ap.add_argument("--stop-after", choices=STAGES, default=STAGES[-1])
    ap.add_argument("--from-stage", choices=STAGES, help="recompute this stage and later ones, ignoring the cache")
    ap.add_argument("--captions", choices=["offline", "online", "off"], default="offline",
                    help="figure captions: offline = cache only (default, no API calls)")
    args = ap.parse_args()

    parsers = ["naive", "layout"] if args.parser == "all" else [args.parser]
    chunkers = ["A_fixed", "B_structure"] if args.chunker == "all" else [args.chunker]
    for parser, chunker in ((p, c) for p in parsers for c in chunkers):
        docs, run_dir = run_ingestion(parser, chunker, args.stop_after, captions=args.captions,
                                      from_stage=args.from_stage)
        config = json.loads((run_dir / "config.json").read_text())
        for s in config["stages"]:
            print(f"  {s['stage']:7s} {'cache hit' if s['cache_hit'] else 'computed ':9s} {s['seconds']:6.2f}s  "
                  f"key {s['cache_key'][:12]}")
        counts = Counter(d.decision.status for d in docs)
        summary = " | ".join(f"{s} {counts[s]}" for s in ("cleaned", "dropped", "quarantined") if counts[s])
        chunk_stage = next((s for s in config["stages"] if s["stage"] == "chunk"), None)
        if chunk_stage:
            lengths = [len(json.loads(line)["text"]) for line in open(run_dir / "chunks.jsonl", encoding="utf-8")]
            summary += f" | {len(lengths)} chunks, mean {sum(lengths) / len(lengths):.0f} / max {max(lengths)} chars"
        print(f"[{parser} / {chunker}] {len(docs)} files | {summary}  ->  {run_dir.name}/")


if __name__ == "__main__":
    main()
