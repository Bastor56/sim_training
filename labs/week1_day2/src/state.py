"""Agent state: one serializable object threaded through the loop, never a
module-level global, so a run can be dumped mid-flight and inspected. See
spec.md 'Agent state'.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Status = Literal[
    "running",
    "terminated_success",
    "terminated_iteration_limit",
    "terminated_budget_limit",
]


@dataclass
class Observation:
    tool: str
    args: dict[str, Any]
    timestamp: float
    result: Any = None
    error: str | None = None

    def __post_init__(self) -> None:
        if (self.result is None) == (self.error is None):
            raise ValueError("Observation must set exactly one of result or error")


@dataclass
class AgentState:
    goal: str
    claim_id: str
    max_iterations: int = 6
    token_budget: int = 20000
    wall_clock_budget_seconds: float = 60.0
    observations: list[Observation] = field(default_factory=list)
    iteration_count: int = 0
    tokens_used: int = 0
    # time.monotonic() is only meaningful within this process — a dump is
    # for post-hoc inspection of a run, not for resuming timers cross-process.
    started_at: float = field(default_factory=time.monotonic)
    status: Status = "running"
    final_decision: dict[str, Any] | None = None

    def elapsed_seconds(self) -> float:
        return time.monotonic() - self.started_at

    def add_observation(self, obs: Observation) -> None:
        self.observations.append(obs)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentState":
        data = dict(data)
        data["observations"] = [Observation(**o) for o in data.get("observations", [])]
        return cls(**data)
