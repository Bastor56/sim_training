"""Phase 7 deliverable: a deterministic forced-failure run.

Uses the real executor (real retries, real time.sleep backoff, real
observations) but drives the loop with a scripted planner instead of the
live LLM, so the "must call check_repair_shop_reputation" scenario from
plan.md Phase 7 is reproducible on every run rather than depending on
whether the live model happens to choose that tool.

Usage (from labs/week1_day2/src):
    python3 demo_forced_failure.py --out ../runs/forced_failure.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from loop import run_agent
from mock_data import CLAIMS
from state import AgentState

CLAIM_ID = "CLM-1042"


def scripted_planner_forcing_the_flaky_tool(state: AgentState) -> dict:
    claim = CLAIMS[CLAIM_ID]

    already_tried = any(o.tool == "check_repair_shop_reputation" for o in state.observations)
    if not already_tried:
        return {
            "action": "call_tool",
            "tool": "check_repair_shop_reputation",
            "args": {"repair_shop_id": claim["repair_shop_id"]},
            "reasoning": "verify the repair shop's reputation before deciding",
        }

    return {
        "action": "terminate",
        "decision": "escalate",
        "reasoning": (
            "repair shop reputation check failed even after retries; "
            "escalating to a human adjuster rather than deciding on "
            "incomplete evidence"
        ),
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the forced-failure/backoff demo.")
    parser.add_argument("--out", help="path to save the full run as JSON")
    args = parser.parse_args(argv)

    claim = CLAIMS[CLAIM_ID]
    state = AgentState(
        goal=f"Investigate claim {CLAIM_ID} for fraud (scripted forced-failure demo).",
        claim_id=CLAIM_ID,
    )

    final_state = run_agent(state, planner=scripted_planner_forcing_the_flaky_tool)

    dump = final_state.to_dict()
    print(json.dumps(dump, indent=2, default=str))
    print(
        f"\nstatus={final_state.status} iterations={final_state.iteration_count}",
        file=sys.stderr,
    )
    assert final_state.status == "terminated_success", (
        "expected the loop to terminate cleanly via the planner's terminate "
        f"signal, not {final_state.status!r} -- the loop must not hang or "
        "crash on a persistently failing tool"
    )
    assert any(o.error is not None for o in final_state.observations), (
        "expected at least one observation to record the exhausted-retries "
        "failure, proving it became an observation rather than an exception"
    )

    if args.out:
        out_dir = os.path.dirname(args.out)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(args.out, "w") as f:
            json.dump(dump, f, indent=2, default=str)


if __name__ == "__main__":
    main()
