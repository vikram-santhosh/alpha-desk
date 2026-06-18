from __future__ import annotations

from src.alpha_scout.candidate_sourcer import source_all_candidates
from src.alpha_scout.screener import normalize_weights, screen_candidates


def test_top_buys_mode_keeps_existing_portfolio_and_watchlist_tickers():
    audit: dict = {}
    candidates = source_all_candidates(
        existing_tickers=["AMZN", "META", "AVGO"],
        holdings=[{"ticker": "AMZN"}],
        config={
            "sources": {
                "agent_bus": False,
                "sector_peers": False,
                "sp500_index": False,
                "yfinance_screener": False,
                "supply_chain": False,
                "thematic_scanner": False,
                "superinvestor_13f": False,
                "reddit_moonshot": False,
                "filing_scanner": False,
            },
            "screening": {"max_candidates": 50},
        },
        include_existing=True,
        audit=audit,
    )

    tickers = [candidate["ticker"] for candidate in candidates]
    assert tickers == ["AMZN", "META", "AVGO"]
    assert audit["source_counts"]["existing universe"] == 3
    assert audit["excluded_existing"] == []


def test_new_discoveries_mode_excludes_existing_tickers():
    audit: dict = {}
    candidates = source_all_candidates(
        existing_tickers=["AMZN"],
        holdings=[{"ticker": "AMZN"}],
        config={
            "sources": {
                "agent_bus": False,
                "sector_peers": True,
                "sp500_index": False,
                "yfinance_screener": False,
                "supply_chain": False,
                "thematic_scanner": False,
                "superinvestor_13f": False,
                "reddit_moonshot": False,
                "filing_scanner": False,
            },
            "screening": {"max_candidates": 50},
            "sector_peers": {"Consumer Cyclical": ["AMZN", "TSLA"]},
        },
        include_existing=False,
        audit=audit,
    )

    assert [candidate["ticker"] for candidate in candidates] == ["TSLA"]
    assert audit["excluded_existing"][0]["ticker"] == "AMZN"


def test_screener_normalizes_configured_weights_and_scores_full_rubric():
    weights = normalize_weights({
        "technical": 0.20,
        "fundamental": 0.25,
        "sentiment": 0.10,
        "diversification": 0.15,
        "novelty": 0.10,
        "catalyst_proximity": 0.10,
        "evidence_quality": 0.10,
    })

    assert round(sum(weights.values()), 6) == 1.0

    scored = screen_candidates(
        candidates=[
            {
                "ticker": "META",
                "source": "existing_watchlist",
                "signal_type": "watchlist",
                "signal_data": {"cohort": "watchlist", "catalyst": "earnings"},
            }
        ],
        technicals={"META": {}},
        fundamentals={
            "META": {
                "pe_trailing": 28,
                "revenue_growth": 0.16,
                "net_margin": 0.25,
                "gross_margin": 0.80,
                "market_cap": 1_500_000_000_000,
                "sector": "Communication Services",
                "next_earnings_date": "2026-07-25",
            }
        },
        portfolio_tickers=["AMZN"],
        portfolio_fundamentals={"AMZN": {"sector": "Consumer Cyclical"}},
        weights=weights,
    )

    scores = scored[0]["scores"]
    assert "novelty" in scores
    assert "catalyst_proximity" in scores
    assert "evidence_quality" in scores
    assert scores["composite"] > 60
