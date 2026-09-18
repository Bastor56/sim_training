# FDE Xlerate - Week 1, Day 3
Spec: port day 2's hand-rolled agent loop onto LangGraph

## Business problem

Unchanged from day 2 — same insurance claim fraud investigation, same
domain model, same tools, same claims. See `../week1_day2/spec.md` for the
full domain writeup (policies, claims, claim history, repair shop
reputation, weather records). Today's exercise is not a new business
problem; it's the same agent, moved onto a framework, with the goal of
producing an honest tradeoffs comparison — see `../../training_instructions/
week1_day3.md`.

## Goal

Re-implement day 2's agent on LangGraph with identical externally-visible
behavior: same tools available, same termination conditions, same retry
semantics. Prove behavior-equivalence by running the same two claims
(CLM-1001 clean, CLM-1042 suspicious) through both implementations and
diffing the tool-call sequence and final decision.

## What's reused unchanged from day 2

Imported directly (see `src/bootstrap.py`), not copied or reimplemented:

- `mock_data.py` — policies, claims, claim history, repair shop table,
  weather table
- `tools.py` — all 4 tool implementations, including the always-fails
  `check_repair_shop_reputation`
- `registry.py` — the tool registry dict
- `errors.py` — `ToolError`
- `planner.py` — `plan_next_action`, `validate_action`, the system prompt,
  the model pin (`claude-sonnet-5`), the two-shape JSON contract
- `state.py` — the `Observation` dataclass (used as the item type inside
  the graph's own state; see `src/graph_state.py`)

Only day 2's `loop.py` (the `while True` loop + termination checks) and
`executor.py` (the hand-rolled retry/backoff loop) are replaced — those two
are exactly the pieces LangGraph's orchestration layer takes over. That's
the diff the port is supposed to isolate.

## What's new for the port

| File | Day 2 equivalent | Role |
|---|---|---|
| `src/graph_state.py` | `state.py`'s `AgentState` | LangGraph state schema (a dataclass with reducers) |
| `src/graph_nodes.py` | `loop.py` + `executor.py` | Node functions + the retry policy |
| `src/graph.py` | `loop.py`'s `while True` structure | Graph wiring (nodes + conditional edges) |
| `src/run.py` | `run.py` | CLI entry, same shape, same output format |

See `tradeoffs.md` for the full day2-component -> LangGraph-equivalent
mapping, including the two places (planner's `tokens_used` mutation,
retry-exhaustion handling) where day 2's code couldn't be reused verbatim
and needed a small adapter.

## Setup (any machine)

Unlike day 1/2 (which install `anthropic` globally with
`--break-system-packages`, no venv), day 3 uses its own isolated virtualenv
so `langgraph` doesn't have to go anywhere near the global Python. This is
also just better practice, and it's what makes the steps below work the
same on a clean clone, not only on the machine that built this lab.

```bash
cd labs/week1_day3
python3 -m venv .venv          # any Python 3.10+ (langgraph's own minimum)
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# from the repo root, make sure ANTHROPIC_API_KEY is set (copy
# ../../.env.example to ../../.env and fill it in if you haven't already)

python3 -m unittest discover -s tests   # 6 tests, no live API calls
python3 src/run.py CLM-1001              # a real run against the live model
```

`.venv/` is gitignored — everyone who clones this repo creates their own,
which is the point: a committed venv bakes in one machine's absolute
paths and doesn't survive being copied to another machine at all.
`requirements.txt` pins the two versions this lab was actually tested
against (see that file's comment for why `anthropic` in particular is
pinned, not just floated to "latest").

## Troubleshooting: `pip install` crashes with a `pyexpat`/`libexpat` error

This is a known Homebrew issue on some macOS builds, unrelated to this lab:
a `python@3.14` bottle can end up linked against a newer `libexpat` symbol
than the OS actually ships, which breaks anything touching Python's `xml`/
`plistlib` modules — including `pip`'s own internal version-detection code.
`anthropic` alone doesn't hit this path (day 1/2 are unaffected), but
`langgraph`'s install does.

If `python3 --version` reports 3.14 and this happens, install a different
Python 3.10+ via Homebrew (e.g. `brew install python@3.12`) and use that
interpreter specifically to create `.venv` in the steps above:
`/opt/homebrew/opt/python@3.12/bin/python3.12 -m venv .venv`. This is a
workaround for one machine's broken interpreter, not a requirement of this
lab — someone without that bug just uses their normal `python3`.

## Out of scope

Same as day 2: no real APIs, no persistence beyond the JSON dumps under
`runs/`, no multi-agent decomposition.
