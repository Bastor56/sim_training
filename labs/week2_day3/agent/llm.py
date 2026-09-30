"""THE instrumentation wrapper: the only door to the Claude API (spec.md "Instrumentation rules").

This is the only file in the lab allowed to import `anthropic` or create a
client (rule 1, enforced by tests/test_no_bypass.py). Every LLM call goes
through call(), which, in this order:

    1. refuses to run without a correlation id           (rule 2: no orphan calls)
    2. looks in the exact-match local cache               (a hit costs $0 and is still recorded)
    3. checks the spend guard                             (before any money is spent)
    4. calls the provider
    5. prices the usage from pricing.json, appends the spend ledger
    6. writes exactly one call record, in a `finally`     (rule 3: errors are recorded too)

Request settings per role come from settings.py (model, thinking, effort,
max_tokens). No temperature is ever sent: Sonnet 5 and Opus 5 reject it.

Day 3 adds native tool use: `tools=` (Claude's tool definitions, built from
what the MCP server advertised) and `messages=` (the multi-turn exchange of
tool_use / tool_result blocks). The result's `blocks` carry any tool_use
requests. Tool-path calls are never cached (`cache=False`): their inputs
include one member's records, which must never be replayed to another
(spec.md "Instrumentation and cost").
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field

import llm_cache
import pricing
import settings
import spend
import tracing

FALLBACK_BETA = "server-side-fallback-2026-07-01"  # as used by Day 6's captioning
REQUEST_TIMEOUT_S = 120

_config: dict = {"client": None, "cache_mode": "off", "namespace": None}


class LLMError(RuntimeError):
    """The provider answered, but not usably (refusal, truncation, unparseable JSON)."""


@dataclass
class LLMResult:
    call_id: str
    text: str
    data: dict | None  # parsed JSON when an output schema was given
    model_served: str
    usage: dict
    cost_usd: float
    local_cache: str  # "hit" | "miss" | "off"
    stop_reason: str
    record: dict = field(repr=False, default_factory=dict)
    # Every returned block as a plain dict: {"type": "text", "text"} or
    # {"type": "tool_use", "id", "name", "input"}. Ready to send back as the
    # assistant turn of the next request.
    blocks: list[dict] = field(default_factory=list)

    @property
    def tool_uses(self) -> list[dict]:
        return [b for b in self.blocks if b["type"] == "tool_use"]

    @property
    def latency_ms(self) -> float:
        # Filled in by call()'s `finally`, after the result object is built.
        return self.record.get("latency_ms", 0.0)


def configure(*, client=None, cache_mode: str | None = None, namespace: str | None = None) -> None:
    """Set the client (tests inject a fake), cache mode and cache namespace for later calls."""
    if client is not None:
        _config["client"] = client
    if cache_mode is not None:
        if cache_mode not in llm_cache.MODES:
            raise ValueError(f"cache_mode must be one of {llm_cache.MODES}")
        _config["cache_mode"] = cache_mode
    if namespace is not None:
        _config["namespace"] = namespace


def reset() -> None:
    _config.update(client=None, cache_mode="off", namespace=None)


def _load_api_key() -> None:
    """Earlier labs keep the key in the repo-root .env. Only fills it in if unset."""
    if os.environ.get("ANTHROPIC_API_KEY") or not settings.ENV_FILE.exists():
        return
    for line in settings.ENV_FILE.read_text(encoding="utf-8").splitlines():
        name, sep, value = line.partition("=")
        if sep and name.strip() == "ANTHROPIC_API_KEY" and value.strip():
            os.environ["ANTHROPIC_API_KEY"] = value.strip().strip("\"'")


def _client():
    if _config["client"] is None:
        import anthropic

        _load_api_key()
        _config["client"] = anthropic.Anthropic(timeout=REQUEST_TIMEOUT_S)
    return _config["client"]


def build_request(role: dict, system: str, user: str, output_schema: dict | None,
                  tools: list[dict] | None = None, messages: list[dict] | None = None) -> dict:
    """The provider-neutral description of one call (also what the cache key is built from)."""
    return {
        "model": role["model"],
        "thinking": role.get("thinking"),
        "effort": role.get("effort"),
        "max_tokens": role["max_tokens"],
        "output_schema": output_schema,
        "system": system,
        "user": user,
        "tools": tools,
        "messages": messages,
    }


def _send(client, request: dict):
    kwargs: dict = {
        "model": request["model"],
        "max_tokens": request["max_tokens"],
        # The static system prompt is the cacheable prefix for provider-side prompt
        # caching. Below the model's minimum prefix length it silently does nothing.
        "system": [{"type": "text", "text": request["system"], "cache_control": {"type": "ephemeral"}}],
        "messages": request["messages"] or [{"role": "user", "content": request["user"]}],
    }
    if request["tools"]:
        kwargs["tools"] = request["tools"]
    if request["thinking"] is not None:
        kwargs["thinking"] = request["thinking"]
    output_config: dict = {}
    if request["effort"] is not None:
        output_config["effort"] = request["effort"]
    if request["output_schema"] is not None:
        output_config["format"] = {"type": "json_schema", "schema": request["output_schema"]}
    if output_config:
        kwargs["output_config"] = output_config
    if request["model"] in settings.FALLBACK_MODELS:
        # Server-side refusal fallbacks: not a named argument in anthropic 0.104.1.
        return client.beta.messages.create(**kwargs, betas=[FALLBACK_BETA], extra_body={"fallbacks": "default"})
    return client.messages.create(**kwargs)


def _usage(response) -> dict:
    u = response.usage
    return {
        "input_tokens": u.input_tokens or 0,
        "output_tokens": u.output_tokens or 0,
        "cache_creation_input_tokens": getattr(u, "cache_creation_input_tokens", 0) or 0,
        "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", 0) or 0,
    }


def _text(content) -> str:
    """Visible answer only: thinking blocks are billed (in output_tokens) but not returned as text."""
    return "\n".join(b.text for b in content if getattr(b, "type", None) == "text").strip()


def _blocks(content) -> list[dict]:
    """Text and tool_use blocks as plain dicts (thinking blocks dropped, as in _text)."""
    out = []
    for b in content:
        kind = getattr(b, "type", None)
        if kind == "text":
            out.append({"type": "text", "text": b.text})
        elif kind == "tool_use":
            out.append({"type": "tool_use", "id": b.id, "name": b.name, "input": dict(b.input or {})})
    return out


def _parse(text: str, schema: dict | None) -> dict | None:
    if schema is None:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise LLMError(f"structured output was not valid JSON: {e}") from None


def call(
    purpose: str,
    role: dict,
    *,
    system: str,
    user: str,
    prompt_version: str,
    output_schema: dict | None = None,
    question: str | None = None,
    scope: dict | None = None,
    namespace: str | None = None,
    tools: list[dict] | None = None,
    messages: list[dict] | None = None,
    cache: bool = True,
) -> LLMResult:
    """One LLM call, recorded, cached, budget-checked and priced.

    purpose:  "gate" | "rewrite" | "generate" | "direct_answer" | "tool_select" | "generate_from_tools" | "smoke"
    role:     a settings.py role dict (model, thinking, effort, max_tokens)
    question: the member's raw question inside `user`, normalised for the cache key
    scope:    tenant / allow_restricted / current_only / corpus_version (cache key)
    namespace: overrides the configured cache namespace for this call
    tools:    Claude tool definitions; the reply may then contain tool_use blocks (LLMResult.tool_uses)
    messages: the full message list, for multi-turn tool use (replaces `user` in the request)
    cache:    False = never read or write the local cache for this call. Forced off whenever
              `tools` is given: tool-path calls carry member-specific records.
    """
    if tools and output_schema is not None:
        raise ValueError("a call is either a tool-use call or a structured-output call, not both")
    ctx = tracing.require_current()
    run = tracing.run()
    request = build_request(role, system, user, output_schema, tools, messages)
    mode, namespace = _config["cache_mode"], namespace or _config["namespace"]
    if tools or not cache:
        mode = "off"
    record: dict = {
        "call_id": tracing.new_call_id(),
        "correlation_id": ctx.correlation_id,
        "run_id": run.run_id,
        "ts": tracing.now_iso(),
        "kind": "llm",
        "purpose": purpose,
        "billable": ctx.billable,
        "model_requested": request["model"],
        "model_served": None,
        "fallback_used": False,
        "thinking": request["thinking"],
        "effort": request["effort"],
        "max_tokens": request["max_tokens"],
        "prompt_version": prompt_version,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "local_cache": "off",
        "cost_usd": 0.0,
        "cost_basis": "provider",
        "pricing_version": pricing.pricing_version(),
        "stop_reason": None,
        "error": None,
    }
    t0 = time.perf_counter()
    try:
        cache_key = None
        if mode != "off":
            if not namespace or scope is None:
                raise ValueError("caching needs a namespace (llm.configure) and a scope")
            cache_key = llm_cache.key(llm_cache.key_parts(request, prompt_version=prompt_version,
                                                          question=question, scope=scope))
            record["cache_key"] = cache_key
            hit = llm_cache.get(namespace, cache_key)
            if hit is not None:
                record.update(local_cache="hit", cost_basis="local_cache", model_served=hit["model_served"],
                              fallback_used=hit["model_served"] != request["model"],
                              stop_reason=hit["stop_reason"], cached_usage=hit["usage"])
                return LLMResult(record["call_id"], hit["text"], _parse(hit["text"], output_schema),
                                 hit["model_served"], hit["usage"], 0.0, "hit", hit["stop_reason"], record)
            record["local_cache"] = "miss"
            if mode == "read-only":
                raise llm_cache.CacheMissReadOnly(f"no cache entry {cache_key[:12]} in namespace {namespace!r}")

        spend.check(run_spend=run.provider_spend, run_cap=run.max_spend)
        response = _send(_client(), request)
        usage = _usage(response)
        # A dated snapshot of the requested alias is the same model, not a fallback.
        served = pricing.canonical(response.model or request["model"])
        record.update(usage, model_served=served, fallback_used=served != request["model"],
                      stop_reason=response.stop_reason)
        try:
            cost = pricing.cost(served, usage)
        except pricing.UnknownModelPrice:
            # A fallback model we have no price for: price at the requested model, flagged.
            cost = pricing.cost(request["model"], usage)
            record["pricing_note"] = f"no price for served model {served}; priced as {request['model']}"
        record["cost_usd"] = cost
        run.provider_spend += cost
        spend.append({"ts": record["ts"], "run_id": run.run_id, "call_id": record["call_id"],
                      "purpose": purpose, "model": served, "cost_usd": cost})

        if response.stop_reason == "refusal":
            raise LLMError(f"refused: {getattr(response, 'stop_details', None)}")
        if response.stop_reason == "max_tokens":
            raise LLMError(f"truncated at max_tokens={request['max_tokens']}")
        text = _text(response.content)
        blocks = _blocks(response.content)
        if tools:
            record["tools_offered"] = [x["name"] for x in tools]
            record["tool_uses"] = [b["name"] for b in blocks if b["type"] == "tool_use"]
        data = _parse(text, output_schema)
        if cache_key is not None and mode == "read-write":
            llm_cache.put(namespace, cache_key, {
                "text": text, "model_served": served, "usage": usage, "stop_reason": response.stop_reason,
                "purpose": purpose, "prompt_version": prompt_version, "created_at": record["ts"],
            })
        return LLMResult(record["call_id"], text, data, served, usage, cost,
                         record["local_cache"], response.stop_reason, record, blocks)
    except Exception as e:
        record["error"] = f"{type(e).__name__}: {e}"
        raise
    finally:
        record["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        tracing.write_record(record)
