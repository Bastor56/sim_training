import context  # noqa: F401  -- must be first: puts src/ and mock_crm/ on sys.path

import json
from dataclasses import dataclass
from typing import Any, List

import pytest

from conversation_state import ConversationState
from decision import DecisionContractError, decide, validate_decision

MARIA_ACCOUNTS = [
    {"account_id": "ACC-2001", "type": "checking"},
    {"account_id": "ACC-2002", "type": "savings"},
]


@dataclass
class FakeBlock:
    text: str
    type: str = "text"


@dataclass
class FakeResponse:
    content: list


class FakeMessagesClient:
    """Stands in for anthropic.Anthropic().messages -- no network call,
    no real model. Mirrors day 2's test_planner.py FakeMessagesClient."""

    def __init__(self, reply_text: str):
        self.reply_text = reply_text
        self.calls: List[dict] = []

    def create(self, **kwargs: Any) -> FakeResponse:
        self.calls.append(kwargs)
        return FakeResponse(content=[FakeBlock(text=self.reply_text)])


def _fake_client(decision_dict: dict) -> FakeMessagesClient:
    return FakeMessagesClient(json.dumps(decision_dict))


def _state(*referenced_account_ids: str) -> ConversationState:
    state = ConversationState(session_id="sess-1", customer_id="CUST-1001")
    for account_id in referenced_account_ids:
        turn = state.start_turn(user_message=f"about {account_id}")
        turn.referenced_account_id = account_id
    return state


# -- validate_decision ---------------------------------------------------


def test_validate_answer_directly_passes():
    action = {"action": "answer_directly", "reasoning": "just a greeting"}
    assert validate_decision(action) == action


def test_validate_call_tool_customer_scoped_passes_without_account_reference():
    action = {"action": "call_tool", "tool": "get_customer", "reasoning": "wants their profile"}
    assert validate_decision(action) == action


def test_validate_non_dict_raises():
    with pytest.raises(DecisionContractError):
        validate_decision(["not", "a", "dict"])


def test_validate_unknown_action_kind_raises():
    with pytest.raises(DecisionContractError):
        validate_decision({"action": "wander_off"})


def test_validate_unregistered_tool_raises():
    with pytest.raises(DecisionContractError):
        validate_decision({"action": "call_tool", "tool": "delete_everything", "reasoning": "..."})


def test_validate_account_scoped_tool_invalid_reference_raises():
    with pytest.raises(DecisionContractError):
        validate_decision(
            {"action": "call_tool", "tool": "get_account", "account_reference": "guessed", "reasoning": "..."}
        )


def test_validate_missing_reasoning_raises():
    with pytest.raises(DecisionContractError):
        validate_decision({"action": "answer_directly"})


# -- decide(): call vs no-call -------------------------------------------


def test_no_call_for_a_message_that_needs_no_data():
    client = _fake_client({"action": "answer_directly", "reasoning": "just says thanks"})
    result = decide(_state(), "thanks so much!", MARIA_ACCOUNTS, client=client)
    assert result.needs_tool is False
    assert result.tool is None


def test_call_for_a_message_that_needs_account_data():
    client = _fake_client(
        {
            "action": "call_tool",
            "tool": "get_account",
            "account_reference": "explicit",
            "explicit_account_hint": "ACC-2001",
            "reasoning": "asked for their checking balance",
        }
    )
    result = decide(_state(), "what's the balance on ACC-2001?", MARIA_ACCOUNTS, client=client)
    assert result.needs_tool is True
    assert result.tool == "get_account"
    assert result.account_id == "ACC-2001"
    assert result.resolution_error is None


def test_customer_scoped_tool_needs_no_account_resolution():
    client = _fake_client({"action": "call_tool", "tool": "list_customer_accounts", "reasoning": "wants a summary"})
    result = decide(_state(), "what accounts do I have?", MARIA_ACCOUNTS, client=client)
    assert result.needs_tool is True
    assert result.tool == "list_customer_accounts"
    assert result.account_id is None
    assert result.resolution_error is None


# -- decide(): account reference resolution ------------------------------


def test_explicit_hint_matches_by_account_type():
    client = _fake_client(
        {
            "action": "call_tool",
            "tool": "get_account",
            "account_reference": "explicit",
            "explicit_account_hint": "checking",
            "reasoning": "named the account type",
        }
    )
    result = decide(_state(), "what's in my checking account?", MARIA_ACCOUNTS, client=client)
    assert result.account_id == "ACC-2001"


def test_last_mentioned_resolves_to_prior_turns_account():
    client = _fake_client(
        {
            "action": "call_tool",
            "tool": "list_account_transactions",
            "account_reference": "last_mentioned",
            "explicit_account_hint": None,
            "reasoning": "pronoun refers to what we just discussed",
        }
    )
    result = decide(_state("ACC-2001"), "and what were the recent transactions on it?", MARIA_ACCOUNTS, client=client)
    assert result.account_id == "ACC-2001"
    assert result.resolution_error is None


def test_the_other_one_resolves_via_conversation_state():
    client = _fake_client(
        {
            "action": "call_tool",
            "tool": "get_account",
            "account_reference": "the_other_one",
            "explicit_account_hint": None,
            "reasoning": "asking about the account not yet discussed",
        }
    )
    result = decide(_state("ACC-2001"), "and what about the other one?", MARIA_ACCOUNTS, client=client)
    assert result.account_id == "ACC-2002"
    assert result.resolution_error is None


def test_the_other_one_ambiguous_with_three_accounts_sets_resolution_error():
    three_accounts = MARIA_ACCOUNTS + [{"account_id": "ACC-2008", "type": "credit"}]
    client = _fake_client(
        {
            "action": "call_tool",
            "tool": "get_account",
            "account_reference": "the_other_one",
            "explicit_account_hint": None,
            "reasoning": "asking about another account",
        }
    )
    result = decide(_state("ACC-2001"), "what about the other one?", three_accounts, client=client)
    assert result.account_id is None
    assert result.resolution_error is not None


def test_none_reference_defaults_when_customer_has_one_account():
    single_account = [{"account_id": "ACC-2003", "type": "checking"}]
    client = _fake_client(
        {
            "action": "call_tool",
            "tool": "get_account",
            "account_reference": "none",
            "explicit_account_hint": None,
            "reasoning": "only one account exists",
        }
    )
    result = decide(_state(), "what's my balance?", single_account, client=client)
    assert result.account_id == "ACC-2003"
    assert result.resolution_error is None


def test_none_reference_ambiguous_with_multiple_accounts():
    client = _fake_client(
        {
            "action": "call_tool",
            "tool": "get_account",
            "account_reference": "none",
            "explicit_account_hint": None,
            "reasoning": "customer didn't say which account",
        }
    )
    result = decide(_state(), "what's my balance?", MARIA_ACCOUNTS, client=client)
    assert result.account_id is None
    assert result.resolution_error is not None


def test_explicit_hint_that_matches_nothing_sets_resolution_error():
    client = _fake_client(
        {
            "action": "call_tool",
            "tool": "get_account",
            "account_reference": "explicit",
            "explicit_account_hint": "ACC-9999",
            "reasoning": "customer named an account",
        }
    )
    result = decide(_state(), "what's the balance on ACC-9999?", MARIA_ACCOUNTS, client=client)
    assert result.account_id is None
    assert result.resolution_error is not None


# -- decide(): contract violations propagate, never guessed around ------


def test_malformed_json_raises_decision_contract_error():
    client = FakeMessagesClient("this is not json")
    with pytest.raises(DecisionContractError):
        decide(_state(), "hello", MARIA_ACCOUNTS, client=client)


def test_well_formed_json_wrong_shape_raises_decision_contract_error():
    client = _fake_client({"action": "call_tool", "tool": "ghost_tool", "reasoning": "..."})
    with pytest.raises(DecisionContractError):
        decide(_state(), "hello", MARIA_ACCOUNTS, client=client)
