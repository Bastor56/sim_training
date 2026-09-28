"""A fake Anthropic client: scripted responses, no network, no cost.

It mimics just the surface llm.py uses: client.messages.create(...) and
client.beta.messages.create(...), each returning an object with .model,
.stop_reason, .usage and .content (text blocks, plus an optional thinking
block to show that thinking is billed but never returned as text).
"""

from __future__ import annotations

import json
import time
from types import SimpleNamespace


def response(text="", *, model="claude-haiku-4-5", input_tokens=100, output_tokens=20,
             cache_read=0, cache_write=0, stop_reason="end_turn", thinking=False):
    content = []
    if thinking:
        content.append(SimpleNamespace(type="thinking", thinking=""))
    content.append(SimpleNamespace(type="text", text=text if isinstance(text, str) else json.dumps(text)))
    usage = SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens,
                            cache_read_input_tokens=cache_read, cache_creation_input_tokens=cache_write)
    return SimpleNamespace(model=model, stop_reason=stop_reason, usage=usage, content=content)


class _Messages:
    def __init__(self, owner, beta: bool):
        self.owner, self.beta = owner, beta

    def create(self, **kwargs):
        self.owner.calls.append({"beta": self.beta, **kwargs})
        if self.owner.delay_s:
            time.sleep(self.owner.delay_s)
        item = self.owner.script.pop(0) if self.owner.script else self.owner.default
        if isinstance(item, Exception):
            raise item
        if callable(item):
            return item(kwargs)
        return item


class FakeAnthropic:
    """script: responses (or exceptions, or callables of the request kwargs) returned in order."""

    def __init__(self, script=None, default=None, delay_s: float = 0.0):
        self.script = list(script or [])
        self.default = default or response('{"ok": true}')
        self.delay_s = delay_s
        self.calls: list[dict] = []
        self.messages = _Messages(self, beta=False)
        self.beta = SimpleNamespace(messages=_Messages(self, beta=True))
