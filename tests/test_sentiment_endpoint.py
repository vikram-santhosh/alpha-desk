from __future__ import annotations

import importlib


def test_sentiment_from_score_result_splits_bull_bear():
    app = importlib.import_module("src.api.app")
    result = {
        "top": [
            {
                "ticker": "NVDA",
                "score": 8.0,
                "breakdown": [
                    {"direction": "BULL", "evidence": "Earnings beat"},
                    {"direction": "BULL", "evidence": "Guidance raised"},
                    {"direction": "BEAR", "evidence": "Valuation rich"},
                    {"direction": "NEUTRAL", "evidence": ""},
                ],
            }
        ]
    }
    out = app._sentiment_from_score_result(result, 12)
    assert len(out) == 1
    s = out[0]
    assert s.ticker == "NVDA"
    assert s.socialScore == 80.0  # 8.0 * 10
    assert s.bullishPct == round(2 / 3 * 100, 1)  # 2 bull / 3 directional
    assert s.bearishPct == round(100 - 2 / 3 * 100, 1)
    assert s.topInfluencerPosts == ["Earnings beat", "Guidance raised", "Valuation rich"]


def test_sentiment_neutral_when_no_directional_signals():
    app = importlib.import_module("src.api.app")
    out = app._sentiment_from_score_result({"top": [{"ticker": "ABC", "score": 5.0, "breakdown": []}]}, 12)
    assert out[0].bullishPct == 50.0
    assert out[0].bearishPct == 50.0


def test_enrich_sentiment_noop_without_lunarcrush_key(monkeypatch):
    import asyncio
    app = importlib.import_module("src.api.app")
    from src.shared import lunarcrush as lc

    monkeypatch.setattr(lc, "_get_headers", lambda: None)
    base = [app.SentimentTickerOut(ticker="NVDA", socialScore=70, bullishPct=70, bearishPct=30)]
    out = asyncio.run(app._enrich_sentiment_with_lunarcrush(base, 12))
    assert out == base


def test_enrich_sentiment_overlays_lunarcrush_social(monkeypatch):
    import asyncio
    app = importlib.import_module("src.api.app")
    from src.shared import lunarcrush as lc

    monkeypatch.setattr(lc, "_get_headers", lambda: {"Authorization": "Bearer x"})
    monkeypatch.setattr(lc, "get_trending_social_stocks", lambda n=300: [{"symbol": "NVDA", "percent_change_24h": -3.0}])
    monkeypatch.setattr(lc, "get_social_summary", lambda s: {"types_sentiment": {"tweet": 80, "reddit-post": 70}})
    monkeypatch.setattr(
        lc, "get_social_posts",
        lambda s, n=8: [{"platform": "tweet", "title": "NVDA to the moon", "link": "u",
                         "sentiment": "bullish", "creator": "bull1", "interactions": 5000}],
    )
    base = [app.SentimentTickerOut(ticker="NVDA", socialScore=50.0, bullishPct=50.0, bearishPct=50.0)]
    out = asyncio.run(app._enrich_sentiment_with_lunarcrush(base, 12))
    s = out[0]
    assert s.bullishPct == 75.0          # avg(80, 70)
    assert s.bearishPct == 25.0
    assert s.priceChangePct == -3.0
    assert s.divergence == "bullish"     # crowd bullish, price down
    assert s.socialVolume[0].value == 5000.0
    assert s.topInfluencerPosts == ["@bull1: NVDA to the moon"]
