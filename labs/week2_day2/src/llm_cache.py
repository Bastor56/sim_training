"""Exact-match local cache in front of the provider (spec.md "Cache", decision 8).

Two LLM calls may share a cached response only if everything that could
change the answer is identical (the "safely equivalent" rule):

    model, thinking config, effort, max_tokens, output schema   same model + settings
    prompt version                                              a prompt edit never serves an old answer
    rendered system + user message (retrieved chunks included)  same question, same evidence
    tenant                                                      retail and business fees differ
    access scope (allow_restricted, current_only)               a cleared answer never reaches a member session
    corpus version (golden-set corpus_version + index name)     a re-ingested corpus invalidates everything

Only the member's question is normalised (NFKC, casefold, collapse
whitespace, strip trailing ?!.): "What is the wire fee?" and
"  what is the WIRE fee " share an entry; a paraphrase does not, on purpose.
A semantic cache would treat "overdraft fee" and "overdraft fee for a
business account", or Overdraft v2 and v3 wording, as the same question:
exactly the cases where Harbor's answers differ.

Entries live at cache/llm/<namespace>/<sha256>.json and are committed, so a
reported run can be replayed for $0. The key is recorded, never the question.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path

import settings

MODES = ("off", "read-only", "read-write")

_TRAILING = re.compile(r"[?!.\s]+$")


class CacheMissReadOnly(RuntimeError):
    """read-only mode (replay) found no entry, and must not call the provider."""


def normalise_question(question: str) -> str:
    text = unicodedata.normalize("NFKC", question).casefold()
    text = " ".join(text.split())
    return _TRAILING.sub("", text)


def key_parts(request: dict, *, prompt_version: str, question: str | None, scope: dict) -> dict:
    """Everything the key covers. The question is swapped for its normalised form."""
    user = request["user"]
    if question:
        user = user.replace(question, normalise_question(question))
    return {
        "model": request["model"],
        "thinking": request.get("thinking"),
        "effort": request.get("effort"),
        "max_tokens": request["max_tokens"],
        "output_schema": request.get("output_schema"),
        "prompt_version": prompt_version,
        "system": request["system"],
        "user": user,
        "tenant": scope["tenant"],
        "allow_restricted": scope["allow_restricted"],
        "current_only": scope["current_only"],
        "corpus_version": scope["corpus_version"],
    }


def key(parts: dict) -> str:
    canonical = json.dumps(parts, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _path(namespace: str, cache_key: str) -> Path:
    return settings.CACHE_DIR / namespace / f"{cache_key}.json"


def get(namespace: str, cache_key: str) -> dict | None:
    path = _path(namespace, cache_key)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def put(namespace: str, cache_key: str, entry: dict) -> None:
    path = _path(namespace, cache_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entry, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
