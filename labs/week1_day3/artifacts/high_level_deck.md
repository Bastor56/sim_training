# FDE Xlerate - Week 1, Day 3
High-level deck: porting the hand-built agent loop onto LangGraph

## Slide 1: Title / Framing
- Exercise: take day 2's hand-rolled fraud-investigation agent and port it
  onto LangGraph, unchanged in behavior, so the diff shows only the
  orchestration layer.
- Same use case as day 2: investigate a submitted insurance claim for
  fraud signals before it reaches a human adjuster.
- The point isn't "LangGraph is better" or "hand-rolled is better" — it's
  that on a real engagement, the client's platform team has usually
  already picked the framework (or their security review will pick it for
  you). The skill being practiced is mapping concepts across that
  boundary honestly, criticism included.

## Slide 2: The Problem
- A client architect doesn't want to hear "I prefer X" — they want to know
  exactly what maps, what doesn't, and what breaks quietly if nobody
  checks.
- Day 2's five-piece ring (planner / registry / executor / state /
  termination check) was designed with explicit, hand-written contracts
  for every one of those pieces. Moving it onto a framework tests whether
  those contracts survive the move, or whether some of them were secretly
  relying on being hand-rolled.
- Two of the five didn't survive unchanged: the planner's in-place state
  mutation, and the executor's retry-exhaustion handling. Both needed a
  small adapter — see Slide 5.

## Slide 3: High-Level Flow
```
        day 2 (hand-rolled)                day 3 (LangGraph)

     ┌─────────────┐                    ┌───────────────┐
┌───▶│  Planning   │───┐           ┌───▶│ check_limits  │───┐
│    └─────────────┘   │           │    └───────────────┘   │
│           │           │          │            │            │
│      chooses a    [terminate]    │       route: planner  route: limit_hit
│      tool call         │         │            │            │
│           ▼            ▼         │            ▼            ▼
│    ┌────────────┐  Terminated    │      ┌──────────┐   Terminated
└────┤  Executing │  (success)     └──────┤ executor │  (iteration/
     └────────────┘                       │+RetryPolicy│   budget limit)
                                           └──────────┘
     retry/backoff hand-written        retry/backoff = framework
     inside Executing                  RetryPolicy on the executor node
```
- Same ring, same two legitimate exits (planner says done, or a limit is
  hit) — the shape of the state machine didn't change.
- What changed is *who* runs the loop. Day 2's `while True` is your code
  calling your code. Day 3's edges are the graph deciding what runs next,
  based on a label your routing function returned.

## Slide 4: Architecture — what's reused vs. new
- **Reused unchanged** (imported directly, see `src/bootstrap.py`):
  `tools.py`, `registry.py`, `mock_data.py`, `errors.py`, and — most
  importantly — `planner.py`'s `plan_next_action`: same system prompt,
  same model pin, same JSON contract.
- **Replaced**: `loop.py` and `executor.py`'s hand-rolled retry loop —
  exactly the two pieces LangGraph's orchestration layer takes over.
- **New**: `graph_state.py` (the state schema), `graph_nodes.py` (node
  functions + `RetryPolicy`), `graph.py` (the wiring).
- Two adapters were unavoidable, not optional: a shim object for the
  planner's `tokens_used` mutation, and a `node_attempt`-based check so an
  exhausted retry becomes an observation instead of crashing the graph.
  See `../tradeoffs.md` for why both are structural, not style choices.

## Slide 5: Tech Stack
- **Orchestration**: LangGraph `StateGraph` (`langgraph==1.2.11`) — low-level
  graph primitives (nodes + conditional edges), deliberately not the
  prebuilt ReAct-agent constructor, so the planner's prompt stays day 2's
  own and isn't replaced by the framework's.
- **Model/SDK**: same `claude-sonnet-5` pin as day 2, via `anthropic`
  pinned to the exact same `0.104.1` day 2 uses — not "latest," because a
  newer major version drops the `temperature` kwarg day 2's `planner.py`
  passes, which would silently turn this into a model/SDK comparison
  instead of a framework comparison.
- **Retry**: `RetryPolicy` (LangGraph's own retry primitive) attached to
  the executor node, configured to match day 2's hand-written curve
  (`initial_interval=0.5, backoff_factor=2.0, max_attempts=3, jitter=True`)
  — the framework's idiom standing in for day 2's hand-rolled backoff loop.
- **Environment**: an isolated venv (`requirements.txt`) rather than day
  1/2's global install — `langgraph` never touches the global Python, and
  the setup is what let this actually be verified from a clean, from-scratch
  install rather than just "works in the venv already sitting here."
- **Tests**: `tests/test_graph.py`, 6 fake-planner tests ported from day
  2's `test_loop.py`, using a fast `RetryPolicy` variant since the
  framework's retry sleep can't be swapped out the way day 2's injectable
  `sleep` parameter could.

## Slide 6: What LangGraph gives you — and what it costs
- **Gained**: retry/backoff as declarative config instead of hand-written
  loop code; a static graph object you can inspect before running it;
  `interrupt()` for real mid-run human-in-the-loop, which day 2 had no
  equivalent for at all.
- **Cost**: `RetryPolicy` retries the *entire node*, not just the risky
  call inside it — day 2's hand-rolled loop only ever retried the tool
  call itself. Getting day-2-equivalent granularity back required reading
  the current attempt off `get_runtime().execution_info.node_attempt`,
  which is a framework-specific escape hatch, not something obvious from
  the docs alone.
- **Cost**: day 2's injectable `sleep` (for fast, deterministic backoff
  tests) has no equivalent — the framework's retry sleep is hardcoded.
  Tests can only get faster by changing the timing config itself, which
  means they're no longer testing the production curve.

## Slide 7: Demo — Behaviour-equivalence
Same two claims day 2 used, run live against the same model:

| Claim | day 2 tool sequence | day 3 tool sequence | Decision (both) |
|---|---|---|---|
| CLM-1001 (clean) | policy → history → weather → repair shop (failed) | identical, same order | **approve** |
| CLM-1042 (suspicious) | policy → history → weather → repair shop (failed) | policy → history → **repair shop (failed) → weather** (order swapped) | **deny** |

- Identical decision and iteration count on both claims. CLM-1042's tools
  3 and 4 came back in a different order — attributed to the planner's
  `temperature=1` sampling (same prompt, same model, reused unchanged),
  not to anything LangGraph's wiring changed. Full detail in
  `behavior_equivalence.md`.
- 6 fake-planner unit tests (`tests/test_graph.py`, ported from day 2's
  `test_loop.py`) pass with zero live API calls — proving the termination
  guarantees, retry-then-observation behavior, and budget caps hold
  independent of what the live model does on any given run.

## Slide 8: Framework comparison + Takeaways
- Full matrix in `comparison_matrix.md`: LangGraph, AutoGen, Semantic
  Kernel, Amazon Bedrock Agents, and Salesforce Agentforce
  (platform-native) across orchestration, state, tool integration, HITL,
  observability, learning curve, and enterprise readiness.
- Build-vs-platform-native scenario: a Salesforce-standardized P&C insurer
  — Agentforce owns the case/queue/audit trail adjusters already live in;
  a LangGraph (or hand-rolled) action plugs in only for the one thing the
  platform's builder can't express: the open-ended, budgeted,
  retry-aware fraud-investigation reasoning loop itself.
- The framework's actual footprint in this port is small and contained:
  two files (`graph.py`, `graph_nodes.py`) own 100% of the
  LangGraph-specific surface. Everything else — the prompt, the tools, the
  domain data, the retry *policy decision* — is either reused unchanged or
  would survive a framework swap untouched.
- "Framework-independent design" isn't a slogan here — it's the concrete
  fact that day 2's planner and tools ported with zero code changes,
  because they were never coupled to the loop that called them.
- The things that got harder to see (retry timing, the exact instant
  state commits) are real costs, not imagined ones — but they're costs of
  *this specific abstraction layer* (`StateGraph` + nodes), not of "using
  a framework" in general. A prebuilt agent constructor would have cost
  prompt visibility too; this port deliberately avoided that trade by
  staying at the lower layer.
