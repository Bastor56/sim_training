import validator


def _r(cid, score):
    return {"chunk_id": cid, "rerank": score}


def test_keeps_chunks_at_or_above_tau_in_rank_order():
    kept, verdict = validator.validate([_r("a", 0.9), _r("b", 0.10), _r("c", 0.099)], 0.10)
    assert [k["chunk_id"] for k in kept] == ["a", "b"] and verdict == "usable"


def test_nothing_kept_is_poor():
    kept, verdict = validator.validate([_r("a", 0.02)], 0.10)
    assert kept == [] and verdict == "poor"


def test_empty_results_are_poor():
    assert validator.validate([], 0.10) == ([], "poor")


def test_near_miss_passes_layer_one():
    # Day 6: q045's auto-loan chunk scores 0.549. Layer 1 lets it through, by design;
    # the generator's coverage check (layer 2) has to catch it.
    assert validator.validate([_r("auto_loan", 0.549)], 0.10)[1] == "usable"
