"""harbor-mcp: builds and runs the server (spec.md "The server").

    uv run python -m mcp_server.server        # Streamable HTTP on 127.0.0.1:8200/mcp

The layers a request goes through, outermost first:
  1. audit_unauthenticated   records requests refused with 401 (no MCP message was read)
  2. the SDK's bearer auth   token -> caller, or 401
  3. middleware.enforce      authorization, argument check, audit record (every tools/call)
  4. the tool                touches the backend
"""

from __future__ import annotations

import time

import uvicorn
from mcp.server import MCPServer
from mcp.server.auth.settings import AuthSettings

from . import config as config_module
from . import outcomes, tools
from .audit import AuditLog, new_audit_id, now_iso
from .auth import StaticTokenVerifier
from .backends import CoreBanking, CRMClient
from .middleware import make_middleware
from .permissions import PERMISSIONS

SERVER_NAME = "harbor-mcp"
SERVER_VERSION = "0.2.0"  # bump with every change to the advertised tools; see TOOL_MANIFEST.md

INSTRUCTIONS = (
    "Harbor Credit Union's member records: CRM (members, cards) and core banking "
    "(accounts, transactions). Every result carries a `source` block naming the record it came from. "
    "Calls are authorized per caller and per tool, and every call is audited."
)


def build_server(cfg: config_module.ServerConfig, *, crm, core, audit: AuditLog,
                 permissions: dict[str, frozenset[str]] = PERMISSIONS,
                 version: str = SERVER_VERSION) -> MCPServer:
    """The MCP server with its backends injected (tests pass fakes)."""
    server: MCPServer | None = None
    enforce = make_middleware(lambda: server, audit, version, permissions)
    server = MCPServer(
        SERVER_NAME,
        version=version,
        instructions=INSTRUCTIONS,
        token_verifier=StaticTokenVerifier(cfg.tokens),
        # The SDK needs these URLs to publish its resource metadata. There is
        # no real authorization server: tokens are static (spec.md known gap 2).
        # validate_token_resource=False: a static token has no audience
        # ("which server was this issued for?") to check. With OAuth tokens this
        # must become True, so a token issued for another service is refused here.
        auth=AuthSettings(issuer_url=f"http://{cfg.host}:{cfg.port}", resource_server_url=cfg.url,
                          validate_token_resource=False),
        middleware=[enforce],
    )
    tools.register(server, crm, core, version)
    return server


class AuditUnauthenticated:
    """ASGI wrapper: writes an audit line for every request answered with 401.

    Those requests never reach the middleware (the SDK refuses them first),
    so without this they'd leave no trace. The rejected token is NOT
    logged: it may be a real token for another system, typed wrongly."""

    def __init__(self, app, audit: AuditLog, version: str):
        self.app, self.audit, self.version = app, audit, version

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        t0 = time.perf_counter()

        async def send_and_watch(message):
            if message["type"] == "http.response.start" and message["status"] == 401:
                client = scope.get("client") or ("?", 0)
                self.audit.write({
                    "ts": now_iso(), "audit_id": new_audit_id(), "request_id": None,
                    "caller": None, "tool": None, "arguments": None,
                    "decision": "denied", "outcome": outcomes.UNAUTHENTICATED,
                    "error": "missing or unknown bearer token",
                    "http": {"method": scope.get("method"), "path": scope.get("path"), "client": client[0]},
                    "latency_ms": round((time.perf_counter() - t0) * 1000, 1), "server_version": self.version,
                })
            await send(message)

        await self.app(scope, receive, send_and_watch)


def build_app(server: MCPServer, audit: AuditLog, cfg: config_module.ServerConfig):
    return AuditUnauthenticated(server.streamable_http_app(host=cfg.host), audit, server.version)


def main() -> None:
    cfg = config_module.load()
    audit = AuditLog(cfg.audit_path)
    crm = CRMClient.from_config(cfg.crm_base_url, cfg.crm_api_key)
    core = CoreBanking.from_config(cfg.db_host, cfg.db_port, cfg.db_name, cfg.db_user, cfg.db_password)
    server = build_server(cfg, crm=crm, core=core, audit=audit)
    import anyio

    tool_names = sorted(t.name for t in anyio.run(server.list_tools))
    print(f"{SERVER_NAME} {server.version} on {cfg.url}")
    print(f"  tools ({len(tool_names)}): {', '.join(tool_names)}")
    print(f"  callers: {', '.join(sorted(set(cfg.tokens.values())))}")
    print(f"  audit log: {cfg.audit_path}")
    uvicorn.run(build_app(server, audit, cfg), host=cfg.host, port=cfg.port, log_level="warning")


if __name__ == "__main__":
    main()
