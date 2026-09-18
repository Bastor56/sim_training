# FDE Xlerate - Week 1, Day 3
Tradeoffs: hand-rolled agent loop (day 2) vs. LangGraph port (day 3)

## Component mapping

| Day 2 (hand-rolled) | LangGraph equivalent | Notes |
|---|---|---|
| `loop.py`'s `while True` + termination checks | `check_limits_node` (no-op) + `route_after_limits` conditional edge, wired both from `START` and from the executor node | Direct equivalent. The check still runs before every planner call, first iteration included — that guarantee didn't need the framework, it just needed the same hub reachable from two places. |
| `loop.py`'s `action = planner(state)` | `planner_node` | Calls day 2's `plan_next_action` unchanged. See "What had to change" below — this one needed an adapter, not a straight swap. |
| `executor.py`'s dispatch + hand-rolled retry loop | `executor_node` + `RetryPolicy` attached to it | The retry *mechanics* (exponential backoff, jitter, cap) moved entirely into the framework's config object. The *policy decision* — "an exhausted retry becomes an observation, not a crash" — still had to be written by hand, because that's domain logic the framework has no way to infer. |
| `state.py`'s `AgentState` (a mutated-in-place dataclass) | `graph_state.py`'s `GraphState` (a dataclass with per-field reducers) | Same fields, structurally. The difference is ownership: day 2's state was a plain Python object your code read and wrote directly. LangGraph's version is a *channel* — your node returns a partial update, the framework decides how to merge it (overwrite by default, `operator.add` for lists here), and persists the result between node calls. You no longer control when or how the merge happens. Persistence is a separate axis from ownership, and it's where day 2 had nothing at all: `AgentState.to_dict()` was a manual, one-off JSON dump you had to remember to call. LangGraph ships checkpointers (in-memory, SQLite, Postgres) that persist every step automatically and support replay/time-travel — this port uses the in-memory default and never turns the durable ones on, but the capability is one constructor argument away, not a feature you'd have to build. |
| `registry.py`'s tool registry (name -> callable + schema + description) | **No first-class equivalent at the layer this port uses.** Reused unchanged; `executor_node` calls `REGISTRY[tool_name]["fn"](**args)` exactly like day 2's executor did. | LangGraph does have tool-integration abstractions — `bind_tools`, the `@tool` decorator, `ToolNode` — but they exist to let a model's native function-calling drive tool selection. Day 2's planner doesn't use native function-calling; it's constrained to a hand-written two-shape JSON contract (`call_tool` / `terminate`) that already encodes "which tool, what args." Adopting LangGraph's tool abstractions would mean also replacing that contract with the model's own function-calling format — a bigger behavioral change than "port the orchestration," so this port left the registry exactly as day 2 built it and never touched LangGraph's tool layer at all. That's worth saying plainly to a client: "we used framework X" doesn't mean every part of X's surface area got used. |
| `errors.py`'s `ToolError` vs. everything-else distinction | Unchanged, reused as-is; also becomes the `retry_on` predicate on `RetryPolicy` | The one piece of day 2 logic the framework has a first-class slot for. `retry_on` *is* "which exceptions are recoverable" — the same judgment call day 2 made by hand in `except ToolError`. |
| Day 2's injectable `sleep` parameter on `execute_tool` (for fast tests) | **No equivalent.** | `RetryPolicy`'s sleep is `time.sleep`, hardcoded inside `langgraph/pregel/_retry.py`. Tests can only make retries fast by shrinking the policy's own `initial_interval`/`backoff_factor` — which means the test is no longer exercising the same timing curve as production, just some faster curve. Day 2 could test the *exact* production backoff without waiting for it; day 3 can't. |
| Day 2's "one dataclass, no module-level globals, dump mid-flight" requirement | Naturally satisfied — LangGraph's state schema *is* that dataclass, and `graph.invoke()` returns the final channel values as a plain dict, trivially JSON-serializable (after `asdict()`-ing the `Observation` list) | This requirement got easier, not harder — it's close to what a StateGraph schema is for by default. |

## What had to change to reuse day 2's code, and why

Two adapters were unavoidable, both in `src/graph_nodes.py`:

1. **The planner's in-place mutation.** `plan_next_action` does
   `state.tokens_used += response.usage.input_tokens + ...` as a side
   effect on the object you pass it. That's fine in a hand-rolled loop
   where `state` is a real, shared, mutable object. It's not fine as a
   LangGraph node body, because only a node's *return value* is committed
   — mutating the `GraphState` instance a node receives has no effect on
   the graph's persisted state. `planner_node` works around this by
   handing `plan_next_action` a small `SimpleNamespace` shim instead of
   the real state, letting the mutation happen on the shim, then reading
   the mutated value back out and returning it explicitly. This is exactly
   the kind of one-way door a framework port exposes: day 2's code was
   never explicitly designed to be "pure," and it didn't need to be, until
   something else started deciding when state gets persisted.

2. **Retry exhaustion.** `RetryPolicy` retries by re-invoking the whole
   node function and, once `max_attempts` is hit, **re-raises the last
   exception past the graph boundary** — it does not hand the node a
   graceful "this was your last try" callback. LangGraph does expose the
   current attempt number to node code (`get_runtime().execution_info.
   node_attempt`, 1-indexed, added specifically for this), so
   `executor_node` checks that against the same `MAX_ATTEMPTS` constant
   the policy was built with, and converts the failure into an error
   `Observation` on the final attempt instead of letting it propagate.
   Without that check, the whole graph run — not just the one tool call —
   would crash on a flaky tool, which is precisely the failure mode day
   2's requirements were written to prevent.

## What LangGraph does that the hand-rolled version didn't

- **`RetryPolicy` is declarative and inspectable as config**, not as code
  you have to read line-by-line to find the backoff formula. Attaching it
  to `executor.py`'s equivalent node is one dataclass, not a 15-line
  hand-written loop with its own jitter math.
- **The graph is a static object you can introspect and (with `langgraph`'s
  visualization extras) draw** before ever running it — day 2's control
  flow only existed as whatever the `while True` body happened to do at
  runtime; there was no artifact to inspect except the source.
- **Conditional-edge routing separates "what decided to move on" from
  "what happens next"** more forcibly than an `if` chain does — the routing
  function (`route_after_limits`, `route_after_planner`) is a pure
  function from state to a label, which is a slightly stricter shape than
  day 2's loop body was ever forced into.

## What it does that wouldn't have been chosen by default

- **`RetryPolicy` retries the entire node function, not just the risky
  call inside it.** In `executor_node` that's harmless — everything before
  `fn(**args)` is a cheap dict lookup. In a node with any side effect
  before the risky call (a partial write, a log line meant to fire once),
  the framework would silently re-run that side effect on every retry
  attempt. Day 2's hand-rolled retry loop wrapped *only* the tool call for
  exactly this reason; LangGraph's unit of retry is coarser than that by
  default, and getting day-2-equivalent granularity took the
  `node_attempt` workaround above rather than being the default behavior.
- **Two competing ways to model this agent exist inside the same library**,
  and this port deliberately used the low-level one (`StateGraph` +
  hand-written nodes) instead of LangGraph's higher-level prebuilt agent
  constructors (e.g. a ReAct-style agent that owns its own system prompt
  and tool-calling loop). The prebuilt route would have been less code but
  would have handed prompt construction to the framework — which is
  exactly the inversion of control the next section is about. Choosing the
  low-level route was the only way to keep the requirement "same tools,
  same prompt, same model settings as day 2" honest.

## What you can no longer see

Because this port used LangGraph's low-level graph primitives rather than
a prebuilt agent, the actual thing sent to the model is **unchanged and
fully visible** — `planner.py`'s system prompt is reused verbatim, and
nothing in `graph_nodes.py` or `graph.py` touches it. That's a real finding
worth stating plainly: *the framework doesn't have to cost you prompt
visibility if you stay at the graph-primitives layer.* It would cost you
that visibility immediately if the port had instead used a prebuilt
tool-calling agent, which injects its own system prompt and tool-call
formatting you'd have to go looking for.

What *did* become harder to inspect:

- **Retry timing.** Day 2 printed each backoff delay to stderr
  (`[retry] ... backing off 0.61s`) from code you wrote. LangGraph's retry
  loop logs via its own `logger.info(...)` inside `_retry.py` — present,
  but now a framework internal you'd read about in that file rather than
  a line in your own `executor.py`.
- **The exact moment state changes.** Day 2's loop body executes top to
  bottom; you can put a breakpoint anywhere and read the state as of that
  line. LangGraph's execution model (Pregel-style super-steps: every node
  scheduled in a step runs against the *same* input snapshot, and their
  return values are merged only at the step boundary) means "what does the
  state look like right now" depends on which side of a step boundary
  you're asking from — a genuinely different debugging model, not just a
  relocated print statement.

## Human-in-the-loop support

Day 2 has no HITL mechanism at all — a human adjuster only ever sees a
claim *after* the loop has already reached `approve`/`deny`/`escalate`.
There's no way to pause mid-investigation and ask a person something
before the agent commits to a decision, short of not calling `run_agent`
in the first place.

LangGraph has a first-class primitive for exactly this — `interrupt()` —
which pauses the graph at a node, surfaces whatever payload you give it to
a human, and resumes from that exact point (via the checkpointer) once
they respond. This port doesn't use it, because day 2 never required it
and adding it would be a behavior *change*, not a behavior-equivalent
port. But it's the clearest concrete capability gap between the two
versions: adding "pause before `deny`/`escalate` and require adjuster
sign-off" to the LangGraph version is a node insertion; the same feature
in day 2's hand-rolled loop would mean threading a pause/resume state
through the `while True` loop and figuring out how to serialize "we're
mid-iteration, waiting on a human" — day 2's state dataclass was designed
for dump-and-inspect, not suspend-and-resume.

## Observability hooks

Day 2's only observability was `print(..., file=sys.stderr)` calls you
wrote yourself — the retry backoff messages in `executor.py`, and the
final JSON dump in `run.py`. Everything you could see was something you'd
explicitly decided to log.

Day 3 trades a specific piece of that away and gains a broader surface in
exchange. What's lost: the retry backoff message is now
`logger.info(...)` inside LangGraph's own `_retry.py` — still real, still
findable, but a framework internal rather than a line in your `executor.py`
(see "What you can no longer see" below). What's gained: the graph is a
structured object LangGraph can trace natively — every node call, every
edge taken, every retry attempt — through LangSmith, without writing any
tracing code yourself. This port doesn't wire LangSmith up (no API key
configured for it, and day 2 has no equivalent to compare against even if
it did), so the honest claim here is "the capability exists and is bigger
than day 2's," not "this port demonstrated it." A client already paying
for LangSmith would get meaningfully more visibility than day 2 ever
offered; a client with nothing configured gets *less* per-line visibility
into the one thing day 2 did log by hand.

## Removing the framework later

Low cost, by construction: every node function is a plain Python function
taking a dataclass and returning a dict; none of them import anything
LangGraph-specific except `get_runtime` (one call, isolated to
`executor_node`) and `RetryPolicy` (one config object, isolated to
`graph.py`). Deleting `graph.py` and writing a `while True` loop that calls
the same node functions in the same order — which is close to reconstructing
day 2's `loop.py` — would remove the dependency without touching
`planner.py`, `tools.py`, `registry.py`, `mock_data.py`, or `errors.py` at
all. The state schema (`GraphState`) would need its reducer annotations
stripped back to plain fields, and the retry loop would need to be
hand-written again. That's the actual size of the framework's footprint
here: two files own 100% of the LangGraph-specific surface.

## Framework comparison

See `artifacts/comparison_matrix.md` for the full matrix (LangGraph,
AutoGen, Semantic Kernel, Bedrock Agents, and one platform-native product)
and the build-vs-platform-native decision for a named client scenario.
