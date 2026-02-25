"""Test macro thesis news deduplication — no more shared headlines across all theses."""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Mock heavy dependencies before any src imports
from unittest.mock import MagicMock
for mod_name in [
    "anthropic",
    "telegram",
    "telegram.ext",
    "telegram.constants",
    "bs4",
    "feedparser",
    "yfinance",
    "requests",
]:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

import pytest


def test_match_news_to_thesis_no_macro_broad():
    """Broad macro articles should NOT be matched to all theses."""
    from src.advisor.macro_analyst import _match_news_to_thesis

    news_signals = [
        # 3 generic macro articles (no specific tickers or keywords)
        {"headline": "Markets fall on inflation fears", "category": "macro", "tickers": [], "source": "Reuters"},
        {"headline": "Global markets update: mixed signals", "category": "macro", "tickers": [], "source": "Bloomberg"},
        {"headline": "Economic outlook uncertain amid trade tensions", "category": "macro", "tickers": [], "source": "CNBC"},
        # 3 NVDA-specific articles
        {"headline": "Nvidia earnings will offer crucial AI update", "category": "earnings", "tickers": ["NVDA"], "source": "Barrons"},
        {"headline": "NVDA price target raised by Morgan Stanley", "category": "analyst", "tickers": ["NVDA"], "source": "MS"},
        {"headline": "Nvidia chips powering next-gen AI data centers", "category": "technology", "tickers": ["NVDA", "AVGO"], "source": "Reuters"},
        # 2 MA-specific articles
        {"headline": "Mastercard Q4 beats estimates on cross-border volume", "category": "earnings", "tickers": ["MA"], "source": "Reuters"},
        {"headline": "Digital payments surge as contactless adoption grows", "category": "payments", "tickers": ["MA", "V"], "source": "FT"},
        # 2 Fed policy articles
        {"headline": "Fed signals rate cuts coming in 2026", "category": "macro", "tickers": [], "source": "WSJ"},
        {"headline": "Federal Reserve easing cycle boosts growth stocks", "category": "macro", "tickers": ["AMZN", "GOOG"], "source": "Bloomberg"},
    ]

    # Test thesis 1: Hyperscaler CapEx Boom
    capex_matches = _match_news_to_thesis(
        "Hyperscaler CapEx Boom",
        ["NVDA", "AVGO", "VRT", "MRVL"],
        news_signals
    )
    capex_headlines = [m["headline"] for m in capex_matches]

    # Test thesis 2: Fed Easing Cycle
    fed_matches = _match_news_to_thesis(
        "Fed Easing Cycle",
        ["AMZN", "GOOG", "META", "NFLX"],
        news_signals
    )
    fed_headlines = [m["headline"] for m in fed_matches]

    # Test thesis 3: Digital Payments
    payments_matches = _match_news_to_thesis(
        "Digital Payments Secular Growth",
        ["MA"],
        news_signals
    )
    payments_headlines = [m["headline"] for m in payments_matches]

    print(f"\n{'='*60}")
    print("Macro Thesis Deduplication Test")
    print(f"{'='*60}")

    print(f"\n📊 Hyperscaler CapEx Boom ({len(capex_matches)} matches):")
    for m in capex_matches:
        print(f"  [{m['match_reason']}] {m['headline']}")

    print(f"\n📊 Fed Easing Cycle ({len(fed_matches)} matches):")
    for m in fed_matches:
        print(f"  [{m['match_reason']}] {m['headline']}")

    print(f"\n📊 Digital Payments ({len(payments_matches)} matches):")
    for m in payments_matches:
        print(f"  [{m['match_reason']}] {m['headline']}")

    # ASSERTIONS

    # 1. Generic macro articles should NOT appear in Digital Payments
    for headline in payments_headlines:
        assert "Markets fall on inflation fears" not in headline, \
            "Generic macro article should not match Digital Payments"
        assert "Global markets update" not in headline, \
            "Generic macro article should not match Digital Payments"

    # 2. NVDA articles should appear in Hyperscaler CapEx
    assert any("Nvidia" in h or "NVDA" in h for h in capex_headlines), \
        "NVDA articles should match Hyperscaler CapEx Boom"

    # 3. NVDA articles should NOT appear in Digital Payments
    for headline in payments_headlines:
        assert "Nvidia" not in headline and "NVDA" not in headline, \
            f"NVDA article should not match Digital Payments: {headline}"

    # 4. MA articles should appear in Digital Payments
    assert any("Mastercard" in h or "payments" in h.lower() or "contactless" in h.lower() for h in payments_headlines), \
        "MA/payments articles should match Digital Payments"

    # 5. No macro_broad matches should exist anywhere
    all_matches = capex_matches + fed_matches + payments_matches
    broad_matches = [m for m in all_matches if m.get("match_reason") == "macro_broad"]
    assert len(broad_matches) == 0, \
        f"Found {len(broad_matches)} macro_broad matches — should be 0"

    # 6. Max 5 matches per thesis
    assert len(capex_matches) <= 5, f"CapEx has {len(capex_matches)} matches, max is 5"
    assert len(fed_matches) <= 5, f"Fed has {len(fed_matches)} matches, max is 5"
    assert len(payments_matches) <= 5, f"Payments has {len(payments_matches)} matches, max is 5"

    print(f"\n✅ No duplication detected!")
    print(f"✅ No macro_broad matches found")
    print(f"✅ Headlines are properly thesis-specific")


def test_no_shared_headlines_across_unrelated_theses():
    """Headlines specific to one thesis should NOT appear in unrelated theses."""
    from src.advisor.macro_analyst import _match_news_to_thesis

    news_signals = [
        {"headline": "Nvidia Q4 revenue crushes expectations", "category": "earnings", "tickers": ["NVDA"], "source": "CNBC"},
        {"headline": "Mastercard launches new B2B payment platform", "category": "business", "tickers": ["MA"], "source": "Reuters"},
        {"headline": "Trump tariff announcement rattles markets", "category": "macro", "tickers": [], "source": "Bloomberg"},
    ]

    capex_matches = _match_news_to_thesis("Hyperscaler CapEx Boom", ["NVDA", "AVGO"], news_signals)
    payments_matches = _match_news_to_thesis("Digital Payments Secular Growth", ["MA"], news_signals)

    capex_headlines = set(m["headline"] for m in capex_matches)
    payments_headlines = set(m["headline"] for m in payments_matches)

    # No overlap between unrelated theses
    shared = capex_headlines & payments_headlines

    print(f"\n{'='*60}")
    print("Cross-Thesis Overlap Test")
    print(f"{'='*60}")
    print(f"  CapEx headlines: {capex_headlines}")
    print(f"  Payments headlines: {payments_headlines}")
    print(f"  Shared: {shared}")

    assert len(shared) == 0, f"Unrelated theses share headlines: {shared}"
    print("  ✅ No cross-thesis headline sharing!")


if __name__ == "__main__":
    test_match_news_to_thesis_no_macro_broad()
    test_no_shared_headlines_across_unrelated_theses()
    print("\n✅ All Phase 2 tests passed!")
