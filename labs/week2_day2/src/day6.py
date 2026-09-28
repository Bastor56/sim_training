"""The only bridge to Day 6's code (spec.md "Import rule", decision 1).

Day 2 reuses Day 6's retrieval path and index unchanged, by importing it
rather than copying it, so there is exactly one retrieval implementation to
evaluate. Day 6's modules are flat files (config.py, golden.py, ...) found
through sys.path, so this file appends Day 6's src/ to sys.path *after*
Day 2's: a Day 2 module can never be shadowed by a Day 6 one, and
test_no_bypass.py checks the two sets of names never overlap.

Every other Day 2 module imports Day 6 names from here, never directly.
"""

from __future__ import annotations

import sys
from pathlib import Path

DAY6_DIR = Path(__file__).resolve().parent.parent.parent / "week2_day1"
DAY6_SRC = DAY6_DIR / "src"

if str(DAY6_SRC) not in sys.path:
    sys.path.append(str(DAY6_SRC))

# Importing Day 6's config also sets HF_HUB_OFFLINE=1: models load from the
# local cache only, so retrieval never touches the network.
from config import DEFAULT_PARAMS as DAY6_PARAMS  # noqa: E402
from config import GOLDEN_SET_PATH, INDEX_DIR  # noqa: E402
from golden import GoldenQuery, GoldenSet, Location, load_golden_set, matches, normalise, relevant_items  # noqa: E402
from index import collection_name  # noqa: E402
from retrieval import Response, Result, Retriever, access_filter  # noqa: E402

__all__ = [
    "DAY6_DIR", "DAY6_SRC", "DAY6_PARAMS", "GOLDEN_SET_PATH", "INDEX_DIR",
    "GoldenQuery", "GoldenSet", "Location", "load_golden_set", "matches", "normalise", "relevant_items",
    "collection_name", "Response", "Result", "Retriever", "access_filter",
]
