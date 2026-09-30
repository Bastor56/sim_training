"""Gate-only regression check: Day 2's 55 questions + the 15 tool questions (plan.md milestone 10).

gate_v2 added a third decision (use_tool) and a runtime list of the tools
harbor-mcp advertises. This re-asks ONLY the gate (no retrieval, no tools,
no answers) for:
  - Day 2's 45 golden questions (expected: retrieve) and 10 no-retrieval
    questions (expected: answer_direct), where Day 2's gate_v1 scored
    165/165 over three runs: any change of decision is a regression;
  - the 15 tool questions (expected: use_tool).

Day 2 labels that Day 3 changes on purpose are listed, with reasons, in
eval/gate_relabels.yaml. A relabel applies only if its tool is advertised.
The summary always reports BOTH scores: against Day 2's labels (raw) and
with the documented relabels.

    HARBOR_MCP_TOKEN=... uv run python scripts/gate_recheck.py

The tool list is discovered live from the server, exactly as the agent sees
it. Writes runs/<run_id>/gate_recheck.jsonl and summary.json.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

LAB_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(LAB_DIR / "agent"))
sys.path.insert(0, str(LAB_DIR / "scripts"))


def main() -> int:
    import agent_nodes
    import eval_sets
    import llm
    import mcp_gateway
    import settings
    import tracing
    from agent_state import AgentState
    from run_tool_eval import load_tool_set

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run-id", default="")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--ids", default="", help="comma-separated question ids (e.g. to re-ask a mismatch)")
    ap.add_argument("--repeat", type=int, default=1, help="ask each question this many times (consistency)")
    args = ap.parse_args()

    import yaml

    items = [(q.id, q.set, q.question, q.tenant, q.expected_gate) for q in eval_sets.load(["golden", "no_retrieval"])]
    relabels = yaml.safe_load((LAB_DIR / "eval" / "gate_relabels.yaml").read_text())["relabels"]
    items += [(q["id"], "tool", q["question"], "retail", q["expect_gate"]) for q in load_tool_set()["queries"]]
    if args.ids:
        wanted = {i.strip() for i in args.ids.split(",")}
        items = [it for it in items if it[0] in wanted]
    if args.limit:
        items = items[:args.limit]
    items = [(f"{it[0]}" if args.repeat == 1 else f"{it[0]}#{k}", *it[1:]) for it in items for k in range(1, args.repeat + 1)]

    run_id = args.run_id or datetime.now().strftime("%Y%m%d-%H%M%S") + f"_gate_recheck_{len(items)}q"
    run = tracing.start_run(run_id)
    llm.configure(cache_mode="off")
    gateway = mcp_gateway.MCPGateway(os.environ.get("HARBOR_MCP_URL", mcp_gateway.DEFAULT_URL),
                                     os.environ.get("HARBOR_MCP_TOKEN", "")).connect()
    try:
        deps = agent_nodes.AgentDeps(retriever=None, generator=settings.GENERATORS["haiku"], gateway=gateway)
        section = agent_nodes.tools_section(deps.visible_tools())
        advertised = set(gateway.discovery["tools"])
        active = {r["id"]: r for r in relabels if r["requires_tool"] in advertised}
        print(f"relabels in force: {sorted(active) or 'none'}")
        corpus = eval_sets.corpus_version()
        print(f"run {run_id}: {len(items)} questions, prompt {settings.PROMPTS['gate']}, "
              f"server {gateway.discovery['server_version']}, tools {gateway.discovery['tool_list_hash']}")
        rows = []
        for qid, qset, question, tenant, expected in items:
            state = AgentState(correlation_id=f"{run_id}/{qid}", question=question, tenant=tenant,
                               corpus_version=corpus, tools_hash=gateway.discovery["tool_list_hash"])
            with tracing.interaction(state.correlation_id):
                try:
                    data = deps.call("gate", deps.gate_role, state, agent_nodes.gate_message(state),
                                     agent_nodes.GATE_SCHEMA, system_extra=section).data
                except llm.LLMError as e:
                    data = {"decision": "error", "reason": str(e), "search_query": ""}
            base_id = qid.split("#")[0]
            final = active[base_id]["day3_expected"] if base_id in active else expected
            row = {"id": qid, "set": qset, "question": question, "expected": final, "day2_expected": expected,
                   "relabelled": base_id in active, "decision": data["decision"],
                   "correct": data["decision"] == final, "correct_vs_day2_label": data["decision"] == expected,
                   "reason": data["reason"]}
            rows.append(row)
            run.append("gate_recheck.jsonl", row)
            if not row["correct"]:
                print(f"  MISMATCH {qid} [{qset}] expected {final}, got {data['decision']}: {question}\n"
                      f"           reason: {data['reason']}")
    finally:
        gateway.close()

    by_set = {s: f"{sum(r['correct'] for r in rows if r['set'] == s)}/{sum(r['set'] == s for r in rows)}"
              for s in dict.fromkeys(r["set"] for r in rows)}
    confusion = Counter(f"{r['expected']} -> {r['decision']}" for r in rows)
    records = [json.loads(line) for line in (run.dir / "calls.jsonl").read_text().splitlines()]
    summary = {"questions": len(rows), "correct": f"{sum(r['correct'] for r in rows)}/{len(rows)}",
               "correct_vs_day2_labels_raw": f"{sum(r['correct_vs_day2_label'] for r in rows)}/{len(rows)}",
               "relabels_applied": sorted(active), "by_set": by_set,
               "confusion": dict(sorted(confusion.items())),
               "day2_questions_sent_to_tools": [r["id"] for r in rows if r["set"] != "tool" and r["decision"] == "use_tool"],
               "cost_usd": round(sum(r["cost_usd"] for r in records), 5),
               "mean_input_tokens": round(sum(r["input_tokens"] for r in records) / max(1, len(records)))}
    (run.dir / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
