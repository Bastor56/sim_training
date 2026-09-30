"""Every tool over real HTTP with fake backends: ok, anticipated failures, schema, provenance (plan.md milestone 4)."""

from __future__ import annotations

import pytest
from mcp.shared.exceptions import MCPError

from mcp_harness import EXPECTED_TOOLS, SERVER_VERSION, FakeCore, RunningServer

pytestmark = pytest.mark.anyio

ALL_TOOLS = set(EXPECTED_TOOLS)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def srv(tmp_path):
    with RunningServer(tmp_path) as s:
        yield s


async def call(srv, token, tool, args):
    async with srv.client(token) as c:
        return await c.call_tool(tool, args)


# ---------------------------------------------------------------- discovery shape (R1)

async def test_every_tool_is_advertised_with_a_typed_schema_and_description(srv):
    async with srv.client("tok-member") as c:
        tools = {t.name: t for t in (await c.list_tools()).tools}
    assert set(tools) == ALL_TOOLS
    for t in tools.values():
        assert t.description and len(t.description) > 80, t.name  # routing needs real words
        assert t.input_schema["type"] == "object"
        for name, prop in t.input_schema["properties"].items():
            assert "type" in prop and prop.get("description"), f"{t.name}.{name}"
        assert t.annotations is not None


async def test_annotations_mark_the_one_write(srv):
    async with srv.client("tok-member") as c:
        tools = {t.name: t for t in (await c.list_tools()).tools}
    assert tools["freeze_card"].annotations.read_only_hint is False
    assert all(tools[n].annotations.read_only_hint for n in ALL_TOOLS - {"freeze_card"})


# ---------------------------------------------------------------- success + provenance

@pytest.mark.parametrize("tool,args,system,record_ids", [
    ("get_member", {"member_id": "M-1001"}, "harbor_crm", ["M-1001"]),
    ("list_cards", {"member_id": "M-1001"}, "harbor_crm", ["CARD-4001"]),
    ("get_card_limits", {"card_id": "CARD-4001"}, "harbor_crm", ["CARD-4001"]),
    ("list_member_accounts", {"member_id": "M-1001"}, "harbor_core_banking", ["ACC-2001"]),
    ("get_account", {"account_id": "ACC-2001"}, "harbor_core_banking", ["ACC-2001"]),
    ("list_transactions", {"account_id": "ACC-2001", "limit": 2}, "harbor_core_banking", ["TXN-0", "TXN-1"]),
])
async def test_read_tools_return_data_with_source(srv, tool, args, system, record_ids):
    r = await call(srv, "tok-member", tool, args)
    assert not r.is_error
    src = r.structured_content["source"]
    assert (src["system"], src["record_ids"], src["tool"]) == (system, record_ids, tool)
    assert src["server"] == "harbor-mcp" and src["server_version"] == SERVER_VERSION and src["fetched_at"].endswith("Z")
    assert src["lookup"] == args


async def test_list_transactions_default_limit_is_10(srv):
    r = await call(srv, "tok-member", "list_transactions", {"account_id": "ACC-2001"})
    assert len(r.structured_content["data"]) == 10
    assert srv.core.calls[-1] == ("list_transactions", ("ACC-2001", 10))


async def test_contact_centre_can_freeze(srv):
    r = await call(srv, "tok-cc", "freeze_card", {"card_id": "CARD-4001", "reason": "member reports card lost"})
    assert r.structured_content["data"]["status"] == "frozen"
    assert srv.crm.calls == [("freeze_card", ("CARD-4001", "member reports card lost"))]


# ---------------------------------------------------------------- anticipated failures

@pytest.mark.parametrize("token,tool,args,outcome,text", [
    ("tok-member", "get_account", {"account_id": "ACC-9999"}, "not_found", "No account ACC-9999."),
    ("tok-member", "list_cards", {"member_id": "M-1003"}, "unavailable", "The CRM is unavailable right now."),
    ("tok-cc", "freeze_card", {"card_id": "CARD-4008", "reason": "lost"}, "conflict", "already reported lost"),
])
async def test_failures_are_readable_error_results(srv, token, tool, args, outcome, text):
    r = await call(srv, token, tool, args)
    assert r.is_error and text in r.content[0].text
    assert srv.audit.read()[-1]["outcome"] == outcome


async def test_core_banking_down_is_unavailable(tmp_path):
    with RunningServer(tmp_path, core=FakeCore(down=True)) as srv:
        r = await call(srv, "tok-member", "get_account", {"account_id": "ACC-2001"})
        assert r.is_error and "Core banking is unavailable" in r.content[0].text
        assert srv.audit.read()[-1]["outcome"] == "unavailable"


# ---------------------------------------------------------------- schema limits enforced before the backend

@pytest.mark.parametrize("token,tool,args", [
    ("tok-member", "list_transactions", {"account_id": "ACC-2001", "limit": 51}),
    ("tok-member", "list_transactions", {"account_id": "ACC-2001", "limit": 0}),
    ("tok-member", "get_account", {"account_id": "2001"}),
    ("tok-cc", "freeze_card", {"card_id": "CARD-4001"}),                   # reason is required
    ("tok-cc", "freeze_card", {"card_id": "CARD-4001", "reason": ""}),     # and non-empty
    ("tok-member", "list_cards", {"member_id": "M-1001; drop table"}),
])
async def test_bad_arguments_never_reach_the_backend(srv, token, tool, args):
    # pytest.raises must sit INSIDE the client's `async with`: an error that
    # escapes the block comes out wrapped in an ExceptionGroup.
    async with srv.client(token) as c:
        with pytest.raises(MCPError, match="invalid arguments"):
            await c.call_tool(tool, args)
    assert srv.crm.calls == [] and srv.core.calls == []
