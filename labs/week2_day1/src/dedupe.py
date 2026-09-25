"""Exact and near-duplicate detection (spec decision rules 3 and 7).

Exact:  identical SHA-256 of the raw file bytes, checked at load time.
Near:   word 5-gram ("shingle") Jaccard similarity of the cleaned,
        normalised text, checked after cleaning, so that formatting noise
        (double spaces, a missing page header) doesn't hide a copy.

Jaccard = |shingles in both| / |shingles in either|. 1.0 means the same
sequence of words; unrelated documents score near 0.

Within a duplicate group one copy is kept (the canonical one) and the
others are dropped with a reason that names it.
"""

from __future__ import annotations

import re
from itertools import combinations

from golden import normalise
from models import Decision, Document

_COPY_MARKER = re.compile(r"\(\d+\)|\bcopy\b", re.I)
# Published/rendered formats first: that's what members actually received.
_FORMAT_RANK = {"pdf": 0, "html": 1, "docx": 2, "md": 3, "txt": 4}


def canonical_sort_key(doc: Document) -> tuple:
    """Lower sorts first = preferred copy (spec "Choosing the canonical copy").

    Plain filename order would pick wrongly in both corpus pairs:
    "faq (1).html" sorts before "faq.html", "PAY-WT-004...docx" before the PDF.
    """
    return (
        bool(_COPY_MARKER.search(doc.source_filename)),
        _FORMAT_RANK.get(doc.format, 9),
        doc.catalog.get("effective_date") or "9999-99-99",
        doc.source_filename,
    )


def _drop_duplicates(group: list[Document], stage: str, why: str) -> None:
    canonical, *copies = sorted(group, key=canonical_sort_key)
    for doc in copies:
        doc.decision = Decision(
            status="dropped",
            reason=f"{why(doc)} of {canonical.doc_id} ({canonical.source_filename})",
            stage=stage,
            details={**doc.decision.details, "canonical_doc_id": canonical.doc_id},
        )


def drop_exact_duplicates(docs: list[Document]) -> None:
    """Rule 3: byte-identical files. Runs before parsing, so copies cost nothing."""
    groups: dict[str, list[Document]] = {}
    for doc in docs:
        if doc.decision.is_active:
            groups.setdefault(doc.source_sha256, []).append(doc)
    for group in groups.values():
        if len(group) > 1:
            _drop_duplicates(group, "load", lambda d: "exact duplicate")
            for doc in group:
                if doc.decision.status == "dropped":
                    doc.decision.reason += "; identical SHA-256"


def shingles(text: str, n: int) -> set[tuple[str, ...]]:
    words = normalise(text).split()
    return {tuple(words[i:i + n]) for i in range(max(1, len(words) - n + 1))}


def jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


def drop_near_duplicates(docs: list[Document], params: dict) -> list[tuple[str, str, float]]:
    """Rule 7. Returns every compared pair's similarity (for the report).

    Two versions of the same policy (different catalog `version`) are never
    duplicates of each other, however similar the words: Overdraft Policy v2
    and v3 differ only in their fees, and "which version is in force" is
    exactly what the superseded filter needs both of them for.
    """
    active = [d for d in docs if d.decision.is_active]
    sets = {d.doc_id: shingles(d.text, params["shingle_words"]) for d in active}
    pairs, groups = [], {d.doc_id: {d.doc_id} for d in active}
    by_id = {d.doc_id: d for d in active}
    for a, b in combinations(active, 2):
        score = jaccard(sets[a.doc_id], sets[b.doc_id])
        pairs.append((a.doc_id, b.doc_id, round(score, 3)))
        same_version = a.catalog.get("version", "") == b.catalog.get("version", "")
        if score >= params["near_duplicate_jaccard"] and same_version:
            merged = groups[a.doc_id] | groups[b.doc_id]
            for doc_id in merged:
                groups[doc_id] = merged
    seen: set[frozenset] = set()
    for group in groups.values():
        key = frozenset(group)
        if len(group) > 1 and key not in seen:
            seen.add(key)
            members = [by_id[i] for i in group]
            canonical = min(members, key=canonical_sort_key)
            _drop_duplicates(
                members, "dedupe",
                lambda d: f"near-duplicate (Jaccard={jaccard(sets[d.doc_id], sets[canonical.doc_id]):.2f})",
            )
    return sorted(pairs, key=lambda p: -p[2])
