"""Grade an ingestion run against the answer key. The ONLY code that reads _answer_key/.

    uv run python src/grade_ingestion.py --run latest            # newest layout run
    uv run python src/grade_ingestion.py --run latest --parser naive

Two reports:
  decisions      each file's status vs _answer_key/ingestion_expectations.csv;
                 for duplicates the reason must also name the right canonical doc.
                 A naive run is expected to quarantine the 4 scanned PDFs
                 ("no text layer"); those count as expected differences.
  quote survival every golden quote checked against its document's full cleaned
                 text, before chunking. A quote lost here can never be
                 retrieved, so this separates "parsing lost it" from
                 "retrieval missed it".
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

from config import ANSWER_KEY_DIR, RUNS_DIR
from golden import load_golden_set, matches
from models import Document, read_jsonl


def find_run(run: str, parser: str) -> Path:
    if run != "latest":
        return RUNS_DIR / run
    runs = sorted(p for p in RUNS_DIR.glob(f"*_{parser}*") if (p / "decisions.csv").exists())
    if not runs:
        sys.exit(f"no {parser} run found under {RUNS_DIR}; run src/ingest.py first")
    return runs[-1]


def grade_decisions(run_dir: Path) -> dict:
    with open(run_dir / "decisions.csv", encoding="utf-8", newline="") as f:
        actual = {r["filename"]: r for r in csv.DictReader(f)}
    with open(ANSWER_KEY_DIR / "ingestion_expectations.csv", encoding="utf-8", newline="") as f:
        expected = {r["filename"]: r for r in csv.DictReader(f)}
    doc_ids = {r["doc_id"] for r in expected.values()}

    rows, results = [], {"match": 0, "expected_difference": 0, "mismatch": 0}
    for filename in sorted(expected):
        exp, act = expected[filename], actual.get(filename)
        status = act["status"] if act else "MISSING"
        verdict = "OK" if status == exp["expected_decision"] else "MISMATCH"
        # A duplicate must be dropped *in favour of the right copy*.
        if verdict == "OK" and "duplicate" in exp["reason"].lower():
            canonical = [d for d in doc_ids if d != exp["doc_id"] and re.search(rf"\b{d}\b", exp["reason"])]
            if canonical and not re.search(rf"\b{canonical[0]}\b", act["reason"]):
                verdict = f"MISMATCH (should name {canonical[0]})"
        if (verdict != "OK" and act and act["parser"] == "naive" and exp["format"] == "pdf (scanned)"
                and status == "quarantined" and "no text layer" in act["reason"]):
            verdict = "EXPECTED (naive parser has no OCR)"
        key = "match" if verdict == "OK" else "expected_difference" if verdict.startswith("EXPECTED") else "mismatch"
        results[key] += 1
        rows.append((filename, status, act["reason"] if act else "", verdict))

    counts = {s: sum(r[1] == s for r in rows) for s in ("cleaned", "dropped", "quarantined")}
    print(f"decisions: {len(rows)} files | cleaned {counts['cleaned']} | dropped {counts['dropped']} | "
          f"quarantined {counts['quarantined']}")
    print(f"match vs answer key: {results['match']}/{len(rows)}"
          + (f"  (+{results['expected_difference']} expected differences)" if results["expected_difference"] else ""))
    for filename, status, reason, verdict in rows:
        print(f"  {filename[:44]:44s} {status:11s} {reason[:70]:70s} {verdict}")
    return {"files": len(rows), **counts, **results}


def quote_survival(run_dir: Path) -> dict:
    docs = {d.doc_id: d for d in read_jsonl(run_dir / "documents.jsonl", Document)}
    rows = []
    for q in load_golden_set().queries:
        for loc in q.expected:
            doc = docs.get(loc.doc_id)
            if doc is not None and "canonical_doc_id" in doc.decision.details:
                # A dropped duplicate: its canonical copy carries the same quote.
                state = f"n/a: duplicate of {doc.decision.details['canonical_doc_id']}"
            elif doc is None or not doc.decision.is_active:
                state = f"LOST (doc {doc.decision.status if doc else 'missing'})"
            else:
                state = "survived" if matches(doc.text, loc) else "LOST"
            rows.append({"query": q.id, "type": q.type, "doc_id": loc.doc_id, "quote": loc.quote, "state": state})
    scored = [r for r in rows if not r["state"].startswith("n/a")]
    survived = sum(r["state"] == "survived" for r in scored)
    print(f"\nquote survival ({run_dir.name}): {survived}/{len(scored)} "
          f"({len(rows) - len(scored)} quotes point at dropped duplicate copies; their canonical copy is counted)")
    for r in scored:
        if r["state"].startswith("LOST"):
            print(f"  {r['state']} {r['query']} [{r['type']}] {r['doc_id']}: {r['quote']!r}")
    (run_dir / "quote_survival.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return {"survived": survived, "scored": len(scored)}


def grade_pii(run_dir: Path) -> dict:
    """Recall per type vs the planted inventory, plus every other redaction for review.

    The run's scrub log holds only hashes, so to *show* a false positive the
    grader re-runs load + clean (a dev tool reading the corpus, printing to
    the terminal; nothing raw is written to disk).
    """
    import hashlib

    from config import DEFAULT_PARAMS
    from pipeline import stage_clean, stage_load

    docs = {d.doc_id: d for d in read_jsonl(run_dir / "documents.jsonl", Document)}
    with open(ANSWER_KEY_DIR / "pii_inventory.csv", encoding="utf-8", newline="") as f:
        inventory = list(csv.DictReader(f))

    by_type: dict[str, list[int]] = {}
    missed = []
    for row in inventory:
        doc = docs[row["doc_id"]]
        leaked = row["value"] in doc.text
        by_type.setdefault(row["pii_type"], []).append(0 if leaked else 1)
        if leaked:
            missed.append(row)
    print(f"\nPII recall vs inventory ({len(inventory)} planted values):")
    for pii_type, hits in sorted(by_type.items()):
        print(f"  {pii_type:8s} {sum(hits):3d}/{len(hits):<3d} {100 * sum(hits) / len(hits):5.1f}%")
    for row in missed:
        print(f"  MISSED {row['pii_type']} in {row['doc_id']}: {row['value']!r}")

    inventory_hashes = {hashlib.sha256(r["value"].encode("utf-8")).hexdigest() for r in inventory}
    raw = {d.doc_id: d for d in stage_clean(stage_load(docs[next(iter(docs))].parser), DEFAULT_PARAMS["clean"])}
    false_positives = []
    for doc_id, doc in sorted(docs.items()):
        for span in doc.pii_spans:
            if span["value_sha256"] in inventory_hashes:
                continue
            value = raw[doc_id].blocks[span["block"]].text[span["start"]:span["end"]]
            false_positives.append((doc_id, span["type"], value))
    print(f"\nredactions not in the inventory (review each: false positive, or real PII the inventory missed): "
          f"{len(false_positives)}")
    for doc_id, kind, value in false_positives:
        print(f"  {doc_id:28s} {kind:8s} {value!r}")
    total = sum(len(h) for h in by_type.values())
    return {"recall": {t: f"{sum(h)}/{len(h)}" for t, h in sorted(by_type.items())},
            "found": sum(sum(h) for h in by_type.values()), "planted": total,
            "not_in_inventory": len(false_positives)}


def main() -> None:
    ap = argparse.ArgumentParser(description="Grade an ingestion run.")
    ap.add_argument("--run", default="latest", help="run folder name under runs/, or 'latest'")
    ap.add_argument("--parser", choices=["naive", "layout"], default="layout", help="which run 'latest' means")
    ap.add_argument("--decisions", action="store_true", help="only the decision grading")
    ap.add_argument("--quotes", action="store_true", help="only the quote-survival table")
    ap.add_argument("--pii", action="store_true", help="only the PII scrubbing report")
    args = ap.parse_args()
    run_dir = find_run(args.run, args.parser)
    both = not (args.decisions or args.quotes or args.pii)
    grade = {}
    if args.decisions or both:
        grade["decisions"] = grade_decisions(run_dir)
    if args.quotes or both:
        grade["quote_survival"] = quote_survival(run_dir)
    scrubbed = any("scrub" in d.history for d in read_jsonl(run_dir / "documents.jsonl", Document))
    if (args.pii or both) and scrubbed:
        grade["pii"] = grade_pii(run_dir)
    (run_dir / "ingestion_grade.json").write_text(json.dumps(grade, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
