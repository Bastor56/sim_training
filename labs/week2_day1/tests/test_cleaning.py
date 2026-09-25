import unittest

from catalog import load_catalog, new_document
from cleaning import clean_document
from config import CORPUS_DIR, DEFAULT_PARAMS
from golden import load_golden_set, matches
from loaders import load_blocks
from models import Block, Decision, Document

PARAMS = DEFAULT_PARAMS["clean"]
CATALOG = load_catalog()


def cleaned(name: str, parser: str = "naive") -> Document:
    doc = new_document(CORPUS_DIR / name, CATALOG, parser)
    doc.blocks, info = load_blocks(CORPUS_DIR / name, parser)
    doc.decision.details["load"] = info
    return clean_document(doc, PARAMS)


def golden_quotes(doc_id: str):
    return [loc for q in load_golden_set().queries for loc in q.expected if loc.doc_id == doc_id]


class DefectFixTests(unittest.TestCase):
    def test_privacy_notice_decoded_as_cp1252(self):
        doc = cleaned("Privacy_Notice_Rev01-2026.txt")
        self.assertIn("members’", doc.text)
        self.assertIn("decoded as cp1252", doc.decision.reason)

    def test_debit_card_mojibake_repaired(self):
        doc = cleaned("Debit Card Limits and Controls.txt")
        for bad in ("â€", "Ã©", "Â®"):  # â€  Ã©  Â®
            self.assertNotIn(bad, doc.text)
        self.assertIn("card’s", doc.text)  # curly apostrophe kept, not straightened
        self.assertIn("mojibake", doc.decision.reason)

    def test_wire_pdf_running_header_removed(self):
        before, _ = load_blocks(CORPUS_DIR / "Wire_Transfer_Policy_Rev2026-02.pdf", "naive")
        self.assertEqual(sum(b.text.count("Internal Use") for b in before), 3)  # once per page
        doc = cleaned("Wire_Transfer_Policy_Rev2026-02.pdf")
        self.assertEqual(doc.text.count("Internal Use"), 0)
        self.assertEqual(doc.text.count("Page "), 0)
        self.assertIn("running header/footer", doc.decision.reason)

    def test_closure_tracked_changes_removed(self):
        doc = cleaned("Account Closure Procedure v1.4.docx")
        self.assertNotIn("[DELETED:", doc.text)
        self.assertIn("HCU-ACL-220", doc.text)

    def test_html_boilerplate_removed_content_kept(self):
        doc = cleaned("faq.html")
        self.assertNotIn("We use cookies", doc.text)
        self.assertNotIn("All rights reserved", doc.text)
        for loc in golden_quotes("member_faq"):
            self.assertTrue(matches(doc.text, loc), loc.quote)

    def test_email_unquoted_not_dropped(self):
        doc = cleaned("FW_ RE_ Complaint - international wire delayed and fee.eml")
        self.assertIn("I am writing to formally complain", doc.text)  # only existed as a quoted reply
        self.assertNotIn("\n>", "\n" + doc.text)
        self.assertNotIn("CONFIDENTIALITY NOTICE", doc.text)
        self.assertNotIn("From:", doc.text)
        self.assertEqual(doc.text.count("Member Service Supervisor, Port Alden Branch"), 1)  # signature once
        for loc in golden_quotes("complaint_email_export"):
            self.assertTrue(matches(doc.text, loc), loc.quote)

    def test_loan_policy_whitespace(self):
        doc = cleaned("Loan_Late_Payment_and_Collections_Policy_v1.6.md")
        for ch in (" ", "\t", "\r"):
            self.assertNotIn(ch, doc.text)


class NearEmptyTests(unittest.TestCase):
    def test_holiday_placeholder_dropped(self):
        doc = cleaned("Holiday_Schedule_2026.txt")
        self.assertEqual(doc.decision.status, "dropped")
        self.assertIn("content to follow", doc.decision.reason)

    def test_long_document_mentioning_tbd_is_kept(self):
        doc = Document(doc_id="x", source_filename="x.md", source_sha256="", format="md", catalog={},
                       blocks=[Block(type="paragraph", text="word " * 300 + "Owner: TBD.")], decision=Decision())
        self.assertEqual(clean_document(doc, PARAMS).decision.status, "cleaned")

    def test_cleaned_reason_is_never_empty(self):
        doc = cleaned("CC_Script_Lost_Stolen_Card_v2.2.md")
        self.assertEqual(doc.decision.status, "cleaned")
        self.assertTrue(doc.decision.reason)


if __name__ == "__main__":
    unittest.main()
