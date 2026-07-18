"""The analyst-target upside signal must be trusted in proportion to coverage
depth, haircut for sell-side optimism, and dampened when even the low target is
below price — not trusted identically for a 2-analyst vs a 40-analyst name."""
from __future__ import annotations

from src.alpha_scout.screener import (
    _analyst_coverage_factor,
    _blended_pe,
    score_valuation,
)


def test_coverage_factor_scales_with_analyst_count():
    assert _analyst_coverage_factor({"num_analyst_opinions": 2}) < _analyst_coverage_factor(
        {"num_analyst_opinions": 20}
    )
    assert _analyst_coverage_factor({"num_analyst_opinions": 40}) == 1.0
    assert _analyst_coverage_factor({}) == 0.5  # unknown -> half trust


def test_same_upside_more_coverage_scores_higher():
    thin = score_valuation({"implied_upside_pct": 40, "num_analyst_opinions": 2})
    deep = score_valuation({"implied_upside_pct": 40, "num_analyst_opinions": 40})
    assert deep > thin


def test_target_low_below_price_dampens_upside():
    base = score_valuation({"implied_upside_pct": 40, "num_analyst_opinions": 20})
    flagged = score_valuation(
        {"implied_upside_pct": 40, "num_analyst_opinions": 20, "target_low_below_price": True}
    )
    assert flagged < base


def test_blended_pe_prefers_forward_when_both_present():
    # trailing 30 (peak-cycle inflated), forward 12 -> blend leans toward forward
    pe = _blended_pe({"pe_trailing": 30, "pe_forward": 12})
    assert 12 < pe < 30 and pe < 21  # 0.4*30 + 0.6*12 = 19.2


def test_blended_pe_falls_back_to_single_value():
    assert _blended_pe({"pe_forward": 14}) == 14
    assert _blended_pe({"pe_trailing": 22}) == 22
    assert _blended_pe({}) is None


def test_peak_cycle_name_less_cheap_under_blended_pe():
    # Low trailing P/E but high forward P/E (earnings expected to fall) should
    # NOT get the full 'inexpensive' credit a genuinely cheap name gets.
    peak = score_valuation({"pe_trailing": 10, "pe_forward": 30})
    cheap = score_valuation({"pe_trailing": 10, "pe_forward": 11})
    assert cheap > peak
