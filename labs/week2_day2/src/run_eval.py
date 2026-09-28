"""Run an eval set through the agent with one generator, grade it, and write runs/<run_id>/.

    uv run python src/run_eval.py --generator haiku --namespace A                  # 55 quality questions
    uv run python src/run_eval.py --generator haiku --namespace A --set repeat     # cache probes
    uv run python src/run_eval.py --generator opus --namespace pilot_opus --ids q001,q009,q017,q029,q045
    uv run python src/run_eval.py --generator haiku --namespace A --cache read-only   # replay for $0

Writes, in runs/<run_id>/:
    config.json         everything that determined this run (written first)
    calls.jsonl         one record per LLM call / local-model step (tracing.py)
    trace.jsonl         agent events per question
    interactions.jsonl  one row per question: outcome, reply, cost and latency rollup
    grades.jsonl        deterministic checks + judge verdict per question
    summary.json/.md    run-level quality, cost, latency and cache numbers

A BudgetExceeded (spend guard) or CacheMissReadOnly (replay) stops the run:
both mean "do not keep spending / guessing". Any other error on one question
is recorded as that question's outcome "error" and the run continues.
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
from collections import defaultdict
from datetime import datetime

import agent_graph
import agent_nodes
import day6
import eval_sets
import grading
import llm
import llm_cache
import pricing
import settings
import spend
import tracing

STOP_ERRORS = (spend.BudgetExceeded, llm_cache.CacheMissReadOnly)


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    k = (len(ordered) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
    return round(ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo), 6)


def _git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                              cwd=settings.LAB_DIR).stdout.strip()
    except OSError:
        return ""


def _pip_freeze() -> list[str]:
    try:
        out = subprocess.run(["uv", "pip", "freeze"], capture_output=True, text=True, cwd=settings.LAB_DIR).stdout
        return out.splitlines()
    except OSError:
        return []


def write_config(run: tracing.Run, args, corpus_version: str, golden_version: int) -> None:
    config = {
        "run_id": run.run_id,
        "created": datetime.now().isoformat(timespec="seconds"),
        "args": vars(args),
        "generator": settings.GENERATORS[args.generator],
        "gate_role": settings.GATE,
        "judge_role": settings.JUDGE,
        "prompts": settings.PROMPTS,
        "max_rounds": settings.MAX_ROUNDS,
        "tau_keep": args.tau,
        "top_k": settings.TOP_K,
        "retrieval": {"parser": settings.PARSER, "chunker": settings.CHUNKER, "mode": settings.RETRIEVAL_MODE,
                      "index": day6.collection_name(settings.PARSER, settings.CHUNKER),
                      "day6_params": day6.DAY6_PARAMS["retrieval"]},
        "corpus_version": corpus_version,
        "golden_set_version": golden_version,
        "pricing_version": pricing.pricing_version(),
        "pricing": pricing.load()["models"],
        "git_commit": _git_commit(),
        "pip_freeze": _pip_freeze(),
    }
    run.dir.mkdir(parents=True, exist_ok=True)
    (run.dir / "config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def probe_grade(row: dict, item: eval_sets.EvalItem) -> dict:
    """Repeat-traffic probes are scored on cache behaviour only.

    The question a probe asks is "did the cache treat this as the same question as
    an earlier one?", and that is decided by the first LLM call (the gate): a hit
    there means an earlier question's cached response was reused. Hits on later
    calls can come from the same question repeating itself (two rounds that
    retrieve identical evidence send the generator an identical request), so they
    are reported separately and don't decide the probe. Finding, run A probes: r014.
    """
    result = row.get("first_call_cache") or "miss"
    return {"id": item.id, "set": item.set, "category": item.category, "source_id": item.extra["source_id"],
            "expect_cache": item.expect_cache, "cache_result": result, "probe_ok": result == item.expect_cache,
            "within_question_hits": row.get("within_question_hits", 0),
            "all_calls_hit": bool(row["llm_calls"]) and row["local_cache_hits"] == row["llm_calls"]}


def regrade_probes(run_dir) -> None:
    """Re-score a finished probe run from its own call records (no agent calls, no spend)."""
    from pathlib import Path

    run_dir = Path(run_dir)
    calls = [json.loads(line) for line in (run_dir / "calls.jsonl").read_text().splitlines()]
    rows = [json.loads(line) for line in (run_dir / "interactions.jsonl").read_text().splitlines()]
    items = {i.id: i for i in eval_sets.load(["repeat"])}
    for row in rows:
        llm_records = [c for c in calls if c["correlation_id"] == row["correlation_id"] and c["kind"] == "llm"]
        row["first_call_cache"] = llm_records[0]["local_cache"] if llm_records else None
        row["within_question_hits"] = sum(c["local_cache"] == "hit" for c in llm_records[1:])
    grades = [probe_grade(row, items[row["id"]]) for row in rows]
    (run_dir / "interactions.jsonl").write_text("".join(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n"
                                                        for r in rows), encoding="utf-8")
    (run_dir / "grades.jsonl").write_text("".join(json.dumps(g, sort_keys=True) + "\n" for g in grades),
                                          encoding="utf-8")
    run = tracing.Run(run_dir.name, run_dir)
    summary = summarise(rows, grades, run)
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (run_dir / "summary.md").write_text(summary_md(summary), encoding="utf-8")
    print(summary_md(summary))


REPLAY_FIELDS = ("gate_decision", "queries", "round_verdicts", "outcome", "answer", "reply", "source_line")


def replay_diff(original_dir, rows: list[dict], grades: list[dict]) -> list[str]:
    """Compare a read-only replay with the run it replays: every stable field must match.

    Latency, cost (a replay is all $0 cache hits) and correlation ids differ by
    design, so they're excluded. Citations are compared by chunk id.
    """
    from pathlib import Path

    d = Path(original_dir)
    orig_rows = {r["id"]: r for r in map(json.loads, (d / "interactions.jsonl").read_text().splitlines())}
    orig_grades = {g["id"]: g for g in map(json.loads, (d / "grades.jsonl").read_text().splitlines())}
    diffs = []
    for row, g in zip(rows, grades):
        o, og = orig_rows[row["id"]], orig_grades[row["id"]]
        for f in REPLAY_FIELDS:
            if row.get(f) != o.get(f):
                diffs.append(f"{row['id']}.{f}")
        if [c["chunk_id"] for c in row["citations"]] != [c["chunk_id"] for c in o["citations"]]:
            diffs.append(f"{row['id']}.citations")
        for f in ("task_success", "judge_verdict"):
            if g.get(f) != og.get(f):
                diffs.append(f"{row['id']}.{f}")
    return diffs


def summarise(rows: list[dict], grades: list[dict], run: tracing.Run) -> dict:
    quality = [r for r in rows if r["set"] in ("golden", "no_retrieval") and r["outcome"] != "error"]
    costs = [r["cost_usd"] for r in quality]
    lat = [r["latency_ms"] for r in quality]
    by_purpose: dict[str, float] = defaultdict(float)
    for r in quality:
        for k, v in r["cost_by_purpose"].items():
            by_purpose[k] += v
    llm_calls = sum(r["llm_calls"] for r in rows)
    hits = sum(r["local_cache_hits"] for r in rows)
    ledger = [e for e in spend.entries() if e["run_id"] == run.run_id]
    summary = {
        "run_id": run.run_id,
        "questions": len(rows),
        "errors": sum(r["outcome"] == "error" for r in rows),
        "cost_per_interaction": {"mean": round(statistics.mean(costs), 6) if costs else None,
                                 "p50": percentile(costs, 0.5), "p95": percentile(costs, 0.95),
                                 "max": max(costs) if costs else None},
        "latency_ms": {"p50": percentile(lat, 0.5), "p95": percentile(lat, 0.95), "max": max(lat) if lat else None},
        "llm_latency_ms_mean": round(statistics.mean(r["llm_latency_ms"] for r in quality), 1) if quality else None,
        "local_latency_ms_mean": round(statistics.mean(r["local_latency_ms"] for r in quality), 1) if quality else None,
        "interaction_cost_total": round(sum(costs), 6),
        "cost_by_purpose_total": {k: round(v, 6) for k, v in sorted(by_purpose.items())},
        "rounds_distribution": {n: sum(r["rounds"] == n for r in quality) for n in range(settings.MAX_ROUNDS + 1)},
        "llm_calls": llm_calls,
        "local_cache_hit_rate": round(hits / llm_calls, 4) if llm_calls else None,
        "provider_cache_read_tokens": sum(r["cache_read_input_tokens"] for r in rows),
        "output_tokens_per_generate_mean": None,
        "provider_spend_this_run": round(sum(e["cost_usd"] for e in ledger), 6),
        "judge_spend_this_run": round(sum(e["cost_usd"] for e in ledger if e["purpose"] == "judge"), 6),
        "ledger_total_after_run": spend.total(),
    }
    gen = [json.loads(line) for line in (run.dir / "calls.jsonl").read_text().splitlines()] \
        if (run.dir / "calls.jsonl").exists() else []
    gen = [c for c in gen if c["purpose"] == "generate" and c["local_cache"] != "hit" and not c.get("error")]
    if gen:
        summary["output_tokens_per_generate_mean"] = round(statistics.mean(c["output_tokens"] for c in gen), 1)
    qgrades = [g for g in grades if g["set"] in ("golden", "no_retrieval")]
    if qgrades:
        summary["quality"] = grading.summarise(qgrades)
    probes = [g for g in grades if g["set"] == "repeat_traffic"]
    if probes:
        by_variant: dict[str, list] = defaultdict(list)
        for p in probes:
            by_variant[p["category"]].append(p)
        summary["probes"] = {v: {"n": len(ps), "ok": sum(p["probe_ok"] for p in ps),
                                 "results": [f"{p['id']}:{p['cache_result']}" for p in ps],
                                 "within_question_hits": sum(p.get("within_question_hits", 0) for p in ps)}
                             for v, ps in by_variant.items()}
    return summary


def summary_md(s: dict) -> str:
    c, lat = s["cost_per_interaction"], s["latency_ms"]
    lines = [f"# {s['run_id']}", "",
             f"- questions: {s['questions']} (errors: {s['errors']})",
             f"- cost per interaction: mean ${c['mean']} | p50 ${c['p50']} | p95 ${c['p95']} | max ${c['max']}",
             f"- latency per interaction: p50 {lat['p50']} ms | p95 {lat['p95']} ms | max {lat['max']} ms "
             f"(LLM mean {s['llm_latency_ms_mean']} ms, retrieval mean {s['local_latency_ms_mean']} ms)",
             f"- cost by purpose (sum): {s['cost_by_purpose_total']}",
             f"- rounds distribution: {s['rounds_distribution']}",
             f"- local cache hit rate: {s['local_cache_hit_rate']} of {s['llm_calls']} LLM calls; "
             f"provider cache read tokens: {s['provider_cache_read_tokens']}",
             f"- output tokens per generate call (mean, provider calls): {s['output_tokens_per_generate_mean']}",
             f"- provider spend this run: ${s['provider_spend_this_run']} (judge ${s['judge_spend_this_run']}); "
             f"ledger total ${s['ledger_total_after_run']}"]
    if "quality" in s:
        lines += ["", "## Quality", ""] + [f"- {k}: {v}" for k, v in s["quality"].items()]
    if "probes" in s:
        lines += ["", "## Cache probes", ""] + [f"- {k}: {v['ok']}/{v['n']} as expected {v['results']}"
                                                for k, v in s["probes"].items()]
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--generator", choices=list(settings.GENERATORS), required=True)
    ap.add_argument("--namespace", required=True, help="cache namespace (fresh = cold run)")
    ap.add_argument("--set", default="golden,no_retrieval", help="golden,no_retrieval | repeat")
    ap.add_argument("--ids", default="", help="comma-separated item ids (subset)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--tau", type=float, default=settings.TAU_KEEP)
    ap.add_argument("--cache", choices=["read-write", "read-only", "off"], default="read-write")
    ap.add_argument("--max-spend", type=float, default=None)
    ap.add_argument("--no-judge", action="store_true")
    ap.add_argument("--tag", default="", help="extra label for the run id")
    ap.add_argument("--regrade-probes", default="", help="re-score an existing probe run dir, then exit")
    ap.add_argument("--replay-of", default="", help="an earlier run dir: replay it read-only and diff (costs $0)")
    args = ap.parse_args()
    if args.regrade_probes:
        regrade_probes(args.regrade_probes)
        return
    if args.replay_of:
        args.cache = "read-only"  # a replay must never reach the provider
        args.tag = args.tag or "replay"

    items = eval_sets.load(args.set.split(","))
    if args.ids:
        wanted = args.ids.split(",")
        items = [i for i in items if i.id in wanted]
    if args.limit:
        items = items[: args.limit]
    set_tag = "repeat" if args.set == "repeat" else ""
    run_id = "_".join(x for x in [datetime.now().strftime("%Y%m%d-%H%M%S"), args.generator, args.namespace,
                                  set_tag, args.tag] if x)
    run = tracing.start_run(run_id, max_spend=args.max_spend)
    llm.configure(cache_mode=args.cache, namespace=args.namespace)
    gs = day6.load_golden_set()
    corpus = eval_sets.corpus_version(gs)
    write_config(run, args, corpus, gs.version)

    deps = agent_nodes.AgentDeps(retriever=day6.Retriever(settings.PARSER, settings.CHUNKER),
                                 generator=settings.GENERATORS[args.generator], tau=args.tau)
    graph = agent_graph.build_graph(deps)
    rows, grades = [], []
    print(f"run {run_id}: {len(items)} items, generator={args.generator}, namespace={args.namespace}, "
          f"tau={args.tau}, cache={args.cache}")
    for n, item in enumerate(items, start=1):
        cid = f"{run_id}/{item.id}"
        item_corpus = item.corpus_version or corpus
        try:
            _, row = agent_graph.answer_question(graph, correlation_id=cid, question=item.question,
                                                 tenant=item.tenant, corpus_version=item_corpus)
        except STOP_ERRORS:
            raise
        except Exception as e:  # recorded, not fatal: one bad question shouldn't lose the run
            row = {"correlation_id": cid, "question": item.question, "tenant": item.tenant, "outcome": "error",
                   "outcome_reason": f"{type(e).__name__}: {e}", "gate_decision": None, "rounds": 0,
                   "round_verdicts": [], "citations": [], "answer": "", "reply": "", "source_line": "",
                   "rewrite_helped": False, "rescued_after_decline": False, "latency_ms": 0.0,
                   "cost_usd": 0.0, "cost_by_purpose": {}, "llm_calls": 0, "local_cache_hits": 0,
                   "llm_latency_ms": 0.0, "local_latency_ms": 0.0, "cache_read_input_tokens": 0,
                   "input_tokens": 0, "output_tokens": 0, "errors": [str(e)]}
        row.update({"id": item.id, "set": item.set, "category": item.category, "corpus_version": item_corpus})
        if item.set == "repeat_traffic":
            g = probe_grade(row, item)
        elif row["outcome"] == "error":
            g = {"id": item.id, "set": item.set, "category": item.category, "outcome_expected": item.expected_outcome,
                 "outcome_actual": "error", "gate_expected": item.expected_gate, "gate_actual": None,
                 "gate_correct": False, "outcome_correct": False, "task_success": False, "source_line_ok": False,
                 "leak": False, "declined_rounds": 0, "ungrounded_rounds": 0, "rewrite_helped": False,
                 "rescued_after_decline": False, "rounds": 0, "round_verdicts": []}
        else:
            g = grading.grade(row, item, corpus_version=corpus, use_judge=not args.no_judge)
        rows.append(row)
        grades.append(g)
        run.append("interactions.jsonl", row)
        run.append("grades.jsonl", g)
        mark = ("ok " if g.get("probe_ok") else "BAD") if item.set == "repeat_traffic" else \
            ("ok " if g["task_success"] else "---")
        print(f"{n:3d} {item.id} {mark} {row['outcome'] or '':15s} rounds={row['rounds']} "
              f"${row['cost_usd']:.5f} {row['latency_ms']:7.0f} ms  judge={g.get('judge_verdict', '-')}"
              f"{'  cache=' + g['cache_result'] if 'cache_result' in g else ''}")

    summary = summarise(rows, grades, run)
    if args.replay_of:
        diffs = replay_diff(args.replay_of, rows, grades)
        summary["replay_of"] = args.replay_of
        summary["replay_diffs"] = diffs
        print(f"replay of {args.replay_of}: " + ("IDENTICAL (all stable fields match)" if not diffs
                                                  else f"{len(diffs)} DIFFERENCES: {diffs[:20]}"))
    (run.dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (run.dir / "summary.md").write_text(summary_md(summary), encoding="utf-8")
    print()
    print(summary_md(summary))


if __name__ == "__main__":
    main()
