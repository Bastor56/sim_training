import unittest
from collections import Counter

from config import GROUND_TRUTH_DIR
from golden import Location, load_golden_set, matches, normalise, relevant_items


class NormaliseTests(unittest.TestCase):
    def test_curly_quotes_dashes_and_whitespace(self):
        self.assertEqual(normalise("It’s  a — test"), "it's a - test")

    def test_en_dash_ranges_match_ocr_hyphens(self):
        # OCR reads "37–60" as "37-60" (setup smoke test); both must normalise alike.
        self.assertEqual(normalise("New 37–60 mo"), normalise("new 37-60 MO"))

    def test_nfkc_and_newlines(self):
        self.assertEqual(normalise("Fee schedule\r\n\tpage 1"), "fee schedule page 1")


class MatchTests(unittest.TestCase):
    def test_substring(self):
        loc = Location("overdraft_policy_v3", "a fee of $29 per item", "substring")
        self.assertTrue(matches("Harbor charges A FEE of $29  per item, up to...", loc))
        self.assertFalse(matches("a fee of $32 per item", loc))

    def test_all_tokens_matches_table_row(self):
        loc = Location("deposit_rate_sheet_2026q3", "24 months 4.05%", "all_tokens")
        self.assertTrue(matches("24 months | 3.95% | 4.00% | 4.05%", loc))
        self.assertFalse(matches("24 months | 3.95%", loc))

    def test_unknown_rule_raises(self):
        with self.assertRaises(ValueError):
            matches("text", Location("d", "q", "regex"))


class GoldenSetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.golden = load_golden_set()

    def test_loads_45_queries_in_the_readme_mix(self):
        self.assertEqual(len(self.golden.queries), 45)
        counts = Counter(q.type for q in self.golden.queries)
        self.assertEqual(
            counts,
            {
                "exact_term": 6, "paraphrase": 9, "scanned_table": 8, "figure": 2,
                "reading_order": 2, "version_trap": 4, "multi_chunk": 4,
                "duplicate_source": 2, "tenant_filter": 2, "encoding": 2,
                "pii_adjacent": 1, "unanswerable": 3,
            },
        )

    def test_special_queries_carry_their_tenant_and_access(self):
        self.assertEqual(self.golden.by_id("q002").tenant, "business")
        self.assertEqual(self.golden.by_id("q003").access, "restricted")

    def test_relevant_item_grouping(self):
        n_items = {qid: len(relevant_items(self.golden.by_id(qid))) for qid in ("q009", "q036", "q032", "q043")}
        # q009: same quote in the wire PDF and its near-duplicate -> 1 item.
        # q036: byte-identical FAQ copies -> 1 item. q032: 4 passages -> 4.
        # q043: unanswerable -> 0.
        self.assertEqual(n_items, {"q009": 1, "q036": 1, "q032": 4, "q043": 0})
        self.assertEqual(len(relevant_items(self.golden.by_id("q009"))[0].locations), 2)

    def test_item_requires_the_expected_doc_id(self):
        (item,) = relevant_items(self.golden.by_id("q036"))
        quote = item.locations[0].quote
        self.assertTrue(item.satisfied_by("member_faq", f"... {quote} ..."))
        self.assertTrue(item.satisfied_by("member_faq_copy", quote))
        self.assertFalse(item.satisfied_by("online_banking_help", quote))

    def test_every_quote_matches_its_own_ground_truth(self):
        # Free sanity check: our matcher must agree with verify_dataset.py.
        checked, failures = 0, []
        for q in self.golden.queries:
            for loc in q.expected:
                text = (GROUND_TRUTH_DIR / f"{loc.doc_id}.txt").read_text(encoding="utf-8")
                checked += 1
                if not matches(text, loc):
                    failures.append((q.id, loc.doc_id, loc.quote))
        self.assertEqual(failures, [])
        self.assertEqual(checked, 54)


if __name__ == "__main__":
    unittest.main()
