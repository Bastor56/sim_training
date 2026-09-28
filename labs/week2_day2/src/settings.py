"""Paths, agent limits, model roles and the budget.

Every value that changes agent behaviour or cost lives here, so each run can
record exactly what it used in runs/<run_id>/config.json (spec.md
"Reproducibility rules"). Model settings per role follow spec.md "Model roles
and the three candidates".
"""

from __future__ import annotations

from pathlib import Path

LAB_DIR = Path(__file__).resolve().parent.parent

PROMPTS_DIR = LAB_DIR / "prompts"
EVAL_DIR = LAB_DIR / "eval"
CACHE_DIR = LAB_DIR / "cache" / "llm"
RUNS_DIR = LAB_DIR / "runs"
ARTIFACTS_DIR = LAB_DIR / "artifacts"
PRICING_PATH = LAB_DIR / "pricing.json"
SPEND_LEDGER_PATH = RUNS_DIR / "spend_ledger.jsonl"
ENV_FILE = LAB_DIR.parent.parent / ".env"  # repo-root .env, as in earlier labs

# --- The agent (spec "The agent", "Validator") ---
MAX_ROUNDS = 3  # retrieval rounds per question: the first try + at most 2 rewrites
TAU_KEEP = 0.10  # a chunk is usable if its rerank score is >= this
TOP_K = 5  # chunks retrieved per round (and the most the generator sees)

# Day 6's recommended index, used unchanged.
PARSER = "layout"
CHUNKER = "B_structure"
RETRIEVAL_MODE = "hybrid_rerank"  # rerank scores are what the validator reads

# Prompt file per purpose (prompts/<name>.md). The name is the prompt version:
# it is recorded on every call and is part of every cache key.
PROMPTS = {
    "gate": "gate_v1",
    "rewrite": "rewrite_v1",
    "generate": "generate_v1",
    "direct_answer": "direct_answer_v1",
    "judge": "judge_v2",  # v1 -> v2 after calibration (findings log, milestone 10)
}

# --- Models per role ---
# thinking=None means the parameter is omitted from the request.
HAIKU = "claude-haiku-4-5"
SONNET = "claude-sonnet-5"
OPUS = "claude-opus-5"

GATE = {"model": HAIKU, "thinking": None, "effort": None, "max_tokens": 1024}
JUDGE = {"model": SONNET, "thinking": {"type": "disabled"}, "effort": None, "max_tokens": 1024}

# The three generator candidates (only the generator changes between runs).
GENERATORS = {
    "haiku": {"model": HAIKU, "thinking": None, "effort": None, "max_tokens": 2048},
    # Omitting thinking on Sonnet 5 runs adaptive thinking, so "off" must be explicit.
    "sonnet": {"model": SONNET, "thinking": {"type": "disabled"}, "effort": None, "max_tokens": 2048},
    # The reasoning candidate. Its thinking budget = effort (how much it
    # deliberates) + max_tokens (hard ceiling on thinking + answer tokens).
    # budget_tokens is rejected by this model. Effort is confirmed by the pilot.
    "opus": {"model": OPUS, "thinking": {"type": "adaptive"}, "effort": "medium", "max_tokens": 4000},
}

# Models that get server-side refusal fallbacks (as Day 6's captioning did).
FALLBACK_MODELS = {OPUS}

# --- Budget (decision 11) ---
DAY_LIMIT_USD = 4.00
BUDGET_GUARD_USD = 3.50  # no new provider call once the ledger reaches this
