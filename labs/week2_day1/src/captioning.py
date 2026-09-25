"""Figure captions from a vision model, behind a disk cache and two gates.

Some Harbor facts exist only inside an image (the auto loan bar chart), so
each figure crop is described in text by Claude and that text is indexed
(spec.md "Figure captioning"). This is the only step where data leaves
Harbor's environment, so, before any API call:

  gate 1  the document's catalog sensitivity must be "public"
  gate 2  the picture must have a linked "Figure N." caption: real
          figures do, signatures / stamps / logos don't

Every decision (skipped, cache hit, API call) is appended to
cache/captions/calls.jsonl.

Determinism comes from the cache, not the request: captions are stored at
cache/captions/<image sha256>__<model>__<prompt version>.json and that
folder is committed, so the eval runs with --captions offline: no network,
no API key, and the same text on every run.

One-time live call (milestone 3):
    uv run python src/captioning.py --doc auto_loan_comparison --mode online
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from config import CAPTION_CACHE_DIR, DEFAULT_PARAMS, LAB_DIR, PROMPTS_DIR
from models import Block

MODEL = DEFAULT_PARAMS["caption"]["model"]
PROMPT_VERSION = DEFAULT_PARAMS["caption"]["prompt_version"]
# Server-side refusal fallbacks: if the model declines, the API re-runs the
# request on a fallback model inside the same call. Not a named argument in
# anthropic 0.104.1, so it goes in extra_body with its beta header.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_TOKENS = 2000  # a caption is a few hundred tokens; leave headroom for thinking

NON_PUBLIC_PLACEHOLDER = "[Figure not captioned: non-public document]"


class CaptionCacheMiss(RuntimeError):
    """Offline mode found no cached caption. Run once with --mode online."""


def caption_prefix(model: str = MODEL, prompt_version: str = PROMPT_VERSION) -> str:
    return f"[Figure caption, model-generated: {model}, prompt {prompt_version}]"


def cache_key(image_png: bytes, model: str = MODEL, prompt_version: str = PROMPT_VERSION) -> str:
    return f"{hashlib.sha256(image_png).hexdigest()}__{model}__{prompt_version}"


def load_prompt(prompt_version: str = PROMPT_VERSION) -> str:
    return (PROMPTS_DIR / f"figure_caption_{prompt_version}.md").read_text(encoding="utf-8").strip()


def load_api_key_from_env_file() -> None:
    """Earlier labs keep the key in the repo-root .env. Only fills it in if unset."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return
    env_file = LAB_DIR.parent.parent / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() == "ANTHROPIC_API_KEY" and value.strip():
            os.environ["ANTHROPIC_API_KEY"] = value.strip().strip("\"'")


def _log(cache_dir: Path, event: dict) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    with open(cache_dir / "calls.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(event, sort_keys=True) + "\n")


def _call_api(client, image_png: bytes, prompt: str) -> tuple[str, str, dict]:
    """One Messages API call. Returns (caption, model that served it, usage).

    No temperature/top_p: this model rejects sampling parameters.
    """
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        betas=[FALLBACK_BETA],
        extra_body={"fallbacks": "default"},
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {
                    "type": "base64", "media_type": "image/png",
                    "data": base64.standard_b64encode(image_png).decode("ascii"),
                }},
                {"type": "text", "text": prompt},
            ],
        }],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError(f"caption request refused: {getattr(response, 'stop_details', None)}")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("caption truncated at max_tokens; raise MAX_TOKENS")
    caption = "\n".join(b.text for b in response.content if b.type == "text").strip()
    usage = {"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens}
    return caption, response.model, usage


def caption_figure(
    block: Block,
    *,
    doc_id: str,
    sensitivity: str,
    mode: str,
    client=None,
    cache_dir: Path = CAPTION_CACHE_DIR,
) -> str:
    """Return the text to put in a figure block ("" means leave it out).

    mode: "online" calls the API on a cache miss; "offline" raises
    CaptionCacheMiss instead and never touches the network.
    """
    if mode not in ("online", "offline"):
        raise ValueError(f"unknown caption mode {mode!r}")
    event = {"doc_id": doc_id, "page": block.page, "image_ref": block.image_ref, "mode": mode}

    if sensitivity != "public":
        _log(cache_dir, {**event, "action": "skipped", "reason": f"non-public document ({sensitivity})"})
        return NON_PUBLIC_PLACEHOLDER
    if not block.figure_label or not block.image_ref:
        # A signature or stamp: nothing worth indexing, and never sent out.
        _log(cache_dir, {**event, "action": "skipped", "reason": "no linked figure caption (not a chart/figure)"})
        return ""

    image_png = (LAB_DIR / block.image_ref).read_bytes()
    key = cache_key(image_png)
    cache_file = cache_dir / f"{key}.json"
    event["image_sha256"] = key.split("__")[0]

    if cache_file.exists():
        cached = json.loads(cache_file.read_text(encoding="utf-8"))
        _log(cache_dir, {**event, "action": "cache_hit"})
        return f"{caption_prefix()}\n{cached['caption']}"
    if mode == "offline":
        _log(cache_dir, {**event, "action": "cache_miss_offline"})
        raise CaptionCacheMiss(f"no cached caption for {block.image_ref} ({doc_id} p.{block.page}); "
                               f"run: uv run python src/captioning.py --doc {doc_id} --mode online")

    if client is None:
        import anthropic

        load_api_key_from_env_file()
        client = anthropic.Anthropic()
    caption, served_by, usage = _call_api(client, image_png, load_prompt())
    record = {
        "caption": caption,
        "model": MODEL,
        "served_by": served_by,
        "prompt_version": PROMPT_VERSION,
        "doc_id": doc_id,
        "page": block.page,
        "figure_label": block.figure_label,
        "image_sha256": event["image_sha256"],
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "usage": usage,
    }
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(record, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    _log(cache_dir, {**event, "action": "api_call", "model": MODEL, "served_by": served_by, **usage})
    return f"{caption_prefix()}\n{caption}"


def apply_captions(blocks: list[Block], *, doc_id: str, sensitivity: str, mode: str, **kwargs) -> list[Block]:
    """Fill every figure block's text in place. mode "off" leaves them empty."""
    if mode == "off":
        return blocks
    for block in blocks:
        if block.type == "figure_caption":
            block.text = caption_figure(block, doc_id=doc_id, sensitivity=sensitivity, mode=mode, **kwargs)
    return blocks


if __name__ == "__main__":
    from config import CORPUS_DIR, SOURCE_CATALOG_PATH
    from parse_pdf_layout import parse_blocks

    ap = argparse.ArgumentParser(description="Caption the figures in one PDF (cache-first).")
    ap.add_argument("--doc", required=True, help="doc_id from config/source_catalog.csv")
    ap.add_argument("--mode", choices=["online", "offline"], default="offline")
    args = ap.parse_args()

    with open(SOURCE_CATALOG_PATH, encoding="utf-8", newline="") as f:
        row = next(r for r in csv.DictReader(f) if r["doc_id"] == args.doc)
    blocks, _ = parse_blocks(CORPUS_DIR / row["filename"])
    apply_captions(blocks, doc_id=args.doc, sensitivity=row["sensitivity"], mode=args.mode)
    for b in blocks:
        if b.type == "figure_caption":
            print(f"--- figure on p.{b.page} ({b.figure_label or 'no linked caption'})")
            print(b.text or "(skipped: not captioned)")
