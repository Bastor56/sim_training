import context  # noqa: F401  -- must be first: puts src/ and mock_crm/ on sys.path

from conversation_state import ConversationState, resolve_other_account

# Mirrors the fixture customer CUST-1001 (Maria Chen), who has exactly
# two accounts in mock_crm/fixtures.py -- ACC-2001 and ACC-2002.
MARIA_ACCOUNT_IDS = ["ACC-2001", "ACC-2002"]


def _state_with_turns(*referenced_account_ids: str) -> ConversationState:
    state = ConversationState(session_id="sess-1", customer_id="CUST-1001")
    for account_id in referenced_account_ids:
        turn = state.start_turn(user_message=f"what's the balance on {account_id}?")
        turn.referenced_account_id = account_id
    return state


def test_last_referenced_account_id_tracks_most_recent_turn():
    state = _state_with_turns("ACC-2001", "ACC-2002")
    assert state.last_referenced_account_id() == "ACC-2002"


def test_last_referenced_account_id_none_before_any_turn():
    state = ConversationState(session_id="sess-1", customer_id="CUST-1001")
    assert state.last_referenced_account_id() is None


def test_previously_referenced_account_ids_dedupes_and_preserves_order():
    state = _state_with_turns("ACC-2001", "ACC-2002", "ACC-2001")
    assert state.previously_referenced_account_ids() == ["ACC-2001", "ACC-2002"]


# -- the lab's own "Done when" scenario: ask about account A, then "and
# what about the other one?" resolves to account B via state alone -----


def test_resolve_other_account_after_one_turn_referenced():
    state = _state_with_turns("ACC-2001")  # "what's the balance on my checking?"
    assert resolve_other_account(state, MARIA_ACCOUNT_IDS) == "ACC-2002"


def test_resolve_other_account_is_order_independent():
    state = _state_with_turns("ACC-2002")
    assert resolve_other_account(state, MARIA_ACCOUNT_IDS) == "ACC-2001"


# -- ambiguous cases: a guess would violate "never invent an answer," so
# these must return None rather than picking one -----------------------


def test_resolve_other_account_none_when_nothing_referenced_yet():
    state = ConversationState(session_id="sess-1", customer_id="CUST-1001")
    assert resolve_other_account(state, MARIA_ACCOUNT_IDS) is None


def test_resolve_other_account_none_when_more_than_one_remains():
    # A three-account customer where only one has come up -- "the other
    # one" is genuinely ambiguous between the remaining two.
    state = _state_with_turns("ACC-2001")
    assert resolve_other_account(state, ["ACC-2001", "ACC-2002", "ACC-2008"]) is None


def test_resolve_other_account_none_when_every_account_already_referenced():
    state = _state_with_turns("ACC-2001", "ACC-2002")
    assert resolve_other_account(state, MARIA_ACCOUNT_IDS) is None
