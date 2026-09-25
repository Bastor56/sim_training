"""Precision@k, recall@k, aggregation and leak checks (spec.md "Metric definitions").

A retrieved result is just (doc_id, chunk_text) here, so the metrics can be
tested with hand-made chunks and never need an index.

  Recall@k    = relevant items satisfied by at least one top-k chunk / n_items
  Precision@k = top-k chunks that satisfy an item not already satisfied by a
                higher-ranked chunk / k

The "not already satisfied" rule means a quote repeated in two overlapping
chunks counts once, so chunker A's overlap isn't rewarded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean

from golden import GoldenQuery, RelevantItem, relevant_items

Result = tuple[str, str]  # (doc_id, chunk_text)


def _credited(results: list[Result], items: list[RelevantItem], k: int) -> tuple[int, set[int]]:
    """Walk the top k in rank order. Returns (chunks credited, item indexes found)."""
    found: set[int] = set()
    credited_chunks = 0
    for doc_id, text in results[:k]:
        new = {i for i, item in enumerate(items) if i not in found and item.satisfied_by(doc_id, text)}
        if new:
            credited_chunks += 1  # one chunk counts once, even if it satisfies two new items
            found |= new
    return credited_chunks, found


def recall_at_k(results: list[Result], items: list[RelevantItem], k: int) -> float:
    if not items:
        raise ValueError("recall is undefined for a query with no relevant items (unanswerable)")
    _, found = _credited(results, items, k)
    return len(found) / len(items)


def precision_at_k(results: list[Result], items: list[RelevantItem], k: int) -> float:
    if not items:
        raise ValueError("precision is not scored for a query with no relevant items (unanswerable)")
    credited_chunks, _ = _credited(results, items, k)
    return credited_chunks / k  # divide by k even if fewer than k results came back


def precision_ceiling(n_items: int, k: int) -> float:
    """Best possible P@k: with one relevant item, P@5 can never exceed 0.20."""
    return min(n_items, k) / k


@dataclass
class QueryScore:
    query_id: str
    type: str
    n_items: int
    recall: dict[int, float] = field(default_factory=dict)  # k -> value
    precision: dict[int, float] = field(default_factory=dict)


def score_query(query: GoldenQuery, results: list[Result], k_values: list[int]) -> QueryScore:
    items = relevant_items(query)
    if not items:
        raise ValueError(f"{query.id} is unanswerable; it is reported separately, not scored")
    return QueryScore(
        query_id=query.id,
        type=query.type,
        n_items=len(items),
        recall={k: recall_at_k(results, items, k) for k in k_values},
        precision={k: precision_at_k(results, items, k) for k in k_values},
    )


def _means(scores: list[QueryScore]) -> dict[str, float]:
    k_values = sorted(scores[0].recall)
    out: dict[str, float] = {}
    for k in k_values:
        out[f"recall@{k}"] = mean(s.recall[k] for s in scores)
        out[f"precision@{k}"] = mean(s.precision[k] for s in scores)
        out[f"precision_ceiling@{k}"] = mean(precision_ceiling(s.n_items, k) for s in scores)
    return out


def aggregate(scores: list[QueryScore]) -> dict:
    """Macro averages (mean of per-query values) plus a per-query-type breakdown."""
    if not scores:
        raise ValueError("nothing to aggregate")
    if any(s.n_items == 0 for s in scores):
        raise ValueError("unanswerable queries must not be averaged into P/R")
    by_type: dict[str, list[QueryScore]] = {}
    for s in scores:
        by_type.setdefault(s.type, []).append(s)
    return {
        "n_queries": len(scores),
        **_means(scores),
        "by_type": {t: {"n_queries": len(group), **_means(group)} for t, group in sorted(by_type.items())},
    }


def leak_counts(top_metadata: list[dict], tenant: str) -> dict[str, int]:
    """Chunks that should never have been returned, given the access filter.

    restricted:   sensitivity == "restricted" (e.g. the fraud thresholds doc)
    wrong_tenant: a different tenant's doc (e.g. business fees for a retail query)
    superseded:   not the version in force (e.g. Overdraft Policy v2)
    """
    return {
        "restricted": sum(m["sensitivity"] == "restricted" for m in top_metadata),
        "wrong_tenant": sum(m["tenant"] != tenant for m in top_metadata),
        "superseded": sum(not m["is_current"] for m in top_metadata),
    }
