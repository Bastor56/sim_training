"""PII scrubbing with Presidio, before anything is chunked or embedded (spec.md "PII scrubbing").

An embedding computed over a member's SSN can't be "un-computed" later, so
every cleaned document (not only confidential ones) is scrubbed here, whole,
before chunking: an entity can never be split across a chunk boundary and
slip through.

Detection:
  - Harbor's structured formats (member / account numbers, SSN, phone,
    email, DOB, street address): regex PatternRecognizers, case-sensitive,
    from the dataset README.
  - Names: spaCy PERSON via Presidio, kept only for full first + last names
    (so staff written "J. Okafor" survive) and not on the allow-list.
    Staff *full* names are redacted too, deliberately: NER can't tell them
    from members' names, and over-redaction is the safer failure (spec.md
    "PII scrubbing").
Overlapping hits are merged: the structured match wins over a PERSON hit
inside it ("Birch Lane" in an address), and the longest span wins over a
shorter one (a URL inside an email address).

The scrub log (Document.pii_spans) stores type, position and a SHA-256 of
the value, never the value itself; otherwise the log is a PII leak.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter

from models import Document

# Harbor formats (dataset README "PII formats"). Case-sensitive on purpose:
# Presidio's default flags ignore case, which lets "[A-Z][a-z]+" match anything.
PATTERNS: dict[str, list[str]] = {
    "MEMBER": [r"\bHCU-\d{6}\b"],
    "ACCOUNT": [r"\b7730-\d{4}-\d{4}\b"],
    # Presidio's built-in US_SSN recogniser treats 9XX as invalid, so it would skip these.
    "SSN": [r"\b9\d{2}-\d{2}-\d{4}\b"],
    "PHONE": [r"\(555\) ?\d{3}-\d{4}\b", r"\b555[ .-]\d{3}-\d{4}\b", r"\b555-01\d{2}\b"],
    "EMAIL": [r"[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.(?:com|org)\b"],
    "DOB": [r"(?<=DOB: )\d{2}/\d{2}/\d{4}", r"(?<=DOB )\d{2}/\d{2}/\d{4}"],
    "ADDRESS": [r"\b\d{1,5}(?: [A-Z][a-z]+){1,3} (?:Lane|Street|Road|Court|Drive|Way|Avenue), "
                r"[A-Z][a-z]+(?: [A-Z][a-z]+)?, ME 0\d{4}\b"],
}
NAME = "NAME"
TOKEN = "[REDACTED-{}]"

_analyzer = None


def _build_analyzer():
    import regex
    from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer, RecognizerRegistry
    from presidio_analyzer.nlp_engine import NlpEngineProvider
    from presidio_analyzer.predefined_recognizers import SpacyRecognizer

    flags = regex.M  # no IGNORECASE
    registry = RecognizerRegistry(global_regex_flags=flags)
    for entity, regexes in PATTERNS.items():
        registry.add_recognizer(PatternRecognizer(
            supported_entity=entity, name=f"harbor_{entity.lower()}",
            patterns=[Pattern(f"{entity.lower()}_{i}", rx, 1.0) for i, rx in enumerate(regexes)],
            global_regex_flags=flags,
        ))
    registry.add_recognizer(SpacyRecognizer(supported_entities=["PERSON"]))
    nlp = NlpEngineProvider(nlp_configuration={
        "nlp_engine_name": "spacy",
        "models": [{"lang_code": "en", "model_name": "en_core_web_lg"}],
    }).create_engine()
    return AnalyzerEngine(registry=registry, nlp_engine=nlp, supported_languages=["en"])


def analyzer():
    global _analyzer
    if _analyzer is None:
        _analyzer = _build_analyzer()
    return _analyzer


def _is_full_name(text: str, params: dict) -> bool:
    """Keep PERSON hits that look like a member's full name, e.g. "Rosa Delgado-Pierce".

    Rejected: single words, initials ("J. Okafor"), allow-listed Harbor names,
    and anything that isn't Capitalised Words.
    """
    words = text.split()
    # Containment, not equality: NER tagged "Port Alden Branch" as a person.
    if len(words) < 2 or any(allowed in text for allowed in params["allow_list"]):
        return False
    if any(re.fullmatch(r"[A-Z]\.?", w) for w in words):
        return False
    return all(re.fullmatch(r"[A-Z][a-zA-Z'\-]+", w) for w in words)


def detect(text: str, params: dict) -> list[tuple[int, int, str]]:
    """Return non-overlapping (start, end, type) spans to redact, in text order."""
    entities = [*PATTERNS, "PERSON"]
    hits = []
    for r in analyzer().analyze(text=text, language="en", entities=entities, score_threshold=params["min_score"]):
        kind = NAME if r.entity_type == "PERSON" else r.entity_type
        if kind == NAME:
            # spaCy sometimes includes a trailing possessive or punctuation.
            span = re.sub(r"['’]s$", "", text[r.start:r.end]).rstrip(".,;:")
            end = r.start + len(span)
            if not _is_full_name(text[r.start:end], params):
                continue
            hits.append((r.start, end, kind))
        else:
            hits.append((r.start, r.end, kind))
    # Structured types beat names; then longer beats shorter; then earlier.
    hits.sort(key=lambda h: (h[2] == NAME, -(h[1] - h[0]), h[0]))
    chosen: list[tuple[int, int, str]] = []
    for start, end, kind in hits:
        if all(end <= s or start >= e for s, e, _ in chosen):
            chosen.append((start, end, kind))
    return sorted(chosen)


def scrub_text(text: str, params: dict) -> tuple[str, list[dict]]:
    spans = detect(text, params)
    log = [{"type": kind, "start": s, "end": e,
            "value_sha256": hashlib.sha256(text[s:e].encode("utf-8")).hexdigest()} for s, e, kind in spans]
    for start, end, kind in reversed(spans):  # right to left, so earlier offsets stay valid
        text = text[:start] + TOKEN.format(kind) + text[end:]
    return text, log


def scrub_document(doc: Document, params: dict) -> Document:
    """Scrub every block; record what was removed (types and hashes only)."""
    doc.pii_spans = []
    for i, block in enumerate(doc.blocks):
        if not block.text:
            continue
        block.text, log = scrub_text(block.text, params)
        doc.pii_spans.extend({**entry, "block": i} for entry in log)  # offsets refer to the pre-scrub block
    doc.rebuild_text()
    counts = Counter(s["type"].lower() for s in doc.pii_spans)
    doc.decision.details["pii"] = dict(sorted(counts.items()))
    if counts:
        summary = ", ".join(f"{t} {n}" for t, n in sorted(counts.items()))
        doc.decision.reason += f"; redacted {sum(counts.values())} PII values ({summary})"
    return doc
