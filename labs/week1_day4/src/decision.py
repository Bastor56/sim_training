"""Decision layer: one LLM call per turn that classifies whether this
turn needs CRM data, and if so, which tool.

Mirrors day 2's planner.py shape closely -- an injectable Anthropic
client, a strict two-shape JSON contract, a validate_*() function that
raises rather than guesses on anything else. See spec 'Planner contract'
in day 2 for the pattern this is copying.

One deliberate split from day 2's planner: the LLM is never asked to
output a real account_id directly. For account-scoped tools it instead
classifies *how* the customer referred to an account --
"explicit" / "last_mentioned" / "the_other_one" / "none" -- and
_resolve_account_id() turns that into an actual ID deterministically,
using conversation_state.py's pure functions (Phase 3). This removes an
entire class of hallucination risk: the model literally cannot invent an
account ID for a pronoun-style reference, because it never gets to name
one for those cases at all. It's also why Phase 3 built
resolve_other_account() as a standalone, LLM-free function in the first
place, rather than folding that logic into a prompt.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, List, Optional

import anthropic

from conversation_state import ConversationState, resolve_other_account

MODEL = "claude-sonnet-5"
# Generous relative to the ~150-300 tokens a decision JSON object actually
# needs -- observed in testing that this model occasionally spends part of
# the budget on an internal reasoning pass before its text output, and a
# too-tight budget can leave zero tokens for the text block itself,
# producing an empty response (see DecisionContractError's "did not return
# valid JSON: ''" case). Headroom here, not a temperature change, is the
# fix: temperature=1 matches day 2's planner.py on purpose.
MAX_TOKENS = 1024

# tool name -> {"scope": "customer" | "account", "description": ...}.
# "customer"-scoped tools need no account resolution at all -- they act
# on the session's own customer_id. This is also the decision layer's
# one-tool-per-turn contract: exactly the 5 mock CRM endpoints from
# Phase 1, one tool each, per the tool-granularity decision in plan.md.
TOOLS = {
    "get_customer": {
        "scope": "customer",
        "description": "Look up this customer's own profile (name, email, member since).",
    },
    "list_customer_accounts": {
        "scope": "customer",
        "description": "List every account belonging to this customer.",
    },
    "get_account": {
        "scope": "account",
        "description": "Get one account's type, balance, and status.",
    },
    "list_account_transactions": {
        "scope": "account",
        "description": "List recent transactions on one account.",
    },
    "list_account_cards": {
        "scope": "account",
        "description": "List the cards issued on one account.",
    },
}

ACCOUNT_REFERENCES = {"explicit", "last_mentioned", "the_other_one", "none"}

SYSTEM_PROMPT_TEMPLATE = """You are the decision layer of a bank customer-service agent. Every turn, decide whether answering the customer requires calling the CRM, and if so, exactly which tool -- never call a tool the answer doesn't need; every unnecessary CRM hit is a failure of this decision, not a safe default.

Available tools:
{tool_catalog}

This customer's accounts on file:
{account_catalog}

Respond with exactly one JSON object and nothing else, in one of these two shapes:

{{"action": "answer_directly", "reasoning": "..."}}
{{"action": "call_tool", "tool": "<tool name>", "account_reference": "explicit" | "last_mentioned" | "the_other_one" | "none", "explicit_account_hint": "<account id or account type the customer named, or null>", "reasoning": "..."}}

Use "answer_directly" for anything that doesn't need this customer's account data: greetings, thanks, general questions about how banking works, or a clarifying question back to the customer.

For "call_tool" against an account-scoped tool (get_account, list_account_transactions, list_account_cards), set account_reference to describe how the customer referred to the account -- you do not name the account ID yourself, a later step resolves it:
- "explicit": the customer named a specific account (an ID, or a type like "checking"/"savings") -- put what they said in explicit_account_hint.
- "last_mentioned": a pronoun referring to whatever was just discussed ("it", "that account").
- "the_other_one": they're asking about the account they haven't asked about yet this conversation.
- "none": they didn't specify one at all.

For get_customer and list_customer_accounts, set account_reference to "none" and explicit_account_hint to null -- those tools act on the customer, not one account."""


class DecisionContractError(Exception):
    """The decision layer's response didn't satisfy the two-shape
    contract: not JSON, an unregistered tool, or an invalid
    account_reference. Harness-visible -- raised, not silently guessed
    around, matching day 2's tool-error vs. harness-error split."""


@dataclass
class Decision:
    """The decision layer's final output, after account resolution --
    what graph_nodes.py (Phase 5) actually acts on.

    needs_tool: whether this turn calls the CRM at all.
    tool: one of TOOLS' keys, set only when needs_tool is True.
    account_id: the resolved account to call an account-scoped tool
        with. None for customer-scoped tools (not needed) and also None
        when resolution failed -- check resolution_error to tell those
        two apart.
    resolution_error: set when needs_tool is True, the tool is
        account-scoped, and _resolve_account_id() couldn't produce a
        confident answer. The response layer (Phase 5) turns this into a
        clarifying question rather than guessing an account.
    """

    needs_tool: bool
    tool: Optional[str] = None
    account_id: Optional[str] = None
    resolution_error: Optional[str] = None
    reasoning: str = ""


def default_client() -> Any:
    return anthropic.Anthropic().messages


def _format_tool_catalog() -> str:
    return "\n".join(f"- {name}: {spec['description']}" for name, spec in TOOLS.items())


def _format_account_catalog(customer_accounts: List[dict]) -> str:
    if not customer_accounts:
        return "(no accounts on file for this customer)"
    return "\n".join(f"- {a['account_id']} ({a['type']})" for a in customer_accounts)


def _format_turn_history(state: ConversationState) -> str:
    if not state.turns:
        return "(this is the first turn)"
    lines = []
    for turn in state.turns:
        line = f"- customer said: {turn.user_message!r}"
        if turn.referenced_account_id:
            line += f" [about {turn.referenced_account_id}]"
        if turn.reply:
            line += f" -> agent replied: {turn.reply!r}"
        lines.append(line)
    return "\n".join(lines)


def validate_decision(parsed: Any) -> dict:
    if not isinstance(parsed, dict):
        raise DecisionContractError(f"decision layer output was not a JSON object: {parsed!r}")

    kind = parsed.get("action")
    if kind == "answer_directly":
        if "reasoning" not in parsed:
            raise DecisionContractError("answer_directly action is missing reasoning")
        return parsed
    if kind == "call_tool":
        tool = parsed.get("tool")
        if tool not in TOOLS:
            raise DecisionContractError(f"decision layer named an unregistered tool: {tool!r}")
        if TOOLS[tool]["scope"] == "account":
            reference = parsed.get("account_reference")
            if reference not in ACCOUNT_REFERENCES:
                raise DecisionContractError(
                    f"call_tool for {tool!r} has an invalid account_reference: {reference!r}"
                )
        if "reasoning" not in parsed:
            raise DecisionContractError("call_tool action is missing reasoning")
        return parsed
    raise DecisionContractError(f"decision action must be 'answer_directly' or 'call_tool', got: {kind!r}")


def _resolve_account_id(
    reference: Optional[str],
    hint: Optional[str],
    state: ConversationState,
    customer_accounts: List[dict],
) -> "tuple[Optional[str], Optional[str]]":
    """Returns (account_id, resolution_error) -- exactly one of the two
    is set. Never guesses: an ambiguous or unmatched reference returns
    (None, <reason>) rather than picking an account, the same "never
    invent" principle contract.md applies to CRM data extended to which
    record the decision is even about."""
    account_ids = [a["account_id"] for a in customer_accounts]

    if reference == "explicit":
        if not hint:
            return None, "the customer didn't name an account"
        for account in customer_accounts:
            if account["account_id"] == hint or account.get("type") == hint:
                return account["account_id"], None
        return None, f"couldn't match '{hint}' to one of this customer's accounts"

    if reference == "last_mentioned":
        account_id = state.last_referenced_account_id()
        if account_id is None:
            return None, "no account has been discussed yet this session"
        return account_id, None

    if reference == "the_other_one":
        account_id = resolve_other_account(state, account_ids)
        if account_id is None:
            return None, "it's unclear which account 'the other one' refers to"
        return account_id, None

    if reference == "none":
        if len(account_ids) == 1:
            return account_ids[0], None
        return None, "this customer has more than one account and none was specified"

    return None, f"unrecognized account_reference: {reference!r}"


def decide(
    state: ConversationState,
    user_message: str,
    customer_accounts: List[dict],
    client: Optional[Any] = None,
) -> Decision:
    messages_client = client or default_client()
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        tool_catalog=_format_tool_catalog(),
        account_catalog=_format_account_catalog(customer_accounts),
    )
    user_prompt = (
        f"Conversation so far:\n{_format_turn_history(state)}\n\n"
        f"Customer's new message: {user_message!r}\n\n"
        "What is your decision?"
    )

    response = messages_client.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        temperature=1,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )

    text = "".join(block.text for block in response.content if block.type == "text")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DecisionContractError(f"decision layer did not return valid JSON: {text!r}") from exc

    action = validate_decision(parsed)

    if action["action"] == "answer_directly":
        return Decision(needs_tool=False, reasoning=action["reasoning"])

    tool = action["tool"]
    reasoning = action["reasoning"]

    if TOOLS[tool]["scope"] == "customer":
        return Decision(needs_tool=True, tool=tool, reasoning=reasoning)

    account_id, resolution_error = _resolve_account_id(
        action.get("account_reference"),
        action.get("explicit_account_hint"),
        state,
        customer_accounts,
    )
    return Decision(
        needs_tool=True,
        tool=tool,
        account_id=account_id,
        resolution_error=resolution_error,
        reasoning=reasoning,
    )
