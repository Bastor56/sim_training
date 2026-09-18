# FDE Xlerate - Week 1, Day 2
Spec: hand-built agent loop — insurance claim fraud investigation

## Business problem

Day 1 built FNOL intake: one LLM call turns an unstructured claim report into a
structured record. No loop, no branching — every claim takes exactly one step.

Today's agent picks up where that leaves off. Given a submitted claim, it
investigates whether the claim looks fraudulent before it reaches a human
adjuster. Unlike intake, the number of investigative steps cannot be known in
advance: a clean claim might clear after checking the policy and history; a
suspicious one might need every tool available — repair shop reputation,
weather corroboration, repeated cross-checks — before the agent is confident
enough to decide. That variability is exactly what a fixed workflow can't
express and what the agent loop exists to handle.

## Goal

Given a `claim_id`, produce one of three decisions — `approve`, `deny`,
`escalate` — plus the full observation trail (every tool called, its result,
and the reasoning) that justifies the decision.

## Requirements

Restated from `training_instructions/week1_day2.md`:

1. Tool registry maps a tool name → callable + typed parameter schema +
   description. Adding a tool means adding a registry entry — never editing
   the loop.
2. Every iteration appends a structured observation record (tool name,
   arguments, result or error, timestamp) to agent state. The planner reasons
   over these records, not free-text scratch notes.
3. A failed tool call retries with exponential backoff (jitter, capped
   attempts). Once the cap is hit, the failure becomes an observation the
   planner reasons about — not an exception that kills the run.
4. Termination is explicit and multi-conditional: planner final-answer
   signal, max iteration count, token/wall-clock budget. Prove the loop
   can't run forever using a tool that always fails.
5. Agent state is one serializable object threaded through the loop — no
   module-level mutable globals — so a run can be dumped mid-flight and
   replayed.
6. A tool error (recoverable, fed back to the planner) is handled
   differently from a harness error (a bug in the loop's own code, raised).

## Domain model (mock data — no real APIs, no DB)

**Policy record** — `policy_id`, `claimant_id`, `coverage_type`, `limit`,
`start_date`

**Claim record** (the input to a run) — `claim_id`, `policy_id`,
`claimant_id`, `claimed_amount`, `damage_type`, `incident_date`,
`incident_location`, `repair_shop_id`

**Claim history table** — `claimant_id` → list of past claims (frequency and
amount patterns are the fraud signal)

**Repair shop reputation table** — `repair_shop_id` → reputation score +
flags

**Weather record table** — `(location, date)` → conditions, used to
corroborate or contradict a claimed cause of damage (e.g., hail claimed, no
hail recorded)

Keep every table to a handful of records — enough to construct one clean
claim and one suspicious claim. Realism isn't the point; branching is.

## Tool registry

| Tool | Args | Returns | Notes |
|---|---|---|---|
| `get_policy_details` | `policy_id` | policy record | |
| `get_claim_history` | `claimant_id` | list of past claims | |
| `check_repair_shop_reputation` | `repair_shop_id` | reputation score, flags | **Designated flaky tool** — always raises a simulated `ToolError` (service unavailable). This is the forced-failure demo. |
| `check_weather_conditions` | `location`, `date` | weather record | |

Each registry entry: `{"fn": callable, "schema": {...typed params...}, "description": "..."}`.

## Agent state

A single dataclass, threaded through every function — never a global:

```
AgentState:
  goal: str                    # e.g. "investigate claim CLM-1042 for fraud"
  claim_id: str
  observations: list[Observation]
  iteration_count: int
  max_iterations: int
  tokens_used: int
  token_budget: int
  started_at: float
  wall_clock_budget_seconds: float
  status: "running" | "terminated_success" | "terminated_iteration_limit" | "terminated_budget_limit"
  final_decision: dict | None   # set only on terminated_success
```

`Observation`: `{tool, args, result | error, timestamp}` — always one of
`result` or `error`, never both.

## Planner contract

Input: `goal` + full `observations` list (structured, not summarized to
text). Output: strict JSON — **exactly these two shapes, nothing else.**
Every planner turn is either "keep going" or "I'm done," never free text and
never a third option — that's what "explicit termination" (requirement 4)
means in practice.

```json
{"action": "call_tool", "tool": "<any registered tool name>", "args": {...matches that tool's schema...}, "reasoning": "..."}
```
```json
{"action": "terminate", "decision": "approve" | "deny" | "escalate", "reasoning": "..."}
```

`call_tool` is generic, not tied to one tool — `"tool"` must be one of the 4
registry names (`get_policy_details`, `get_claim_history`,
`check_repair_shop_reputation`, `check_weather_conditions`) and `"args"`
must match whichever tool's schema. One instantiation, for illustration:

```json
{"action": "call_tool", "tool": "check_weather_conditions", "args": {"location": "...", "date": "..."}, "reasoning": "..."}
```

This genericity is also what satisfies requirement 1 (tool registry
extension without touching the loop): a 5th tool needs no new planner
shape, since `call_tool` already covers "any tool in the registry" — only
the registry dict and the tool's own implementation change.

A response using any other `"action"` value, or missing required fields, is
a parse failure — treat it as a harness-visible problem in Phase 4 (log and
raise), not something to silently guess around.

System prompt instructs the planner: keep investigating while evidence is
ambiguous (repeat claimant, shop flagged, weather contradicts the story);
terminate once confident. This is what makes the step count data-dependent
rather than scripted.

## Executor / retry policy

- Catch `ToolError` (recoverable — simulated timeouts, bad lookups) inside
  the executor; anything else (e.g. a `KeyError` from a dispatch bug) is a
  harness error and propagates as a real exception, ending the run loudly.
- Backoff: `delay = base * 2 ** attempt + random_jitter`, capped at 3
  attempts.
- On exhausted retries: wrap the last error into an observation (not a
  crash) and hand control back to the planner.

## Termination conditions

Checked at the top of every iteration, before calling the planner:

1. Planner emitted `terminate` on the previous turn → `terminated_success`
2. `iteration_count >= max_iterations` → `terminated_iteration_limit`
3. `tokens_used >= token_budget` or elapsed time exceeds
   `wall_clock_budget_seconds` → `terminated_budget_limit`

Exactly two legitimate exits: planner says done, or a limit is hit. No other
path out of the loop.

## Deliverables mapping

| Lab deliverable | Satisfied by |
|---|---|
| Running agent, ≥2 tools in sequence, observation history | Clean-claim run: policy + history checks, decision reached |
| Forced-failure run, backoff in the log, clean termination at cap | Suspicious-claim run that must call `check_repair_shop_reputation` |
| State-machine diagram of agent + failure modes | See `artifacts/` (diagram generated separately) |
| 5–8 slide deck | See `artifacts/` (deck generated separately) |

## Out of scope

No framework, no persistence beyond the in-memory state dump, no
multi-agent decomposition — those come later in the program.

## Setup

The one third-party dependency (`anthropic`) is pinned in
`requirements.txt`. This lab installs it globally (no venv), matching how
it was originally built:

```bash
cd labs/week1_day2
python3 -m pip install --break-system-packages -r requirements.txt

# from the repo root, make sure ANTHROPIC_API_KEY is set (copy
# ../../.env.example to ../../.env and fill it in if you haven't already)

python3 -m unittest discover -s tests   # 41 tests, no live API calls
```

`--break-system-packages` is only needed on a PEP 668 "externally managed"
Python (Homebrew's, notably) that refuses global installs by default; a
plain `python3 -m venv` + `pip install -r requirements.txt` works too and
is the safer default going forward — see `../week1_day3/spec.md`'s Setup
section for that pattern, which this lab predates.
