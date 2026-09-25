import tempfile
import unittest
from pathlib import Path

from catalog import load_catalog, new_document
from config import CORPUS_DIR
from loaders import LoadError, decode_bytes, load_blocks


def load(name: str, parser: str = "naive"):
    return load_blocks(CORPUS_DIR / name, parser)


def text_of(blocks) -> str:
    return "\n\n".join(b.text for b in blocks)


class DecodeTests(unittest.TestCase):
    def test_utf8_bom_is_removed_and_recorded(self):
        text, info = decode_bytes("﻿# Title".encode("utf-8"))
        self.assertEqual(text, "# Title")
        self.assertEqual((info["encoding"], info["bom"]), ("utf-8", True))

    def test_cp1252_fallback(self):
        text, info = decode_bytes("members’ — ©".encode("cp1252"))
        self.assertEqual(text, "members’ — ©")
        self.assertEqual(info["encoding"], "cp1252")
        self.assertTrue(info["utf8_failed"])


class FormatTests(unittest.TestCase):
    def test_md_bom_file(self):
        blocks, info = load("Overdraft_Policy_v3_FINAL.md")
        self.assertTrue(info["bom"])
        self.assertEqual((blocks[0].type, blocks[0].text), ("heading", "Harbor Credit Union Overdraft Policy"))
        self.assertIn("list_item", {b.type for b in blocks})

    def test_txt_cp1252_privacy_notice(self):
        blocks, info = load("Privacy_Notice_Rev01-2026.txt")
        self.assertEqual(info["encoding"], "cp1252")  # the detector's cp775 guess is overridden
        self.assertIn("detector_guess", info)
        self.assertIn("—", text_of(blocks))  # em dash decoded correctly

    def test_txt_mojibake_is_left_for_cleaning(self):
        blocks, info = load("Debit Card Limits and Controls.txt")
        self.assertEqual(info["encoding"], "utf-8")
        self.assertIn("â€", text_of(blocks))  # "â€" still there; milestone 6 fixes it

    def test_html_keeps_structure_and_hints(self):
        blocks, _ = load("faq.html")
        self.assertTrue(any(b.type == "heading" and "faq-q" in b.source_hint for b in blocks))
        self.assertTrue(any("footer" in b.source_hint for b in blocks))  # boilerplate kept, but labelled
        self.assertFalse(any("script" in b.source_hint for b in blocks))

    def test_html_table_rows(self):
        blocks, _ = load("online-banking-help.html")
        tables = [b for b in blocks if b.type == "table"]
        self.assertTrue(any(b.text.startswith("How much can I deposit? |") or "\nHow much can I deposit? |" in b.text
                            for b in tables))

    def test_docx_closure_table(self):
        blocks, _ = load("Account Closure Procedure v1.4.docx")
        tables = [b for b in blocks if b.type == "table"]
        self.assertEqual(len(tables), 1)
        self.assertIn("HCU-ACL-220", tables[0].text)
        self.assertTrue(tables[0].text.startswith("Step | Action | Owner"))

    def test_docx_card_dispute_headings_and_numbering(self):
        blocks, _ = load("Card Dispute Procedure CS-PRO-031 rev5.docx")
        headings = [b.text for b in blocks if b.type == "heading"]
        for n in range(2, 7):
            self.assertTrue(any(h.startswith(f"{n}. ") for h in headings), f"section {n} heading missing")
        items = [b.text for b in blocks if b.type == "list_item"]
        self.assertTrue(items[0].startswith("1. "))
        # Section path: every block under section 2 knows it.
        intake = [b for b in blocks if b.section_path and b.section_path[-1].startswith("2. ")]
        self.assertTrue(intake)

    def test_rtf_has_no_control_words(self):
        blocks, _ = load("Savings Account Terms and Conditions.rtf")
        text = text_of(blocks)
        self.assertNotIn("\\par", text)
        self.assertNotIn("{\\rtf", text)
        self.assertTrue(any(b.type == "table" and "$10.00 each" in b.text for b in blocks))
        self.assertIn("1. Membership and Par Value", [b.text for b in blocks if b.type == "heading"])

    def test_eml_subject_and_body(self):
        blocks, _ = load("FW_ RE_ Complaint - international wire delayed and fee.eml")
        self.assertEqual(blocks[0].type, "heading")
        self.assertIn("Complaint - international wire delayed and fee", blocks[0].text)
        self.assertIn("CMP-2026-0831", text_of(blocks))
        self.assertNotIn("Return-Path", text_of(blocks))

    def test_empty_csv_has_no_blocks(self):
        blocks, info = load("branch_locations.csv")
        self.assertEqual(blocks, [])
        self.assertEqual(info["bytes"], 0)

    def test_naive_pdf_on_scan_finds_no_text(self):
        blocks, info = load("HCU_Fee_Schedule_2026.pdf")
        self.assertEqual(blocks, [])
        self.assertEqual(info["pages_without_text"], info["pages"])

    def test_corrupt_pdf_raises_load_error(self):
        with self.assertRaises(LoadError):
            load("Rate Sheet Q2 2026 - Deposits.pdf")


class WholeCorpusTests(unittest.TestCase):
    def test_every_file_loads_or_raises_load_error(self):
        # Naive PDF parsing keeps this fast; the layout parser is covered by the spike.
        failures = {}
        for path in sorted(CORPUS_DIR.iterdir()):
            try:
                load_blocks(path, "naive")
            except LoadError as exc:
                failures[path.name] = str(exc)
        self.assertEqual(list(failures), ["Rate Sheet Q2 2026 - Deposits.pdf"])


class CatalogTests(unittest.TestCase):
    def test_new_document_carries_catalog_metadata(self):
        catalog = load_catalog()
        doc = new_document(CORPUS_DIR / "Overdraft_Policy_v2.md", catalog, parser="layout")
        self.assertEqual(doc.doc_id, "overdraft_policy_v2")
        self.assertEqual(doc.catalog["superseded_by"], "overdraft_policy_v3")
        self.assertEqual(doc.format, "md")
        self.assertEqual(doc.decision.status, "pending")
        self.assertEqual(len(doc.source_sha256), 64)

    def test_uncatalogued_file_gets_placeholder_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            stray = Path(tmp) / "mystery.txt"
            stray.write_text("hello")
            doc = new_document(stray, load_catalog(), parser="layout")
        self.assertEqual(doc.doc_id, "uncatalogued::mystery.txt")
        self.assertEqual(doc.catalog, {})


if __name__ == "__main__":
    unittest.main()
