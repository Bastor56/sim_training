"""CLI entry point: run the agent on a given claim_id, print the full
observation trail, and optionally save it as JSON. See plan.md Phase 6
(golden path) and Phase 7 (forced failure).

Usage (from labs/week1_day2/src):
    python3 run.py CLM-1001 --out ../runs/clm-1001.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from loop import run_agent
from mock_data import CLAIMS
from state import AgentState


def build_state(claim_id: str) -> AgentState:
    if claim_id not in CLAIMS:
        raise SystemExit(f"unknown claim_id: {claim_id!r} (known: {list(CLAIMS)})")
    claim = CLAIMS[claim_id]
    return AgentState(
        goal=(
            f"Investigate claim {claim_id} for fraud and reach a decision: "
            f"approve, deny, or escalate. Claim details: policy_id="
            f"{claim['policy_id']!r}, claimant_id={claim['claimant_id']!r}, "
            f"claimed_amount={claim['claimed_amount']}, damage_type="
            f"{claim['damage_type']!r}, incident_date={claim['incident_date']!r}, "
            f"incident_location={claim['incident_location']!r}, repair_shop_id="
            f"{claim['repair_shop_id']!r}."
        ),
        claim_id=claim_id,
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the claim fraud investigation agent.")
    parser.add_argument("claim_id", help=f"one of: {', '.join(CLAIMS)}")
    parser.add_argument("--out", help="path to save the full run as JSON")
    args = parser.parse_args(argv)

    state = build_state(args.claim_id)
    final_state = run_agent(state)

    dump = final_state.to_dict()
    print(json.dumps(dump, indent=2, default=str))
    print(
        f"\nstatus={final_state.status} iterations={final_state.iteration_count} "
        f"tokens_used={final_state.tokens_used}",
        file=sys.stderr,
    )

    if args.out:
        out_dir = os.path.dirname(args.out)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(args.out, "w") as f:
            json.dump(dump, f, indent=2, default=str)


if __name__ == "__main__":
    main()
