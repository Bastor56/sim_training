"""Fixture data for the mock CRM.

Design choice worth stating plainly: fault flags live on Account records
only, never on Customer records. Every documented customer ID resolves
normally at GET /customers/{id} -- it's specific *accounts* that are
flaky. This mirrors a real bank's system boundaries reasonably well
(customer/identity data tends to live in a more stable system than the
account/ledger data behind it) and keeps the fixture set easy to reason
about: "can I find this person" and "can I reach their account data" are
different questions with different answers.

Six customers:
  CUST-1001  Maria Chen     -- two normal accounts (ACC-2001, ACC-2002),
                                used for the multi-turn follow-up demo
                                ("and what about the other one?").
  CUST-1002  Devon Walsh    -- one normal account (ACC-2003) with zero
                                transactions -- "found, but empty" is not
                                the same thing as "not found."
  CUST-1003  Priya Natarajan -- ACC-2004 always 500s.
  CUST-1004  Sam Okafor      -- ACC-2005 always times out.
  CUST-1005  Elena Petrova   -- ACC-2006 always returns a malformed body.
  CUST-1006  Jordan Blake    -- ACC-2007 fails twice, then recovers on the
                                 3rd request -- the only fixture that
                                 proves the tool layer's retry policy can
                                 succeed, not just exhaust gracefully.

CUST-9999 and ACC-9999 are documented "known missing" IDs -- neither
exists in any table below, so they 404 with no special-casing required.
"""

import itertools
from typing import Dict, List

from schemas import Account, Card, Customer, Transaction

TIMEOUT_SLEEP_SECONDS_DEFAULT = 5.0
"""How long a timeout-flagged account sleeps before responding, when
MOCK_CRM_TIMEOUT_SLEEP_SECONDS isn't set. Overridable via env var so
tests can shrink it -- see app.py."""

CUSTOMERS: Dict[str, Customer] = {
    c.customer_id: c
    for c in [
        Customer(
            customer_id="CUST-1001",
            name="Maria Chen",
            email="maria.chen@example.com",
            since_date="2019-03-11",
        ),
        Customer(
            customer_id="CUST-1002",
            name="Devon Walsh",
            email="devon.walsh@example.com",
            since_date="2021-07-02",
        ),
        Customer(
            customer_id="CUST-1003",
            name="Priya Natarajan",
            email="priya.natarajan@example.com",
            since_date="2020-01-20",
        ),
        Customer(
            customer_id="CUST-1004",
            name="Sam Okafor",
            email="sam.okafor@example.com",
            since_date="2022-11-08",
        ),
        Customer(
            customer_id="CUST-1005",
            name="Elena Petrova",
            email="elena.petrova@example.com",
            since_date="2018-05-30",
        ),
        Customer(
            customer_id="CUST-1006",
            name="Jordan Blake",
            email="jordan.blake@example.com",
            since_date="2023-02-14",
        ),
    ]
}

ACCOUNTS: Dict[str, Account] = {
    a.account_id: a
    for a in [
        Account(
            account_id="ACC-2001",
            customer_id="CUST-1001",
            type="checking",
            balance=4210.55,
            status="active",
        ),
        Account(
            account_id="ACC-2002",
            customer_id="CUST-1001",
            type="savings",
            balance=15320.10,
            status="active",
        ),
        Account(
            account_id="ACC-2003",
            customer_id="CUST-1002",
            type="checking",
            balance=512.00,
            status="active",
        ),
        Account(
            account_id="ACC-2004",
            customer_id="CUST-1003",
            type="checking",
            balance=980.40,
            status="active",
            simulated_fault="server_error",
        ),
        Account(
            account_id="ACC-2005",
            customer_id="CUST-1004",
            type="checking",
            balance=2300.00,
            status="active",
            simulated_fault="timeout",
        ),
        Account(
            account_id="ACC-2006",
            customer_id="CUST-1005",
            type="savings",
            balance=7800.25,
            status="active",
            simulated_fault="malformed",
        ),
        Account(
            account_id="ACC-2007",
            customer_id="CUST-1006",
            type="checking",
            balance=1150.75,
            status="active",
            simulated_fault="fail_then_recover",
        ),
    ]
}

# customer_id -> that customer's account_ids, in display order.
CUSTOMER_ACCOUNTS: Dict[str, List[str]] = {
    "CUST-1001": ["ACC-2001", "ACC-2002"],
    "CUST-1002": ["ACC-2003"],
    "CUST-1003": ["ACC-2004"],
    "CUST-1004": ["ACC-2005"],
    "CUST-1005": ["ACC-2006"],
    "CUST-1006": ["ACC-2007"],
}

TRANSACTIONS: Dict[str, List[Transaction]] = {
    "ACC-2001": [
        Transaction(
            transaction_id="TXN-3001",
            account_id="ACC-2001",
            date="2026-09-10",
            amount=-42.10,
            description="Green Leaf Grocery",
            category="groceries",
        ),
        Transaction(
            transaction_id="TXN-3002",
            account_id="ACC-2001",
            date="2026-09-08",
            amount=-15.00,
            description="Metro Transit",
            category="transport",
        ),
        Transaction(
            transaction_id="TXN-3003",
            account_id="ACC-2001",
            date="2026-09-01",
            amount=2400.00,
            description="Payroll Deposit",
            category="income",
        ),
        Transaction(
            transaction_id="TXN-3004",
            account_id="ACC-2001",
            date="2026-08-27",
            amount=-89.99,
            description="Citywide Electric",
            category="utilities",
        ),
    ],
    "ACC-2002": [
        Transaction(
            transaction_id="TXN-3101",
            account_id="ACC-2002",
            date="2026-09-05",
            amount=500.00,
            description="Transfer from Checking",
            category="transfer",
        ),
        Transaction(
            transaction_id="TXN-3102",
            account_id="ACC-2002",
            date="2026-08-05",
            amount=500.00,
            description="Transfer from Checking",
            category="transfer",
        ),
        Transaction(
            transaction_id="TXN-3103",
            account_id="ACC-2002",
            date="2026-07-31",
            amount=18.22,
            description="Interest Payment",
            category="interest",
        ),
    ],
    # ACC-2003 intentionally has no key here -- an account that exists but
    # has never had a transaction. Accessed via TRANSACTIONS.get(id, []).
    "ACC-2004": [],
    "ACC-2005": [],
    "ACC-2006": [],
    "ACC-2007": [],
}

CARDS: Dict[str, List[Card]] = {
    "ACC-2001": [Card(card_id="CARD-4001", account_id="ACC-2001", last_four="4471", status="active")],
    "ACC-2002": [],
    "ACC-2003": [Card(card_id="CARD-4003", account_id="ACC-2003", last_four="9012", status="active")],
    "ACC-2004": [Card(card_id="CARD-4004", account_id="ACC-2004", last_four="1123", status="active")],
    "ACC-2005": [Card(card_id="CARD-4005", account_id="ACC-2005", last_four="5567", status="active")],
    "ACC-2006": [Card(card_id="CARD-4006", account_id="ACC-2006", last_four="8890", status="frozen")],
    "ACC-2007": [Card(card_id="CARD-4007", account_id="ACC-2007", last_four="2234", status="active")],
}

# Documented "known missing" IDs -- absent from every table above on
# purpose, so GET /customers/CUST-9999 and GET /accounts/ACC-9999 404
# with no special-case code required anywhere in app.py.
KNOWN_MISSING_CUSTOMER_ID = "CUST-9999"
KNOWN_MISSING_ACCOUNT_ID = "ACC-9999"

# account_id -> number of times it's been requested since the last
# reset. Backs the "fail_then_recover" fault: request 1 and 2 fail,
# request 3 succeeds, then the cycle repeats. Module-level and mutable
# on purpose -- app.py and tests share this process's fixture state.
_fault_attempt_counts: Dict[str, itertools.count] = {}


def next_fault_attempt(account_id: str) -> int:
    """Returns the 1-indexed attempt number for this account_id's
    fail_then_recover fault, incrementing as a side effect."""
    counter = _fault_attempt_counts.setdefault(account_id, itertools.count(1))
    return next(counter)


def reset_fault_counters() -> None:
    """Resets all fail_then_recover attempt counters. Call this in test
    setup so tests don't depend on how many times a previous test (or a
    previous run of the same test) already hit the same account."""
    _fault_attempt_counts.clear()
