# Harbor Mock CRM — Contract

A real HTTP service (FastAPI), copied from week 1
(`labs/week1_day4/mock_crm`) and reshaped for Harbor Credit Union. It holds
**members and cards**. Accounts and transactions live in core banking
(Postgres, `harbor_core` schema), not here.

Run it from `labs/week2_day3/`:

```bash
uv run python scripts/run_crm.py          # :8100, key from mcp_server/.env
```

`run_crm.py` passes this process **only** `CRM_API_KEY`, nothing else
from the server's `.env`. The CRM refuses to start without a key.

Base URL: `http://127.0.0.1:8100`. This document is the contract. If
`app.py` disagrees with it, `app.py` has the bug.

## Authentication

Every endpoint except `/health` requires the header
`X-API-Key: <key>`. Missing or wrong key:

**401** `{"error": "unauthorized", "message": "Missing or invalid X-API-Key."}`

The key is checked **before** anything else, including the fault
injection header: an unauthenticated caller can't trigger anything.

In the Day 3 architecture, the harbor-mcp server is the only holder of
this key. The agent never has it.

## Operational endpoints (not part of the business contract)

- `GET /health` → `200 {"status": "ok"}`. No key needed.
- `POST /admin/reset` → `200 {"status": "reset"}`. Restores every card to
  its initial status and clears fault counters. Key required. For tests
  and between demo runs; the MCP server never calls it.

## Domain endpoints

### `GET /members/{member_id}`

**200**:
```json
{"member_id": "M-1001", "name": "Maria Chen", "email": "maria.chen@example.com", "member_since": "2019-03-11"}
```
**404** `not_found`. Member lookups are never fault-flagged.

### `GET /members/{member_id}/cards`

**200**: the member's cards (can be `[]`):
```json
[{"card_id": "CARD-4001", "member_id": "M-1001", "account_id": "ACC-2001", "type": "debit", "last_four": "4471", "status": "active"}]
```
- `type`: `debit` | `credit`. `status`: `active` | `frozen` | `lost`.
- `account_id` is the core-banking account the card draws on.

**404** `not_found`. **500 / malformed / slow**: see "Fixture-flagged members".

### `GET /cards/{card_id}/limits`

*Added 2026-09-28 (for harbor-mcp 0.2.0, the discovery demo).*

**200**: the card's own daily limits, money as 2-decimal strings:
```json
{"card_id": "CARD-4001", "atm_daily_limit": "800.00", "purchase_daily_limit": "5000.00", "currency": "USD", "updated_on": "2026-06-14"}
```
Harbor's standard is $500 ATM / $3,000 purchases. `CARD-4001` carries a
raised limit on purpose. **404** `not_found`. Never fixture-faulted.

### `POST /cards/{card_id}/freeze`

The **only endpoint that changes data.**

Request body: `{"reason": "<1-500 chars>"}` (required).

| Status | When | Body |
|---|---|---|
| **200** | frozen now, **or it was already frozen** (idempotent: no change, same response) | the card, `status: "frozen"` |
| **404** `not_found` | no such card | error envelope |
| **409** `conflict` | the card is `lost`. It's already permanently blocked; freezing would replace that with a reversible status. | error envelope |
| **422** | `reason` missing or empty | FastAPI's validation body |

## Error envelope

Every non-2xx response (except 422 and the malformed-body fault):
```json
{"error": "<code>", "message": "<detail>"}
```
Codes: `unauthorized` (401), `not_found` (404), `conflict` (409),
`server_error` (500), `invalid_fault_header` (400).

## Fault injection — two mechanisms (from week 1)

### 1. Header override — `X-Simulate-Fault: 500 | timeout | malformed`

Works on every domain endpoint (after the key check), before any fixture
lookup, so it fires even for an ID that doesn't exist. For tests. An
unknown value → `400 invalid_fault_header`.

### 2. Fixture-flagged members

These members' **card listing** (`GET /members/{id}/cards`) misbehaves by
default. Their member lookup is always normal.

| Member | Fault | Behaviour |
|---|---|---|
| `M-1003` Priya Natarajan | `server_error` | Every request → `500`. |
| `M-1004` Sam Okafor | `timeout` | Sleeps `MOCK_CRM_TIMEOUT_SLEEP_SECONDS` (default 5 s) before answering; the caller's timeout is meant to fire first. |
| `M-1005` Elena Petrova | `malformed` | `200` with a body that isn't valid JSON. |
| `M-1006` Jordan Blake | `fail_then_recover` | 1st and 2nd request → `500`; 3rd → normal. Repeats every 3. |

### Other fixtures worth knowing

- `M-1002` has a second card, `CARD-4008`, with status `lost`: freezing
  it is the `409` case.
- `CARD-4006` (M-1005) starts `frozen`: freezing it is the idempotent case.
- Known missing: `M-9999`, `CARD-9999` → `404`.

### Malformed body — no distinct status code

The malformed fault returns **200**. A caller must parse and validate the
body; the status code alone doesn't reveal the problem.
