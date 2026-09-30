"""Harbor mock CRM -- a real FastAPI HTTP service, not an in-process stub.

Copied from week 1 (labs/week1_day4/mock_crm) and changed for Day 3:
  - Harbor members and cards; accounts/transactions moved to core banking.
  - Every endpoint except /health demands an X-API-Key. Only the harbor-mcp
    server holds that key (spec.md "Backend credentials").
  - POST /cards/{card_id}/freeze: the one endpoint that changes something.

Run it (from labs/week2_day3) with scripts/run_crm.py, which hands this
process ONLY the CRM key from mcp_server/.env. Or directly:
    CRM_API_KEY=... uvicorn app:app --app-dir backends/mock_crm --port 8100

contract.md is the source of truth; if this file disagrees with it, this
file has the bug.

Fault injection is week 1's, with two mechanisms (contract.md):
  1. `X-Simulate-Fault: 500|timeout|malformed` forces a fault on any
     authenticated request, before any fixture lookup.
  2. Fixture-flagged members (M-1003..M-1006) fault on card listing.
The API key is checked BEFORE either: an unauthenticated caller can't
trigger anything, not even a simulated fault.
"""

import hmac
import os
import time
from typing import Optional

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse, Response

import fixtures
from schemas import ErrorEnvelope, FreezeRequest, MemberOut

# Fail closed: a CRM started without a key must not serve unauthenticated.
_API_KEY = os.environ.get("CRM_API_KEY", "")
if not _API_KEY:
    raise RuntimeError("CRM_API_KEY is not set; refusing to start without an API key")

app = FastAPI(title="Harbor Mock CRM", version="2.0.0")

# Paths that don't need the key: operational only, never business data.
_OPEN_PATHS = {"/health"}

# Header values -> internal fault names. "fail_then_recover" is reachable
# only through a flagged fixture (it needs a per-member attempt counter).
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


@app.middleware("http")
async def require_api_key(request: Request, call_next):
    if request.url.path in _OPEN_PATHS:
        return await call_next(request)
    supplied = request.headers.get("X-API-Key", "")
    # compare_digest: takes the same time whether the first or last
    # character is wrong, so the key can't be guessed one character at a time.
    if not hmac.compare_digest(supplied.encode(), _API_KEY.encode()):
        return _error_response("unauthorized", "Missing or invalid X-API-Key.", 401)
    return await call_next(request)


def _malformed_response() -> Response:
    """A 200 whose body is not even valid JSON -- truncated mid-object.
    The caller can't rely on the status code alone (contract.md)."""
    broken_body = '[{"card_id": "CARD-0000", "status": "act'
    return Response(content=broken_body, media_type="application/json", status_code=200)


def _sleep_for_timeout_fault() -> None:
    seconds = float(os.environ.get("MOCK_CRM_TIMEOUT_SLEEP_SECONDS", fixtures.TIMEOUT_SLEEP_SECONDS_DEFAULT))
    time.sleep(seconds)


def _apply_fault(fault: str, resource_id: str) -> Optional[Response]:
    """Executes one fault. Returns the Response to send now, or None to fall
    through to the normal response (timeout falls through after sleeping;
    fail_then_recover falls through on every 3rd attempt)."""
    if fault == "server_error":
        return _error_response("server_error",
                               f"The CRM backend encountered an internal error processing '{resource_id}'.", 500)
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
                f"The CRM backend encountered an internal error processing '{resource_id}' (attempt {attempt}).", 500)
        return None
    raise AssertionError(f"unhandled simulated fault type: {fault!r}")


def _forced_fault_response(header_value: Optional[str], resource_id: str) -> Optional[Response]:
    if header_value is None:
        return None
    if header_value not in _HEADER_FAULT_MAP:
        return _error_response("invalid_fault_header",
                               f"X-Simulate-Fault must be one of 500, timeout, malformed; got '{header_value}'.", 400)
    return _apply_fault(_HEADER_FAULT_MAP[header_value], resource_id)


@app.get("/health")
def health() -> dict:
    """Operational, not part of the business contract; needs no key."""
    return {"status": "ok"}


@app.post("/admin/reset")
def admin_reset() -> dict:
    """Operational: restore fixtures (cards unfrozen, fault counters cleared)
    between demo runs. Needs the key like everything else."""
    fixtures.reset()
    return {"status": "reset"}


@app.get("/members/{member_id}")
def get_member(member_id: str, x_simulate_fault: Optional[str] = Header(None, alias="X-Simulate-Fault")):
    forced = _forced_fault_response(x_simulate_fault, member_id)
    if forced is not None:
        return forced
    member = fixtures.MEMBERS.get(member_id)
    if member is None:
        return _error_response("not_found", f"No member found with id '{member_id}'.", 404)
    # Member lookups never apply the member's fault flag (fixtures.py).
    return _json_response(MemberOut(**member.model_dump(exclude={"simulated_fault"})))


@app.get("/members/{member_id}/cards")
def list_member_cards(member_id: str, x_simulate_fault: Optional[str] = Header(None, alias="X-Simulate-Fault")):
    forced = _forced_fault_response(x_simulate_fault, member_id)
    if forced is not None:
        return forced
    member = fixtures.MEMBERS.get(member_id)
    if member is None:
        return _error_response("not_found", f"No member found with id '{member_id}'.", 404)
    if member.simulated_fault is not None:
        forced = _apply_fault(member.simulated_fault, member_id)
        if forced is not None:
            return forced
    return _json_response(fixtures.cards_for_member(member_id))


@app.get("/cards/{card_id}/limits")
def get_card_limits(card_id: str, x_simulate_fault: Optional[str] = Header(None, alias="X-Simulate-Fault")):
    forced = _forced_fault_response(x_simulate_fault, card_id)
    if forced is not None:
        return forced
    limits = fixtures.CARD_LIMITS.get(card_id)
    if limits is None:
        return _error_response("not_found", f"No card found with id '{card_id}'.", 404)
    return _json_response(limits)


@app.post("/cards/{card_id}/freeze")
def freeze_card(card_id: str, body: FreezeRequest,
                x_simulate_fault: Optional[str] = Header(None, alias="X-Simulate-Fault")):
    forced = _forced_fault_response(x_simulate_fault, card_id)
    if forced is not None:
        return forced
    card = fixtures.CARDS.get(card_id)
    if card is None:
        return _error_response("not_found", f"No card found with id '{card_id}'.", 404)
    if card.status == "lost":
        # A lost card is already blocked permanently; "freezing" it would
        # hide that status behind a reversible one.
        return _error_response("conflict", f"Card '{card_id}' is already reported lost and cannot be frozen.", 409)
    # Idempotent: freezing a frozen card is a 200 with no change.
    card.status = "frozen"
    return _json_response(card)
