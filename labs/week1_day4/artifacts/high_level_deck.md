# FDE Xlerate - Week 1, Day 4
High-level deck: customer-service agent over a mock CRM (PoC #1, day 1 of 2)

## Slide 1: Title / Framing
- PoC #1: a customer-service agent that answers bank-account questions by
  calling a CRM — the shape of most first client engagements, an agent
  over a system of record the client won't hand over real access to on
  day one.
- New PoC, deliberately separate from days 1–3's insurance
  claims-fraud investigator: retail bank accounts (customers, accounts,
  transactions, cards), a fresh domain, same framework (LangGraph)
  carried forward from day 3.
- The design doc is as much the deliverable as the code — it's what a
  client architect reads before deciding whether this agent earns access
  to the real system.

## Slide 2: The Problem
- Every unnecessary CRM call is a failure of the decision step, not a
  safe default — the agent has to actually decide, per turn, whether a
  question needs account data at all.
- The mock has to be a real, documented HTTP service — not an
  in-process stub — so swapping in the real CRM later is a config
  change, not a rewrite.
- Four failure classes, on demand: `500`, timeout, `404`, malformed body.
  Every one of them has to produce a useful reply, never an exception and
  never invented account data.
- Follow-ups ("and what about the other one?") have to resolve against
  what the conversation already covered, across turns within a session.

## Slide 3: High-Level Flow
```
                         START
                           │
                           ▼
                     ┌───────────┐
                     │ decision  │   one LLM call: needs data? which tool?
                     └───────────┘
                    /             \
      needs a tool, resolved     no tool needed, OR
                  │               account reference unresolved
                  ▼                            │
            ┌───────────┐                      │
            │   tool    │  CRM call, owns       │
            │           │  retry + translation  │
            └───────────┘                      │
                  │                             │
                  └──────────────┬──────────────┘
                                  ▼
                           ┌───────────┐
                           │ response  │   templated for found/failure,
                           └───────────┘   LLM only for "no tool needed"
                                  │
                                  ▼
                                 END
```
- No loop-back edge anywhere in the graph — the only retry in the whole
  system is inside the tool layer's own client, invisible to LangGraph.
- Conversation state persists **across separate graph.invoke() calls**
  via LangGraph's checkpointer, keyed by session id — that's the actual
  mechanism behind multi-turn memory, not something bolted on after.

## Slide 4: Architecture — what's reused vs. new
- **Framework choice repeated from day 3, on purpose**: low-level
  `StateGraph` + hand-written nodes, not a prebuilt ReAct/tool-calling
  agent — keeps `decision.py`'s and `response.py`'s system prompts fully
  visible in this repo, not replaced by a framework-injected one (see day
  3's `tradeoffs.md`, "What you can no longer see").
- **Retry pattern reused from day 2, not day 3**: hand-rolled in
  `tool_client.py` with an injectable `sleep`, same shape as day 2's
  `executor.py` — deliberately *not* LangGraph's `RetryPolicy`, because
  day 3 documented that `RetryPolicy`'s sleep is hardcoded and can't be
  tested at full speed. Keeping retry inside the tool layer sidesteps
  that limitation and matches this lab's own architecture: "the only
  loop-back is the retry inside the tool layer."
- **New this lab**: the mock CRM itself (`mock_crm/`, a standalone
  FastAPI service with two independent fault-injection mechanisms), the
  decision layer's account-reference classification contract, and a
  conversation-state layer built specifically to resolve follow-ups
  deterministically rather than asking an LLM to guess an account ID.

## Slide 5: Tech Stack
- **Mock CRM**: FastAPI + `uvicorn`, fixture data, header-driven fault
  override for exhaustive pytest coverage, fixture-flagged accounts (one
  per fault class, plus a fail-then-recover account) for the natural-
  conversation demo. Full contract in `mock_crm/contract.md`.
- **Tool layer**: `httpx` client, explicit timeouts, hand-rolled retry
  (3 attempts, exponential backoff + jitter), translates HTTP reality
  into a closed outcome set — `found` / `not_found` / `unavailable`.
- **Orchestration**: LangGraph `StateGraph` (`langgraph==1.2.11`, same
  pin as day 3), `InMemorySaver` checkpointer for cross-turn persistence.
- **Model/SDK**: `claude-sonnet-5` via `anthropic==0.104.1`, same pin
  carried from days 2–3.
- **Tests**: `pytest` (this lab's own choice, not day 2/3's `unittest`)
  — 43 tests, mocked LLM calls throughout, real HTTP against a live
  `uvicorn` instance of the mock for the tool/graph layers, whole suite
  under 2 seconds.

## Slide 6: Failure handling — the actual demo
Live run, `runs/fault_injection_demo.json`, all four classes against
their documented fixture IDs:

| Fault | Account | Tool outcome | Reply (excerpt) |
|---|---|---|---|
| `500` | ACC-2004 | `unavailable` | "I'm having trouble reaching our account systems right now... connect you with a specialist" |
| timeout | ACC-2005 | `unavailable` | same generic message — the customer never sees *why* it failed |
| malformed body | ACC-2006 | `unavailable` | same generic message |
| unknown customer | CUST-9999 | `not_found` | "No customer found with id 'CUST-9999'... connect you with a specialist" |
- All four are templated replies, not LLM-generated — the one path this
  lab is actually graded on ("never invent data," "tool-failure handling
  implemented") is deliberately the one with no room for a model to
  improvise on top of a failure.
- The internal failure detail (e.g. the exact HTTP status or exception)
  is logged in the turn record for support/ops, never shown to the
  customer — they don't need to know *how* it broke, only that it did.

## Slide 7: Multi-turn demo + known risks
`runs/multiturn_demo.json`, Maria Chen (CUST-1001, two accounts):
1. "What's the balance on my checking account?" → **ACC-2001**, $4,210.55.
2. "And what about the other one?" → resolves to **ACC-2002**, $15,320.10
   — via conversation state alone, no LLM guess at an account ID.
- Two real findings from running this live, not hypothetical: the
  decision layer occasionally returned an empty response at
  `temperature=1` (thinking budget crowding out the text output —
  `MAX_TOKENS` raised, exposure reduced not eliminated), and LangGraph's
  checkpointer warns on the custom `Turn`/`ToolOutcome` dataclass types
  it's storing (harmless today, pinned version, a real forward-
  compatibility gap). Both in `design_doc.md`'s "Known risks."

## Slide 8: What breaks against a real CRM
- No auth, no pagination, no rate-limit-aware backoff, no eventual
  consistency — the mock is instantly, fully consistent with no
  credentials required, none of which survives contact with a real
  system of record.
- Exactly one CRM call per turn, by design — a question needing two
  calls in one turn ("compare my checking and savings balances") would
  need this architecture to grow toward day 2/3's multi-iteration loop.
- The customer's account list is fetched once at session start and never
  refreshed — a new or closed account mid-session wouldn't be seen until
  the next session.
- Full list, with reasoning for each, in `design_doc.md`'s "Assumptions"
  section — this slide is the summary, that doc is the actual commitment
  a client architect should hold this PoC to.
