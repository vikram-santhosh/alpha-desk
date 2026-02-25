"""Test that conviction list fix works — candidates can pass with 2/5 evidence sources."""
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

import sqlite3
import tempfile
from unittest.mock import patch

import pytest


def test_evidence_test_with_fundamentals_and_valuation():
    """Candidates with good fundamentals + valuation should pass 2/5."""
    from src.advisor.conviction_manager import evidence_test

    fundamentals = {
        "revenue_growth": 0.25,
        "net_margin": 0.12,
        "gross_margin": 0.55,
    }
    valuation = {
        "implied_cagr": 28.0,
        "margin_of_safety": 20.0,
        "insufficient_data": False,
    }

    # Mock passes_investment_gate to return True for our valuation
    with patch("src.advisor.conviction_manager.passes_investment_gate") as mock_gate:
        mock_gate.return_value = (True, "Passes 25% CAGR gate")
        sources, descriptions = evidence_test(
            ticker="PLTR",
            guidance_data=None,
            crowd_data=None,
            smart_money_data=None,
            fundamentals=fundamentals,
            valuation=valuation,
        )

    print(f"\n{'='*60}")
    print(f"PLTR Evidence Test: {sources}/5 sources passing")
    print(f"{'='*60}")
    for d in descriptions:
        status = "PASS" if d.startswith("PASS") else "FAIL"
        print(f"  {status} {d}")

    # Should pass at least 2: fundamentals + valuation
    assert sources >= 2, f"Expected >= 2 sources passing, got {sources}"


def test_evidence_test_with_smart_money():
    """Candidate with superinvestor holding should get smart money pass."""
    from src.advisor.conviction_manager import evidence_test

    smart_money = {
        "superinvestor_count": 2,
        "insider_buying": True,
    }
    fundamentals = {
        "revenue_growth": 0.30,
        "net_margin": 0.15,
        "gross_margin": 0.60,
    }

    sources, descriptions = evidence_test(
        ticker="IONQ",
        guidance_data=None,
        crowd_data=None,
        smart_money_data=smart_money,
        fundamentals=fundamentals,
        valuation=None,
    )

    print(f"\n{'='*60}")
    print(f"IONQ Evidence Test: {sources}/5 sources passing")
    print(f"{'='*60}")
    for d in descriptions:
        status = "PASS" if d.startswith("PASS") else "FAIL"
        print(f"  {status} {d}")

    assert sources >= 2, f"Expected >= 2 sources passing, got {sources}"


def test_update_conviction_list_adds_candidates():
    """update_conviction_list should add candidates that pass the relaxed 2/5 gate."""
    from src.advisor.conviction_manager import update_conviction_list

    # Create a temp DB so we don't affect the real one
    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        tmp_path = tmp.name

    # Patch memory to use temp DB
    with patch("src.advisor.conviction_manager.memory") as mock_memory, \
         patch("src.advisor.conviction_manager.passes_investment_gate") as mock_gate, \
         patch("src.advisor.conviction_manager._generate_thesis_via_opus") as mock_opus:

        # Setup mocks
        mock_memory.get_conviction_list.return_value = []  # Empty list initially
        mock_gate.return_value = (True, "Passes gate")
        mock_opus.return_value = "Strong fundamentals with 28% implied CAGR and improving margins."

        # Track what gets upserted
        upserted = []
        def track_upsert(**kwargs):
            upserted.append(kwargs)
        mock_memory.upsert_conviction.side_effect = track_upsert

        # After upsert, return the upserted entries
        def get_conviction_after_upsert(active_only=True):
            return [{"ticker": u["ticker"], "conviction": u["conviction"],
                     "thesis": u["thesis"], "weeks_on_list": 1} for u in upserted]
        mock_memory.get_conviction_list.side_effect = get_conviction_after_upsert

        candidates = []
        for i, ticker in enumerate(["PLTR", "IONQ", "RKLB", "SMR", "PATH"]):
            candidates.append({
                "ticker": ticker,
                "source": f"test_source/{ticker}",
                "signal_type": "test",
                "signal_data": {"sentiment": 0.6, "mentions": 15},
                "scores": {"composite": 70 - i * 5, "sentiment": 65},
                "fundamentals_summary": {
                    "revenue_growth": 0.25 + i * 0.02,
                    "net_margin": 0.12,
                    "gross_margin": 0.55,
                    "market_cap": 20_000_000_000,
                },
            })

        config = {
            "strategy": {"min_evidence_sources": 2},
            "output": {"max_conviction_list": 5},
            "holdings": [{"ticker": "NVDA"}, {"ticker": "AMZN"}],
        }

        valuation_data = {}
        for c in candidates:
            valuation_data[c["ticker"]] = {
                "implied_cagr": 28.0,
                "margin_of_safety": 20.0,
                "insufficient_data": False,
            }

        result = update_conviction_list(
            candidates=candidates,
            superinvestor_data={},
            earnings_data={},
            prediction_data=[],
            valuation_data=valuation_data,
            config=config,
        )

    print(f"\n{'='*60}")
    print(f"Conviction List Update Results")
    print(f"{'='*60}")
    print(f"  Added: {len(result['added'])}")
    print(f"  Removed: {len(result['removed'])}")
    print(f"  Upgraded: {len(result.get('upgraded', []))}")
    for entry in result['added']:
        print(f"  + {entry['ticker']}: conviction={entry['conviction']}, evidence={entry['evidence_sources']}/5")

    # At least 1 candidate should have been added
    assert len(result['added']) >= 1, f"Expected at least 1 addition, got {len(result['added'])}"
    # Verify they have at least 2 evidence sources
    for entry in result['added']:
        assert entry['evidence_sources'] >= 2, f"{entry['ticker']} only had {entry['evidence_sources']} sources"


def test_build_crowd_data_from_signal_data():
    """_build_crowd_data should extract sentiment from candidate signal_data."""
    from src.advisor.conviction_manager import _build_crowd_data

    candidates = [
        {
            "ticker": "PLTR",
            "signal_data": {"sentiment": 0.7, "avg_sentiment": 0.65, "mentions": 20},
        },
        {
            "ticker": "IONQ",
            "signal_data": {"sentiment": 0.5},
        },
    ]

    crowd_pltr = _build_crowd_data("PLTR", candidates, {})
    crowd_ionq = _build_crowd_data("IONQ", candidates, {})
    crowd_unknown = _build_crowd_data("UNKNOWN", candidates, {})

    print(f"\n{'='*60}")
    print(f"Crowd Data Build Test")
    print(f"{'='*60}")
    print(f"  PLTR crowd: {crowd_pltr}")
    print(f"  IONQ crowd: {crowd_ionq}")
    print(f"  UNKNOWN crowd: {crowd_unknown}")

    assert crowd_pltr.get("reddit_sentiment") is not None, "PLTR should have reddit_sentiment"
    assert crowd_ionq.get("reddit_sentiment") is not None, "IONQ should have reddit_sentiment"


if __name__ == "__main__":
    test_evidence_test_with_fundamentals_and_valuation()
    test_evidence_test_with_smart_money()
    test_update_conviction_list_adds_candidates()
    test_build_crowd_data_from_signal_data()
    print("\nAll Phase 1 tests passed!")
