"""Pydantic models for the Harbor mock CRM's request/response bodies.

These are the schemas documented in contract.md. Copied from week 1
(labs/week1_day4/mock_crm) and reshaped for Harbor: members instead of
customers, and no accounts or transactions (those now live in core banking,
Postgres). Route handlers in app.py still build responses by hand, not via
FastAPI's `response_model`, so the malformed-body fault can return a body
that violates these schemas on purpose.
"""

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field

CardType = Literal["debit", "credit"]
CardStatus = Literal["active", "frozen", "lost"]

# One of week 1's four fault classes, or None for normal behaviour. Lives on
# Member records and applies to that member's CARD LISTING only -- see
# fixtures.py's module docstring.
SimulatedFault = Literal["server_error", "timeout", "malformed", "fail_then_recover"]


class Member(BaseModel):
    member_id: str
    name: str
    email: str
    member_since: date
    simulated_fault: Optional[SimulatedFault] = None


class MemberOut(BaseModel):
    """Member as returned over the wire -- simulated_fault is a fixture
    authoring detail, never exposed to a client."""

    member_id: str
    name: str
    email: str
    member_since: date


class Card(BaseModel):
    card_id: str
    member_id: str
    account_id: str  # the core-banking account the card draws on
    type: CardType
    last_four: str
    status: CardStatus


class CardLimits(BaseModel):
    """A card's own daily limits (added for harbor-mcp 0.2.0). Money as 2-decimal strings, like core banking."""

    card_id: str
    atm_daily_limit: str
    purchase_daily_limit: str
    currency: str = "USD"
    updated_on: date


class FreezeRequest(BaseModel):
    # Required and non-empty: a freeze without a stated reason is not
    # something a bank's card operations team would accept.
    reason: str = Field(min_length=1, max_length=500)


class ErrorEnvelope(BaseModel):
    error: str
    message: str
