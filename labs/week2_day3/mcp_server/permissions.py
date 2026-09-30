"""Authorization policy: which caller may call which tool (spec.md "Callers and permissions").

Kept in code, not config, because it's policy: a change to it should go
through review like any other code change.

Deny by default: a caller not listed, or a tool not listed for a caller, is
refused. A newly added tool is therefore refused for everyone until it's
deliberately granted here (spec.md known gap 4).
"""

from __future__ import annotations

# Every tool that only reads. Grow this as read tools are added.
READ_TOOLS: frozenset[str] = frozenset({
    "get_member",
    "list_cards",
    "list_member_accounts",
    "get_account",
    "list_transactions",
    "get_card_limits",  # granted 2026-09-28 with 0.2.0 (discovery demo); refused until this line existed
})

PERMISSIONS: dict[str, frozenset[str]] = {
    # The member-facing agent: reads only.
    "member_assistant": READ_TOOLS,
    # A contact-centre staff tool: reads, plus the one action.
    "contact_centre": READ_TOOLS | {"freeze_card"},
}


def is_allowed(caller: str | None, tool: str | None, permissions: dict[str, frozenset[str]] = PERMISSIONS) -> bool:
    if not caller or not tool:
        return False
    return tool in permissions.get(caller, frozenset())
