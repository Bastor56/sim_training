"""The closed set of tool-call outcomes (spec.md "Failure modes").

Backend reality (HTTP status codes, timeouts, database errors) is
translated into these names, and nothing else reaches the client or the
audit log.

How an outcome gets from a tool to the audit record: the middleware puts
an empty dict in CURRENT_CALL before running the tool. A tool that fails
raises ToolFailure, which writes its outcome into that dict as it's
created. The SDK then turns the exception into an `is_error` result for
the client, and the middleware reads the outcome back when it writes the
audit record. (The middleware can't catch the exception itself: the SDK
has already turned it into a result by then.)
"""

from __future__ import annotations

from contextvars import ContextVar

from mcp.server.mcpserver.exceptions import ToolError

OK = "ok"
NOT_FOUND = "not_found"
CONFLICT = "conflict"
UNAVAILABLE = "unavailable"
INVALID_ARGUMENTS = "invalid_arguments"
FORBIDDEN = "forbidden"
UNAUTHENTICATED = "unauthenticated"
ERROR = "error"  # a bug on our side: an exception nobody anticipated

CURRENT_CALL: ContextVar[dict | None] = ContextVar("harbor_mcp_current_call", default=None)


class ToolFailure(ToolError):
    """An anticipated failure. The client gets `message` as an error result it can read."""

    def __init__(self, outcome: str, message: str):
        super().__init__(message)
        self.outcome = outcome
        holder = CURRENT_CALL.get()
        if holder is not None:
            holder["outcome"] = outcome
