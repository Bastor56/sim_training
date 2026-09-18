"""Graph nodes: LangGraph's equivalent of day 2's loop.py + executor.py.

Component mapping (see tradeoffs.md for the full writeup):
  day 2 loop.py's `while True` termination check  -> check_limits_node +
        route_after_limits (a conditional edge, run before every planner
        call by wiring it both from START and from the executor node)
  day 2 loop.py's `action = planner(state)` turn   -> planner_node
  day 2 executor.py's dispatch + retry/backoff     -> executor_node +
        the RetryPolicy attached to it in graph.py

Planner reuse: `plan_next_action` (day 2's planner.py) is imported and
called UNCHANGED — same system prompt, same JSON contract, same model.
It expects an object with `.goal`, `.observations`, and a mutable
`.tokens_used` it can `+=` on as a side effect. LangGraph nodes can't rely
on in-place mutation being visible to the graph (only a node's *returned*
dict is committed), so planner_node hands it a small shim object exposing
those three attributes, then reads the mutated `tokens_used` back out and
returns it explicitly. This is the one adapter needed to reuse day 2's
planner unmodified; see tradeoffs.md for why that mutation pattern is a
day-2-only idiom that doesn't survive the port as-is.

Retry/backoff reuse: day 2's executor.py hand-rolled the retry loop itself
(exponential backoff + jitter, capped at 3, injectable `sleep` for fast
tests). Here that loop is deleted entirely and replaced with LangGraph's
own `RetryPolicy` (see graph.py) attached to executor_node — the
framework's own idiom for retry, not a quiet reimplementation of day 2's.
The one thing RetryPolicy can't do on its own is convert an *exhausted*
retry into a graceful observation instead of crashing the graph (on the
final attempt it just re-raises). LangGraph exposes the current attempt
number to node code via `get_runtime().execution_info.node_attempt`
(1-indexed) specifically for this kind of "am I on my last try" decision,
which is what executor_node uses below.
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any, Callable

import bootstrap  # noqa: F401
from errors import ToolError
from planner import plan_next_action
from registry import REGISTRY
from state import Observation

from langgraph.runtime import get_runtime
from langgraph.types import RetryPolicy

from graph_state import GraphState

MAX_ATTEMPTS = 3
BASE_DELAY_SECONDS = 0.5

# Mirrors day 2's executor.py constants (MAX_ATTEMPTS=3, BASE_DELAY_SECONDS=0.5,
# delay = base * 2**attempt + jitter) so the backoff curve is the same curve,
# just expressed in the framework's own config object instead of hand code.
EXECUTOR_RETRY_POLICY = RetryPolicy(
    initial_interval=BASE_DELAY_SECONDS,
    backoff_factor=2.0,
    max_attempts=MAX_ATTEMPTS,
    jitter=True,
    retry_on=ToolError,
)


class UnknownToolError(Exception):
    """The planner named a tool that isn't in the registry. Same harness-
    error meaning as day 2's executor.UnknownToolError: planner.validate_action
    should have caught this already, so landing here means that validation
    was skipped or has a bug — propagate, don't retry or guess."""


def check_limits_node(state: GraphState) -> dict[str, Any]:
    """No-op hub node. All it does is give route_after_limits a place to
    attach a conditional edge that both START and the executor node can
    loop back into, so the check genuinely runs before every planner call
    (including the first) -- matching day 2's "checked at the top of every
    iteration" ordering."""
    return {}


def route_after_limits(state: GraphState) -> str:
    if state.iteration_count >= state.max_iterations:
        return "iteration_limit"
    if state.tokens_used >= state.token_budget:
        return "budget_limit"
    if time.monotonic() - state.started_at >= state.wall_clock_budget_seconds:
        return "budget_limit"
    return "planner"


def set_iteration_limit_status_node(state: GraphState) -> dict[str, Any]:
    return {"status": "terminated_iteration_limit"}


def set_budget_limit_status_node(state: GraphState) -> dict[str, Any]:
    return {"status": "terminated_budget_limit"}


def make_planner_node(
    plan_fn: Callable[[Any], dict[str, Any]] = plan_next_action,
) -> Callable[[GraphState], dict[str, Any]]:
    """Factory so tests can inject a fake/scripted planner, the same way
    day 2's tests passed `planner=` into `run_agent` (see loop.py)."""

    def planner_node(state: GraphState) -> dict[str, Any]:
        # Shim carries exactly the attributes plan_next_action touches:
        # .goal and .observations are read; .tokens_used is mutated via +=
        # as a side effect. See module docstring for why this adapter exists.
        shim = SimpleNamespace(
            goal=state.goal,
            observations=state.observations,
            tokens_used=state.tokens_used,
        )
        action = plan_fn(shim)

        updates: dict[str, Any] = {
            "iteration_count": state.iteration_count + 1,
            "tokens_used": shim.tokens_used,
            "pending_action": action,
        }
        if action["action"] == "terminate":
            updates["status"] = "terminated_success"
            updates["final_decision"] = {
                "decision": action["decision"],
                "reasoning": action["reasoning"],
            }
        return updates

    return planner_node


def route_after_planner(state: GraphState) -> str:
    return "end" if state.status == "terminated_success" else "executor"


def executor_node(state: GraphState) -> dict[str, Any]:
    action = state.pending_action
    tool_name = action["tool"]
    args = action["args"]

    if tool_name not in REGISTRY:
        raise UnknownToolError(f"{tool_name!r} is not a registered tool")

    attempt = get_runtime().execution_info.node_attempt
    fn = REGISTRY[tool_name]["fn"]

    try:
        result = fn(**args)
        obs = Observation(tool=tool_name, args=args, timestamp=time.time(), result=result)
    except ToolError as exc:
        if attempt < MAX_ATTEMPTS:
            # Let it propagate: EXECUTOR_RETRY_POLICY (attached to this node
            # in graph.py) catches ToolError, sleeps with backoff, and
            # re-invokes this whole function as the next attempt.
            raise
        # Last attempt allowed by the policy. RetryPolicy would otherwise
        # re-raise this past the graph boundary and crash the run — day 2's
        # "exhausted retries become an observation, not a crash" requirement
        # has to be re-implemented here, at the one point the framework
        # hands control back to node code.
        obs = Observation(tool=tool_name, args=args, timestamp=time.time(), error=str(exc))

    return {"observations": [obs]}
