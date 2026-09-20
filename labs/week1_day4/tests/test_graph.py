import context  # noqa: F401  -- must be first: puts src/ and mock_crm/ on sys.path

import httpx

from conversation_state import resolve_other_account
from decision import Decision
from graph import bootstrap_session, build_graph
from tool_client import CRMClient


class _ForbiddenCRMClient:
    """Stands in wherever a test wants to prove the tool node was never
    reached at all -- any attribute access returns a function that
    raises, so a wrongly-taken "tool" edge fails loudly instead of
    silently doing nothing."""

    def __getattr__(self, name):
        def _raise(*_args, **_kwargs):
            raise AssertionError(f"tool_node should not have called {name}() for this decision")

        return _raise


def _live_crm_client(mock_crm_base_url: str) -> CRMClient:
    # sleep is a no-op here (as in test_tool_client.py) so a test that
    # happens to hit a fixture-flagged fault and exhausts real retries
    # doesn't also eat real backoff wall-clock time.
    return CRMClient(httpx.Client(base_url=mock_crm_base_url, timeout=1.0), sleep=lambda _seconds: None)


def _scripted_decide(state, user_message, customer_accounts):
    """Stands in for decision.decide()'s LLM call -- no network call, but
    real account-resolution logic via conversation_state.resolve_other_account,
    so "the other one" is genuinely resolved from conversation history, not
    hardcoded. Mirrors day 3's test_graph.py fake_planner pattern."""
    message = user_message.lower()
    if "other" in message:
        account_id = resolve_other_account(state, [a["account_id"] for a in customer_accounts])
        return Decision(
            needs_tool=True,
            tool="get_account",
            account_id=account_id,
            resolution_error=None if account_id else "ambiguous which account",
            reasoning="scripted: the other one",
        )
    if "balance" in message:
        return Decision(needs_tool=True, tool="get_account", account_id="ACC-2001", reasoning="scripted: balance")
    return Decision(needs_tool=False, reasoning="scripted: no data needed")


# -- the lab's own "Done when": one full turn end-to-end against a live
# mock CRM, returning a composed reply. ------------------------------


def test_full_turn_against_live_mock_crm_returns_composed_reply(mock_crm_base_url):
    crm = _live_crm_client(mock_crm_base_url)
    graph = build_graph(decide_fn=_scripted_decide, crm_client=crm)

    initial = bootstrap_session(crm, session_id="sess-full-turn", customer_id="CUST-1001")
    initial["pending_user_message"] = "what's my balance?"
    config = {"configurable": {"thread_id": "sess-full-turn"}}

    result = graph.invoke(initial, config=config)

    assert len(result["turns"]) == 1
    turn = result["turns"][0]
    assert turn.tool_outcome.status == "found"
    assert "4210.55" in turn.reply


def test_multi_turn_conversation_state_persists_via_checkpointer(mock_crm_base_url):
    crm = _live_crm_client(mock_crm_base_url)
    graph = build_graph(decide_fn=_scripted_decide, crm_client=crm)

    initial = bootstrap_session(crm, session_id="sess-multi-turn", customer_id="CUST-1001")
    initial["pending_user_message"] = "what's my balance?"
    config = {"configurable": {"thread_id": "sess-multi-turn"}}

    first = graph.invoke(initial, config=config)
    assert first["turns"][-1].referenced_account_id == "ACC-2001"

    # No session_id/customer_id/customer_accounts supplied this time --
    # the checkpointer (keyed by thread_id) is what makes those, and
    # turn 1, available to this second invoke() call at all.
    second = graph.invoke({"pending_user_message": "and what about the other one?"}, config=config)

    assert len(second["turns"]) == 2
    assert second["turns"][-1].referenced_account_id == "ACC-2002"
    assert "15320.10" in second["turns"][-1].reply


def test_no_tool_needed_skips_tool_node_entirely():
    def scripted_no_call(state, user_message, customer_accounts):
        return Decision(needs_tool=False, reasoning="just a greeting")

    def fake_compose(decision, outcome, user_message, state):
        return "Fake direct reply"

    graph = build_graph(decide_fn=scripted_no_call, compose_fn=fake_compose, crm_client=_ForbiddenCRMClient())

    initial = {"session_id": "sess-no-tool", "customer_id": "CUST-1001", "pending_user_message": "hi there!"}
    config = {"configurable": {"thread_id": "sess-no-tool"}}
    result = graph.invoke(initial, config=config)

    turn = result["turns"][0]
    assert turn.reply == "Fake direct reply"
    assert turn.tool_outcome is None


def test_unresolved_account_reference_skips_tool_and_asks_for_clarification():
    def scripted_ambiguous(state, user_message, customer_accounts):
        return Decision(
            needs_tool=True,
            tool="get_account",
            account_id=None,
            resolution_error="this customer has more than one account and none was specified",
            reasoning="ambiguous",
        )

    graph = build_graph(decide_fn=scripted_ambiguous, crm_client=_ForbiddenCRMClient())

    initial = {
        "session_id": "sess-ambiguous",
        "customer_id": "CUST-1001",
        "customer_accounts": [{"account_id": "ACC-2001", "type": "checking"}, {"account_id": "ACC-2002", "type": "savings"}],
        "pending_user_message": "what's my balance?",
    }
    config = {"configurable": {"thread_id": "sess-ambiguous"}}
    result = graph.invoke(initial, config=config)

    turn = result["turns"][0]
    assert turn.tool_outcome is None
    assert "more than one account" in turn.reply


def test_tool_failure_produces_graceful_reply_not_exception(mock_crm_base_url):
    crm = _live_crm_client(mock_crm_base_url)

    def scripted_faulty_account(state, user_message, customer_accounts):
        return Decision(needs_tool=True, tool="get_account", account_id="ACC-2004", reasoning="scripted: faulty account")

    graph = build_graph(decide_fn=scripted_faulty_account, crm_client=crm)
    initial = bootstrap_session(crm, session_id="sess-fault", customer_id="CUST-1003")
    initial["pending_user_message"] = "what's my balance?"
    config = {"configurable": {"thread_id": "sess-fault"}}

    result = graph.invoke(initial, config=config)

    turn = result["turns"][0]
    assert turn.tool_outcome.status == "unavailable"
    assert "trouble reaching" in turn.reply
