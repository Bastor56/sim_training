"""Builds the compiled LangGraph.

    START -> decision --[needs a tool, resolved]--> tool -> response -> END
                      \\--[no tool / unresolved]-----------> response -> END

Three nodes, matching the lab's architecture: decision, tool, response
(conversation is passive state -- see graph_state.py). No loop-back edge
anywhere; the tool layer's own retry (tool_client.py) is internal to a
single call into the tool node.

Uses LangGraph's low-level StateGraph + hand-written nodes, not a
prebuilt ReAct/tool-calling agent -- the same choice day 3 made, for the
same reason: it keeps the system prompts in decision.py and response.py
fully visible and hand-written, rather than a framework-injected prompt
you'd have to go looking for. See day 3's tradeoffs.md, "What you can no
longer see."
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from decision import Decision, decide
from graph_nodes import make_decision_node, make_response_node, make_tool_node, route_after_decision
from graph_state import GraphState
from tool_client import CRMClient, build_http_client


def bootstrap_session(crm_client: CRMClient, session_id: str, customer_id: str) -> dict:
    """The one CRM call that happens outside the per-turn decision/tool/
    response flow: fetching this customer's account summary once, at
    session start, so decision.py has enough context (account IDs and
    types) to resolve which account a turn is even about -- see
    decision.py's module docstring. Real deployments typically already
    have this on screen before a chat starts (a logged-in customer
    portal already shows your accounts); this makes that assumption
    explicit rather than silently baking it in -- see design_doc.md.

    Returns a plain dict of GraphState's session-scoped fields, meant to
    be merged with the first turn's pending_user_message and passed as
    the initial state to graph.invoke().
    """
    outcome = crm_client.list_customer_accounts(customer_id)
    accounts = outcome.data if outcome.status == "found" else []
    return {"session_id": session_id, "customer_id": customer_id, "customer_accounts": accounts}


def build_graph(
    decide_fn: Callable[..., Decision] = decide,
    compose_fn: Callable[..., str] = None,
    crm_client: Optional[CRMClient] = None,
    checkpointer: Optional[Any] = None,
):
    if crm_client is None:
        crm_client = CRMClient(build_http_client())
    if checkpointer is None:
        checkpointer = InMemorySaver()

    # None means "use make_response_node's own default" (response.compose_reply)
    # rather than this module needing its own copy of that default to pass through.
    response_node = make_response_node(compose_fn) if compose_fn is not None else make_response_node()

    g = StateGraph(GraphState)
    g.add_node("decision", make_decision_node(decide_fn))
    g.add_node("tool", make_tool_node(crm_client))
    g.add_node("response", response_node)

    g.add_edge(START, "decision")
    g.add_conditional_edges("decision", route_after_decision, {"tool": "tool", "response": "response"})
    g.add_edge("tool", "response")
    g.add_edge("response", END)

    return g.compile(checkpointer=checkpointer)
