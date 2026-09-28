"""Pinned per-model rates and the cost of one call (spec.md "Cost formula").

    cost = input_tokens                x input rate
         + cache_creation_input_tokens x 5-minute cache-write rate
         + cache_read_input_tokens     x cache-read rate
         + output_tokens               x output rate      (thinking tokens included)

Rates come from pricing.json, never from code, and a model with no entry is
an error: a missing price must never quietly become $0.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from settings import PRICING_PATH

PER = 1_000_000  # rates are USD per million tokens


class UnknownModelPrice(KeyError):
    """The model has no row in pricing.json."""


@lru_cache(maxsize=None)
def load(path: Path = PRICING_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def pricing_version() -> str:
    return load()["pricing_version"]


_DATE_SUFFIX = re.compile(r"-\d{8}$")


def canonical(model: str) -> str:
    """The pricing.json name for a model ID the API reports.

    The API can report a dated snapshot ("claude-haiku-4-5-20251001") for
    the alias we requested ("claude-haiku-4-5"); both are the same model at
    the same price. Found in the milestone 2 smoke test.
    """
    models = load()["models"]
    if model in models:
        return model
    undated = _DATE_SUFFIX.sub("", model)
    return undated if undated in models else model


def rates(model: str) -> dict:
    try:
        return load()["models"][canonical(model)]
    except KeyError:
        raise UnknownModelPrice(f"no price for {model!r} in {PRICING_PATH.name}; add it from the live pricing page") from None


def cost(model: str, usage: dict) -> float:
    """USD for one call, from its usage token counts."""
    r = rates(model)
    total = (
        usage.get("input_tokens", 0) * r["input"]
        + usage.get("cache_creation_input_tokens", 0) * r["cache_write_5m"]
        + usage.get("cache_read_input_tokens", 0) * r["cache_read"]
        + usage.get("output_tokens", 0) * r["output"]
    )
    return round(total / PER, 8)
