"""Builds the agent graph and runs one question through it (spec.md "The agent").

Copied from Day 2; Day 3 adds the record path (use_tool):

    START -> planner --use_tool--> tool_loop --(tools ran)--> generate_from_tools -> finalise -> END
                                           \\--(no tools / no member / failed)-----> finalise -> END

Day 2's paths, unchanged:

    START -> planner --answer_direct--> answer_direct -> finalise -> END
               ^   \\--retrieve--> retrieve -> validate --usable--> generate --answered--> finalise -> END
               |                                 |                     |
               |<------ poor, round < 3 ---------+                     |
               |<------ declined / ungrounded, round < 3 --------------+   (decision 12)
                                                 |                     |
                                    poor, round = 3          declined, round = 3
                                                 v                     v
                                            not_in_corpus -> finalise -> END

LangGraph's low-level StateGraph with hand-written nodes, as in week 1 days
3-4, so every prompt is a visible file under prompts/ rather than a
framework-injected one.

answer_question() is the one entry point runners use: it opens the
interaction (the correlation id), invokes the graph, and rolls the call
records up into one per-interaction row (spec.md "Per-interaction rollup").
"""

from __future__ import annotations

import time
from collections import defaultdict
from datetime import date

from langgraph.graph import END, START, StateGraph

import agent_nodes as n
import tracing
from agent_state import AgentState

# planner/retrieve/validate/generate can repeat 3 times, plus the end nodes:
# well under this, which only guards against a routing bug looping forever.
RECURSION_LIMIT = 40


def build_graph(deps: n.AgentDeps):
    routes = n.make_routes(deps)
    g = StateGraph(AgentState)
    g.add_node("planner", n.make_planner(deps))
    g.add_node("retrieve", n.make_retrieve(deps))
    g.add_node("validate", n.make_validate(deps))
    g.add_node("generate", n.make_generate(deps))
    g.add_node("answer_direct", n.make_answer_direct(deps))
    g.add_node("not_in_corpus", n.not_in_corpus)
    g.add_node("tool_loop", n.make_tool_loop(deps))
    g.add_node("generate_from_tools", n.make_generate_from_tools(deps))
    g.add_node("finalise", n.finalise)

    g.add_edge(START, "planner")
    g.add_conditional_edges("planner", routes["after_planner"],
                            {"answer_direct": "answer_direct", "retrieve": "retrieve", "tool_loop": "tool_loop"})
    g.add_conditional_edges("tool_loop", routes["after_tool_loop"],
                            {"generate_from_tools": "generate_from_tools", "finalise": "finalise"})
    g.add_edge("generate_from_tools", "finalise")
    g.add_edge("retrieve", "validate")
    g.add_conditional_edges("validate", routes["after_validate"],
                            {"generate": "generate", "planner": "planner", "not_in_corpus": "not_in_corpus"})
    g.add_conditional_edges("generate", routes["after_generate"],
                            {"finalise": "finalise", "planner": "planner", "not_in_corpus": "not_in_corpus"})
    g.add_edge("answer_direct", "finalise")
    g.add_edge("not_in_corpus", "finalise")
    g.add_edge("finalise", END)
    return g.compile()


def rollup(records: list[dict]) -> dict:
    """Sum one interaction's call records. Cost counts billable records only."""
    by_purpose: dict[str, float] = defaultdict(float)
    for r in records:
        if r["billable"]:
            by_purpose[r["purpose"]] += r["cost_usd"]
    llm = [r for r in records if r["kind"] == "llm"]
    return {
        "cost_usd": round(sum(r["cost_usd"] for r in records if r["billable"]), 8),
        "cost_by_purpose": {k: round(v, 8) for k, v in sorted(by_purpose.items())},
        "llm_calls": len(llm),
        "local_cache_hits": sum(r["local_cache"] == "hit" for r in llm),
        "llm_latency_ms": round(sum(r["latency_ms"] for r in llm), 1),
        "local_latency_ms": round(sum(r["latency_ms"] for r in records if r["kind"] == "local_model"), 1),
        "tool_calls_made": sum(r["kind"] == "mcp_tool" for r in records),
        "tool_latency_ms": round(sum(r["latency_ms"] for r in records if r["kind"] == "mcp_tool"), 1),
        "input_tokens": sum(r["input_tokens"] for r in llm),
        "output_tokens": sum(r["output_tokens"] for r in llm),
        "cache_read_input_tokens": sum(r["cache_read_input_tokens"] for r in llm),
        "errors": [r["error"] for r in records if r.get("error")],
        # The first LLM call (the gate) decides whether the cache treated this as a
        # repeat of an EARLIER question. Later hits can be repeats within the same
        # question (identical evidence in two rounds), which is a different thing.
        "first_call_cache": llm[0]["local_cache"] if llm else None,
        "within_question_hits": sum(r["local_cache"] == "hit" for r in llm[1:]),
    }


def answer_question(graph, *, correlation_id: str, question: str, tenant: str = "retail",
                    corpus_version: str, allow_restricted: bool = False, member_id: str = "",
                    tools_hash: str = "", today: str | None = None) -> tuple[AgentState, dict]:
    """One member question, end to end. Returns (final state, per-interaction row)."""
    with tracing.interaction(correlation_id) as ctx:
        t0 = time.perf_counter()
        initial = AgentState(correlation_id=correlation_id, question=question, tenant=tenant,
                             allow_restricted=allow_restricted, corpus_version=corpus_version,
                             member_id=member_id, tools_hash=tools_hash,
                             # Code supplies the date; the model never guesses it. Pinned in evals.
                             today=today or date.today().isoformat())
        state = AgentState(**graph.invoke(initial, {"recursion_limit": RECURSION_LIMIT}))
        latency_ms = round((time.perf_counter() - t0) * 1000, 1)  # wall clock, not a sum of records
        totals = rollup(ctx.records)
        tracing.trace("outcome", outcome=state.outcome, cost_usd=totals["cost_usd"], latency_ms=latency_ms)
    row = {
        "correlation_id": correlation_id,
        "question": question,
        "tenant": tenant,
        "gate_decision": state.gate["decision"] if state.gate else None,
        "gate_reason": state.gate["reason"] if state.gate else "",
        "rounds": len(state.rounds),
        "round_verdicts": [r["verdict"] for r in state.rounds],
        "queries": state.queries,
        "rewrites": state.rewrites,
        # A rewrite led to an answer after an earlier round failed for any reason...
        "rewrite_helped": state.outcome == "answered" and len(state.rounds) > 1,
        # ...and specifically after the generator declined or was blocked (decision 12).
        "rescued_after_decline": state.outcome == "answered" and any(
            r["verdict"] in ("declined", "ungrounded") for r in state.rounds[:-1]),
        "outcome": state.outcome,
        "outcome_reason": state.outcome_reason,
        "answer": state.answer,
        "reply": state.reply,
        "source_line": state.source_line,
        "citations": state.citations,
        # Day 3: the record path
        "member_id": member_id,
        "today": state.today,
        "tools_hash": tools_hash,
        "tool_stop": state.tool_stop,
        "tool_calls": [{k: c[k] for k in ("n", "tool", "arguments", "status", "error", "code", "record_ids")}
                       for c in state.tool_calls],
        "record_citations": state.record_citations,
        "latency_ms": latency_ms,
        **totals,
    }
    return state, row
