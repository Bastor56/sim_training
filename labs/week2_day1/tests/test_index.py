import csv
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from config import ANSWER_KEY_DIR
from embedding import embed_query
from index import (BM25Index, ChromaIndex, IndexRevisionMismatch, collection_name, matches_where,
                   to_chroma_where, tokenize)
from models import Chunk

MEMBER_FACING = {"tenant": "retail", "sensitivity_not_in": ["restricted"], "is_current": True}
COMBOS = [(p, c) for p in ("naive", "layout") for c in ("A_fixed", "B_structure")]
QUERIES = ["What is the overdraft fee per item?", "How much does a domestic wire cost?",
           "What triggers velocity rule VR-3?", "What is the daily ATM withdrawal limit?",
           "Earnings Credit Rate for Business Analysis Checking"]


class TokenizerTests(unittest.TestCase):
    def test_keeps_rates_amounts_and_form_numbers_whole(self):
        tokens = tokenize("Rate 4.05% APY; fee $30.00. Form HCU-DSP-114, caps 5/1/5 and $1,000.")
        for t in ("4.05%", "$30.00", "hcu-dsp-114", "5/1/5", "$1,000"):
            self.assertIn(t, tokens)
        self.assertIn("fee", tokens)  # trailing punctuation stripped from ordinary words

    def test_uses_golden_set_normalisation(self):
        # Curly apostrophe/dash normalised; a possessive splits, so "member" still matches.
        self.assertEqual(tokenize("Member’s 37–60 MO"), ["member", "s", "37-60", "mo"])


class FilterTranslationTests(unittest.TestCase):
    def test_python_filter(self):
        ok = {"tenant": "retail", "sensitivity": "internal", "is_current": True}
        self.assertTrue(matches_where(ok, MEMBER_FACING))
        self.assertFalse(matches_where({**ok, "sensitivity": "restricted"}, MEMBER_FACING))
        self.assertFalse(matches_where({**ok, "tenant": "business"}, MEMBER_FACING))
        self.assertFalse(matches_where({**ok, "is_current": False}, MEMBER_FACING))

    def test_chroma_translation(self):
        self.assertEqual(to_chroma_where(MEMBER_FACING), {"$and": [
            {"tenant": {"$eq": "retail"}}, {"sensitivity": {"$nin": ["restricted"]}}, {"is_current": {"$eq": True}}]})
        self.assertEqual(to_chroma_where({"tenant": "business"}), {"tenant": {"$eq": "business"}})
        self.assertIsNone(to_chroma_where({}))


class BuiltIndexTests(unittest.TestCase):
    """Checks the four indexes built by `src/ingest.py --parser all --chunker all`."""

    @classmethod
    def setUpClass(cls):
        cls.vector = {combo: ChromaIndex(collection_name(*combo)).open() for combo in COMBOS}
        cls.bm25 = {combo: BM25Index(collection_name(*combo)).open() for combo in COMBOS}
        cls.query_vectors = {q: embed_query(q) for q in QUERIES}

    def test_both_indexes_hold_the_same_chunks(self):
        for combo in COMBOS:
            self.assertEqual(self.vector[combo].count(), len(self.bm25[combo].chunk_ids), combo)
            self.assertGreater(self.vector[combo].count(), 100, combo)

    def test_stored_metadata_is_complete_typed_and_never_none(self):
        for combo in COMBOS:
            metas = self.vector[combo].collection.get(include=["metadatas"])["metadatas"]
            for m in metas:
                self.assertTrue({"doc_id", "char_start", "tenant", "sensitivity", "is_current",
                                 "embedding_revision"} <= set(m))
                self.assertTrue(all(v is not None and isinstance(v, (str, int, float, bool)) for v in m.values()))

    def test_member_facing_filter_holds_in_both_indexes(self):
        for combo in COMBOS:
            for q in QUERIES:
                vector_ids = [cid for cid, _ in self.vector[combo].query(self.query_vectors[q], 50, MEMBER_FACING)]
                bm25_ids = [cid for cid, _ in self.bm25[combo].query(q, 50, MEMBER_FACING)]
                for cid in vector_ids + bm25_ids:
                    self.assertFalse(cid.startswith(("business_fee_guide", "fraud_monitoring_thresholds",
                                                     "overdraft_policy_v2")), f"{combo} {q!r} leaked {cid}")

    def test_bm25_filters_before_truncating(self):
        bm25 = self.bm25[("layout", "B_structure")]
        # "velocity rule VR-3" only occurs in the restricted doc; "card transactions" occurs widely.
        query = "velocity rule VR-3 card transactions"
        unfiltered = bm25.query(query, 5)
        self.assertTrue(unfiltered[0][0].startswith("fraud_monitoring_thresholds"))  # the restricted doc ranks first
        filtered = bm25.query(query, 5, MEMBER_FACING)
        self.assertEqual(len(filtered), 5)  # still n results, just none of them restricted
        self.assertFalse(any(cid.startswith("fraud_monitoring_thresholds") for cid, _ in filtered))

    def test_results_are_ranked_deterministically(self):
        combo = ("layout", "B_structure")
        v = self.query_vectors[QUERIES[0]]
        self.assertEqual(self.vector[combo].query(v, 20, MEMBER_FACING), self.vector[combo].query(v, 20, MEMBER_FACING))
        scores = [s for _, s in self.bm25[combo].query(QUERIES[0], 20)]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_no_planted_pii_value_is_stored_anywhere(self):
        with open(ANSWER_KEY_DIR / "pii_inventory.csv", encoding="utf-8", newline="") as f:
            values = [r["value"] for r in csv.DictReader(f)]
        for combo in COMBOS:
            texts = self.vector[combo].all_texts()
            leaks = [v for v in values for t in texts if v in t]
            self.assertEqual(leaks, [], combo)


class RevisionGuardTests(unittest.TestCase):
    def test_opening_an_index_built_with_another_revision_fails_loudly(self):
        with tempfile.TemporaryDirectory() as tmp:
            index = ChromaIndex("harbor__test__x__00000000", path=Path(tmp))
            index.create(cache_key="k")
            index.add([Chunk("c1", "text", {"doc_id": "d"}, embedding=[1.0, 0.0])])
            real = index.open()  # same revision: fine
            self.assertEqual(real.count(), 1)
            other = {"model": "BAAI/bge-small-en-v1.5", "revision": "ffffffffffff"}
            with mock.patch("index.model_spec", return_value=other):
                with self.assertRaises(IndexRevisionMismatch):
                    ChromaIndex("harbor__test__x__00000000", path=Path(tmp)).open()


if __name__ == "__main__":
    unittest.main()
