"""The agent loop: planner -> executor -> observation -> termination check
-> planner. Exactly two legitimate exits, checked at the top of every
iteration: the planner terminates, or a limit (iteration/budget) is hit.
See spec.md 'Termination conditions'.
"""

from __future__ import annotations

from typing import Any, Callable

from executor import execute_tool
from planner import plan_next_action
from state import AgentState


def run_agent(
    state: AgentState,
    planner: Callable[[AgentState], dict[str, Any]] = plan_next_action,
) -> AgentState:
    while True:
        if state.iteration_count >= state.max_iterations:
            state.status = "terminated_iteration_limit"
            return state
        if state.tokens_used >= state.token_budget:
            state.status = "terminated_budget_limit"
            return state
        if state.elapsed_seconds() >= state.wall_clock_budget_seconds:
            state.status = "terminated_budget_limit"
            return state

        state.iteration_count += 1
        action = planner(state)

        if action["action"] == "terminate":
            state.status = "terminated_success"
            state.final_decision = {
                "decision": action["decision"],
                "reasoning": action["reasoning"],
            }
            return state

        observation = execute_tool(action["tool"], action["args"])
        state.add_observation(observation)
