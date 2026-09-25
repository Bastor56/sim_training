import copy
import json
import tempfile
import unittest
from pathlib import Path

from config import DEFAULT_PARAMS
from pipeline import STAGES, cache_key, run_ingestion


def stage_log(run_dir: Path) -> dict[str, dict]:
    return {s["stage"]: s for s in json.loads((run_dir / "config.json").read_text())["stages"]}


class StageCacheTests(unittest.TestCase):
    """Runs the real corpus (naive parser, for speed) against a private stage cache."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.cache = Path(cls._tmp.name) / "stages"
        cls.first_dir = Path(cls._tmp.name) / "run1"
        cls.index = Path(cls._tmp.name) / "index"  # never touch the real index/ folder
        cls.first_docs, _ = run_ingestion("naive", run_dir=cls.first_dir, cache_dir=cls.cache, index_dir=cls.index)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def run_again(self, name: str, **kwargs) -> Path:
        _, run_dir = run_ingestion("naive", run_dir=Path(self._tmp.name) / name, cache_dir=self.cache,
                                   index_dir=self.index, **kwargs)
        return run_dir

    def test_first_run_computes_every_stage(self):
        log = stage_log(self.first_dir)
        self.assertEqual(list(log), STAGES)
        self.assertFalse(any(s["cache_hit"] for s in log.values()))

    def test_document_count_is_the_same_after_every_stage(self):
        self.assertEqual({s["documents"] for s in stage_log(self.first_dir).values()}, {27})
        self.assertGreater(stage_log(self.first_dir)["chunk"]["chunks"], 0)

    def test_identical_rerun_hits_every_stage_and_gives_identical_output(self):
        run_dir = self.run_again("rerun")
        self.assertTrue(all(s["cache_hit"] for s in stage_log(run_dir).values()))
        for name in ("documents.jsonl", "decisions.csv", "chunks.jsonl"):
            self.assertEqual((run_dir / name).read_bytes(), (self.first_dir / name).read_bytes(), name)

    def test_changing_a_late_param_only_reruns_that_stage(self):
        params = copy.deepcopy(DEFAULT_PARAMS)
        params["scrub"]["min_score"] = 0.6
        log = stage_log(self.run_again("scrub_changed", params=params))
        self.assertEqual({s: log[s]["cache_hit"] for s in STAGES},
                         {"load": True, "clean": True, "dedupe": True, "scrub": False, "chunk": False,
                          "embed": False, "index": False})

    def test_changing_a_chunker_param_only_rechunks(self):
        params = copy.deepcopy(DEFAULT_PARAMS)
        params["B_structure"]["max_chars"] = 1000
        log = stage_log(self.run_again("chunk_changed", params=params))
        self.assertEqual({s: log[s]["cache_hit"] for s in STAGES},
                         {"load": True, "clean": True, "dedupe": True, "scrub": True, "chunk": False,
                          "embed": False, "index": False})

    def test_from_stage_forces_recompute_downstream(self):
        log = stage_log(self.run_again("from_clean", from_stage="clean"))
        self.assertEqual({s: log[s]["cache_hit"] for s in STAGES},
                         {"load": True, "clean": False, "dedupe": False, "scrub": False, "chunk": False,
                          "embed": False, "index": False})

    def test_config_records_what_is_needed_to_reproduce(self):
        config = json.loads((self.first_dir / "config.json").read_text())
        for key in ("params", "corpus_fingerprint", "corpus_files", "models", "packages"):
            self.assertIn(key, config)
        self.assertEqual(len(config["corpus_files"]), 27)


class CacheKeyTests(unittest.TestCase):
    def test_upstream_change_changes_every_later_key(self):
        clean_a = cache_key("clean", {"x": 1}, "corpus")
        clean_b = cache_key("clean", {"x": 2}, "corpus")
        self.assertNotEqual(cache_key("dedupe", {}, clean_a), cache_key("dedupe", {}, clean_b))

    def test_param_order_does_not_matter(self):
        self.assertEqual(cache_key("clean", {"a": 1, "b": 2}, "k"), cache_key("clean", {"b": 2, "a": 1}, "k"))


if __name__ == "__main__":
    unittest.main()
