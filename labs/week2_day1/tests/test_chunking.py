import tempfile
import unittest
from pathlib import Path

from chunking import make_chunker
from config import DEFAULT_PARAMS
from golden import load_golden_set, matches
from models import Block, Decision, Document
from pipeline import run_ingestion


def chunk(name: str, docs):
    return make_chunker(name, DEFAULT_PARAMS[name]).chunk(docs)


class RealCorpusChunkTests(unittest.TestCase):
    """Chunk the real (cached) layout-parsed, scrubbed corpus with both strategies."""

    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as tmp:
            docs, _ = run_ingestion("layout", stop_after="scrub", run_dir=Path(tmp))
        cls.docs = docs
        cls.by_id = {d.doc_id: d for d in docs}
        cls.A = chunk("A_fixed", docs)
        cls.B = chunk("B_structure", docs)

    def body(self, c) -> str:
        """Chunk text without B's section-path prefix."""
        return c.text[c.metadata.get("prefix_chars", 0):]

    def test_offsets_point_at_the_chunk_text(self):
        for c in self.A + self.B:
            doc = self.by_id[c.metadata["doc_id"]]
            self.assertEqual(doc.text[c.metadata["char_start"]:c.metadata["char_end"]], self.body(c), c.chunk_id)

    def test_a_size_overlap_and_word_boundaries(self):
        p = DEFAULT_PARAMS["A_fixed"]
        self.assertLessEqual(max(len(c.text) for c in self.A), p["size_chars"])
        for c in self.A:
            text = self.by_id[c.metadata["doc_id"]].text
            s, e = c.metadata["char_start"], c.metadata["char_end"]
            self.assertTrue(s == 0 or text[s - 1].isspace(), f"{c.chunk_id} starts mid-word")
            self.assertTrue(e == len(text) or text[e].isspace(), f"{c.chunk_id} ends mid-word")
        # Neighbouring windows of one document overlap by roughly the configured amount.
        doc_chunks = [c for c in self.A if c.metadata["doc_id"] == "overdraft_policy_v3"]
        overlaps = [a.metadata["char_end"] - b.metadata["char_start"] for a, b in zip(doc_chunks, doc_chunks[1:])]
        self.assertTrue(all(100 <= o <= p["overlap_chars"] + 10 for o in overlaps), overlaps)

    def test_b_never_splits_a_table_and_keeps_its_header(self):
        tables = [b.text for d in self.docs if d.decision.is_active for b in d.blocks if b.type == "table"]
        for table in tables:
            self.assertTrue(any(table in c.text for c in self.B), table[:40])
        rate = next(c for c in self.B if "24 months | 3.95% | 4.00% | 4.05%" in c.text)
        self.assertIn("Certificate term", rate.text)  # header row travels with the rows

    def test_b_chunks_start_at_section_boundaries(self):
        # Every heading is the first thing in its chunk's body (B never starts a new
        # section halfway through a chunk), except tiny sections merged forward.
        for c in self.B:
            doc = self.by_id[c.metadata["doc_id"]]
            headings = [b for b in doc.blocks if b.type == "heading"
                        and c.metadata["char_start"] < doc.text.find(b.text, c.metadata["char_start"]) < c.metadata["char_end"]]
            for h in headings:
                pos = doc.text.find(h.text, c.metadata["char_start"])
                before = doc.text[c.metadata["char_start"]:pos]
                self.assertLess(len(before), DEFAULT_PARAMS["B_structure"]["min_chars"],
                                f"{c.chunk_id}: heading {h.text!r} after {len(before)} chars of another section")

    def test_b_prefix_gives_context(self):
        c = next(c for c in self.B if "$29" in c.text and c.metadata["doc_id"] == "overdraft_policy_v3")
        self.assertTrue(c.text.startswith("Harbor Credit Union Overdraft Policy"))

    def test_metadata_schema_is_complete_and_chroma_safe(self):
        fields = {"chunk_id", "doc_id", "source_filename", "title", "chunk_index", "char_start", "char_end",
                  "page_start", "page_end", "section_path", "tenant", "sensitivity", "version", "effective_date",
                  "superseded_by", "is_current", "parser", "chunker", "chunker_params",
                  "contains_generated_text", "pii_redactions"}
        for c in self.A + self.B:
            self.assertLessEqual(fields, set(c.metadata))
            self.assertTrue(all(isinstance(v, (str, int, float, bool)) for v in c.metadata.values()), c.chunk_id)
        v2 = next(c for c in self.B if c.metadata["doc_id"] == "overdraft_policy_v2")
        self.assertEqual((v2.metadata["is_current"], v2.metadata["superseded_by"]), (False, "overdraft_policy_v3"))
        chart = [c for c in self.B if c.metadata["contains_generated_text"]]
        self.assertTrue(chart and all(c.metadata["doc_id"] == "auto_loan_comparison" for c in chart))

    def test_ids_are_deterministic(self):
        again = chunk("B_structure", self.docs)
        self.assertEqual([c.chunk_id for c in again], [c.chunk_id for c in self.B])
        self.assertEqual([c.text for c in again], [c.text for c in self.B])

    def test_every_surviving_quote_fits_inside_one_chunk(self):
        for name, chunks in (("A_fixed", self.A), ("B_structure", self.B)):
            split = []
            for q in load_golden_set().queries:
                for loc in q.expected:
                    doc = self.by_id.get(loc.doc_id)
                    if doc and doc.decision.is_active and matches(doc.text, loc):
                        if not any(c.metadata["doc_id"] == loc.doc_id and matches(c.text, loc) for c in chunks):
                            split.append(q.id)
            self.assertEqual(split, [], name)


class SmallDocumentTests(unittest.TestCase):
    def doc(self, blocks) -> Document:
        d = Document(doc_id="t", source_filename="t.md", source_sha256="", format="md", catalog={"tenant": "retail"},
                     blocks=blocks, decision=Decision(status="cleaned", reason="x"))
        d.rebuild_text()
        return d

    def test_oversized_table_split_by_rows_with_header_repeated(self):
        rows = [f"Service {i} | ${i}.00 | note {'x' * 80}" for i in range(40)]
        doc = self.doc([Block(type="heading", text="Fees", level=1),
                        Block(type="table", text="\n".join(["Service | Amount | Notes", *rows]), section_path=["Fees"])])
        pieces = [c for c in chunk("B_structure", [doc]) if "Service 1" in c.text or "Service 3" in c.text]
        self.assertGreater(len(pieces), 1)
        for c in pieces:
            self.assertIn("Service | Amount | Notes", c.text)
            self.assertLessEqual(len(c.text) - c.metadata["prefix_chars"], DEFAULT_PARAMS["B_structure"]["table_max_chars"])
        every_row = "\n".join(c.text for c in pieces)
        self.assertTrue(all(r in every_row for r in rows))

    def test_inactive_documents_are_not_chunked(self):
        doc = self.doc([Block(type="paragraph", text="word " * 50)])
        doc.decision = Decision(status="dropped", reason="near-duplicate")
        self.assertEqual(chunk("A_fixed", [doc]), [])


if __name__ == "__main__":
    unittest.main()
