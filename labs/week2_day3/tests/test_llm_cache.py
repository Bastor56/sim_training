"""The "safely equivalent" rule (spec.md "Cache"): one test per row of the table."""

import pytest

import fakes
import llm
import llm_cache
import settings
import tracing

SCOPE = {"tenant": "retail", "allow_restricted": False, "current_only": True,
         "corpus_version": "1|harbor__layout__B_structure__5c38ec7c"}
SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"],
          "additionalProperties": False}


def _key(question="What is the wire fee?", *, chunk="Wire fee: $30.", role=None, prompt_version="gen_v1", **scope):
    user = f"Question: {question}\nEvidence: {chunk}"
    request = llm.build_request(role or settings.GATE, "sys", user, SCHEMA)
    return llm_cache.key(llm_cache.key_parts(request, prompt_version=prompt_version, question=question,
                                             scope={**SCOPE, **scope}))


def test_surface_variants_share_a_key():
    assert _key("What is the wire fee?") == _key("  what is the WIRE   fee ") == _key("What is the wire fee")


def test_paraphrase_misses_by_design():
    assert _key("What is the wire fee?") != _key("How much does a wire cost?")


@pytest.mark.parametrize("change", [
    {"tenant": "business"},
    {"allow_restricted": True},
    {"current_only": False},
    {"corpus_version": "2|harbor__layout__B_structure__5c38ec7c"},
    {"prompt_version": "gen_v2"},
    {"role": settings.GENERATORS["sonnet"]},
    {"role": {**settings.GENERATORS["opus"], "effort": "low"}},
    {"chunk": "Wire fee: $35."},
])
def test_any_other_difference_changes_the_key(change):
    assert _key(**change) != _key()


def _cached_call(question):
    return llm.call("gate", settings.GATE, system="sys", user=f"Question: {question}", prompt_version="gate_v1",
                    output_schema=SCHEMA, question=question, scope=SCOPE)


def test_second_identical_call_is_a_free_recorded_hit(lab):
    llm.configure(cache_mode="read-write", namespace="t")
    lab["client"].default = fakes.response({"ok": True}, input_tokens=500, output_tokens=50)
    with tracing.interaction("test_run/q001") as ctx:
        first = _cached_call("What is the wire fee?")
        second = _cached_call("what is the wire fee")
    assert len(lab["client"].calls) == 1
    assert first.local_cache == "miss" and first.cost_usd > 0
    assert second.local_cache == "hit" and second.cost_usd == 0.0 and second.data == {"ok": True}
    assert [r["local_cache"] for r in ctx.records] == ["miss", "hit"]
    hit = ctx.records[1]
    assert hit["cost_basis"] == "local_cache" and hit["input_tokens"] == 0 and hit["cached_usage"]["input_tokens"] == 500
    assert "wire" not in str(hit).lower()  # the record holds the key, never the question


def test_read_only_never_calls_the_client(lab):
    llm.configure(cache_mode="read-only", namespace="t")
    with tracing.interaction("test_run/q001"):
        with pytest.raises(llm_cache.CacheMissReadOnly):
            _cached_call("What is the wire fee?")
    assert lab["client"].calls == []


def test_failed_call_is_not_cached(lab):
    llm.configure(cache_mode="read-write", namespace="t")
    lab["client"].script = [fakes.response("{", stop_reason="max_tokens")]
    with tracing.interaction("test_run/q001"):
        with pytest.raises(llm.LLMError):
            _cached_call("What is the wire fee?")
        _cached_call("What is the wire fee?")  # retried at the provider, not served from cache
    assert len(lab["client"].calls) == 2
