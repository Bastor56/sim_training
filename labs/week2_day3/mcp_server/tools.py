"""The tools harbor-mcp advertises (spec.md "Tools", TOOL_MANIFEST.md).

Each tool is thin: no argument checks (the middleware already validated the
arguments against this function's own schema), one backend call, and the
data returned with a server-stamped `source` block.

Descriptions are written for routing (R1). A client model picks tools from
these words alone, so each says what it returns, when to use it, what it
needs, and what it does NOT do. The annotations (read-only, destructive,
idempotent) are MCP's standard hints, visible to clients at discovery.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any

from mcp_types import ToolAnnotations
from pydantic import BaseModel, Field

MEMBER_ID = Annotated[str, Field(description="Harbor member ID, e.g. M-1001", pattern=r"^M-\d{4}$")]
ACCOUNT_ID = Annotated[str, Field(description="Core-banking account ID, e.g. ACC-2001", pattern=r"^ACC-\d{4}$")]
CARD_ID = Annotated[str, Field(description="Card ID, e.g. CARD-4001", pattern=r"^CARD-\d{4}$")]

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)


class Source(BaseModel):
    """Where a result came from. Stamped by the server; the agent copies it into its source line."""

    system: str  # harbor_crm | harbor_core_banking
    record_type: str
    record_ids: list[str]  # the records returned (can be empty: "looked, found none")
    lookup: dict[str, Any]  # the key that was looked up, so an empty result still names what was searched
    tool: str
    server: str
    server_version: str
    fetched_at: str


class ToolResult(BaseModel):
    data: Any
    source: Source


def register(mcp, crm, core, server_version: str) -> None:
    def stamp(tool: str, system: str, record_type: str, record_ids: list[str], **lookup) -> Source:
        return Source(system=system, record_type=record_type, record_ids=record_ids, lookup=lookup, tool=tool,
                      server="harbor-mcp", server_version=server_version,
                      fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"))

    # ------------------------------------------------------------ CRM

    @mcp.tool(annotations=READ_ONLY)
    def get_member(member_id: MEMBER_ID) -> ToolResult:
        """Look up a Harbor member's profile in the CRM: name, email and member-since date.

        Use to confirm who the member is or how long they've been a member.
        Does not return accounts, balances or cards (use list_member_accounts or list_cards).
        """
        member = crm.get_member(member_id)
        return ToolResult(data=member, source=stamp("get_member", crm.system, "member",
                                                    [member["member_id"]], member_id=member_id))

    @mcp.tool(annotations=READ_ONLY)
    def list_cards(member_id: MEMBER_ID) -> ToolResult:
        """List a member's payment cards from the CRM: card ID, type (debit/credit), last four digits,
        status (active / frozen / lost) and the account each card draws on.

        Use when the member asks about their cards, whether a card is active or frozen, or needs a
        card ID (for example before a freeze). Does not return spending limits or transactions.
        """
        cards = crm.list_cards(member_id)
        return ToolResult(data=cards, source=stamp("list_cards", crm.system, "card",
                                                   [c["card_id"] for c in cards], member_id=member_id))

    @mcp.tool(annotations=READ_ONLY)
    def get_card_limits(card_id: CARD_ID) -> ToolResult:
        """A card's own current daily limits from the CRM: the ATM cash withdrawal limit and the purchase
        (point-of-sale) limit, in USD as decimal strings, and when they were last changed.

        Use when the member asks about the limits on their own card. These are the card's actual limits,
        which can differ from Harbor's standard limits. Needs a card ID (from list_cards). Does not change
        limits and does not return transactions.
        """
        limits = crm.get_card_limits(card_id)
        return ToolResult(data=limits, source=stamp("get_card_limits", crm.system, "card limits",
                                                    [limits["card_id"]], card_id=card_id))

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True,
                                          open_world_hint=False))
    def freeze_card(card_id: CARD_ID,
                    reason: Annotated[str, Field(description="Why the card is being frozen, as stated by the member "
                                                             "or staff, e.g. 'member reports card lost'",
                                                 min_length=1, max_length=500)]) -> ToolResult:
        """Freeze a card in the CRM so it can't be used. CHANGES DATA: sets the card's status to frozen.

        Use only when the member explicitly asks to freeze or block a card. Needs the card ID
        (from list_cards). Freezing an already-frozen card changes nothing. A card already
        reported lost can't be frozen (it's already permanently blocked). Restricted: most
        callers are not permitted to use this tool.
        """
        card = crm.freeze_card(card_id, reason)
        return ToolResult(data=card, source=stamp("freeze_card", crm.system, "card", [card["card_id"]],
                                                  card_id=card_id))

    # ------------------------------------------------------------ core banking

    @mcp.tool(annotations=READ_ONLY)
    def list_member_accounts(member_id: MEMBER_ID) -> ToolResult:
        """List a member's accounts from core banking: account ID, type (checking / savings / credit),
        current balance (USD, as a decimal string), status and opening date.

        Use first for any question about the member's own accounts or balances, to find the right
        account ID. Returns an empty list if core banking has no accounts for this member ID; it does
        not check the member exists (use get_member). Does not return transactions.
        """
        accounts = core.list_member_accounts(member_id)
        return ToolResult(data=accounts, source=stamp("list_member_accounts", core.system, "account",
                                                      [a["account_id"] for a in accounts], member_id=member_id))

    @mcp.tool(annotations=READ_ONLY)
    def get_account(account_id: ACCOUNT_ID) -> ToolResult:
        """Current balance (USD, decimal string), type, status and opening date of ONE account, from core
        banking.

        Use when the member asks about a specific account's balance or status. Needs an account ID;
        to find a member's account IDs use list_member_accounts. Does not return transactions.
        """
        account = core.get_account(account_id)
        return ToolResult(data=account, source=stamp("get_account", core.system, "account",
                                                     [account["account_id"]], account_id=account_id))

    @mcp.tool(annotations=READ_ONLY)
    def list_transactions(account_id: ACCOUNT_ID,
                          limit: Annotated[int, Field(description="How many of the most recent transactions "
                                                                  "to return", ge=1, le=50)] = 10) -> ToolResult:
        """Most recent posted transactions on ONE account, newest first, from core banking: date, amount
        (USD decimal string; negative = money out), description and category (e.g. groceries, transport).

        Use for questions about recent spending, deposits, payments or a specific charge. Needs an account
        ID (from list_member_accounts). An empty list means the account exists but has no transactions.
        Does not return pending transactions or card authorizations.
        """
        txns = core.list_transactions(account_id, limit)
        return ToolResult(data=txns, source=stamp("list_transactions", core.system, "transaction",
                                                  [t["transaction_id"] for t in txns],
                                                  account_id=account_id, limit=limit))
