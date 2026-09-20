"""Response layer: composes the reply the customer actually sees, from
the decision layer's output and (if a tool was called) its ToolOutcome.

Deliberately NOT one LLM call for every case. Split in two:

- found / not_found / unavailable / a resolution_error (ambiguous account
  reference) are all composed by plain Python string templates, not an
  LLM. This is the correctness-critical path the lab actually grades
  ("tool-failure handling implemented," "never invent account data") --
  templating it removes any chance of a model improvising reassuring but
  false detail on top of a failure, and makes the exact wording for each
  failure class testable byte-for-byte rather than testable only in
  spirit.
- answer_directly (a greeting, thanks, a general question) is the one
  case that's genuinely open-ended enough to need generation, so that
  path alone makes an LLM call -- and its system prompt explicitly
  forbids stating any specific account fact, since this path never looks
  anything up.
"""

from __future__ import annotations

from typing import Any, Optional

import anthropic

from conversation_state import ConversationState
from decision import TOOLS, Decision
from tool_client import ToolOutcome

RESPONSE_MODEL = "claude-sonnet-5"
# See decision.py's MAX_TOKENS comment -- same headroom-for-thinking reason.
RESPONSE_MAX_TOKENS = 512

ESCALATION_LINE = (
    "If you'd like, I can connect you with a specialist who can look into this further."
)

DIRECT_REPLY_SYSTEM_PROMPT = """You are a bank customer-service agent replying directly to a customer message that does not require looking up their account -- a greeting, thanks, or a general question. Reply briefly and warmly, in plain text (not JSON). You have not looked anything up this turn: never state or imply any specific balance, transaction, card, or account detail."""


def default_client() -> Any:
    return anthropic.Anthropic().messages


def compose_reply(
    decision: Decision,
    tool_outcome: Optional[ToolOutcome],
    user_message: str,
    state: ConversationState,
    client: Optional[Any] = None,
) -> str:
    if not decision.needs_tool:
        return _compose_direct_reply(user_message, state, client)

    if decision.resolution_error is not None:
        return _compose_clarification(decision.resolution_error)

    assert tool_outcome is not None, "needs_tool with no resolution_error must have a tool_outcome"

    if tool_outcome.status == "not_found":
        return _compose_not_found(tool_outcome.detail)
    if tool_outcome.status == "unavailable":
        return _compose_unavailable()
    return _compose_found(decision.tool, tool_outcome.data)


def _compose_clarification(resolution_error: str) -> str:
    return f"I want to make sure I look up the right account -- {resolution_error}. Could you clarify which one you mean?"


def _compose_not_found(detail: Optional[str]) -> str:
    # The mock's 404 message (see contract.md) is already customer-
    # appropriate wording ("No account found with id '...'"), unlike the
    # 500/malformed detail handled in _compose_unavailable -- see that
    # function for why those two cases are treated differently.
    reason = detail or "I couldn't find that record."
    return f"{reason} {ESCALATION_LINE}"


def _compose_unavailable() -> str:
    # tool_outcome.detail is deliberately not interpolated here -- it's
    # an internal, technical description (e.g. "the CRM returned HTTP
    # 500 for GET /accounts/ACC-2004") meant for the turn's logged
    # ToolOutcome, not for a customer-facing message. What the customer
    # sees stays the same generic, honest statement regardless of which
    # of the three unavailable causes (500, timeout, malformed) fired.
    return f"I'm having trouble reaching our account systems right now, so I can't pull that up. {ESCALATION_LINE}"


def _compose_found(tool: Optional[str], data: Any) -> str:
    if tool == "get_customer":
        return f"You're {data['name']} ({data['email']}), a customer with us since {data['since_date']}."

    if tool == "list_customer_accounts":
        if not data:
            return "I don't see any accounts on file for you."
        lines = [f"- {a['account_id']} ({a['type']}, {a['status']})" for a in data]
        return "Here are the accounts on your profile:\n" + "\n".join(lines)

    if tool == "get_account":
        return (
            f"Your {data['type']} account ({data['account_id']}) has a balance of "
            f"${data['balance']:.2f} and is currently {data['status']}."
        )

    if tool == "list_account_transactions":
        if not data:
            return "That account doesn't have any transactions on record."
        lines = [f"- {t['date']}: {t['description']} ({t['amount']:+.2f})" for t in data]
        return "Here are the recent transactions:\n" + "\n".join(lines)

    if tool == "list_account_cards":
        if not data:
            return "There are no cards on file for that account."
        lines = [f"- card ending {c['last_four']} ({c['status']})" for c in data]
        return "Here are the cards on that account:\n" + "\n".join(lines)

    raise AssertionError(f"no reply formatter for tool {tool!r} (known tools: {sorted(TOOLS)})")


def _compose_direct_reply(user_message: str, state: ConversationState, client: Optional[Any]) -> str:
    messages_client = client or default_client()
    history = "\n".join(f"- customer: {turn.user_message!r} -> agent: {turn.reply!r}" for turn in state.turns)
    user_prompt = f"Conversation so far:\n{history or '(no prior turns)'}\n\nCustomer's new message: {user_message!r}"

    response = messages_client.create(
        model=RESPONSE_MODEL,
        max_tokens=RESPONSE_MAX_TOKENS,
        temperature=1,
        system=DIRECT_REPLY_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return "".join(block.text for block in response.content if block.type == "text").strip()
