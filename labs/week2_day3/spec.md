# FDE Xlerate - Week 2, Day 3
Spec: an MCP server in front of Harbor's CRM and core banking, with the Day 2 agent as its client (Harbor Credit Union)

## Business problem

Day 2 gave Harbor an agent that answers from its **documents**. It can't
answer anything about a **member's own** accounts ("what's my checking
balance?", "is my card frozen?"), because that data lives in Harbor's CRM
and core banking system. Harbor's rule is that no outside team may touch
those systems directly.

Week 1's agent did touch a CRM directly: its `tool_client.py` held the
CRM's URL, made the HTTP calls itself and decided what to do with every
error. That pattern doesn't survive a bank's security review:

- every agent a team builds would carry its own copy of the integration
  code and its own credentials;
- "what is this agent allowed to do?" would be answered by the agent's
  own code, which is the thing being reviewed;
- there is no single record of who called what.

**MCP (Model Context Protocol)** moves that boundary. Harbor (the client)
runs an **MCP server** that owns the tools, the credentials, the
permission decision and the audit log. We bring the **agent**, which
connects as an MCP client, discovers what tools exist, and calls them. It
holds no integration code and no backend credentials.

The security question moves with it: **the server, not the agent, is the
thing that says no.**

Full lab text: `../../training_instructions/week2_day3.md`.

## Goal

1. An **MCP server** (`mcp_server/`) that exposes Harbor's CRM and core
   banking data as typed tools, authenticates each caller by token, checks
   a per-tool permission map on every call, holds the only backend
   credentials, and writes one audit record per tool call.
2. The **Day 2 agent as an MCP client** (`agent/`): it discovers the tool
   list at runtime and uses it through Claude's native tool use. Adding a
   tool on the server needs no change to the agent.
3. **Proof**, as files: a discovery trace, an authorization test (one
   permitted call, one refused), a bypass of a client-side allow-list that
   the server still refuses, and the audit log that recorded all of it.
4. A **tool manifest** written as a contract and versioned with the
   server, plus the architecture diagram and the 5-8 slide deck.

## Requirements

From the lab text, numbered so the plan and tests can refer to them.

| # | Requirement |
|---|---|
| R1 | The server exposes the CRM and database tools with typed input schemas and descriptions good enough for a client to route on discovery alone. |
| R2 | The client discovers the tool list at runtime and adapts: adding a tool on the server requires no change to the agent. |
| R3 | Authorization is enforced server-side, per tool call, against the caller's identity. Proven by a correctly refused call. A client-side allow-list is shown **not** to be enforcement by bypassing one. |
| R4 | Backend credentials live only on the server. The agent never holds them; the server never accepts them from the client. |
| R5 | Every tool call is logged server-side: caller identity, tool name, arguments, outcome. |
| R6 | The tool manifest is a contract: per tool, name, purpose, parameters, required permissions, side effects, failure modes. Checked in next to the server and versioned with it. |
| R7 | The agent's direct integration code is removed, not left dormant. |

## Decisions already made (planning session, 2026-09-28)

| # | Decision | Choice |
|---|---|---|
| 1 | Which agent becomes the client | The **Day 2 Harbor agent** (copied into `agent/` and extended). Week 1's CRM agent is not carried forward. |
| 2 | "The database" | **Local Postgres** (the repo's Supabase setup) holds core banking: accounts and transactions. The **mock CRM** (from week 1, renamed to Harbor members) holds members and cards. Both backends require a credential that only the server holds. |
| 3 | Transport | **Streamable HTTP.** The server is its own process; every request carries a bearer token. |
| 4 | Authorization granularity | **Per tool.** Not per record. (A caller allowed `get_account` can ask for any account ID. Listed as a known gap.) |
| 5 | A tool that changes something | **Yes, one:** `freeze_card`. It gives the manifest's side-effects column real content and gives the refusal demo an obvious target. |
| 6 | Stack | Python 3.12, **`mcp==2.2.0`** (the v2 SDK; its API differs from 1.x tutorials), LangGraph as Day 2, `anthropic==0.104.1` unchanged, `psycopg` for Postgres. Dependency resolve checked: no conflicts. |
| 7 | "Direct integration code deleted" | Week 1's `labs/week1_day4/src/tool_client.py` **stays** (week 1 is a finished submission). Day 3's agent has no integration code, and `tests/test_no_bypass.py` fails if any ever appears. |
| 8 | How the agent calls tools | **Claude native tool use.** The discovered MCP input schemas are passed straight into the Anthropic `tools` parameter. |
| 9 | Questions needing both documents and account data | **Out of scope today.** Handed to the Day 4/5 router. |

### What the spike proved (2026-09-28, scratchpad, before planning)

A throwaway server and client on `mcp==2.2.0`:
- `MCPServer(token_verifier=..., auth=AuthSettings(...), middleware=[...])`
  accepts a bearer-token verifier and a middleware list.
- The middleware runs on **every** request (`server/discover`,
  `tools/list`, `tools/call`) and sees the caller through
  `get_access_token().client_id`. One function can therefore do the
  permission check and the audit record for every tool.
- Raising `MCPError` in the middleware refuses the call. The client sees
  `MCPError: forbidden: member_assistant may not call freeze_card`.
- An unknown token is rejected at the HTTP layer (401) before any MCP
  message is handled.
- The client sends its token with
  `Client(streamable_http_client(url, http_client=httpx2.AsyncClient(headers={"Authorization": "Bearer ..."})))`.
  `Client(url, http_client=...)` does **not** exist and fails.
- The SDK uses its own HTTP library, **`httpx2`**, separate from `httpx`.

## Harbor constraints that apply today

| Constraint | How today meets it |
|---|---|
| Every answer names the source it came from | The tool-path reply ends with a **code-built source line** naming the system, record type and record ID, e.g. `Source: Harbor core banking, account ACC-2001 (get_account), via harbor-mcp 0.1.0`. The server stamps provenance on every result; the agent copies it, never writes it. |
| Memory holds only what the member said in this conversation | Unchanged from Day 2: single-turn, nothing carried between questions. Tool results are not cached (see "Cache"). |
| Aggregate questions go through the governed SQL view | No aggregate tools today. The server's database role can read single records only. The governed view is Day 4. |
| Policy answers quote the version in force | Unchanged: the document path is Day 2's. |

## Scope and non-goals

**In scope:** everything under Goal.

**Not in scope today:**
- **Per-record authorization** (decision 4). A known gap, written in the
  manifest.
- **Mixed questions** needing documents *and* account data (decision 9).
- **OAuth.** Static per-caller tokens stand in for Harbor's identity
  provider. The server's `TokenVerifier` is the only thing that would
  change.
- **Aggregate / reporting tools** (Day 4's governed SQL view).
- **MCP resources and prompts.** Tools only.
- **Multi-turn conversation.** Single-turn as Day 2.
- **Re-running Day 2's three-model comparison.** Haiku 4.5 stays the
  generator (Day 2's recommendation).
- **Changing week 1's code.** The mock CRM is *copied* and then changed.

## Key concepts (short primer)

- **MCP.** An open protocol with two sides. A **server** advertises
  *tools* (functions with a name, description and JSON input schema),
  *resources* (readable data) and *prompts*. A **client** connects, asks
  "what do you have?" (`tools/list`) and calls them (`tools/call`). Any
  client can use any server; neither needs to be written for the other.
- **Discovery.** The client learns the tool list from the server at
  runtime instead of having it written into its code. If the server adds
  a tool, the next `tools/list` includes it.
- **Native tool use.** Claude's API takes a `tools` list (name,
  description, `input_schema`). The model replies with a `tool_use` block
  ("call `get_account` with `{account_id: "ACC-2001"}`"). Our code runs the
  call, sends back a `tool_result`, and the model continues. An MCP
  tool's schema is already in the shape Claude expects, which is why the
  two fit together.
- **Authentication vs authorization.** *Authentication:* who are you?
  (the bearer token → `member_assistant`). *Authorization:* are you
  allowed to do this? (may `member_assistant` call `freeze_card`? No).
  Both happen on the server.
- **Bearer token.** A secret the caller sends in the
  `Authorization: Bearer <token>` HTTP header. The server looks it up to
  find the caller's identity. It identifies the *caller*, and is not a
  backend credential.
- **Allow-list vs enforcement.** A client-side allow-list ("this agent
  only shows the model these tools") is a convenience. Anyone with the
  token can skip it by writing their own client. Enforcement is a check
  the caller can't skip, which means it runs on the server.
- **Audit log.** An append-only record of every action: who, what, with
  which arguments, allowed or not, and what happened. It's what a bank's
  security review asks to see first.
- **MCP vs A2A.** MCP is the **vertical** boundary: one agent down to its
  tools and data. A2A (Agent2Agent) is the **horizontal** boundary between
  independent agents that each own their own tools and delegate tasks to
  each other. MCP guards "what data can this agent touch?"; A2A guards
  "what can one agent ask another agent to do?".

## Architecture

Three tiers, and the middle one is the whole point.

```
                        A2A (horizontal): agent <-> agent, each owns its own tools
   ┌──────────────────────────┐  - - - - - - - - - - - - - ->  ┌──────────────────────────┐
   │  Harbor member agent      │   (not built; drawn for        │  e.g. Harbor disputes    │
   │  (Day 2 agent + MCP       │    contrast: guards what one   │  agent, owns its own     │
   │   client)                 │    agent may ask another)      │  tools                   │
   │  - gate: retrieve /       │                                └──────────────────────────┘
   │    answer_direct /        │
   │    use_tool               │   holds: its MCP bearer token only
   │  - tool loop (Claude      │   holds NOT: CRM key, DB password, any backend URL
   │    native tool use)       │
   └────────────┬─────────────┘
                │  MCP over Streamable HTTP        MCP (vertical): agent -> tools/data
                │  Authorization: Bearer <token>   guards what data an agent can touch
                ▼
   ┌──────────────────────────────────────────────────────────────┐
   │  harbor-mcp server  (Harbor runs this; the boundary)          │
   │  1. authenticate:  token -> caller identity  (401 if unknown) │
   │  2. middleware, on EVERY request:                              │
   │       tools/call -> PERMISSIONS[caller] has tool? else refuse │
   │                  -> args match tool's schema? else refuse    │
   │                  -> run tool -> audit record (always)         │
   │  3. tools: typed schemas, provenance stamped on every result  │
   │  holds: CRM API key, Postgres password (mcp_server/.env)      │
   │  writes: audit/audit.jsonl                                    │
   └───────────────┬──────────────────────────────┬───────────────┘
                   │ HTTP + X-API-Key              │ SQL as role harbor_mcp
                   ▼                               ▼  (SELECT on 2 tables only)
   ┌──────────────────────────┐        ┌──────────────────────────┐
   │  Mock CRM (FastAPI)       │        │  Core banking (Postgres)  │
   │  members, cards,          │        │  accounts, transactions   │
   │  POST freeze card         │        │  schema harbor_core       │
   │  injectable faults        │        │                           │
   └──────────────────────────┘        └──────────────────────────┘
```

Control flows client → server → backend, and results return the same
way. **The authorization check happens before the backend is touched.**
A refused call never reaches the CRM or the database.

The agent's document path (Day 6 retrieval, validator, generator) is
unchanged and stays inside the agent process. It isn't behind MCP today.

## The server (`mcp_server/`)

### Callers and permissions (R3)

Per-caller tokens live in `mcp_server/.env` (gitignored; an
`.env.example` with placeholders is committed). The permission map lives
in code (`mcp_server/permissions.py`), because it's policy that should be
reviewed like code.

| Caller (`client_id`) | Who it stands for | Allowed tools |
|---|---|---|
| `member_assistant` | The member-facing agent (this lab's agent, by default) | every **read** tool |
| `contact_centre` | A contact-centre staff tool acting for an agent on the phone | every read tool **+ `freeze_card`** |

A tool missing from the map is refused for everyone ("deny by default").
So a newly added tool is invisible to authorization until someone
deliberately grants it. That's the safe default, and it's why the
discovery demo (milestone 8) includes granting the new tool as a step.

### Tools (R1, R6)

Version `0.1.0`. Full contract in `mcp_server/TOOL_MANIFEST.md`.

| Tool | Backend | Parameters | Side effects | Allowed |
|---|---|---|---|---|
| `get_member` | CRM | `member_id` | none | both |
| `list_cards` | CRM | `member_id` | none | both |
| `freeze_card` | CRM | `card_id`, `reason` | **sets the card's status to `frozen`** (idempotent) | `contact_centre` |
| `list_member_accounts` | core banking | `member_id` | none | both |
| `get_account` | core banking | `account_id` | none | both |
| `list_transactions` | core banking | `account_id`, `limit` (1-50, default 10) | none | both |

Added in milestone 8 for the discovery demo, as version `0.2.0`:

| `get_card_limits` | CRM | `card_id` | none | both, once granted |

**Descriptions are written for routing** (R1): each one says what the
tool returns, when to use it, and what it does *not* do. For example,
`get_account`: "Current balance, type and status of one account, from
core banking. Use when the member asks about a specific account's balance
or status. Needs an account ID; to find a member's account IDs, use
`list_member_accounts`. Does not return transactions."

### Every result carries provenance

Each tool returns structured content with the data plus a `source`
block, stamped by the server:

```json
{"data": {...},
 "source": {"system": "harbor_core_banking", "record_type": "account",
            "record_ids": ["ACC-2001"], "tool": "get_account",
            "server": "harbor-mcp", "server_version": "0.1.0",
            "fetched_at": "2026-09-28T14:02:11Z"}}
```

The agent's source line is built from this block by code. The model never
writes the source line.

### Failure modes (closed set)

Backend reality is translated into a small set of outcomes, the same idea
as week 1's tool layer, now on the server:

| Outcome | Cause | What the client gets |
|---|---|---|
| `ok` | success | data + source |
| `not_found` | 404 from CRM, no row in core banking | a tool error result: "No account ACC-9999." |
| `conflict` | 409 from CRM: freezing a card already reported lost (added in milestone 2) | a tool error result: "Card CARD-4008 is already reported lost and cannot be frozen." |
| `unavailable` | CRM 500 / timeout / malformed body after retries; Postgres unreachable | a tool error result: "Core banking is unavailable right now." |
| `invalid_arguments` | schema validation failed, or an undeclared argument was sent | protocol error (refused before the tool runs) |
| `forbidden` | caller not allowed this tool | protocol error (refused before the tool runs) |

`not_found` and `unavailable` come back as **tool results with
`is_error=True`**, so the model can read them and tell the member. The
two refusals are raised in the middleware as `MCPError`, so they never
reach the tool code.

Faults are injectable as in week 1: specific fixture members' card
lookups return 500 / time out / return a malformed body. Postgres
`unavailable` is shown by stopping the database container.

### No credentials from the client (R4)

- No tool has a credential-like parameter.
- The middleware validates every call's arguments against the tool's own
  advertised schema (types, patterns, required fields) and refuses **any
  undeclared argument** (`db_password`, `api_key`, anything). Pydantic
  would otherwise silently ignore extras, and "silently ignored" is weaker
  than "refused and logged".
- **Order (changed in milestone 3):** the permission check runs *before*
  the argument check, so a caller without the grant learns nothing about
  a tool, not even its parameters.
- **The value of an undeclared argument is never written to the audit
  log** (`"db_password": "[redacted: undeclared argument]"`). Otherwise
  the audit log would become the place the secret ends up stored.
- The server reads `CRM_API_KEY` and `HARBOR_DB_*` from its own `.env`
  only.

### Audit log (R5)

One JSON line per `tools/call`, appended to `mcp_server/audit/audit.jsonl`
by the middleware, in a `finally` so refusals and crashes are recorded
too:

```json
{"ts": "2026-09-28T14:02:11.482Z", "audit_id": "aud_...", "request_id": 7,
 "caller": "member_assistant", "tool": "freeze_card",
 "arguments": {"card_id": "CARD-4001", "reason": "member reports card lost"},
 "decision": "denied", "outcome": "forbidden", "error": "member_assistant may not call freeze_card",
 "latency_ms": 0.4, "server_version": "0.1.0"}
```

- `decision`: `allowed` | `denied`. `outcome`: one of the failure-mode
  names above.
- Unauthenticated requests (401) are rejected before the middleware
  runs. They're logged by a small ASGI wrapper as `outcome: "unauthenticated"`
  with the caller as `null` (milestone 3 checks the SDK allows this; if
  not, it becomes a known gap).
- `tools/list` is not logged per call (only `tools/call`), but the
  server logs its advertised tool list and version on startup.
- The log is gitignored. The demo run's lines are copied into
  `artifacts/authorization_test.md` as evidence.

### Backend credentials

| Backend | Credential | Where it's set |
|---|---|---|
| Mock CRM | `X-API-Key` header, checked on every endpoint except `/health` | CRM reads `CRM_API_KEY` from its env; server reads the same value from `mcp_server/.env` |
| Postgres | role `harbor_mcp` with a password, `SELECT` on `harbor_core.accounts` and `harbor_core.transactions` only (no INSERT/UPDATE, no other schemas) | The **migration creates the role without a password** (so none is committed). `scripts/set_db_password.py` sets it from `mcp_server/.env`. |

## The agent (`agent/`)

A copy of Day 2's `src/` (wrapper, tracing, spend guard, cache, Day 6
bridge, graph), extended. Day 2's own folder is not touched.

### Graph

```
START -> planner --answer_direct--> answer_direct ----------------------------> finalise -> END
            |   \--retrieve--> retrieve -> validate -> generate ... (Day 2, unchanged)
            |
            \--use_tool--> tool_loop --> generate_from_tools -----------------> finalise -> END
                             ^   |  (Claude native tool use, max 3 tool rounds)
                             └───┘
```

### The gate (`gate_v2`)

- Adds a third decision, **`use_tool`**: "the answer needs this member's
  own records."
- The gate's system prompt gets the **discovered tool list** (name + first
  line of each description) appended at runtime. So when the server adds
  a tool, the gate sees it with no prompt edit. The static part stays
  first, so the provider-side prompt cache still covers it.
- Schema: `{decision: retrieve|answer_direct|use_tool, reason, search_query}`.
- **`use_tool` only if a listed tool can provide what's asked** (added in
  milestone 6). Otherwise `retrieve` (Harbor's standard limits/fees) or
  `answer_direct`. This makes the gate's decision depend on what the
  server advertises: before `get_card_limits` exists, "what's my ATM
  limit?" is answered from the Debit Card Limits document; after, from the
  card's own record. That is the discovery demo (milestone 8).
- Re-checked on Day 2's 55 questions (to prove nothing regressed) plus the
  new tool questions.

### The tool loop (`tool_loop` node)

1. Tools shown to the model = discovered tools (minus the client-side
   allow-list, if one is configured; see "Allow-list" below), converted
   `{name, description, input_schema}` → Anthropic `tools`.
2. One LLM call (`purpose="tool_select"`, Haiku 4.5, via the wrapper).
   The user message includes the question and the **authenticated member
   ID** for this session (`--member M-1001`).
3. For each `tool_use` block: call the MCP server, append a `tool_result`
   (the structured content, or the error text with `is_error: true`).
4. Repeat until the model stops asking for tools, or **3 rounds** (the
   cap is enforced in code, as on Day 2).
5. Every tool call writes a trace event: tool, arguments, outcome, record
   IDs, latency.

### Answering from tool results (`generate_from_tools`)

- Structured output: `{status: answered|cannot_answer, answer, cited_record_ids, reason}`.
- The code checks every cited ID came from a tool result in this
  question, the same guard as Day 2's `cited_chunk_ids`. An uncited or
  unknown ID blocks the answer. An ID that was *looked up* but returned
  nothing is citable too (for example "no transactions on ACC-2003"),
  because the server's `source.lookup` names it.
- Outcomes: `answered_from_records` (model answer + source line),
  `records_cannot_answer` (the model's plain explanation, e.g. "I can't
  freeze cards here; the contact centre can"), `records_blocked` (fixed
  reply: uncited / unknown IDs), `records_unavailable` (fixed reply: no
  tools, or the lookup step failed). A member with no session gets a fixed
  "sign in" reply and no lookups.
- If a tool was refused or unavailable, the reply says so plainly and
  offers the contact-centre path. Never invent data (week 1's rule).

### The MCP client (`agent/mcp_gateway.py`)

- **The only agent file that imports `mcp`.**
- The graph is synchronous (as Day 2); the MCP client is async. The
  gateway runs one persistent MCP session on a background event loop
  (`anyio.from_thread.start_blocking_portal`) and exposes plain methods:
  `list_tools()`, `call_tool(name, args)`. Fallback if that misbehaves:
  one short-lived connection per call (slower, simpler). Milestone 5
  decides.
- Reads **only** `HARBOR_MCP_URL` and `HARBOR_MCP_TOKEN`.
- Logs the discovery result on connect: server name/version, tool names,
  and a hash of the full tool list. That's the discovery trace (R2).

### Allow-list (R3 bypass demo)

`agent/settings.py` has `CLIENT_ALLOWED_TOOLS: set | None`. When set, the
agent hides other tools from the model. It's set to the read tools in the
bypass demo, and it **is not enforcement**. `scripts/bypass_allowlist.py`
opens its own MCP session with the same `member_assistant` token, skips
the agent entirely, and calls `freeze_card`. The server refuses it, and
the audit log records the refusal.

### No direct integration (R4, R7)

`tests/test_no_bypass.py` (extending Day 2's) parses every `agent/*.py`
file's syntax tree and fails if:
- `anthropic` is imported anywhere but `llm.py` (Day 2's rule);
- `mcp` / `httpx2` is imported anywhere but `mcp_gateway.py`;
- `httpx`, `requests`, `urllib`, `psycopg` or `fastapi` is imported
  anywhere in the agent;
- any agent file contains `CRM_API_KEY`, `HARBOR_DB_` or a backend URL /
  port (`:8100`, `:54322`).

## Instrumentation and cost

- Day 2's wrapper (`llm.py`) is extended with `tools=` and multi-turn
  `messages=` for the tool loop. Every call is still recorded, priced and
  budget-checked. New purposes: `tool_select`, `generate_from_tools`.
- Tool calls are recorded as `kind="mcp_tool"` records ($0, with latency)
  under the question's correlation ID, as Day 2 did for local retrieval.
- **Cache (Day 2 open question 5, now answered):** tool results are
  member-specific and change over time (a card can be frozen between two
  identical questions). So **calls on the tool path are never cached**
  (`tool_select`, `generate_from_tools`). The gate's cache key adds the
  hash of the discovered tool list, because the gate prompt now contains
  it.

## Budget

| | |
|---|---|
| Day limit | **$2.00** of API spend |
| Guard | **$1.75**: no new provider call once the lab's ledger reaches this |
| Expected | ~$0.10 gate re-check (70 questions × gate only), ~$0.25 tool-set runs, ~$0.10 demos |

Ledger: `runs/spend_ledger.jsonl` (Day 3's own, committed).

## Eval

`eval/tool_set.yaml`, 15 questions, each with an expected gate decision,
expected tool(s), and an expected fact in the answer:

| Kind | Count | Example |
|---|---|---|
| Single-tool read | 5 | "What's the balance on my checking?" (M-1001) |
| Two-hop (list → detail) | 3 | "What did I spend at the grocery store last week?" (accounts → transactions) |
| Not found | 1 | a member with no savings asks for the savings balance |
| Backend unavailable | 2 | M-1003 (CRM 500), M-1004 (timeout): the reply says unavailable, invents nothing |
| Forbidden action | 2 | "Please freeze my card, I lost it" as `member_assistant` → refused; the reply points to the contact centre |
| Needs the new tool | 2 | "What's my daily ATM limit on my card?": before `0.2.0` → tells the member it can't look this up; after → answered with no agent change |

Grading is **deterministic only** (no judge today): gate decision
matches; the expected tool set was called; the expected fact is in the
answer; the reply ends with a source line naming the record; zero invented
IDs.

Plus the gate re-check: Day 2's 55 questions must still get their Day 2
decision (`retrieve` / `answer_direct`), and none may become `use_tool`,
**except** where a relabel in `eval/gate_relabels.yaml` says otherwise, with
its reason, while its tool is advertised (q039, milestone 10). Both scores
are reported. Results: `artifacts/eval_results.md`.

## Deliverables → files

| Deliverable | File |
|---|---|
| Working server + agent as client, direct integration removed | `mcp_server/`, `agent/`, `tests/test_no_bypass.py` |
| Discovery trace | `artifacts/discovery_trace.md` (0.1.0 → 0.2.0, the same agent code adapting) |
| Authorization test | `tests/test_authorization.py` + `artifacts/authorization_test.md` (permitted, refused, bypass, undeclared-arg, bad token, with audit lines) |
| Tool manifest | `mcp_server/TOOL_MANIFEST.md` (+ `tests/test_manifest.py` checking it matches the server) |
| Architecture diagram | in the deck (and above) |
| Deck (5-8 slides) | `artifacts/high_level_deck.md` |
| Findings | `artifacts/findings_log.md` |

## File / folder layout

```
labs/week2_day3/
  spec.md  plan.md  requirements.txt  pytest.ini  .python-version  .gitignore
  backends/
    mock_crm/            copied from week1_day4/mock_crm, then: Harbor members,
                         no accounts/transactions, X-API-Key, POST /cards/{id}/freeze,
                         card limits (0.2.0)
  mcp_server/
    server.py            MCPServer, tools, startup log
    auth.py              TokenVerifier (token -> caller)
    permissions.py       PERMISSIONS map
    middleware.py        undeclared-arg check, authorization, audit record
    audit.py             JSONL writer
    backends.py          CRM client (httpx, key, retries) + Postgres (psycopg, role harbor_mcp)
    config.py            reads mcp_server/.env
    TOOL_MANIFEST.md
    .env.example
    audit/               (gitignored)
  agent/                 copied from week2_day2/src, then extended
    mcp_gateway.py       the only MCP import
    llm.py               + tools / messages
    agent_nodes.py       + tool_loop, generate_from_tools
    agent_graph.py       + use_tool branch
    ...
  prompts/               gate_v2, tool_select_v1, generate_from_tools_v1 (+ Day 2's, copied)
  scripts/
    set_db_password.py   sets harbor_mcp's password from mcp_server/.env
    bypass_allowlist.py  the R3 bypass demo
    run_tool_eval.py     runs eval/tool_set.yaml
  eval/tool_set.yaml
  tests/
  runs/  artifacts/

../../supabase/migrations/2026092800xxxx_harbor_core_banking.sql   schema, tables, role (no password)
../../supabase/seed.sql                                             + Harbor accounts/transactions rows
```

## Setup

```bash
# 1. Docker Desktop running. Then, from the repo root, LOCAL ONLY:
npx supabase start
npx supabase db reset          # local by default. NEVER `db push` (the CLI is linked to a remote project)

# 2. From labs/week2_day3/
uv venv --python 3.12 && uv pip install -r requirements.txt
cp mcp_server/.env.example mcp_server/.env   # then fill in tokens / keys
uv run python scripts/set_db_password.py

# 3. Three terminals
uv run uvicorn app:app --app-dir backends/mock_crm --port 8100
uv run python -m mcp_server.server                          # :8200/mcp
HARBOR_MCP_TOKEN=... uv run python agent/run_agent.py --member M-1001 "What's my checking balance?"
```

## Acceptance criteria

| Req | Met when | Evidence |
|---|---|---|
| R1 | Every tool has a typed schema and a routing-grade description; the agent routes the 15 tool questions using only discovered descriptions | `tools/list` dump in discovery trace; tool-set results |
| R2 | The same agent commit answers the "needs the new tool" questions after the server moves to 0.2.0, and can't before | `artifacts/discovery_trace.md` (two tool-list hashes, same agent git SHA) |
| R3 | `member_assistant` → `get_account` allowed; → `freeze_card` refused by the server; `contact_centre` → `freeze_card` allowed; bypass script refused | `tests/test_authorization.py`; audit lines |
| R4 | Undeclared `db_password` argument refused and logged; `test_no_bypass.py` passes; the agent process env has no backend credentials | tests; `artifacts/authorization_test.md` |
| R5 | One audit line per `tools/call` in every test and demo (count matches), including denied ones | `test_audit.py`; audit excerpt |
| R6 | Manifest covers all 7 columns for every tool; `test_manifest.py` passes at 0.1.0 and 0.2.0 | `TOOL_MANIFEST.md` |
| R7 | No integration code in `agent/` (test) | `test_no_bypass.py` |
| Harbor | 0 tool-path replies without a record-level source line; 0 invented record IDs | tool-set grades |
| No regression | Day 2's 55 questions keep their gate decision | gate re-check run |
| Budget | ledger ≤ $2.00 | `runs/spend_ledger.jsonl` |

## Known gaps / assumptions (to grow during the build)

1. **Per-tool, not per-record** (decision 4). `member_assistant` may call
   `get_account` for *any* account ID. The agent passes the session's
   member ID, but nothing on the server stops a prompt-injected model
   from asking for someone else's. Production needs the member's identity
   in the token and a per-record check on the server.
2. **Static tokens**, no expiry or rotation. Production: Harbor's identity
   provider issuing short-lived tokens (OAuth), verified by the same
   `TokenVerifier` interface.
3. **Arguments are logged in full.** Today they're IDs and a free-text
   `reason`. If a tool ever takes PII, the audit log needs redaction
   rules.
4. **Deny-by-default means a new tool needs a grant.** That's deliberate,
   but it means "no agent change" (R2) still needs one server-side policy
   change. Say so in the demo rather than hiding it.
5. **Local only.** No TLS between agent and server; a bearer token over
   plain HTTP is only acceptable on localhost.
6. **Model arithmetic and filtering (milestone 7).** A dollar-figure check
   (`agent/figures.py`) blocks answers whose figures aren't in, or the exact
   total of, the cited records. It cannot catch a *missed* record: a
   "last week" total omitted one of two matching purchases. Time-window and
   total questions are aggregates and belong in Day 4's governed SQL view.
7. **Today's date is supplied by code** (`--today`, pinned in evals) so
   relative dates ("last week") mean something to the model.
