"""The server's configuration, from mcp_server/.env only (spec.md "Backend credentials").

This is the one module that reads the server's secrets. The agent never
imports it (tests/test_no_bypass.py), and nothing here is ever sent to a
client.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent
ENV_FILE = SERVER_DIR / ".env"
AUDIT_PATH = SERVER_DIR / "audit" / "audit.jsonl"

TOKEN_PREFIX = "MCP_TOKEN_"  # MCP_TOKEN_MEMBER_ASSISTANT=<token>  ->  caller "member_assistant"


@dataclass(frozen=True)
class ServerConfig:
    # bearer token -> caller identity. repr=False: never printed in a log or traceback.
    tokens: dict[str, str] = field(repr=False)
    crm_base_url: str
    crm_api_key: str = field(repr=False)
    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str = field(repr=False)
    host: str = "127.0.0.1"
    port: int = 8200
    audit_path: Path = AUDIT_PATH

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/mcp"


def read_env(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        name, sep, value = line.partition("=")
        if sep and not name.strip().startswith("#"):
            values[name.strip()] = value.strip().strip("\"'")
    return values


def load(env_file: Path = ENV_FILE) -> ServerConfig:
    env = read_env(env_file)
    placeholders = sorted(k for k, v in env.items() if v in ("", "replace-me"))
    if placeholders:
        raise RuntimeError(f"{env_file} still has placeholder values for: {', '.join(placeholders)}")
    tokens = {v: k[len(TOKEN_PREFIX):].lower() for k, v in env.items() if k.startswith(TOKEN_PREFIX)}
    if len(tokens) != sum(k.startswith(TOKEN_PREFIX) for k in env):
        raise RuntimeError("two callers share the same token; every caller needs its own")
    return ServerConfig(
        tokens=tokens,
        crm_base_url=env["CRM_BASE_URL"],
        crm_api_key=env["CRM_API_KEY"],
        db_host=env["HARBOR_DB_HOST"],
        db_port=int(env["HARBOR_DB_PORT"]),
        db_name=env["HARBOR_DB_NAME"],
        db_user=env["HARBOR_DB_USER"],
        db_password=env["HARBOR_DB_PASSWORD"],
        host=env.get("MCP_HOST", "127.0.0.1"),
        port=int(env.get("MCP_PORT", "8200")),
    )
