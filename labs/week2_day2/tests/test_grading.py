"""Grading rules (spec.md "Grading"), with hand-made interaction rows and a fake judge."""

from types import SimpleNamespace

import pytest

import agent_nodes
import eval_sets
import grading

ITEMS = {i.id: i for i in eval_sets.load(["golden", "no_retrieval"])}
Q001_QUOTE = "completes Form HCU-DSP-114 (Card Transaction Dispute) during the initial contact"


def cite(doc_id, text="", tenant="retail", sensitivity="internal"):
    return {"chunk_id": f"{doc_id}::x", "doc_id": doc_id, "title": doc_id, "tenant": tenant,
            "sensitivity": sensitivity, "text": text}


def row(outcome="answered", *, gate="retrieve", rounds=1, citations=(), answer="An answer.", source=None,
        verdicts=None):
    source = source or {"answered": "Source: Some Doc (version 1)",
                        "answered_direct": agent_nodes.DIRECT_SOURCE,
                        "not_in_corpus": "Source: none found. Searched Harbor's documents (3 rounds)."}[outcome]
    body = answer if outcome != "not_in_corpus" else agent_nodes.NOT_IN_CORPUS_REPLY
    return {"correlation_id": "t/q", "gate_decision": gate, "rounds": rounds, "outcome": outcome,
            "round_verdicts": verdicts or (["usable"] * rounds), "citations": list(citations), "answer": answer,
            "reply": f"{body}\n\n{source}", "source_line": source, "rewrite_helped": False,
            "rescued_after_decline": False}


def fake_judge(verdict):
    calls = []

    def call(purpose, role, **kw):
        calls.append((purpose, kw["namespace"]))
        return SimpleNamespace(data={"verdict": verdict, "reason": "r"}, cost_usd=0.001)
    call.calls = calls
    return call


def grade(r, qid, verdict="correct"):
    return grading.grade(r, ITEMS[qid], corpus_version="1|x", llm_call=fake_judge(verdict))


def test_citation_hit_on_the_expected_quote():
    g = grade(row(citations=[cite("card_dispute_procedure", f"... the agent {Q001_QUOTE} ...")]), "q001")
    assert g["citation_hit"] and g["task_success"]


def test_right_quote_wrong_document_is_not_a_hit():
    g = grade(row(citations=[cite("member_faq", Q001_QUOTE)]), "q001")
    assert not g["citation_hit"] and not g["task_success"]


def test_judge_partial_fails_task_success():
    g = grade(row(citations=[cite("card_dispute_procedure", Q001_QUOTE)]), "q001", verdict="partial")
    assert g["citation_hit"] and g["judge_verdict"] == "partial" and not g["task_success"]


def test_judge_uses_its_own_namespace_and_only_runs_on_answered_answerable():
    judge = fake_judge("correct")
    grading.grade(row(citations=[cite("card_dispute_procedure", Q001_QUOTE)]), ITEMS["q001"],
                  corpus_version="1|x", llm_call=judge)
    grading.grade(row("not_in_corpus", rounds=3), ITEMS["q044"], corpus_version="1|x", llm_call=judge)
    grading.grade(row("answered_direct", gate="answer_direct", rounds=0), ITEMS["n001"], corpus_version="1|x",
                  llm_call=judge)
    assert judge.calls == [("judge", "judge")]


def test_q029_citing_v2_fails_version_check():
    g = grade(row(citations=[cite("overdraft_policy_v2")], answer="Three per day."), "q029")
    assert g["version_check"] is False


def test_version_quoted_via_source_line_but_not_in_prose():
    r = row(citations=[cite("overdraft_policy_v3")], answer="$29 per item.",
            source="Source: Overdraft Policy (version 3.0, effective 2026-01-01)")
    g = grade(r, "q028")
    assert g["version_check"] and g["version_quoted"] and not g["version_in_prose"]


def test_mentioning_v2_fails_version_quoted():
    r = row(citations=[cite("overdraft_policy_v3")], answer="Under v3 it is $29 (v2 said $30).",
            source="Source: Overdraft Policy (version 3.0)")
    assert grade(r, "q028")["version_quoted"] is False


@pytest.mark.parametrize("text, expected", [
    ("Overdraft Policy v3", True), ("version 3.0", True), ("(version 3.0, effective 2026-01-01)", True),
    ("Schedule of Fees (version 2026)", False), ("Wire Transfer Policy Rev 2026-02", False),
    ("$3.00 fee", False), ("v3 replaced version 2", False),
])
def test_version_regex(text, expected):
    assert grading.names_in_force_version(text) is expected


def test_unanswerable_answered_is_wrong_whatever_the_judge_thinks():
    g = grade(row(citations=[cite("auto_loan_comparison")]), "q044", verdict="correct")
    assert not g["outcome_correct"] and not g["task_success"] and "judge_verdict" not in g


def test_unanswerable_declined_is_a_success():
    assert grade(row("not_in_corpus", rounds=3, verdicts=["poor"] * 3), "q045")["task_success"]


def test_no_retrieval_question_that_retrieved_is_wrong_twice():
    g = grade(row("answered", gate="retrieve", rounds=1), "n005")
    assert not g["gate_correct"] and not g["outcome_correct"]


def test_direct_answer_with_dollar_amount_fails_no_amount_check():
    g = grade(row("answered_direct", gate="answer_direct", rounds=0, answer="Our fee is $30."), "n009")
    assert g["outcome_correct"] and g["no_dollar_amount"] is False


def test_missing_or_wrong_source_line_is_a_violation():
    r = row("answered_direct", gate="answer_direct", rounds=0)
    r["reply"] = "Hello!"  # source line dropped
    assert grade(r, "n001")["source_line_ok"] is False
    wrong_kind = row("answered_direct", gate="answer_direct", rounds=0, source="Source: Overdraft Policy")
    assert grade(wrong_kind, "n001")["source_line_ok"] is False


def test_leak_detected_on_restricted_or_wrong_tenant_citation():
    assert grade(row(citations=[cite("fraud_monitoring_thresholds", sensitivity="restricted")]), "q003")["leak"]
    assert grade(row(citations=[cite("business_fee_guide", tenant="business")]), "q038")["leak"]


def test_summary_counts():
    grades = [
        grade(row(citations=[cite("card_dispute_procedure", Q001_QUOTE)]), "q001"),
        grade(row("not_in_corpus", rounds=3), "q045"),
        grade(row("not_in_corpus", rounds=3), "q004"),  # a false decline
        grade(row("answered_direct", gate="answer_direct", rounds=0), "n001"),
    ]
    s = grading.summarise(grades)
    assert s["questions"] == 4 and s["task_success_count"] == 3
    assert s["not_in_corpus_recall"] == 1.0 and s["not_in_corpus_precision"] == 0.5
    assert s["not_in_corpus_false_declines"] == 1 and s["source_line_violations"] == 0
