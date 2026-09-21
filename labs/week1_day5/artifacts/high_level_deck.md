# FDE Xlerate - Week 1, Day 5
High-level deck: PoC #1 finished, tested, demoed — Week 1 Checkpoint

## Slide 1: Title / Framing
- Day 5 is not a new build — it's the day a PoC stops being "works when I
  type the right thing" and becomes something you could put in front of a
  client: tested tool-calling logic, a peer review acted on, a demo that
  survives a question you didn't rehearse.
- The checkpoint is the client meeting. Being unable to say why this is an
  agent rather than a scripted workflow, or defend a design choice, is
  what actually loses the room — not a missing feature.
- Same build as day 4 (customer-service agent over a mock bank CRM),
  carried forward unchanged. Today's deliverables are proof, not product.

## Slide 2: The Problem
- Finishing is a skill most PoCs die without. Four concrete bars to clear:
  1. Unit tests over the tool-calling logic specifically — call/no-call,
     argument construction, every failure class — LLM stubbed, deterministic.
  2. A demo that runs end-to-end from a clean checkout, no fixture
     fiddling between steps, including one deliberate failure shown on
     purpose rather than steered around.
  3. A peer review with a finding actually acted on before submission.
  4. Every path the demo doesn't cover, named as a known gap — an
     unclaimed gap a reviewer finds costs more than one named up front.
- Underneath all four: the checkpoint itself — explain, out loud, without
  notes, why this is an agent and not a workflow, what breaks at 100x
  traffic, and what you'd build next.

## Slide 3: High-Level Flow (unchanged from day 4)
```
                         START
                           │
                           ▼
                     ┌───────────┐
                     │ decision  │ ★ one LLM call: needs data? which
                     └───────────┘   tool? already known from this
                    /             \  session?
      needs a tool, resolved,     no tool call needed --
      not already known           no data needed, OR
                  │               already known (recalled), OR
                  ▼               account reference unresolved
            ┌───────────┐                      │
            │   tool    │◄─┄┄ tool boundary:    │
            │           │    HTTP → found /     │
            └───────────┘    not_found /        │
                  │           unavailable        │
                  └──────────────┬──────────────┘
                                  ▼
                           ┌───────────┐
                           │ response  │   templated for found/recalled/
                           └───────────┘   failure, LLM only for
                                  │        "no data needed"
                                  ▼
                                 END
```
- ★ marks the single place the model — not the code — makes a decision.
  That mark is the literal answer to "what makes this an agent?": nothing
  upstream of `decide()` could tell "what's my balance?" apart from
  "thanks so much!" ahead of time — including telling a genuinely new
  question apart from a repeat of one already answered this session.
- The tool boundary is marked too: everything above it reasons only in
  `found` / `not_found` / `unavailable`, never a status code — the answer
  to "what changes when this points at the real CRM?" before it's asked.
  Recall resolution happens entirely inside `decide()`, before the
  graph's own routing runs, so the graph shape itself never had to grow
  a branch for it.

## Slide 4: Architecture — what's new this week
Same three-node graph as day 4 (framework/retry reasoning in day 4's
deck, slide 4 — not re-litigated here). New this week, closing a real
gap, not padding scope:
- **`tests/test_response.py`** — `compose_reply` had zero direct unit
  tests before; only 2 of its ~7 branches were reachable through the
  existing graph-integration tests. Now: the `not_found` branch, all five
  `_compose_found` tool-formatters, the `recalled_outcome` branch, and
  the LLM-stubbed `_compose_direct_reply` path are each tested directly.
  76 tests total, still under 3 seconds.
- **A rehearsed demo script** (`demo_script.md`) — `run.py` and the mock
  CRM turned into a runbook: exact commands, narration tied to specific
  code, and a troubleshooting section (a live port-8000 conflict while
  rehearsing, now a documented pre-flight check).
- **`known_gaps.md`** — what the live demo won't show and why, written
  down before a reviewer can find it first.

## Slide 5: Tech Stack
- **Orchestration, tool layer, mock CRM**: unchanged from day 4 — full
  stack detail in day 4's deck, slide 5.
- **Testing, this week's actual focus**: `pytest`, LLM fully stubbed via
  dependency-injected `client` parameters (`FakeMessagesClient`, same
  pattern across `decision.py` and `response.py`) — no network calls,
  deterministic, fast enough to run live in review. Tool-layer tests run
  against a real `uvicorn` instance, not an in-process stub — the lab's
  own "real HTTP service" requirement, one layer down.

## Slide 6: Failure handling — shown live vs. proven elsewhere
| Fault class | Shown live? | Where it's proven |
|---|---|---|
| `500` (`ACC-2004`) | **Yes** — the deliberate failure | `demo_script.md` Scenario 2 + `tests/test_tool_client.py` |
| timeout (`ACC-2005`) | No | `tests/test_tool_client.py`, `runs/fault_injection_demo.json` (day 4) |
| malformed body (`ACC-2006`) | No | same as above |
| unknown customer, `404` (`CUST-9999`) | No | `tests/test_tool_client.py` + `tests/test_response.py` |
- 500 picked for the live slot: fastest to demo (~6s), and
  `response.py` collapses all three `unavailable` causes into identical
  wording — showing one demonstrates all three.
- Every reply is templated, not LLM-generated — zero room to improvise
  on the one path this PoC is actually graded on.

## Slide 7: Known gaps (full list in `known_gaps.md`)
- **Demo scope, not defects**: 3 of 4 failure classes, 4 of 5 tools, and
  the ambiguous-account clarifying path are tested but not walked
  through live.
- **System limitations carried from day 4**: no auth, pagination,
  rate-limit awareness, or eventual consistency on the mock; exactly one
  CRM call per turn; account list fetched once per session.
- **Peer review**: no peer was available this cycle — a review request
  was drafted (`peer_review_request.md`, pointed at `decision.py`'s
  account-resolution logic and `tool_client.py`'s retry policy), ready
  to send rather than silently skipped.

## Slide 8: The checkpoint answers
- **"What makes this an agent?"** One place the model decides something
  the code couldn't have decided in advance — `decide()`. Everything
  downstream is deliberately deterministic, because the one thing that
  must never be improvised is a customer's account balance.
- **"What breaks at 100x traffic?"** The in-memory checkpointer first —
  can't be sharded, can't run behind a load balancer as-is. Second:
  three synchronous retries per CRM call, at 100x volume, amplify load
  onto an already-struggling CRM — needs a circuit breaker, not more
  retries.
- **"What would you build next, one more week?"** In order: a durable
  shared checkpointer, a circuit breaker around the CRM client, real
  authentication on the CRM boundary, and mid-session account-list
  refresh — all already named in `design_doc.md` and `known_gaps.md`,
  not discovered live. Full reasoning in `checkpoint_prep.md`.
