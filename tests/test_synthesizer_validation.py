"""Tests for Alpha Scout synthesizer ticker validation and figure tagging."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.alpha_scout.synthesizer import (
    _has_unverified_figures,
    _parse_synthesis,
    _validate_ticker,
)


def _fake_ticker_empty(ticker: str):
    """Mock yfinance.Ticker returning empty history (no existence)."""
    mock = MagicMock()
    mock.history.return_value = MagicMock(empty=True)
    return mock


def test_validate_ticker_accepts_candidate_universe():
    """Tickers in the screened candidate universe are valid without yfinance."""
    assert _validate_ticker("NVDA", {"NVDA", "TSLA"}) == (True, "in_candidate_universe")


def test_validate_ticker_rejects_fake_ticker():
    """A ticker not in the universe and with no yfinance data is invalid."""
    with patch("yfinance.Ticker", side_effect=_fake_ticker_empty):
        assert _validate_ticker("FAKECO", {"NVDA", "TSLA"}) == (False, "not_in_candidate_universe_or_yfinance")


def test_parse_synthesis_quarantines_fake_ticker():
    """A fake ticker from the LLM is quarantined, not emitted as a rec."""
    scored_candidates = [
        {
            "ticker": "NVDA",
            "scores": {"composite": 75.0},
            "fundamentals_summary": {"pe_trailing": 35.0, "revenue_growth": 0.25},
        }
    ]

    raw_json = """
    {
      "portfolio": [
        {"ticker": "NVDA", "conviction": "high", "thesis": "AI GPU leader with 25% revenue growth."},
        {"ticker": "FAKECO", "conviction": "medium", "thesis": "FAKECO will grow 50% next year."}
      ],
      "watchlist": []
    }
    """

    with patch("yfinance.Ticker", side_effect=_fake_ticker_empty):
        result = _parse_synthesis(raw_json, scored_candidates)

    assert [r["ticker"] for r in result["portfolio_recs"]] == ["NVDA"]
    assert [r["ticker"] for r in result["quarantined_recs"]] == ["FAKECO"]
    assert result["quarantined_recs"][0]["quarantine_reason"] == "not_in_candidate_universe_or_yfinance"


def test_parse_synthesis_tags_unverified_figures():
    """A thesis citing numbers for a ticker without fundamentals is tagged."""
    scored_candidates = [
        {
            "ticker": "ZZZZ",
            "scores": {"composite": 60.0},
            "fundamentals_summary": {},
        }
    ]

    raw_json = """
    {
      "portfolio": [
        {"ticker": "ZZZZ", "conviction": "medium", "thesis": "ZZZZ trades at 12x earnings and will grow 30%."}
      ],
      "watchlist": []
    }
    """

    with patch("yfinance.Ticker", side_effect=_fake_ticker_empty):
        result = _parse_synthesis(raw_json, scored_candidates)

    rec = result["portfolio_recs"][0]
    assert "unverified_figures" in rec.get("tags", [])


def test_has_unverified_figures_no_numbers():
    """A thesis without hard numbers is never tagged as unverified."""
    assert _has_unverified_figures("ZZZZ", "Strong qualitative tailwinds.", {"ZZZZ": {}}) is False
