"""Golden-set loading and the rules for "does this chunk answer this query?"

The golden set labels answers as (doc_id, quote) rather than chunk IDs, so
the same labels can score any chunking strategy (spec.md "Eval methodology").
Normalisation matches the dataset's own verify_dataset.py exactly, so our
matcher and the dataset's checker agree on what counts as a match.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from config import GOLDEN_SET_PATH

# Curly quotes, primes and dash variants -> ASCII; ellipsis -> "...".
_ASCII_PUNCT = {
    0x2018: "'", 0x2019: "'", 0x201A: "'", 0x2032: "'",
    0x201C: '"', 0x201D: '"', 0x201E: '"', 0x2033: '"',
    0x2013: "-", 0x2014: "-", 0x2012: "-", 0x2212: "-", 0x2011: "-",
    0x2026: "...",
}


def normalise(text: str) -> str:
    """Lowercase, Unicode NFKC, ASCII quotes/dashes, collapse whitespace."""
    text = unicodedata.normalize("NFKC", text).translate(_ASCII_PUNCT).lower()
    return " ".join(text.split())


@dataclass(frozen=True)
class Location:
    doc_id: str
    quote: str
    match: str  # "substring" | "all_tokens"


def matches(chunk_text: str, location: Location) -> bool:
    """Text-only test: does the chunk contain this expected quote?

    substring:  the normalised chunk contains the normalised quote.
    all_tokens: every token of the quote appears somewhere in the chunk
                (for table rows and figure captions, where parsers format
                cells differently: "24 months 4.05%" matches
                "24 months | 3.95% | 4.00% | 4.05%").
    """
    quote, text = normalise(location.quote), normalise(chunk_text)
    if location.match == "substring":
        return quote in text
    if location.match == "all_tokens":
        return all(token in text for token in quote.split())
    raise ValueError(f"unknown match rule {location.match!r}")


@dataclass
class RelevantItem:
    """One thing recall counts. Locations sharing a quote (a doc and its
    duplicate) form one item: finding either copy satisfies it."""

    locations: list[Location]

    def satisfied_by(self, doc_id: str, chunk_text: str) -> bool:
        # The chunk must also come from the expected document.
        return any(loc.doc_id == doc_id and matches(chunk_text, loc) for loc in self.locations)


@dataclass
class GoldenQuery:
    id: str
    query: str
    type: str
    tenant: str
    expected: list[Location]
    access: str = ""  # "restricted" on q003 only
    answer: str = ""
    fact_ids: list[str] = field(default_factory=list)
    notes: str = ""

    @property
    def is_unanswerable(self) -> bool:
        return not self.expected


def relevant_items(query: GoldenQuery) -> list[RelevantItem]:
    """Group expected locations by normalised quote, in first-seen order.

    duplicate_source: both copies carry the same quote -> 1 item.
    multi_chunk:      each passage has its own quote -> one item each.
    unanswerable:     no locations -> 0 items.
    """
    groups: dict[str, list[Location]] = {}
    for loc in query.expected:
        groups.setdefault(normalise(loc.quote), []).append(loc)
    return [RelevantItem(locations=locs) for locs in groups.values()]


@dataclass
class GoldenSet:
    version: int
    corpus_version: int
    queries: list[GoldenQuery]

    def by_id(self, query_id: str) -> GoldenQuery:
        for q in self.queries:
            if q.id == query_id:
                return q
        raise KeyError(query_id)


def load_golden_set(path: str | Path = GOLDEN_SET_PATH) -> GoldenSet:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    queries = [
        GoldenQuery(
            id=q["id"],
            query=q["query"],
            type=q["type"],
            tenant=q["tenant"],
            expected=[Location(**loc) for loc in q.get("expected", [])],
            access=q.get("access", ""),
            answer=q.get("answer", ""),
            fact_ids=list(q.get("fact_ids", [])),
            notes=q.get("notes", ""),
        )
        for q in raw["queries"]
    ]
    return GoldenSet(version=raw["version"], corpus_version=raw["corpus_version"], queries=queries)
