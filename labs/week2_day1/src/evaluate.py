"""Retrieval eval: precision@k and recall@k on the golden set, for one config or the whole matrix.

    uv run python src/evaluate.py --parser layout --chunker B_structure --mode hybrid_rerank
    uv run python src/evaluate.py --matrix
    uv run python src/evaluate.py --matrix --check-repro

What gets scored (spec.md "Eval methodology"):
  - 41 queries: all 45 except the 3 unanswerable ones and q003 (restricted).
  - Each query runs with its own tenant, restricted docs excluded, superseded
    docs excluded (row 17 switches that last filter off).
  - Every row also runs the safety checks: q003 must not leak the restricted
    fraud doc, but must find it when restricted access is allowed
    ("clearance"); no wrong-tenant, restricted or superseded chunk may appear
    in any top 10.

Before scoring, the ingestion pipeline is re-run for each parser x chunker
with captions offline. It's all cache hits when nothing changed, and it
guarantees the indexes match the current code and data. The eval makes no
network calls.

Output in runs/<timestamp>_eval/: results.json (metrics, byte-stable),
results.md, per_query.csv, timings.json (latency, kept out of
results.json because wall-clock time never repeats exactly).
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from datetime import datetime
from pathlib import Path

from config import DEFAULT_PARAMS, RUNS_DIR
from golden import GoldenSet, load_golden_set, relevant_items
from metrics import aggregate, leak_counts, recall_at_k, score_query
from pipeline import run_ingestion
from retrieval import MODES, Retriever

PARSERS = ("naive", "layout")
CHUNKERS = ("A_fixed", "B_structure")
K_VALUES = DEFAULT_PARAMS["eval"]["k_values"]
TOP_K = max(K_VALUES)
RESTRICTED_QUERY = "q003"


def _pct(values: list[float], q: float) -> float:
    values = sorted(values)
    return values[min(len(values) - 1, int(round(q * (len(values) - 1))))]


def evaluate_config(retriever: Retriever, golden: GoldenSet, parser: str, chunker: str, mode: str,
                    current_only: bool = True) -> tuple[dict, list[dict], dict]:
    """Score one matrix row. Returns (row summary, per-query rows, latency samples)."""
    scores, per_query, leaks, latency = [], [], {"restricted": 0, "wrong_tenant": 0, "superseded": 0}, {}
    top1_answerable, top1_unanswerable = [], {}
    for q in golden.queries:
        if q.id == RESTRICTED_QUERY:
            continue
        response = retriever.search(q.query, mode, tenant=q.tenant, current_only=current_only, top_k=TOP_K)
        for stage, ms in response.timings_ms.items():
            latency.setdefault(stage, []).append(ms)
        results = [(r.metadata["doc_id"], r.text) for r in response.results]
        for kind, n in leak_counts([r.metadata for r in response.results], q.tenant).items():
            leaks[kind] += n
        top1 = response.results[0].score if response.results else None
        if q.is_unanswerable:
            top1_unanswerable[q.id] = top1
            continue
        top1_answerable.append(top1)
        s = score_query(q, results, K_VALUES)
        scores.append(s)
        per_query.append({"query_id": q.id, "type": q.type, "n_items": s.n_items,
                          **{f"R@{k}": s.recall[k] for k in K_VALUES},
                          **{f"P@{k}": s.precision[k] for k in K_VALUES},
                          "top1": response.results[0].chunk_id if response.results else ""})

    # q003: the member-facing filter must hide the restricted doc...
    q003 = golden.by_id(RESTRICTED_QUERY)
    hidden = retriever.search(q003.query, mode, tenant=q003.tenant, current_only=current_only, top_k=TOP_K)
    leak_pass = not any(r.metadata["sensitivity"] == "restricted" for r in hidden.results)
    # ...and with clearance it must be found, proving the filter (not a missing doc) is what hid it.
    cleared = retriever.search(q003.query, mode, tenant=q003.tenant, allow_restricted=True, top_k=TOP_K)
    clearance_ok = recall_at_k([(r.metadata["doc_id"], r.text) for r in cleared.results],
                               relevant_items(q003), TOP_K) == 1.0

    summary = aggregate(scores)
    version_trap = summary["by_type"].get("version_trap", {})
    row = {
        "parser": parser, "chunker": chunker, "mode": mode, "superseded_filter": current_only,
        **{k: round(v, 4) for k, v in summary.items() if k != "by_type"},
        "by_type": {t: {k: round(v, 4) for k, v in m.items()} for t, m in summary["by_type"].items()},
        "q003_leak_check": "PASS" if leak_pass else "FAIL",
        "q003_clearance": "OK" if clearance_ok else "FAIL",
        "leaks": leaks,
        "version_trap_recall@5": round(version_trap.get("recall@5", 0.0), 4),
    }
    if mode == "hybrid_rerank":
        worst_unanswerable = max(v for v in top1_unanswerable.values() if v is not None)
        row["unanswerable"] = {
            "top1_rerank": {k: round(v, 4) for k, v in top1_unanswerable.items()},
            "answerable_top1_min": round(min(top1_answerable), 4),
            "answerable_top1_median": round(statistics.median(top1_answerable), 4),
            "answerable_below_best_unanswerable": sum(v < worst_unanswerable for v in top1_answerable),
        }
    return row, per_query, latency


def ensure_indexes(run_dir: Path, combos: list[tuple[str, str]], captions: str) -> None:
    for parser, chunker in combos:
        run_ingestion(parser, chunker, captions=captions, run_dir=run_dir / f"ingest_{parser}_{chunker}")


def run_matrix(golden: GoldenSet, combos: list[tuple[str, str]], modes: tuple[str, ...], with_row_17: bool):
    rows, per_query, timings = [], [], {}
    retrievers = {combo: Retriever(*combo) for combo in combos}
    for parser, chunker in combos:
        for mode in modes:
            row, pq, lat = evaluate_config(retrievers[(parser, chunker)], golden, parser, chunker, mode)
            row["row"] = len(rows) + 1
            rows.append(row)
            per_query.extend({"row": row["row"], **r} for r in pq)
            timings[row["row"]] = lat
            print(_console_line(row), flush=True)
    if with_row_17:
        best = max(rows, key=lambda r: (r["recall@5"], r["recall@10"], -r["row"]))
        row, pq, lat = evaluate_config(retrievers[(best["parser"], best["chunker"])], golden,
                                       best["parser"], best["chunker"], best["mode"], current_only=False)
        row["row"] = len(rows) + 1
        row["best_of"] = best["row"]
        rows.append(row)
        per_query.extend({"row": row["row"], **r} for r in pq)
        timings[row["row"]] = lat
        print(_console_line(row), flush=True)
    return rows, per_query, timings


# ---------------------------------------------------------------- output

HEADER = (f"{'row':>3} {'parser':6} {'chunker':11} {'mode':13} {'P@5':>5} {'P@10':>5} {'R@5':>5} {'R@10':>5}  "
          f"{'q003':4} {'clr':4} {'wrongT':>6} {'restr':>5} {'v2':>3}")


def _console_line(r: dict) -> str:
    line = (f"{r['row']:>3} {r['parser']:6} {r['chunker']:11} {r['mode']:13} {r['precision@5']:5.3f} "
            f"{r['precision@10']:5.3f} {r['recall@5']:5.3f} {r['recall@10']:5.3f}  {r['q003_leak_check']:4} "
            f"{r['q003_clearance']:4} {r['leaks']['wrong_tenant']:6d} {r['leaks']['restricted']:5d} "
            f"{r['leaks']['superseded']:3d}")
    if not r["superseded_filter"]:
        line += f"   <- row {r['best_of']} with the superseded filter OFF; version_trap R@5 {r['version_trap_recall@5']:.3f}"
    return line


def _latency_summary(timings: dict) -> dict:
    return {row: {stage: {"mean_ms": round(statistics.mean(v), 1), "p95_ms": round(_pct(v, 0.95), 1)}
                  for stage, v in stages.items()} for row, stages in timings.items()}


def _find(rows, parser, chunker, mode, current=True):
    return next((r for r in rows if (r["parser"], r["chunker"], r["mode"], r["superseded_filter"])
                 == (parser, chunker, mode, current)), None)


def write_markdown(rows: list[dict], latency: dict, path: Path, meta: dict) -> None:
    out = [f"# Retrieval eval results ({meta['run_id']})\n",
           f"Golden set v{meta['golden_version']} (corpus v{meta['corpus_version']}): {rows[0]['n_queries']} scored "
           f"queries. Filter: the query's own tenant, restricted excluded, superseded excluded (except row 17). "
           f"P@5 ceiling for single-item queries is 0.20; mean ceiling shown per row.\n",
           "\n## Matrix\n",
           "| Row | Parser | Chunker | Mode | P@5 | P@10 | R@5 | R@10 | P@5 ceiling | q003 leak | clearance | wrong tenant | restricted | superseded |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        mode = r["mode"] + ("" if r["superseded_filter"] else " (superseded filter OFF)")
        out.append(f"| {r['row']} | {r['parser']} | {r['chunker']} | {mode} | {r['precision@5']:.3f} | "
                   f"{r['precision@10']:.3f} | {r['recall@5']:.3f} | {r['recall@10']:.3f} | "
                   f"{r['precision_ceiling@5']:.3f} | {r['q003_leak_check']} | {r['q003_clearance']} | "
                   f"{r['leaks']['wrong_tenant']} | {r['leaks']['restricted']} | {r['leaks']['superseded']} |")

    def compare(title, pairs):
        out.extend([f"\n## {title}\n", "| Config | R@5 | R@10 | P@5 | mean latency (ms) |", "|---|---|---|---|---|"])
        for label, r in pairs:
            if r:
                total = latency[r["row"]].get("total", {}).get("mean_ms", 0)
                out.append(f"| {label} | {r['recall@5']:.3f} | {r['recall@10']:.3f} | {r['precision@5']:.3f} | {total} |")

    compare("Before/after 1: parsing (B_structure, hybrid_rerank)",
            [("naive", _find(rows, "naive", "B_structure", "hybrid_rerank")),
             ("layout-aware", _find(rows, "layout", "B_structure", "hybrid_rerank"))])
    compare("Before/after 2: chunking (layout, hybrid_rerank)",
            [("A_fixed", _find(rows, "layout", "A_fixed", "hybrid_rerank")),
             ("B_structure", _find(rows, "layout", "B_structure", "hybrid_rerank"))])
    compare("Before/after 3: retrieval stages (layout, B_structure)",
            [(m, _find(rows, "layout", "B_structure", m)) for m in MODES])

    types = sorted({t for r in rows for t in r["by_type"]})
    out.extend(["\n## Recall@5 by query type (hybrid_rerank rows)\n",
                "| Type | n | " + " | ".join(f"{r['parser']}/{r['chunker']}" for r in rows
                                             if r["mode"] == "hybrid_rerank" and r["superseded_filter"]) + " |",
                "|---|---|" + "---|" * sum(1 for r in rows if r["mode"] == "hybrid_rerank" and r["superseded_filter"])])
    for t in types:
        cells = [r["by_type"].get(t, {}) for r in rows if r["mode"] == "hybrid_rerank" and r["superseded_filter"]]
        n = next((c["n_queries"] for c in cells if c), 0)
        out.append(f"| {t} | {n} | " + " | ".join(f"{c.get('recall@5', 0):.2f}" for c in cells) + " |")

    out.extend(["\n## Unanswerable queries (hybrid_rerank: top-1 rerank score)\n",
                "| Row | q043 | q044 | q045 | answerable top-1 min | answerable top-1 median | answerable below the best unanswerable |",
                "|---|---|---|---|---|---|---|"])
    for r in rows:
        u = r.get("unanswerable")
        if u and r["superseded_filter"]:
            t = u["top1_rerank"]
            out.append(f"| {r['row']} | {t.get('q043')} | {t.get('q044')} | {t.get('q045')} | "
                       f"{u['answerable_top1_min']} | {u['answerable_top1_median']} | "
                       f"{u['answerable_below_best_unanswerable']} |")

    out.extend(["\n## Latency per stage (mean / p95 ms per query, CPU)\n",
                "| Row | Mode | BM25 | Vector | Fusion | Rerank | Total |", "|---|---|---|---|---|---|---|"])
    for r in rows:
        lat = latency[r["row"]]
        cell = lambda s: f"{lat[s]['mean_ms']} / {lat[s]['p95_ms']}" if s in lat else "-"
        out.append(f"| {r['row']} | {r['mode']} | {cell('bm25')} | {cell('vector')} | {cell('fusion')} | "
                   f"{cell('rerank')} | {cell('total')} |")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def evaluate(combos, modes, with_row_17: bool, captions: str, run_dir: Path) -> dict:
    if captions != "offline":
        sys.exit("the eval only runs with --captions offline: it must never call the API")
    run_dir.mkdir(parents=True, exist_ok=True)
    golden = load_golden_set()
    ensure_indexes(run_dir, combos, captions)
    print(HEADER)
    rows, per_query, timings = run_matrix(golden, combos, modes, with_row_17)
    results = {"golden_version": golden.version, "corpus_version": golden.corpus_version,
               "k_values": K_VALUES, "rows": rows}
    (run_dir / "results.json").write_text(json.dumps(results, indent=2, sort_keys=True), encoding="utf-8")
    latency = _latency_summary(timings)
    (run_dir / "timings.json").write_text(json.dumps(latency, indent=2, sort_keys=True), encoding="utf-8")
    with open(run_dir / "per_query.csv", "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(per_query[0]))
        writer.writeheader()
        writer.writerows(per_query)
    write_markdown(rows, latency, run_dir / "results.md",
                   {"run_id": run_dir.name, "golden_version": golden.version, "corpus_version": golden.corpus_version})
    ceiling = rows[0]["precision_ceiling@5"]
    print(f"mean P@5 ceiling over the scored queries: {ceiling:.3f} (0.20 for a single-item query)")
    print(f"-> {run_dir.relative_to(RUNS_DIR.parent)}/results.md")
    return results


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--matrix", action="store_true", help="all 16 rows plus row 17 (superseded filter off)")
    ap.add_argument("--check-repro", action="store_true", help="run twice and require identical results.json")
    ap.add_argument("--parser", choices=PARSERS, default="layout")
    ap.add_argument("--chunker", choices=CHUNKERS, default="B_structure")
    ap.add_argument("--mode", choices=MODES, default="hybrid_rerank")
    ap.add_argument("--captions", default="offline")
    args = ap.parse_args()

    if args.matrix:
        combos, modes, row_17 = [(p, c) for p in PARSERS for c in CHUNKERS], MODES, True
    else:
        combos, modes, row_17 = [(args.parser, args.chunker)], (args.mode,), False
    stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
    first = evaluate(combos, modes, row_17, args.captions, RUNS_DIR / f"{stamp}_eval")
    if args.check_repro:
        print("\n-- second run for --check-repro --")
        second = evaluate(combos, modes, row_17, args.captions, RUNS_DIR / f"{stamp}_eval_repro")
        if json.dumps(first, sort_keys=True) != json.dumps(second, sort_keys=True):
            sys.exit("NOT reproducible: results.json differs between the two runs")
        print(f"reproducible: results identical ({len(first['rows'])} rows)")


if __name__ == "__main__":
    main()
