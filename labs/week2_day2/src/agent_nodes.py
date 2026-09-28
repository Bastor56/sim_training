"""The agent's nodes and routing functions (spec.md "The agent: Nodes / Edges").

    planner        LLM   round 0: the gate (retrieve or answer directly, and the first search query)
                         later:   the rewrite (a new query, told why earlier rounds failed)
    retrieve       local Day 6 hybrid + rerank, recorded as a $0 local-model step
    validate       local layer 1: rerank score >= tau
    generate       LLM   layer 2: a grounded answer, or a decline; code enforces the citations
    answer_direct  LLM   no documents, no Harbor facts
    not_in_corpus  -     the fixed "won't guess" reply
    finalise       -     the code-built source line (decision 13), on every path

Every LLM call goes through deps.llm_call (llm.call in production, a fake in
tests) and every node writes a trace event. The loop cap is enforced here,
in the routing functions, never by a prompt.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

import llm
import settings
import tracing
import validator
from agent_state import AgentState

NOT_IN_CORPUS_REPLY = "I couldn't find this in Harbor's documents, so I won't guess. A colleague can help."
DIRECT_SOURCE = "Source: general information, not from Harbor's documents."

GATE_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": ["retrieve", "answer_direct"]},
        "reason": {"type": "string"},
        "search_query": {"type": "string"},
    },
    "required": ["decision", "reason", "search_query"],
    "additionalProperties": False,
}
REWRITE_SCHEMA = {
    "type": "object",
    "properties": {"search_query": {"type": "string"}, "reason": {"type": "string"}},
    "required": ["search_query", "reason"],
    "additionalProperties": False,
}
GENERATE_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["answered", "not_in_corpus"]},
        "answer": {"type": "string"},
        "cited_chunk_ids": {"type": "array", "items": {"type": "string"}},
        "reason": {"type": "string"},
    },
    "required": ["status", "answer", "cited_chunk_ids", "reason"],
    "additionalProperties": False,
}
DIRECT_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}


def load_prompt(name: str) -> str:
    return (settings.PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8").strip()


@dataclass
class AgentDeps:
    """Everything the nodes need that isn't per-question state. Injected so tests can swap in fakes."""

    retriever: Any  # day6.Retriever or a fake with the same .search()
    generator: dict  # a settings.GENERATORS role
    llm_call: Callable[..., llm.LLMResult] = llm.call
    gate_role: dict = field(default_factory=lambda: settings.GATE)
    tau: float = settings.TAU_KEEP
    max_rounds: int = settings.MAX_ROUNDS
    top_k: int = settings.TOP_K
    prompts: dict = field(default_factory=lambda: dict(settings.PROMPTS))

    def call(self, purpose: str, role: dict, state: AgentState, user: str, schema: dict) -> llm.LLMResult:
        name = self.prompts[purpose]
        return self.llm_call(purpose, role, system=load_prompt(name), user=user, prompt_version=name,
                             output_schema=schema, question=state.question, scope=scope(state))


def scope(state: AgentState) -> dict:
    """The access and corpus context that goes into every cache key."""
    return {"tenant": state.tenant, "allow_restricted": state.allow_restricted, "current_only": True,
            "corpus_version": state.corpus_version}


# ---------------------------------------------------------------- message builders

def gate_message(state: AgentState) -> str:
    return f"Member message:\n{state.question}"


def _failure(r: dict, tau: float) -> str:
    if r["verdict"] == "poor":
        return f"low relevance (no result scored >= {tau:.2f})"
    if r["verdict"] == "declined":
        return f"declined: {r.get('generator_reason', '')}"
    if r["verdict"] == "ungrounded":
        return "the answer step cited passages it was not given, so its answer was blocked"
    return f"error in the answer step: {r.get('generator_reason', '')}"


def rewrite_message(state: AgentState, tau: float) -> str:
    lines = [f"Member question:\n{state.question}", "", "Attempts so far:"]
    for r in state.rounds:
        results = "; ".join(f"{x['title']} ({x['rerank']:.2f})" for x in r["results"]) or "(nothing returned)"
        lines += [f'Attempt {r["n"]}: query "{r["query"]}"', f"  results: {results}",
                  f"  failed: {_failure(r, tau)}"]
    return "\n".join(lines)


def _chunk_header(c: dict) -> str:
    m = c["metadata"]
    parts = [m.get("title", c["doc_id"])]
    if m.get("version"):
        parts.append(f"version {m['version']}")
    if m.get("effective_date"):
        parts.append(f"effective {m['effective_date']}")
    if m.get("page_start", -1) > 0:
        parts.append(f"p.{m['page_start']}")
    if m.get("section_path"):
        parts.append(f"section: {m['section_path']}")
    return f"[{c['chunk_id']}] " + ", ".join(parts)


def generate_message(state: AgentState) -> str:
    passages = "\n\n".join(f"{_chunk_header(c)}\n{c['text']}" for c in state.kept_chunks)
    return (f"Member question:\n{state.question}\n\nMember tenant: {state.tenant}\n\n"
            f"Evidence passages:\n\n{passages}")


# ---------------------------------------------------------------- source line (decision 13)

def source_line(state: AgentState) -> str:
    if state.outcome == "answered_direct":
        return DIRECT_SOURCE
    if state.outcome != "answered":
        n = len(state.rounds)
        return f"Source: none found. Searched Harbor's documents ({n} round{'s' if n != 1 else ''})."
    by_doc: dict[str, list[dict]] = {}
    for c in state.citations:
        by_doc.setdefault(c["doc_id"], []).append(c)
    entries = []
    for cites in by_doc.values():
        first = cites[0]
        entry = first["title"]
        detail = []
        if first.get("version"):
            detail.append(f"version {first['version']}")
        if first.get("effective_date"):
            detail.append(f"effective {first['effective_date']}")
        if detail:
            entry += f" ({', '.join(detail)})"
        pages = sorted({c["page"] for c in cites if c.get("page", -1) > 0})
        if pages:
            entry += ", p." + ", ".join(str(p) for p in pages)
        # A section named the same as the document adds nothing (seen on the fee schedule).
        sections = list(dict.fromkeys(c["section"] for c in cites if c.get("section") and c["section"] != c["title"]))
        if sections:
            entry += ", " + "; ".join(sections)
        if any(c.get("generated") for c in cites):
            entry += " [includes a model-generated figure caption]"
        entries.append(entry)
    return "Source: " + " | ".join(entries)


def _citation(c: dict) -> dict:
    m = c["metadata"]
    return {"chunk_id": c["chunk_id"], "doc_id": c["doc_id"], "title": m.get("title", c["doc_id"]),
            "version": m.get("version", ""), "effective_date": m.get("effective_date", ""),
            "page": m.get("page_start", -1), "section": (m.get("section_path") or "").split(" > ")[-1],
            "generated": bool(m.get("contains_generated_text", False)),
            # For grading only: quote matching needs the text; the leak check needs the labels.
            "tenant": m.get("tenant", ""), "sensitivity": m.get("sensitivity", ""), "text": c["text"]}


# ---------------------------------------------------------------- nodes

def make_planner(deps: AgentDeps) -> Callable[[AgentState], dict]:
    def planner(state: AgentState) -> dict:
        if state.gate is None:  # round 0: the gate
            try:
                data = deps.call("gate", deps.gate_role, state, gate_message(state), GATE_SCHEMA).data
            except llm.LLMError as e:
                # Fail safe: when unsure, look it up. Retrieval can still end in not_in_corpus.
                data = {"decision": "retrieve", "reason": f"gate error, defaulting to retrieve ({e})",
                        "search_query": state.question}
            query = (data.get("search_query") or "").strip() or state.question
            tracing.trace("gate", decision=data["decision"], reason=data["reason"],
                          search_query=query if data["decision"] == "retrieve" else "")
            update: dict = {"gate": data}
            if data["decision"] == "retrieve":
                update["queries"] = state.queries + [query]
            return update

        # after a failed round: the rewrite
        try:
            data = deps.call("rewrite", deps.gate_role, state, rewrite_message(state, deps.tau), REWRITE_SCHEMA).data
            new_query = data["search_query"].strip() or state.question
            reason = data["reason"]
        except llm.LLMError as e:
            new_query, reason = state.question, f"rewrite error, retrying with the member's own words ({e})"
        repeated = new_query.casefold() in {q.casefold() for q in state.queries}
        n = state.round + 1
        tracing.trace("rewrite", round=n, new_query=new_query, reason=reason, repeated=repeated)
        return {"rewrites": state.rewrites + [{"n": n, "new_query": new_query, "reason": reason,
                                               "repeated": repeated}],
                "queries": state.queries + [new_query]}

    return planner


def make_retrieve(deps: AgentDeps) -> Callable[[AgentState], dict]:
    def retrieve(state: AgentState) -> dict:
        n, query = state.round + 1, state.queries[-1]
        t0 = time.perf_counter()
        response = deps.retriever.search(query, mode=settings.RETRIEVAL_MODE, tenant=state.tenant,
                                         allow_restricted=state.allow_restricted, current_only=True,
                                         top_k=deps.top_k)
        ms = (time.perf_counter() - t0) * 1000
        results = [{"chunk_id": r.chunk_id, "doc_id": r.metadata["doc_id"], "title": r.metadata.get("title", ""),
                    "rerank": round(float(r.score), 4), "text": r.text, "metadata": r.metadata}
                   for r in response.results]
        tracing.record_local("retrieve", ms, round=n, timings_ms=getattr(response, "timings_ms", {}))
        tracing.trace("retrieve", round=n, query=query, top=[[r["doc_id"], r["rerank"]] for r in results],
                      ms=round(ms, 1))
        summary = [{k: r[k] for k in ("chunk_id", "doc_id", "title", "rerank")} for r in results]
        return {"round": n, "current_results": results,
                "rounds": state.rounds + [{"n": n, "query": query, "results": summary, "kept": [],
                                           "verdict": None, "generator_reason": ""}]}

    return retrieve


def make_validate(deps: AgentDeps) -> Callable[[AgentState], dict]:
    def validate(state: AgentState) -> dict:
        kept, verdict = validator.validate(state.current_results, deps.tau)
        tracing.trace("validate", round=state.round, kept=len(kept), verdict=verdict, tau_keep=deps.tau)
        last = {**state.rounds[-1], "kept": [c["chunk_id"] for c in kept], "verdict": verdict}
        return {"kept_chunks": kept, "rounds": state.rounds[:-1] + [last]}

    return validate


def make_generate(deps: AgentDeps) -> Callable[[AgentState], dict]:
    def generate(state: AgentState) -> dict:
        kept_ids = {c["chunk_id"] for c in state.kept_chunks}
        try:
            data = deps.call("generate", deps.generator, state, generate_message(state), GENERATE_SCHEMA).data
        except llm.LLMError as e:
            data = {"status": "error", "answer": "", "cited_chunk_ids": [], "reason": str(e)}
        cited = list(dict.fromkeys(data.get("cited_chunk_ids") or []))
        if data["status"] == "answered" and cited and set(cited) <= kept_ids:
            verdict = "answered"
        elif data["status"] == "answered":
            verdict = "ungrounded"  # cited nothing, or a chunk it was never given: blocked
        elif data["status"] == "not_in_corpus":
            verdict = "declined"
        else:
            verdict = "error"
        tracing.trace("generate", round=state.round, status=data["status"], verdict=verdict, cited=cited,
                      reason=data.get("reason", ""))
        last = {**state.rounds[-1], "generator_reason": data.get("reason", "")}
        if verdict == "answered":
            by_id = {c["chunk_id"]: c for c in state.kept_chunks}
            return {"outcome": "answered", "answer": data["answer"].strip(),
                    "outcome_reason": data.get("reason", ""),
                    "citations": [_citation(by_id[cid]) for cid in cited], "rounds": state.rounds[:-1] + [last]}
        last["verdict"] = verdict  # a failed round (decision 12)
        return {"rounds": state.rounds[:-1] + [last]}

    return generate


def make_answer_direct(deps: AgentDeps) -> Callable[[AgentState], dict]:
    def answer_direct(state: AgentState) -> dict:
        data = deps.call("direct_answer", deps.generator, state, gate_message(state), DIRECT_SCHEMA).data
        tracing.trace("direct_answer", chars=len(data["answer"]))
        return {"outcome": "answered_direct", "answer": data["answer"].strip(),
                "outcome_reason": state.gate["reason"]}

    return answer_direct


def not_in_corpus(state: AgentState) -> dict:
    verdicts = [r["verdict"] for r in state.rounds]
    last = state.rounds[-1] if state.rounds else {}
    if last.get("verdict") == "poor":
        reason = f"no chunk scored >= tau after {len(verdicts)} rounds"
    else:
        reason = f"answer step did not answer in round {len(verdicts)}: {last.get('generator_reason', '')}"
    tracing.trace("not_in_corpus", rounds=len(verdicts), verdicts=verdicts, reason=reason)
    return {"outcome": "not_in_corpus", "outcome_reason": reason, "answer": ""}


def finalise(state: AgentState) -> dict:
    line = source_line(state)
    body = state.answer if state.outcome in ("answered", "answered_direct") else NOT_IN_CORPUS_REPLY
    return {"source_line": line, "reply": f"{body}\n\n{line}"}


# ---------------------------------------------------------------- routing (the loop cap lives here)

def make_routes(deps: AgentDeps) -> dict[str, Callable[[AgentState], str]]:
    def after_planner(state: AgentState) -> str:
        if state.round == 0 and state.gate and state.gate["decision"] == "answer_direct":
            return "answer_direct"
        return "retrieve"

    def after_validate(state: AgentState) -> str:
        if state.rounds[-1]["verdict"] == "usable":
            return "generate"
        return "planner" if state.round < deps.max_rounds else "not_in_corpus"

    def after_generate(state: AgentState) -> str:
        if state.outcome == "answered":
            return "finalise"
        return "planner" if state.round < deps.max_rounds else "not_in_corpus"

    return {"after_planner": after_planner, "after_validate": after_validate, "after_generate": after_generate}
