"""Authentication: who is calling? (spec.md "Callers and permissions").

A static token -> caller map stands in for Harbor's identity provider. In
production this class is the one thing that changes (verify an OAuth / JWT
token instead); everything downstream only ever sees `AccessToken.client_id`.

An unknown token returns None, and the SDK's bearer middleware answers 401
before any MCP message is handled.
"""

from __future__ import annotations

import hmac

from mcp.server.auth.provider import AccessToken


class StaticTokenVerifier:
    def __init__(self, tokens: dict[str, str]):
        self._tokens = dict(tokens)  # token -> caller

    async def verify_token(self, token: str) -> AccessToken | None:
        # Compare against every known token with compare_digest (constant time),
        # rather than a dict lookup, so response timing leaks nothing about the token.
        for known, caller in self._tokens.items():
            if hmac.compare_digest(token.encode(), known.encode()):
                return AccessToken(token=token, client_id=caller, scopes=[])
        return None
