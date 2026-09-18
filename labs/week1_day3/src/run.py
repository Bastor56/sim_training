"""CLI entry point: run the LangGraph-ported agent on a given claim_id,
print the full observation trail, and optionally save it as JSON.

Mirrors day 2's run.py exactly (same claim goal string, same CLI shape,
same output shape) so the two runs' JSON dumps can be diffed directly.

Usage (from labs/week1_day3/src, with the day3 .venv activated):
    python3 run.py CLM-1001 --out ../runs/clm-1001_langgraph.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict

import bootstrap  # noqa: F401
from mock_data import CLAIMS

from graph import build_graph
from graph_state import GraphState


def build_initial_state(claim_id: str) -> GraphState:
    if claim_id not in CLAIMS:
        raise SystemExit(f"unknown claim_id: {claim_id!r} (known: {list(CLAIMS)})")
    claim = CLAIMS[claim_id]
    return GraphState(
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
        started_at=time.monotonic(),
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the LangGraph-ported claim fraud investigation agent.")
    parser.add_argument("claim_id", help=f"one of: {', '.join(CLAIMS)}")
    parser.add_argument("--out", help="path to save the full run as JSON")
    args = parser.parse_args(argv)

    graph = build_graph()
    initial_state = build_initial_state(args.claim_id)
    final = graph.invoke(initial_state)  # LangGraph returns a plain dict of final channel values

    dump = dict(final)
    dump["observations"] = [asdict(o) for o in dump["observations"]]

    print(json.dumps(dump, indent=2, default=str))
    print(
        f"\nstatus={dump['status']} iterations={dump['iteration_count']} "
        f"tokens_used={dump['tokens_used']}",
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
