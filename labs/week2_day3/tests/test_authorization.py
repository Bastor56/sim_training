"""Authorization is enforced by the server, per tool call (spec.md R3/R4; plan.md milestone 3)."""

from __future__ import annotations

import pytest
from mcp.shared.exceptions import MCPError

from mcp_harness import RunningServer
from mcp_server.permissions import PERMISSIONS, is_allowed

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def srv(tmp_path):
    with RunningServer(tmp_path) as s:
        yield s


# ---------------------------------------------------------------- the policy itself

def test_deny_by_default():
    assert not is_allowed("member_assistant", "some_tool_nobody_granted")
    assert not is_allowed("stranger", "get_member")
    assert not is_allowed(None, "get_member")
    assert not is_allowed("member_assistant", None)


def test_member_assistant_has_no_write_tools():
    assert "freeze_card" not in PERMISSIONS["member_assistant"]
    assert "freeze_card" in PERMISSIONS["contact_centre"]


# ---------------------------------------------------------------- over HTTP

async def test_permitted_call_succeeds(srv):
    async with srv.client("tok-member") as c:
        r = await c.call_tool("get_member", {"member_id": "M-1001"})
    assert not r.is_error
    assert r.structured_content["data"]["member_id"] == "M-1001"
    assert r.structured_content["source"]["record_ids"] == ["M-1001"]
    assert srv.crm.calls == [("get_member", ("M-1001",))]
    [line] = srv.audit.read()
    assert (line["caller"], line["tool"], line["decision"], line["outcome"]) == \
        ("member_assistant", "get_member", "allowed", "ok")


async def test_forbidden_call_is_refused_and_never_reaches_the_backend(srv):
    async with srv.client("tok-auditor") as c:
        with pytest.raises(MCPError, match="forbidden: auditor may not call get_member"):
            await c.call_tool("get_member", {"member_id": "M-1001"})
    assert srv.crm.calls == []  # the backend was never touched
    [line] = srv.audit.read()
    assert (line["caller"], line["decision"], line["outcome"]) == ("auditor", "denied", "forbidden")


async def test_write_tool_refused_for_member_assistant(srv):
    # freeze_card isn't even registered yet (milestone 4): authorization is
    # checked first, so the caller learns nothing about whether it exists.
    async with srv.client("tok-member") as c:
        with pytest.raises(MCPError, match="forbidden"):
            await c.call_tool("freeze_card", {"card_id": "CARD-4001", "reason": "lost"})
    assert srv.audit.read()[0]["outcome"] == "forbidden"


async def test_undeclared_argument_is_refused_and_its_value_never_logged(srv):
    async with srv.client("tok-member") as c:
        with pytest.raises(MCPError, match="undeclared argument"):
            await c.call_tool("get_member", {"member_id": "M-1001", "db_password": "hunter2"})
    assert srv.crm.calls == []
    [line] = srv.audit.read()
    assert line["outcome"] == "invalid_arguments"
    assert "hunter2" not in srv.cfg.audit_path.read_text()
    assert line["arguments"]["db_password"].startswith("[redacted")


@pytest.mark.parametrize("args,problem", [
    ({"member_id": "bogus"}, "pattern"),
    ({}, "missing required argument"),
    ({"member_id": 1001}, "type"),
])
async def test_arguments_checked_against_the_tools_schema(srv, args, problem):
    async with srv.client("tok-member") as c:
        with pytest.raises(MCPError, match=problem):
            await c.call_tool("get_member", args)
    assert srv.crm.calls == []


async def test_anticipated_backend_failure_is_a_readable_error_result(srv):
    async with srv.client("tok-member") as c:
        r = await c.call_tool("get_member", {"member_id": "M-9999"})
    assert r.is_error
    assert "No member M-9999." in r.content[0].text
    assert srv.audit.read()[0]["outcome"] == "not_found"


async def _connect(srv, token):
    async with srv.client(token) as c:
        await c.list_tools()


@pytest.mark.parametrize("token", ["wrong-token", None])
async def test_bad_token_cannot_connect(srv, token):
    with pytest.raises(BaseException):  # the SDK surfaces the 401 as an exception group
        await _connect(srv, token)
    lines = srv.audit.read()
    assert lines and all(l["outcome"] == "unauthenticated" and l["caller"] is None for l in lines)
    assert "wrong-token" not in srv.cfg.audit_path.read_text()  # the rejected token isn't stored
