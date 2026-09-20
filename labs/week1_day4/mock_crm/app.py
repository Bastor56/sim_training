"""Mock CRM -- a real FastAPI HTTP service, not an in-process stub.

Run it standalone with (from labs/week1_day4):
    uvicorn app:app --app-dir mock_crm --port 8000

--app-dir matters: this module's `import fixtures` / `from schemas
import ...` below are plain sibling imports, which only resolve if
mock_crm/ itself is on sys.path -- see contract.md.

Endpoints and their documented contract live in contract.md; this module
is the implementation of that contract, not the source of truth for it --
if the two ever disagree, contract.md is what a client integrator (or
day 4's own tool layer) is allowed to assume, and this file is what has
the bug.

Two independent fault-injection mechanisms, both explained in full in
contract.md:
  1. The `X-Simulate-Fault: 500|timeout|malformed` header forces a fault
     on ANY request to ANY endpoint, even for an account/customer ID that
     doesn't exist -- it's checked before any fixture lookup. Used by
     pytest to exhaustively cover every failure branch against every
     route.
  2. Specific, documented account IDs (see fixtures.py) carry a
     `simulated_fault` flag baked into their fixture record, so the
     fault-injection *demo* deliverable can happen through a natural
     conversation ("what's the balance on ACC-2004?") instead of a
     header a chat user would never send.
"""

import os
import time
from typing import List, Optional

from fastapi import FastAPI, Header, Query
from fastapi.responses import JSONResponse, Response

import fixtures
from schemas import AccountOut, Card, ErrorEnvelope, Transaction

app = FastAPI(title="Mock CRM", version="1.0.0")

# Maps the header's documented values to the internal fault names used by
# fixtures.py. "fail_then_recover" is deliberately absent here -- it's
# reachable only through a flagged fixture record, never forced via
# header, because "fails twice then recovers" needs the persistent
# per-resource attempt counter fixtures.next_fault_attempt() keeps, and a
# header is a single stateless request.
_HEADER_FAULT_MAP = {
    "500": "server_error",
    "timeout": "timeout",
    "malformed": "malformed",
}


def _json_response(data, status_code: int = 200) -> JSONResponse:
    if isinstance(data, list):
        payload = [item.model_dump(mode="json") for item in data]
    else:
        payload = data.model_dump(mode="json")
    return JSONResponse(content=payload, status_code=status_code)


def _error_response(error: str, message: str, status_code: int) -> JSONResponse:
    return _json_response(ErrorEnvelope(error=error, message=message), status_code=status_code)


def _malformed_response() -> Response:
    """A 200 whose body is not even valid JSON -- truncated mid-object.

    Malformed-body faults are NOT signaled by status code (see
    contract.md); this is what a caller actually receives when one
    fires, and it's why the tool layer can't rely on checking
    response.status_code alone."""
    broken_body = '{"account_id": "ACC-0000", "balance": 104'
    return Response(content=broken_body, media_type="application/json", status_code=200)


def _sleep_for_timeout_fault() -> None:
    seconds = float(os.environ.get("MOCK_CRM_TIMEOUT_SLEEP_SECONDS", fixtures.TIMEOUT_SLEEP_SECONDS_DEFAULT))
    time.sleep(seconds)


def _apply_fault(fault: str, resource_id: str) -> Optional[Response]:
    """Executes one fault. Returns the Response to send immediately, or
    None to mean "fall through to the normal response" -- the timeout
    fault falls through after sleeping (the mock isn't broken, just
    slow; it's the caller's own client-side timeout that fires first in
    practice), and fail_then_recover falls through once its counter
    reaches a multiple of 3."""
    if fault == "server_error":
        return _error_response(
            "server_error",
            f"The CRM backend encountered an internal error processing '{resource_id}'.",
            500,
        )
    if fault == "timeout":
        _sleep_for_timeout_fault()
        return None
    if fault == "malformed":
        return _malformed_response()
    if fault == "fail_then_recover":
        attempt = fixtures.next_fault_attempt(resource_id)
        if attempt % 3 != 0:
            return _error_response(
                "server_error",
                f"The CRM backend encountered an internal error processing '{resource_id}' (attempt {attempt}).",
                500,
            )
        return None
    raise AssertionError(f"unhandled simulated fault type: {fault!r}")


def _forced_fault_response(header_value: Optional[str], resource_id: str) -> Optional[Response]:
    """Checked first, before any fixture lookup -- this is what lets the
    header force a fault on an ID that doesn't exist in fixtures at all."""
    if header_value is None:
        return None
    if header_value not in _HEADER_FAULT_MAP:
        return _error_response(
            "invalid_fault_header",
            f"X-Simulate-Fault must be one of 500, timeout, malformed; got '{header_value}'.",
            400,
        )
    return _apply_fault(_HEADER_FAULT_MAP[header_value], resource_id)


def _fixture_fault_response(fault: Optional[str], resource_id: str) -> Optional[Response]:
    if fault is None:
        return None
    return _apply_fault(fault, resource_id)


@app.get("/health")
def health() -> dict:
    """Operational endpoint, not part of the CRM's documented business
    contract -- see contract.md."""
    return {"status": "ok"}


@app.get("/customers/{customer_id}")
def get_customer(
    customer_id: str,
    x_simulate_fault: Optional[str] = Header(None, alias="X-Simulate-Fault"),
):
    forced = _forced_fault_response(x_simulate_fault, customer_id)
    if forced is not None:
        return forced

    customer = fixtures.CUSTOMERS.get(customer_id)
    if customer is None:
        return _error_response("not_found", f"No customer found with id '{customer_id}'.", 404)

    # Customers are never fault-flagged -- see fixtures.py's module
    # docstring for why.
    return _json_response(customer)


@app.get("/customers/{customer_id}/accounts")
def list_customer_accounts(
    customer_id: str,
    x_simulate_fault: Optional[str] = Header(None, alias="X-Simulate-Fault"),
):
    forced = _forced_fault_response(x_simulate_fault, customer_id)
    if forced is not None:
        return forced

    customer = fixtures.CUSTOMERS.get(customer_id)
    if customer is None:
        return _error_response("not_found", f"No customer found with id '{customer_id}'.", 404)

    account_ids = fixtures.CUSTOMER_ACCOUNTS.get(customer_id, [])
    # Listing never applies an individual account's own fault flag -- see
    # fixtures.py: it's account *detail* lookups that are flaky, not the
    # account index. A fault-flagged account still shows up here.
    accounts_out: List[AccountOut] = [
        AccountOut(**fixtures.ACCOUNTS[account_id].model_dump(exclude={"simulated_fault"}))
        for account_id in account_ids
    ]
    return _json_response(accounts_out)


@app.get("/accounts/{account_id}")
def get_account(
    account_id: str,
    x_simulate_fault: Optional[str] = Header(None, alias="X-Simulate-Fault"),
):
    forced = _forced_fault_response(x_simulate_fault, account_id)
    if forced is not None:
        return forced

    account = fixtures.ACCOUNTS.get(account_id)
    if account is None:
        return _error_response("not_found", f"No account found with id '{account_id}'.", 404)

    forced = _fixture_fault_response(account.simulated_fault, account_id)
    if forced is not None:
        return forced

    return _json_response(AccountOut(**account.model_dump(exclude={"simulated_fault"})))


@app.get("/accounts/{account_id}/transactions")
def list_account_transactions(
    account_id: str,
    limit: int = Query(20, ge=1, le=100),
    x_simulate_fault: Optional[str] = Header(None, alias="X-Simulate-Fault"),
):
    forced = _forced_fault_response(x_simulate_fault, account_id)
    if forced is not None:
        return forced

    account = fixtures.ACCOUNTS.get(account_id)
    if account is None:
        return _error_response("not_found", f"No account found with id '{account_id}'.", 404)

    forced = _fixture_fault_response(account.simulated_fault, account_id)
    if forced is not None:
        return forced

    transactions: List[Transaction] = fixtures.TRANSACTIONS.get(account_id, [])[:limit]
    return _json_response(transactions)


@app.get("/accounts/{account_id}/cards")
def list_account_cards(
    account_id: str,
    x_simulate_fault: Optional[str] = Header(None, alias="X-Simulate-Fault"),
):
    forced = _forced_fault_response(x_simulate_fault, account_id)
    if forced is not None:
        return forced

    account = fixtures.ACCOUNTS.get(account_id)
    if account is None:
        return _error_response("not_found", f"No account found with id '{account_id}'.", 404)

    forced = _fixture_fault_response(account.simulated_fault, account_id)
    if forced is not None:
        return forced

    cards: List[Card] = fixtures.CARDS.get(account_id, [])
    return _json_response(cards)
