# Known Gaps — PoC #1, Week 1 Checkpoint

There are two kinds of gaps: what the live demo won't show and what the
system doesn't yet handle.


## 1. What the live demo does not cover

The rehearsed demo runs one multi-turn happy path (balance lookup, then
"and what about the other one?") and one deliberate failure. Everything
below is real and tested, but not re-performed in front of the room:

- **Only one failure class is shown live (the `500`/server-error case,
  `ACC-2004`).** The other three from day 4 — timeout, malformed body, and
  `404` unknown-customer — are proven two other ways: exhaustively in
  `tests/test_tool_client.py` (one test per class, against the real mock
  over real HTTP), and as a recorded run in `runs/fault_injection_demo.json`.
  They aren't repeated live because past the first one, a second and third
  "I'm having trouble reaching our systems" reply demonstrates nothing new
  — the response layer collapses all three causes into the same customer
  wording by design (see `response.py::_compose_unavailable`), so showing
  one is showing the behavior.
- **Only `get_account` is exercised live.** The other four tools —
  `get_customer`, `list_customer_accounts`, `list_account_transactions`,
  `list_account_cards` — are covered at the unit level
  (`tests/test_response.py`, added this week) but not walked through live.
- **The ambiguous-reference clarifying question is not shown live.** When a
  customer with 2+ accounts asks "what's my balance?" without naming one,
  the agent asks a clarifying question rather than guessing
  (`tests/test_graph.py::test_unresolved_account_reference_skips_tool_and_asks_for_clarification`).
  Real behavior, not demoed on stage.
- **No two-account comparison.** "How much more is in my savings than my
  checking?" is out of architectural scope this phase (exactly one CRM call
  per turn) and isn't in the demo because there's no path that would make it
  look like it works.


## 2. Known system limitations (carried from `design_doc.md`)

From validation (Section 5 there):

- **The decision step occasionally returns an unusable model response** —
  under the sampling settings chosen for reasoning variation, the model can
  spend its output budget on internal reasoning and leave nothing for the
  actual JSON answer. Output budget was raised, which reduces but doesn't
  eliminate this. When it recurs, it's treated as a genuine logged failure,
  not silently retried — so it degrades honestly rather than masking itself.
- **The checkpointer logs a compatibility warning** for the custom
  dataclass types (`Turn`, `ToolOutcome`) this agent stores in session
  state. Not a functional problem on the pinned LangGraph version today; a
  forward-compatibility gap to close before hardening further.

From scope boundaries (Section 6 there) — all deliberate for this phase, not
oversights:

- No authentication on the simulator (production needs a real token +
  refresh path).
- No pagination (transactions return everything up to a flat limit).
- No rate-limit awareness (every server error retries on the same fixed
  curve; a real CRM would likely dictate its own wait time).
- No eventual consistency (the simulator is always immediately consistent).
- Assumed reliability differences between operations were a simplification,
  not confirmed against a real system.
- A customer's account list is fetched once per session and not refreshed.
- A recalled fact is only as fresh as when it was first retrieved this
  session — same staleness assumption as the account list, extended to
  individual facts recalled later in the same conversation.
- Exactly one CRM call per turn.
- Customer identity is provided to the session, not authenticated by it.

## 3. Peer review

No peer was available to review against for this submission.