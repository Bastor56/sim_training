"""Ask the agent one or more questions and print each trace readably.

    uv run python agent/run_agent.py "What is the fee for a stop payment?" "Hi there!"
    HARBOR_MCP_TOKEN=... uv run python agent/run_agent.py --member M-1001 "What's my checking balance?"
    ... --allow-tools get_account,list_member_accounts "..."    # the client-side allow-list (R3 demo)

Day 3: with --member, the agent connects to the harbor-mcp server (URL from
HARBOR_MCP_URL, default 127.0.0.1:8200; token from HARBOR_MCP_TOKEN, or the
env var named by --token-env), prints what it discovered, and can answer
from the member's own records. Without a reachable server it still answers
from documents; record questions then get the "couldn't check" reply.

Shows, per question: the gate decision and its reason, every retrieval
round (query, top-5 with rerank scores, what the validator kept), each
generator verdict, any rewrite and why, then the reply the member sees
(with its code-added source line), the cost and the latency split.

Records go to runs/adhoc/ and the cache namespace "adhoc" (read-write),
so asking the same question again is a free, recorded cache hit.
"""

from __future__ import annotations

import argparse
import json
import textwrap

import os
import sys

import agent_graph
import agent_nodes
import day6
import eval_sets
import llm
import mcp_gateway
import settings
import tracing


def show(state, row, tau: float) -> None:
    print("=" * 100)
    print(f"Q: {row['question']}   [tenant={row['tenant']}, cid={row['correlation_id']}]")
    gate = state.gate or {}
    print(f"GATE     {gate.get('decision')}: {gate.get('reason')}")
    rewrites = {r["n"]: r for r in state.rewrites}
    for r in state.rounds:
        if r["n"] in rewrites:
            rw = rewrites[r["n"]]
            print(f"REWRITE  -> \"{rw['new_query']}\"  ({rw['reason']})" + ("  [REPEATED QUERY]" if rw["repeated"] else ""))
        print(f"ROUND {r['n']}  query: \"{r['query']}\"")
        for x in r["results"]:
            mark = "kept" if x["chunk_id"] in r["kept"] else "    "
            print(f"   {mark} {x['rerank']:.3f}  {x['title'][:48]:48s} {x['chunk_id']}")
        verdict = r["verdict"]
        extra = f" - {r['generator_reason']}" if r.get("generator_reason") else ""
        print(f"   verdict: {verdict} (tau={tau}){extra}")
    if row.get("tool_calls") or state.tool_stop:
        for c in state.tool_calls:
            ids = ", ".join(c["record_ids"]) or "-"
            err = f"  {c['error']}" if c["error"] else ""
            print(f"TOOL {c['n']}   {c['tool']}({json.dumps(c['arguments'])}) -> {c['status']:11s} "
                  f"{c['latency_ms']:7.1f} ms  records: {ids}{err}")
        print(f"   tool loop stopped: {state.tool_stop}")
    print(f"OUTCOME  {row['outcome']}: {row['outcome_reason']}")
    print("REPLY")
    for para in row["reply"].split("\n\n"):
        print(textwrap.indent(textwrap.fill(para, 96), "   "))
    print(f"COST     ${row['cost_usd']:.5f}  {row['llm_calls']} LLM calls ({row['local_cache_hits']} cache hits)  "
          f"by purpose: {row['cost_by_purpose']}")
    print(f"LATENCY  {row['latency_ms']:.0f} ms total = LLM {row['llm_latency_ms']:.0f} ms + "
          f"retrieval {row['local_latency_ms']:.0f} ms + tools {row['tool_latency_ms']:.0f} ms + overhead")
    if row["errors"]:
        print(f"ERRORS   {row['errors']}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("questions", nargs="+")
    ap.add_argument("--tenant", default="retail")
    ap.add_argument("--generator", choices=list(settings.GENERATORS), default="haiku")
    ap.add_argument("--cache", choices=["off", "read-write", "read-only"], default="read-write")
    ap.add_argument("--member", default="", help="signed-in member ID; enables the record path")
    ap.add_argument("--today", default=None, help="ISO date the agent treats as today (default: the real date)")
    ap.add_argument("--token-env", default="HARBOR_MCP_TOKEN", help="env var holding this agent's MCP token")
    ap.add_argument("--allow-tools", default="",
                    help="comma-separated client-side allow-list (hides other tools from the model; NOT enforcement)")
    args = ap.parse_args()

    run = tracing.start_run("adhoc")
    llm.configure(cache_mode=args.cache, namespace="adhoc")
    gateway, tools_hash = None, ""
    if args.member:
        try:
            gateway = mcp_gateway.MCPGateway(os.environ.get("HARBOR_MCP_URL", mcp_gateway.DEFAULT_URL),
                                             os.environ.get(args.token_env, "")).connect()
            tools_hash = gateway.discovery["tool_list_hash"]
            run.append("discovery.jsonl", {"ts": tracing.now_iso(), **gateway.discovery})
            d = gateway.discovery
            print(f"DISCOVERY {d['server']} {d['server_version']} at {d['url']}: {len(d['tools'])} tools, "
                  f"hash {d['tool_list_hash']}\n          {', '.join(d['tools'])}")
        except mcp_gateway.GatewayError as e:
            print(f"DISCOVERY failed: {e}\n          continuing without record tools", file=sys.stderr)
    allowed = frozenset(t.strip() for t in args.allow_tools.split(",") if t.strip()) or None
    if allowed:
        print(f"ALLOW-LIST (client side) {sorted(allowed)}")
    deps = agent_nodes.AgentDeps(retriever=day6.Retriever(settings.PARSER, settings.CHUNKER),
                                 generator=settings.GENERATORS[args.generator], gateway=gateway,
                                 allowed_tools=allowed)
    graph = agent_graph.build_graph(deps)
    corpus = eval_sets.corpus_version()
    existing = (run.dir / "trace.jsonl").read_text().count('"event": "outcome"') if (run.dir / "trace.jsonl").exists() else 0
    for i, question in enumerate(args.questions, start=existing + 1):
        state, row = agent_graph.answer_question(graph, correlation_id=f"adhoc/{i:04d}", question=question,
                                                 tenant=args.tenant, corpus_version=corpus,
                                                 member_id=args.member, tools_hash=tools_hash, today=args.today)
        show(state, row, deps.tau)
    if gateway is not None:
        gateway.close()


if __name__ == "__main__":
    main()
