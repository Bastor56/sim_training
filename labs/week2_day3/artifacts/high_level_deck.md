# FDE Xlerate - Week 2, Day 3
High-level deck: an MCP server in front of the CRM and core banking, with the agent as a client (Harbor Credit Union)

## Slide 1: Title / Framing
- **Client: Harbor Credit Union.** 180,000 members, a 40-person contact centre. Members' data lives in a
  CRM and a core banking system that **no outside team may touch directly**.
- Days 1-2 grounded the agent in Harbor's **documents**. Today it answers from the **member's own
  records** ("what's my balance?", "freeze my card"), without ever holding a key to those systems.
- The FDE shape of the deliverable: **Harbor keeps the data and runs the server; we bring the agent.**
- One sentence to remember: **the server, not the agent, is the thing that says no.**

## Slide 2: The Problem
- **Week 1's agent called the CRM directly.** Its own code held the URL, made the calls and decided what
  it was allowed to do. That doesn't survive a bank's security review:
  - every new agent brings its own integration code and its own credentials;
  - "what may this agent do?" is answered by the code under review;
  - there is no single record of who called what.
- **MCP (Model Context Protocol) moves the boundary.** A server advertises typed tools; any client
  discovers and calls them. The server owns the credentials, the permission decision and the audit log.
- **The lab's tests of that claim:**
  - the agent adapts to a new server tool with **no agent change**;
  - a forbidden call is **refused by the server**, even when a client-side allow-list is bypassed;
  - credentials **never leave the server**, and every call is **audited**.

## Slide 3: High-Level Flow
```
member question ──▶ GATE (Haiku): documents? member's records? neither?   (tool list discovered at runtime)
                      │                        │                        │
                  retrieve                 use_tool                answer_direct
                  (Day 2, unchanged)          │
                                              ▼
                      TOOL LOOP (Claude native tool use, ≤ 3 rounds, cap in code)
                      e.g. list_member_accounts ──▶ list_transactions         every call ──▶ harbor-mcp
                                              ▼
                      ANSWER from the tool results only
                        · every cited record ID must have been returned        ─┐ else: fixed
                        · every $ figure must be in, or the exact total of,     │ "I couldn't confirm
                          the cited records                                     ─┘ that, so I won't guess"
                                              ▼
                      reply + source line built by code from the server's stamp:
                      "Source: Harbor core banking, account ACC-2001 (list_member_accounts).
                       Retrieved via harbor-mcp 0.2.0 at 2026-09-29T23:55:28Z."
```

## Slide 4: Architecture: Three Tiers, and the Middle One Is the Point
```
          A2A (horizontal): agent ⇄ agent, each owning its own tools. Guards: what one agent may ASK another.
  ┌──────────────────────────────┐   - - - - - - (not built; shown for contrast) - - - - - ▶  ┌────────────────────┐
  │ Harbor member agent          │                                                          │ e.g. disputes agent │
  │ gate · tool loop · answer    │  holds: ONE bearer token.   holds NOT: CRM key,           └────────────────────┘
  │ MCP client (mcp_gateway.py)  │  DB password, backend URLs, a list of tools
  └──────────────┬───────────────┘
                 │ MCP over Streamable HTTP · Authorization: Bearer <token>
                 │ MCP (vertical): agent → tools/data. Guards: what data an agent may TOUCH.
                 ▼
  ┌────────────────────────────────────────────────────────────────────────────┐
  │ harbor-mcp (Harbor runs this)                                               │
  │ 1. token → caller (unknown: HTTP 401, audited, token not logged)            │
  │ 2. middleware on EVERY tools/call, before the backend is touched:           │
  │      caller granted this tool?  → else forbidden (deny by default)          │
  │      args match the tool's schema, nothing undeclared? → else refused        │
  │      run tool → stamp `source` → ONE audit line (in `finally`)              │
  │ holds: CRM API key, Postgres password (mcp_server/.env)                     │
  └──────────────┬───────────────────────────────────────┬─────────────────────┘
                 │ HTTP + X-API-Key                        │ SQL as harbor_mcp (SELECT on 2 tables)
                 ▼                                         ▼
  ┌──────────────────────────────┐          ┌──────────────────────────────┐
  │ Mock CRM (FastAPI)           │          │ Core banking (Postgres)       │
  │ members · cards · freeze     │          │ accounts · transactions       │
  └──────────────────────────────┘          └──────────────────────────────┘
```
- **7 tools** (4 CRM, 3 core banking), each with a typed schema, a routing-grade description and a
  contract in `TOOL_MANIFEST.md`. A test fails the build if the manifest and the server disagree.
- **Two callers:** `member_assistant` (reads only), `contact_centre` (reads + `freeze_card`).

## Slide 5: Tech Stack
- **MCP:** the Python SDK **`mcp` 2.2.0** (the v2 line; its API differs from most 1.x examples online)
  for both halves: `MCPServer` + a `TokenVerifier` + one middleware; `Client` over Streamable HTTP.
- **Server:** Python 3.12, uvicorn; CRM client with week 1's timeout/retry policy (httpx); Postgres via
  psycopg as a least-privilege role whose password is **not** in the migration (set from `.env`).
- **Backends:** week 1's mock CRM, copied and given an API key and a `freeze_card` endpoint; local
  Supabase Postgres (`harbor_core` schema, not exposed to the REST API).
- **Agent:** Day 2's LangGraph agent, extended. Claude **Haiku 4.5** for the gate, tool selection and
  answers; a sync→async bridge (one background event loop, one MCP session) in `mcp_gateway.py`.
- **Proof tooling:** 212 pytest tests (real HTTP server in-process, fake backends that count calls),
  mutation checks, a JSONL audit log, an agent fingerprint, deterministic eval grading (no LLM judge).

## Slide 6: Evidence: The Server Says No
| Caller | Call | Result |
|---|---|---|
| member_assistant | `get_account(ACC-2001)` | ok, $4,210.55, audited `allowed/ok` |
| member_assistant, **own client, no agent, no allow-list** | `freeze_card(CARD-4001)` | **refused by the server** (`-32003 forbidden`), CRM never touched |
| contact_centre | the same call | ok: card frozen |
| member_assistant | `get_account(…, db_password="hunter2")` | refused; audit shows `[redacted]`, never the value |
| unknown token | connect | HTTP 401, audited, token not stored |
- **The allow-list is not the control.** With it, the model never *sees* `freeze_card`; without it, the
  model tries and the server refuses; a separate client with the same token is refused the same way.
- **Credentials:** a test fails if any agent file imports an HTTP/DB client, names a backend secret,
  port or path, or hardcodes a tool name. Planting week 1's pattern in `agent/` fails 3 tests.
- **Found by testing, fixed:** the audit log would have *stored* a smuggled password; the refusal alone
  wasn't enough.

## Slide 7: Evidence: Discovery and Eval
- **Discovery (R2): same agent, new server tool.** Agent fingerprint `7fd25b2d8f81ede0` before and after.
  | "What's my daily ATM limit?" | server 0.1.0 (6 tools) | server 0.2.0 (+ `get_card_limits`) |
  |---|---|---|
  | route | documents | `list_cards` → `get_card_limits` |
  | answer | $500 (Harbor's standard) | **$800.00 (this card's own limit)** |
  - One server-side step was still needed: **granting** the new tool. Before the grant it was advertised
    but refused. Deny by default, on purpose.
- **Tool eval (15 questions, deterministic):** **14/14** excluding one known gap; **every safety check
  15/15** (no invented IDs, no leaked values, no successful forbidden write, a source line on every reply).
- **Gate re-check (Day 2's 55 + 15 new):** 68/70 → a real regression found (a grace-period question
  answered from "general knowledge") → **gate_v3** → **70/70** (69/70 against Day 2's labels; one
  relabel, documented, where a new tool makes the old label wrong).
- **Cost:** **$0.010 per record question** (Haiku), ~3× a document question; 67% is tool selection.
  Latency p50 6.1 s. Day's spend: $0.76 of $2.00.

## Slide 8: Known Gaps / What's Next
- **Per tool, not per record.** `member_assistant` may read *any* account ID. Next: the member's identity
  in the token and an ownership check on the server.
- **Aggregates in the model.** "How much did I spend on groceries last week?" was right **1 time in 3**:
  the model sometimes *omits* a matching purchase. The figure check stops invented numbers, not omitted
  ones. → **Day 4: the governed SQL view**, exposed as its own tool.
- **Identity and transport.** Static tokens, no expiry, plain HTTP on localhost. Production: Harbor's
  identity provider (OAuth, audience checked), TLS.
- **Cost and latency.** Tool definitions are re-sent on every tool-selection call and are too short for
  Haiku's prompt caching; a CRM timeout costs ~8 s of retries.
- **What I'd build next week:** per-record authorization; the SQL-view aggregate tool; one question
  that needs both documents *and* records (routed today to one or the other).
