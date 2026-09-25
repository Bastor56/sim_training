import csv
import os
import unittest

from config import CORPUS_DIR, SOURCE_CATALOG_PATH


class SourceCatalogTests(unittest.TestCase):
    def test_catalog_filenames_exactly_match_corpus(self):
        with open(SOURCE_CATALOG_PATH, encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 27)
        self.assertEqual(sorted(r["filename"] for r in rows), sorted(os.listdir(CORPUS_DIR)))

    def test_doc_ids_are_unique(self):
        with open(SOURCE_CATALOG_PATH, encoding="utf-8", newline="") as f:
            doc_ids = [r["doc_id"] for r in csv.DictReader(f)]
        self.assertEqual(len(doc_ids), len(set(doc_ids)))
