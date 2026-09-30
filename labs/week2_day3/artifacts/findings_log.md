# Findings log — Week 2, Day 3 (Harbor MCP server)

Surprises and decisions found while building, in the order they came up.
Each says what was seen, why it matters, and what was done.

## Milestone 1 — core banking

- **The REST API can't reach core banking, even with the service-role key.**
  Seen: `PGRST106: Only the following schemas are exposed: public,
  graphql_public`. Why it matters: Supabase's REST API would otherwise be a
  second door into Harbor's data, around the MCP server. Done: nothing
  needed; `harbor_core` is simply not an exposed schema. Checked, not
  assumed.

## Milestone 2 — mock CRM

- **Freezing a lost card is a `409 conflict`, not a success.** Otherwise
  "freeze" would quietly replace a permanent block with a reversible one.
  Added a sixth outcome (`conflict`) to the spec and manifest.

## Milestone 3 — server skeleton

- **Permission check moved before the argument check** (the spec had it
  the other way). A caller without the grant now learns nothing about a
  tool, not even its parameters.
- **The audit log would have stored a secret.** First live run: a call with
  `db_password: "hunter2"` was correctly refused, and the value would have
  been written to the audit log verbatim. Done: values of undeclared
  arguments are redacted (`[redacted: undeclared argument]`), and a test
  checks the string never appears in the file.
- **The 401 wrapper caught my own readiness check.** A `curl` without a
  token, used to wait for the server to start, produced an
  `unauthenticated` audit line. Correct behaviour; worth knowing when
  reading the log.
- **The SDK needs an explicit `validate_token_resource`.** Static tokens
  have no audience to check, so it's `False` with a comment. It must become
  `True` with OAuth tokens.

## Milestone 4 — tools and manifest

- **A refused call inside a test must be caught inside the client's
  `async with`.** Escaping the block, the SDK wraps the `MCPError` in an
  `ExceptionGroup`, so `pytest.raises(MCPError)` outside it fails even
  though the server refused correctly. Six tests failed for this reason
  alone.
- **Worst-case latency of one CRM call is ~8 s.** M-1004 (the timeout
  fixture): 3 attempts × 2 s timeout + backoff = 8.15 s measured before
  `unavailable`. A 500 costs ~2.1 s (backoff only). Why it matters: the
  agent's tool loop can make several calls per question. To watch in
  milestone 7; the fix, if needed, is a shorter timeout on the server, not
  in the agent.
- **Drift checks work.** Granting `freeze_card` to `member_assistant`
  without updating the manifest fails `test_permissions_match_policy`.
  Disabling the `is_allowed` check fails 3 authorization/audit tests
  (milestone 3).

## Milestone 5 — the agent's MCP gateway

- **The blocking portal works; no fallback needed.** One background event
  loop (`anyio.from_thread.start_blocking_portal`) holds one MCP session;
  the sync agent calls plain methods. Live: connect + discovery in ~95 ms,
  then each call reuses the session (a DB read ~100 ms end to end including
  the first call's warm-up; a refusal ~5 ms). The plan's fallback (one
  connection per call) wasn't needed.
- **A "thread leak" that wasn't.** A test counting threads after `close()`
  found one extra. It was the *test server's* pooled "AnyIO worker thread"
  (created on the first tool call and reused), not the gateway's. The
  gateway's own `asyncio-portal-*` thread is gone after `close()`, and six
  connect/close cycles leave the count flat. Tests now check the gateway's
  own thread, and that nothing accumulates.
- **Day 2's guard test hard-coded Day 2's $3.50.** Rewritten relative to
  `settings.BUDGET_GUARD_USD`, so it holds for Day 3's $1.75 (or any
  later budget).
- **"No hardcoded tool names" is now a test.** Planting `import httpx`, the
  CRM's address, `CRM_API_KEY` and a tool name in an agent file fails three
  separate `test_no_bypass.py` tests; removing it passes. This is what
  enforces R2 (no agent change for a new tool) and R7 (integration code
  gone, not dormant).
- **The agent runs with only two settings.** Live check with a clean
  environment (`env -i`): `HARBOR_MCP_TOKEN` (+ the default URL) and
  nothing mentioning CRM, DB or server tokens. It connected, discovered all
  six tools, read an account, got `unavailable` for M-1003 and was
  `forbidden` from `freeze_card`: 3 calls, 3 audit lines.

## Milestone 6 — the record path in the graph

- **The gate's tool rule ties routing to discovery.** `gate_v2` may choose
  `use_tool` only if a *listed* tool can provide what's asked. So the
  same question routes differently depending on what the server
  advertises, which is what milestone 8 needs to show R2. Without the rule,
  "what's my ATM limit?" would go to `use_tool` before any limits tool
  existed and dead-end.
- **Day 2's test helper matched prompts exactly.** The gate's prompt now
  ends with a runtime tool list, so 13 copied tests failed with "unknown
  prompt". Fixed by matching on the prompt's beginning.
- **A diagram in a docstring had an invalid escape (`\-`).** Python warns
  (20 warnings in `test_no_bypass`, which parses every agent file). Fixed.
  Warnings are worth reading, not just counting.
- **Hidden tools are stopped twice.** The allow-list hides a tool from the
  model; if the model asks for it anyway (hallucinated from the prompt or
  a result), the agent refuses it locally (`not_offered`) and the server
  never sees it. Neither is enforcement: that stays on the server, which
  milestone 9's bypass shows.
- **Never cached, tested.** Asking the same record question twice with
  the cache on: the gate hits (member-independent), `tool_select` and
  `generate_from_tools` stay `off` both times.

## Milestone 7 — first live traces ($0.049, 6 questions, `runs/adhoc/`)

| # | Member / caller | Question | Route | Tools | Outcome |
|---|---|---|---|---|---|
| 1 | M-1001 / member_assistant | checking balance | use_tool | list_member_accounts | answered, $4,210.55 ✓ |
| 2 | M-1001 / member_assistant | groceries recently | use_tool | list_member_accounts → list_transactions | answered, **total wrong** (below) |
| 3 | M-1001 / member_assistant | freeze my card | use_tool | list_cards → freeze_card **forbidden** | cannot_answer → contact centre ✓ |
| 4 | M-1001 / member_assistant | stop payment fee | retrieve (Day 2 path) | none | answered, $30.00, fee schedule ✓ |
| 5 | M-1003 / member_assistant | are my cards active | use_tool | list_cards **unavailable** (2.0 s) | cannot_answer, no invented status ✓ |
| 6 | M-1001 / contact_centre | freeze my card | use_tool | list_cards → freeze_card ok | answered, card frozen (CRM confirms) ✓ |

Audit log: 8 lines = the agent's 8 `mcp_tool` records, caller and outcome
matching each trace.

- **An arithmetic error passed every check.** Q2's reply: "You've spent
  $144.75 on groceries". The three transactions it lists and cites are
  $63.48 + $38.17 + $42.10 = **$143.75**. The citation guard passed because
  every cited *record* is real; nothing checks a *computed* figure. This is
  the "every answer traceable to the record" constraint failing in a way
  the source line hides: the source is right, the number isn't in it.
  Decision needed (⏸ PAUSE).
- **Bug: the source line credited the wrong call.** Q6 says "has been
  frozen" but its source line named `list_cards` (which saw the card
  *active*), not `freeze_card`. Cause: when two calls return the same
  record, the first was kept. Fixed: the latest call wins (its state is
  the current one). Test added, failed first, passes.
- **Record questions cost 3-4× a document question.** $0.007-0.012 vs
  $0.0034. `tool_select` is 67% of spend: each call re-sends ~2,000 tokens
  (prompt + 6 tool definitions), and the model makes one extra
  `tool_select` call just to say it's finished.
- **Provider prompt caching does nothing here.** `cache_read = 0` on every
  call: ~2,000 tokens is below Haiku 4.5's minimum cacheable prefix, so
  the `cache_control` marker is silently ignored (as Day 2's wrapper
  notes). Not worth padding the prompt to reach it.
- **Latency 6-8.5 s, almost all LLM.** Tools add 20-60 ms (2 s for the
  CRM-500 case). Four sequential Haiku calls is the cost of the tool loop.
- **The gate names tools in its reasons** ("which the get_account tool can
  retrieve"), then `tool_select` chose `list_member_accounts` instead: one
  call instead of two. The gate's reason is a routing reason, not a plan.
- **The gate cache hit across callers** (Q6's gate reused Q3's decision).
  Correct: the gate's decision depends on the question and the tool list,
  not on who is calling, and both callers see the same tool list.

### Milestone 7, after the pause: figure check + prompt v2 (decision: "code check + prompt")

- **Built:** `agent/figures.py`. Every `$` figure in a record answer must
  equal a money value in a cited record, or the exact total (all / out /
  in) of the cited transactions; otherwise the answer is blocked.
  `generate_from_tools_v2` asks the model not to total unless asked. The
  live failure is replayed as a test (`$144.75` → blocked; `$143.75` →
  passes).
- **Live re-check ($0.025):** "What did I spend on groceries recently?" →
  now lists the three purchases, no total; figures `63.48, 38.17, 42.10`
  all verified.
- **New gap: the agent didn't know today's date.** "How much did I spend in
  total last week?" → an honest `cannot_answer` ("I don't have today's
  date"). Fixed: code supplies `Today's date` to the tool-selection and
  answer steps (`--today` pins it for reproducible runs; evals pin
  2026-09-28, the seed data's "now"). Test added.
- **Still wrong after the date fix: an omission, not an invention.** Same
  question with `--today 2026-09-28`: the model framed the week correctly
  (21-27 Sep) but reported only $63.48 (26 Sep) and said it was "your only
  grocery transaction that week", missing $38.17 (23 Sep), which was in
  the same list. Correct answer: $101.65. The figure check passed, because
  $63.48 is real. **The figure check stops invented numbers; it cannot
  stop omitted records.**
- **What this means:** filtering and adding up a list is an aggregate
  question, and Harbor's constraint already says where those go: "the
  governed SQL view, never raw tables" (and not the LLM). That is Day 4's
  slice. Today: recorded as a known gap, and the eval keeps a "last week"
  question and reports it honestly rather than tuning the prompt until it
  passes once.

## Milestone 8 — discovery demo ($0.05; `artifacts/discovery_trace.md`)

- **The gate saw a truncated tool list (bug, milestone 6 code).** It got
  only the first *line* of each description, and `list_cards`'s wraps
  mid-sentence before "Does not return spending limits". So the gate chose
  `use_tool` for limit questions no tool could answer (a safe dead end, but
  the wrong route). Fixed: the full description, whitespace collapsed
  (~+450 input tokens per gate call, ~$0.0005). Found only because the
  demo compared a before and an after: the rule "use a tool only if one
  can provide it" needs the tools' *negative* statements too.
- **Baseline taken after the fix.** Agent fingerprint `7fd25b2d8f81ede0`,
  identical before and after the server change.
- **Deny by default, shown on a real tool.** `get_card_limits` advertised
  at 0.2.0 but not yet granted → `forbidden` (-32003), audited, CRM never
  touched. One line in `permissions.py` granted it.
- **It worked:** same agent, new tool list hash (`f5e8…` → `7fd2…`),
  both limit questions answered from the card's own record ($800.00 /
  $5000.00) with `get_card_limits` in the source line.
- **Tests had hard-coded "0.1.0" and the six-tool list in four places.**
  Moved to one `EXPECTED_TOOLS` list in `tests/mcp_harness.py` and the
  server's `SERVER_VERSION`, so a version bump only fails tests that are
  actually about the change.

## Milestone 9 — authorization evidence ($0.008; `artifacts/authorization_test.md`)

- **The bypass was refused by the server.** `scripts/bypass_allowlist.py`
  (its own MCP client, no agent import) with the member token →
  `freeze_card` → `-32003 forbidden`, audited, CRM untouched. The same call
  with the contact-centre token → ok. The agent *with* an allow-list never
  showed the model `freeze_card`; the agent *without* one (milestone 7)
  was refused by the server. The allow-list changed what the model saw,
  nothing about what the token could do.
- **A bad token writes two audit lines.** The SDK client in `mode="auto"`
  tries the newer handshake and then the older one: two `POST /mcp`, both
  401, 1 ms apart. Correct (each HTTP request is audited), but worth
  knowing when counting 401s in the log. The token itself: 0 occurrences.

## Milestone 10 — eval and gate re-check ($0.61; `artifacts/eval_results.md`)

- **Tool set: 14/14 excluding the known gap; every safety check 15/15.**
  Pilot (3 questions, $0.0084 each) before the full run.
- **t08 (last-week total) is intermittent: 1 correct in 3 attempts.**
  Same prompts every time. The known gap is real and not fixed by the
  prompt; Day 4.
- **Figure-check hole (fixed).** t09's `cannot_answer` explanation
  mentioned "$512.00": true, but unchecked, because the figure check only
  covered `answered`. Now any figure in a cannot-answer reply must come
  from a record some tool returned. Test failed first, passes.
- **Gate regression q012 (fixed with gate_v3).** Under gate_v2 a
  loan-grace-period question went to `answer_direct` 2 times in 4. gate_v2's
  fallback offered "otherwise answer directly" when no tool fit; gate_v3
  says retrieve. 5/5, then 70/70 in the full re-check.
- **Label conflict q039 (relabelled, documented).** Day 2 expected
  `retrieve` for "the ATM limit on my debit card"; tool eval t14 expects
  `use_tool` for the same question. With a limits tool advertised,
  `use_tool` is right for a signed-in member. `eval/gate_relabels.yaml`
  records why, applies only while the tool is advertised, and the raw
  score (69/70) is always reported beside the relabelled one (70/70).
- **Cost: $0.0102 per record question, 67% of it `tool_select`.** 23 MCP
  tool calls cost $0.
