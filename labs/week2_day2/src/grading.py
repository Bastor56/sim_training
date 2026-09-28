"""Grading one interaction against its eval item (spec.md "Grading").

Deterministic checks (free, every run):
    gate_correct         expected retrieve / answer_direct vs actual
    outcome_correct      answerable -> answered; q003 + unanswerable -> not_in_corpus;
                         no-retrieval -> answered_direct with 0 rounds
    citation_hit         a cited chunk contains an expected quote, from the expected document (Day 6's matcher)
    version_check        q028-q031: cites overdraft_policy_v3, never v2
    version_quoted       q028-q031: the member-facing reply names version 3 and never version 2 (decision 14)
    version_in_prose     ...the same, on the model's own prose only (informational)
    source_line_ok       the reply ends with a source line of the right kind (decision 13)
    no_dollar_amount     no-retrieval: no "$" in the reply (proxy for "no Harbor fee or limit")
    leak                 a cited chunk is restricted or from another tenant (should never happen)

LLM judge (Sonnet 5, not billable to the interaction, cache namespace "judge"):
    runs only on answerable questions that ended "answered"; grades the prose
    answer against the golden `answer` as correct / partial / incorrect.

task_success = outcome_correct, and for an answerable question also
judge "correct" and a citation hit.
"""

from __future__ import annotations

import re
from collections import Counter

import agent_nodes
import day6
import llm
import settings
import tracing
from eval_sets import EvalItem

IN_FORCE_DOC, SUPERSEDED_DOC = "overdraft_policy_v3", "overdraft_policy_v2"
_V3 = re.compile(r"\bv(?:ersion)?\s?3(?:\.0)?\b|\b3\.0\b", re.IGNORECASE)
_V2 = re.compile(r"\bv(?:ersion)?\s?2(?:\.0)?\b", re.IGNORECASE)

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["correct", "partial", "incorrect"]},
        "reason": {"type": "string"},
    },
    "required": ["verdict", "reason"],
    "additionalProperties": False,
}


def names_in_force_version(text: str) -> bool:
    return bool(_V3.search(text)) and not _V2.search(text)


def _source_line_ok(row: dict) -> bool:
    line, reply = row.get("source_line", ""), row.get("reply", "")
    if not line or not reply.endswith(line):
        return False
    if row["outcome"] == "answered_direct":
        return line == agent_nodes.DIRECT_SOURCE
    if row["outcome"] == "answered":
        return line.startswith("Source: ") and not line.startswith("Source: none found")
    return line.startswith("Source: none found")


def deterministic(row: dict, item: EvalItem) -> dict:
    cited_docs = {c["doc_id"] for c in row["citations"]}
    g = {
        "id": item.id,
        "set": item.set,
        "category": item.category,
        "gate_expected": item.expected_gate,
        "gate_actual": row["gate_decision"],
        "gate_correct": row["gate_decision"] == item.expected_gate,
        "outcome_expected": item.expected_outcome,
        "outcome_actual": row["outcome"],
        "rounds": row["rounds"],
        "round_verdicts": row["round_verdicts"],
        "declined_rounds": row["round_verdicts"].count("declined"),
        "ungrounded_rounds": row["round_verdicts"].count("ungrounded"),
        "rewrite_helped": row["rewrite_helped"],
        "rescued_after_decline": row["rescued_after_decline"],
        "source_line_ok": _source_line_ok(row),
        "leak": any(c.get("sensitivity") == "restricted" or (c.get("tenant") and c["tenant"] != item.tenant)
                    for c in row["citations"]),
    }
    if item.expected_outcome == "answered_direct":
        g["outcome_correct"] = row["outcome"] == "answered_direct" and row["rounds"] == 0
        g["no_dollar_amount"] = "$" not in row["reply"]
    else:
        g["outcome_correct"] = row["outcome"] == item.expected_outcome
    if item.expected_outcome == "answered" and item.golden is not None:
        items = day6.relevant_items(item.golden)
        g["citation_hit"] = any(it.satisfied_by(c["doc_id"], c.get("text", "")) for it in items
                                for c in row["citations"])
    if item.category == "version_trap":
        g["version_check"] = IN_FORCE_DOC in cited_docs and SUPERSEDED_DOC not in cited_docs
        g["version_quoted"] = names_in_force_version(row["reply"])
        g["version_in_prose"] = names_in_force_version(row["answer"])
    return g


def judge_message(item: EvalItem, row: dict) -> str:
    return (f"Member question:\n{item.question}\n\nReference answer:\n{item.golden.answer}\n\n"
            f"Assistant's answer:\n{row['answer']}")


def judge(row: dict, item: EvalItem, *, corpus_version: str, llm_call=llm.call) -> dict:
    """One judge call, outside the interaction's bill but inside the ledger and the guard."""
    name = settings.PROMPTS["judge"]
    scope = {"tenant": item.tenant, "allow_restricted": False, "current_only": True,
             "corpus_version": corpus_version}
    with tracing.interaction(f"{row['correlation_id']}#judge", billable=False):
        try:
            result = llm_call("judge", settings.JUDGE, system=agent_nodes.load_prompt(name),
                              user=judge_message(item, row), prompt_version=name, output_schema=JUDGE_SCHEMA,
                              question=item.question, scope=scope, namespace="judge")
            return {"judge_verdict": result.data["verdict"], "judge_reason": result.data["reason"],
                    "judge_cost_usd": result.cost_usd}
        except llm.LLMError as e:
            return {"judge_verdict": "error", "judge_reason": str(e), "judge_cost_usd": 0.0}


def needs_judge(row: dict, item: EvalItem) -> bool:
    return item.expected_outcome == "answered" and row["outcome"] == "answered"


def grade(row: dict, item: EvalItem, *, corpus_version: str, use_judge: bool = True, llm_call=llm.call) -> dict:
    g = deterministic(row, item)
    if use_judge and needs_judge(row, item):
        g.update(judge(row, item, corpus_version=corpus_version, llm_call=llm_call))
    if item.expected_outcome == "answered":
        g["task_success"] = bool(g["outcome_correct"] and g.get("judge_verdict") == "correct" and g.get("citation_hit"))
    else:
        g["task_success"] = bool(g["outcome_correct"])
    return g


def _share(values: list[bool]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def summarise(grades: list[dict]) -> dict:
    """Run-level quality numbers over the quality sets (golden + no_retrieval)."""
    q = [g for g in grades if g["set"] in ("golden", "no_retrieval")]
    answerable = [g for g in q if g["outcome_expected"] == "answered"]
    judged = [g for g in answerable if "judge_verdict" in g]
    nic_expected = [g for g in q if g["outcome_expected"] == "not_in_corpus"]
    nic_actual = [g for g in q if g["outcome_actual"] == "not_in_corpus"]
    direct = [g for g in q if g["outcome_expected"] == "answered_direct"]
    confusion = Counter(f"{g['gate_expected']}->{g['gate_actual']}" for g in q)
    verdicts = Counter(g["judge_verdict"] for g in judged)
    version = [g for g in q if "version_check" in g]
    return {
        "questions": len(q),
        "task_success": _share([g["task_success"] for g in q]),
        "task_success_count": sum(g["task_success"] for g in q),
        "gate_accuracy": _share([g["gate_correct"] for g in q]),
        "gate_confusion": dict(sorted(confusion.items())),
        "outcome_correct": _share([g["outcome_correct"] for g in q]),
        "answerable_answered": _share([g["outcome_actual"] == "answered" for g in answerable]),
        "judge_verdicts": dict(verdicts),
        "judge_correct_of_answerable": _share([g.get("judge_verdict") == "correct" for g in answerable]),
        "citation_hit_of_answerable": _share([bool(g.get("citation_hit")) for g in answerable]),
        "not_in_corpus_recall": _share([g["outcome_actual"] == "not_in_corpus" for g in nic_expected]),
        "not_in_corpus_precision": _share([g["outcome_expected"] == "not_in_corpus" for g in nic_actual]),
        "not_in_corpus_false_declines": sum(g["outcome_expected"] == "answered" for g in nic_actual),
        "direct_correct": _share([g["outcome_correct"] for g in direct]),
        "direct_no_dollar": _share([g.get("no_dollar_amount", False) for g in direct]),
        "version_check": _share([g["version_check"] for g in version]),
        "version_quoted": _share([g["version_quoted"] for g in version]),
        "version_in_prose": _share([g["version_in_prose"] for g in version]),
        "source_line_violations": sum(not g["source_line_ok"] for g in q),
        "leaks": sum(g["leak"] for g in q),
        "declined_rounds": sum(g["declined_rounds"] for g in q),
        "ungrounded_rounds": sum(g["ungrounded_rounds"] for g in q),
        "rewrite_helped": sum(g["rewrite_helped"] for g in q),
        "rescued_after_decline": sum(g["rescued_after_decline"] for g in q),
    }
