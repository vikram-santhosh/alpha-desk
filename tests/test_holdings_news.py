"""Test that holdings show news context instead of just streaks."""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Mock heavy dependencies before any src imports
from unittest.mock import patch, MagicMock
for mod_name in [
    "anthropic",
    "telegram",
    "telegram.ext",
    "telegram.constants",
    "bs4",
    "feedparser",
    "yfinance",
    "requests",
    "dotenv",
]:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

import pytest


def test_news_by_ticker_indexes_all_tickers():
    """News with tickers list should be indexed under all mentioned tickers."""
    from src.advisor.holdings_monitor import monitor_holdings

    holdings = [
        {"ticker": "NVDA", "entry_price": 150.0, "shares": 10, "tracking_since": "2025-01-01",
         "thesis": "AI GPU leader", "thesis_status": "intact", "category": "core"},
        {"ticker": "MA", "entry_price": 400.0, "shares": 5, "tracking_since": "2025-01-01",
         "thesis": "Digital payments", "thesis_status": "intact", "category": "core"},
    ]

    prices = {
        "NVDA": {"price": 190.10, "change_pct": 0.1},
        "MA": {"price": 520.0, "change_pct": -0.5},
    }

    fundamentals = {
        "NVDA": {"sector": "Technology"},
        "MA": {"sector": "Financial Services"},
    }

    news_signals = [
        # This article mentions NVDA in its tickers list but has no primary ticker
        {
            "headline": "Trump hikes global tariff to 15%",
            "category": "macro",
            "tickers": ["NVDA", "AMZN", "GOOG"],
            "source": "Reuters",
        },
        # This article has NVDA as primary ticker
        {
            "headline": "Nvidia earnings Feb 25 — crucial AI CapEx update",
            "ticker": "NVDA",
            "category": "earnings",
            "tickers": ["NVDA"],
            "source": "Barrons",
        },
        # This article is about MA
        {
            "headline": "Mastercard Q4 results beat estimates on cross-border volume",
            "ticker": "MA",
            "category": "earnings",
            "tickers": ["MA"],
            "source": "Reuters",
        },
    ]

    # Mock memory functions to avoid DB access
    with patch("src.advisor.holdings_monitor.get_all_holdings", return_value=holdings), \
         patch("src.advisor.holdings_monitor.get_recent_snapshots", return_value=[]), \
         patch("src.advisor.holdings_monitor.record_snapshot"):

        reports = monitor_holdings(
            holdings=holdings,
            prices=prices,
            fundamentals=fundamentals,
            signals=[],
            news_signals=news_signals,
        )

    nvda_report = next(r for r in reports if r["ticker"] == "NVDA")
    ma_report = next(r for r in reports if r["ticker"] == "MA")

    print(f"\n{'='*60}")
    print("Holdings News Context Test")
    print(f"{'='*60}")

    print(f"\n📊 NVDA key_events ({len(nvda_report['key_events'])}):")
    for e in nvda_report["key_events"]:
        print(f"  📌 {e}")

    print(f"\n📊 MA key_events ({len(ma_report['key_events'])}):")
    for e in ma_report["key_events"]:
        print(f"  📌 {e}")

    # NVDA should have both the tariff headline AND the earnings headline
    nvda_events = nvda_report["key_events"]
    assert any("tariff" in e.lower() for e in nvda_events), \
        f"NVDA should have tariff headline. Got: {nvda_events}"
    assert any("earnings" in e.lower() or "nvidia" in e.lower() for e in nvda_events), \
        f"NVDA should have earnings headline. Got: {nvda_events}"

    # MA should have the Q4 results headline
    ma_events = ma_report["key_events"]
    assert any("mastercard" in e.lower() or "q4" in e.lower() for e in ma_events), \
        f"MA should have Q4 results headline. Got: {ma_events}"

    # Events should NOT have "News: " prefix
    for e in nvda_events + ma_events:
        assert not e.startswith("News: "), f"Event should not have 'News: ' prefix: {e}"

    print("\n✅ All news correctly indexed by tickers list!")
    print("✅ No 'News: ' prefix in key_events!")


def test_formatter_shows_news_before_streaks():
    """Formatter should show news headlines before trend streaks."""
    from src.advisor.formatter import _format_holding_detail

    # Holding with news events AND a streak
    h = {
        "ticker": "NVDA",
        "price": 190.10,
        "shares": 10,
        "entry_price": 150.0,
        "change_pct": 0.1,
        "cumulative_return_pct": 26.7,
        "thesis": "AI GPU leader",
        "thesis_status": "intact",
        "recent_trend": "Strong: up 6/7 sessions. 6-day up streak.",
        "key_events": [
            "Trump hikes global tariff to 15%",
            "Nvidia earnings Feb 25 — crucial AI CapEx update",
        ],
        "position_pct": 8.5,
        "earnings_approaching": True,
        "earnings_date": "2026-02-25",
        "earnings_days_out": 1,
    }

    lines = []
    _format_holding_detail(h, lines)
    output = "\n".join(lines)

    print(f"\n{'='*60}")
    print("Formatter Priority Test (NVDA with news + streak)")
    print(f"{'='*60}")
    print(output)

    # News should appear (with 📌)
    assert "📌" in output, "News headlines should have 📌 emoji"
    assert "tariff" in output.lower(), "Tariff headline should appear"
    assert "earnings" in output.lower() or "nvidia" in output.lower(), "Earnings headline should appear"

    # Earnings date should appear (with 📅)
    assert "📅" in output, "Earnings date should have 📅 emoji"

    # Streak should NOT appear when news is present
    assert "6-day up streak" not in output, "Streak should not show when news is present"
    assert "6/7 sessions" not in output, "Streak count should not show when news is present"

    print("\n✅ News shown before streaks!")
    print("✅ Streak hidden when news is present!")


def test_formatter_fallback_to_trend_when_no_news():
    """When there's no news, formatter should fall back to trend narrative."""
    from src.advisor.formatter import _format_holding_detail

    h = {
        "ticker": "GOOG",
        "price": 313.42,
        "shares": 5,
        "entry_price": 280.0,
        "change_pct": -0.5,
        "cumulative_return_pct": 11.9,
        "thesis": "Cloud margin inflection",
        "thesis_status": "intact",
        "recent_trend": "Sideways (4 up, 3 down of 7).",
        "key_events": [],  # No news
        "position_pct": 5.2,
        "earnings_approaching": False,
        "earnings_date": None,
        "earnings_days_out": None,
    }

    lines = []
    _format_holding_detail(h, lines)
    output = "\n".join(lines)

    print(f"\n{'='*60}")
    print("Formatter Fallback Test (GOOG with no news)")
    print(f"{'='*60}")
    print(output)

    # No 📌 since no news
    assert "📌" not in output, "Should not show 📌 when no news"
    # Trend should appear as fallback
    assert "sideways" in output.lower() or "4 up" in output.lower(), \
        "Trend should appear as fallback when no news"

    print("\n✅ Trend correctly shown as fallback!")


if __name__ == "__main__":
    test_news_by_ticker_indexes_all_tickers()
    test_formatter_shows_news_before_streaks()
    test_formatter_fallback_to_trend_when_no_news()
    print("\n✅ All Phase 3 tests passed!")
