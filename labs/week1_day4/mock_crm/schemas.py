"""Pydantic models for the mock CRM's request/response bodies.

These are the schemas documented in contract.md. Route handlers in app.py
build responses from these models by hand (rather than relying on
FastAPI's `response_model` validation) specifically so the malformed-body
fault can return a body that violates this schema on purpose -- see the
note in app.py's `_malformed_response`.
"""

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel

AccountType = Literal["checking", "savings", "credit"]
AccountStatus = Literal["active", "frozen", "closed"]
CardStatus = Literal["active", "frozen", "lost"]

# One of the four fault classes the lab requires, or None for normal
# behavior. Lives on Account records only -- see fixtures.py's module
# docstring for why customer lookups are never fault-flagged.
SimulatedFault = Literal["server_error", "timeout", "malformed", "fail_then_recover"]


class Customer(BaseModel):
    customer_id: str
    name: str
    email: str
    since_date: date


class Account(BaseModel):
    account_id: str
    customer_id: str
    type: AccountType
    balance: float
    status: AccountStatus
    simulated_fault: Optional[SimulatedFault] = None


class AccountOut(BaseModel):
    """Account as returned over the wire -- simulated_fault is a fixture
    authoring detail, never exposed to a client."""

    account_id: str
    customer_id: str
    type: AccountType
    balance: float
    status: AccountStatus


class Transaction(BaseModel):
    transaction_id: str
    account_id: str
    date: date
    amount: float
    description: str
    category: str


class Card(BaseModel):
    card_id: str
    account_id: str
    last_four: str
    status: CardStatus


class ErrorEnvelope(BaseModel):
    error: str
    message: str
