# FDE Xlerate - Week 1, Day 3
Build plan: port the day 2 agent onto LangGraph

See `spec.md` for what's reused unchanged vs. new. This is the build order.

## Phase 0 — Environment

- [x] Confirm day 2's tools/registry/planner/state are importable unchanged
      from a sibling lab directory (`src/bootstrap.py`'s `sys.path` shim)
- [x] `requirements.txt` pins `langgraph` + `anthropic==0.104.1` (matching
      day 2's version exactly); isolated venv, not a global install — see
      spec.md's "Setup" section
- [x] Verified portable: installed `requirements.txt` into a brand-new
      venv (no leftover state from building this lab) and confirmed both
      the test suite and a live `run.py` invocation pass against it —
      the actual "works on someone else's machine too" check, not just
      "works in the venv already sitting here"

**Done when:** `python3 -c "import bootstrap, tools, registry, planner, langgraph"`
succeeds from `src/`, using only what `requirements.txt` installs.

## Phase 1 — Graph state

- [ ] `GraphState` dataclass (`src/graph_state.py`): same fields as day 2's
      `AgentState`, plus `pending_action` (the framework-owned equivalent
      of a loop-local variable), `observations` using an `operator.add`
      reducer so returned lists append instead of overwrite

**Done when:** you can construct a `GraphState`, and a plain dict update
against one of its list fields behaves like an append when run through the
graph (see Phase 3).

## Phase 2 — Nodes

- [ ] `check_limits_node` (no-op hub) + `route_after_limits` (the day 2
      termination check, as a conditional edge function)
- [ ] `make_planner_node` — wraps day 2's `plan_next_action` unchanged via
      a small shim object (see `graph_nodes.py` docstring for why the shim
      exists: day 2's planner mutates `state.tokens_used` in place, which
      LangGraph nodes can't rely on)
- [ ] `executor_node` — calls the tool directly, no manual retry loop;
      catches `ToolError` only; on the framework's last allowed attempt
      (`get_runtime().execution_info.node_attempt`), converts the failure
      into an error `Observation` instead of letting it propagate

**Done when:** calling `executor_node` directly against the flaky tool,
wrapped in a graph with a fast `RetryPolicy`, produces an error observation
without raising — mirroring day 2's Phase 3 "done when."

## Phase 3 — Graph wiring

- [ ] `build_graph()` (`src/graph.py`): wire `check_limits -> planner ->
      executor -> check_limits`, with the two limit-hit exits and the
      planner's `terminate` exit, matching day 2's state-machine diagram
- [ ] `RetryPolicy` attached to the executor node only (initial_interval
      0.5, backoff_factor 2.0, max_attempts 3, jitter on, retry_on
      `ToolError`) — day 2's backoff curve, expressed in the framework's
      own retry config instead of hand code

**Done when:** the graph runs start-to-finish on a scripted fake planner
(one that always terminates immediately) without manual intervention —
same "done when" as day 2 Phase 5.

## Phase 4 — Tests

- [ ] Port day 2's four `test_loop.py` scenarios (planner terminates
      immediately, golden path, forced failure, can't-run-forever x3) onto
      the graph, using a fast `RetryPolicy` for the forced-failure test so
      it doesn't eat the real backoff delay

**Done when:** `python3 -m unittest discover -s tests` passes, all green,
no live API calls.

## Phase 5 — Behavior-equivalence demo

- [ ] Run CLM-1001 and CLM-1042 through `src/run.py` against the live
      model, save under `runs/`
- [ ] Diff each run's tool-call sequence and final decision against day
      2's saved runs (`../week1_day2/runs/`)
- [ ] Record what matched, what didn't, and *why* it didn't (model
      sampling variance vs. an actual orchestration difference) —
      see `artifacts/behavior_equivalence.md`

**Done when:** both claims land on the same decision as day 2's original
runs, and any tool-call-order differences are attributable to the
planner's `temperature=1` sampling, not to the graph's wiring.

## Phase 6 — Deliverables

- [ ] `tradeoffs.md` — day2-component -> LangGraph-equivalent mapping,
      what LangGraph does that day 2 didn't, what it does that wouldn't be
      chosen by default, what's no longer inspectable, framework-removal
      cost
- [ ] `artifacts/comparison_matrix.md` — framework comparison table
      (LangGraph, AutoGen, Semantic Kernel, Bedrock Agents, + one
      platform-native product) with a build-vs-platform-native row
- [ ] `artifacts/architecture_diagram.md` — two-column diagram (day 2's
      components left, LangGraph's right), arrows for every mapping, gaps
      marked where nothing lines up
- [ ] `artifacts/high_level_deck.md` — 5-8 slides

**Done when:** all four live under this lab's directory and reference the
actual runs under `runs/`, not hypothetical ones.
