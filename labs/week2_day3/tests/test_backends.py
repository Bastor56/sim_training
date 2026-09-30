"""The server's backend clients translate reality into the closed outcome set (plan.md milestone 4).

CRM: httpx's MockTransport scripts each HTTP response, and the sleep is a
fake, so week 1's real retry policy runs at full speed.
Core banking: live against local Postgres as harbor_mcp (skipped if down).
"""

from __future__ import annotations

import httpx
import pytest

from mcp_server import outcomes
from mcp_server.backends import MAX_ATTEMPTS, CoreBanking, CRMClient
from mcp_server.config import ENV_FILE, read_env
from mcp_server.outcomes import ToolFailure

MEMBER = {"member_id": "M-1001", "name": "Maria Chen", "email": "m@example.com", "member_since": "2019-03-11"}
CARD = {"card_id": "CARD-4001", "member_id": "M-1001", "account_id": "ACC-2001", "type": "debit",
        "last_four": "4471", "status": "frozen"}


def scripted_crm(*responses):
    """A CRMClient whose HTTP calls return `responses` in order. Records requests and sleeps."""
    seen, sleeps, queue = [], [], list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        r = queue.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    http = httpx.Client(base_url="http://crm", transport=httpx.MockTransport(handler), headers={"X-API-Key": "k"})
    return CRMClient(http, sleep=sleeps.append), seen, sleeps


def test_success_sends_the_key():
    crm, seen, sleeps = scripted_crm(httpx.Response(200, json=MEMBER))
    assert crm.get_member("M-1001") == MEMBER
    assert seen[0].headers["X-API-Key"] == "k" and sleeps == []


def test_500_then_success_retries():
    crm, seen, sleeps = scripted_crm(httpx.Response(500), httpx.Response(500), httpx.Response(200, json=MEMBER))
    assert crm.get_member("M-1001") == MEMBER
    assert len(seen) == 3 and len(sleeps) == 2


@pytest.mark.parametrize("failure", [
    httpx.Response(500),
    httpx.Response(200, content=b'{"broken'),     # malformed body, 200
    httpx.ReadTimeout("slow"),
    httpx.ConnectError("refused"),
])
def test_persistent_failure_is_unavailable_after_max_attempts(failure):
    crm, seen, sleeps = scripted_crm(*[failure] * MAX_ATTEMPTS)
    with pytest.raises(ToolFailure) as e:
        crm.get_member("M-1001")
    assert e.value.outcome == outcomes.UNAVAILABLE
    assert len(seen) == MAX_ATTEMPTS and len(sleeps) == MAX_ATTEMPTS - 1


@pytest.mark.parametrize("status,outcome", [(404, outcomes.NOT_FOUND), (409, outcomes.CONFLICT),
                                            (401, outcomes.UNAVAILABLE)])
def test_4xx_is_not_retried(status, outcome):
    crm, seen, _ = scripted_crm(httpx.Response(status, json={"error": "x", "message": "Card is lost."}))
    with pytest.raises(ToolFailure) as e:
        crm.freeze_card("CARD-4008", "lost")
    assert e.value.outcome == outcome and len(seen) == 1


def test_401_message_does_not_blame_or_inform_the_caller():
    crm, _, _ = scripted_crm(httpx.Response(401, json={"error": "unauthorized", "message": "bad key"}))
    with pytest.raises(ToolFailure, match="^The CRM is unavailable right now.$"):
        crm.get_member("M-1001")


def test_wrong_shape_is_unavailable():
    crm, _, _ = scripted_crm(httpx.Response(200, json={"unexpected": True}))
    with pytest.raises(ToolFailure) as e:
        crm.get_member("M-1001")
    assert e.value.outcome == outcomes.UNAVAILABLE


def test_freeze_posts_the_reason():
    crm, seen, _ = scripted_crm(httpx.Response(200, json=CARD))
    assert crm.freeze_card("CARD-4001", "lost")["status"] == "frozen"
    assert seen[0].method == "POST" and seen[0].url.path == "/cards/CARD-4001/freeze"
    assert b'"reason":"lost"' in seen[0].content.replace(b" ", b"")


# ---------------------------------------------------------------- core banking, live

@pytest.fixture(scope="module")
def core():
    env = read_env(ENV_FILE)
    c = CoreBanking.from_config(env["HARBOR_DB_HOST"], int(env["HARBOR_DB_PORT"]), env["HARBOR_DB_NAME"],
                                env["HARBOR_DB_USER"], env["HARBOR_DB_PASSWORD"])
    try:
        c.get_account("ACC-2001")
    except ToolFailure:
        pytest.skip("local Postgres not reachable as harbor_mcp")
    return c


def test_core_accounts(core):
    accounts = core.list_member_accounts("M-1001")
    assert [(a["account_id"], a["type"], a["balance"]) for a in accounts] == \
        [("ACC-2001", "checking", "4210.55"), ("ACC-2002", "savings", "15320.10")]
    assert accounts[0]["opened_on"] == "2019-03-11"


def test_core_money_is_an_exact_string(core):
    assert core.get_account("ACC-2003")["balance"] == "512.00"


def test_core_unknown_member_is_empty_not_error(core):
    assert core.list_member_accounts("M-9999") == []


def test_core_unknown_account_is_not_found(core):
    for fn in (lambda: core.get_account("ACC-9999"), lambda: core.list_transactions("ACC-9999", 5)):
        with pytest.raises(ToolFailure) as e:
            fn()
        assert e.value.outcome == outcomes.NOT_FOUND


def test_core_transactions_newest_first_and_limited(core):
    txns = core.list_transactions("ACC-2001", 3)
    assert [t["transaction_id"] for t in txns] == ["TXN-3010", "TXN-3009", "TXN-3008"]
    assert txns[0]["amount"] == "-63.48" and txns[0]["posted_on"] == "2026-09-26"
    assert core.list_transactions("ACC-2003", 10) == []  # exists, no history


def test_core_injection_attempt_is_just_a_value(core):
    # Parameterised: the quote is data, not SQL. (The middleware's pattern check
    # would refuse this before it got here; this proves the second layer holds.)
    assert core.list_member_accounts("M-1001' or '1'='1") == []


def test_core_down_is_unavailable():
    c = CoreBanking.from_config("127.0.0.1", 1, "postgres", "harbor_mcp", "x")  # nothing listens on port 1
    with pytest.raises(ToolFailure) as e:
        c.get_account("ACC-2001")
    assert e.value.outcome == outcomes.UNAVAILABLE and "127.0.0.1" not in str(e.value)


def test_card_limits_shape():
    body = {"card_id": "CARD-4001", "atm_daily_limit": "800.00", "purchase_daily_limit": "5000.00",
            "currency": "USD", "updated_on": "2026-06-14"}
    crm, seen, _ = scripted_crm(httpx.Response(200, json=body))
    assert crm.get_card_limits("CARD-4001") == body
    assert seen[0].url.path == "/cards/CARD-4001/limits"
