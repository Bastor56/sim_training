"""Paths, seed, default stage parameters and pinned-model loading.

Every value that changes pipeline output lives here, so each run can record
the exact params it used (spec.md "Reproducibility rules"). Models are loaded
only at the revisions pinned in model_manifest.json, and only on CPU, so the
same inputs always produce the same vectors and scores.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

# The pipeline and eval make no network calls (spec "Reproducibility rules"):
# models load from the local Hugging Face cache only. On a new machine, run
# once with HARBOR_ALLOW_DOWNLOADS=1 to fetch the pinned models.
if os.environ.get("HARBOR_ALLOW_DOWNLOADS") != "1":
    os.environ.setdefault("HF_HUB_OFFLINE", "1")

LAB_DIR = Path(__file__).resolve().parent.parent

DATASET_DIR = LAB_DIR / "data" / "harbor_rag_dataset"
CORPUS_DIR = DATASET_DIR / "corpus"  # the ONLY pipeline input
GOLDEN_SET_PATH = DATASET_DIR / "eval" / "golden_set.yaml"
GROUND_TRUTH_DIR = DATASET_DIR / "eval" / "ground_truth_text"
ANSWER_KEY_DIR = DATASET_DIR / "_answer_key"  # grading only, never pipeline input

SOURCE_CATALOG_PATH = LAB_DIR / "config" / "source_catalog.csv"
MANIFEST_PATH = LAB_DIR / "model_manifest.json"
PROMPTS_DIR = LAB_DIR / "prompts"
CAPTION_CACHE_DIR = LAB_DIR / "cache" / "captions"
STAGE_CACHE_DIR = LAB_DIR / "cache" / "stages"
INDEX_DIR = LAB_DIR / "index"
RUNS_DIR = LAB_DIR / "runs"

SEED = 0
DEVICE = "cpu"  # no MPS/GPU: avoids nondeterministic kernels (spec "Determinism")

# Default params per stage. Anything that affects output belongs here, not
# hard-coded in a stage, so it ends up in the stage cache key and run config.
DEFAULT_PARAMS: dict[str, dict] = {
    "clean": {
        "near_empty_min_words": 50,
        "placeholder_phrases": ["content to follow", "coming soon", "tbd"],
        "placeholder_max_words": 200,  # a long doc that mentions "TBD" is not a placeholder
        "html_boilerplate_tags": ["header", "footer", "nav", "aside"],
        "html_boilerplate_names": ["cookie", "alert-bar", "promo", "breadcrumb", "utility-bar",
                                   "sidebar", "related-links"],
        "email_disclaimer_prefixes": ["CONFIDENTIALITY NOTICE"],
        "running_line_band": 3,  # lines at the top and bottom of each page to compare
        "running_line_min_page_share": 0.5,
    },
    "scrub": {
        "min_score": 0.5,
        # Harbor's own names that NER may tag as people: never PII.
        "allow_list": ["Harbor Credit Union", "Carrow Bay", "Port Alden", "Harbor Pay", "Courtesy Pay"],
    },
    "dedupe": {
        "shingle_words": 5,
        "near_duplicate_jaccard": 0.90,
    },
    "caption": {
        "model": "claude-opus-5",
        "prompt_version": "v1",
    },
    "A_fixed": {
        "size_chars": 800,
        "overlap_chars": 150,
        "boundary": "whitespace_backoff_50",
    },
    "B_structure": {
        "boundary": "heading",
        "max_chars": 1200,
        "min_chars": 200,
        "table_rule": "atomic_repeat_header",
        "table_max_chars": 2000,
        "prefix_section_path": True,
        "overlap_chars": 0,
    },
    "embed": {
        "batch_size": 32,
        "normalize_embeddings": True,
        "query_prefix": "Represent this sentence for searching relevant passages: ",
    },
    "bm25": {"k1": 1.5, "b": 0.75},
    "retrieval": {
        "candidates_per_retriever": 50,
        "rrf_k": 60,
        "rerank_candidates": 30,
        "top_k": 10,
        "reranker_max_length": 512,
    },
    "eval": {"k_values": [5, 10]},
}


def load_manifest() -> dict:
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        return json.load(f)


def model_spec(model_id: str) -> dict:
    """Return one manifest entry by its id ("embedder", "reranker", ...)."""
    for entry in load_manifest()["models"]:
        if entry["id"] == model_id:
            return entry
    raise KeyError(f"model id {model_id!r} not in {MANIFEST_PATH.name}")


def load_embedder():
    from sentence_transformers import SentenceTransformer

    spec = model_spec("embedder")
    return SentenceTransformer(spec["model"], revision=spec["revision"], device=DEVICE)


def load_reranker():
    from sentence_transformers import CrossEncoder

    spec = model_spec("reranker")
    return CrossEncoder(
        spec["model"],
        revision=spec["revision"],
        device=DEVICE,
        max_length=DEFAULT_PARAMS["retrieval"]["reranker_max_length"],
    )


def check_models_offline() -> None:
    """Load both pinned models and print their ids + revisions.

    Offline by default (see the top of this file). On a new machine, run it
    once with HARBOR_ALLOW_DOWNLOADS=1 to download the weights.
    """
    embedder = load_embedder()
    dim = embedder.get_embedding_dimension()
    load_reranker()
    offline = os.environ.get("HF_HUB_OFFLINE") == "1"
    for model_id in ("embedder", "reranker"):
        spec = model_spec(model_id)
        print(f"{model_id:9s} {spec['model']} @ {spec['revision']}")
    print(f"embedding dimension: {dim}   offline: {offline}")


if __name__ == "__main__":
    check_models_offline()
