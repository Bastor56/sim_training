# FDE Xlerate - Week 2, Day 3
Build plan: MCP server in front of the CRM and core banking, the Day 2 agent as its client (Harbor Credit Union)

See `spec.md` for the design (tiers, tools, permissions, audit record,
graph changes, eval). This is the build order. Each milestone should be
working and verified before you start the next.

**Why this order:**
- **Backends first, then the server, then the agent.** Each tier is
  tested against the real tier below it before anything sits on top.
- **The server's security is built before its tools are finished.** The
  middleware (permission check + audit) goes in with the *first* tool, so
  no tool ever exists without it. Retrofitting it is how a tool ends up
  unchecked.
- **The riskiest unknown is the sync/async bridge** between the
  synchronous LangGraph agent and the async MCP client (milestone 5). It
  is spiked alone, with no LLM involved, before the agent depends on it.
- **Money is spent late.** All tests use fakes. The first real LLM call is
  in milestone 7.

**⏸ PAUSE** marks a point where you should stop, look at the output
yourself, and decide whether to continue.

**💲** marks a step that spends real API money. Run
`uv run python agent/spend.py` after each one. Guard $1.75, day limit
$2.00.

All commands run from `labs/week2_day3/` unless stated.

## Milestone 0 — Environment

- [x] Folders: `backends/`, `mcp_server/audit/`, `agent/`, `prompts/`,
      `scripts/`, `eval/`, `tests/`, `runs/`, `artifacts/`
- [x] `.python-version` (3.12), `pytest.ini`, `.gitignore` (`.venv/`,
      `__pycache__/`, `mcp_server/.env`, `mcp_server/audit/`,
      `runs/*/tmp/`). `runs/spend_ledger.jsonl` **is** committed.
- [x] `requirements.txt`: `-r ../week2_day2/requirements.txt` plus
      `mcp==2.2.0`, `psycopg[binary]==3.3.6`, `fastapi==0.141.1`,
      `uvicorn==0.53.0`, `httpx==0.28.1`. Create the venv and install.
- [x] Start Docker Desktop. From the repo root: `npx supabase start`.

**Verify:**
```bash
uv run python -c "import mcp, psycopg, langgraph, anthropic, chromadb, fastapi; print('ok')"
uv pip show mcp | grep Version        # 2.2.0
```

**Checkpoint:** one venv imports everything; local Supabase is up
(`npx supabase status` shows the DB on :54322).

## Milestone 1 — Core banking in Postgres (no spend)

- [x] Migration `supabase/migrations/<ts>_harbor_core_banking.sql`:
  - schema `harbor_core`; tables `accounts` (account_id, member_id, type,
    balance, status, opened_on) and `transactions` (transaction_id,
    account_id, posted_on, amount, description, category);
  - `create role harbor_mcp login;` with **no password**;
  - `grant usage on schema harbor_core`, `grant select` on the two tables
    only. Nothing on `public` (week 1's `policies` table).
- [x] Harbor rows appended to `supabase/seed.sql`: week 1's accounts and
      transactions, re-keyed to Harbor members (M-1001 … M-1006,
      ACC-2001 … ACC-2007), plus a few more recent transactions so
      "last week" questions have answers.
- [x] `npx supabase db reset` (**local**; never `db push`).
- [x] `mcp_server/.env.example` with placeholders; your real
      `mcp_server/.env` with a generated password
      (`python -c "import secrets; print(secrets.token_urlsafe(24))"`).
- [x] `scripts/set_db_password.py`: connects as the local superuser
      (Supabase's documented local default), runs
      `ALTER ROLE harbor_mcp PASSWORD ...` from `.env`.

**Verify:** `uv run pytest -v tests/test_core_banking_db.py` (7 live
checks, skipped if Postgres is down):
- `harbor_mcp` reads both tables (7 accounts, 17 transactions);
- reading `public.policies` → permission denied;
- UPDATE / INSERT / DELETE → permission denied;
- a wrong password → rejected;
- week 1's `policies` still has its 5 rows after the reset.

Also checked by hand: the Supabase REST API refuses `harbor_core` even
with the service-role key (`PGRST106: Only the following schemas are
exposed: public, graphql_public`).

**If you run `db reset` again:** re-run `scripts/set_db_password.py`
afterwards (harmless if the password survived).

**Checkpoint:** you can explain why the role's password is not in the
migration file.

## Milestone 2 — Mock CRM for Harbor (no spend)

- [x] Copy `../week1_day4/mock_crm/` → `backends/mock_crm/`. Week 1's
      folder is not edited.
- [x] Rename to Harbor members (`M-1001` …). Remove accounts and
      transactions (now in Postgres). Keep members and cards.
- [x] Move the fixture faults onto **card lookups** for M-1003 (500),
      M-1004 (timeout), M-1005 (malformed), M-1006 (fails twice then
      recovers). Keep the `X-Simulate-Fault` header.
- [x] `X-API-Key` check on every endpoint except `/health` (401 with the
      contract's error envelope). Key from the `CRM_API_KEY` env var.
- [x] `POST /cards/{card_id}/freeze` with `{reason}`: sets status to
      `frozen`, idempotent (freezing a frozen card is `200`, no change).
      `/admin/reset` (or restart) restores fixtures for demos.
- [x] Update `contract.md` to match.
- [x] Tests: copy/adapt week 1's CRM tests; add key-missing → 401,
      freeze → frozen, freeze twice → same.

**Verify:** `uv run pytest tests/test_mock_crm.py` (25 tests, in-process),
and live:
```bash
uv run python scripts/run_crm.py     # :8100; passes the CRM only CRM_API_KEY
KEY=$(grep ^CRM_API_KEY= mcp_server/.env | cut -d= -f2)
curl -s localhost:8100/members/M-1001                          # 401
curl -s -H "X-API-Key: $KEY" localhost:8100/members/M-1001     # Maria Chen
curl -s -X POST -H "X-API-Key: $KEY" localhost:8100/admin/reset
```

Added beyond the original list: freezing a **lost** card is a `409
conflict` (CARD-4008), which gives the manifest a sixth failure mode; the
CRM **refuses to start** without a key (fails closed); the key is checked
**before** the fault header.

## Milestone 3 — Server skeleton: auth, permissions, audit, one tool (no spend)

The security layer goes in with the first tool.

- [x] `mcp_server/config.py`: loads `mcp_server/.env` (tokens, CRM key,
      DB settings, ports). Nothing else reads these.
- [x] `auth.py`: `TokenVerifier` mapping token → `AccessToken(client_id=...)`.
- [x] `permissions.py`: `PERMISSIONS = {"member_assistant": {...}, "contact_centre": {...}}`,
      `is_allowed(caller, tool)`, deny by default.
- [x] `audit.py`: append-only JSONL writer (the spec's record shape).
- [x] `middleware.py`, on `tools/call` only:
      `is_allowed` → refuse (`forbidden`) → arguments vs the tool's
      schema, undeclared keys refused and their values redacted in the
      log (`invalid_arguments`) → call next →
      classify outcome → **audit record in `finally`**.
- [x] `server.py`: `MCPServer("harbor-mcp", version="0.1.0", ...)`, one
      tool (`get_member`), Streamable HTTP on :8200, a startup line
      logging version + tool names.
- [x] Try the ASGI wrapper for **401 audit lines** (spec "Audit log"). If
      the SDK makes it awkward, write it down as a known gap and move on.
- [x] `tests/test_authorization.py`, running the server in-process where
      possible (the SDK's in-memory transport) and over HTTP for the
      token tests:
  - `member_assistant` → `get_member`: allowed, audit `allowed/ok`;
  - a caller with no grant for `get_member` → `forbidden`, **and the
    CRM is never called** (assert with a fake backend that counts calls);
  - undeclared argument `db_password` → refused, audited;
  - unknown token → 401.
- [x] `tests/test_audit.py`: N calls → exactly N audit lines, all fields
      present.

**Verify:** `uv run pytest tests/test_authorization.py tests/test_audit.py`
(13 tests, real HTTP on a free port, fake CRM that counts calls).

Mutation check done: with the `is_allowed` line disabled, 3 of those tests
fail; restored, all pass. The tests catch a missing permission check.

The tests run over real HTTP, not the SDK's in-memory transport, because
the bearer token only exists on the HTTP path.

**Checkpoint:** you can point at the one line of code that makes a
refusal happen and explain why a new tool can't skip it.

## Milestone 4 — All six tools and the manifest (no spend)

- [x] `backends.py`:
  - CRM client: httpx with explicit timeout + retry (week 1's policy),
    `X-API-Key`, errors → `not_found` / `unavailable`;
  - Postgres: psycopg as `harbor_mcp`, **parameterised queries only**,
    connection errors → `unavailable`.
- [x] Tools: `list_cards`, `freeze_card`, `list_member_accounts`,
      `get_account`, `list_transactions`, each returning
      `{data, source}` (spec "Every result carries provenance"), with
      routing-grade descriptions (spec example).
- [x] `mcp_server/TOOL_MANIFEST.md`: server version, changelog, callers,
      then one section per tool: name, purpose, parameters (types,
      ranges), required permission, side effects, failure modes,
      example call and result. Plus the known gaps.
- [x] `tests/test_manifest.py`: the tool names and parameter names in
      the manifest equal what the running server advertises; the version
      matches.
- [x] Tests per tool with fake backends: ok, not_found, unavailable. One
      live test against the real CRM + Postgres (marked, skipped if
      they're not running).

**Verify:** `uv run pytest` (88 tests):
- `test_tools.py`: every tool over HTTP with fakes: success + `source`
  block, the three tool failures, schema limits refused before the
  backend, annotations mark the one write;
- `test_backends.py`: the CRM retry policy with scripted HTTP responses
  (retry on 5xx / timeout / malformed, none on 4xx), plus live Postgres
  (exact money strings, newest-first, `not_found`, injection string treated
  as data, database down → `unavailable` without leaking the host);
- `test_manifest.py`: manifest ↔ server agree on tools, parameters,
  required flags, types, permissions, version. Mutation-checked.

Live against the real CRM + Postgres: 13 calls → 13 audit lines, every
outcome as documented (see `artifacts/findings_log.md` for the ~8 s
timeout case).

**⏸ PAUSE:** review the manifest and descriptions before the agent
depends on them.

## Milestone 5 — The MCP gateway in the agent (highest risk, no spend)

- [x] Copy `../week2_day2/src/` → `agent/`, and Day 2's prompts →
      `prompts/`. Fix `settings.py` paths (`LAB_DIR`, `PRICING_PATH`,
      Day 6 bridge). Copy `pricing.json`. Day 2's tests for the copied
      modules come too.
- [x] `agent/mcp_gateway.py`: a persistent session on a background event
      loop (`anyio.from_thread.start_blocking_portal`); sync
      `list_tools()` / `call_tool()`; reads only `HARBOR_MCP_URL` /
      `HARBOR_MCP_TOKEN`; logs server version, tool names and a tool-list
      hash on connect. Converts a tool result to
      `{ok, data, source, error}`.
- [x] Fallback (one connection per call, if the portal hung on close or
      errored across threads): **not needed**, the portal worked
      (findings log, milestone 5).
- [x] `tests/test_no_bypass.py`, extended per spec "No direct
      integration".

**Verify:** `uv run pytest` (168 tests). New in this milestone:
- `test_mcp_gateway.py` (14): discovery, specs ready for Claude, ok /
  error / refused mapped with codes, one session for many calls, survives
  a refusal, clear errors on bad token / no token / server down, the
  gateway's thread is released on close, nothing accumulates;
- `test_no_bypass.py` (9): Day 2's rules plus: only the gateway imports
  `mcp`; no HTTP / DB / server imports in the agent; no backend secret
  names, ports or paths; **no hardcoded tool names in agent code or
  prompts**. Mutation-checked with a planted week-1-style file.

Live with a clean agent environment (`env -i ... HARBOR_MCP_TOKEN=...`):
connect + discovery ~95 ms; 3 calls (ok / unavailable / forbidden) → 3
audit lines.

**Checkpoint:** Day 2's copied test suite passes inside `agent/` (Day 2's
`src/` and tests untouched; only paths, budget and the judge role changed).

## Milestone 6 — Tool path in the graph, with fakes (no spend)

- [x] `llm.py`: accept `tools=` and a `messages=` list; return
      `tool_use` blocks; never cache when `tools` is set (spec "Cache").
      Recorded, priced, budget-checked exactly as before.
- [x] `prompts/gate_v2.md` (third decision + a runtime tool-list
      section), `tool_select_v1.md`, `generate_from_tools_v1.md`.
- [x] `agent_nodes.py`: `tool_loop` (3-round cap in code),
      `generate_from_tools` (cited IDs must come from this question's
      tool results), source line from the `source` blocks; the gate's
      cache scope adds the tool-list hash.
- [x] `agent_graph.py`: the `use_tool` branch.
- [x] `CLIENT_ALLOWED_TOOLS` in settings (default `None`).
- [x] `run_agent.py`: `--member`, `--token-env`.
- [x] `tests/test_tool_path.py` with a fake LLM and a fake gateway:
  - tool loop stops at 3 rounds even if the model keeps asking;
  - a refused tool call becomes a reply that says so, not a crash;
  - a cited record ID that no tool returned → blocked;
  - `CLIENT_ALLOWED_TOOLS` hides tools from the model;
  - the retrieve and answer_direct paths are unchanged (Day 2's graph
    tests still pass).

**Verify:** `uv run pytest` (184 tests). New: `test_tool_path.py` (16):
happy path with a code-built source line; tool results go back as
`tool_result` blocks; the model sees the discovered tools and the member;
**the cap holds at 3** even if the model keeps asking; a refused action
becomes a plain reply; citing an unreturned record or nothing is
**blocked**; an empty result can cite what was looked up; no tools / no
member → no lookups; the allow-list hides tools and a hidden tool is never
sent to the server; the tool path is never cached (the gate is); tool
calls are recorded ($0) and traced; the document path is unchanged; and
one end-to-end test with a fake LLM and the **real gateway + server**.

Mutation-checked: removing the citation check fails the 2 "blocked"
tests; removing the cap fails the cap test.

## Milestone 7 — 💲 First live traces (~$0.05)

Three terminals: CRM, server, agent.
- [x] `M-1001`: "What's the balance on my checking account?"
- [x] `M-1001`: "What did I spend on groceries recently?" (two hops)
- [x] `M-1003`: "Are my cards active?" (CRM 500 → unavailable reply)
- [x] `M-1001`: "Please freeze my debit card, I lost it" as
      `member_assistant` → refused → contact-centre reply
- [x] Same question as `contact_centre` → frozen. Reset the CRM after.
- [x] One Day 2 document question, to show the old path still works.

**⏸ PAUSE:** read every `trace.jsonl` and audit line. Does each reply
end with a record-level source line? Does every audit line match a trace
event? Log surprises in `artifacts/findings_log.md`.

**Done (spend $0.086).** 6 planned questions + 3 re-checks; the audit
log matched the agent's tool records line for line. Found and fixed: the
source line credited the wrong call; the agent had no date. Decided at
the pause: a **code check on dollar figures + prompt v2**. Left as a
known gap (Day 4): an aggregate answer can still *omit* a matching record.
Details: `artifacts/findings_log.md`, milestone 7.

## Milestone 8 — 💲 Discovery demo: add a tool, change no agent code (~$0.03)

- [x] Note the agent's fingerprint (`scripts/agent_fingerprint.py`; the lab is uncommitted, so a file hash rather than a git SHA). Run the two "needs the new tool" questions
      on server 0.1.0 → the agent says it can't look this up.
- [x] On the server only: add `get_card_limits` (CRM endpoint + tool),
      grant it in `permissions.py`, bump to **0.2.0**, add it to the
      manifest and changelog. Restart the server.
- [x] Re-run the same questions with **the same agent SHA** → answered via
      `get_card_limits`.
- [x] `artifacts/discovery_trace.md`: both tool lists (names + hashes),
      the gate reasons, the tool calls, the replies, the two SHAs (equal),
      and the one server-side policy change it needed (known gap 4).

**Done ($0.05).** Fingerprint `7fd25b2d8f81ede0` before and after; tool
list hash `f5e87c29c6eea09e` → `7fd22ec198fa2fa7`; ATM $500 (policy) →
$800.00 (card), purchase dead end → $5000.00 (card). Deny-by-default shown
before the grant. Found and fixed first: the gate saw truncated tool
descriptions. `artifacts/discovery_trace.md`.

## Milestone 9 — Authorization evidence and the bypass (no spend)

- [x] `scripts/bypass_allowlist.py`: own MCP session with the
      `member_assistant` token, ignores `CLIENT_ALLOWED_TOOLS`, calls
      `freeze_card` → prints the server's refusal.
- [x] The agent with its allow-list set (model never shown `freeze_card`),
      the script with no allow-list at all (server refuses), and milestone 7's
      agent without one (server refused): the allow-list was never the thing
      refusing.
- [x] `artifacts/authorization_test.md`: the permitted call, the refused
      call, the bypass, the undeclared-`db_password` call and the bad
      token, each with its audit line and the pytest output.

**Done ($0.008).** `artifacts/authorization_test.md`; 25 related tests pass.

## Milestone 10 — 💲 Eval: tool set + gate re-check (~$0.35)

- [x] `eval/tool_set.yaml` (spec table, 15 questions).
- [x] `scripts/run_tool_eval.py`: runs the set, grades deterministically
      (spec "Eval"), writes `runs/<run_id>/`.
- [x] Pilot on 3 questions; check cost per question; then the full set.
- [x] Gate-only re-check on Day 2's 55 questions + the 15 new ones with
      `gate_v2`. Any Day 2 question that changed decision is a finding.

**⏸ PAUSE:** if the gate re-check regressed, fix the prompt (a named
`gate_v3`, not a silent edit) and re-run. Don't tune until it passes.

**Done ($0.61).** Tool set 14/14 excluding the known gap (t08: 1 of 3
over all attempts), every safety check 15/15. The pause fired: gate
re-check 68/70 under gate_v2. Decided: **gate_v3** (q012 regression:
"if no tool fits, retrieve") and a **documented relabel** of q039
(`eval/gate_relabels.yaml`). Final: 70/70 (69/70 against Day 2's labels).
`artifacts/eval_results.md`.

## Milestone 11 — Deck and wrap-up

- [x] `artifacts/high_level_deck.md`, 5-8 slides: problem (why MCP,
      "the server says no"), high-level flow, architecture (the three
      tiers, with MCP vertical vs A2A horizontal labelled), tech stack,
      the evidence (refusal, bypass, discovery), known gaps.
- [x] Update `spec.md` known gaps with anything found.
- [x] Final `uv run pytest`; `uv run python agent/spend.py`.

**Done.** `artifacts/high_level_deck.md` (8 slides). 212 tests pass. Day
spend $0.757 of $2.00. No server secret appears in any file git would
track (checked against `mcp_server/.env`); `.env` and the live audit log
are gitignored. Changes outside this folder: the Supabase migration
`20260928120000_harbor_core_banking.sql` and Harbor rows in
`supabase/seed.sql`. Nothing committed yet.

## Things to watch for (beginner pitfalls)

- **v1 tutorials.** Most MCP examples online are for SDK 1.x (`FastMCP`,
  `streamablehttp_client`). This lab uses 2.2.0 (`MCPServer`,
  `Client(streamable_http_client(...))`). When an example doesn't work,
  check the version first.
- **`supabase db push`** would apply the migration to the *remote* linked
  project. Only `db reset` / `migration up` locally.
- **Hiding a tool isn't forbidding it.** If you ever find yourself
  "fixing" a refusal test by filtering the tool list, stop: the test is
  about the server.
- **Two HTTP libraries.** The agent's gateway uses `httpx2` (MCP's); the
  server's CRM client uses `httpx`. Don't mix them up.
- **Mutating demo state.** `freeze_card` really changes the CRM. Reset
  the CRM between demo runs, or the second "freeze" looks like it did
  nothing.
- **Caching member data.** Never turn the local cache on for the tool
  path, or member A could get member B's cached answer.
