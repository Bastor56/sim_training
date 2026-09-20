import context  # noqa: F401  -- must be first: puts src/ and mock_crm/ on sys.path

import time

import httpx
import pytest

import fixtures as mock_fixtures  # mock_crm/fixtures.py
from tool_client import MAX_ATTEMPTS, CRMClient

# All requests below (except the connection-error test) go through the
# real mock CRM process started by conftest.py's mock_crm_base_url
# fixture -- genuine sockets, genuine HTTP, genuine timeout behavior.


@pytest.fixture(autouse=True)
def _reset_fault_counters():
    """fail_then_recover's attempt counter is process-global state (see
    fixtures.py) -- without this, test order would change test results."""
    mock_fixtures.reset_fault_counters()


@pytest.fixture
def make_client(mock_crm_base_url):
    """Factory fixture: each test picks its own client-side timeout
    (the timeout test needs a very short one), and every httpx.Client
    created this way is closed automatically at teardown."""
    opened = []

    def _make(timeout_seconds: float = 1.0):
        sleeps = []
        http = httpx.Client(base_url=mock_crm_base_url, timeout=timeout_seconds)
        opened.append(http)
        return CRMClient(http, sleep=sleeps.append), sleeps

    yield _make
    for http in opened:
        http.close()


# -- found / not_found -------------------------------------------------


def test_found_returns_data(make_client):
    crm, sleeps = make_client()
    outcome = crm.get_account("ACC-2001")
    assert outcome.status == "found"
    assert outcome.data["account_id"] == "ACC-2001"
    assert outcome.data["balance"] == 4210.55
    assert sleeps == []


def test_found_but_empty_is_distinct_from_not_found(make_client):
    crm, sleeps = make_client()
    outcome = crm.list_account_transactions("ACC-2003")
    assert outcome.status == "found"
    assert outcome.data == []
    assert sleeps == []


def test_list_customer_accounts_returns_all(make_client):
    crm, sleeps = make_client()
    outcome = crm.list_customer_accounts("CUST-1001")
    assert outcome.status == "found"
    assert {a["account_id"] for a in outcome.data} == {"ACC-2001", "ACC-2002"}


def test_not_found_customer_does_not_retry(make_client):
    crm, sleeps = make_client()
    outcome = crm.get_customer("CUST-9999")
    assert outcome.status == "not_found"
    assert "CUST-9999" in outcome.detail
    assert sleeps == []  # not retryable -- a missing record won't appear on attempt 2


def test_not_found_account_does_not_retry(make_client):
    crm, sleeps = make_client()
    outcome = crm.get_account("ACC-9999")
    assert outcome.status == "not_found"
    assert sleeps == []


def test_list_accounts_for_unknown_customer_is_not_found(make_client):
    crm, sleeps = make_client()
    outcome = crm.list_customer_accounts("CUST-9999")
    assert outcome.status == "not_found"


# -- unavailable: each HTTP-level branch tested separately, even though
# they all converge on the same outcome value -- see tool_client.py's
# module docstring on why the internal branches stay distinct. --------


def test_server_error_exhausts_retries_to_unavailable(make_client):
    crm, sleeps = make_client()
    outcome = crm.get_account("ACC-2004")  # fixture-flagged: always 500
    assert outcome.status == "unavailable"
    assert len(sleeps) == MAX_ATTEMPTS - 1  # retried between every attempt, gave up after the last


def test_timeout_becomes_unavailable_without_hanging(monkeypatch, make_client):
    # Mock sleeps 0.15s before responding; client gives up after 0.02s.
    # Injected `sleep` is a no-op (list.append), so none of the 3 retry
    # backoffs actually block -- only the mock's real sleep costs wall
    # time, and only up to 3x 0.15s.
    monkeypatch.setenv("MOCK_CRM_TIMEOUT_SLEEP_SECONDS", "0.15")
    crm, sleeps = make_client(timeout_seconds=0.02)

    started = time.monotonic()
    outcome = crm.get_account("ACC-2005")  # fixture-flagged: always times out
    elapsed = time.monotonic() - started

    assert outcome.status == "unavailable"
    assert "did not respond in time" in outcome.detail
    assert len(sleeps) == MAX_ATTEMPTS - 1
    assert elapsed < 2.0, "timeout test should stay fast, not wait out a realistic delay"


def test_connection_error_exhausts_to_unavailable():
    # A real socket client (no ASGI transport) pointed at a port nothing
    # listens on -- connection refused is immediate, no sleep needed to
    # trigger it, so this stays fast without any mocking.
    sleeps = []
    http = httpx.Client(base_url="http://127.0.0.1:1", timeout=0.2)
    crm = CRMClient(http, sleep=sleeps.append)
    try:
        outcome = crm.get_account("ACC-2001")
    finally:
        http.close()
    assert outcome.status == "unavailable"
    assert len(sleeps) == MAX_ATTEMPTS - 1


def test_malformed_body_becomes_unavailable_without_retry(make_client):
    crm, sleeps = make_client()
    outcome = crm.get_account("ACC-2006")  # fixture-flagged: always malformed
    assert outcome.status == "unavailable"
    assert sleeps == []  # not retryable -- a schema violation won't fix itself


# -- retry can succeed, not just exhaust --------------------------------


def test_fail_then_recover_succeeds_on_final_attempt(make_client):
    crm, sleeps = make_client()
    outcome = crm.get_account("ACC-2007")  # fails twice, then recovers
    assert outcome.status == "found"
    assert outcome.data["account_id"] == "ACC-2007"
    assert len(sleeps) == MAX_ATTEMPTS - 1  # backed off twice before the 3rd attempt succeeded
