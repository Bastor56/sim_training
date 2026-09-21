import context  # noqa: F401  -- must be first: puts src/ and mock_crm/ on sys.path

from dataclasses import dataclass
from typing import Any, List

import pytest

from conversation_state import ConversationState
from decision import Decision
from response import compose_reply
from tool_client import ToolOutcome


@dataclass
class FakeBlock:
    text: str
    type: str = "text"


@dataclass
class FakeResponse:
    content: list


class FakeMessagesClient:
    """Stands in for anthropic.Anthropic().messages -- no network call,
    no real model. Mirrors test_decision.py's FakeMessagesClient."""

    def __init__(self, reply_text: str):
        self.reply_text = reply_text
        self.calls: List[dict] = []

    def create(self, **kwargs: Any) -> FakeResponse:
        self.calls.append(kwargs)
        return FakeResponse(content=[FakeBlock(text=self.reply_text)])


def _state() -> ConversationState:
    return ConversationState(session_id="sess-1", customer_id="CUST-1001")


# -- not_found: the day-4 404 failure class, uncovered until now --------


def test_not_found_uses_crm_detail_and_offers_escalation():
    decision = Decision(needs_tool=True, tool="get_account", account_id="ACC-9999")
    outcome = ToolOutcome(status="not_found", detail="No account found with id 'ACC-9999'")
    reply = compose_reply(decision, outcome, "what's the balance on ACC-9999?", _state())
    assert "No account found with id 'ACC-9999'" in reply
    assert "specialist" in reply  # ESCALATION_LINE


def test_not_found_without_detail_falls_back_to_generic_wording():
    decision = Decision(needs_tool=True, tool="get_account", account_id="ACC-9999")
    outcome = ToolOutcome(status="not_found", detail=None)
    reply = compose_reply(decision, outcome, "what's the balance on ACC-9999?", _state())
    assert "I couldn't find that record." in reply


# -- unavailable: confirms the customer never sees internal detail ------


def test_unavailable_reply_is_generic_regardless_of_underlying_cause():
    decision = Decision(needs_tool=True, tool="get_account", account_id="ACC-2004")
    outcome = ToolOutcome(status="unavailable", detail="the CRM returned HTTP 500 for GET /accounts/ACC-2004")
    reply = compose_reply(decision, outcome, "what's my balance?", _state())
    assert "trouble reaching" in reply
    assert "500" not in reply  # internal detail must never leak to the customer


# -- found: the four tool formatters test_graph.py never exercises ------


def test_found_get_customer_formats_profile():
    decision = Decision(needs_tool=True, tool="get_customer")
    outcome = ToolOutcome(status="found", data={"name": "Maria Alvarez", "email": "maria@example.com", "since_date": "2019-03-01"})
    reply = compose_reply(decision, outcome, "who am i?", _state())
    assert "Maria Alvarez" in reply
    assert "maria@example.com" in reply
    assert "2019-03-01" in reply


def test_found_list_customer_accounts_lists_each_account():
    decision = Decision(needs_tool=True, tool="list_customer_accounts")
    outcome = ToolOutcome(
        status="found",
        data=[
            {"account_id": "ACC-2001", "type": "checking", "status": "active"},
            {"account_id": "ACC-2002", "type": "savings", "status": "active"},
        ],
    )
    reply = compose_reply(decision, outcome, "what accounts do I have?", _state())
    assert "ACC-2001" in reply and "ACC-2002" in reply


def test_found_list_customer_accounts_empty_says_so_without_fabricating():
    decision = Decision(needs_tool=True, tool="list_customer_accounts")
    outcome = ToolOutcome(status="found", data=[])
    reply = compose_reply(decision, outcome, "what accounts do I have?", _state())
    assert "don't see any accounts" in reply


def test_found_list_account_transactions_lists_each_transaction():
    decision = Decision(needs_tool=True, tool="list_account_transactions", account_id="ACC-2001")
    outcome = ToolOutcome(status="found", data=[{"date": "2026-09-01", "description": "Coffee shop", "amount": -4.5}])
    reply = compose_reply(decision, outcome, "recent transactions?", _state())
    assert "Coffee shop" in reply and "-4.50" in reply


def test_found_list_account_transactions_empty_says_so_without_fabricating():
    decision = Decision(needs_tool=True, tool="list_account_transactions", account_id="ACC-2003")
    outcome = ToolOutcome(status="found", data=[])
    reply = compose_reply(decision, outcome, "recent transactions?", _state())
    assert "doesn't have any transactions" in reply


def test_found_list_account_cards_lists_each_card():
    decision = Decision(needs_tool=True, tool="list_account_cards", account_id="ACC-2001")
    outcome = ToolOutcome(status="found", data=[{"last_four": "4242", "status": "active"}])
    reply = compose_reply(decision, outcome, "what cards do I have?", _state())
    assert "4242" in reply


def test_found_list_account_cards_empty_says_so_without_fabricating():
    decision = Decision(needs_tool=True, tool="list_account_cards", account_id="ACC-2001")
    outcome = ToolOutcome(status="found", data=[])
    reply = compose_reply(decision, outcome, "what cards do I have?", _state())
    assert "no cards on file" in reply


def test_found_unknown_tool_raises_rather_than_silently_dropping_data():
    decision = Decision(needs_tool=True, tool="ghost_tool")
    outcome = ToolOutcome(status="found", data={"anything": "at all"})
    with pytest.raises(AssertionError):
        compose_reply(decision, outcome, "hello", _state())


# -- clarification: resolution_error short-circuits before any tool_outcome


def test_resolution_error_asks_for_clarification_without_touching_outcome():
    decision = Decision(needs_tool=True, tool="get_account", resolution_error="this customer has more than one account")
    reply = compose_reply(decision, None, "what's my balance?", _state())
    assert "more than one account" in reply
    assert "clarify" in reply


# -- recalled_outcome: replayed through the found templates, no LLM call -


def test_recalled_outcome_formats_via_found_template():
    decision = Decision(
        needs_tool=False,
        tool="get_account",
        account_id="ACC-2001",
        recalled_outcome=ToolOutcome(status="found", data={"type": "checking", "account_id": "ACC-2001", "balance": 4210.55, "status": "active"}),
    )
    reply = compose_reply(decision, None, "what did you say my balance was?", _state())
    assert "4210.55" in reply


def test_recalled_outcome_does_not_call_the_direct_reply_client():
    decision = Decision(
        needs_tool=False,
        tool="get_customer",
        recalled_outcome=ToolOutcome(status="found", data={"name": "Maria Alvarez", "email": "maria@example.com", "since_date": "2019-03-01"}),
    )
    client = FakeMessagesClient("should never be used")

    reply = compose_reply(decision, None, "who am i again?", _state(), client=client)

    assert "Maria Alvarez" in reply
    assert client.calls == []


# -- answer_directly: the only branch that calls the model, and its ------
# explicit instruction never to state an account fact -------------------


def test_direct_reply_uses_stubbed_client_not_the_real_anthropic_client():
    decision = Decision(needs_tool=False, reasoning="just a greeting")
    client = FakeMessagesClient("Happy to help -- what can I do for you today?")

    reply = compose_reply(decision, None, "hi there!", _state(), client=client)

    assert reply == "Happy to help -- what can I do for you today?"
    assert len(client.calls) == 1


def test_direct_reply_system_prompt_forbids_stating_account_facts():
    decision = Decision(needs_tool=False, reasoning="just a greeting")
    client = FakeMessagesClient("Hi! How can I help?")

    compose_reply(decision, None, "hi there!", _state(), client=client)

    system_prompt = client.calls[0]["system"]
    assert "never state or imply any specific balance" in system_prompt


def test_direct_reply_includes_prior_turn_history_in_prompt():
    decision = Decision(needs_tool=False, reasoning="follow-up thanks")
    client = FakeMessagesClient("You're welcome!")
    state = _state()
    turn = state.start_turn(user_message="what's my balance?")
    turn.reply = "Your checking account has a balance of $4210.55 and is currently active."

    compose_reply(decision, None, "thanks so much!", state, client=client)

    user_prompt = client.calls[0]["messages"][0]["content"]
    assert "what's my balance?" in user_prompt
    assert "4210.55" in user_prompt
