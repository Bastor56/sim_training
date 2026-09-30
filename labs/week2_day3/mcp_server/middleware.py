"""The enforcement point: every tools/call passes through here (spec.md "The server", R3-R5).

The SDK runs this middleware around EVERY inbound request, before it looks
up or validates anything. So a tool can't be called without passing these
checks, including a tool added later by someone who never read this file.

For tools/call, in this order:
  1. who is calling?        the bearer token's caller (the SDK already
                            answered 401 for an unknown token)
  2. may they call it?      permissions.is_allowed      -> refuse: forbidden
     Checked FIRST, so a caller without the grant learns nothing about the
     tool, not even which arguments it takes.
  3. are the arguments      validated against the tool's own advertised
     what it declared?      input schema, with undeclared keys refused
                            (credentials can't ride along, R4) -> refuse: invalid_arguments
  4. run the tool           the backend is touched only now
  5. audit record           always, in `finally`: allowed or denied,
                            success, anticipated failure or crash
"""

from __future__ import annotations

import time
from typing import Any, Callable

import jsonschema
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.shared.exceptions import MCPError
from mcp_types import INVALID_PARAMS

from . import outcomes
from .audit import AuditLog, new_audit_id, now_iso
from .permissions import PERMISSIONS, is_allowed

# JSON-RPC leaves -32000..-32099 for servers to define. MCP defines no
# "forbidden" code, so this one is ours, documented in TOOL_MANIFEST.md.
FORBIDDEN_CODE = -32003

REDACTED = "[redacted: undeclared argument]"


def _is_error(result: Any) -> bool:
    if isinstance(result, dict):
        return bool(result.get("isError") or result.get("is_error"))
    return bool(getattr(result, "is_error", False))


def _strict(schema: dict) -> dict:
    """The tool's advertised schema, with undeclared properties refused.

    Pydantic, which the SDK validates with, silently drops unknown
    arguments. Silently dropped is weaker than refused and logged, so we
    check against a copy that forbids them."""
    return {**schema, "additionalProperties": False}


def _schema_errors(schema: dict, arguments: dict) -> list[str]:
    """Field names and problem kinds only, never the values: a rejected
    value might be exactly the secret that must not be echoed back."""
    errors = []
    for e in jsonschema.Draft202012Validator(_strict(schema)).iter_errors(arguments):
        if e.validator == "additionalProperties":
            extra = sorted(set(arguments) - set(schema.get("properties", {})))
            errors.append(f"undeclared argument(s): {', '.join(extra)}")
        elif e.validator == "required":
            errors.append(f"missing required argument: {e.message.split(' ')[0]}")
        else:
            where = ".".join(str(p) for p in e.absolute_path) or "(arguments)"
            errors.append(f"{where}: fails '{e.validator}' check")
    return errors


def make_middleware(get_server: Callable[[], Any], audit: AuditLog, server_version: str,
                    permissions: dict[str, frozenset[str]] = PERMISSIONS):
    """Builds the middleware. `get_server` returns the MCPServer (it doesn't
    exist yet when the middleware is created), used to read tool schemas."""

    async def enforce(ctx, call_next):
        if ctx.method != "tools/call":
            return await call_next(ctx)

        t0 = time.perf_counter()
        token = get_access_token()
        caller = token.client_id if token else None
        params = ctx.params or {}
        tool = params.get("name")
        arguments = dict(params.get("arguments") or {})
        record = {
            "ts": now_iso(), "audit_id": new_audit_id(), "request_id": ctx.request_id,
            "caller": caller, "tool": tool, "arguments": arguments,
            "decision": "denied", "outcome": outcomes.ERROR, "error": None,
            "latency_ms": None, "server_version": server_version,
        }
        holder: dict = {}
        reset_token = outcomes.CURRENT_CALL.set(holder)
        try:
            # 2. authorization
            if not is_allowed(caller, tool, permissions):
                record.update(outcome=outcomes.FORBIDDEN, error=f"{caller} may not call {tool}")
                raise MCPError(FORBIDDEN_CODE, f"forbidden: {caller} may not call {tool}")

            # 3. arguments, against the tool's own advertised schema
            advertised = {t.name: t for t in await get_server().list_tools()}
            if tool not in advertised:
                # Granted but not registered: a policy/code mismatch on our side.
                record.update(outcome=outcomes.INVALID_ARGUMENTS, error=f"unknown tool {tool}")
                raise MCPError(INVALID_PARAMS, f"unknown tool: {tool}")
            schema = advertised[tool].input_schema
            declared = set(schema.get("properties", {}))
            # Never write an undeclared argument's value to the log.
            record["arguments"] = {k: (v if k in declared else REDACTED) for k, v in arguments.items()}
            problems = _schema_errors(schema, arguments)
            if problems:
                record.update(outcome=outcomes.INVALID_ARGUMENTS, error="; ".join(problems))
                raise MCPError(INVALID_PARAMS, f"invalid arguments for {tool}: {'; '.join(problems)}")

            # 4. run it
            record["decision"] = "allowed"
            result = await call_next(ctx)
            if _is_error(result):
                record["outcome"] = holder.get("outcome", outcomes.ERROR)
                content = result.get("content") if isinstance(result, dict) else getattr(result, "content", None)
                texts = [getattr(c, "text", None) or (c.get("text") if isinstance(c, dict) else None)
                         for c in (content or [])]
                record["error"] = " ".join(t for t in texts if t) or "tool error"
            else:
                record["outcome"] = outcomes.OK
            return result
        except MCPError:
            raise
        except Exception as e:
            record.update(outcome=outcomes.ERROR, error=f"{type(e).__name__}: {e}")
            raise
        finally:
            outcomes.CURRENT_CALL.reset(reset_token)
            record["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
            audit.write(record)

    return enforce
