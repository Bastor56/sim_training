"""The record path (use_tool), proved with fakes (spec.md "The agent"; plan.md milestone 6).

As in test_agent_graph.py, every LLM call goes through the REAL wrapper
(llm.call) with a fake Anthropic client, so calls are recorded and priced
as in production. The MCP gateway is a fake with the real gateway's
surface (list_tools / call_tool returning ToolSpec / ToolCall), so these
tests need no server.
"""

import json

import pytest

import agent_graph
import agent_nodes
import fakes
import llm
import settings
from mcp_gateway import ToolCall, ToolSpec
from test_agent_graph import FakeRetriever, purpose_of

CORPUS = "1|test_index"
FETCHED = "2026-09-28T19:05:57Z"


def spec(name, desc, read_only=True, props=None):
    return ToolSpec(name=name, description=desc, read_only=read_only,
                    input_schema={"type": "object", "properties": props or {"x": {"type": "string"}}})


TOOLS = [
    spec("list_member_accounts", "List a member's accounts from core banking.\nMore detail."),
    spec("get_account", "One account's balance, from core banking."),
    spec("list_transactions", "Recent transactions on one account."),
    spec("list_cards", "A member's cards from the CRM."),
    spec("freeze_card", "Freeze a card. CHANGES DATA.", read_only=False),
]


def source(tool, system, record_type, ids, **lookup):
    return {"system": system, "record_type": record_type, "record_ids": ids, "lookup": lookup, "tool": tool,
            "server": "harbor-mcp", "server_version": "0.1.0", "fetched_at": FETCHED}


ACCOUNTS = [{"account_id": "ACC-2001", "type": "checking", "balance": "4210.55"},
            {"account_id": "ACC-2002", "type": "savings", "balance": "15320.10"}]


def ok(tool, data, src):
    return ToolCall(tool=tool, arguments={}, status="ok", data=data, source=src,
                    record_ids=src["record_ids"], latency_ms=12.0)


RESPONSES = {
    "list_member_accounts": lambda args: ok("list_member_accounts", ACCOUNTS, source(
        "list_member_accounts", "harbor_core_banking", "account", ["ACC-2001", "ACC-2002"], member_id=args["member_id"])),
    "get_account": lambda args: ok("get_account", ACCOUNTS[0], source(
        "get_account", "harbor_core_banking", "account", [args["account_id"]], account_id=args["account_id"])),
    "list_transactions": lambda args: ok("list_transactions", [], source(
        "list_transactions", "harbor_core_banking", "transaction", [], account_id=args["account_id"], limit=10)),
    "list_cards": lambda args: ToolCall(tool="list_cards", arguments=args, status="error",
                                        error="The CRM is unavailable right now.", latency_ms=2100.0),
    "freeze_card": lambda args: ToolCall(tool="freeze_card", arguments=args, status="refused", code=-32003,
                                         error="forbidden: member_assistant may not call freeze_card", latency_ms=4.0),
}


class FakeGateway:
    def __init__(self, tools=TOOLS):
        self.tools, self.calls = list(tools), []

    def list_tools(self):
        return list(self.tools)

    def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return RESPONSES[name](arguments)


class Script:
    """Per-purpose queues. Structured purposes take JSON payloads; tool_select takes fake responses."""

    def __init__(self, **queues):
        self.queues = {k: list(v) for k, v in queues.items()}
        self.log: list[tuple[str, dict]] = []

    def __call__(self, kwargs):
        purpose = purpose_of(kwargs)
        self.log.append((purpose, kwargs))
        queue = self.queues[purpose]
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if purpose == "tool_select":
            return item
        return fakes.response(item, input_tokens=1000, output_tokens=100)

    def of(self, purpose):
        return [k for p, k in self.log if p == purpose]


GATE_TOOL = {"decision": "use_tool", "reason": "asks for their own balance", "search_query": ""}
STOP = fakes.tool_response(text="found the checking balance")


def answered(*ids, text="Your checking account ending 2001 has $4,210.55."):
    return {"status": "answered", "answer": text, "cited_record_ids": list(ids), "reason": "from the account record"}


CANNOT = {"status": "cannot_answer", "answer": "I can't freeze cards here, but the contact centre can do it now.",
          "cited_record_ids": [], "reason": "freeze not permitted for this assistant"}


def run(lab, script, gateway=None, question="What's my checking balance?", member="M-1001", **deps_kw):
    lab["client"].default = script
    deps = agent_nodes.AgentDeps(retriever=FakeRetriever([[]]), generator=settings.GENERATORS["haiku"],
                                 gateway=gateway if gateway is not None else FakeGateway(), **deps_kw)
    graph = agent_graph.build_graph(deps)
    return agent_graph.answer_question(graph, correlation_id="test_run/t", question=question,
                                       corpus_version=CORPUS, member_id=member, tools_hash="h1")


def _jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


# ---------------------------------------------------------------- the happy path

def test_one_tool_round_then_answer(lab):
    script = Script(gate=[GATE_TOOL],
                    tool_select=[fakes.tool_response(("list_member_accounts", {"member_id": "M-1001"})), STOP],
                    generate_from_tools=[answered("ACC-2001")])
    gw = FakeGateway()
    state, row = run(lab, script, gw)
    assert row["outcome"] == "answered_from_records" and state.tool_stop == "done"
    assert gw.calls == [("list_member_accounts", {"member_id": "M-1001"})]
    assert [p for p, _ in script.log] == ["gate", "tool_select", "tool_select", "generate_from_tools"]
    assert state.source_line == ("Source: Harbor core banking, account ACC-2001 (list_member_accounts). "
                                 f"Retrieved via harbor-mcp 0.1.0 at {FETCHED}.")
    assert state.reply == f"{state.answer}\n\n{state.source_line}"
    assert row["tool_calls_made"] == 1 and row["tool_calls"][0]["status"] == "ok"


def test_tool_results_go_back_to_the_model_as_tool_result_blocks(lab):
    script = Script(gate=[GATE_TOOL],
                    tool_select=[fakes.tool_response(("list_member_accounts", {"member_id": "M-1001"}),
                                                     ("list_cards", {"member_id": "M-1001"})), STOP],
                    generate_from_tools=[answered("ACC-2001")])
    run(lab, script)
    second = script.of("tool_select")[1]["messages"]
    assert [m["role"] for m in second] == ["user", "assistant", "user"]
    results = second[2]["content"]
    assert [r["type"] for r in results] == ["tool_result", "tool_result"]
    assert results[0]["is_error"] is False and "ACC-2001" in results[0]["content"]
    assert results[1]["is_error"] is True and "unavailable" in results[1]["content"]


def test_the_model_sees_the_discovered_tools_and_the_member(lab):
    script = Script(gate=[GATE_TOOL], tool_select=[STOP], generate_from_tools=[CANNOT])
    run(lab, script)
    gate_system = script.of("gate")[0]["system"][0]["text"]
    # the full description on one line: what a tool does NOT do matters to routing (milestone 8)
    assert "- list_member_accounts: List a member's accounts from core banking. More detail." in gate_system
    select = script.of("tool_select")[0]
    assert [t["name"] for t in select["tools"]] == [t.name for t in TOOLS]
    assert select["tools"][0]["input_schema"] == TOOLS[0].input_schema
    assert "Signed-in member: M-1001" in select["messages"][0]["content"]


# ---------------------------------------------------------------- limits and failures

def test_tool_loop_stops_at_the_cap_even_if_the_model_keeps_asking(lab):
    keep_asking = fakes.tool_response(("get_account", {"account_id": "ACC-2001"}))
    script = Script(gate=[GATE_TOOL], tool_select=[keep_asking], generate_from_tools=[answered("ACC-2001")])
    gw = FakeGateway()
    state, _ = run(lab, script, gw)
    assert len(script.of("tool_select")) == settings.MAX_TOOL_ROUNDS == 3
    assert len(gw.calls) == 3 and state.tool_stop == "cap"
    assert script.of("generate_from_tools")  # still answers from what it has


def test_refused_action_becomes_a_plain_reply_not_a_crash(lab):
    script = Script(gate=[GATE_TOOL],
                    tool_select=[fakes.tool_response(("freeze_card", {"card_id": "CARD-4001", "reason": "lost"})), STOP],
                    generate_from_tools=[CANNOT])
    state, row = run(lab, script, question="Please freeze my card, I lost it")
    assert row["outcome"] == "records_cannot_answer"
    assert state.reply.startswith("I can't freeze cards here")
    assert state.source_line == "Source: none. Harbor's records were checked: freeze_card (not permitted)."
    assert row["tool_calls"][0]["code"] == -32003
    gen_input = script.of("generate_from_tools")[0]["messages"][0]["content"]
    assert "not permitted for this assistant" in gen_input


def test_citing_a_record_no_tool_returned_is_blocked(lab):
    script = Script(gate=[GATE_TOOL],
                    tool_select=[fakes.tool_response(("list_member_accounts", {"member_id": "M-1001"})), STOP],
                    generate_from_tools=[answered("ACC-7777")])
    state, row = run(lab, script)
    assert row["outcome"] == "records_blocked"
    assert state.reply.startswith(agent_nodes.RECORDS_BLOCKED_REPLY)
    assert "4,210.55" not in state.reply  # the model's unverified text never reaches the member


def test_an_answer_citing_nothing_is_blocked(lab):
    script = Script(gate=[GATE_TOOL],
                    tool_select=[fakes.tool_response(("list_member_accounts", {"member_id": "M-1001"})), STOP],
                    generate_from_tools=[answered()])
    _, row = run(lab, script)
    assert row["outcome"] == "records_blocked"


def test_an_empty_result_can_cite_what_was_looked_up(lab):
    script = Script(gate=[GATE_TOOL],
                    tool_select=[fakes.tool_response(("list_transactions", {"account_id": "ACC-2003"})), STOP],
                    generate_from_tools=[answered("ACC-2003", text="There are no transactions on that account yet.")])
    state, row = run(lab, script, member="M-1002")
    assert row["outcome"] == "answered_from_records"
    assert state.record_citations[0]["record_type"] == "account"
    assert "account ACC-2003 (list_transactions)" in state.source_line


def test_no_tools_available_means_no_tool_loop_calls(lab):
    script = Script(gate=[GATE_TOOL], tool_select=[STOP], generate_from_tools=[CANNOT])
    state, row = run(lab, script, gateway=FakeGateway(tools=[]))
    assert row["outcome"] == "records_unavailable" and script.of("tool_select") == []
    assert "Record tools available for this member: none" in script.of("gate")[0]["system"][0]["text"]
    assert state.reply.startswith(agent_nodes.RECORDS_UNAVAILABLE_REPLY)


def test_no_signed_in_member_means_no_lookups(lab):
    script = Script(gate=[GATE_TOOL], tool_select=[STOP], generate_from_tools=[CANNOT])
    state, _ = run(lab, script, member="")
    assert script.of("tool_select") == [] and state.reply.startswith(agent_nodes.NO_MEMBER_REPLY)


# ---------------------------------------------------------------- the client-side allow-list (R3 demo)

def test_allow_list_hides_tools_from_the_model(lab):
    script = Script(gate=[GATE_TOOL], tool_select=[STOP], generate_from_tools=[CANNOT])
    run(lab, script, allowed_tools=frozenset({"get_account", "list_member_accounts"}))
    assert [t["name"] for t in script.of("tool_select")[0]["tools"]] == ["list_member_accounts", "get_account"]
    assert "freeze_card" not in script.of("gate")[0]["system"][0]["text"]


def test_a_hidden_tool_requested_anyway_is_never_sent_to_the_server(lab):
    script = Script(gate=[GATE_TOOL],
                    tool_select=[fakes.tool_response(("freeze_card", {"card_id": "CARD-4001", "reason": "x"})), STOP],
                    generate_from_tools=[CANNOT])
    gw = FakeGateway()
    state, _ = run(lab, script, gw, allowed_tools=frozenset({"get_account"}))
    assert gw.calls == [] and state.tool_calls[0]["status"] == "not_offered"


# ---------------------------------------------------------------- instrumentation

def test_tool_path_is_never_cached_but_the_gate_is(lab):
    llm.configure(cache_mode="read-write", namespace="t")
    script = Script(gate=[GATE_TOOL],
                    tool_select=[fakes.tool_response(("list_member_accounts", {"member_id": "M-1001"})), STOP],
                    generate_from_tools=[answered("ACC-2001")])
    run(lab, script)
    run(lab, script)  # the same question again
    records = [r for r in _jsonl(lab["run"].dir / "calls.jsonl") if r["kind"] == "llm"]
    by_purpose = {}
    for r in records:
        by_purpose.setdefault(r["purpose"], []).append(r["local_cache"])
    assert by_purpose["gate"] == ["miss", "hit"]
    assert set(by_purpose["tool_select"]) == {"off"} and set(by_purpose["generate_from_tools"]) == {"off"}


def test_tool_calls_are_recorded_and_traced(lab):
    script = Script(gate=[GATE_TOOL],
                    tool_select=[fakes.tool_response(("list_member_accounts", {"member_id": "M-1001"})), STOP],
                    generate_from_tools=[answered("ACC-2001")])
    _, row = run(lab, script)
    records = _jsonl(lab["run"].dir / "calls.jsonl")
    tool_records = [r for r in records if r["kind"] == "mcp_tool"]
    assert len(tool_records) == 1 and tool_records[0]["cost_usd"] == 0.0
    assert tool_records[0]["correlation_id"] == "test_run/t"
    assert row["tool_latency_ms"] == 12.0
    events = [e["event"] for e in _jsonl(lab["run"].dir / "trace.jsonl")]
    assert events == ["gate", "tool_select", "tool_call", "tool_select", "tool_loop", "generate_from_tools", "outcome"]
    gate = _jsonl(lab["run"].dir / "trace.jsonl")[0]
    assert gate["tools_hash"] == "h1" and "freeze_card" in gate["tools_offered"]
    llm_records = [r for r in records if r["kind"] == "llm" and r["purpose"] == "tool_select"]
    assert llm_records[0]["tool_uses"] == ["list_member_accounts"]


def test_document_path_unchanged_with_a_gateway_present(lab):
    gate = {"decision": "answer_direct", "reason": "a greeting", "search_query": ""}
    script = Script(gate=[gate], direct_answer=[{"answer": "Hello!"}], tool_select=[STOP],
                    generate_from_tools=[CANNOT])
    gw = FakeGateway()
    _, row = run(lab, script, gw, question="Hi")
    assert row["outcome"] == "answered_direct" and gw.calls == [] and script.of("tool_select") == []


# ---------------------------------------------------------------- end to end: fake LLM, REAL gateway + server

def test_real_gateway_and_server_end_to_end(lab, tmp_path):
    from mcp_gateway import MCPGateway
    from mcp_harness import RunningServer

    script = Script(gate=[GATE_TOOL],
                    tool_select=[fakes.tool_response(("list_member_accounts", {"member_id": "M-1001"}),
                                                     ("freeze_card", {"card_id": "CARD-4001", "reason": "lost"})),
                                 STOP],
                    generate_from_tools=[answered("ACC-2001")])
    with RunningServer(tmp_path) as srv, MCPGateway(srv.cfg.url, "tok-member") as gw:
        state, row = run(lab, script, gw)
        audit = srv.audit.read()
    assert [(c["tool"], c["status"]) for c in state.tool_calls] == [("list_member_accounts", "ok"),
                                                                   ("freeze_card", "refused")]
    assert row["outcome"] == "answered_from_records"
    assert "Harbor core banking, account ACC-2001 (list_member_accounts)" in state.source_line
    # the server saw exactly what the agent did, and refused the write itself
    assert [(a["tool"], a["decision"], a["outcome"]) for a in audit] == [
        ("list_member_accounts", "allowed", "ok"), ("freeze_card", "denied", "forbidden")]
    # the tools the model was offered are exactly the ones the server advertised
    offered = [t["name"] for t in script.of("tool_select")[0]["tools"]]
    from mcp_harness import EXPECTED_TOOLS
    assert sorted(offered) == EXPECTED_TOOLS


def test_citation_credits_the_latest_call_that_returned_the_record(lab):
    """Milestone 7 finding: list_cards then freeze_card both return CARD-4001. "Has been frozen"
    rests on the freeze result, so the source line must name freeze_card, not the earlier lookup."""
    class FreezingGateway(FakeGateway):
        def call_tool(self, name, arguments):
            self.calls.append((name, arguments))
            card = {"card_id": "CARD-4001", "status": "active" if name == "list_cards" else "frozen"}
            src = source(name, "harbor_crm", "card", ["CARD-4001"],
                         **({"member_id": "M-1001"} if name == "list_cards" else {"card_id": "CARD-4001"}))
            return ok(name, [card] if name == "list_cards" else card, src)

    script = Script(gate=[GATE_TOOL],
                    tool_select=[fakes.tool_response(("list_cards", {"member_id": "M-1001"})),
                                 fakes.tool_response(("freeze_card", {"card_id": "CARD-4001", "reason": "lost"})),
                                 STOP],
                    generate_from_tools=[answered("CARD-4001", text="Your debit card ending 4471 has been frozen.")])
    state, _ = run(lab, script, FreezingGateway())
    assert [c["tool"] for c in state.record_citations] == ["freeze_card"]
    assert "card CARD-4001 (freeze_card)" in state.source_line


def test_code_supplies_todays_date_to_the_record_steps(lab):
    """Milestone 7 finding: "last week" is unanswerable if the model doesn't know today's date."""
    script = Script(gate=[GATE_TOOL],
                    tool_select=[fakes.tool_response(("list_member_accounts", {"member_id": "M-1001"})), STOP],
                    generate_from_tools=[answered("ACC-2001")])
    lab["client"].default = script
    deps = agent_nodes.AgentDeps(retriever=FakeRetriever([[]]), generator=settings.GENERATORS["haiku"],
                                 gateway=FakeGateway())
    state, row = agent_graph.answer_question(agent_graph.build_graph(deps), correlation_id="test_run/d",
                                             question="What did I spend last week?", corpus_version=CORPUS,
                                             member_id="M-1001", today="2026-09-28")
    assert "Today's date: 2026-09-28" in script.of("tool_select")[0]["messages"][0]["content"]
    assert "Today's date: 2026-09-28" in script.of("generate_from_tools")[0]["messages"][0]["content"]
    assert row["today"] == "2026-09-28"
