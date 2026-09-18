"""Builds the compiled LangGraph -- the framework's equivalent of day 2's
loop.py. See graph_nodes.py for what each node/edge maps back to.

    START ---------------------------------> check_limits
    check_limits --[iteration_limit]------->  set_iteration_limit_status -> END
    check_limits --[budget_limit]---------->  set_budget_limit_status    -> END
    check_limits --[planner]---------------> planner
    planner --[terminate]-------------------> END
    planner --[call_tool]-------------------> executor  (RetryPolicy attached)
    executor --------------------------------> check_limits   (loop back)

This is the same ring day 2 drew (Planning -> Executing -> Observing ->
Planning) with the termination check pulled out as its own hub so it truly
runs before every planner call, first iteration included.
"""

from __future__ import annotations

from typing import Any, Callable

from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from graph_nodes import (
    EXECUTOR_RETRY_POLICY,
    check_limits_node,
    executor_node,
    make_planner_node,
    route_after_limits,
    route_after_planner,
    set_budget_limit_status_node,
    set_iteration_limit_status_node,
)
from graph_state import GraphState


def build_graph(
    plan_fn: Callable[[Any], dict[str, Any]] | None = None,
    retry_policy: RetryPolicy = EXECUTOR_RETRY_POLICY,
):
    g = StateGraph(GraphState)

    planner_node = make_planner_node(plan_fn) if plan_fn is not None else make_planner_node()

    g.add_node("check_limits", check_limits_node)
    g.add_node("set_iteration_limit_status", set_iteration_limit_status_node)
    g.add_node("set_budget_limit_status", set_budget_limit_status_node)
    g.add_node("planner", planner_node)
    g.add_node("executor", executor_node, retry_policy=retry_policy)

    g.add_edge(START, "check_limits")
    g.add_conditional_edges(
        "check_limits",
        route_after_limits,
        {
            "planner": "planner",
            "iteration_limit": "set_iteration_limit_status",
            "budget_limit": "set_budget_limit_status",
        },
    )
    g.add_edge("set_iteration_limit_status", END)
    g.add_edge("set_budget_limit_status", END)
    g.add_conditional_edges(
        "planner",
        route_after_planner,
        {"executor": "executor", "end": END},
    )
    g.add_edge("executor", "check_limits")

    return g.compile()
