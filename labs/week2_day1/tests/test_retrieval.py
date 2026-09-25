import unittest

from golden import load_golden_set, relevant_items
from retrieval import MODES, Retriever, access_filter, rrf

GOLDEN = load_golden_set()


class RrfTests(unittest.TestCase):
    def test_spec_worked_example(self):
        # BM25 ranks c7=1, c9=2, c2=3; vector ranks c2=1, x=2, y=3, c7=4 (spec "Retrieval").
        fused = dict(rrf([["c7", "c9", "c2"], ["c2", "x", "y", "c7"]], k=60))
        self.assertEqual(round(fused["c2"], 5), 0.03227)  # 0.015873 + 0.016393 = 0.032266
        self.assertEqual(round(fused["c7"], 5), 0.03202)
        self.assertEqual(round(fused["c9"], 5), 0.01613)
        order = [cid for cid, _ in rrf([["c7", "c9", "c2"], ["c2", "x", "y", "c7"]], k=60)]
        self.assertEqual(order[:3], ["c2", "c7", "c9"])  # ranked well by both beats first in one

    def test_ties_break_on_chunk_id(self):
        self.assertEqual([c for c, _ in rrf([["b"], ["a"]])], ["a", "b"])


class AccessFilterTests(unittest.TestCase):
    def test_default_is_member_facing(self):
        self.assertEqual(access_filter("retail"),
                         {"tenant": "retail", "sensitivity_not_in": ["restricted"], "is_current": True})

    def test_switches(self):
        self.assertNotIn("sensitivity_not_in", access_filter("retail", allow_restricted=True))
        self.assertNotIn("is_current", access_filter("retail", current_only=False))


class RetrieverTests(unittest.TestCase):
    """Against the real layout / B_structure indexes."""

    @classmethod
    def setUpClass(cls):
        cls.retriever = Retriever("layout", "B_structure")

    def hit(self, query_id: str, mode: str, **kwargs) -> int | None:
        """Rank of the first result satisfying the query's first relevant item, or None."""
        q = GOLDEN.by_id(query_id)
        item = relevant_items(q)[0]
        response = self.retriever.search(q.query, mode, tenant=q.tenant, **kwargs)
        return next((r.rank for r in response.results if item.satisfied_by(r.metadata["doc_id"], r.text)), None)

    def test_identical_query_gives_identical_results(self):
        q = GOLDEN.by_id("q009").query
        a = self.retriever.search(q, "hybrid_rerank")
        b = self.retriever.search(q, "hybrid_rerank")
        self.assertEqual([(r.chunk_id, r.score) for r in a.results], [(r.chunk_id, r.score) for r in b.results])

    def test_rerank_only_reorders_the_fused_candidates(self):
        q = GOLDEN.by_id("q009").query
        fused = self.retriever.search(q, "hybrid", top_k=30)
        reranked = self.retriever.search(q, "hybrid_rerank", top_k=30)
        self.assertEqual({r.chunk_id for r in reranked.results}, {r.chunk_id for r in fused.results})
        self.assertTrue(all("rrf" in r.stage_scores and "rerank" in r.stage_scores for r in reranked.results))

    def test_every_mode_returns_cited_results(self):
        for mode in MODES:
            response = self.retriever.search("What is the fee for a stop payment?", mode)
            self.assertEqual(len(response.results), 10, mode)
            self.assertEqual([r.rank for r in response.results], list(range(1, 11)))
            self.assertIn("total", response.timings_ms)
            self.assertTrue(response.results[0].citation())

    def test_exact_term_bm25_finds_form_number(self):
        self.assertEqual(self.hit("q001", "bm25"), 1)

    def test_paraphrase_vector_beats_bm25(self):
        vector_rank = self.hit("q009", "vector")
        self.assertEqual(vector_rank, 1)
        self.assertIsNone(self.hit("q009", "bm25"))  # not in BM25's top 10: no shared keywords

    def test_version_trap_filter_keeps_v2_out(self):
        q = GOLDEN.by_id("q028").query
        filtered = self.retriever.search(q, "hybrid_rerank")
        self.assertFalse(any(r.metadata["doc_id"] == "overdraft_policy_v2" for r in filtered.results))
        self.assertEqual(filtered.results[0].metadata["doc_id"], "overdraft_policy_v3")
        unfiltered = self.retriever.search(q, "hybrid_rerank", current_only=False)
        # Without the filter the superseded v2 clause outranks v3: relevance alone can't tell versions apart.
        self.assertEqual(unfiltered.results[0].metadata["doc_id"], "overdraft_policy_v2")

    def test_restricted_doc_only_with_clearance(self):
        q = GOLDEN.by_id("q003").query
        member = self.retriever.search(q, "hybrid_rerank")
        self.assertFalse(any(r.metadata["sensitivity"] == "restricted" for r in member.results))
        cleared = self.retriever.search(q, "hybrid_rerank", allow_restricted=True)
        self.assertEqual(cleared.results[0].metadata["doc_id"], "fraud_monitoring_thresholds")


if __name__ == "__main__":
    unittest.main()
