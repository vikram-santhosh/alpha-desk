from __future__ import annotations

from src.advisor.conviction_manager import evidence_test
from src.advisor.strategy_engine import should_add
from src.advisor.valuation_engine import passes_investment_gate


GATE_BY_ROLE = {
    "growth": {"min_cagr_pct": 25, "min_mos_pct": 15},
    "ballast": {"min_cagr_pct": 10, "min_mos_pct": 10, "use_total_return": True},
    "defensive": {"min_cagr_pct": 10, "min_mos_pct": 10, "use_total_return": True},
    "moonshot": {"exempt": True},
}


def test_ballast_role_passes_lower_gate_where_growth_fails():
    valuation = {
        "implied_cagr": 12.0,
        "margin_of_safety": 12.0,
        "insufficient_data": False,
    }

    growth_passes, growth_reason = passes_investment_gate(
        valuation,
        role="growth",
        gate_by_role=GATE_BY_ROLE,
    )
    ballast_passes, ballast_reason = passes_investment_gate(
        valuation,
        role="ballast",
        gate_by_role=GATE_BY_ROLE,
    )

    assert growth_passes is False
    assert "FAIL (growth)" in growth_reason
    assert ballast_passes is True
    assert "PASS (ballast)" in ballast_reason


def test_ballast_gate_uses_dividend_in_total_return():
    valuation = {
        "implied_cagr": 7.0,
        "margin_of_safety": 12.0,
        "dividend_yield": 0.04,
        "insufficient_data": False,
    }

    passes, reason = passes_investment_gate(
        valuation,
        role="ballast",
        gate_by_role=GATE_BY_ROLE,
    )

    assert passes is True
    assert "11.0% total return" in reason


def test_strategy_should_add_uses_role_dependent_gate():
    entry = {
        "ticker": "VTI",
        "weeks_on_list": 4,
        "conviction": "medium",
        "category": "ballast",
        "pros": ["PASS Numbers", "PASS Valuation", "PASS Smart money"],
    }
    valuation = {
        "implied_cagr": 7.0,
        "margin_of_safety": 12.0,
        "dividend_yield": 0.04,
        "insufficient_data": False,
    }
    config = {
        "strategy": {
            "conviction_promotion_weeks": 3,
            "min_evidence_sources": 3,
            "gate_by_role": GATE_BY_ROLE,
        }
    }

    should, reason = should_add(entry, valuation, config)

    assert should is True
    assert "PASS (ballast)" in reason


def test_conviction_manager_gate_respects_config_thresholds():
    valuation = {
        "implied_cagr": 12.0,
        "margin_of_safety": 12.0,
        "insufficient_data": False,
    }

    default_sources, default_descriptions = evidence_test(
        ticker="LOWCAGR",
        guidance_data=None,
        crowd_data=None,
        smart_money_data=None,
        fundamentals=None,
        valuation=valuation,
    )
    configured_sources, configured_descriptions = evidence_test(
        ticker="LOWCAGR",
        guidance_data=None,
        crowd_data=None,
        smart_money_data=None,
        fundamentals=None,
        valuation=valuation,
        gate_config={
            "min_cagr_pct": 10,
            "min_margin_of_safety_pct": 10,
        },
        role="growth",
    )

    assert default_sources == 0
    assert any(desc.startswith("FAIL Valuation") for desc in default_descriptions)
    assert configured_sources == 1
    assert any(desc.startswith("PASS Valuation") for desc in configured_descriptions)
