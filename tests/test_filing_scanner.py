"""Test 13F filing scanner for new superinvestor position detection."""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from unittest.mock import patch, MagicMock

# Mock all external dependencies before imports
for mod in ["anthropic", "fredapi", "yfinance"]:
    sys.modules.setdefault(mod, MagicMock())

import pytest


def test_scan_new_positions():
    """Scanner should find new positions, exclude portfolio tickers and small positions."""
    import src.advisor.superinvestor_tracker as tracker_mod

    mock_raw_candidates = [
        {"ticker": "PLTR", "source": "superinvestor_13f/Dragoneer_Investment",
         "signal_type": "superinvestor_new_position",
         "signal_data": {"investor": "Dragoneer Investment", "shares": 500000,
                         "value_usd": 45_000_000, "filing_date": "2026-02-14"}},
        {"ticker": "IONQ", "source": "superinvestor_13f/Coatue_Management",
         "signal_type": "superinvestor_new_position",
         "signal_data": {"investor": "Coatue Management", "shares": 200000,
                         "value_usd": 8_000_000, "filing_date": "2026-02-10"}},
        {"ticker": "AAPL", "source": "superinvestor_13f/Berkshire_Hathaway",
         "signal_type": "superinvestor_new_position",
         "signal_data": {"investor": "Berkshire Hathaway", "shares": 1000000,
                         "value_usd": 200_000_000}},
        {"ticker": "TINY", "source": "superinvestor_13f/Small_Fund",
         "signal_type": "superinvestor_new_position",
         "signal_data": {"investor": "Small Fund", "shares": 100,
                         "value_usd": 1_000_000}},
    ]
    config = {"superinvestors": [
        {"name": "Dragoneer Investment", "cik": "0001571983"},
        {"name": "Coatue Management", "cik": "0001535392"},
    ]}
    portfolio_tickers = {"NVDA", "AMZN", "GOOG", "META", "AAPL"}

    original_fn = tracker_mod.get_new_positions_as_candidates
    tracker_mod.get_new_positions_as_candidates = lambda config: mock_raw_candidates
    try:
        from src.alpha_scout.filing_scanner import scan_new_positions
        candidates = scan_new_positions(config, exclude_tickers=portfolio_tickers)
    finally:
        tracker_mod.get_new_positions_as_candidates = original_fn

    print(f"\n{'='*60}")
    print("13F Filing Scanner Test")
    print(f"{'='*60}")
    print(f"\nFound {len(candidates)} new position candidates:\n")
    for c in candidates:
        sd = c["signal_data"]
        value_str = f"${sd.get('position_value', 0) / 1e6:.0f}M" if sd.get("position_value") else "N/A"
        print(f"  {c['ticker']}: {sd['fund_name']} — {value_str}")
        print(f"    Source: {c['source']}, Type: {c['signal_type']}\n")

    candidate_tickers = [c["ticker"] for c in candidates]
    assert "PLTR" in candidate_tickers, "PLTR should be found"
    assert "IONQ" in candidate_tickers, "IONQ should be found"
    assert "AAPL" not in candidate_tickers, "AAPL excluded (portfolio)"
    assert "TINY" not in candidate_tickers, "TINY excluded (< $5M)"
    for c in candidates:
        assert c["signal_type"] == "superinvestor_new_position"
        assert c["signal_data"].get("fund_name")
        assert c["source"].startswith("13f_new_position/")

    print("  ✅ PLTR and IONQ detected!")
    print("  ✅ AAPL excluded (portfolio), TINY excluded (< $5M)!")


def test_discovery_narrative():
    from src.advisor.moonshot_manager import _build_discovery_narrative

    cases = [
        ({"signal_type": "reddit_moonshot",
          "signal_data": {"mention_count": 12, "top_subreddits": ["smallstreetbets", "SecurityAnalysis"]},
          "source": "reddit_moonshot/test"},
         "12", "smallstreetbets"),
        ({"signal_type": "superinvestor_new_position",
          "signal_data": {"fund_name": "Dragoneer Investment", "position_value": 45_000_000},
          "source": "13f_new_position/Dragoneer"},
         "Dragoneer", "45M"),
        ({"signal_type": "screener_hit",
          "signal_data": {"screener": "undervalued_growth_stocks"},
          "source": "yf_screener/test"},
         "undervalued_growth_stocks", None),
        ({"signal_type": "unknown", "signal_data": {}, "source": "test/source"},
         "test/source", None),
    ]

    print(f"\n{'='*60}")
    print("Discovery Narrative Test")
    print(f"{'='*60}")
    for candidate, check1, check2 in cases:
        narrative = _build_discovery_narrative(candidate)
        print(f"  {candidate['signal_type']}: {narrative}")
        assert check1 in narrative, f"Expected '{check1}' in '{narrative}'"
        if check2:
            assert check2 in narrative, f"Expected '{check2}' in '{narrative}'"

    print("\n  ✅ All discovery narratives correct!")
