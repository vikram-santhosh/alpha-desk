"""Unit tests for the Sector Scanner module.

Tests all sub-modules: sector_fetcher, analyzer, tracker, formatter, main.
All external dependencies (Finnhub API, Anthropic/Gemini, SQLite, config)
are mocked so tests run fully offline.

Usage:
    pytest tests/test_sector_scanner.py -v
"""

import asyncio
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

SAMPLE_CONFIG = {
    "moonshot": {
        "thematic_sectors": {
            "defense_aerospace": ["LMT", "RTX", "NOC", "GD", "LHX"],
            "gold_miners": ["NEM", "GOLD", "AEM", "FNV", "WPM"],
            "uranium": ["CCJ", "UEC", "NXE", "DNN"],
        },
    },
    "sector_scanner": {
        "enabled": True,
        "tickers_per_sector": 2,
        "max_articles": 60,
        "min_relevance": 6,
    },
}

SAMPLE_ARTICLES = [
    {
        "title": "Lockheed Martin wins $5B Pentagon contract",
        "url": "https://example.com/lmt",
        "source": "Reuters",
        "published_at": "2026-03-18T08:00:00",
        "published_ts": 1774000000,
        "summary": "LMT secures major defense deal for next-gen fighter jets",
        "category": "company",
        "related_tickers": ["LMT"],
        "origin": "finnhub",
        "image": "",
        "finnhub_id": 1,
        "sector": "defense_aerospace",
    },
    {
        "title": "Gold hits $2,500 on inflation fears",
        "url": "https://example.com/gold",
        "source": "Bloomberg",
        "published_at": "2026-03-18T09:00:00",
        "published_ts": 1774003600,
        "summary": "Gold prices surge as CPI data shows persistent inflation",
        "category": "macro",
        "related_tickers": ["NEM"],
        "origin": "finnhub",
        "image": "",
        "finnhub_id": 2,
        "sector": "gold_miners",
    },
    {
        "title": "Uranium prices rise amid nuclear energy push",
        "url": "https://example.com/uranium",
        "source": "WSJ",
        "published_at": "2026-03-18T10:00:00",
        "published_ts": 1774007200,
        "summary": "New nuclear plant approvals drive uranium demand",
        "category": "sector",
        "related_tickers": ["CCJ"],
        "origin": "finnhub",
        "image": "",
        "finnhub_id": 3,
        "sector": "uranium",
    },
]


SAMPLE_ANALYZED = [
    {
        **SAMPLE_ARTICLES[0],
        "sector_relevance": 9,
        "direction": "bullish",
        "catalyst_type": "policy",
        "sector_summary": "Major Pentagon contract strengthens LMT's backlog",
        "sector_tickers": ["LMT", "NOC"],
    },
    {
        **SAMPLE_ARTICLES[1],
        "sector_relevance": 7,
        "direction": "bullish",
        "catalyst_type": "macro",
        "sector_summary": "Gold miners benefit from inflation-driven gold rally",
        "sector_tickers": ["NEM", "GOLD"],
    },
    {
        **SAMPLE_ARTICLES[2],
        "sector_relevance": 8,
        "direction": "bullish",
        "catalyst_type": "supply_demand",
        "sector_summary": "Nuclear energy expansion driving uranium demand",
        "sector_tickers": ["CCJ", "UEC"],
    },
]


# ---------------------------------------------------------------------------
# sector_fetcher tests
# ---------------------------------------------------------------------------


class TestSectorFetcher:

    def test_get_sector_tickers_excludes_portfolio(self):
        from src.sector_scanner.sector_fetcher import _get_sector_tickers

        picks = _get_sector_tickers(SAMPLE_CONFIG, tickers_per_sector=2, exclude_tickers={"LMT", "NOC"})
        assert "defense_aerospace" in picks
        for t in picks["defense_aerospace"]:
            assert t not in ("LMT", "NOC")

    def test_get_sector_tickers_respects_limit(self):
        from src.sector_scanner.sector_fetcher import _get_sector_tickers

        picks = _get_sector_tickers(SAMPLE_CONFIG, tickers_per_sector=1)
        for sector, tickers in picks.items():
            assert len(tickers) <= 1

    def test_get_sector_tickers_empty_config(self):
        from src.sector_scanner.sector_fetcher import _get_sector_tickers

        picks = _get_sector_tickers({}, tickers_per_sector=2)
        assert picks == {}

    @patch("src.news_desk.news_fetcher.fetch_finnhub_news")
    def test_fetch_sector_news_basic(self, mock_fetch):
        from src.sector_scanner.sector_fetcher import fetch_sector_news

        mock_fetch.return_value = SAMPLE_ARTICLES[:2]

        with patch.dict("os.environ", {"FINNHUB_API_KEY": "test-key"}):
            result = fetch_sector_news(config=SAMPLE_CONFIG)

        assert "articles" in result
        assert "sector_picks" in result
        assert "stats" in result
        assert result["stats"]["sectors_scanned"] > 0

    def test_fetch_sector_news_no_api_key(self):
        from src.sector_scanner.sector_fetcher import fetch_sector_news

        with patch.dict("os.environ", {"FINNHUB_API_KEY": ""}):
            result = fetch_sector_news(config=SAMPLE_CONFIG)

        assert result["articles"] == []


# ---------------------------------------------------------------------------
# analyzer tests
# ---------------------------------------------------------------------------


class TestAnalyzer:

    def _mock_response(self, results: list[dict]) -> MagicMock:
        """Build a mock Anthropic response."""
        response = MagicMock()
        response.content = [MagicMock(text=json.dumps(results))]
        response.usage = MagicMock(input_tokens=100, output_tokens=200)
        return response

    @patch("src.sector_scanner.analyzer.record_usage")
    @patch("src.sector_scanner.analyzer.check_budget", return_value=(True, 0.5, 10.0))
    @patch("src.sector_scanner.analyzer.anthropic")
    def test_analyze_articles_filters_by_relevance(self, mock_anthropic, mock_budget, mock_record):
        from src.sector_scanner.analyzer import analyze_sector_articles

        analysis_results = [
            {"sector": "defense_aerospace", "sector_relevance": 9, "direction": "bullish",
             "catalyst_type": "policy", "summary": "Major contract", "tickers": ["LMT"]},
            {"sector": "gold_miners", "sector_relevance": 3, "direction": "neutral",
             "catalyst_type": "other", "summary": "Minor news", "tickers": []},
        ]

        mock_client = MagicMock()
        mock_client.messages.create.return_value = self._mock_response(analysis_results)
        mock_anthropic.Anthropic.return_value = mock_client

        result = analyze_sector_articles(SAMPLE_ARTICLES[:2], min_relevance=6)

        assert len(result) == 1
        assert result[0]["sector_relevance"] == 9
        assert result[0]["direction"] == "bullish"

    @patch("src.sector_scanner.analyzer.check_budget", return_value=(False, 10.0, 10.0))
    def test_analyze_articles_budget_exceeded(self, mock_budget):
        from src.sector_scanner.analyzer import analyze_sector_articles

        result = analyze_sector_articles(SAMPLE_ARTICLES)
        assert result == []

    def test_analyze_articles_empty(self):
        from src.sector_scanner.analyzer import analyze_sector_articles

        result = analyze_sector_articles([])
        assert result == []


# ---------------------------------------------------------------------------
# tracker tests
# ---------------------------------------------------------------------------


class TestTracker:

    @pytest.fixture(autouse=True)
    def _use_tmp_db(self, tmp_path, monkeypatch):
        db_path = tmp_path / "sector_scanner_tracker.db"
        monkeypatch.setattr("src.sector_scanner.tracker.DB_PATH", db_path)

    @patch("src.sector_scanner.tracker.publish")
    def test_track_and_publish_basic(self, mock_publish):
        from src.sector_scanner.tracker import track_and_publish

        mock_publish.return_value = 1

        signals = track_and_publish(SAMPLE_ANALYZED)

        assert len(signals) > 0
        assert mock_publish.call_count > 0

        # Check signal types
        signal_types = {s["type"] for s in signals}
        assert "sector_momentum" in signal_types or "sector_catalyst" in signal_types

    @patch("src.sector_scanner.tracker.publish")
    def test_track_and_publish_deduplicates(self, mock_publish):
        from src.sector_scanner.tracker import track_and_publish

        mock_publish.return_value = 1

        # First call
        signals1 = track_and_publish(SAMPLE_ANALYZED)
        # Second call with same articles
        signals2 = track_and_publish(SAMPLE_ANALYZED)

        assert len(signals2) == 0  # All deduplicated

    @patch("src.sector_scanner.tracker.publish")
    def test_track_and_publish_empty(self, mock_publish):
        from src.sector_scanner.tracker import track_and_publish

        signals = track_and_publish([])
        assert signals == []
        mock_publish.assert_not_called()

    @patch("src.sector_scanner.tracker.publish")
    def test_sector_catalyst_for_high_relevance(self, mock_publish):
        from src.sector_scanner.tracker import track_and_publish

        mock_publish.return_value = 1

        # Article with relevance 9 should trigger sector_catalyst
        high_relevance = [SAMPLE_ANALYZED[0]]  # relevance=9
        signals = track_and_publish(high_relevance)

        catalyst_signals = [s for s in signals if s["type"] == "sector_catalyst"]
        assert len(catalyst_signals) > 0


# ---------------------------------------------------------------------------
# formatter tests
# ---------------------------------------------------------------------------


class TestFormatter:

    def test_format_output_basic(self):
        from src.sector_scanner.formatter import format_output

        result = format_output(SAMPLE_ANALYZED)

        assert "Sector Scanner" in result
        assert "Defense" in result
        assert "Gold" in result
        assert "Uranium" in result

    def test_format_output_empty(self):
        from src.sector_scanner.formatter import format_output

        result = format_output([])
        assert "No notable sector activity" in result

    def test_format_output_max_sectors(self):
        from src.sector_scanner.formatter import format_output, MAX_SECTORS

        # Create articles for more than MAX_SECTORS sectors
        articles = []
        sectors = ["defense_aerospace", "gold_miners", "uranium",
                    "energy_infrastructure", "nuclear_energy", "space_tech",
                    "quantum_computing"]
        for i, sector in enumerate(sectors):
            articles.append({
                "title": f"Article {i}",
                "sector": sector,
                "sector_relevance": 7,
                "direction": "bullish",
                "catalyst_type": "macro",
                "sector_summary": f"Summary for {sector}",
                "sector_tickers": [],
            })

        result = format_output(articles)
        # Should cap at MAX_SECTORS
        sector_count = result.count("\U0001f7e2")  # bullish emoji count
        assert sector_count <= MAX_SECTORS

    def test_format_output_direction_emojis(self):
        from src.sector_scanner.formatter import format_output

        bearish_article = [{
            "title": "Test",
            "sector": "gold_miners",
            "sector_relevance": 8,
            "direction": "bearish",
            "catalyst_type": "macro",
            "sector_summary": "Gold drops",
            "sector_tickers": ["NEM"],
        }]

        result = format_output(bearish_article)
        assert "\U0001f534" in result  # Red circle for bearish


# ---------------------------------------------------------------------------
# main pipeline tests
# ---------------------------------------------------------------------------


class TestMain:

    @patch("src.sector_scanner.tracker.track_and_publish")
    @patch("src.sector_scanner.analyzer.analyze_sector_articles")
    @patch("src.sector_scanner.sector_fetcher.fetch_sector_news")
    def test_run_pipeline_basic(self, mock_fetch, mock_analyze, mock_track):
        from src.sector_scanner.main import run

        mock_fetch.return_value = {
            "articles": SAMPLE_ARTICLES,
            "sector_picks": {"defense_aerospace": ["LMT"]},
            "stats": {"tickers_scanned": 1, "sectors_scanned": 1, "articles_fetched": 3},
        }
        mock_analyze.return_value = SAMPLE_ANALYZED
        mock_track.return_value = [{"id": 1, "type": "sector_momentum", "sector": "defense_aerospace"}]

        result = asyncio.get_event_loop().run_until_complete(
            run(config=SAMPLE_CONFIG)
        )

        assert "formatted" in result
        assert "signals" in result
        assert "stats" in result
        assert len(result["signals"]) == 1

    def test_run_pipeline_no_articles(self):
        from src.sector_scanner.main import run

        with patch("src.sector_scanner.sector_fetcher.fetch_sector_news",
                    return_value={"articles": [], "sector_picks": {}, "stats": {"tickers_scanned": 0}}):
            result = asyncio.get_event_loop().run_until_complete(
                run(config=SAMPLE_CONFIG)
            )

        assert result["formatted"] != ""
        assert result["signals"] == []


# ---------------------------------------------------------------------------
# agent_bus signal type registration test
# ---------------------------------------------------------------------------


class TestSignalTypes:

    def test_sector_signal_types_registered(self):
        from src.shared.agent_bus import SIGNAL_TYPES

        assert "sector_momentum" in SIGNAL_TYPES
        assert "sector_catalyst" in SIGNAL_TYPES


# ---------------------------------------------------------------------------
# run_profile integration test
# ---------------------------------------------------------------------------


class TestRunProfile:

    def test_sector_scanner_in_morning_full(self):
        from src.advisor.run_profile import RUN_STEP_MATRIX

        assert "sector_scanner" in RUN_STEP_MATRIX["morning_full"]

    def test_sector_scanner_not_in_evening(self):
        from src.advisor.run_profile import RUN_STEP_MATRIX

        assert "sector_scanner" not in RUN_STEP_MATRIX["evening_wrap"]
