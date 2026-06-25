from __future__ import annotations

from src.advisor.position_sizer import size_recommendations


def test_position_sizer_caps_weights_includes_cash_and_sums_to_100():
    result = size_recommendations(
        conviction_list=[
            {"ticker": "META", "conviction": "high", "weighted_score": 0.90},
            {"ticker": "MSFT", "conviction": "medium", "weighted_score": 0.65},
        ],
        moonshot_list=[
            {"ticker": "RKLB", "conviction": "high", "max_position_pct": 3.0},
        ],
        holdings=[
            {"ticker": "META", "position_pct": 8.0, "sector": "Communication Services"},
            {"ticker": "MSFT", "position_pct": 12.0, "sector": "Software"},
        ],
        valuation_data={
            "META": {"margin_of_safety": 30.0},
            "MSFT": {"margin_of_safety": 18.0},
            "RKLB": {"margin_of_safety": 60.0},
        },
        config={"strategy": {"max_position_pct": 15, "moonshot_max_pct": 3, "min_hold_period_days": 365}},
    )

    allocations = result["allocations"]
    total = sum(item["recommended_weight_pct"] for item in allocations)
    assert round(total, 2) == 100.0
    assert any(item["ticker"] == "CASH" and item["recommended_weight_pct"] > 0 for item in allocations)

    meta = next(item for item in allocations if item["ticker"] == "META")
    rklb = next(item for item in allocations if item["ticker"] == "RKLB")
    assert meta["recommended_weight_pct"] <= 15
    assert rklb["recommended_weight_pct"] <= 3
    assert meta["entry_strategy"]
    assert meta["portfolio_impact"]
    assert meta["sizing"]["recommended_weight_pct"] == meta["recommended_weight_pct"]


def test_position_sizer_flags_concentration_and_proposes_trims():
    result = size_recommendations(
        conviction_list=[],
        moonshot_list=[],
        holdings=[
            {"ticker": "NVDA", "position_pct": 35.0, "sector": "Semiconductors"},
            {"ticker": "AVGO", "position_pct": 25.0, "sector": "Semiconductors"},
            {"ticker": "MSFT", "position_pct": 20.0, "sector": "Software"},
        ],
        valuation_data={},
        config={"strategy": {"theme_concentration_threshold_pct": 50}},
    )

    flags = result["concentration_flags"]
    assert flags
    flag = flags[0]
    assert flag["theme"] == "Semiconductors"
    assert flag["exposure_pct"] == 60.0
    assert flag["excess_pct"] == 10.0
    assert flag["trim_suggestions"]
    assert result["trim_suggestions"][0]["ticker"] == "NVDA"
