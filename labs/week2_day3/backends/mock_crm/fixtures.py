"""Fixture data for the Harbor mock CRM.

Copied from week 1 and re-keyed: CUST-100x -> Harbor member M-100x, same
people. Accounts and transactions moved to core banking (Postgres, see
supabase/seed.sql); the CRM keeps members and their cards.

Design choice carried over from week 1, with one change: fault flags live on
Member records but apply only to that member's CARD LISTING
(GET /members/{id}/cards). Member lookups never fault. Week 1 put them on
account detail lookups; accounts aren't in the CRM any more, and card
listing is the CRM call the agent makes most often after the member lookup.

Six members:
  M-1001  Maria Chen       -- one active debit card (CARD-4001). The freeze demo.
  M-1002  Devon Walsh      -- one active debit card and one card already
                              reported lost (CARD-4008): freezing it is a 409.
  M-1003  Priya Natarajan  -- card listing always 500s.
  M-1004  Sam Okafor       -- card listing always times out.
  M-1005  Elena Petrova    -- card listing always returns a malformed body.
  M-1006  Jordan Blake     -- card listing fails twice, then recovers on the
                              3rd request: the only fixture that proves a
                              retry policy can succeed, not just give up.

M-9999 and CARD-9999 are documented "known missing" IDs (404).

Cards are MUTABLE: POST /cards/{id}/freeze changes CARDS in place. reset()
restores the initial state, for tests and between demo runs.
"""

import copy
import itertools
from typing import Dict, List

from schemas import Card, CardLimits, Member

TIMEOUT_SLEEP_SECONDS_DEFAULT = 5.0
"""How long a timeout-flagged listing sleeps before responding, when
MOCK_CRM_TIMEOUT_SLEEP_SECONDS isn't set. Overridable via env var so tests
can shrink it -- see app.py."""

MEMBERS: Dict[str, Member] = {
    m.member_id: m
    for m in [
        Member(member_id="M-1001", name="Maria Chen", email="maria.chen@example.com",
               member_since="2019-03-11"),
        Member(member_id="M-1002", name="Devon Walsh", email="devon.walsh@example.com",
               member_since="2021-07-02"),
        Member(member_id="M-1003", name="Priya Natarajan", email="priya.natarajan@example.com",
               member_since="2020-01-20", simulated_fault="server_error"),
        Member(member_id="M-1004", name="Sam Okafor", email="sam.okafor@example.com",
               member_since="2022-11-08", simulated_fault="timeout"),
        Member(member_id="M-1005", name="Elena Petrova", email="elena.petrova@example.com",
               member_since="2018-05-30", simulated_fault="malformed"),
        Member(member_id="M-1006", name="Jordan Blake", email="jordan.blake@example.com",
               member_since="2023-02-14", simulated_fault="fail_then_recover"),
    ]
}

_INITIAL_CARDS: List[Card] = [
    Card(card_id="CARD-4001", member_id="M-1001", account_id="ACC-2001", type="debit", last_four="4471", status="active"),
    Card(card_id="CARD-4003", member_id="M-1002", account_id="ACC-2003", type="debit", last_four="9012", status="active"),
    Card(card_id="CARD-4008", member_id="M-1002", account_id="ACC-2003", type="debit", last_four="3350", status="lost"),
    Card(card_id="CARD-4004", member_id="M-1003", account_id="ACC-2004", type="debit", last_four="1123", status="active"),
    Card(card_id="CARD-4005", member_id="M-1004", account_id="ACC-2005", type="debit", last_four="5567", status="active"),
    Card(card_id="CARD-4006", member_id="M-1005", account_id="ACC-2006", type="debit", last_four="8890", status="frozen"),
    Card(card_id="CARD-4007", member_id="M-1006", account_id="ACC-2007", type="debit", last_four="2234", status="active"),
]

# card_id -> that card's own daily limits (GET /cards/{id}/limits, added for the
# discovery demo). Harbor's standard is $500 ATM / $3,000 purchases (the Debit
# Card Limits document); CARD-4001 carries a raised limit on purpose, so an
# answer from the card's record is visibly different from one from the policy.
CARD_LIMITS: Dict[str, CardLimits] = {
    card_id: CardLimits(card_id=card_id, atm_daily_limit=atm, purchase_daily_limit=pos, updated_on=updated)
    for card_id, atm, pos, updated in [
        ("CARD-4001", "800.00", "5000.00", "2026-06-14"),
        ("CARD-4003", "500.00", "3000.00", "2021-07-02"),
        ("CARD-4008", "500.00", "3000.00", "2021-07-02"),
        ("CARD-4004", "500.00", "3000.00", "2020-01-20"),
        ("CARD-4005", "500.00", "3000.00", "2022-11-08"),
        ("CARD-4006", "500.00", "3000.00", "2018-05-30"),
        ("CARD-4007", "500.00", "3000.00", "2023-02-14"),
    ]
}

# card_id -> Card. Mutated by the freeze endpoint; restored by reset().
CARDS: Dict[str, Card] = {}

KNOWN_MISSING_MEMBER_ID = "M-9999"
KNOWN_MISSING_CARD_ID = "CARD-9999"

# member_id -> attempts since the last reset. Backs "fail_then_recover":
# requests 1 and 2 fail, request 3 succeeds, then the cycle repeats.
_fault_attempt_counts: Dict[str, itertools.count] = {}


def cards_for_member(member_id: str) -> List[Card]:
    return [c for c in CARDS.values() if c.member_id == member_id]


def next_fault_attempt(member_id: str) -> int:
    """The 1-indexed attempt number for this member's fail_then_recover
    fault, incrementing as a side effect."""
    counter = _fault_attempt_counts.setdefault(member_id, itertools.count(1))
    return next(counter)


def reset() -> None:
    """Restore every card to its initial state and clear fault counters."""
    CARDS.clear()
    CARDS.update({c.card_id: copy.deepcopy(c) for c in _INITIAL_CARDS})
    _fault_attempt_counts.clear()


reset()
