"""The Harbor mock CRM honours its contract (backends/mock_crm/contract.md; plan.md milestone 2).

In-process via FastAPI's TestClient: no server needs to be running.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

CRM_DIR = Path(__file__).resolve().parent.parent / "backends" / "mock_crm"
TEST_KEY = "test-crm-key"


@pytest.fixture(scope="module")
def crm():
    os.environ["CRM_API_KEY"] = TEST_KEY
    os.environ["MOCK_CRM_TIMEOUT_SLEEP_SECONDS"] = "0.01"
    sys.path.insert(0, str(CRM_DIR))
    try:
        app_module = importlib.import_module("app")
        yield app_module, importlib.import_module("fixtures")
    finally:
        sys.path.remove(str(CRM_DIR))
        for name in ("app", "fixtures", "schemas"):
            sys.modules.pop(name, None)
        os.environ.pop("CRM_API_KEY", None)


@pytest.fixture
def client(crm):
    app_module, fixtures = crm
    fixtures.reset()
    return TestClient(app_module.app, headers={"X-API-Key": TEST_KEY})


@pytest.fixture
def anon(crm):
    return TestClient(crm[0].app)


# ---------------------------------------------------------------- authentication

def test_refuses_to_start_without_a_key(monkeypatch):
    monkeypatch.delenv("CRM_API_KEY", raising=False)
    monkeypatch.syspath_prepend(str(CRM_DIR))
    saved = {n: sys.modules.pop(n, None) for n in ("app", "fixtures", "schemas")}
    try:
        with pytest.raises(RuntimeError, match="CRM_API_KEY"):
            importlib.import_module("app")
    finally:
        for n in ("app", "fixtures", "schemas"):
            sys.modules.pop(n, None)
        sys.modules.update({n: m for n, m in saved.items() if m is not None})


def test_health_needs_no_key(anon):
    assert anon.get("/health").json() == {"status": "ok"}


@pytest.mark.parametrize("method,path", [
    ("get", "/members/M-1001"),
    ("get", "/members/M-1001/cards"),
    ("post", "/cards/CARD-4001/freeze"),
    ("post", "/admin/reset"),
])
def test_missing_key_is_401(anon, method, path):
    r = getattr(anon, method)(path, json={"reason": "x"}) if method == "post" else anon.get(path)
    assert r.status_code == 401
    assert r.json()["error"] == "unauthorized"


def test_wrong_key_is_401(crm):
    r = TestClient(crm[0].app, headers={"X-API-Key": "wrong"}).get("/members/M-1001")
    assert r.status_code == 401


def test_key_checked_before_fault_header(anon):
    # An unauthenticated caller must not be able to trigger anything.
    r = anon.get("/members/M-1001", headers={"X-Simulate-Fault": "500"})
    assert r.status_code == 401


# ---------------------------------------------------------------- reads

def test_get_member(client):
    body = client.get("/members/M-1001").json()
    assert body == {"member_id": "M-1001", "name": "Maria Chen", "email": "maria.chen@example.com",
                    "member_since": "2019-03-11"}
    assert "simulated_fault" not in client.get("/members/M-1003").json()


def test_unknown_member_is_404(client):
    r = client.get("/members/M-9999")
    assert r.status_code == 404 and r.json()["error"] == "not_found"


def test_list_cards(client):
    cards = client.get("/members/M-1002/cards").json()
    assert {c["card_id"]: c["status"] for c in cards} == {"CARD-4003": "active", "CARD-4008": "lost"}
    assert all(c["account_id"] == "ACC-2003" for c in cards)


def test_member_lookup_never_faults(client):
    for member_id in ("M-1003", "M-1004", "M-1005", "M-1006"):
        assert client.get(f"/members/{member_id}").status_code == 200


# ---------------------------------------------------------------- fixture faults on card listing

def test_fault_server_error(client):
    assert client.get("/members/M-1003/cards").status_code == 500


def test_fault_timeout_sleeps_then_answers(client):
    # The sleep is shrunk to 0.01 s here; the caller's own timeout is what fires in practice.
    assert client.get("/members/M-1004/cards").status_code == 200


def test_fault_malformed_is_200_with_broken_json(client):
    r = client.get("/members/M-1005/cards")
    assert r.status_code == 200
    with pytest.raises(ValueError):
        r.json()


def test_fault_fail_then_recover(client):
    codes = [client.get("/members/M-1006/cards").status_code for _ in range(3)]
    assert codes == [500, 500, 200]


def test_header_fault_and_bad_header(client):
    assert client.get("/members/M-9999", headers={"X-Simulate-Fault": "500"}).status_code == 500
    r = client.get("/members/M-1001", headers={"X-Simulate-Fault": "nope"})
    assert r.status_code == 400 and r.json()["error"] == "invalid_fault_header"


# ---------------------------------------------------------------- card limits (added for harbor-mcp 0.2.0)

def test_card_limits(client):
    assert client.get("/cards/CARD-4001/limits").json() == {
        "card_id": "CARD-4001", "atm_daily_limit": "800.00", "purchase_daily_limit": "5000.00",
        "currency": "USD", "updated_on": "2026-06-14"}
    assert client.get("/cards/CARD-4003/limits").json()["atm_daily_limit"] == "500.00"
    assert client.get("/cards/CARD-9999/limits").status_code == 404


def test_card_limits_need_the_key(anon):
    assert anon.get("/cards/CARD-4001/limits").status_code == 401


# ---------------------------------------------------------------- freeze (the one write)

def test_freeze_sets_frozen(client):
    r = client.post("/cards/CARD-4001/freeze", json={"reason": "member reports card lost"})
    assert r.status_code == 200 and r.json()["status"] == "frozen"
    cards = client.get("/members/M-1001/cards").json()
    assert cards[0]["status"] == "frozen"  # the change is visible to later reads


def test_freeze_twice_is_idempotent(client):
    first = client.post("/cards/CARD-4001/freeze", json={"reason": "lost"})
    second = client.post("/cards/CARD-4001/freeze", json={"reason": "lost"})
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()


def test_freeze_already_frozen_card(client):
    r = client.post("/cards/CARD-4006/freeze", json={"reason": "check"})
    assert r.status_code == 200 and r.json()["status"] == "frozen"


def test_freeze_lost_card_is_409(client):
    r = client.post("/cards/CARD-4008/freeze", json={"reason": "lost"})
    assert r.status_code == 409 and r.json()["error"] == "conflict"
    assert client.get("/members/M-1002/cards").json()[1]["status"] == "lost"  # unchanged


def test_freeze_unknown_card_is_404(client):
    assert client.post("/cards/CARD-9999/freeze", json={"reason": "x"}).status_code == 404


@pytest.mark.parametrize("body", [{}, {"reason": ""}])
def test_freeze_needs_a_reason(client, body):
    assert client.post("/cards/CARD-4001/freeze", json=body).status_code == 422


def test_admin_reset_restores_cards(client):
    client.post("/cards/CARD-4001/freeze", json={"reason": "lost"})
    assert client.post("/admin/reset").json() == {"status": "reset"}
    assert client.get("/members/M-1001/cards").json()[0]["status"] == "active"
