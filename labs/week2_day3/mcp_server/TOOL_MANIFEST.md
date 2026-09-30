# harbor-mcp — Tool Manifest

**Server version:** 0.2.0

The contract between Harbor's systems of record and any agent that
connects to this server. For each tool: its name, purpose, parameters,
required permission, side effects and failure modes.

The **server** is the source of truth for what it advertises (`tools/list`).
This document is the source of truth for what a caller may **rely on**.
`tests/test_manifest.py` fails if the two disagree on tool names,
parameters, required fields, permissions or version. Change them together,
bump the version, and add a changelog line.

## Changelog

| Version | Date | Change |
|---|---|---|
| 0.1.0 | 2026-09-28 | First release: 6 tools (3 CRM, 3 core banking), per-tool authorization, audit log. |
| 0.2.0 | 2026-09-28 | Added `get_card_limits` (CRM, read-only), granted to both callers. No change to existing tools. Clients pick it up at their next `tools/list`; no client change needed. |

## Connecting

| | |
|---|---|
| Transport | MCP Streamable HTTP, `http://127.0.0.1:8200/mcp` (local only; production needs TLS) |
| Authentication | `Authorization: Bearer <token>`, one token per caller, issued by Harbor. Unknown or missing token → HTTP **401** before any MCP message is read. |
| Credentials | Callers never send backend credentials. The server holds the CRM key and the database login; any argument a tool didn't declare is **refused**. |
| Audit | Every `tools/call` is recorded server-side: caller, tool, arguments, decision, outcome, latency. Values of undeclared arguments are redacted. 401s are recorded too, without the token. |

## Callers

| Caller | Stands for | Granted |
|---|---|---|
| `member_assistant` | The member-facing agent | every read tool |
| `contact_centre` | A contact-centre staff tool | every read tool + `freeze_card` |

**Deny by default.** A caller not listed, or a tool not granted to that
caller, is refused. A new tool is refused for everyone until granted.

## Result shape (every tool)

Success: an MCP result whose `structuredContent` is

```json
{"data": <tool-specific>,
 "source": {"system": "harbor_crm | harbor_core_banking", "record_type": "member | card | account | transaction",
            "record_ids": ["..."], "lookup": {<the arguments that were looked up>},
            "tool": "<tool name>", "server": "harbor-mcp", "server_version": "0.2.0",
            "fetched_at": "<UTC ISO-8601>"}}
```

`source` is stamped by the server. A caller that shows the data to a
person should name the source from this block, not write its own.
`record_ids` can be empty ("looked, found none"); `lookup` then says what
was looked for.

Money is a **decimal string** in USD with 2 decimals (`"4210.55"`), never a
float. Negative transaction amounts are money out. Dates are ISO
(`YYYY-MM-DD`).

## Failure modes (every tool)

Two kinds, and a caller must handle both.

**Refusals: a protocol error.** Raised before the tool runs; the backend
is never touched. The client SDK raises `MCPError`.

| Outcome | JSON-RPC code | When |
|---|---|---|
| `forbidden` | `-32003` (server-defined) | The caller isn't granted this tool. Checked first: a refused caller learns nothing about the tool's parameters. |
| `invalid_arguments` | `-32602` | Arguments don't match the tool's input schema: wrong type, fails a pattern or range, a required one missing, or **any undeclared argument**. The message names fields, never values. |

**Tool failures: an error result** (`isError: true`, message in
`content[0].text`). Safe to show a member; they contain no hosts, URLs or
status codes.

| Outcome | When | Message (example) |
|---|---|---|
| `not_found` | The record doesn't exist | `No account ACC-9999.` |
| `conflict` | The action can't apply to the record's current state | `Card 'CARD-4008' is already reported lost and cannot be frozen.` |
| `unavailable` | The backend is down, slow (CRM: 2 s timeout, 3 attempts with backoff), returned a malformed body, or refused the server's own credentials | `The CRM is unavailable right now.` / `Core banking is unavailable right now.` |

A caller should never retry `forbidden` or `invalid_arguments` unchanged.
`unavailable` has already been retried by the server.

## Tools

### `get_member`

**Purpose:** A member's CRM profile: name, email, member-since date. For
confirming who the member is or how long they've been a member. Does not
return accounts, balances or cards.

**Backend:** CRM · `GET /members/{member_id}`

**Parameters:**

| Name | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `member_id` | string | yes | `^M-\d{4}$` | Harbor member ID, e.g. M-1001 |

**Required permission:** `member_assistant`, `contact_centre`

**Side effects:** None (read-only).

**Failure modes:** `not_found` (no such member) · `unavailable` · refusals.

**Example:** `{"member_id": "M-1001"}` →
`data: {"member_id": "M-1001", "name": "Maria Chen", "email": "maria.chen@example.com", "member_since": "2019-03-11"}`

### `list_cards`

**Purpose:** A member's payment cards: card ID, type (debit/credit), last
four digits, status (`active` / `frozen` / `lost`) and the account each
card draws on. For card-status questions and for finding a card ID.
Does not return limits or transactions.

**Backend:** CRM · `GET /members/{member_id}/cards`

**Parameters:**

| Name | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `member_id` | string | yes | `^M-\d{4}$` | Harbor member ID, e.g. M-1001 |

**Required permission:** `member_assistant`, `contact_centre`

**Side effects:** None (read-only).

**Failure modes:** `not_found` (no such member) · `unavailable` (the mock
CRM's fixture members M-1003 to M-1006 fail here on purpose; M-1006
recovers on the 3rd attempt, inside the server's retries) · refusals. An
empty list means the member has no cards.

**Example:** `{"member_id": "M-1001"}` →
`data: [{"card_id": "CARD-4001", "member_id": "M-1001", "account_id": "ACC-2001", "type": "debit", "last_four": "4471", "status": "active"}]`

### `get_card_limits`

*Added in 0.2.0.*

**Purpose:** A card's own current daily limits: ATM cash withdrawal and
purchase (point-of-sale), and when they were last changed. These are the
card's actual limits, which can differ from Harbor's standard limits
($500 ATM / $3,000 purchases, in the Debit Card Limits document). Does not
change limits.

**Backend:** CRM · `GET /cards/{card_id}/limits`

**Parameters:**

| Name | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `card_id` | string | yes | `^CARD-\d{4}$` | Card ID, e.g. CARD-4001 (from `list_cards`) |

**Required permission:** `member_assistant`, `contact_centre`

**Side effects:** None (read-only).

**Failure modes:** `not_found` (no such card) · `unavailable` · refusals.

**Example:** `{"card_id": "CARD-4001"}` →
`data: {"card_id": "CARD-4001", "atm_daily_limit": "800.00", "purchase_daily_limit": "5000.00", "currency": "USD", "updated_on": "2026-06-14"}`

### `freeze_card`

**Purpose:** Freeze a card so it can't be used. The only tool that changes
data. Use only when the member explicitly asks to freeze or block a card.

**Backend:** CRM · `POST /cards/{card_id}/freeze`

**Parameters:**

| Name | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `card_id` | string | yes | `^CARD-\d{4}$` | Card ID, e.g. CARD-4001 (from `list_cards`) |
| `reason` | string | yes | 1-500 chars | Why the card is being frozen, as stated by the member or staff |

**Required permission:** `contact_centre`

**Side effects:** **Sets the card's status to `frozen` in the CRM.**
Idempotent: freezing an already-frozen card changes nothing and returns
the same result (so the server's retry can't double-apply). Reversing a
freeze is not available through this server.

**Failure modes:** `not_found` (no such card) · `conflict` (the card is
`lost`, which is already a permanent block) · `unavailable` · refusals.
`forbidden` for `member_assistant`.

**Example:** `{"card_id": "CARD-4001", "reason": "member reports card lost"}` →
`data: {"card_id": "CARD-4001", ..., "status": "frozen"}`

### `list_member_accounts`

**Purpose:** A member's accounts: ID, type (checking / savings / credit),
current balance, status, opening date. The usual first call for any
question about the member's own accounts or balances. Does not return
transactions.

**Backend:** core banking · `harbor_core.accounts`, read as role `harbor_mcp` (SELECT only)

**Parameters:**

| Name | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `member_id` | string | yes | `^M-\d{4}$` | Harbor member ID, e.g. M-1001 |

**Required permission:** `member_assistant`, `contact_centre`

**Side effects:** None (read-only; the database role can't write).

**Failure modes:** `unavailable` · refusals. An **empty list** means core
banking has no accounts for this ID. It does **not** confirm the member
exists; use `get_member` for that.

**Example:** `{"member_id": "M-1001"}` →
`data: [{"account_id": "ACC-2001", "member_id": "M-1001", "type": "checking", "balance": "4210.55", "status": "active", "opened_on": "2019-03-11"}, {"account_id": "ACC-2002", ...}]`

### `get_account`

**Purpose:** One account's current balance, type, status and opening date.

**Backend:** core banking · `harbor_core.accounts`

**Parameters:**

| Name | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `account_id` | string | yes | `^ACC-\d{4}$` | Core-banking account ID, e.g. ACC-2001 |

**Required permission:** `member_assistant`, `contact_centre`

**Side effects:** None (read-only).

**Failure modes:** `not_found` (no such account) · `unavailable` · refusals.

**Example:** `{"account_id": "ACC-2001"}` →
`data: {"account_id": "ACC-2001", "member_id": "M-1001", "type": "checking", "balance": "4210.55", "status": "active", "opened_on": "2019-03-11"}`

### `list_transactions`

**Purpose:** The most recent posted transactions on one account, newest
first: date, signed amount, description, category. For spending, deposit
and specific-charge questions. Does not include pending transactions or
card authorizations.

**Backend:** core banking · `harbor_core.transactions`

**Parameters:**

| Name | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `account_id` | string | yes | `^ACC-\d{4}$` | Core-banking account ID, e.g. ACC-2001 |
| `limit` | integer | no | 1-50, default 10 | How many of the most recent transactions to return |

**Required permission:** `member_assistant`, `contact_centre`

**Side effects:** None (read-only).

**Failure modes:** `not_found` (no such account; checked, so an unknown
account is never a silent empty list) · `unavailable` · refusals. An
**empty list** means the account exists and has no transactions.

**Example:** `{"account_id": "ACC-2001", "limit": 2}` →
`data: [{"transaction_id": "TXN-3010", "account_id": "ACC-2001", "posted_on": "2026-09-26", "amount": "-63.48", "description": "Green Leaf Grocery", "category": "groceries"}, {...}]`

## Known gaps (what a security review should know)

1. **Authorization is per tool, not per record.** A caller granted
   `get_account` can read *any* account ID. The member-facing agent passes
   its session's member ID, but the server doesn't check that the record
   belongs to that member. Production: the member's identity in the token,
   and a per-record ownership check on the server.
2. **Static tokens**, no expiry or rotation. Production: short-lived OAuth
   tokens from Harbor's identity provider, with audience checking turned on.
3. **Audit arguments are logged in full** (except undeclared ones). Today
   they are IDs and a free-text `reason`. A tool that ever takes PII needs
   redaction rules first.
4. **Deny by default:** a new tool needs a grant here before any caller can
   use it. Deliberate, but it means "no agent change" still needs one
   server-side policy change.
5. **Local only:** plain HTTP on localhost. A bearer token over plain HTTP
   is not acceptable anywhere else.
6. **One database connection per call.** Fine locally; production needs a
   connection pool.
7. **No aggregate tools.** `list_transactions` returns raw rows; "how much
   did I spend on X last week?" leaves filtering and adding to the calling
   model, which omitted a matching transaction in testing (the agent's
   figure check catches invented totals, not omissions). Aggregates belong
   in Harbor's governed SQL view (Day 4), exposed as their own tool.
