"""R3 evidence: a client-side allow-list is not enforcement; the server is (plan.md milestone 9).

The agent can be run with `--allow-tools` so the model is never SHOWN
freeze_card. That's a convenience, not a control: anyone holding the same
token can write their own MCP client and skip it. This script is that
client. It does not import the agent, so the agent's allow-list can play no
part in what happens, and it calls each case directly on the server:

  1. permitted       member_assistant -> get_account           expect: ok
  2. the bypass      member_assistant -> freeze_card           expect: refused by the SERVER (forbidden)
  3. right caller    contact_centre   -> freeze_card           expect: ok (the server tells callers apart)
  4. credentials     member_assistant -> get_account + db_password   expect: refused (invalid_arguments), value redacted
  5. bad token       wrong token      -> connect               expect: HTTP 401, audited without the token

After each case it prints the audit lines the server wrote for it.

    HARBOR_MCP_TOKEN=<member token> HARBOR_MCP_TOKEN_CC=<contact-centre token> \\
        uv run python scripts/bypass_allowlist.py

Case 3 really freezes CARD-4001: reset the CRM afterwards (POST /admin/reset).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import MCPError

URL = os.environ.get("HARBOR_MCP_URL", "http://127.0.0.1:8200/mcp")
AUDIT = Path(__file__).resolve().parent.parent / "mcp_server" / "audit" / "audit.jsonl"


def audit_lines() -> list[dict]:
    if not AUDIT.exists():
        return []
    return [json.loads(line) for line in AUDIT.read_text(encoding="utf-8").splitlines() if line.strip()]


def client(token: str) -> Client:
    return Client(streamable_http_client(URL, http_client=httpx2.AsyncClient(
        headers={"Authorization": f"Bearer {token}"})))


def root(e: BaseException) -> BaseException:
    while isinstance(e, BaseExceptionGroup) and e.exceptions:
        e = e.exceptions[0]
    return e


async def call(token: str, tool: str, args: dict) -> str:
    try:
        async with client(token) as c:
            try:
                r = await c.call_tool(tool, args)
            except MCPError as e:
                return f"REFUSED BY SERVER  code={e.error.code}  {e.error.message}"
            if r.is_error:
                return f"TOOL ERROR  {r.content[0].text}"
            return f"OK  data={json.dumps(r.structured_content['data'])}"
    except BaseException as e:  # a failed connect surfaces as an exception group
        return f"CONNECTION REFUSED  {type(root(e)).__name__}: {root(e)}"


async def main() -> int:
    member, cc = os.environ.get("HARBOR_MCP_TOKEN", ""), os.environ.get("HARBOR_MCP_TOKEN_CC", "")
    if not member or not cc:
        print("set HARBOR_MCP_TOKEN (member_assistant) and HARBOR_MCP_TOKEN_CC (contact_centre)", file=sys.stderr)
        return 1
    cases = [
        ("1. permitted", member, "get_account", {"account_id": "ACC-2001"}),
        ("2. the bypass: member token, freeze_card, no agent and no allow-list involved", member, "freeze_card",
         {"card_id": "CARD-4001", "reason": "bypass test"}),
        ("3. right caller: contact-centre token, same call", cc, "freeze_card",
         {"card_id": "CARD-4001", "reason": "member reports card lost"}),
        ("4. credentials smuggled as an argument", member, "get_account",
         {"account_id": "ACC-2001", "db_password": "hunter2"}),
        ("5. bad token", "not-a-real-token", "get_account", {"account_id": "ACC-2001"}),
    ]
    for title, token, tool, args in cases:
        before = len(audit_lines())
        shown = {k: ("hunter2" if k == "db_password" else v) for k, v in args.items()}
        print(f"\n=== {title}\n    call    {tool}({json.dumps(shown)})")
        print(f"    result  {await call(token, tool, args)}")
        for line in audit_lines()[before:]:
            keep = {k: line.get(k) for k in ("caller", "tool", "arguments", "decision", "outcome", "error")}
            print(f"    audit   {json.dumps(keep)}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
