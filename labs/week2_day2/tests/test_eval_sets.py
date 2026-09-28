from collections import Counter

import eval_sets


def test_sizes_and_unique_ids():
    quality = eval_sets.load(["golden", "no_retrieval"])
    probes = eval_sets.load(["repeat"])
    assert len(quality) == 55 and len(probes) == 18
    ids = [i.id for i in quality + probes]
    assert len(ids) == len(set(ids))


def test_expected_outcomes_match_the_spec():
    counts = Counter(i.expected_outcome for i in eval_sets.load(["golden", "no_retrieval"]))
    assert counts == {"answered": 41, "not_in_corpus": 4, "answered_direct": 10}
    nic = sorted(i.id for i in eval_sets.load(["golden"]) if i.expected_outcome == "not_in_corpus")
    assert nic == ["q003", "q043", "q044", "q045"]


def test_expected_gate():
    assert {i.expected_gate for i in eval_sets.load(["golden"])} == {"retrieve"}
    assert {i.expected_gate for i in eval_sets.load(["no_retrieval"])} == {"answer_direct"}


def test_probes_point_at_real_golden_rows_and_expectations_fit_variants():
    for p in eval_sets.load(["repeat"]):
        assert p.golden is not None and p.golden.id == p.extra["source_id"]
        assert p.expect_cache == ("hit" if p.category == "surface" else "miss")
    variants = Counter(p.category for p in eval_sets.load(["repeat"]))
    assert variants == {"surface": 8, "paraphrase": 5, "tenant_swap": 3, "corpus_change": 2}


def test_tenant_swaps_really_swap_tenant():
    for p in eval_sets.load(["repeat"]):
        if p.category == "tenant_swap":
            assert p.tenant != p.golden.tenant


def test_corpus_version_names_the_day6_index():
    assert eval_sets.corpus_version() == "1|harbor__layout__B_structure__5c38ec7c"
