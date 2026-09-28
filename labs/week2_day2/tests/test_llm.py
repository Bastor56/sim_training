"""The wrapper's contract (spec.md "Instrumentation rules"), with a fake client."""

import json

import pytest

import fakes
import llm
import settings
import spend
import tracing

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"],
          "additionalProperties": False}
RECORD_FIELDS = {
    "call_id", "correlation_id", "run_id", "ts", "kind", "purpose", "billable", "model_requested",
    "model_served", "fallback_used", "thinking", "effort", "max_tokens", "prompt_version", "input_tokens",
    "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "local_cache", "latency_ms",
    "cost_usd", "cost_basis", "pricing_version", "stop_reason", "error",
}


def _call(purpose="smoke", role=None, **kw):
    return llm.call(purpose, role or settings.GATE, system="sys", user="Reply ok", prompt_version="t_v1",
                    output_schema=SCHEMA, **kw)


def _records(lab):
    path = lab["run"].dir / "calls.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_call_outside_interaction_raises(lab):
    with pytest.raises(tracing.NoActiveInteraction):
        _call()
    assert lab["client"].calls == []


def test_one_call_one_complete_record(lab):
    lab["client"].script = [fakes.response({"ok": True}, input_tokens=2500, output_tokens=300)]
    with tracing.interaction("test_run/q001") as ctx:
        result = _call()
    assert result.data == {"ok": True}
    [rec] = _records(lab)
    assert RECORD_FIELDS <= set(rec)
    assert rec["correlation_id"] == "test_run/q001" and rec["purpose"] == "smoke"
    assert rec["cost_usd"] == pytest.approx(0.004) and rec["cost_basis"] == "provider"
    assert rec["latency_ms"] >= 0 and result.latency_ms == rec["latency_ms"]
    assert ctx.records == [rec]
    assert spend.total() == pytest.approx(0.004)


def test_api_error_still_recorded(lab):
    lab["client"].script = [RuntimeError("boom")]
    with tracing.interaction("test_run/q002"):
        with pytest.raises(RuntimeError):
            _call()
    [rec] = _records(lab)
    assert rec["error"] == "RuntimeError: boom" and rec["cost_usd"] == 0.0


def test_truncation_is_billed_and_recorded_as_error(lab):
    lab["client"].script = [fakes.response("{", output_tokens=1024, stop_reason="max_tokens")]
    with tracing.interaction("test_run/q003"):
        with pytest.raises(llm.LLMError):
            _call()
    [rec] = _records(lab)
    assert rec["error"].startswith("LLMError: truncated") and rec["cost_usd"] > 0
    assert spend.total() == pytest.approx(rec["cost_usd"])


def test_guard_blocks_before_the_client_is_called(lab):
    spend.append({"run_id": "earlier", "call_id": "x", "purpose": "dev", "model": "m", "cost_usd": 3.49})
    with tracing.interaction("test_run/a"):
        _call()  # $3.49 < $3.50: allowed
    assert len(lab["client"].calls) == 1
    spend.append({"run_id": "earlier", "call_id": "y", "purpose": "dev", "model": "m", "cost_usd": 0.01})
    with tracing.interaction("test_run/b"):
        with pytest.raises(spend.BudgetExceeded):
            _call()
    assert len(lab["client"].calls) == 1  # never reached the provider
    assert _records(lab)[-1]["error"].startswith("BudgetExceeded")


def test_per_run_cap(lab):
    lab["run"].max_spend = 0.001
    lab["client"].default = fakes.response({"ok": True}, input_tokens=2000, output_tokens=0)  # $0.002
    with tracing.interaction("test_run/a"):
        _call()
        with pytest.raises(spend.BudgetExceeded):
            _call()


def test_non_billable_interaction_is_marked(lab):
    with tracing.interaction("test_run/q001#judge", billable=False):
        _call("judge", settings.JUDGE)
    assert _records(lab)[0]["billable"] is False


def test_request_shape_per_role(lab):
    with tracing.interaction("test_run/r"):
        _call(role=settings.GATE)
        _call(role=settings.GENERATORS["sonnet"])
        _call(role=settings.GENERATORS["opus"])
    haiku, sonnet, opus = lab["client"].calls
    for c in (haiku, sonnet, opus):
        assert "temperature" not in c
        assert c["system"][0]["cache_control"] == {"type": "ephemeral"}
        assert c["output_config"]["format"]["type"] == "json_schema"
    assert "thinking" not in haiku and not haiku["beta"]
    assert sonnet["thinking"] == {"type": "disabled"}
    assert opus["beta"] and opus["thinking"] == {"type": "adaptive"}
    assert opus["output_config"]["effort"] == settings.GENERATORS["opus"]["effort"]
    assert opus["max_tokens"] == 4000 and opus["extra_body"] == {"fallbacks": "default"}


def test_thinking_is_billed_but_not_returned(lab):
    lab["client"].script = [fakes.response({"ok": True}, model="claude-opus-5", input_tokens=0,
                                           output_tokens=1000, thinking=True)]
    with tracing.interaction("test_run/t"):
        result = _call(role=settings.GENERATORS["opus"])
    assert result.data == {"ok": True}
    assert result.cost_usd == pytest.approx(0.025)  # 1,000 output tokens x $25/MTok


def test_dated_snapshot_is_not_a_fallback(lab):
    # Milestone 2 finding: the API reports "claude-haiku-4-5-20251001" for "claude-haiku-4-5".
    lab["client"].script = [fakes.response({"ok": True}, model="claude-haiku-4-5-20251001")]
    with tracing.interaction("test_run/d"):
        _call()
    rec = _records(lab)[0]
    assert rec["model_served"] == "claude-haiku-4-5" and rec["fallback_used"] is False
    assert "pricing_note" not in rec


def test_fallback_served_by_other_model_is_flagged_and_priced_as_served(lab):
    lab["client"].script = [fakes.response({"ok": True}, model="claude-sonnet-5", input_tokens=1_000_000,
                                           output_tokens=0)]
    with tracing.interaction("test_run/f"):
        result = _call(role=settings.GENERATORS["opus"])
    rec = _records(lab)[0]
    assert rec["fallback_used"] is True and rec["model_served"] == "claude-sonnet-5"
    assert result.cost_usd == pytest.approx(2.00)
