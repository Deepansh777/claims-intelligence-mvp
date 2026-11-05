import pytest

from app.llm.usage import breakdown, cost, match_price

PRICE = {
    "id": 1,
    "model": "gpt-6.1-sol",
    "input_per_1m": 2.0,
    "cached_input_per_1m": 0.10,
    "cache_write_per_1m": 2.50,
    "output_per_1m": 10.0,
}


def test_breakdown_and_cost():
    tokens = breakdown(
        {
            "input_tokens": 12000,
            "output_tokens": 900,
            "total_tokens": 12900,
            "input_token_details": {"cache_read": 4000, "cache_creation": 7000},
            "output_token_details": {"reasoning": 600},
        }
    )
    assert tokens == {
        "input_tokens": 12000,
        "cached_input_tokens": 4000,
        "cache_write_tokens": 7000,
        "output_tokens": 900,
        "reasoning_tokens": 600,
        "total_tokens": 12900,
    }
    # 1,000 uncached x $2 + 4,000 cached x $0.10 + 7,000 written x $2.50; 900 out x $10 (per 1M).
    assert cost(tokens, PRICE) == pytest.approx((0.0199, 0.009))
    assert breakdown(None) is None


def test_match_price_prefers_exact_then_longest_prefix():
    prices = [PRICE, {**PRICE, "id": 2, "model": "gpt-6"}]
    assert match_price("gpt-6.1-sol", prices)["id"] == 1
    assert match_price("gpt-6.1-sol-2026-10-01", prices)["id"] == 1
    assert match_price("gpt-6.2", prices)["id"] == 2
    assert match_price("gpt-4o-mini", prices) is None
