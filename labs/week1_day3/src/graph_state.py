"""LangGraph's equivalent of day 2's AgentState (state.py).

Day 2 threaded one mutable dataclass through a hand-written `while True`
loop and mutated it in place (`state.add_observation(obs)`,
`state.tokens_used += ...`). LangGraph owns the state store instead: nodes
must be pure functions that return a *partial update* dict, and the
framework merges it into the graph's persisted state using each field's
reducer (default: overwrite; `observations` below uses `operator.add` so
returned lists are appended, not replaced — the framework-native way to get
day 2's "always append, never mutate" observation trail).

`Observation` itself is imported unchanged from day 2 (see bootstrap.py) —
only the container that holds the list changes shape.
"""

from __future__ import annotations

import operator
import time
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal

import bootstrap  # noqa: F401
from state import Observation

Status = Literal[
    "running",
    "terminated_success",
    "terminated_iteration_limit",
    "terminated_budget_limit",
]


@dataclass
class GraphState:
    goal: str
    claim_id: str
    max_iterations: int = 6
    token_budget: int = 20000
    wall_clock_budget_seconds: float = 60.0
    observations: Annotated[list[Observation], operator.add] = field(default_factory=list)
    iteration_count: int = 0
    tokens_used: int = 0
    started_at: float = field(default_factory=time.monotonic)
    status: Status = "running"
    final_decision: dict[str, Any] | None = None
    # Framework-owned "in-flight message" passed from the planner node to
    # the executor node. Day 2 never needed this: a plain local variable in
    # the loop body (`action = planner(state)`) served the same purpose.
    # Once control flow becomes graph edges instead of a loop body, that
    # local variable has to become a state field so the next node can see it.
    pending_action: dict[str, Any] | None = None
