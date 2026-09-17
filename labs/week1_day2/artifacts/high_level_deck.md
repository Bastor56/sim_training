# FDE Xlerate - Week 1, Day 2
High-level deck: hand-built agent loop (insurance claim fraud investigation)

## Slide 1: Title / Framing
- Exercise: build the agent loop by hand, no framework, so nothing is hidden.
- Use case: investigate a submitted insurance claim for fraud signals before
  it reaches a human adjuster.
- Builds directly on day 1's FNOL intake — that produced a structured claim
  record in one LLM call; today's agent decides what to do with it.

## Slide 2: The Problem
- Day 1 was one shot: prompt in, structured object out, done.
- A fraud investigation can't be scripted that way — the number of checks
  needed depends on what earlier checks find. A clean claim might resolve
  after two lookups; a suspicious one needs every tool available.
- That variability is exactly what a fixed workflow can't express and what
  an agent loop exists to handle.

## Slide 3: High-Level Flow
```
                 ┌─────────────┐
        ┌───────▶│  Planning   │───────┐
        │        └─────────────┘       │
        │               │              │
   [observation           │        [planner says
    appended]        chooses a       "terminate"]
        │            tool call            │
        │               ▼                 ▼
┌───────────────┐  ┌────────────┐   Terminated
│   Observing    │◀─┤  Executing │   (success)
└───────────────┘  └────────────┘
                          │
                    tool fails → retry
                    with backoff (capped
                    at 3), then becomes
                    an observation
```
- Exactly two ways out, checked at the top of every iteration: the planner
  says it's done, or a limit (iteration count / token / wall-clock budget)
  is hit — never a third path.
- The retry/backoff sub-loop lives entirely inside one `Executing` turn; it
  never inflates the outer iteration count.

## Slide 4: Architecture
- **Tool registry** (`registry.py`) — name → callable + JSON-schema-style
  args + description. 4 tools: `get_policy_details`, `get_claim_history`,
  `check_repair_shop_reputation` (deliberately flaky), `check_weather_conditions`.
- **Agent state** (`state.py`) — one dataclass threaded through the whole
  run: goal, observation history, iteration/token/time counters, status.
  No module-level globals — a run can be dumped to JSON mid-flight.
- **Planner** (`planner.py`) — one Claude call per turn, constrained to two
  JSON output shapes (`call_tool` / `terminate`); anything else is treated
  as a harness-visible contract violation and raised, not guessed around.
- **Executor** (`executor.py`) — dispatches the tool, owns exponential
  backoff with jitter (capped at 3 attempts), and always returns an
  Observation — a tool failure becomes data for the planner, never a crash.
- **Termination checker** — runs before the planner is even called each
  iteration, so the loop's upper bound doesn't depend on the planner or any
  tool cooperating.

## Slide 5: Tech Stack
- Python for the loop, registry, and executor — no agent framework.
- Anthropic API (`claude-sonnet-5`) as the planner — same vendor/model as
  day 1's FNOL intake, so the loop is the only new variable.
- In-memory state (a dataclass), no persistence — the boundary between
  agent state and durable memory stays visible until later in the program.
- Hand-written backoff (`delay = 0.5 * 2^attempt + jitter`) instead of a
  retry library, so the curve is inspectable and tunable.
- 39 unit tests (`tests/`, stdlib `unittest`) covering state invariants,
  each tool, the retry/backoff mechanics, planner-contract validation
  (against a fake client — no network calls), and the loop's termination
  guarantees.

## Slide 6: Demo — Golden Path
Two real runs against the live model, full traces in `runs/`:

| Claim | Tools called | Iterations | Decision |
|---|---|---|---|
| CLM-1001 (clean) | policy → history → weather → repair shop (failed) | 5 | **approve** |
| CLM-1042 (suspicious) | policy → history → weather → repair shop (failed) | 5 | **deny** |

- Same tools available to both, but the *evidence* drove different
  decisions: CLM-1042's weather record contradicted the claimed hail
  damage ("clear and sunny, no precipitation") on top of 3 prior claims
  totaling $75,500 in 18 months — the planner denied it on that basis.
- CLM-1001's weather record corroborated the claim and its history was
  clean — approved despite the same repair-shop tool failure.
- In both runs, the repair-shop tool failed and got retried automatically;
  the planner reasoned around the missing data rather than stalling.

## Slide 7: Demo — Forced Failure
- Scripted run (`demo_forced_failure.py`) forces `check_repair_shop_reputation`
  on turn 1, deterministically — reproducible independent of what the live
  model would choose to call.
- Log (`runs/forced_failure.log`) shows the backoff curve directly:
  `attempt 1 failed → backing off 0.61s`, `attempt 2 failed → backing off
  1.10s`, `attempt 3 failed → retry cap hit`.
- The exhausted failure becomes a single error observation; the (scripted)
  planner reasons over it and terminates with `escalate` — the process
  exits 0, never an unhandled exception.

## Slide 8: Takeaways
- The loop's forever-bound is structural, not planner-dependent: the
  termination check runs before the planner is called, so a stuck or
  uncooperative planner still gets cut off at `max_iterations`.
- A tool error and a harness error are handled by genuinely different code
  paths (`ToolError` → retry → observation vs. everything else → raise) —
  that distinction is what let two live runs survive a real tool outage
  without either crashing or silently ignoring it.
- Every framework this program uses from tomorrow onward is a wrapper
  around this same five-piece ring.
