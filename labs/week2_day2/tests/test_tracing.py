import json

import pytest

import tracing


def test_interaction_sets_and_clears_correlation_id(lab):
    assert tracing.current() is None
    with tracing.interaction("test_run/q001") as ctx:
        assert tracing.current() is ctx and ctx.billable
    assert tracing.current() is None


def test_nested_interaction_restores_outer(lab):
    with tracing.interaction("outer"):
        with tracing.interaction("inner", billable=False):
            assert tracing.current().correlation_id == "inner"
        assert tracing.current().correlation_id == "outer"


def test_record_local_is_free_and_tagged(lab):
    with tracing.interaction("test_run/q001") as ctx:
        rec = tracing.record_local("retrieve", 1480.26, round=1)
    assert rec["kind"] == "local_model" and rec["cost_usd"] == 0.0 and rec["latency_ms"] == 1480.3
    assert rec["correlation_id"] == "test_run/q001" and rec["round"] == 1
    assert ctx.records == [rec]


def test_trace_events_written_with_cid(lab):
    with tracing.interaction("test_run/q001"):
        tracing.trace("gate", decision="retrieve", reason="asks for a fee")
    [event] = [json.loads(line) for line in (lab["run"].dir / "trace.jsonl").read_text().splitlines()]
    assert event["cid"] == "test_run/q001" and event["event"] == "gate" and event["reason"] == "asks for a fee"


def test_local_record_outside_interaction_raises(lab):
    with pytest.raises(tracing.NoActiveInteraction):
        tracing.record_local("retrieve", 1.0)
