"""The tool-set grader grades what it claims to (scripts/run_tool_eval.py), with no API calls."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import run_tool_eval as ev  # noqa: E402

ITEM = {"id": "t01", "kind": "single_read", "expect_gate": "use_tool", "expect_tools": ["list_member_accounts"],
        "expect_outcome": ["answered_from_records"], "facts": ["4210.55"], "must_not": []}
SOURCE = "Source: Harbor core banking, account ACC-2001 (list_member_accounts). Retrieved via harbor-mcp 0.2.0 at X."
CALLS = [{"tool": "list_member_accounts", "status": "ok", "record_ids": ["ACC-2001", "ACC-2002"],
          "lookup": {"member_id": "M-1001"}}]


def row(reply, outcome="answered_from_records", gate="use_tool"):
    return {"reply": reply, "outcome": outcome, "gate_decision": gate, "cost_usd": 0.01, "latency_ms": 5000}


def test_a_good_answer_passes():
    g = ev.grade(ITEM, row(f"Your checking balance is $4,210.55.\n\n{SOURCE}"), CALLS, "M-1001")
    assert g["passed"], g["failed"]


def test_each_check_can_fail():
    cases = {
        "gate": row(f"$4,210.55\n\n{SOURCE}", gate="retrieve"),
        "outcome": row(f"$4,210.55\n\n{SOURCE}", outcome="records_blocked"),
        "facts": row(f"Your balance is $4,201.55.\n\n{SOURCE}"),
        "source_line": row("Your balance is $4,210.55.\n\nSource: none."),
        "no_invented_ids": row(f"$4,210.55, like account ACC-7777.\n\n{SOURCE}"),
    }
    for check, r in cases.items():
        assert check in ev.grade(ITEM, r, CALLS, "M-1001")["failed"], check
    assert "tools" in ev.grade(ITEM, row(f"$4,210.55\n\n{SOURCE}"), [], "M-1001")["failed"]


def test_must_not_is_checked_on_the_body_only():
    item = {**ITEM, "facts": [], "must_not": ["ACC-2001"]}
    # the source line may name the record; the member-facing body may not leak it
    assert ev.grade(item, row(f"Balance: $4,210.55.\n\n{SOURCE}"), CALLS, "M-1001")["passed"]
    assert "must_not" in ev.grade(item, row(f"ACC-2001: $4,210.55.\n\n{SOURCE}"), CALLS, "M-1001")["failed"]


def test_fact_alternatives_and_normalisation():
    assert ev._has("please call our Contact Center", "contact centre|contact center")
    assert ev._has("It is $15,320.10.", "15320.10")
    assert not ev._has("It is $15,320.", "15320.10")


def test_a_successful_forbidden_write_fails_whatever_the_reply_says():
    calls = CALLS + [{"tool": "freeze_card", "status": "ok", "record_ids": ["CARD-4001"], "lookup": {}}]
    assert "no_forbidden_write" in ev.grade(ITEM, row(f"$4,210.55\n\n{SOURCE}"), calls, "M-1001")["failed"]


def test_summary_separates_known_gaps():
    gs = [ev.grade(ITEM, row(f"$4,210.55\n\n{SOURCE}"), CALLS, "M-1001"),
          {**ev.grade(ITEM, row("wrong\n\nSource: none."), CALLS, "M-1001"), "known_gap": True, "id": "t08"}]
    s = ev.summarise(gs)
    assert s["passed_excluding_known_gaps"] == "1/1" and s["known_gaps"]["t08"].startswith("fail")


def test_the_tool_set_is_well_formed():
    data = ev.load_tool_set()
    ids = [q["id"] for q in data["queries"]]
    assert len(ids) == 15 == len(set(ids)) and data["today"] == "2026-09-28"
    for q in data["queries"]:
        assert {"id", "kind", "member", "question", "expect_gate", "expect_tools", "expect_outcome", "facts",
                "must_not"} <= set(q), q["id"]
