import tempfile
import unittest
from collections import Counter
from pathlib import Path

from dedupe import canonical_sort_key, drop_exact_duplicates, drop_near_duplicates, jaccard, shingles
from config import DEFAULT_PARAMS
from models import Decision, Document
from pipeline import run_ingestion


def doc(doc_id, filename, fmt, text="", sha="", version="", status="cleaned"):
    return Document(doc_id=doc_id, source_filename=filename, source_sha256=sha, format=fmt,
                    catalog={"version": version, "effective_date": ""}, text=text,
                    decision=Decision(status=status))


POLICY = " ".join(f"Clause {i}: wires are sent the same business day if received before the cutoff." for i in range(40))


class CanonicalChoiceTests(unittest.TestCase):
    def test_copy_marker_loses_even_though_it_sorts_first(self):
        a, b = doc("member_faq_copy", "faq (1).html", "html"), doc("member_faq", "faq.html", "html")
        self.assertLess("faq (1).html", "faq.html")  # why plain filename order is wrong
        self.assertEqual(min([a, b], key=canonical_sort_key).doc_id, "member_faq")

    def test_published_pdf_beats_editable_docx(self):
        pdf = doc("wire_transfer_policy", "Wire_Transfer_Policy_Rev2026-02.pdf", "pdf")
        docx = doc("wire_transfer_policy_copy", "PAY-WT-004 Wire Transfer Policy.docx", "docx")
        self.assertEqual(min([docx, pdf], key=canonical_sort_key).doc_id, "wire_transfer_policy")


class DuplicateRuleTests(unittest.TestCase):
    def test_exact_duplicate_names_canonical(self):
        docs = [doc("member_faq_copy", "faq (1).html", "html", sha="abc", status="pending"),
                doc("member_faq", "faq.html", "html", sha="abc", status="pending")]
        drop_exact_duplicates(docs)
        self.assertEqual(docs[0].decision.status, "dropped")
        self.assertIn("exact duplicate of member_faq (faq.html)", docs[0].decision.reason)
        self.assertTrue(docs[1].decision.is_active)

    def test_near_duplicate_with_formatting_noise(self):
        pdf = doc("wire", "Wire.pdf", "pdf", text=POLICY, version="Rev 2026-02")
        docx = doc("wire_copy", "Wire.docx", "docx", text=POLICY.replace(". ", ".  "), version="Rev 2026-02")
        drop_near_duplicates([docx, pdf], DEFAULT_PARAMS["dedupe"])
        self.assertEqual(docx.decision.status, "dropped")
        self.assertIn("near-duplicate (Jaccard=1.00) of wire", docx.decision.reason)

    def test_different_versions_are_never_duplicates(self):
        v2 = doc("overdraft_policy_v2", "v2.md", "md", text=POLICY, version="2.0")
        v3 = doc("overdraft_policy_v3", "v3.md", "md", text=POLICY, version="3.0")
        drop_near_duplicates([v2, v3], DEFAULT_PARAMS["dedupe"])
        self.assertTrue(v2.decision.is_active and v3.decision.is_active)

    def test_jaccard_bounds(self):
        s = shingles(POLICY, 5)
        self.assertEqual(jaccard(s, s), 1.0)
        self.assertLess(jaccard(s, shingles("an entirely different set of words about savings rates", 5)), 0.05)


class PipelineDecisionTests(unittest.TestCase):
    """End to end over the real corpus: every file gets exactly one decision."""

    def test_layout_run_decisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            docs, run_dir = run_ingestion("layout", stop_after="dedupe", run_dir=Path(tmp))
            self.assertTrue((run_dir / "decisions.csv").exists())
        self.assertEqual(len(docs), 27)
        self.assertEqual(Counter(d.decision.status for d in docs), {"cleaned": 22, "dropped": 4, "quarantined": 1})
        self.assertTrue(all(d.decision.reason for d in docs))


if __name__ == "__main__":
    unittest.main()
