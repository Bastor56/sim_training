"""The agent's nodes and routing functions (spec.md "The agent: Nodes / Edges").

Copied from Day 2 and extended on Day 3 with the record path (spec.md "The agent"):

    planner        LLM   round 0: the gate (retrieve / use_tool / answer directly, and the first search query)
                         later:   the rewrite (a new query, told why earlier rounds failed)
    tool_loop      LLM   Day 3: Claude native tool use over the tools the MCP server advertised,
                         at most MAX_TOOL_ROUNDS rounds (cap in code); every call goes through the gateway
    generate_from_tools  LLM   Day 3: an answer from the record results only; code enforces the citations
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

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import figures
import llm
import settings
import tracing
import validator
from agent_state import AgentState

NOT_IN_CORPUS_REPLY = "I couldn't find this in Harbor's documents, so I won't guess. A colleague can help."
DIRECT_SOURCE = "Source: general information, not from Harbor's documents."

# Day 3: fixed replies for the record path, used when no model-written answer may be shown.
RECORDS_UNAVAILABLE_REPLY = ("I couldn't check your records just now, so I won't guess. "
                             "A colleague in the contact centre can help.")
RECORDS_BLOCKED_REPLY = ("I couldn't confirm that from your records, so I won't guess. "
                         "A colleague in the contact centre can help.")
NO_MEMBER_REPLY = ("I can only look up your own records once you're signed in. "
                   "A colleague in the contact centre can help.")
SYSTEM_NAMES = {"harbor_crm": "Harbor CRM", "harbor_core_banking": "Harbor core banking"}
STATUS_WORDS = {"ok": "checked", "error": "failed", "refused": "not permitted", "not_offered": "not available here"}

GATE_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": ["retrieve", "use_tool", "answer_direct"]},
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
RECORDS_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["answered", "cannot_answer"]},
        "answer": {"type": "string"},
        "cited_record_ids": {"type": "array", "items": {"type": "string"}},
        "reason": {"type": "string"},
    },
    "required": ["status", "answer", "cited_record_ids", "reason"],
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
    # --- Day 3: the record path ---
    gateway: Any = None  # mcp_gateway.MCPGateway (or a fake with list_tools / call_tool); None = no records
    tool_role: dict = field(default_factory=lambda: settings.TOOL_SELECT)
    max_tool_rounds: int = settings.MAX_TOOL_ROUNDS
    allowed_tools: frozenset[str] | None = settings.CLIENT_ALLOWED_TOOLS

    def visible_tools(self) -> list:
        """The discovered tools the model may be shown. The allow-list only HIDES
        tools from the model; the server still decides what is permitted."""
        if self.gateway is None:
            return []
        return [t for t in self.gateway.list_tools() if self.allowed_tools is None or t.name in self.allowed_tools]

    def call(self, purpose: str, role: dict, state: AgentState, user: str, schema: dict, *,
             system_extra: str = "", cache: bool = True) -> llm.LLMResult:
        name = self.prompts[purpose]
        system = load_prompt(name) + (f"\n\n{system_extra}" if system_extra else "")
        return self.llm_call(purpose, role, system=system, user=user, prompt_version=name,
                             output_schema=schema, question=state.question, scope=scope(state), cache=cache)

    def call_tools(self, state: AgentState, messages: list[dict], tools: list[dict]) -> llm.LLMResult:
        name = self.prompts["tool_select"]
        return self.llm_call("tool_select", self.tool_role, system=load_prompt(name), user=messages[0]["content"],
                             prompt_version=name, messages=messages, tools=tools, question=state.question,
                             scope=scope(state), cache=False)


def scope(state: AgentState) -> dict:
    """The access and corpus context that goes into every cache key."""
    return {"tenant": state.tenant, "allow_restricted": state.allow_restricted, "current_only": True,
            "corpus_version": state.corpus_version, "tools_hash": state.tools_hash}


# ---------------------------------------------------------------- message builders

def gate_message(state: AgentState) -> str:
    return f"Member message:\n{state.question}"


def tools_section(tools: list) -> str:
    """Appended to the gate's prompt at runtime: what the record server offers right now.
    Built from discovery, so a tool added on the server appears here with no prompt edit (R2)."""
    if not tools:
        return "Record tools available for this member: none. Never choose \"use_tool\"."
    lines = ["Record tools available for this member (advertised by Harbor's record server):"]
    for t in sorted(tools, key=lambda t: t.name):
        # The FULL description, whitespace collapsed. Not just its first line: the gate must see what a
        # tool does NOT return ("Does not return spending limits") to know when no tool fits
        # (milestone 8: a first-line cut hid exactly that sentence).
        description = " ".join((t.description or "(no description)").split())
        lines.append(f"- {t.name}: {description}")
    return "\n".join(lines)


def _today_line(state: AgentState) -> str:
    return f"Today's date: {state.today}" if state.today else "Today's date: unknown"


def tool_select_message(state: AgentState) -> str:
    return f"Signed-in member: {state.member_id}\n{_today_line(state)}\n\nMember message:\n{state.question}"


def _citable_ids(call: dict) -> set[str]:
    """What an answer may cite from one successful call: the records it returned, plus the ID it
    looked up (so "no transactions on ACC-2003" can cite ACC-2003 although no record came back)."""
    return set(call["record_ids"]) | {str(v) for v in call["lookup"].values() if isinstance(v, str)}


def records_message(state: AgentState) -> str:
    by_i = {r["i"]: r for r in state.tool_results}
    lines = [f"Signed-in member: {state.member_id}", _today_line(state), "", f"Member message:\n{state.question}", "",
             "Record results:"]
    if not state.tool_calls:
        lines.append("(no lookups were made)")
    for c in state.tool_calls:
        head = f"[{c['i']}] {c['tool']}({json.dumps(c['arguments'], sort_keys=True)})"
        if c["status"] == "ok":
            ids = ", ".join(sorted(_citable_ids(c))) or "(none)"
            lines += [f"{head} -> ok. Record IDs you may cite: {ids}",
                      json.dumps(by_i[c["i"]]["data"], ensure_ascii=False)]
        elif c["status"] == "refused":
            lines.append(f"{head} -> not permitted for this assistant: {c['error']}")
        elif c["status"] == "not_offered":
            lines.append(f"{head} -> not available to this assistant")
        else:
            lines.append(f"{head} -> failed: {c['error']}")
    return "\n".join(lines)


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

def records_source_line(state: AgentState) -> str:
    """Decision 13 for the record path: named by code from the server-stamped `source` blocks."""
    if state.outcome == "answered_from_records" and state.record_citations:
        entries = list(dict.fromkeys(
            f"{SYSTEM_NAMES.get(c['system'], c['system'])}, {c['record_type']} {c['record_id']} ({c['tool']})"
            for c in state.record_citations))
        last = max(state.record_citations, key=lambda c: c["fetched_at"])
        return (f"Source: {' | '.join(entries)}. Retrieved via {last['server']} {last['server_version']} "
                f"at {last['fetched_at']}.")
    if not state.tool_calls:
        return "Source: none. Harbor's records could not be checked."
    tried = ", ".join(f"{c['tool']} ({STATUS_WORDS.get(c['status'], c['status'])})" for c in state.tool_calls)
    return f"Source: none. Harbor's records were checked: {tried}."


def source_line(state: AgentState) -> str:
    if (state.outcome or "").startswith("records_") or state.outcome == "answered_from_records":
        return records_source_line(state)
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
            tools = deps.visible_tools()
            try:
                data = deps.call("gate", deps.gate_role, state, gate_message(state), GATE_SCHEMA,
                                 system_extra=tools_section(tools)).data
            except llm.LLMError as e:
                # Fail safe: when unsure, look it up. Retrieval can still end in not_in_corpus.
                data = {"decision": "retrieve", "reason": f"gate error, defaulting to retrieve ({e})",
                        "search_query": state.question}
            query = (data.get("search_query") or "").strip() or state.question
            tracing.trace("gate", decision=data["decision"], reason=data["reason"],
                          search_query=query if data["decision"] == "retrieve" else "",
                          tools_hash=state.tools_hash, tools_offered=sorted(t.name for t in tools))
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


def make_tool_loop(deps: AgentDeps) -> Callable[[AgentState], dict]:
    def tool_loop(state: AgentState) -> dict:
        tools = deps.visible_tools()
        if not tools:
            tracing.trace("tool_loop", stop="no_tools", tool_calls=0)
            return {"tool_stop": "no_tools", "outcome": "records_unavailable",
                    "outcome_reason": "no record tools are available to this assistant"}
        if not state.member_id:
            tracing.trace("tool_loop", stop="no_member", tool_calls=0)
            return {"tool_stop": "no_member", "outcome": "records_cannot_answer", "answer": NO_MEMBER_REPLY,
                    "outcome_reason": "no signed-in member, so no records to look up"}

        offered = {t.name for t in tools}
        definitions = [t.for_claude() for t in tools]
        messages: list[dict] = [{"role": "user", "content": tool_select_message(state)}]
        calls: list[dict] = []
        results: list[dict] = []
        stop = "done"
        for n in range(1, deps.max_tool_rounds + 1):
            try:
                res = deps.call_tools(state, messages, definitions)
            except llm.LLMError as e:
                stop = "error"
                tracing.trace("tool_select", round=n, requested=[], error=str(e))
                break
            uses = res.tool_uses
            tracing.trace("tool_select", round=n, requested=[u["name"] for u in uses], note=res.text[:300])
            if not uses:
                break
            messages.append({"role": "assistant", "content": res.blocks})
            content = []
            for use in uses:
                call, data = _run_tool(deps, use, offered, n, i=len(calls) + 1)
                calls.append(call)
                if call["status"] == "ok":
                    results.append({"i": call["i"], "data": data, "source": call["source"]})
                    payload = {"record_ids": call["record_ids"], "data": data}
                elif call["status"] == "not_offered":
                    payload = {"error": "that tool is not available to this assistant"}
                else:
                    payload = {"error": call["error"]}
                content.append({"type": "tool_result", "tool_use_id": use["id"],
                                "content": json.dumps(payload, ensure_ascii=False),
                                "is_error": call["status"] != "ok"})
            messages.append({"role": "user", "content": content})
            if n == deps.max_tool_rounds:
                stop = "cap"  # the cap lives here, in code, never in the prompt
        tracing.trace("tool_loop", stop=stop, tool_calls=len(calls),
                      statuses=[c["status"] for c in calls])
        update: dict = {"tool_calls": calls, "tool_results": results, "tool_stop": stop}
        if stop == "error" and not calls:
            update.update(outcome="records_unavailable", outcome_reason="the tool-selection step failed")
        return update

    return tool_loop


def _run_tool(deps: AgentDeps, use: dict, offered: set[str], n: int, i: int) -> tuple[dict, Any]:
    """One requested tool call. A tool the model wasn't shown is never sent to the server."""
    name, arguments = use["name"], dict(use.get("input") or {})
    call = {"i": i, "n": n, "tool": name, "arguments": arguments, "status": "not_offered", "error": "",
            "code": None, "record_ids": [], "lookup": {}, "source": None, "latency_ms": 0.0}
    data = None
    if name in offered:
        result = deps.gateway.call_tool(name, arguments)
        source = result.source or {}
        call.update(status=result.status, error=result.error, code=result.code, record_ids=list(result.record_ids),
                    lookup=dict(source.get("lookup") or {}), source=result.source or None,
                    latency_ms=result.latency_ms)
        data = result.data
        tracing.record_tool(name, result.latency_ms, status=result.status, record_ids=call["record_ids"],
                            error=result.error or None)
    tracing.trace("tool_call", round=n, tool=name, arguments=arguments, status=call["status"],
                  error=call["error"], code=call["code"], record_ids=call["record_ids"], latency_ms=call["latency_ms"])
    return call, data


def make_generate_from_tools(deps: AgentDeps) -> Callable[[AgentState], dict]:
    def generate_from_tools(state: AgentState) -> dict:
        ok_calls = [c for c in state.tool_calls if c["status"] == "ok"]
        # record ID -> the LATEST successful call that returned or looked it up: its state is the
        # current one (list_cards says "active", a later freeze_card says "frozen").
        citable: dict[str, dict] = {}
        for c in ok_calls:
            for rid in _citable_ids(c):
                citable[rid] = c
        try:
            data = deps.call("generate_from_tools", deps.generator, state, records_message(state), RECORDS_SCHEMA,
                             cache=False).data
        except llm.LLMError as e:
            tracing.trace("generate_from_tools", status="error", verdict="error", cited=[], reason=str(e))
            return {"outcome": "records_unavailable", "outcome_reason": f"answer step failed: {e}"}
        cited = list(dict.fromkeys(data.get("cited_record_ids") or []))
        figure_check = figures.check(data.get("answer", ""), state.tool_results, set(cited))
        if data["status"] == "answered" and cited and set(cited) <= set(citable):
            # Real records cited; now every dollar figure must come from them (milestone 7 decision).
            verdict = "unverified_figure" if figure_check["unverified"] else "answered"
        elif data["status"] == "answered":
            verdict = "ungrounded"  # cited nothing, or an ID no tool returned: blocked
        else:
            # A cannot-answer explanation reaches the member too (tool eval t09), so any figure in
            # it must come from a record some tool returned in this question.
            figure_check = figures.check(data.get("answer", ""), state.tool_results, set(citable))
            verdict = "unverified_figure" if figure_check["unverified"] else "cannot_answer"
        tracing.trace("generate_from_tools", status=data["status"], verdict=verdict, cited=cited,
                      figures=figure_check["figures"], unverified=figure_check["unverified"],
                      reason=data.get("reason", ""))
        if verdict == "answered":
            citations = []
            for rid in cited:
                c = citable[rid]
                src = c["source"] or {}
                returned = rid in c["record_ids"]
                noun = src.get("record_type", "record") if returned else next(
                    (k.removesuffix("_id") for k, v in c["lookup"].items() if v == rid), "record")
                citations.append({"record_id": rid, "record_type": noun, "system": src.get("system", ""),
                                  "tool": c["tool"], "server": src.get("server", ""),
                                  "server_version": src.get("server_version", ""),
                                  "fetched_at": src.get("fetched_at", "")})
            return {"outcome": "answered_from_records", "answer": data["answer"].strip(),
                    "outcome_reason": data.get("reason", ""), "record_citations": citations}
        if verdict == "ungrounded":
            return {"outcome": "records_blocked", "answer": "",
                    "outcome_reason": f"answer cited records no tool returned ({cited}); blocked"}
        if verdict == "unverified_figure":
            return {"outcome": "records_blocked", "answer": "",
                    "outcome_reason": f"answer had figure(s) not in the cited records: "
                                      f"{', '.join('$' + f for f in figure_check['unverified'])}; blocked"}
        return {"outcome": "records_cannot_answer", "answer": data["answer"].strip(),
                "outcome_reason": data.get("reason", "")}

    return generate_from_tools


def not_in_corpus(state: AgentState) -> dict:
    verdicts = [r["verdict"] for r in state.rounds]
    last = state.rounds[-1] if state.rounds else {}
    if last.get("verdict") == "poor":
        reason = f"no chunk scored >= tau after {len(verdicts)} rounds"
    else:
        reason = f"answer step did not answer in round {len(verdicts)}: {last.get('generator_reason', '')}"
    tracing.trace("not_in_corpus", rounds=len(verdicts), verdicts=verdicts, reason=reason)
    return {"outcome": "not_in_corpus", "outcome_reason": reason, "answer": ""}


FIXED_REPLIES = {
    "not_in_corpus": NOT_IN_CORPUS_REPLY,
    "records_blocked": RECORDS_BLOCKED_REPLY,
    "records_unavailable": RECORDS_UNAVAILABLE_REPLY,
}


def finalise(state: AgentState) -> dict:
    line = source_line(state)
    if state.outcome in FIXED_REPLIES:
        body = FIXED_REPLIES[state.outcome]
    else:  # a model-written answer (checked upstream), or a cannot-answer explanation
        body = state.answer or RECORDS_UNAVAILABLE_REPLY
    return {"source_line": line, "reply": f"{body}\n\n{line}"}


# ---------------------------------------------------------------- routing (the loop cap lives here)

def make_routes(deps: AgentDeps) -> dict[str, Callable[[AgentState], str]]:
    def after_planner(state: AgentState) -> str:
        if state.round == 0 and state.gate and state.gate["decision"] == "answer_direct":
            return "answer_direct"
        if state.round == 0 and state.gate and state.gate["decision"] == "use_tool":
            return "tool_loop"
        return "retrieve"

    def after_tool_loop(state: AgentState) -> str:
        return "finalise" if state.outcome else "generate_from_tools"

    def after_validate(state: AgentState) -> str:
        if state.rounds[-1]["verdict"] == "usable":
            return "generate"
        return "planner" if state.round < deps.max_rounds else "not_in_corpus"

    def after_generate(state: AgentState) -> str:
        if state.outcome == "answered":
            return "finalise"
        return "planner" if state.round < deps.max_rounds else "not_in_corpus"

    return {"after_planner": after_planner, "after_validate": after_validate, "after_generate": after_generate,
            "after_tool_loop": after_tool_loop}
