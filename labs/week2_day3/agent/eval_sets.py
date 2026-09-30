"""Loads the three eval sets into one list (spec.md "Eval sets and grading").

    golden          Day 6's 45 questions, unchanged (v1): expected gate = retrieve
    no_retrieval    the 10 new questions where retrieving is the wrong move
    repeat_traffic  18 cache-equivalence probes (scored on cache behaviour only)

expected_outcome follows the spec's grading table:
    answerable golden question                  -> "answered"
    unanswerable (q043-q045), and q003          -> "not_in_corpus"
        (q003's only answer is in a restricted document, excluded for member-facing runs)
    no-retrieval question                       -> "answered_direct"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

import day6
from settings import CHUNKER, EVAL_DIR, PARSER

NO_RETRIEVAL_PATH = EVAL_DIR / "no_retrieval_set.yaml"
REPEAT_TRAFFIC_PATH = EVAL_DIR / "repeat_traffic_set.yaml"


@dataclass
class EvalItem:
    id: str
    set: str  # "golden" | "no_retrieval" | "repeat_traffic"
    question: str
    tenant: str
    expected_gate: str  # "retrieve" | "answer_direct"
    expected_outcome: str | None  # None for repeat-traffic probes
    golden: day6.GoldenQuery | None = None  # the source golden row (golden and probes)
    category: str = ""  # golden type, no-retrieval category, or probe variant
    expect_cache: str | None = None  # probes only: "hit" | "miss"
    corpus_version: str | None = None  # probes only: override to simulate a re-ingested corpus
    notes: str = ""
    extra: dict = field(default_factory=dict)


def corpus_version(golden_set: day6.GoldenSet | None = None) -> str:
    """The corpus identity that goes into every cache key: dataset version + Day 6 index name."""
    gs = golden_set or day6.load_golden_set()
    return f"{gs.corpus_version}|{day6.collection_name(PARSER, CHUNKER)}"


def _golden_outcome(q: day6.GoldenQuery) -> str:
    if q.is_unanswerable or q.access == "restricted":
        return "not_in_corpus"
    return "answered"


def load_golden(golden_set: day6.GoldenSet | None = None) -> list[EvalItem]:
    gs = golden_set or day6.load_golden_set()
    return [EvalItem(q.id, "golden", q.query, q.tenant, "retrieve", _golden_outcome(q), golden=q, category=q.type,
                     notes=q.notes) for q in gs.queries]


def load_no_retrieval(path: Path = NO_RETRIEVAL_PATH) -> list[EvalItem]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [EvalItem(q["id"], "no_retrieval", q["query"], q["tenant"], q["expected_gate"], "answered_direct",
                     category=q["category"], notes=q.get("notes", "")) for q in raw["queries"]]


def load_repeat_traffic(path: Path = REPEAT_TRAFFIC_PATH, golden_set: day6.GoldenSet | None = None) -> list[EvalItem]:
    gs = golden_set or day6.load_golden_set()
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    items = []
    for p in raw["probes"]:
        source = gs.by_id(p["source_id"])
        items.append(EvalItem(p["id"], "repeat_traffic", p["query"], p.get("tenant", source.tenant), "retrieve",
                              None, golden=source, category=p["variant"], expect_cache=p["expect_cache"],
                              corpus_version=p.get("corpus_version"), extra={"source_id": p["source_id"]}))
    return items


def load(sets: list[str]) -> list[EvalItem]:
    gs = day6.load_golden_set()
    loaders = {"golden": lambda: load_golden(gs), "no_retrieval": load_no_retrieval,
               "repeat": lambda: load_repeat_traffic(golden_set=gs)}
    items: list[EvalItem] = []
    for name in sets:
        items += loaders[name]()
    return items
