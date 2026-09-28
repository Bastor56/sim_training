"""Puts Day 2's src/ first on sys.path, then Day 6's, so tests import both
labs' flat modules directly. Day 2 comes first so a Day 6 file can never
shadow a Day 2 one (spec.md "Import rule"). pytest loads this automatically.

The `lab` fixture points every file the wrapper writes (run records, the
spend ledger, the LLM cache) at a temporary folder and installs a fake
client, so no test touches the real ledger, the committed cache or the API.
"""

import os
import sys

import pytest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "src"))
sys.path.append(os.path.join(HERE, "..", "..", "week2_day1", "src"))

import llm  # noqa: E402
import settings  # noqa: E402
import tracing  # noqa: E402
from fakes import FakeAnthropic  # noqa: E402


@pytest.fixture
def lab(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "SPEND_LEDGER_PATH", tmp_path / "spend_ledger.jsonl")
    monkeypatch.setattr(settings, "CACHE_DIR", tmp_path / "cache")
    run = tracing.start_run("test_run", tmp_path / "runs" / "test_run")
    client = FakeAnthropic()
    llm.reset()
    llm.configure(client=client)
    yield {"tmp": tmp_path, "run": run, "client": client}
    llm.reset()
    tracing.start_run("adhoc")
