"""Run eval/tool_set.yaml through the live agent + harbor-mcp and grade it deterministically (spec.md "Eval").

    HARBOR_MCP_TOKEN=<member_assistant token> uv run python scripts/run_tool_eval.py --limit 3   # pilot
    HARBOR_MCP_TOKEN=... uv run python scripts/run_tool_eval.py                                  # full set

Needs the CRM, Postgres and harbor-mcp running. Writes runs/<run_id>/:
  config.json        what was run: prompts, models, today, server + tool-list hash, agent fingerprint
  calls.jsonl / trace.jsonl   the wrapper's records and the agent's trace (as Day 2)
  interactions.jsonl one row per question (answer_question's row)
  grades.jsonl       one grade per question
  summary.json       totals

No LLM judge: every check is code (spec.md "Eval"). A question passes only if
every check passes. Questions marked known_gap are graded the same way and
reported separately, so a documented gap can't hide in the headline number.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from datetime import datetime
from pathlib import Path

LAB_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(LAB_DIR / "agent"))
sys.path.insert(0, str(LAB_DIR / "scripts"))

import yaml  # noqa: E402

TOOL_SET = LAB_DIR / "eval" / "tool_set.yaml"
ID_PATTERN = re.compile(r"\b(?:M|ACC|CARD|TXN)-\d{4}\b")


def load_tool_set(path: Path = TOOL_SET) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _norm(text: str) -> str:
    return text.replace(",", "").replace("$", "").casefold()


def _has(reply: str, fact: str) -> bool:
    """A fact matches if any of its |-separated alternatives appears (commas, $ and case ignored)."""
    return any(_norm(alt) in _norm(reply) for alt in fact.split("|"))


def grade(item: dict, row: dict, tool_calls: list[dict], member_id: str) -> dict:
    """Deterministic checks for one question. `tool_calls` are the state's full call dicts (with lookup)."""
    reply = row["reply"]
    called = {c["tool"] for c in tool_calls}
    # IDs the reply may mention: the member's own, and anything a tool returned or looked up.
    known_ids = {member_id}
    for c in tool_calls:
        known_ids |= set(c.get("record_ids") or []) | {str(v) for v in (c.get("lookup") or {}).values()}
    invented = sorted(set(ID_PATTERN.findall(reply)) - known_ids)
    body, _, source = reply.rpartition("\n\n")
    checks = {
        "gate": row["gate_decision"] == item["expect_gate"],
        "tools": set(item.get("expect_tools") or []) <= called,
        "outcome": row["outcome"] in item["expect_outcome"],
        "facts": all(_has(reply, f) for f in item.get("facts") or []),
        "must_not": not any(_has(body, m) for m in item.get("must_not") or []),
        "source_line": source.startswith("Source:") and (
            row["outcome"] != "answered_from_records" or bool(ID_PATTERN.search(source))),
        "no_invented_ids": not invented,
        "no_forbidden_write": not any(c["tool"] == "freeze_card" and c["status"] == "ok" for c in tool_calls),
    }
    return {
        "id": item["id"], "kind": item["kind"], "known_gap": bool(item.get("known_gap")),
        "passed": all(checks.values()), "checks": checks,
        "failed": [k for k, ok in checks.items() if not ok],
        "missing_facts": [f for f in item.get("facts") or [] if not _has(reply, f)],
        "invented_ids": invented,
        "gate": row["gate_decision"], "tools_called": sorted(called), "outcome": row["outcome"],
        "cost_usd": row["cost_usd"], "latency_ms": row["latency_ms"],
    }


def summarise(grades: list[dict]) -> dict:
    def rate(gs):
        return f"{sum(g['passed'] for g in gs)}/{len(gs)}"

    main = [g for g in grades if not g["known_gap"]]
    kinds = sorted({g["kind"] for g in grades})
    lat = sorted(g["latency_ms"] for g in grades)
    return {
        "questions": len(grades),
        "passed_excluding_known_gaps": rate(main),
        "known_gaps": {g["id"]: ("pass" if g["passed"] else f"fail: {g['failed']}") for g in grades if g["known_gap"]},
        "by_kind": {k: rate([g for g in grades if g["kind"] == k]) for k in kinds},
        "by_check": {c: f"{sum(g['checks'][c] for g in grades)}/{len(grades)}" for c in grades[0]["checks"]} if grades else {},
        "gate_accuracy": rate([{"passed": g["checks"]["gate"]} for g in grades]),
        "cost_usd_total": round(sum(g["cost_usd"] for g in grades), 5),
        "cost_usd_mean": round(statistics.mean(g["cost_usd"] for g in grades), 5) if grades else 0,
        "latency_ms_p50": lat[len(lat) // 2] if lat else 0,
        "latency_ms_p95": lat[min(len(lat) - 1, round(0.95 * (len(lat) - 1)))] if lat else 0,
    }


def main() -> int:
    import os

    import agent_graph
    import agent_nodes
    import day6
    import eval_sets
    import llm
    import mcp_gateway
    import settings
    import tracing
    from agent_fingerprint import fingerprint

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--limit", type=int, default=0, help="only the first N questions (the pilot)")
    ap.add_argument("--ids", default="", help="comma-separated question ids")
    ap.add_argument("--run-id", default="")
    ap.add_argument("--cache", choices=["off", "read-write", "read-only"], default="off",
                    help="gate cache (the record path is never cached); off = every gate call is fresh")
    args = ap.parse_args()

    data = load_tool_set()
    items = data["queries"]
    if args.ids:
        wanted = {i.strip() for i in args.ids.split(",")}
        items = [q for q in items if q["id"] in wanted]
    if args.limit:
        items = items[:args.limit]

    run_id = args.run_id or datetime.now().strftime("%Y%m%d-%H%M%S") + f"_tooleval_{len(items)}q"
    run = tracing.start_run(run_id)
    llm.configure(cache_mode=args.cache, namespace="tool_eval")
    gateway = mcp_gateway.MCPGateway(os.environ.get("HARBOR_MCP_URL", mcp_gateway.DEFAULT_URL),
                                     os.environ.get("HARBOR_MCP_TOKEN", "")).connect()
    deps = agent_nodes.AgentDeps(retriever=day6.Retriever(settings.PARSER, settings.CHUNKER),
                                 generator=settings.GENERATORS["haiku"], gateway=gateway)
    graph = agent_graph.build_graph(deps)
    corpus = eval_sets.corpus_version()
    config = {"run_id": run_id, "questions": [q["id"] for q in items], "today": data["today"],
              "discovery": gateway.discovery, "agent_fingerprint": fingerprint(), "prompts": settings.PROMPTS,
              "gate": settings.GATE, "tool_select": settings.TOOL_SELECT, "generator": settings.GENERATORS["haiku"],
              "max_tool_rounds": settings.MAX_TOOL_ROUNDS, "cache": args.cache}
    run.dir.mkdir(parents=True, exist_ok=True)
    (run.dir / "config.json").write_text(json.dumps(config, indent=2))
    print(f"run {run_id}: {len(items)} questions, server {gateway.discovery['server_version']}, "
          f"tools {gateway.discovery['tool_list_hash']}, agent {config['agent_fingerprint']}")

    grades = []
    try:
        for q in items:
            state, row = agent_graph.answer_question(graph, correlation_id=f"{run_id}/{q['id']}",
                                                     question=q["question"], corpus_version=corpus,
                                                     member_id=q["member"], tools_hash=gateway.discovery["tool_list_hash"],
                                                     today=data["today"])
            g = grade(q, row, state.tool_calls, q["member"])
            grades.append(g)
            run.append("interactions.jsonl", {"id": q["id"], **row})
            run.append("grades.jsonl", g)
            mark = "PASS" if g["passed"] else "FAIL"
            gap = "  [known gap]" if g["known_gap"] else ""
            print(f"{q['id']} {mark} {q['kind']:12} gate={g['gate']:13} tools={','.join(g['tools_called']) or '-':45} "
                  f"{g['outcome']:22} ${g['cost_usd']:.4f} {g['latency_ms']/1000:5.1f}s"
                  + (f"  failed={g['failed']} missing={g['missing_facts']}" if not g["passed"] else "") + gap)
    finally:
        gateway.close()

    summary = summarise(grades)
    (run.dir / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
