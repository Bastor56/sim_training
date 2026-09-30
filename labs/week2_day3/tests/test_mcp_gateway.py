"""The agent's sync gateway works against a real harbor-mcp over HTTP (plan.md milestone 5).

The server runs in one background thread (mcp_harness), the gateway's own
event loop in another, and the test calls plain sync methods: the same
arrangement the synchronous agent graph will use.
"""

from __future__ import annotations

import threading

import pytest

from mcp_gateway import GatewayError, MCPGateway, tool_list_hash
from mcp_harness import EXPECTED_TOOLS, SERVER_VERSION, RunningServer

ALL_TOOLS = EXPECTED_TOOLS


@pytest.fixture
def srv(tmp_path):
    with RunningServer(tmp_path) as s:
        yield s


@pytest.fixture
def gw(srv):
    with MCPGateway(srv.cfg.url, "tok-member") as g:
        yield g


def test_discovery(gw):
    assert gw.discovery["server"] == "harbor-mcp"
    assert gw.discovery["server_version"] == SERVER_VERSION
    assert gw.discovery["tools"] == ALL_TOOLS
    assert len(gw.discovery["tool_list_hash"]) == 16


def test_tool_specs_are_ready_for_claude(gw):
    specs = {t.name: t for t in gw.list_tools()}
    assert specs["freeze_card"].read_only is False and specs["get_account"].read_only is True
    claude = specs["get_account"].for_claude()
    assert set(claude) == {"name", "description", "input_schema"}
    assert claude["input_schema"]["properties"]["account_id"]["pattern"] == r"^ACC-\d{4}$"


def test_ok_call(gw):
    call = gw.call_tool("get_account", {"account_id": "ACC-2001"})
    assert call.status == "ok" and call.data["balance"] == "4210.55"
    assert call.source["system"] == "harbor_core_banking" and call.record_ids == ["ACC-2001"]
    assert call.latency_ms > 0


def test_many_calls_share_one_session(gw, srv):
    for _ in range(5):
        assert gw.call_tool("get_member", {"member_id": "M-1001"}).status == "ok"
    assert len(srv.audit.read()) == 5


def test_anticipated_failure_is_error_with_member_safe_text(gw):
    call = gw.call_tool("get_account", {"account_id": "ACC-9999"})
    assert call.status == "error" and call.error == "No account ACC-9999."  # SDK prefix stripped


def test_forbidden_is_refused_with_code(gw):
    call = gw.call_tool("freeze_card", {"card_id": "CARD-4001", "reason": "lost"})
    assert call.status == "refused" and call.code == -32003
    assert "forbidden: member_assistant may not call freeze_card" in call.error


def test_invalid_arguments_is_refused(gw):
    call = gw.call_tool("get_account", {"account_id": "ACC-2001", "db_password": "x"})
    assert call.status == "refused" and call.code == -32602 and "undeclared" in call.error


def test_session_survives_a_refusal(gw):
    gw.call_tool("freeze_card", {"card_id": "CARD-4001", "reason": "lost"})
    assert gw.call_tool("get_member", {"member_id": "M-1001"}).status == "ok"


def test_bad_token_fails_on_connect_with_a_clear_error(srv):
    with pytest.raises(GatewayError, match="could not connect"):
        MCPGateway(srv.cfg.url, "wrong-token").connect()


def test_no_token_fails_before_any_network(srv):
    with pytest.raises(GatewayError, match="HARBOR_MCP_TOKEN"):
        MCPGateway(srv.cfg.url, "")


def test_server_down_fails_on_connect(tmp_path):
    with pytest.raises(GatewayError, match="could not connect"):
        MCPGateway("http://127.0.0.1:1/mcp", "tok-member").connect()


def _portal_threads() -> list[str]:
    return [t.name for t in threading.enumerate() if t.name.startswith("asyncio-portal")]


def test_close_releases_the_background_thread(srv):
    # Counts only the gateway's own event-loop thread. The in-process test
    # server keeps a pooled "AnyIO worker thread" for running tools; that one
    # is the server's, is reused, and isn't ours to close.
    g = MCPGateway(srv.cfg.url, "tok-member").connect()
    assert len(_portal_threads()) == 1
    g.call_tool("get_member", {"member_id": "M-1001"})
    g.close()
    assert _portal_threads() == []


def test_repeated_connect_close_does_not_accumulate_threads(srv):
    # Warm up: the server creates its worker thread on the first TOOL call, not on connect.
    warm = MCPGateway(srv.cfg.url, "tok-member").connect()
    warm.call_tool("get_member", {"member_id": "M-1001"})
    warm.close()
    before = threading.active_count()
    for _ in range(3):
        g = MCPGateway(srv.cfg.url, "tok-member").connect()
        g.call_tool("get_member", {"member_id": "M-1001"})
        g.close()
    assert threading.active_count() == before


def test_hash_changes_when_the_tool_list_changes(gw):
    tools = gw.list_tools()
    assert tool_list_hash(tools) == tool_list_hash(list(reversed(tools)))  # order-independent
    assert tool_list_hash(tools[:-1]) != tool_list_hash(tools)
