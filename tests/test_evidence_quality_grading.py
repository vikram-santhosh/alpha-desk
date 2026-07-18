"""evidence_quality must differentiate tracked names by coverage/corroboration
instead of pinning every one to a flat 100 (17% of the composite was inert)."""
from __future__ import annotations

from src.alpha_scout.screener import score_evidence_quality

FULL_TECH = {"rsi": {"rsi": 50}}


def _tracked(analysts=None, corroboration=1, channels=None):
    c = {"source": "existing_portfolio/core", "signal_data": {"x": 1}, "signal_type": "tracked"}
    if corroboration:
        c["corroboration_count"] = corroboration
    if channels:
        c["corroborating_sources"] = channels
    fund = {"pe_trailing": 20}
    if analysts is not None:
        fund["num_analyst_opinions"] = analysts
    return c, fund


def test_widely_covered_name_beats_thinly_covered():
    c_hi, f_hi = _tracked(analysts=40)
    c_lo, f_lo = _tracked(analysts=3)
    hi = score_evidence_quality(c_hi, f_hi, FULL_TECH)
    lo = score_evidence_quality(c_lo, f_lo, FULL_TECH)
    assert hi > lo, (hi, lo)


def test_tracked_names_no_longer_all_pin_to_100():
    scores = {
        score_evidence_quality(*(_tracked(analysts=a) + (FULL_TECH,)))
        for a in (2, 6, 12, 20, 40)
    }
    assert len(scores) >= 3, scores  # genuinely spreads
    assert max(scores) <= 100


def test_multi_source_corroboration_adds_evidence():
    c1, f = _tracked(analysts=10, corroboration=1)
    c3, _ = _tracked(analysts=10, corroboration=3, channels=["a", "b", "c"])
    assert score_evidence_quality(c3, f, FULL_TECH) > score_evidence_quality(c1, f, FULL_TECH)


def test_lone_discovery_still_below_validated_name():
    disc = {"source": "supply_chain", "signal_data": {}, "corroboration_count": 1}
    tracked, f = _tracked(analysts=20)
    assert score_evidence_quality(disc, {"pe_trailing": 20}, FULL_TECH) < score_evidence_quality(
        tracked, f, FULL_TECH
    )
