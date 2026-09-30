import pytest

import pricing


def test_input_rate_per_million():
    assert pricing.cost("claude-haiku-4-5", {"input_tokens": 1_000_000}) == pytest.approx(1.00)
    assert pricing.cost("claude-opus-5", {"output_tokens": 1_000_000}) == pytest.approx(25.00)


def test_cache_tokens_priced_at_their_own_rates():
    # Sonnet 5: write $2.50, read $0.20 per MTok (not the $2.00 input rate).
    assert pricing.cost("claude-sonnet-5", {"cache_creation_input_tokens": 1_000_000}) == pytest.approx(2.50)
    assert pricing.cost("claude-sonnet-5", {"cache_read_input_tokens": 1_000_000}) == pytest.approx(0.20)


def test_worked_example_mixed_usage():
    # 2,500 in + 300 out on Haiku = 0.0025 + 0.0015
    usage = {"input_tokens": 2500, "output_tokens": 300}
    assert pricing.cost("claude-haiku-4-5", usage) == pytest.approx(0.004)


def test_unknown_model_raises_never_zero():
    with pytest.raises(pricing.UnknownModelPrice):
        pricing.cost("claude-imaginary-9", {"input_tokens": 10})


def test_every_role_model_is_priced():
    import settings

    models = {settings.GATE["model"]} | {g["model"] for g in settings.GENERATORS.values()}
    for m in models:
        assert set(pricing.rates(m)) >= {"input", "output", "cache_write_5m", "cache_read"}
