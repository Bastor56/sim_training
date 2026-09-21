"""Conversation layer: per-session state and turn history.

A session is scoped to one identified customer for its whole lifetime --
this is a support chat where the customer is already known (session-bound
identity), not a flow where the agent asks "what's your customer ID"
every turn. What varies turn to turn is which of *that customer's*
accounts is being discussed, which is exactly what makes a follow-up like
"and what about the other one?" resolvable: it's asking about the one
account belonging to this customer that hasn't come up yet.

Nothing here calls an LLM or the CRM -- this is pure, deterministic state
and a pure resolution function, on purpose. The decision layer (Phase 4)
is what actually decides whether a turn needs a tool call; this module
just gives it the conversation history to reason from, and a
ready-made answer for the one specific follow-up pattern ("the other
one") that doesn't need an LLM to resolve at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from tool_client import ToolOutcome


@dataclass
class Turn:
    """One turn of the conversation. Fields fill in progressively as the
    turn moves through the graph's layers (Phase 5): user_message is set
    immediately; referenced_account_id, tool, and tool_outcome are set
    only if the decision layer decided this turn needed data (all three
    stay None for a turn answered directly, e.g. "thanks"); reply is set
    last, by the response layer. tool records which CRM endpoint produced
    tool_outcome, so a later turn can recall this one's data by matching
    on it (see resolve_recall()) rather than only replaying it by eye."""

    user_message: str
    referenced_account_id: Optional[str] = None
    tool: Optional[str] = None
    tool_outcome: Optional[ToolOutcome] = None
    reply: Optional[str] = None


@dataclass
class ConversationState:
    session_id: str
    customer_id: str
    turns: List[Turn] = field(default_factory=list)

    def start_turn(self, user_message: str) -> Turn:
        turn = Turn(user_message=user_message)
        self.turns.append(turn)
        return turn

    def last_referenced_account_id(self) -> Optional[str]:
        """The account_id this conversation most recently discussed, or
        None if no turn has referenced one yet. Walks most-recent-first
        -- this is "what were we just talking about," the thing a bare
        pronoun ("it", "that account") would resolve against."""
        for turn in reversed(self.turns):
            if turn.referenced_account_id is not None:
                return turn.referenced_account_id
        return None

    def previously_referenced_account_ids(self) -> List[str]:
        """Every distinct account_id this session has discussed so far,
        oldest first."""
        seen: List[str] = []
        for turn in self.turns:
            account_id = turn.referenced_account_id
            if account_id is not None and account_id not in seen:
                seen.append(account_id)
        return seen


def resolve_other_account(state: ConversationState, customer_account_ids: List[str]) -> Optional[str]:
    """Resolves "and what about the other one?" -- the one account
    belonging to this customer that hasn't come up in the conversation
    yet.

    customer_account_ids is supplied by the caller (the decision layer,
    after listing the customer's accounts via the tool layer) rather than
    looked up here -- this module has no CRM access and shouldn't need
    any to answer a question about its own turn history.

    Returns None when the answer would be a guess rather than a fact:
    zero accounts remain unreferenced (nothing left to call "the other
    one"), or more than one does (genuinely ambiguous -- which other
    one?). A None here should become a clarifying question, never a
    silent pick, consistent with the lab's "never invent data" rule
    extending to "never invent which record the user meant," too.
    """
    referenced = set(state.previously_referenced_account_ids())
    remaining = [account_id for account_id in customer_account_ids if account_id not in referenced]
    if len(remaining) == 1:
        return remaining[0]
    return None


def resolve_recall(state: ConversationState, tool: str, account_id: Optional[str]) -> Optional[ToolOutcome]:
    """Finds the most recent turn's cached ToolOutcome for `tool` and
    `account_id` (None for a customer-scoped tool), so a follow-up that's
    genuinely asking to be reminded of something already retrieved this
    session doesn't need a second CRM call -- the recall counterpart to
    resolve_other_account() above.

    Walks most-recent-first and matches on both which tool was used and
    which account it was about; only a "found" outcome counts as
    something worth recalling, since a not_found or unavailable turn has
    no data to replay. Returns None when nothing matches, meaning the
    caller should fall back to an actual tool call rather than recall
    something that was never actually fetched -- same "never invent"
    principle resolve_other_account() applies to which account, applied
    here to whether the data exists at all.
    """
    for turn in reversed(state.turns):
        if (
            turn.tool == tool
            and turn.referenced_account_id == account_id
            and turn.tool_outcome is not None
            and turn.tool_outcome.status == "found"
        ):
            return turn.tool_outcome
    return None
