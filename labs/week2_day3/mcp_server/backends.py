"""Clients for the systems of record, owned by the server (spec.md "Failure modes").

This is where backend credentials are used, and the only place: the CRM
API key goes into a header here, and the database password into a
connection here. Nothing in this module's results or errors echoes them.

Every failure is translated into the closed outcome set (outcomes.py)
with a message that is safe to show a client: no URLs, hosts, status
codes or stack traces.

The CRM client keeps week 1's policy (labs/week1_day4/src/tool_client.py):
explicit timeout, 3 attempts with exponential backoff on 5xx / timeout /
connection errors / malformed bodies, no retry on 4xx. The sleep is
injectable so tests run the real policy at full speed.
"""

from __future__ import annotations

import random
import time
from datetime import date
from decimal import Decimal
from typing import Any, Callable

import httpx
import psycopg
import psycopg.conninfo
from psycopg.rows import dict_row
from pydantic import BaseModel, ValidationError

from .outcomes import CONFLICT, NOT_FOUND, UNAVAILABLE, ToolFailure

MAX_ATTEMPTS = 3
BASE_DELAY_SECONDS = 0.5
CRM_TIMEOUT_SECONDS = 2.0


def backoff_delay(attempt: int) -> float:
    """attempt is 0-indexed: ~0.5-1.0 s, then ~1.0-1.5 s."""
    return BASE_DELAY_SECONDS * (2 ** attempt) + random.uniform(0, BASE_DELAY_SECONDS)


# The server's own expectation of each CRM response shape, restated rather
# than imported from backends/mock_crm/schemas.py: importing the mock's
# models would make the server depend on the mock, and the mock is what
# gets swapped for Harbor's real CRM.
class _MemberShape(BaseModel):
    member_id: str
    name: str
    email: str
    member_since: str


class _Retryable(Exception):
    pass


class CRMClient:
    system = "harbor_crm"

    def __init__(self, http: httpx.Client, sleep: Callable[[float], None] = time.sleep):
        self._http = http
        self._sleep = sleep

    @classmethod
    def from_config(cls, base_url: str, api_key: str) -> "CRMClient":
        return cls(httpx.Client(base_url=base_url, timeout=CRM_TIMEOUT_SECONDS,
                                headers={"X-API-Key": api_key}))

    def _request(self, method: str, path: str, what: str, json: dict | None = None) -> Any:
        """One logical call, with retries. Returns the parsed JSON body, or raises ToolFailure."""
        for attempt in range(MAX_ATTEMPTS):
            try:
                response = self._http.request(method, path, json=json)
                if response.status_code == 404:
                    raise ToolFailure(NOT_FOUND, f"No {what}.")
                if response.status_code == 409:
                    raise ToolFailure(CONFLICT, response.json().get("message", f"Conflict on {what}."))
                if response.status_code in (401, 403):
                    # Our own key was refused: a server misconfiguration, not the caller's fault.
                    # Not retried. The client learns only that the CRM is unavailable.
                    raise ToolFailure(UNAVAILABLE, "The CRM is unavailable right now.")
                if response.status_code >= 500:
                    raise _Retryable()
                response.raise_for_status()
                try:
                    return response.json()
                except ValueError:
                    raise _Retryable() from None  # malformed body: 200 with broken JSON
            except (_Retryable, httpx.TimeoutException, httpx.TransportError):
                if attempt + 1 < MAX_ATTEMPTS:
                    self._sleep(backoff_delay(attempt))
        raise ToolFailure(UNAVAILABLE, "The CRM is unavailable right now.")

    @staticmethod
    def _shape(model: type[BaseModel], body: Any) -> dict:
        try:
            return model.model_validate(body).model_dump()
        except ValidationError:
            raise ToolFailure(UNAVAILABLE, "The CRM returned data in an unexpected format.") from None

    def get_member(self, member_id: str) -> dict:
        body = self._request("GET", f"/members/{member_id}", what=f"member {member_id}")
        return self._shape(_MemberShape, body)

    def list_cards(self, member_id: str) -> list[dict]:
        body = self._request("GET", f"/members/{member_id}/cards", what=f"member {member_id}")
        if not isinstance(body, list):
            raise ToolFailure(UNAVAILABLE, "The CRM returned data in an unexpected format.")
        return [self._shape(_CardShape, c) for c in body]

    def get_card_limits(self, card_id: str) -> dict:
        body = self._request("GET", f"/cards/{card_id}/limits", what=f"card {card_id}")
        return self._shape(_CardLimitsShape, body)

    def freeze_card(self, card_id: str, reason: str) -> dict:
        # POST is retried like a GET only because the CRM's freeze is
        # idempotent (contract.md): repeating it can't freeze twice.
        body = self._request("POST", f"/cards/{card_id}/freeze", what=f"card {card_id}", json={"reason": reason})
        return self._shape(_CardShape, body)


class _CardShape(BaseModel):
    card_id: str
    member_id: str
    account_id: str
    type: str
    last_four: str
    status: str


class _CardLimitsShape(BaseModel):
    card_id: str
    atm_daily_limit: str
    purchase_daily_limit: str
    currency: str
    updated_on: str


# ---------------------------------------------------------------- core banking (Postgres)

class CoreBanking:
    """Read-only access to harbor_core as the harbor_mcp role (supabase migration
    20260928120000). The role can't write, so even a bug here can't change a
    balance. Queries are parameterised: an argument is never pasted into SQL.

    One short connection per call: simple, thread-safe (tools run in worker
    threads), and fast enough locally. A pool is the production change."""

    system = "harbor_core_banking"

    def __init__(self, conninfo: str, connect: Callable[..., Any] | None = None):
        self._conninfo = conninfo
        self._connect = connect or psycopg.connect

    @classmethod
    def from_config(cls, host: str, port: int, dbname: str, user: str, password: str) -> "CoreBanking":
        return cls(psycopg.conninfo.make_conninfo(host=host, port=port, dbname=dbname, user=user,
                                                  password=password, connect_timeout=3,
                                                  application_name="harbor-mcp"))

    def _query(self, sql: str, params: tuple) -> list[dict]:
        try:
            with self._connect(self._conninfo, row_factory=dict_row) as conn:
                return conn.execute(sql, params).fetchall()
        except psycopg.OperationalError:
            # Down, unreachable, bad credentials, or the 5 s statement timeout.
            raise ToolFailure(UNAVAILABLE, "Core banking is unavailable right now.") from None

    @staticmethod
    def _plain(row: dict) -> dict:
        """Money as a 2-decimal string (never a float: 0.1 + 0.2 != 0.3), dates as ISO."""
        return {k: (f"{v:.2f}" if isinstance(v, Decimal) else v.isoformat() if isinstance(v, date) else v)
                for k, v in row.items()}

    def list_member_accounts(self, member_id: str) -> list[dict]:
        rows = self._query(
            "select account_id, member_id, type, balance, status, opened_on "
            "from harbor_core.accounts where member_id = %s order by account_id", (member_id,))
        return [self._plain(r) for r in rows]

    def get_account(self, account_id: str) -> dict:
        rows = self._query(
            "select account_id, member_id, type, balance, status, opened_on "
            "from harbor_core.accounts where account_id = %s", (account_id,))
        if not rows:
            raise ToolFailure(NOT_FOUND, f"No account {account_id}.")
        return self._plain(rows[0])

    def list_transactions(self, account_id: str, limit: int) -> list[dict]:
        self.get_account(account_id)  # not_found for an unknown account, rather than a silent []
        rows = self._query(
            "select transaction_id, account_id, posted_on, amount, description, category "
            "from harbor_core.transactions where account_id = %s "
            "order by posted_on desc, transaction_id desc limit %s", (account_id, limit))
        return [self._plain(r) for r in rows]
