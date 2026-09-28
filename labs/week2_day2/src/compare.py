"""The three-model comparison, built only from recorded runs (plan.md milestone 11). No API calls.

    uv run python src/compare.py --runs runs/<A> runs/<B> runs/<C> \
        --warm runs/<A_warm> --repeat runs/<A_repeat> --sweep runs/<A_tau005> runs/<A_tau030>

Writes runs/compare_<timestamp>.md and .json. Every number the report quotes
should come from here (or the run folders it reads), never typed by hand.
"""

from __future__ import annotations

import argparse
import json
import statistics
from datetime import datetime
from pathlib import Path

import settings
from run_eval import percentile


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def load_run(run_dir: str) -> dict:
    d = Path(run_dir)
    config = json.loads((d / "config.json").read_text())
    return {"dir": d, "id": d.name, "config": config, "generator": config["args"]["generator"],
            "summary": json.loads((d / "summary.json").read_text()),
            "rows": _jsonl(d / "interactions.jsonl"), "grades": _jsonl(d / "grades.jsonl"),
            "calls": _jsonl(d / "calls.jsonl")}


def model_row(run: dict) -> dict:
    s, q = run["summary"], run["summary"]["quality"]
    rows = [r for r in run["rows"] if r["set"] in ("golden", "no_retrieval")]
    grades = {g["id"]: g for g in run["grades"]}
    successes = sum(grades[r["id"]]["task_success"] for r in rows)
    total_cost = sum(r["cost_usd"] for r in rows)
    gen_calls = [c for c in run["calls"] if c["purpose"] == "generate" and c["local_cache"] != "hit" and not c.get("error")]
    gen = settings.GENERATORS[run["generator"]]
    answerable = [g for g in grades.values() if g.get("outcome_expected") == "answered"]
    nic = [g for g in grades.values() if g.get("outcome_expected") == "not_in_corpus"]
    direct = [g for g in grades.values() if g.get("outcome_expected") == "answered_direct"]
    return {
        "generator": run["generator"],
        "model": gen["model"],
        "thinking": gen["thinking"] or "omitted (none)",
        "effort": gen["effort"],
        "max_tokens": gen["max_tokens"],
        "run_id": run["id"],
        "task_success": f"{successes}/{len(rows)}",
        "task_success_rate": round(successes / len(rows), 4),
        "judge_verdicts": q["judge_verdicts"],
        "judge_correct_of_answerable": f"{sum(g.get('judge_verdict') == 'correct' for g in answerable)}/{len(answerable)}",
        "citation_hit_of_answerable": f"{sum(bool(g.get('citation_hit')) for g in answerable)}/{len(answerable)}",
        "not_in_corpus_correct": f"{sum(g['outcome_correct'] for g in nic)}/{len(nic)}",
        "false_declines": q["not_in_corpus_false_declines"],
        "direct_correct": f"{sum(g['outcome_correct'] for g in direct)}/{len(direct)}",
        "gate_accuracy": q["gate_accuracy"],
        "version_quoted": q["version_quoted"],
        "version_in_prose": q["version_in_prose"],
        "leaks": q["leaks"],
        "source_line_violations": q["source_line_violations"],
        "cost_per_interaction_mean": s["cost_per_interaction"]["mean"],
        "cost_per_interaction_p95": s["cost_per_interaction"]["p95"],
        "cost_per_interaction_max": s["cost_per_interaction"]["max"],
        "cost_per_successful_interaction": round(total_cost / successes, 6) if successes else None,
        "interaction_cost_total_55": round(total_cost, 6),
        "latency_p50_ms": s["latency_ms"]["p50"],
        "latency_p95_ms": s["latency_ms"]["p95"],
        "llm_latency_ms_mean": s["llm_latency_ms_mean"],
        "retrieval_latency_ms_mean": s["local_latency_ms_mean"],
        "generate_output_tokens_mean": round(statistics.mean(c["output_tokens"] for c in gen_calls), 1) if gen_calls else None,
        "generate_input_tokens_mean": round(statistics.mean(c["input_tokens"] for c in gen_calls), 1) if gen_calls else None,
        "generate_latency_ms_p50": percentile([c["latency_ms"] for c in gen_calls], 0.5),
        "cost_by_purpose": s["cost_by_purpose_total"],
        "rounds_distribution": s["rounds_distribution"],
        "provider_cache_read_tokens": s["provider_cache_read_tokens"],
        "provider_cache_write_tokens": sum(c["cache_creation_input_tokens"] for c in run["calls"] if c["kind"] == "llm"),
        "fallback_calls": sum(bool(c.get("fallback_used")) for c in run["calls"] if c["kind"] == "llm"),
        "max_tokens_hits": sum("truncated" in (c.get("error") or "") for c in run["calls"]),
        "run_provider_spend": s["provider_spend_this_run"],
        "judge_spend": s["judge_spend_this_run"],
        "rewrite_helped": q["rewrite_helped"],
        "rescued_after_decline": q["rescued_after_decline"],
        "declined_rounds": q["declined_rounds"],
        "ungrounded_rounds": q["ungrounded_rounds"],
    }


def per_question(runs: list[dict]) -> list[dict]:
    """Every question that failed task_success on at least one model."""
    by_model = {r["generator"]: {g["id"]: g for g in r["grades"]} for r in runs}
    rows_by_model = {r["generator"]: {x["id"]: x for x in r["rows"]} for r in runs}
    ids = [g["id"] for g in runs[0]["grades"]]
    out = []
    for qid in ids:
        cells = {}
        for m, grades in by_model.items():
            g = grades[qid]
            cells[m] = "ok" if g["task_success"] else (g.get("judge_verdict") or rows_by_model[m][qid]["outcome"])
        if any(v != "ok" for v in cells.values()):
            out.append({"id": qid, "category": runs[0]["grades"][ids.index(qid)]["category"], **cells})
    return out


def extremes(run: dict, n: int = 5) -> dict:
    rows = sorted([r for r in run["rows"] if r["set"] in ("golden", "no_retrieval")], key=lambda r: r["cost_usd"])
    fmt = lambda r: {"id": r["id"], "cost_usd": r["cost_usd"], "rounds": r["rounds"], "llm_calls": r["llm_calls"],
                     "output_tokens": r["output_tokens"], "outcome": r["outcome"]}
    return {"most_expensive": [fmt(r) for r in rows[::-1][:n]], "cheapest": [fmt(r) for r in rows[:n]]}


def sweep_rows(runs: list[dict]) -> list[dict]:
    out = []
    for run in runs:
        s, q = run["summary"], run["summary"]["quality"]
        rows = [r for r in run["rows"] if r["set"] in ("golden", "no_retrieval")]
        out.append({"tau": run["config"]["tau_keep"], "run_id": run["id"],
                    "task_success": f"{q['task_success_count']}/{q['questions']}",
                    "judge_verdicts": q["judge_verdicts"], "false_declines": q["not_in_corpus_false_declines"],
                    "not_in_corpus_recall": q["not_in_corpus_recall"],
                    "rounds_distribution": s["rounds_distribution"],
                    "mean_rounds_retrieving": round(statistics.mean(r["rounds"] for r in rows if r["rounds"]), 3),
                    "cost_per_interaction_mean": s["cost_per_interaction"]["mean"],
                    "rewrite_helped": q["rewrite_helped"], "rescued_after_decline": q["rescued_after_decline"]})
    return sorted(out, key=lambda r: r["tau"])


def _table(rows: list[dict], cols: list[tuple[str, str]]) -> list[str]:
    lines = ["| " + " | ".join(h for h, _ in cols) + " |", "|" + "---|" * len(cols)]
    for r in rows:
        lines.append("| " + " | ".join(str(r.get(k, "")) for _, k in cols) + " |")
    return lines


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--runs", nargs=3, required=True, help="the cold runs for haiku, sonnet, opus")
    ap.add_argument("--warm", default="")
    ap.add_argument("--repeat", default="")
    ap.add_argument("--sweep", nargs="*", default=[])
    args = ap.parse_args()

    runs = [load_run(r) for r in args.runs]
    models = [model_row(r) for r in runs]
    result: dict = {"created": datetime.now().isoformat(timespec="seconds"), "models": models,
                    "per_question_failures": per_question(runs),
                    "extremes": {r["generator"]: extremes(r) for r in runs}}
    if args.warm:
        w = load_run(args.warm)["summary"]
        result["warm"] = {"run_id": Path(args.warm).name, "local_cache_hit_rate": w["local_cache_hit_rate"],
                          "cost_per_interaction_mean": w["cost_per_interaction"]["mean"],
                          "latency_p50_ms": w["latency_ms"]["p50"], "latency_p95_ms": w["latency_ms"]["p95"],
                          "task_success": w["quality"]["task_success_count"]}
    if args.repeat:
        rp = load_run(args.repeat)
        result["repeat"] = {"run_id": rp["id"], "probes": rp["summary"]["probes"],
                            "rows": [{"id": g["id"], "variant": g["category"], "source": g["source_id"],
                                      "expected": g["expect_cache"], "result": g["cache_result"],
                                      "ok": g["probe_ok"], "within_question_hits": g.get("within_question_hits", 0)}
                                     for g in rp["grades"]]}
    sweep_runs = [runs[0]] + [load_run(s) for s in args.sweep] if args.sweep else []
    if sweep_runs:
        result["sweep"] = sweep_rows(sweep_runs)

    # ---- markdown
    md = [f"# Three-model comparison ({result['created']})", "",
          "Same 55 questions (45 golden + 10 no-retrieval), same gate (Haiku 4.5) and judge (Sonnet 5); only the "
          "generator changes. Each run is cold (its own cache namespace).", "", "## Quality, cost and latency", ""]
    md += _table(models, [("Generator", "model"), ("Thinking", "thinking"), ("Effort", "effort"),
                          ("Task success", "task_success"), ("Judge correct (of 41)", "judge_correct_of_answerable"),
                          ("Citation hit", "citation_hit_of_answerable"), ("Not-in-corpus (of 4)", "not_in_corpus_correct"),
                          ("False declines", "false_declines"), ("Direct (of 10)", "direct_correct"),
                          ("$/interaction mean", "cost_per_interaction_mean"), ("$ p95", "cost_per_interaction_p95"),
                          ("$/successful interaction", "cost_per_successful_interaction"),
                          ("Latency p50 ms", "latency_p50_ms"), ("Latency p95 ms", "latency_p95_ms")])
    md += ["", "## Where the money and time go", ""]
    md += _table(models, [("Generator", "generator"), ("Cost by purpose (55 questions)", "cost_by_purpose"),
                          ("Generate in tokens (mean)", "generate_input_tokens_mean"),
                          ("Generate out tokens (mean)", "generate_output_tokens_mean"),
                          ("Generate latency p50 ms", "generate_latency_ms_p50"),
                          ("LLM ms / question (mean)", "llm_latency_ms_mean"),
                          ("Retrieval ms / question (mean)", "retrieval_latency_ms_mean"),
                          ("Rounds 0/1/2/3", "rounds_distribution"), ("Run spend incl. judge", "run_provider_spend")])
    md += ["", "## Behaviour checks", ""]
    md += _table(models, [("Generator", "generator"), ("Gate accuracy", "gate_accuracy"),
                          ("Version quoted", "version_quoted"), ("Version in prose", "version_in_prose"),
                          ("Leaks", "leaks"), ("Source-line violations", "source_line_violations"),
                          ("Declined rounds", "declined_rounds"), ("Ungrounded rounds", "ungrounded_rounds"),
                          ("Rewrite helped", "rewrite_helped"), ("Rescued after decline", "rescued_after_decline"),
                          ("Fallback calls", "fallback_calls"), ("max_tokens hits", "max_tokens_hits"),
                          ("Provider cache read / write tokens", "provider_cache_read_tokens")])
    md += ["", "## Questions that failed on at least one model", ""]
    md += _table(result["per_question_failures"],
                 [("Question", "id"), ("Type", "category")] + [(m["generator"], m["generator"]) for m in models])
    for m in models:
        e = result["extremes"][m["generator"]]
        md += ["", f"### {m['generator']}: most expensive interactions", ""]
        md += _table(e["most_expensive"], [("Question", "id"), ("Cost", "cost_usd"), ("Rounds", "rounds"),
                                           ("LLM calls", "llm_calls"), ("Output tokens", "output_tokens"),
                                           ("Outcome", "outcome")])
    if "warm" in result:
        w = result["warm"]
        md += ["", "## Cache", "", f"- Warm rerun of run A ({w['run_id']}): hit rate {w['local_cache_hit_rate']}, "
               f"${w['cost_per_interaction_mean']}/interaction, latency p50 {w['latency_p50_ms']} ms / "
               f"p95 {w['latency_p95_ms']} ms, task success {w['task_success']}/55 (identical replay)."]
    if "repeat" in result:
        md += ["", "Repeat-traffic probes (scored on the first/gate call):", ""]
        md += _table(result["repeat"]["rows"], [("Probe", "id"), ("Variant", "variant"), ("Source", "source"),
                                                ("Expected", "expected"), ("Result", "result"), ("OK", "ok"),
                                                ("Within-question hits", "within_question_hits")])
    if "sweep" in result:
        md += ["", "## Validator threshold sweep (Haiku)", ""]
        md += _table(result["sweep"], [("τ_keep", "tau"), ("Task success", "task_success"),
                                       ("Judge verdicts", "judge_verdicts"), ("False declines", "false_declines"),
                                       ("Rounds 0/1/2/3", "rounds_distribution"),
                                       ("Mean rounds (retrieving)", "mean_rounds_retrieving"),
                                       ("$/interaction", "cost_per_interaction_mean"),
                                       ("Rewrite helped", "rewrite_helped"), ("Rescued", "rescued_after_decline")])

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = settings.RUNS_DIR / f"compare_{stamp}"
    out.with_suffix(".json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    out.with_suffix(".md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))
    print(f"\nwritten: {out}.md / .json")


if __name__ == "__main__":
    main()
