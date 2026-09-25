import tempfile
import unittest
from pathlib import Path

from models import Block, Chunk, Decision, Document, read_jsonl, write_jsonl


def make_document() -> Document:
    doc = Document(
        doc_id="overdraft_policy_v3",
        source_filename="Overdraft_Policy_v3_FINAL.md",
        source_sha256="abc123",
        format="md",
        catalog={"title": "Overdraft Policy", "tenant": "retail", "superseded_by": ""},
        blocks=[
            Block(type="heading", text="Overdraft Policy", level=1, section_path=[]),
            Block(type="paragraph", text="A fee of $29 per item.", section_path=["Overdraft Policy"]),
            Block(type="table", text="Item | Fee\nNSF | $27.00", page=2, section_path=["Overdraft Policy"]),
        ],
        decision=Decision(status="cleaned", reason="stripped BOM", stage="clean", details={"bom": True}),
        history=["load:1a2b"],
        pii_spans=[{"type": "SSN", "start": 3, "end": 14, "value_sha256": "ff00"}],
    )
    doc.rebuild_text()
    return doc


class DecisionTests(unittest.TestCase):
    def test_rejection_requires_a_reason(self):
        # "Never a silent skip" is enforced by the data shape itself.
        with self.assertRaises(ValueError):
            Decision(status="dropped")
        with self.assertRaises(ValueError):
            Decision(status="quarantined", reason="")

    def test_unknown_status_rejected(self):
        with self.assertRaises(ValueError):
            Decision(status="skipped", reason="x")

    def test_only_pending_and_cleaned_are_active(self):
        self.assertTrue(Decision().is_active)
        self.assertTrue(Decision(status="cleaned").is_active)
        self.assertFalse(Decision(status="dropped", reason="empty file (0 bytes)").is_active)


class DocumentTests(unittest.TestCase):
    def test_text_is_blocks_joined_by_blank_lines(self):
        doc = make_document()
        self.assertEqual(doc.text, "Overdraft Policy\n\nA fee of $29 per item.\n\nItem | Fee\nNSF | $27.00")

    def test_round_trip_through_jsonl(self):
        doc = make_document()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "docs.jsonl"
            write_jsonl(path, [doc])
            (loaded,) = read_jsonl(path, Document)
        self.assertEqual(loaded, doc)
        self.assertIsInstance(loaded.blocks[0], Block)
        self.assertIsInstance(loaded.decision, Decision)

    def test_jsonl_output_is_byte_stable(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp) / "a.jsonl", Path(tmp) / "b.jsonl"
            write_jsonl(a, [make_document()])
            write_jsonl(b, [make_document()])
            self.assertEqual(a.read_bytes(), b.read_bytes())


class ChunkTests(unittest.TestCase):
    def test_chunk_id_is_deterministic(self):
        self.assertEqual(
            Chunk.make_id("overdraft_policy_v3", "layout", "B_structure", 4),
            "overdraft_policy_v3::layout::B_structure::0004",
        )

    def test_round_trip_through_jsonl(self):
        chunk = Chunk(
            chunk_id=Chunk.make_id("fee_schedule_2026", "layout", "A_fixed", 0),
            text="Returned item (NSF) | $27.00 | per item",
            metadata={"doc_id": "fee_schedule_2026", "page_start": 1, "is_current": True},
            embedding=[0.1, -0.2, 0.3],
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "chunks.jsonl"
            write_jsonl(path, [chunk])
            (loaded,) = read_jsonl(path, Chunk)
        self.assertEqual(loaded, chunk)


if __name__ == "__main__":
    unittest.main()
