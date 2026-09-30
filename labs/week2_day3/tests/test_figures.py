"""Dollar figures in record answers must trace to cited records (agent/figures.py; milestone 7 decision)."""

from decimal import Decimal

import pytest

import figures
import fakes
from test_tool_path import GATE_TOOL, STOP, Script, answered, ok, run, source

# The exact data from the milestone 7 live run (runs/adhoc, question 2).
TXNS = [
    {"transaction_id": "TXN-3010", "posted_on": "2026-09-26", "amount": "-63.48", "description": "Green Leaf Grocery", "category": "groceries"},
    {"transaction_id": "TXN-3009", "posted_on": "2026-09-24", "amount": "-12.50", "description": "Harbor Coffee Co.", "category": "dining"},
    {"transaction_id": "TXN-3008", "posted_on": "2026-09-23", "amount": "-38.17", "description": "Green Leaf Grocery", "category": "groceries"},
    {"transaction_id": "TXN-3003", "posted_on": "2026-09-01", "amount": "2400.00", "description": "Payroll Deposit", "category": "income"},
    {"transaction_id": "TXN-3001", "posted_on": "2026-09-10", "amount": "-42.10", "description": "Green Leaf Grocery", "category": "groceries"},
]
ACCOUNT = {"account_id": "ACC-2001", "type": "checking", "balance": "4210.55"}
RESULTS = [{"i": 1, "data": [ACCOUNT]}, {"i": 2, "data": TXNS}]
GROCERIES = {"TXN-3010", "TXN-3008", "TXN-3001"}


def test_the_live_failure_is_caught():
    live = ("You've spent $144.75 on groceries recently. Your last three grocery purchases were $63.48 ..., "
            "$38.17 ... and $42.10 ...")
    assert figures.check(live, RESULTS, GROCERIES)["unverified"] == ["144.75"]


def test_the_correct_total_passes():
    right = "You've spent $143.75 on groceries: $63.48, $38.17 and $42.10."
    assert figures.check(right, RESULTS, GROCERIES) == {"figures": ["143.75", "63.48", "38.17", "42.10"],
                                                       "unverified": []}


def test_a_total_over_records_that_were_not_cited_fails():
    # $156.25 = the three groceries + the coffee; the coffee wasn't cited.
    assert figures.check("You spent $156.25.", RESULTS, GROCERIES)["unverified"] == ["156.25"]


def test_a_figure_from_an_uncited_record_fails():
    assert figures.check("Your balance is $4,210.55.", RESULTS, GROCERIES)["unverified"] == ["4210.55"]
    assert figures.check("Your balance is $4,210.55.", RESULTS, {"ACC-2001"})["unverified"] == []


@pytest.mark.parametrize("text,expected", [
    ("$4,210.55", ["4210.55"]), ("$30", ["30.00"]), ("$ 63.48", ["63.48"]), ("-$63.48", ["63.48"]),
    ("$1,200.5", ["1200.50"]), ("on September 26, card ending 4471, 3 purchases", []),
])
def test_figure_extraction(text, expected):
    assert [str(f) for f in figures.figures_in(text)] == expected


def test_money_in_and_money_out_totals_are_both_allowed():
    allowed = figures.allowed_figures([t for t in TXNS if t["transaction_id"] in {"TXN-3010", "TXN-3003"}])
    assert Decimal("63.48") in allowed and Decimal("2400.00") in allowed      # each value
    assert Decimal("2336.52") in allowed                                      # net: 2400.00 - 63.48
    assert allowed >= {Decimal("63.48"), Decimal("2400.00")}                  # out-only and in-only totals


def test_no_figures_passes():
    assert figures.check("Your debit card ending 4471 has been frozen.", RESULTS, set())["unverified"] == []


# ---------------------------------------------------------------- in the graph

class TxnGateway:
    def list_tools(self):
        from test_tool_path import TOOLS
        return TOOLS

    def call_tool(self, name, arguments):
        return ok(name, TXNS, source(name, "harbor_core_banking", "transaction",
                                     [t["transaction_id"] for t in TXNS], account_id="ACC-2001", limit=10))


@pytest.mark.parametrize("text,outcome", [
    ("You've spent $144.75 on groceries recently.", "records_blocked"),
    ("You've spent $143.75 on groceries recently.", "answered_from_records"),
])
def test_graph_blocks_a_wrong_total_and_passes_a_right_one(lab, text, outcome):
    script = Script(gate=[GATE_TOOL],
                    tool_select=[fakes.tool_response(("list_transactions", {"account_id": "ACC-2001"})), STOP],
                    generate_from_tools=[answered(*sorted(GROCERIES), text=text)])
    state, row = run(lab, script, TxnGateway(), question="What did I spend on groceries recently?")
    assert row["outcome"] == outcome
    if outcome == "records_blocked":
        assert "$144.75" in row["outcome_reason"] and "144.75" not in state.reply


def test_a_cannot_answer_reply_is_figure_checked_too(lab):
    """Tool eval t09: a "cannot_answer" explanation mentioned $512.00. True, but unchecked: the figure
    check only covered "answered". Any figure shown to the member must come from a returned record."""
    cannot = {"status": "cannot_answer", "cited_record_ids": [], "reason": "no savings account",
              "answer": "I don't see a savings account. Your checking has $999.99."}
    script = Script(gate=[GATE_TOOL],
                    tool_select=[fakes.tool_response(("list_transactions", {"account_id": "ACC-2001"})), STOP],
                    generate_from_tools=[cannot])
    state, row = run(lab, script, TxnGateway())
    assert row["outcome"] == "records_blocked" and "999.99" not in state.reply

    honest = {**cannot, "answer": "I don't see a savings account. Your most recent purchase was $63.48."}
    script = Script(gate=[GATE_TOOL],
                    tool_select=[fakes.tool_response(("list_transactions", {"account_id": "ACC-2001"})), STOP],
                    generate_from_tools=[honest])
    state, row = run(lab, script, TxnGateway())
    assert row["outcome"] == "records_cannot_answer" and "$63.48" in state.reply
