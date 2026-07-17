"""Tests for the LunarCrush client: env-var fallback + v4 nested-field extraction."""
from __future__ import annotations

from src.shared import lunarcrush


def test_get_headers_accepts_legacy_env_name(monkeypatch):
    monkeypatch.delenv("LUNARCRUSH_API_KEY", raising=False)
    monkeypatch.setenv("LUNAR_CRUSH_API", "abc123")
    headers = lunarcrush._get_headers()
    assert headers == {"Authorization": "Bearer abc123"}


def test_get_headers_prefers_canonical_env_name(monkeypatch):
    monkeypatch.setenv("LUNARCRUSH_API_KEY", "canonical")
    monkeypatch.setenv("LUNAR_CRUSH_API", "legacy")
    assert lunarcrush._get_headers() == {"Authorization": "Bearer canonical"}


def test_get_headers_none_when_unset(monkeypatch):
    monkeypatch.delenv("LUNARCRUSH_API_KEY", raising=False)
    monkeypatch.delenv("LUNAR_CRUSH_API", raising=False)
    assert lunarcrush._get_headers() is None


def test_get_stock_social_metrics_reads_nested_data(monkeypatch):
    """v4 nests metrics under a top-level 'data' object; extraction must follow it."""
    monkeypatch.setenv("LUNARCRUSH_API_KEY", "k")

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "config": {"symbol": "NVDA"},
                "data": {
                    "symbol": "NVDA",
                    "galaxy_score": 48.6,
                    "alt_rank": 228,
                    "social_volume": 1234,
                    "social_score": 99,
                },
            }

    monkeypatch.setattr(lunarcrush.requests, "get", lambda *a, **k: _Resp())
    out = lunarcrush.get_stock_social_metrics("NVDA")
    assert out == {
        "galaxy_score": 48.6,
        "alt_rank": 228,
        "social_volume": 1234,
        "social_score": 99,
    }


def _resp(payload):
    class _R:
        def raise_for_status(self):
            return None

        def json(self):
            return payload

    return _R()


def test_get_social_posts_normalises_cross_platform_feed(monkeypatch):
    monkeypatch.setenv("LUNARCRUSH_API_KEY", "k")
    payload = {"data": [
        {"post_type": "tweet", "post_title": "NVDA breakout", "post_link": "https://x.com/a/1",
         "post_sentiment": 3.6, "creator_name": "bull1", "interactions_24h": 5000},
        {"post_type": "reddit-post", "post_title": "NVDA overvalued", "post_link": "https://r/x",
         "post_sentiment": 2.5, "creator_name": "bear1", "interactions_24h": 800},
    ]}
    captured = {}

    def _get(url, **k):
        captured["url"] = url
        return _resp(payload)

    monkeypatch.setattr(lunarcrush.requests, "get", _get)
    posts = lunarcrush.get_social_posts("NVDA", limit=20)
    assert "/topic/$nvda/posts/v1" in captured["url"]  # cashtag topic
    assert posts[0]["platform"] == "tweet"
    assert posts[0]["sentiment"] == "bullish"
    assert posts[1]["sentiment"] == "bearish"
    assert posts[0]["link"] == "https://x.com/a/1"


def test_get_social_summary_extracts_types_sentiment(monkeypatch):
    monkeypatch.setenv("LUNARCRUSH_API_KEY", "k")
    payload = {"data": {"interactions_24h": 10, "num_posts": 5,
                        "types_sentiment": {"tweet": 80, "reddit-post": 60}}}
    monkeypatch.setattr(lunarcrush.requests, "get", lambda *a, **k: _resp(payload))
    out = lunarcrush.get_social_summary("NVDA")
    assert out["types_sentiment"] == {"tweet": 80, "reddit-post": 60}


def test_social_functions_empty_without_key(monkeypatch):
    monkeypatch.delenv("LUNARCRUSH_API_KEY", raising=False)
    monkeypatch.delenv("LUNAR_CRUSH_API", raising=False)
    assert lunarcrush.get_social_posts("NVDA") == []
    assert lunarcrush.get_top_creators("NVDA") == []
    assert lunarcrush.get_social_summary("NVDA") is None
    assert lunarcrush.get_trending_social_stocks() == []


def test_sentiment_label_thresholds():
    assert lunarcrush._sentiment_label(4.0) == "bullish"
    assert lunarcrush._sentiment_label(2.0) == "bearish"
    assert lunarcrush._sentiment_label(3.0) == "neutral"
    assert lunarcrush._sentiment_label(None) == "neutral"
