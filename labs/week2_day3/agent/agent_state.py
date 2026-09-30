"""LangGraph state for one member question (spec.md "The agent: State").

One graph.invoke() handles one single-turn question from start to finish,
so no checkpointer is needed (unlike week 1 day 4's multi-turn chat).
Nothing is carried between questions, which is what Harbor's "memory holds
only what the member said in this conversation" requires today.

Nodes return *replacement* values for the fields they change (for example
`rounds=state.rounds + [new_round]`), never mutate the state in place, so
each step's output is plain data that can be traced and tested.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AgentState:
    correlation_id: str
    question: str
    tenant: str = "retail"
    allow_restricted: bool = False  # always False in member-facing runs
    corpus_version: str = ""  # part of every cache key (see llm_cache.py)

    round: int = 0  # retrieval rounds done so far (0-3)
    gate: dict | None = None  # {decision, reason, search_query}
    queries: list[str] = field(default_factory=list)  # every search query issued, in order
    # Per round: {n, query, results: [{chunk_id, doc_id, title, rerank}], kept: [chunk_id],
    #             verdict: "usable" | "poor" | "declined" | "ungrounded" | "error", generator_reason}
    rounds: list[dict] = field(default_factory=list)
    rewrites: list[dict] = field(default_factory=list)  # {n, new_query, reason}
    current_results: list[dict] = field(default_factory=list)  # this round's results, with text + metadata
    kept_chunks: list[dict] = field(default_factory=list)  # this round's usable chunks (to the generator)

    # --- the record path (Day 3) ---
    member_id: str = ""  # the signed-in member for this conversation ("" = none)
    today: str = ""  # ISO date the record path treats as "today" (milestone 7: "last week" needs it); set by code
    tools_hash: str = ""  # fingerprint of the tool list the agent was shown (part of the gate's cache key)
    # Per MCP call: {n, tool, arguments, status: ok|error|refused|not_offered, error, code,
    #                record_ids, lookup, source, latency_ms}
    tool_calls: list[dict] = field(default_factory=list)
    tool_results: list[dict] = field(default_factory=list)  # the ok calls' data + source, for the answer step
    tool_stop: str = ""  # "done" (model stopped) | "cap" (MAX_TOOL_ROUNDS) | "no_tools" | "error"

    # "answered" | "answered_direct" | "not_in_corpus"  (documents, Day 2)
    # "answered_from_records" | "records_cannot_answer" | "records_blocked" | "records_unavailable"  (Day 3)
    outcome: str | None = None
    outcome_reason: str = ""
    answer: str = ""  # the model's prose only: what the judge grades
    source_line: str = ""  # added by code (decision 13)
    reply: str = ""  # what the member sees: answer (or the fixed not-in-corpus text) + source line
    citations: list[dict] = field(default_factory=list)
    record_citations: list[dict] = field(default_factory=list)  # Day 3: {record_id, system, record_type, tool, ...}
