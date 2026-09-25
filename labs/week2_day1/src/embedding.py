"""bge-small embeddings at the pinned revision (spec.md "Embedding and indexing").

- CPU only and seeded, so the same text always gets the same vector.
- Vectors are L2-normalised, so cosine similarity is a dot product.
- Queries get bge's retrieval instruction prefix; chunks don't. (bge was
  trained that way: short questions and long passages are embedded
  asymmetrically.)
- Chunks longer than the model's 512-token window are counted and warned
  about, because the model would silently ignore everything past the limit.
"""

from __future__ import annotations

import random
import warnings

from config import DEFAULT_PARAMS, SEED, load_embedder, model_spec

_model = None


def model():
    global _model
    if _model is None:
        import numpy as np
        import torch

        random.seed(SEED)
        np.random.seed(SEED)
        torch.manual_seed(SEED)
        _model = load_embedder()
    return _model


def embedding_identity() -> dict:
    spec = model_spec("embedder")
    return {"embedding_model": spec["model"], "embedding_revision": spec["revision"]}


def count_over_limit(texts: list[str]) -> int:
    m = model()
    limit = m.max_seq_length
    return sum(len(m.tokenizer(t, add_special_tokens=True)["input_ids"]) > limit for t in texts)


def embed_passages(texts: list[str], params: dict = DEFAULT_PARAMS["embed"]) -> list[list[float]]:
    over = count_over_limit(texts)
    if over:
        warnings.warn(f"{over} chunk(s) exceed the embedder's {model().max_seq_length}-token window; "
                      "their tails will not be represented in the vector")
    vectors = model().encode(texts, batch_size=params["batch_size"],
                             normalize_embeddings=params["normalize_embeddings"], show_progress_bar=False)
    return [[round(float(x), 7) for x in v] for v in vectors]


def embed_query(query: str, params: dict = DEFAULT_PARAMS["embed"]) -> list[float]:
    vector = model().encode([params["query_prefix"] + query],
                            normalize_embeddings=params["normalize_embeddings"], show_progress_bar=False)[0]
    return [float(x) for x in vector]
