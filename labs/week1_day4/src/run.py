"""CLI entry point: run the customer-service agent through a scripted
multi-turn conversation against a live mock CRM, print the full turn
history, and optionally save it as JSON.

Mirrors day 3's run.py shape (argparse, JSON to stdout, one-line summary
to stderr, optional --out) even though the underlying conversation is
multi-turn rather than single-shot -- same reasons: predictable, scriptable
output that's easy to diff and easy to check into runs/.

The mock CRM is NOT started by this script -- per the plan's "demo
process management" decision, it's a genuinely separate process you start
yourself, the same way a real CRM would be something this agent has no
control over the lifecycle of:

    # terminal 1
    cd labs/week1_day4 && source .venv/bin/activate
    uvicorn app:app --app-dir mock_crm --port 8000

    # terminal 2
    cd labs/week1_day4 && source .venv/bin/activate
    export ANTHROPIC_API_KEY=...   # or source ../../.env
    python3 src/run.py CUST-1001 "what's my balance?" "and what about the other one?"
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from dataclasses import asdict

from graph import bootstrap_session, build_graph
from tool_client import DEFAULT_BASE_URL, CRMClient, build_http_client


def main(argv: "list[str] | None" = None) -> None:
    parser = argparse.ArgumentParser(
        description="Run the customer-service agent through a scripted multi-turn conversation."
    )
    parser.add_argument("customer_id", help="a customer_id from the mock CRM's fixtures, e.g. CUST-1001")
    parser.add_argument("messages", nargs="+", help="one or more user messages, run as successive turns in one session")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="mock CRM base URL (must already be running)")
    parser.add_argument("--session-id", help="checkpointer thread_id; defaults to a fresh random id")
    parser.add_argument("--out", help="path to save the full run as JSON")
    args = parser.parse_args(argv)

    crm_client = CRMClient(build_http_client(base_url=args.base_url))
    graph = build_graph(crm_client=crm_client)

    session_id = args.session_id or str(uuid.uuid4())
    config = {"configurable": {"thread_id": session_id}}

    bootstrap_fields = bootstrap_session(crm_client, session_id=session_id, customer_id=args.customer_id)

    result = None
    for i, message in enumerate(args.messages):
        update = {"pending_user_message": message}
        if i == 0:
            update = {**bootstrap_fields, **update}
        result = graph.invoke(update, config=config)

    dump = {
        "session_id": session_id,
        "customer_id": args.customer_id,
        "turns": [asdict(turn) for turn in result["turns"]],
    }

    print(json.dumps(dump, indent=2, default=str))
    print(f"\nsession_id={session_id} customer_id={args.customer_id} turns={len(dump['turns'])}", file=sys.stderr)

    if args.out:
        out_dir = os.path.dirname(args.out)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(args.out, "w") as f:
            json.dump(dump, f, indent=2, default=str)


if __name__ == "__main__":
    main()
