"""The agent's one door to Harbor's systems: an MCP client (spec.md "The MCP client").

The ONLY agent file that imports `mcp` (tests/test_no_bypass.py). It knows
two things: the server's URL and this agent's own caller token. It holds no
backend URL, no CRM key, no database login, and no list of tools: the tool
list is whatever the server advertises when we connect (R2).

Sync outside, async inside. The agent graph is synchronous (LangGraph
.invoke, as on Day 2); the MCP SDK is async. The gateway runs ONE event loop
on a background thread (anyio's "blocking portal") and keeps one MCP session
open on it. Each sync method hands a coroutine to that loop and waits for
the answer. So the agent makes ordinary function calls, and the session's
handshake happens once, not once per tool call.

    gw = MCPGateway.from_env().connect()
    gw.discovery            # server name/version, tool names, tool-list hash
    gw.list_tools()         # [ToolSpec]  (what the model will be shown)
    gw.call_tool("get_account", {"account_id": "ACC-2001"})   # ToolCall
    gw.close()
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx2
from anyio.from_thread import start_blocking_portal
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import MCPError

DEFAULT_URL = "http://127.0.0.1:8200/mcp"
REQUEST_TIMEOUT_S = 30  # above the server's worst case (~8 s for a CRM timeout, findings log)

# The server prefixes tool-failure text with this; the member-facing wording is what follows.
_SDK_PREFIX = re.compile(r"^Error executing tool [a-z_]+: ")


class GatewayError(RuntimeError):
    """Couldn't reach or talk to the MCP server at all (down, bad token, protocol error on connect)."""


@dataclass(frozen=True)
class ToolSpec:
    """One discovered tool, in the shape Claude's `tools` parameter wants (plus the read-only hint)."""

    name: str
    description: str
    input_schema: dict
    read_only: bool | None

    def for_claude(self) -> dict:
        return {"name": self.name, "description": self.description, "input_schema": self.input_schema}


@dataclass
class ToolCall:
    """The result of one tools/call, flattened for the agent.

    status:
      ok       -> data + source
      error    -> the tool ran and failed in an anticipated way (not_found,
                  unavailable, conflict); `error` is safe to show the member
      refused  -> the server refused before running the tool (forbidden,
                  invalid arguments); `error` says why, `code` is the JSON-RPC code
    """

    tool: str
    arguments: dict
    status: str
    data: Any = None
    source: dict | None = None
    error: str = ""
    code: int | None = None
    latency_ms: float = 0.0
    record_ids: list[str] = field(default_factory=list)


def tool_list_hash(tools: list[ToolSpec]) -> str:
    """A fingerprint of everything the model is shown about the tools. Changes
    when a tool is added, removed, renamed, re-described or re-typed."""
    canon = json.dumps([t.for_claude() for t in sorted(tools, key=lambda t: t.name)], sort_keys=True)
    return hashlib.sha256(canon.encode()).hexdigest()[:16]


class MCPGateway:
    def __init__(self, url: str, token: str):
        if not token:
            raise GatewayError("no MCP token: set HARBOR_MCP_TOKEN")
        self.url = url
        self._token = token
        self._portal_cm = None
        self._portal = None
        self._client_cm = None
        self._client: Client | None = None
        self._tools: list[ToolSpec] = []
        self.discovery: dict = {}

    @classmethod
    def from_env(cls) -> "MCPGateway":
        # The only two settings the agent has for reaching Harbor's data.
        return cls(os.environ.get("HARBOR_MCP_URL", DEFAULT_URL), os.environ.get("HARBOR_MCP_TOKEN", ""))

    # ------------------------------------------------------------ lifecycle

    def connect(self) -> "MCPGateway":
        self._portal_cm = start_blocking_portal()
        self._portal = self._portal_cm.__enter__()
        http = httpx2.AsyncClient(headers={"Authorization": f"Bearer {self._token}"}, timeout=REQUEST_TIMEOUT_S)
        client = Client(streamable_http_client(self.url, http_client=http))
        try:
            self._client_cm = self._portal.wrap_async_context_manager(client)
            self._client = self._client_cm.__enter__()
            self.refresh_tools()
        except BaseException as e:
            self._shutdown_portal()
            raise GatewayError(f"could not connect to MCP server at {self.url}: {_root_cause(e)}") from None
        return self

    def refresh_tools(self) -> list[ToolSpec]:
        """Ask the server what it offers now. Called on connect; call again to pick up changes."""
        result = self._portal.call(self._client.list_tools)
        self._tools = [ToolSpec(name=t.name, description=t.description or "", input_schema=t.input_schema,
                                read_only=getattr(t.annotations, "read_only_hint", None))
                       for t in result.tools]
        info = self._client.server_info
        self.discovery = {
            "url": self.url,
            "server": getattr(info, "name", None),
            "server_version": getattr(info, "version", None),
            "tools": sorted(t.name for t in self._tools),
            "tool_list_hash": tool_list_hash(self._tools),
        }
        return list(self._tools)

    def close(self) -> None:
        if self._client_cm is not None:
            try:
                self._client_cm.__exit__(None, None, None)
            except BaseException:
                pass  # closing a session that's already gone is not worth crashing over
            self._client_cm = self._client = None
        self._shutdown_portal()

    def _shutdown_portal(self) -> None:
        if self._portal_cm is not None:
            self._portal_cm.__exit__(None, None, None)
            self._portal_cm = self._portal = None

    def __enter__(self) -> "MCPGateway":
        return self.connect()

    def __exit__(self, *exc) -> None:
        self.close()

    # ------------------------------------------------------------ use

    def list_tools(self) -> list[ToolSpec]:
        return list(self._tools)

    def call_tool(self, name: str, arguments: dict) -> ToolCall:
        if self._client is None:
            raise GatewayError("not connected")
        t0 = time.perf_counter()
        call = ToolCall(tool=name, arguments=dict(arguments), status="error")
        try:
            result = self._portal.call(self._client.call_tool, name, arguments)
        except MCPError as e:
            call.status, call.error, call.code = "refused", e.error.message, e.error.code
        except Exception as e:
            call.status, call.error = "error", f"could not reach Harbor's records ({_root_cause(e)})"
        else:
            if result.is_error:
                text = " ".join(getattr(c, "text", "") for c in result.content or []).strip()
                call.error = _SDK_PREFIX.sub("", text) or "the tool failed"
            else:
                structured = result.structured_content or {}
                call.status = "ok"
                call.data = structured.get("data")
                call.source = structured.get("source")
                call.record_ids = list((call.source or {}).get("record_ids", []))
        call.latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        return call


def _root_cause(e: BaseException) -> str:
    """The SDK often raises an ExceptionGroup; show the first real error inside it."""
    while isinstance(e, BaseExceptionGroup) and e.exceptions:
        e = e.exceptions[0]
    return f"{type(e).__name__}: {e}"
