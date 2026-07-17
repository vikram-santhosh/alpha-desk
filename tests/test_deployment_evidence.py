from __future__ import annotations

from types import SimpleNamespace

from src.advisor import deployment_planner as dp


def test_market_value_weights_when_every_holding_is_priced():
    holdings = [
        {"ticker": "A", "shares": 10, "price": 100, "cost_basis": 50},  # mv 1,000
        {"ticker": "B", "shares": 10, "price": 300, "cost_basis": 50},  # mv 3,000
    ]
    basis = dp._apply_market_value_weights(holdings)
    assert basis == "market_value"
    assert holdings[0]["market_value"] == 1000
    assert holdings[0]["position_pct"] == 25.0
    assert holdings[1]["position_pct"] == 75.0


def test_falls_back_to_cost_basis_when_a_price_is_missing():
    holdings = [
        {"ticker": "A", "shares": 10, "price": 100, "position_pct": 40.0},
        {"ticker": "B", "shares": 10, "price": None, "position_pct": 60.0},
    ]
    basis = dp._apply_market_value_weights(holdings)
    assert basis == "cost_basis"
    # Existing cost-basis weights must be left untouched on fallback.
    assert holdings[1]["position_pct"] == 60.0
    assert holdings[1]["market_value"] is None


def test_liquidity_computes_adv_and_days_to_exit():
    holdings = [{"ticker": "A", "price": 100, "avg_volume": 1000, "market_value": 500_000}]
    dp._apply_liquidity(holdings)
    assert holdings[0]["adv_usd"] == 100_000  # 100 × 1,000
    assert holdings[0]["days_to_exit"] == 5.0  # 500,000 ÷ 100,000


def test_liquidity_degrades_when_volume_missing():
    holdings = [{"ticker": "A", "price": 100, "avg_volume": None, "market_value": 500_000}]
    dp._apply_liquidity(holdings)
    assert holdings[0]["adv_usd"] is None
    assert holdings[0]["days_to_exit"] is None


def test_sentiment_from_score_summarizes_lean_and_social_signals():
    score = SimpleNamespace(
        breakdown=[
            {"sensor": "reddit", "direction": "BULL", "evidence": "mentions spiking"},
            {"sensor": "news", "direction": "BEAR", "evidence": "downgrade"},
            {"sensor": "valuation", "direction": "BULL", "evidence": "cheap"},
        ]
    )
    summary = dp._sentiment_from_score(score)
    assert summary["bull_signals"] == 2
    assert summary["bear_signals"] == 1
    assert summary["net_lean"] == "bullish"
    # Only the social/narrative sensors count toward crowding.
    assert {s["sensor"] for s in summary["social_signals"]} == {"reddit", "news"}


def test_attach_sentiment_matches_case_insensitively():
    holdings = [{"ticker": "aapl"}]
    dp._attach_sentiment(holdings, {"AAPL": {"net_lean": "bullish"}})
    assert holdings[0]["sentiment"]["net_lean"] == "bullish"
