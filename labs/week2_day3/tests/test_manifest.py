"""TOOL_MANIFEST.md matches what the server actually advertises and enforces (spec.md R6).

A manifest nobody checks drifts from the code within a release. This test
makes drift a failing build: tool names, parameters, required flags,
permissions and version must agree.
"""

from __future__ import annotations

import re

import anyio
import pytest

from mcp_harness import FakeCore, FakeCRM, TOKENS
from mcp_server.audit import AuditLog
from mcp_server.config import SERVER_DIR, ServerConfig
from mcp_server.permissions import PERMISSIONS
from mcp_server.server import SERVER_VERSION, build_server

MANIFEST = SERVER_DIR / "TOOL_MANIFEST.md"
REQUIRED_FIELDS = ("**Purpose:**", "**Parameters:**", "**Required permission:**", "**Side effects:**",
                   "**Failure modes:**")


def manifest_sections() -> dict[str, str]:
    text = MANIFEST.read_text(encoding="utf-8")
    tools_part = text.split("## Tools", 1)[1].split("\n## ", 1)[0]
    parts = re.split(r"^### `([a-z_]+)`\s*$", tools_part, flags=re.M)
    return dict(zip(parts[1::2], parts[2::2]))


def param_rows(section: str) -> dict[str, dict]:
    rows = {}
    for line in section.splitlines():
        m = re.match(r"^\|\s*`([a-z_]+)`\s*\|\s*(\w+)\s*\|\s*(yes|no)\s*\|", line)
        if m:
            rows[m.group(1)] = {"type": m.group(2), "required": m.group(3) == "yes"}
    return rows


@pytest.fixture(scope="module")
def advertised(tmp_path_factory):
    cfg = ServerConfig(tokens=TOKENS, crm_base_url="x", crm_api_key="x", db_host="x", db_port=0,
                       db_name="x", db_user="x", db_password="x")
    server = build_server(cfg, crm=FakeCRM(), core=FakeCore(),
                          audit=AuditLog(tmp_path_factory.mktemp("audit") / "a.jsonl"))
    return {t.name: t for t in anyio.run(server.list_tools)}


def test_version_matches():
    assert f"**Server version:** {SERVER_VERSION}" in MANIFEST.read_text(encoding="utf-8")
    assert f"| {SERVER_VERSION} |" in MANIFEST.read_text(encoding="utf-8"), "changelog line for this version"


def test_same_tools(advertised):
    assert set(manifest_sections()) == set(advertised)


def test_every_tool_documents_every_field():
    for name, section in manifest_sections().items():
        for field in REQUIRED_FIELDS:
            assert field in section, f"{name}: missing {field}"


def test_parameters_match_schema(advertised):
    for name, section in manifest_sections().items():
        schema = advertised[name].input_schema
        rows = param_rows(section)
        assert set(rows) == set(schema["properties"]), name
        required = set(schema.get("required", []))
        for param, row in rows.items():
            assert row["required"] == (param in required), f"{name}.{param} required flag"
            assert row["type"] == schema["properties"][param]["type"], f"{name}.{param} type"


def test_permissions_match_policy():
    for name, section in manifest_sections().items():
        line = next(l for l in section.splitlines() if l.startswith("**Required permission:**"))
        documented = set(re.findall(r"`([a-z_]+)`", line))
        granted = {caller for caller, tools in PERMISSIONS.items() if name in tools}
        assert documented == granted, name
