import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from captioning import CaptionCacheMiss, NON_PUBLIC_PLACEHOLDER, apply_captions, cache_key, caption_figure
from config import LAB_DIR
from models import Block


class FakeClient:
    """Stands in for anthropic.Anthropic(): records calls, never hits the network."""

    def __init__(self, caption="Average approval time by channel.\n- Mobile app: 0.6 business days"):
        self.calls = []
        outer = self

        class _Messages:
            def create(self, **kwargs):
                outer.calls.append(kwargs)
                return SimpleNamespace(
                    content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=caption)],
                    stop_reason="end_turn",
                    model=kwargs["model"],
                    usage=SimpleNamespace(input_tokens=900, output_tokens=80),
                )

        self.beta = SimpleNamespace(messages=_Messages())


class CaptioningTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.cache_dir = Path(self._tmp.name) / "captions"
        # A tiny PNG inside the lab dir, because image_ref is lab-relative.
        self._img_dir = tempfile.TemporaryDirectory(dir=LAB_DIR / "cache")
        self.png = Path(self._img_dir.name) / "fig.png"
        self.png.write_bytes(b"\x89PNG\r\n\x1a\nfake-chart-bytes")
        self.block = Block(type="figure_caption", text="", page=1, generated=True,
                           image_ref=str(self.png.relative_to(LAB_DIR)),
                           figure_label="Figure 1. Average approval time by application channel")

    def tearDown(self):
        self._img_dir.cleanup()
        self._tmp.cleanup()

    def caption(self, block=None, **kwargs):
        defaults = dict(doc_id="auto_loan_comparison", sensitivity="public", mode="online", cache_dir=self.cache_dir)
        return caption_figure(block or self.block, **{**defaults, **kwargs})

    def log(self):
        return [json.loads(line) for line in (self.cache_dir / "calls.jsonl").read_text().splitlines()]

    def test_miss_online_calls_once_then_hits_cache(self):
        client = FakeClient()
        first = self.caption(client=client)
        second = self.caption(client=client)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(first, second)
        self.assertTrue(first.startswith("[Figure caption, model-generated: claude-opus-5, prompt v1]"))
        self.assertIn("Mobile app: 0.6 business days", first)
        self.assertEqual([e["action"] for e in self.log()], ["api_call", "cache_hit"])

    def test_request_shape(self):
        client = FakeClient()
        self.caption(client=client)
        (call,) = client.calls
        self.assertEqual(call["model"], "claude-opus-5")
        self.assertNotIn("temperature", call)  # rejected by this model
        self.assertEqual(call["extra_body"], {"fallbacks": "default"})
        image, text = call["messages"][0]["content"]
        self.assertEqual(image["source"]["media_type"], "image/png")
        self.assertEqual(text["type"], "text")

    def test_offline_miss_raises_without_calling(self):
        client = FakeClient()
        with self.assertRaises(CaptionCacheMiss):
            self.caption(mode="offline", client=client)
        self.assertEqual(client.calls, [])

    def test_offline_hit_needs_no_client(self):
        self.caption(client=FakeClient())
        self.assertIn("0.6", self.caption(mode="offline", client=None))

    def test_non_public_document_never_calls(self):
        client = FakeClient()
        self.assertEqual(self.caption(sensitivity="internal", client=client), NON_PUBLIC_PLACEHOLDER)
        self.assertEqual(client.calls, [])
        self.assertEqual(self.log()[0]["action"], "skipped")

    def test_signature_without_linked_caption_never_calls(self):
        client = FakeClient()
        signature = Block(type="figure_caption", text="", page=1, generated=True, image_ref=self.block.image_ref)
        self.assertEqual(self.caption(block=signature, client=client), "")
        self.assertEqual(client.calls, [])
        self.assertIn("no linked figure caption", self.log()[0]["reason"])

    def test_key_changes_with_prompt_version_and_model(self):
        png = self.png.read_bytes()
        self.assertNotEqual(cache_key(png, "claude-opus-5", "v1"), cache_key(png, "claude-opus-5", "v2"))
        self.assertNotEqual(cache_key(png, "claude-opus-5", "v1"), cache_key(png, "other-model", "v1"))

    def test_apply_captions_off_leaves_blocks_untouched(self):
        blocks = apply_captions([self.block], doc_id="x", sensitivity="public", mode="off")
        self.assertEqual(blocks[0].text, "")

    def test_refusal_raises(self):
        client = FakeClient()
        original = client.beta.messages.create

        def refuse(**kwargs):
            r = original(**kwargs)
            r.stop_reason = "refusal"
            return r

        client.beta.messages.create = refuse
        with self.assertRaises(RuntimeError):
            self.caption(client=client)
        self.assertFalse(any(self.cache_dir.glob("*.json")))  # nothing cached


if __name__ == "__main__":
    unittest.main()
