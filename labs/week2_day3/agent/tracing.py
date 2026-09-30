"""Correlation IDs, call records and trace events (spec.md "Instrumentation rules").

Everything one user question causes (the gate call, each retrieval round,
rewrites, the answer) is tagged with one correlation ID, so its cost and
latency can be summed. The ID lives in a ContextVar, set once by

    with tracing.interaction("<run_id>/<query_id>"):
        graph.invoke(...)

so no node has to pass it around, and llm.call() refuses to run without one
(rule 2, "no orphan calls").

Files written for the active run (runs/<run_id>/):
    calls.jsonl   one record per LLM call or local-model step
    trace.jsonl   agent events: gate, retrieve, validate, rewrite, generate, outcome
"""

from __future__ import annotations

import json
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from settings import RUNS_DIR


class NoActiveInteraction(RuntimeError):
    """An LLM call was made outside `with tracing.interaction(...)`."""


@dataclass
class Run:
    run_id: str
    dir: Path
    max_spend: float | None = None  # per-run cap on provider spend, USD
    provider_spend: float = 0.0  # provider cost so far in this run (cache hits excluded)

    def append(self, filename: str, obj: dict) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        with open(self.dir / filename, "a", encoding="utf-8") as f:
            f.write(json.dumps(obj, sort_keys=True, ensure_ascii=False) + "\n")


@dataclass
class Interaction:
    correlation_id: str
    billable: bool = True
    records: list[dict] = field(default_factory=list)  # every call record, in order
    started: float = field(default_factory=time.perf_counter)


_run: Run = Run("adhoc", RUNS_DIR / "adhoc")
_current: ContextVar[Interaction | None] = ContextVar("interaction", default=None)


def start_run(run_id: str, run_dir: Path | None = None, max_spend: float | None = None) -> Run:
    """Make run_id the destination for every record and trace event from now on."""
    global _run
    _run = Run(run_id, run_dir or RUNS_DIR / run_id, max_spend)
    return _run


def run() -> Run:
    return _run


def current() -> Interaction | None:
    return _current.get()


def require_current() -> Interaction:
    ctx = _current.get()
    if ctx is None:
        raise NoActiveInteraction("every LLM call needs a correlation id: wrap it in tracing.interaction(...)")
    return ctx


@contextmanager
def interaction(correlation_id: str, billable: bool = True):
    """One user question (billable=True) or one eval-only step such as judging (billable=False)."""
    ctx = Interaction(correlation_id, billable)
    token = _current.set(ctx)
    try:
        yield ctx
    finally:
        _current.reset(token)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def new_call_id() -> str:
    return uuid.uuid4().hex[:16]


def write_record(record: dict) -> None:
    """Append one call record to calls.jsonl and to the active interaction."""
    ctx = require_current()
    _run.append("calls.jsonl", record)
    ctx.records.append(record)


def record_local(purpose: str, latency_ms: float, **details) -> dict:
    """A local model step (embedding + BM25 + vector + rerank): no token cost, real latency (rule 4)."""
    ctx = require_current()
    record = {
        "call_id": new_call_id(),
        "correlation_id": ctx.correlation_id,
        "run_id": _run.run_id,
        "ts": now_iso(),
        "kind": "local_model",
        "purpose": purpose,
        "billable": ctx.billable,
        "latency_ms": round(latency_ms, 1),
        "cost_usd": 0.0,
        "cost_basis": "local_model",
        **details,
    }
    write_record(record)
    return record


def record_tool(tool: str, latency_ms: float, **details) -> dict:
    """One MCP tool call (Day 3): no token cost, real latency, same correlation id as the question."""
    ctx = require_current()
    record = {
        "call_id": new_call_id(),
        "correlation_id": ctx.correlation_id,
        "run_id": _run.run_id,
        "ts": now_iso(),
        "kind": "mcp_tool",
        "purpose": "tool_call",
        "tool": tool,
        "billable": ctx.billable,
        "latency_ms": round(latency_ms, 1),
        "cost_usd": 0.0,
        "cost_basis": "mcp_tool",
        **details,
    }
    write_record(record)
    return record


def trace(event: str, **fields) -> None:
    """One agent event for the active interaction (trace.jsonl)."""
    ctx = require_current()
    _run.append("trace.jsonl", {"cid": ctx.correlation_id, "event": event, "ts": now_iso(), **fields})
