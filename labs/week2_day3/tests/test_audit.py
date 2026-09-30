"""One audit line per tools/call, every field present (spec.md R5; plan.md milestone 3)."""

from __future__ import annotations

import pytest
from mcp.shared.exceptions import MCPError

from mcp_harness import SERVER_VERSION, RunningServer

pytestmark = pytest.mark.anyio

FIELDS = {"ts", "audit_id", "request_id", "caller", "tool", "arguments", "decision", "outcome",
          "error", "latency_ms", "server_version"}


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def test_every_tool_call_writes_exactly_one_line(tmp_path):
    calls = [
        ("tok-member", "get_member", {"member_id": "M-1001"}),                   # ok
        ("tok-member", "get_member", {"member_id": "M-9999"}),                   # not_found
        ("tok-member", "freeze_card", {"card_id": "CARD-4001", "reason": "x"}),  # forbidden
        ("tok-cc", "get_member", {"member_id": "M-1002"}),                       # ok
        ("tok-cc", "get_member", {"member_id": "M-1002", "api_key": "k"}),      # invalid_arguments
        ("tok-auditor", "get_member", {"member_id": "M-1001"}),                  # forbidden
    ]
    with RunningServer(tmp_path) as srv:
        for token, tool, args in calls:
            async with srv.client(token) as c:
                try:
                    await c.call_tool(tool, args)
                except MCPError:
                    pass
            # tools/list and the connection handshake must NOT add lines
        lines = srv.audit.read()

    assert len(lines) == len(calls)
    assert [l["outcome"] for l in lines] == ["ok", "not_found", "forbidden", "ok", "invalid_arguments", "forbidden"]
    assert [l["caller"] for l in lines] == ["member_assistant"] * 3 + ["contact_centre"] * 2 + ["auditor"]
    for line in lines:
        assert set(line) == FIELDS
        assert line["server_version"] == SERVER_VERSION
        assert line["latency_ms"] is not None
    assert len({l["audit_id"] for l in lines}) == len(lines)
