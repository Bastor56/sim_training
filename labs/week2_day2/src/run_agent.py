"""Ask the agent one or more questions and print each trace readably (the D1 demo).

    uv run python src/run_agent.py "What is the fee for a stop payment?" "Hi there!"
    uv run python src/run_agent.py --generator opus --tenant business "..."

Shows, per question: the gate decision and its reason, every retrieval
round (query, top-5 with rerank scores, what the validator kept), each
generator verdict, any rewrite and why, then the reply the member sees
(with its code-added source line), the cost and the latency split.

Records go to runs/adhoc/ and the cache namespace "adhoc" (read-write),
so asking the same question again is a free, recorded cache hit.
"""

from __future__ import annotations

import argparse
import textwrap

import agent_graph
import agent_nodes
import day6
import eval_sets
import llm
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
    print(f"OUTCOME  {row['outcome']}: {row['outcome_reason']}")
    print("REPLY")
    for para in row["reply"].split("\n\n"):
        print(textwrap.indent(textwrap.fill(para, 96), "   "))
    print(f"COST     ${row['cost_usd']:.5f}  {row['llm_calls']} LLM calls ({row['local_cache_hits']} cache hits)  "
          f"by purpose: {row['cost_by_purpose']}")
    print(f"LATENCY  {row['latency_ms']:.0f} ms total = LLM {row['llm_latency_ms']:.0f} ms + "
          f"retrieval {row['local_latency_ms']:.0f} ms + overhead")
    if row["errors"]:
        print(f"ERRORS   {row['errors']}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("questions", nargs="+")
    ap.add_argument("--tenant", default="retail")
    ap.add_argument("--generator", choices=list(settings.GENERATORS), default="haiku")
    ap.add_argument("--cache", choices=["off", "read-write", "read-only"], default="read-write")
    args = ap.parse_args()

    run = tracing.start_run("adhoc")
    llm.configure(cache_mode=args.cache, namespace="adhoc")
    deps = agent_nodes.AgentDeps(retriever=day6.Retriever(settings.PARSER, settings.CHUNKER),
                                 generator=settings.GENERATORS[args.generator])
    graph = agent_graph.build_graph(deps)
    corpus = eval_sets.corpus_version()
    existing = (run.dir / "trace.jsonl").read_text().count('"event": "outcome"') if (run.dir / "trace.jsonl").exists() else 0
    for i, question in enumerate(args.questions, start=existing + 1):
        state, row = agent_graph.answer_question(graph, correlation_id=f"adhoc/{i:04d}", question=question,
                                                 tenant=args.tenant, corpus_version=corpus)
        show(state, row, deps.tau)


if __name__ == "__main__":
    main()
