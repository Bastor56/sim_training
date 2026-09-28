"""Layer 1 of relevance validation: the reranker threshold (spec.md "Validator").

A retrieved chunk is usable if its cross-encoder rerank score is >= tau.
This catches a top-k that is about something else entirely, cheaply and
locally (no LLM call), and sends the agent to rewrite its query.

It cannot catch a near miss: Day 6 showed q045 (RV loan prepayment) scoring
0.549 on an auto-loan chunk, above 12 genuinely answerable questions. That is
layer 2's job: the generator's coverage check (agent_nodes.generate, and
decision 12, which sends a decline back to the rewrite path too).
"""

from __future__ import annotations


def validate(results: list[dict], tau: float) -> tuple[list[dict], str]:
    """Return (usable chunks in rank order, verdict "usable" | "poor")."""
    kept = [r for r in results if r["rerank"] >= tau]
    return kept, ("usable" if kept else "poor")
