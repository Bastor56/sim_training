"""Tool layer: the HTTP client wrapping the mock CRM.

Owns timeouts, the retry policy, and error translation -- converts HTTP
reality (status codes, connection failures, malformed bodies) into the
small closed set of outcomes the rest of the agent reasons about: found,
not_found, unavailable (see ToolOutcome). This is the boundary
mock_crm/contract.md calls out as "the entire reason the real CRM can be
dropped in later without touching the agent" -- everything above this
module only ever sees a ToolOutcome, never a status code or an
httpx exception.

Retry is hand-rolled here, deliberately not delegated to LangGraph's
RetryPolicy the way day 3's executor_node did. Day 3's tradeoffs.md
documented a real cost of that choice: RetryPolicy's sleep is hardcoded
to time.sleep inside langgraph's own code, so tests can only shrink the
policy's *parameters*, never inject a fake sleep and test the exact
production backoff curve at full speed. Keeping retry inside this client
-- with an injectable `sleep`, exactly like day 2's execute_tool -- means
this lab doesn't inherit that limitation, and it keeps the retry loop
where the lab's own architecture says it belongs: "the only loop-back is
the retry inside the tool layer," invisible to the graph, which only
ever sees this client make one call and get one ToolOutcome back.

Deliberately does NOT import anything from mock_crm/ -- the _*Shape
models below are this client's own expectation of what a CRM response
looks like, restated independently of mock_crm/schemas.py. Importing the
mock's schema module directly would quietly make the tool layer depend
on the mock's implementation, which is exactly what "swapping in the
real CRM is a configuration change, not a rewrite" rules out.
"""

from __future__ import annotations

import random
import sys
import time
from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Type

import httpx
from pydantic import BaseModel, ValidationError

MAX_ATTEMPTS = 3
BASE_DELAY_SECONDS = 0.5
DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_TIMEOUT_SECONDS = 2.0


def backoff_delay(attempt: int) -> float:
    """attempt is 0-indexed. Same curve as day 2's executor.backoff_delay:
    0 -> ~0.5-1.0s, 1 -> ~1.0-1.5s, 2 -> ~2.0-2.5s."""
    return BASE_DELAY_SECONDS * (2**attempt) + random.uniform(0, BASE_DELAY_SECONDS)


def build_http_client(base_url: str = DEFAULT_BASE_URL, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> httpx.Client:
    """Production client: real sockets, real timeouts. Tests build their
    own httpx.Client on an ASGI transport instead -- see
    tests/test_tool_client.py."""
    return httpx.Client(base_url=base_url, timeout=timeout_seconds)


@dataclass
class ToolOutcome:
    """The closed outcome set the decision/response layers reason about.

    status: "found" | "not_found" | "unavailable".
    data: parsed, shape-validated response body, only set when found. An
        empty list is still "found" -- see contract.md's "found, but
        empty" case; it is never confused with not_found here.
    detail: short, human-readable reason, always set for not_found and
        unavailable, so the response layer can explain a failure without
        inventing wording of its own.
    """

    status: str
    data: Optional[Any] = None
    detail: Optional[str] = None


# This client's own expectation of each response shape -- see module
# docstring for why these are not imported from mock_crm/schemas.py.
class _CustomerShape(BaseModel):
    customer_id: str
    name: str
    email: str
    since_date: str


class _AccountShape(BaseModel):
    account_id: str
    customer_id: str
    type: str
    balance: float
    status: str


class _TransactionShape(BaseModel):
    transaction_id: str
    account_id: str
    date: str
    amount: float
    description: str
    category: str


class _CardShape(BaseModel):
    card_id: str
    account_id: str
    last_four: str
    status: str


class CRMClient:
    def __init__(
        self,
        http_client: httpx.Client,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._http = http_client
        self._sleep = sleep

    def get_customer(self, customer_id: str) -> ToolOutcome:
        return self._request("GET", f"/customers/{customer_id}", _CustomerShape)

    def list_customer_accounts(self, customer_id: str) -> ToolOutcome:
        return self._request("GET", f"/customers/{customer_id}/accounts", _AccountShape, many=True)

    def get_account(self, account_id: str) -> ToolOutcome:
        return self._request("GET", f"/accounts/{account_id}", _AccountShape)

    def list_account_transactions(self, account_id: str, limit: int = 20) -> ToolOutcome:
        return self._request(
            "GET",
            f"/accounts/{account_id}/transactions",
            _TransactionShape,
            many=True,
            params={"limit": limit},
        )

    def list_account_cards(self, account_id: str) -> ToolOutcome:
        return self._request("GET", f"/accounts/{account_id}/cards", _CardShape, many=True)

    # -- internals --------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        shape: Type[BaseModel],
        many: bool = False,
        params: Optional[dict] = None,
    ) -> ToolOutcome:
        last_detail = "exhausted retries with no successful response"

        for attempt in range(MAX_ATTEMPTS):
            try:
                response = self._http.request(method, path, params=params)
            except httpx.TimeoutException:
                last_detail = f"the CRM did not respond in time calling {method} {path}"
                if self._wait_for_retry(attempt, last_detail):
                    continue
                return ToolOutcome(status="unavailable", detail=last_detail)
            except httpx.HTTPError as exc:
                last_detail = f"could not reach the CRM calling {method} {path} ({exc.__class__.__name__})"
                if self._wait_for_retry(attempt, last_detail):
                    continue
                return ToolOutcome(status="unavailable", detail=last_detail)

            if response.status_code == 404:
                # Not retryable: the record doesn't exist, and it won't
                # start existing on a second attempt.
                return ToolOutcome(
                    status="not_found",
                    detail=self._error_detail(response, default="the requested record was not found"),
                )

            if response.status_code >= 500:
                last_detail = self._error_detail(
                    response, default=f"the CRM returned HTTP {response.status_code} for {method} {path}"
                )
                if self._wait_for_retry(attempt, last_detail):
                    continue
                return ToolOutcome(status="unavailable", detail=last_detail)

            if response.status_code >= 400:
                # An unexpected client-side rejection (e.g. a bad request
                # this client itself sent). Not the CRM being flaky, and
                # not something a retry fixes.
                return ToolOutcome(
                    status="unavailable",
                    detail=self._error_detail(
                        response, default=f"the CRM rejected the request (HTTP {response.status_code})"
                    ),
                )

            return self._validate_success(response, shape, many)

        return ToolOutcome(status="unavailable", detail=last_detail)

    def _validate_success(self, response: httpx.Response, shape: Type[BaseModel], many: bool) -> ToolOutcome:
        try:
            raw = response.json()
        except ValueError:
            # Not retryable: the malformed-body fault is a permanent
            # schema violation, not a transient blip -- see contract.md.
            return ToolOutcome(
                status="unavailable",
                detail="the CRM returned a response that could not be parsed as JSON",
            )

        try:
            if many:
                items: List[BaseModel] = [shape.model_validate(item) for item in raw]
                data: Any = [item.model_dump() for item in items]
            else:
                data = shape.model_validate(raw).model_dump()
        except ValidationError:
            # Also not retryable: valid JSON that doesn't match the
            # documented contract is the same permanent-violation case as
            # unparseable JSON, just caught one step later.
            return ToolOutcome(
                status="unavailable",
                detail="the CRM returned a response that didn't match the documented contract",
            )

        return ToolOutcome(status="found", data=data)

    def _wait_for_retry(self, attempt: int, reason: str) -> bool:
        """True (and sleeps) if another attempt remains; False (no sleep)
        if this was the last one."""
        if attempt >= MAX_ATTEMPTS - 1:
            return False
        delay = backoff_delay(attempt)
        print(
            f"[retry] attempt {attempt + 1}/{MAX_ATTEMPTS} failed: {reason} -- backing off {delay:.2f}s",
            file=sys.stderr,
        )
        self._sleep(delay)
        return True

    @staticmethod
    def _error_detail(response: httpx.Response, default: str) -> str:
        try:
            body = response.json()
        except ValueError:
            return default
        if isinstance(body, dict) and "message" in body:
            return str(body["message"])
        return default
