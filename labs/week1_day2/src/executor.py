"""Executor: dispatches a tool call, owns retry/backoff, and always returns
an Observation — success, or an exhausted-retries failure — rather than
letting a recoverable tool error crash the run. See spec.md 'Executor /
retry policy'.
"""

from __future__ import annotations

import random
import sys
import time
from typing import Any, Callable

from errors import ToolError
from registry import REGISTRY
from state import Observation

MAX_ATTEMPTS = 3
BASE_DELAY_SECONDS = 0.5


class UnknownToolError(Exception):
    """The planner named a tool that isn't in the registry. Planner output
    validation (planner.validate_action) should catch this before it ever
    reaches the executor — landing here means that validation was skipped
    or has a bug, i.e. a harness error, so it propagates rather than
    becoming an observation."""


def backoff_delay(attempt: int) -> float:
    """attempt is 0-indexed. Exponential growth plus jitter so the curve is
    inspectable: 0 -> ~0.5-1.0s, 1 -> ~1.0-1.5s, 2 -> ~2.0-2.5s."""
    return BASE_DELAY_SECONDS * (2**attempt) + random.uniform(0, BASE_DELAY_SECONDS)


def execute_tool(
    tool_name: str,
    args: dict[str, Any],
    sleep: Callable[[float], None] = time.sleep,
) -> Observation:
    if tool_name not in REGISTRY:
        raise UnknownToolError(f"{tool_name!r} is not a registered tool")

    fn = REGISTRY[tool_name]["fn"]
    last_error: str | None = None

    for attempt in range(MAX_ATTEMPTS):
        try:
            result = fn(**args)
            return Observation(tool=tool_name, args=args, timestamp=time.time(), result=result)
        except ToolError as exc:
            last_error = str(exc)
            if attempt < MAX_ATTEMPTS - 1:
                delay = backoff_delay(attempt)
                print(
                    f"[retry] {tool_name}({args}) failed on attempt {attempt + 1}/"
                    f"{MAX_ATTEMPTS}: {last_error} -- backing off {delay:.2f}s",
                    file=sys.stderr,
                )
                sleep(delay)
            else:
                print(
                    f"[retry] {tool_name}({args}) failed on attempt {attempt + 1}/"
                    f"{MAX_ATTEMPTS}: {last_error} -- retry cap hit, "
                    "returning as an error observation",
                    file=sys.stderr,
                )

    return Observation(tool=tool_name, args=args, timestamp=time.time(), error=last_error)
