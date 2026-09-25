import unittest

from golden import load_golden_set, relevant_items
from metrics import aggregate, leak_counts, precision_at_k, precision_ceiling, recall_at_k, score_query

GOLDEN = load_golden_set()
NOISE = ("wire_transfer_policy", "Domestic wires sent through online banking cost less than branch wires.")


def hit(query_id: str, item_index: int, doc_id: str | None = None) -> tuple[str, str]:
    """A made-up retrieved chunk that contains item N's quote, padded with filler text."""
    loc = relevant_items(GOLDEN.by_id(query_id))[item_index].locations[0]
    return (doc_id or loc.doc_id, f"Some text before. {loc.quote}. Some text after.")


class WorkedExampleTests(unittest.TestCase):
    """spec.md "Metric definitions": q032 has 4 items (I1..I4 -> indexes 0..3)."""

    def setUp(self):
        self.items = relevant_items(GOLDEN.by_id("q032"))
        # Ranks 1-5: I1, nothing, I2, I1 again (overlap), I4.  I3 turns up at rank 8.
        self.results = [hit("q032", 0), NOISE, hit("q032", 1), hit("q032", 0), hit("q032", 3),
                        NOISE, NOISE, hit("q032", 2), NOISE, NOISE]

    def test_recall_at_5_is_three_of_four(self):
        self.assertEqual(recall_at_k(self.results, self.items, 5), 0.75)

    def test_precision_at_5_credits_each_item_once(self):
        # Rank 4 repeats I1, so it doesn't count: 3 useful chunks out of 5.
        self.assertEqual(precision_at_k(self.results, self.items, 5), 0.60)

    def test_recall_at_10_finds_i3_at_rank_8(self):
        self.assertEqual(recall_at_k(self.results, self.items, 10), 1.0)
        self.assertEqual(precision_at_k(self.results, self.items, 10), 0.40)


class EdgeCaseTests(unittest.TestCase):
    def test_single_item_hit_at_rank_3(self):
        items = relevant_items(GOLDEN.by_id("q001"))
        results = [NOISE, NOISE, hit("q001", 0), NOISE, NOISE]
        self.assertEqual(recall_at_k(results, items, 5), 1.0)
        self.assertEqual(precision_at_k(results, items, 5), 0.2)  # the best possible for 1 item
        self.assertEqual(precision_ceiling(len(items), 5), 0.2)

    def test_hit_below_k_does_not_count(self):
        items = relevant_items(GOLDEN.by_id("q001"))
        results = [NOISE] * 5 + [hit("q001", 0)]
        self.assertEqual(recall_at_k(results, items, 5), 0.0)
        self.assertEqual(recall_at_k(results, items, 10), 1.0)

    def test_duplicate_source_either_copy_counts(self):
        items = relevant_items(GOLDEN.by_id("q036"))
        self.assertEqual(len(items), 1)
        self.assertEqual(recall_at_k([hit("q036", 0, doc_id="member_faq")], items, 5), 1.0)
        self.assertEqual(recall_at_k([hit("q036", 0, doc_id="member_faq_copy")], items, 5), 1.0)

    def test_right_quote_wrong_doc_is_not_a_hit(self):
        items = relevant_items(GOLDEN.by_id("q001"))
        self.assertEqual(recall_at_k([hit("q001", 0, doc_id="member_faq")], items, 5), 0.0)

    def test_fewer_results_than_k_still_divides_by_k(self):
        items = relevant_items(GOLDEN.by_id("q001"))
        self.assertEqual(precision_at_k([hit("q001", 0)], items, 5), 0.2)

    def test_unanswerable_query_cannot_be_scored(self):
        with self.assertRaises(ValueError):
            score_query(GOLDEN.by_id("q043"), [NOISE], k_values=[5])
        with self.assertRaises(ValueError):
            recall_at_k([NOISE], [], 5)


class AggregateTests(unittest.TestCase):
    def test_macro_average_and_per_type_breakdown(self):
        s1 = score_query(GOLDEN.by_id("q001"), [hit("q001", 0)], k_values=[5])  # exact_term, R=1
        s2 = score_query(GOLDEN.by_id("q009"), [NOISE], k_values=[5])  # paraphrase, R=0
        result = aggregate([s1, s2])
        self.assertEqual(result["n_queries"], 2)
        self.assertEqual(result["recall@5"], 0.5)
        self.assertEqual(result["by_type"]["exact_term"]["recall@5"], 1.0)
        self.assertEqual(result["by_type"]["paraphrase"]["recall@5"], 0.0)

    def test_empty_aggregate_is_an_error(self):
        with self.assertRaises(ValueError):
            aggregate([])


class LeakCountTests(unittest.TestCase):
    def test_counts_restricted_wrong_tenant_and_superseded(self):
        top = [
            {"doc_id": "fee_schedule_2026", "tenant": "retail", "sensitivity": "public", "is_current": True},
            {"doc_id": "fraud_monitoring_thresholds", "tenant": "retail", "sensitivity": "restricted", "is_current": True},
            {"doc_id": "business_fee_guide", "tenant": "business", "sensitivity": "public", "is_current": True},
            {"doc_id": "overdraft_policy_v2", "tenant": "retail", "sensitivity": "public", "is_current": False},
        ]
        self.assertEqual(leak_counts(top, tenant="retail"), {"restricted": 1, "wrong_tenant": 1, "superseded": 1})
        self.assertEqual(leak_counts(top[:1], tenant="retail"), {"restricted": 0, "wrong_tenant": 0, "superseded": 0})


if __name__ == "__main__":
    unittest.main()
