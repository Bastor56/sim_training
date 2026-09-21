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
  question needs account data at all, including a repeat question about
  something it already retrieved and stated this same conversation
  ("what did you say the balance was?") — recalling that counts as
  deciding not to call a tool, the same as recognizing a greeting does.
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
                     │ decision  │   one LLM call: needs data? which
                     └───────────┘   tool? already known from this
                    /             \  session?
      needs a tool, resolved,     no tool call needed --
      not already known           no data needed, OR
                  │               already known (recalled), OR
                  ▼               account reference unresolved
            ┌───────────┐                      │
            │   tool    │  CRM call, owns       │
            │           │  retry + translation  │
            └───────────┘                      │
                  │                             │
                  └──────────────┬──────────────┘
                                  ▼
                           ┌───────────┐
                           │ response  │   templated for found/recalled/
                           └───────────┘   failure, LLM only for
                                  │        "no data needed"
                                  ▼
                                 END
```
- No loop-back edge anywhere in the graph — the only retry in the whole
  system is inside the tool layer's own client, invisible to LangGraph.
- Recall resolution ("did we already learn this?") happens entirely
  inside the decision layer's own function call, before the graph's
  routing logic ever runs — a cache hit and "no data needed" both just
  come back as `needs_tool=False`, so the graph itself doesn't grow a new
  branch or node just because the decision got smarter about when a CRM
  call is actually necessary.
- Conversation state persists **across separate graph.invoke() calls**
  via LangGraph's checkpointer, keyed by session id — that's the actual
  mechanism behind multi-turn memory, not something bolted on after.

## Slide 4: Architecture — four layers, one boundary
- **Decision** (`decision.py`): one LLM call per turn, three-shape
  contract — `answer_directly`, `call_tool`, `recall_from_history`.
  Classifies *how* an account was referenced (`explicit` /
  `last_mentioned` / `the_other_one` / `none`) rather than naming an ID
  itself; a resolver turns that into one. `recall_from_history` names the
  same tool + reference a fresh lookup would, matched against turn
  history — a miss falls back to a real call rather than guessing.
- **Conversation state** (`conversation_state.py`): pure, LLM-free turn
  history plus two resolvers — `resolve_other_account()` and
  `resolve_recall()` — both return `None` on ambiguity rather than guess.
- **Tool layer** (`tool_client.py`): the hard boundary. Owns HTTP,
  timeouts, and retry; collapses every failure into `found` / `not_found`
  / `unavailable` — the only thing anything above it ever sees. Swapping
  in a real CRM later is a config change, not a rewrite.
- **Response** (`response.py`): templated for found/recalled/failure,
  LLM only for "no data needed" — zero room to improvise on the graded path.
- **Graph** (`graph.py`): thin — `decision → tool → response`, no
  loop-back; the only retry lives inside the tool client.
- **Mock CRM** (`mock_crm/`): standalone FastAPI service, two independent
  fault-injection paths — a header override (tests) and fixture-flagged
  accounts (the live demo).

## Slide 5: Tech Stack
- **Mock CRM**: FastAPI + `uvicorn`, fixture data, header-driven fault
  override plus fixture-flagged demo accounts. Contract in
  `mock_crm/contract.md`.
- **Tool layer**: `httpx`, explicit timeouts, hand-rolled retry (3x,
  exponential backoff + jitter).
- **Orchestration**: LangGraph `StateGraph` (`langgraph==1.2.11`, same
  pin as day 3), `InMemorySaver` checkpointer.
- **Model/SDK**: `claude-sonnet-5` via `anthropic==0.104.1`, same pin
  carried from days 2–3.
- **Tests**: `pytest` — 43 tests, LLM mocked throughout, real HTTP
  against a live `uvicorn` mock for the tool/graph layers, under 2s.

## Slide 6: Failure handling — the actual demo
Live run, `runs/fault_injection_demo.json`, all four classes against
their fixture IDs:

| Fault | Account | Tool outcome | Reply (excerpt) |
|---|---|---|---|
| `500` | ACC-2004 | `unavailable` | "having trouble reaching our account systems... connect you with a specialist" |
| timeout | ACC-2005 | `unavailable` | same generic message |
| malformed body | ACC-2006 | `unavailable` | same generic message |
| unknown customer | CUST-9999 | `not_found` | "No customer found with id 'CUST-9999'... specialist" |
- All four are templated, not LLM-generated — zero room to improvise on
  the one path this lab is actually graded on.
- Internal failure detail is logged for support/ops, never shown to the
  customer.

## Slide 7: Multi-turn demo + known risks
`runs/multiturn_demo.json`, Maria Chen (CUST-1001, two accounts):
1. "Balance on my checking?" → **ACC-2001**, $4,210.55.
2. "And the other one?" → **ACC-2002**, $15,320.10 — resolved via
   conversation state, no LLM guess at an account ID.
- Two real findings from running this live: the decision layer
  occasionally returns an empty response at `temperature=1`
  (`MAX_TOKENS` raised, not eliminated), and the checkpointer warns on
  the custom `Turn`/`ToolOutcome` dataclasses it stores (harmless today,
  a forward-compat gap). Both in `design_doc.md`'s "Known risks."

## Slide 8: What breaks against a real CRM
- No auth, pagination, rate-limit-aware backoff, or eventual consistency
  — none of which survives contact with a real system of record.
- Exactly one CRM call per turn — a two-call question would need this
  architecture to grow toward a multi-iteration loop.
- Account list fetched once at session start, never refreshed; a
  recalled fact carries the same staleness assumption.
- Full reasoning in `design_doc.md`'s "Assumptions" section — this slide
  is the summary, that doc is the actual commitment.
