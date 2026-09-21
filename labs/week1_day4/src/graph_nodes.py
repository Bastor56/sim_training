"""Graph nodes: conversation -> decision -> tool -> response, matching
the lab's own architecture description one node per active layer (the
conversation layer is passive state, not a node -- see graph_state.py).

Data flows one way per turn; the only loop-back anywhere in this lab is
the retry *inside* the tool layer (tool_client.py's hand-rolled retry),
which is invisible to the graph -- tool_node below makes exactly one call
into CRMClient and gets back exactly one ToolOutcome, win or lose. There
is no retry edge in this graph at all, unlike day 2/3's investigation
loop.

Every node factory (make_decision_node, make_response_node) takes the
underlying function as a parameter so tests can inject a fake/scripted
one, the same way day 3's make_planner_node took plan_fn -- see
tests/test_graph.py.
"""

from __future__ import annotations

from typing import Any, Callable, Dict

from conversation_state import ConversationState, Turn
from decision import Decision, decide
from graph_state import GraphState
from response import compose_reply
from tool_client import CRMClient, ToolOutcome


def _as_conversation_state(state: GraphState) -> ConversationState:
    """Builds a read-only ConversationState view over the graph's own
    turns list, so decide()/compose_reply() -- written and unit-tested
    against ConversationState directly in Phases 3/4/5 -- can be reused
    here unchanged. The same "build a small adapter object" technique
    day 3's planner_node used (a SimpleNamespace shim) to reuse day 2's
    planner without changing its signature."""
    return ConversationState(session_id=state.session_id, customer_id=state.customer_id, turns=list(state.turns))


def make_decision_node(decide_fn: Callable[..., Decision] = decide) -> Callable[[GraphState], Dict[str, Any]]:
    def decision_node(state: GraphState) -> Dict[str, Any]:
        conv_state = _as_conversation_state(state)
        decision = decide_fn(conv_state, state.pending_user_message, state.customer_accounts)
        return {"pending_decision": decision}

    return decision_node


def route_after_decision(state: GraphState) -> str:
    decision = state.pending_decision
    # A tool call proceeds only when the decision layer both wants one
    # and successfully resolved which account it's about (or didn't need
    # to -- customer-scoped tools never set resolution_error). An
    # unresolved account_reference has nothing to call the CRM with, so
    # it routes straight to response, which turns resolution_error into
    # a clarifying question instead of a tool call.
    if decision.needs_tool and decision.resolution_error is None:
        return "tool"
    return "response"


def _dispatch(crm_client: CRMClient, decision: Decision, customer_id: str) -> ToolOutcome:
    if decision.tool == "get_customer":
        return crm_client.get_customer(customer_id)
    if decision.tool == "list_customer_accounts":
        return crm_client.list_customer_accounts(customer_id)
    if decision.tool == "get_account":
        return crm_client.get_account(decision.account_id)
    if decision.tool == "list_account_transactions":
        return crm_client.list_account_transactions(decision.account_id)
    if decision.tool == "list_account_cards":
        return crm_client.list_account_cards(decision.account_id)
    raise AssertionError(f"no dispatch wired up for tool {decision.tool!r}")


def make_tool_node(crm_client: CRMClient) -> Callable[[GraphState], Dict[str, Any]]:
    def tool_node(state: GraphState) -> Dict[str, Any]:
        outcome = _dispatch(crm_client, state.pending_decision, state.customer_id)
        return {"pending_tool_outcome": outcome}

    return tool_node


def make_response_node(compose_fn: Callable[..., str] = compose_reply) -> Callable[[GraphState], Dict[str, Any]]:
    def response_node(state: GraphState) -> Dict[str, Any]:
        conv_state = _as_conversation_state(state)
        decision = state.pending_decision
        # A recalled_outcome (see decision.py) means the tool node was
        # skipped entirely -- this turn's "outcome" is a prior turn's
        # cached data, not a fresh pending_tool_outcome.
        outcome = decision.recalled_outcome if decision.recalled_outcome is not None else state.pending_tool_outcome

        reply = compose_fn(decision, outcome, state.pending_user_message, conv_state)

        new_turn = Turn(
            user_message=state.pending_user_message,
            referenced_account_id=decision.account_id,
            tool=decision.tool,
            tool_outcome=outcome,
            reply=reply,
        )
        return {
            "turns": [new_turn],
            "pending_user_message": "",
            "pending_decision": None,
            "pending_tool_outcome": None,
        }

    return response_node
