# Mock CRM — Contract

A real HTTP service (FastAPI), not an in-process stub — run it standalone
and talk to it over HTTP exactly as the tool layer does:

```bash
cd labs/week1_day4
source .venv/bin/activate
uvicorn app:app --app-dir mock_crm --port 8000
```

(`--app-dir mock_crm` matters: `app.py` imports its sibling modules as
plain `import fixtures` / `from schemas import ...`, which only resolve
if `mock_crm/` itself is on `sys.path` -- `--app-dir` does exactly that.
`uvicorn mock_crm.app:app` without it fails with `ModuleNotFoundError:
No module named 'fixtures'`.)

Base URL for everything below: `http://localhost:8000`. This document is
the contract — if `mock_crm/app.py`'s behavior ever disagrees with what's
written here, that's a bug in `app.py`, not a doc that needs updating to
match it.

## Operational endpoints (not part of the CRM's business contract)

`GET /health` → `200 {"status": "ok"}`. For confirming the process is up;
not something a real CRM's contract would include, so the tool layer
should never call it as part of answering a customer question.

## Domain endpoints

### `GET /customers/{customer_id}`

**200** — customer found:
```json
{"customer_id": "CUST-1001", "name": "Maria Chen", "email": "maria.chen@example.com", "since_date": "2019-03-11"}
```

**404** — no such customer:
```json
{"error": "not_found", "message": "No customer found with id 'CUST-9999'."}
```

Customer lookups are never fault-flagged (see "Fixture-flagged faults"
below for why) — the only failure mode on this endpoint, besides a header
override, is 404.

### `GET /customers/{customer_id}/accounts`

**200** — list of that customer's accounts (see `AccountOut` shape
below); can be an empty list in principle, though every fixture customer
has at least one account.
```json
[{"account_id": "ACC-2001", "customer_id": "CUST-1001", "type": "checking", "balance": 4210.55, "status": "active"}]
```

**404** — no such customer (same envelope as above).

This endpoint never applies an individual account's `simulated_fault` —
listing an account is not the same call as fetching its detail, and only
the detail call is flaky. A fault-flagged account still appears in this
list.

### `GET /accounts/{account_id}`

**200** — `AccountOut`:
```json
{"account_id": "ACC-2001", "customer_id": "CUST-1001", "type": "checking", "balance": 4210.55, "status": "active"}
```
`type` is one of `checking` / `savings` / `credit`. `status` is one of
`active` / `frozen` / `closed`.

**404** — no such account (`{"error": "not_found", "message": "..."}`).

**500 / malformed body / slow response** — see "Fixture-flagged faults."

### `GET /accounts/{account_id}/transactions?limit=n`

`limit` is optional, default 20, range 1–100.

**200** — list of transactions, newest first, truncated to `limit`. Can
legitimately be `[]` for an account that exists but has no transaction
history — **this is not the same thing as 404** and must be handled as a
distinct case: the account was found, it simply has nothing to report.
```json
[{"transaction_id": "TXN-3001", "account_id": "ACC-2001", "date": "2026-09-10", "amount": -42.10, "description": "Green Leaf Grocery", "category": "groceries"}]
```
`amount` is signed: negative = money out, positive = money in.

**404** — no such account.

### `GET /accounts/{account_id}/cards`

**200** — list of cards on the account (can be empty).
```json
[{"card_id": "CARD-4001", "account_id": "ACC-2001", "last_four": "4471", "status": "active"}]
```
`status` is one of `active` / `frozen` / `lost`.

**404** — no such account.

## Error envelope

Every non-2xx response (that isn't the malformed-body fault) uses this
shape:
```json
{"error": "<short machine-readable code>", "message": "<human-readable detail>"}
```
`error` values in use: `not_found` (404), `server_error` (500),
`invalid_fault_header` (400 — malformed use of the fault-injection header
itself, not one of the four simulated fault classes).

## Fault injection — two independent mechanisms

### 1. Header override — `X-Simulate-Fault: 500 | timeout | malformed`

Works on **every** endpoint above, and is checked **before** any fixture
lookup — it fires even for a customer/account ID that doesn't exist.
Intended for pytest: it's how the tool layer's test suite exercises every
failure branch against every route without needing dedicated fixture
data for each combination. An unrecognized header value returns `400
{"error": "invalid_fault_header", ...}`.

There is no header value for `fail_then_recover` — that fault needs
state that persists across repeated requests to the *same* resource,
which a single stateless header can't express. It's reachable only
through mechanism 2.

### 2. Fixture-flagged accounts

Specific, documented account IDs misbehave by default, with no header
needed — this is what makes the fault-injection **demo** deliverable
possible through an ordinary conversation instead of curl commands:

| Account ID | Customer | Fault | Behavior |
|---|---|---|---|
| `ACC-2004` | CUST-1003 Priya Natarajan | `server_error` | Every request → `500`. |
| `ACC-2005` | CUST-1004 Sam Okafor | `timeout` | Sleeps past any reasonable client timeout, then would return normal data — the point is the caller gives up first, not that the server errors. |
| `ACC-2006` | CUST-1005 Elena Petrova | `malformed` | `200` with a body that isn't even valid JSON (truncated mid-object). |
| `ACC-2007` | CUST-1006 Jordan Blake | `fail_then_recover` | 1st and 2nd request to this account → `500`; 3rd request → succeeds normally. Repeats every 3 requests. This is the only fixture that proves a retry policy's *success* path — every other fault always fails, which only proves graceful exhaustion. |

Fault flags live on **account** records only, never on customer records
— see `fixtures.py`'s module docstring. Every documented customer ID
resolves normally at `GET /customers/{id}`; it's specific accounts that
are unreliable. This roughly mirrors how a real bank's systems are often
split (identity/customer data in a more stable system than the
account/ledger data behind it), and it's called out explicitly in
`design_doc.md`'s assumptions section as something that may not hold
against a real CRM.

### Known-missing IDs (404, no flag needed)

`CUST-9999` and `ACC-9999` are absent from every fixture table on
purpose — any ID not listed above 404s the same way, these two are just
the documented, reproducible ones to use in the demo run.

### Malformed body — no distinct status code

Worth stating plainly since it's easy to miss: the malformed-body fault
returns **`200`**, not an error status. The only sign anything is wrong
is the body itself failing to parse. **The tool layer cannot rely on
`response.status_code` alone** — it must also attempt to parse/validate
the body, and treat a parse failure as its own outcome.

### Timeout sleep duration is configurable for tests

The `timeout` fault sleeps for `MOCK_CRM_TIMEOUT_SLEEP_SECONDS` seconds
(env var), defaulting to 5.0 when unset. pytest sets this to a small
value (e.g. `0.05`) and configures the tool layer's own client timeout
even smaller, so the timeout test suite runs in milliseconds instead of
waiting out a realistic delay — see `tests/test_tool_client.py`.
