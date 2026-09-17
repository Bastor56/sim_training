# FDE Xlerate - Week 1, Day 2
Build plan: hand-built agent loop — insurance claim fraud investigation

See `spec.md` for the full design (schemas, contracts, tool table). This is
the build order — each phase should be working and sanity-checked before
moving to the next.

## Suggested file layout

```
labs/week1_day2/
  spec.md
  plan.md
  src/
    mock_data.py      # Phase 0
    state.py           # Phase 1
    tools.py            # Phase 2
    registry.py         # Phase 2
    executor.py          # Phase 3
    planner.py           # Phase 4
    loop.py               # Phase 5
    run.py                 # CLI entry: golden-path + forced-failure runs
  runs/                     # dumped state / logs from demo runs (Phase 6-7)
  artifacts/
    state_machine_diagram.*  # Phase 8
    high_level_deck.md        # Phase 8
```

## Phase 0 — Domain / mock data

- [ ] Policy records (2–3)
- [ ] One clean claim + one suspicious claim
- [ ] Claim history table (make one claimant look like a repeat filer)
- [ ] Repair shop table (one shop flagged, doesn't matter which since the
      tool always fails anyway — see Phase 2)
- [ ] Weather table (one entry that contradicts a claimed damage cause)

**Done when:** you can manually look up every claim by hand and say what the
"right" decision should be — that's your answer key for Phase 6.

## Phase 1 — Agent state

- [ ] `AgentState` dataclass per spec
- [ ] `Observation` type
- [ ] A `to_dict()` / `from_dict()` (or just `dataclasses.asdict`) so a run
      can be serialized mid-flight

**Done when:** you can construct a state, mutate it, and `json.dumps` it
without errors.

## Phase 2 — Tools + registry

- [ ] Implement the 4 tools against the mock data
- [ ] `check_repair_shop_reputation` always raises `ToolError`
- [ ] Define `ToolError` (recoverable) as its own exception class,
      separate from Python built-ins
- [ ] Build the registry dict: name → `{fn, schema, description}`

**Done when:** you can call each tool directly (outside the loop) and get
the expected result or the expected `ToolError`.

## Phase 3 — Executor

- [ ] Dispatch: look up tool in registry, call with args
- [ ] Catch `ToolError` → backoff loop (exponential + jitter, cap 3)
- [ ] Catch anything else → let it propagate (harness bug)
- [ ] On success or exhausted retries → build and return an `Observation`

**Done when:** calling the executor on the flaky tool produces 3 retries
with visibly growing delays, then returns an error observation instead of
raising.

## Phase 4 — Planner

- [ ] System prompt: goal, tool descriptions, instruction to keep
      investigating while evidence is ambiguous, JSON-only output contract
- [ ] Serialize `observations` into the prompt as structured data
- [ ] Parse the response into the two known shapes; treat a malformed
      response as a harness-visible problem (log it, don't silently guess)

**Done when:** given a hand-written fake observation history, the planner
returns valid JSON matching one of the two shapes, for both a "keep
investigating" case and a "terminate" case.

## Phase 5 — The loop

- [ ] Termination check at the top of every iteration
- [ ] `planner → executor → append observation → loop`
- [ ] Increment `iteration_count`, `tokens_used`, check wall clock each pass
- [ ] Set `status` and `final_decision` on exit

**Done when:** the loop runs start-to-finish on a trivial fake planner
(e.g., one that always terminates immediately) without manual intervention.

## Phase 6 — Golden-path demo

- [ ] Run the clean claim → confirm it resolves in ~2 tool calls
- [ ] Run the suspicious claim → confirm it pulls in more tools (history,
      weather) before deciding — proving step count is data-dependent, not
      hardcoded
- [ ] Save both observation histories under `runs/`

**Done when:** the two runs visibly differ in length and tools used, and
both reach a sensible decision per your Phase 0 answer key.

## Phase 7 — Forced-failure demo

- [ ] Run a claim that must call `check_repair_shop_reputation`
- [ ] Confirm in the log: retries with backoff, cap hit, failure becomes an
      observation, planner reasons around it (e.g. escalates) instead of the
      process crashing
- [ ] Save this run under `runs/`

**Done when:** the process exits cleanly with `status =
terminated_success` (or a limit-hit status if you push it further) — never
an unhandled exception.

## Phase 8 — Deliverables

- [ ] State-machine diagram (states + both legitimate exits + the
      retry/backoff sub-loop + the harness-error escape hatch) — use the
      diagram prompt already drafted in this conversation
- [ ] 5–8 slide deck: problem framing → architecture ring → tech stack →
      golden-path results → forced-failure results
- [ ] Confirm both live under `artifacts/`

## Things to watch for (beginner pitfalls)

- **Infinite loop risk**: if the termination check has a bug, nothing else
  in this design stops the loop — test the iteration cap first, before you
  trust anything else.
- **Malformed planner JSON**: decide up front whether a parse failure is a
  tool error (retry the planner call) or a harness error (raise) — don't
  leave it ambiguous.
- **Backoff without jitter**: pure exponential backoff with no randomness
  is fine here since there's only one caller, but note in the deck *why*
  jitter matters at production scale (avoiding synchronized retry storms
  across many concurrent runs) even though this lab won't demonstrate it.
- **Conflating tool errors with bad decisions**: a tool succeeding but
  returning suspicious data (e.g., a flagged shop) is not an error — it's
  a normal observation the planner reasons over. Only actual failures
  (exceptions) go through the retry path.
