"""Test that conviction list fix works — candidates can pass with 2/5 evidence sources."""
import logging
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Mock heavy dependencies before any src imports
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
            "strategy": {
                "min_evidence_sources": 2,
                "min_weighted_conviction_score_discovery": 0.25,
            },
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
    print("Conviction List Update Results")
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


def test_weighted_conviction_prioritizes_fundamentals_over_viral_reddit():
    """Strong fundamentals should outrank weak fundamentals plus viral Reddit."""
    from src.advisor.conviction_manager import score_weighted_conviction

    fundamentals_first = score_weighted_conviction(
        guidance_data=None,
        crowd_data={"reddit_sentiment": 0.20, "mentions": 3},
        smart_money_data=None,
        fundamentals={
            "revenue_growth": 0.34,
            "net_margin": 0.18,
            "gross_margin": 0.58,
            "analyst_rating": "hold",
        },
        valuation={"implied_cagr": 27, "margin_of_safety": 16, "insufficient_data": False},
    )
    viral_reddit = score_weighted_conviction(
        guidance_data=None,
        crowd_data={"reddit_sentiment": 0.95, "mentions": 120},
        smart_money_data=None,
        fundamentals={
            "revenue_growth": -0.05,
            "net_margin": -0.02,
            "gross_margin": 0.20,
            "analyst_rating": "hold",
        },
        valuation={"implied_cagr": 5, "margin_of_safety": 0, "insufficient_data": False},
    )

    assert fundamentals_first["score"] > viral_reddit["score"]
    assert fundamentals_first["dimension_scores"]["fundamentals"] > 0.8
    assert viral_reddit["dimension_scores"]["crowd_sentiment"] == 1.0


def test_update_conviction_list_orders_by_weighted_score_before_screener_composite():
    from src.advisor.conviction_manager import update_conviction_list

    with patch("src.advisor.conviction_manager.memory") as mock_memory, \
         patch("src.advisor.conviction_manager.passes_investment_gate") as mock_gate, \
         patch("src.advisor.conviction_manager._generate_thesis_via_opus") as mock_opus:
        mock_memory.get_conviction_list.return_value = []
        mock_gate.return_value = (True, "Passes gate")
        mock_opus.side_effect = lambda ticker, candidate, descriptions, valuation=None: f"{ticker} thesis"

        upserted = []

        def track_upsert(**kwargs):
            upserted.append(kwargs)

        mock_memory.upsert_conviction.side_effect = track_upsert
        mock_memory.get_conviction_list.side_effect = lambda active_only=True: [
            {"ticker": u["ticker"], "conviction": u["conviction"], "thesis": u["thesis"]}
            for u in upserted
        ]

        candidates = [
            {
                "ticker": "MEME",
                "source": "reddit",
                "signal_data": {"sentiment": 0.95, "mentions": 120},
                "scores": {"composite": 95},
                "fundamentals_summary": {
                    "revenue_growth": -0.05,
                    "net_margin": -0.02,
                    "gross_margin": 0.20,
                },
            },
            {
                "ticker": "FUND",
                "source": "fundamental_screen",
                "signal_data": {"sentiment": 0.10, "mentions": 1},
                "scores": {"composite": 50},
                "fundamentals_summary": {
                    "revenue_growth": 0.34,
                    "net_margin": 0.18,
                    "gross_margin": 0.58,
                },
            },
        ]
        valuation_data = {
            "MEME": {"implied_cagr": 5, "margin_of_safety": 0, "insufficient_data": False},
            "FUND": {"implied_cagr": 27, "margin_of_safety": 16, "insufficient_data": False},
        }

        result = update_conviction_list(
            candidates=candidates,
            superinvestor_data={},
            earnings_data={},
            prediction_data=[],
            valuation_data=valuation_data,
            config={
                "strategy": {
                    "min_evidence_sources": 1,
                    "min_weighted_conviction_score_discovery": 0.01,
                },
                "output": {"max_conviction_list": 2},
                "holdings": [],
            },
        )

    assert [entry["ticker"] for entry in result["added"]] == ["FUND", "MEME"]
    assert result["added"][0]["weighted_score"] > result["added"][1]["weighted_score"]


def test_conviction_weight_sum_validation_warns(monkeypatch, tmp_path, caplog):
    from src.shared import config_loader

    (tmp_path / "advisor.yaml").write_text(
        """
conviction_weights:
  company_guidance: 0.30
  fundamentals: 0.28
  smart_money: 0.10
  analyst_consensus: 0.05
  crowd_sentiment: 0.02
"""
    )
    monkeypatch.setattr(config_loader, "CONFIG_DIR", tmp_path)
    caplog.set_level(logging.WARNING)

    config_loader.load_config("advisor")

    assert "conviction_weights should sum to 1.0" in caplog.text


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
    print("Crowd Data Build Test")
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
