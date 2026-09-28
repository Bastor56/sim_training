"""Milestone 2: does each model accept its configuration? (plan.md, highest risk)

One tiny structured-output call per distinct role config, all through
llm.call(), so even this first real spend is recorded and in the ledger.
A 400 here means the request shape is wrong for that model or for the
pinned SDK: fix llm._send() and re-run with --only <name>.

    uv run python src/smoke.py [--only haiku,sonnet,opus]
"""

from __future__ import annotations

import argparse

import llm
import settings
import tracing

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"],
          "additionalProperties": False}

CONFIGS = {
    "haiku": settings.GENERATORS["haiku"],    # also the gate/rewrite config
    "sonnet": settings.GENERATORS["sonnet"],  # also the judge config
    "opus": settings.GENERATORS["opus"],
}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--only", default=",".join(CONFIGS))
    args = ap.parse_args()

    tracing.start_run("smoke")
    with tracing.interaction("smoke/1"):
        for name in args.only.split(","):
            role = CONFIGS[name]
            try:
                r = llm.call("smoke", role, system="You are a connectivity check.",
                             user='Reply with the JSON object {"ok": true}.', prompt_version="smoke_v1",
                             output_schema=SCHEMA)
                rec = r.record
                print(f"{name:7s} OK   served={r.model_served:18s} data={r.data} in={rec['input_tokens']} "
                      f"out={rec['output_tokens']} cache_w={rec['cache_creation_input_tokens']} "
                      f"cache_r={rec['cache_read_input_tokens']} {r.latency_ms:.0f} ms ${r.cost_usd:.5f}")
            except Exception as e:  # report every config, don't stop at the first failure
                print(f"{name:7s} FAIL {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
