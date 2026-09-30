"""Runs harbor-mcp over real HTTP in a background thread, with fake backends.

Real HTTP, not the SDK's in-memory transport, because authentication only
exists on the HTTP path: the bearer token is an HTTP header. Tests that go
around HTTP would skip the very thing they're meant to test.
"""

from __future__ import annotations

import socket
import threading
import time
from pathlib import Path

import httpx2
import uvicorn
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from mcp_server import outcomes
from mcp_server.audit import AuditLog
from mcp_server.config import ServerConfig
from mcp_server.outcomes import ToolFailure
from mcp_server.permissions import PERMISSIONS
from mcp_server.server import SERVER_VERSION, build_app, build_server  # noqa: F401 (re-exported for tests)

# The tools the server is expected to advertise: written out ONCE, here, so an accidental
# addition or removal fails the tests that use it.
EXPECTED_TOOLS = sorted(["get_member", "list_cards", "freeze_card", "list_member_accounts", "get_account",
                         "list_transactions", "get_card_limits"])  # get_card_limits: 0.2.0

TOKENS = {
    "tok-member": "member_assistant",
    "tok-cc": "contact_centre",
    "tok-auditor": "auditor",  # authenticated, but granted nothing
}
TEST_PERMISSIONS = {**PERMISSIONS, "auditor": frozenset()}


class FakeCRM:
    """Stands in for backends.CRMClient. Counts every call, so a test can prove
    a refused request never reached the backend."""

    system = "harbor_crm"

    def __init__(self):
        self.calls: list[tuple[str, tuple]] = []

    def get_member(self, member_id: str) -> dict:
        self.calls.append(("get_member", (member_id,)))
        if member_id == "M-9999":
            raise ToolFailure(outcomes.NOT_FOUND, f"No member {member_id}.")
        return {"member_id": member_id, "name": "Test Member", "email": "t@example.com", "member_since": "2020-01-01"}

    def list_cards(self, member_id: str) -> list[dict]:
        self.calls.append(("list_cards", (member_id,)))
        if member_id == "M-1003":
            raise ToolFailure(outcomes.UNAVAILABLE, "The CRM is unavailable right now.")
        return [{"card_id": "CARD-4001", "member_id": member_id, "account_id": "ACC-2001", "type": "debit",
                 "last_four": "4471", "status": "active"}]

    def get_card_limits(self, card_id: str) -> dict:
        self.calls.append(("get_card_limits", (card_id,)))
        return {"card_id": card_id, "atm_daily_limit": "800.00", "purchase_daily_limit": "5000.00",
                "currency": "USD", "updated_on": "2026-06-14"}

    def freeze_card(self, card_id: str, reason: str) -> dict:
        self.calls.append(("freeze_card", (card_id, reason)))
        if card_id == "CARD-4008":
            raise ToolFailure(outcomes.CONFLICT, f"Card '{card_id}' is already reported lost and cannot be frozen.")
        return {"card_id": card_id, "member_id": "M-1001", "account_id": "ACC-2001", "type": "debit",
                "last_four": "4471", "status": "frozen"}


class FakeCore:
    """Stands in for backends.CoreBanking. `down=True` makes every call unavailable."""

    system = "harbor_core_banking"

    def __init__(self, down: bool = False):
        self.calls: list[tuple[str, tuple]] = []
        self.down = down

    def _check(self, name: str, *args):
        self.calls.append((name, args))
        if self.down:
            raise ToolFailure(outcomes.UNAVAILABLE, "Core banking is unavailable right now.")

    def list_member_accounts(self, member_id: str) -> list[dict]:
        self._check("list_member_accounts", member_id)
        return [{"account_id": "ACC-2001", "member_id": member_id, "type": "checking", "balance": "4210.55",
                 "status": "active", "opened_on": "2019-03-11"}]

    def get_account(self, account_id: str) -> dict:
        self._check("get_account", account_id)
        if account_id == "ACC-9999":
            raise ToolFailure(outcomes.NOT_FOUND, f"No account {account_id}.")
        return {"account_id": account_id, "member_id": "M-1001", "type": "checking", "balance": "4210.55",
                "status": "active", "opened_on": "2019-03-11"}

    def list_transactions(self, account_id: str, limit: int) -> list[dict]:
        self._check("list_transactions", account_id, limit)
        return [{"transaction_id": f"TXN-{i}", "account_id": account_id, "posted_on": "2026-09-26",
                 "amount": "-10.00", "description": "x", "category": "groceries"} for i in range(limit)]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class RunningServer:
    def __init__(self, tmp_path: Path, crm=None, core=None, permissions=TEST_PERMISSIONS):
        port = _free_port()
        self.cfg = ServerConfig(tokens=TOKENS, crm_base_url="http://unused", crm_api_key="unused",
                                db_host="unused", db_port=0, db_name="unused", db_user="unused",
                                db_password="unused", port=port, audit_path=tmp_path / "audit.jsonl")
        self.crm = crm or FakeCRM()
        self.core = core or FakeCore()
        self.audit = AuditLog(self.cfg.audit_path)
        self.server = build_server(self.cfg, crm=self.crm, core=self.core, audit=self.audit,
                                   permissions=permissions)
        self._uvicorn = uvicorn.Server(uvicorn.Config(build_app(self.server, self.audit, self.cfg),
                                                      host="127.0.0.1", port=port, log_level="error"))
        self._thread = threading.Thread(target=self._uvicorn.run, daemon=True)

    def __enter__(self) -> "RunningServer":
        self._thread.start()
        deadline = time.monotonic() + 10
        while not self._uvicorn.started:
            if time.monotonic() > deadline:
                raise RuntimeError("test server did not start")
            time.sleep(0.02)
        return self

    def __exit__(self, *exc) -> None:
        self._uvicorn.should_exit = True
        self._thread.join(timeout=10)

    def client(self, token: str | None) -> Client:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return Client(streamable_http_client(self.cfg.url, http_client=httpx2.AsyncClient(headers=headers)))
