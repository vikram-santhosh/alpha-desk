"""The sentiment dimension must use real cross-platform social data when present
(LunarCrush), and stay neutral/degrade gracefully when it isn't."""
from __future__ import annotations

from src.alpha_scout.screener import score_sentiment, score_social_sentiment


def test_no_social_returns_none():
    assert score_social_sentiment(None) is None
    assert score_social_sentiment({}) is None
    assert score_social_sentiment({"bull_pct": None}) is None


def test_bullish_high_engagement_scores_high():
    s = score_social_sentiment({"bull_pct": 80, "num_contributors": 1000})
    assert s >= 75


def test_bearish_high_engagement_scores_low():
    s = score_social_sentiment({"bull_pct": 20, "num_contributors": 1000})
    assert s <= 25


def test_thin_engagement_is_dampened_toward_neutral():
    thin = score_social_sentiment({"bull_pct": 90, "num_contributors": 10})
    heavy = score_social_sentiment({"bull_pct": 90, "num_contributors": 1000})
    assert abs(thin - 50) < abs(heavy - 50)  # thin chatter swings less
    assert 50 <= thin < heavy


def test_score_sentiment_prefers_social_over_bus():
    cand = {
        "social": {"bull_pct": 85, "num_contributors": 800},
        "signal_data": {"sentiment": -1.0},  # bus says bearish; social should win
    }
    assert score_sentiment(cand) >= 70


def test_score_sentiment_falls_back_to_neutral_without_social_or_signals():
    assert score_sentiment({"source": "existing_portfolio/core", "signal_data": {}}) == 50
