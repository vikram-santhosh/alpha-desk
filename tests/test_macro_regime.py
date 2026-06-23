from __future__ import annotations

from src.advisor import memory
from src.advisor.macro_analyst import update_macro_theses


def test_low_prediction_market_cut_odds_weakens_rate_easing_thesis(monkeypatch, tmp_path):
    monkeypatch.setattr(memory, "DB_PATH", tmp_path / "advisor_memory.db")
    memory.seed_macro_theses([
        {
            "title": "Fed Easing Cycle",
            "description": "Rate cuts expected in 2026, dollar weakening, growth tailwind",
            "affected_tickers": ["AMZN", "GOOG"],
        }
    ])

    theses = update_macro_theses(
        macro_data={},
        news_signals=[],
        prediction_markets=[
            {
                "platform": "kalshi",
                "title": "Will the Fed make a rate cut before December 2026?",
                "probability": 0.18,
                "category": "fed_policy",
                "affected_tickers": ["AMZN", "GOOG"],
                "url": "https://example.com/fed-cuts",
            }
        ],
        macro_easing_prob_threshold=0.30,
    )

    stored = memory.get_all_macro_theses()[0]
    assert stored["status"] == "weakening"
    assert any("Prediction market kalshi" in item["evidence"] for item in stored["evidence_log"])
    assert any("18% rate-cut odds" in item["evidence"] for item in stored["evidence_log"])

    fed_thesis = next(item for item in theses if item["title"] == "Fed Easing Cycle")
    assert fed_thesis["current_status"] == "weakening"
    assert fed_thesis["prediction_context"][0]["title"] == "Market-implied Fed cut odds"
    assert fed_thesis["prediction_context"][0]["probability"] == 0.18


def test_high_prediction_market_cut_odds_leave_rate_easing_thesis_intact(monkeypatch, tmp_path):
    monkeypatch.setattr(memory, "DB_PATH", tmp_path / "advisor_memory.db")
    memory.seed_macro_theses([
        {
            "title": "Fed Easing Cycle",
            "description": "Rate cuts expected in 2026, dollar weakening, growth tailwind",
            "affected_tickers": ["AMZN", "GOOG"],
        }
    ])

    update_macro_theses(
        macro_data={},
        news_signals=[],
        prediction_markets=[
            {
                "platform": "polymarket",
                "title": "Will the Fed make a rate cut before December 2026?",
                "probability": 0.64,
                "category": "fed_policy",
                "affected_tickers": ["AMZN", "GOOG"],
                "url": "https://example.com/fed-cuts",
            }
        ],
        macro_easing_prob_threshold=0.30,
    )

    stored = memory.get_all_macro_theses()[0]
    assert stored["status"] == "intact"
    assert stored["evidence_log"] == []
