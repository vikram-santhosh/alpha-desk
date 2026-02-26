"""Comprehensive unit tests for the Substack Ear module.

Tests all five sub-modules: substack_fetcher, analyzer, tracker, formatter, main.
All external dependencies (Anthropic API, RSS feeds, SQLite, config files) are
mocked so tests run fully offline with no real API calls.

Usage:
    pytest tests/test_substack_ear.py -v
"""

import asyncio
import json
import sqlite3
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

SAMPLE_SUBSTACKS_CONFIG = {
    "newsletters": {
        "macro": [
            {"name": "The Diff", "slug": "thediff"},
            {"name": "Kyla Scanlon", "slug": "kylascanlon"},
        ],
        "tech": [
            {"name": "Stratechery", "slug": "stratechery"},
        ],
    },
    "settings": {
        "max_article_age_hours": 72,
        "max_article_chars": 8000,
        "max_articles_per_newsletter": 3,
    },
}


def _make_feed_entry(
    title: str = "Test Article",
    summary: str = "Plain text summary",
    content_html: str | None = None,
    link: str = "https://example.substack.com/p/test",
    author: str = "Author Name",
    published_parsed: time.struct_time | None = None,
) -> SimpleNamespace:
    """Build a mock feedparser entry."""
    entry = SimpleNamespace()
    entry.title = title
    entry.summary = summary
    entry.link = link
    entry.author = author
    if content_html is not None:
        entry.content = [{"value": content_html}]
    else:
        # Mimic no content attribute
        pass
    if published_parsed is None:
        published_parsed = time.localtime()
    entry.published_parsed = published_parsed

    # feedparser entries use .get() for some fields
    entry.get = lambda key, default=None: getattr(entry, key, default)
    return entry


def _make_feed_result(entries: list | None = None, bozo: bool = False, bozo_exception: str = "") -> SimpleNamespace:
    """Build a mock feedparser.parse() result."""
    result = SimpleNamespace()
    result.entries = entries or []
    result.bozo = bozo
    result.bozo_exception = bozo_exception
    return result


@pytest.fixture
def sample_articles() -> list[dict[str, Any]]:
    """Sample articles matching the fetch_articles() output schema."""
    return [
        {
            "title": "AI CapEx Boom Thesis",
            "selftext": "Large language models are driving unprecedented capital expenditure.",
            "score": 0,
            "num_comments": 0,
            "subreddit": "The Diff",
            "url": "https://thediff.substack.com/p/ai-capex",
            "created_utc": time.time() - 3600,
            "author": "Byrne Hobart",
            "source_platform": "substack",
        },
        {
            "title": "Yield Curve Signals",
            "selftext": "The yield curve inversion is unwinding, suggesting sector rotation.",
            "score": 0,
            "num_comments": 0,
            "subreddit": "Kyla Scanlon",
            "url": "https://kylascanlon.substack.com/p/yield-curve",
            "created_utc": time.time() - 7200,
            "author": "Kyla Scanlon",
            "source_platform": "substack",
        },
        {
            "title": "NVDA Earnings Preview",
            "selftext": "NVIDIA is expected to report record revenue driven by data center.",
            "score": 0,
            "num_comments": 0,
            "subreddit": "Stratechery",
            "url": "https://stratechery.substack.com/p/nvda-earnings",
            "created_utc": time.time() - 1800,
            "author": "Ben Thompson",
            "source_platform": "substack",
        },
        {
            "title": "Semiconductor Supply Chains",
            "selftext": "TSMC expansion in Arizona changes the dynamics for chip makers.",
            "score": 0,
            "num_comments": 0,
            "subreddit": "The Diff",
            "url": "https://thediff.substack.com/p/semi-supply",
            "created_utc": time.time() - 5400,
            "author": "Byrne Hobart",
            "source_platform": "substack",
        },
        {
            "title": "Oil Market Rebalancing",
            "selftext": "OPEC cuts and demand recovery suggest higher oil prices ahead.",
            "score": 0,
            "num_comments": 0,
            "subreddit": "Kyla Scanlon",
            "url": "https://kylascanlon.substack.com/p/oil-rebalancing",
            "created_utc": time.time() - 9000,
            "author": "Kyla Scanlon",
            "source_platform": "substack",
        },
        {
            "title": "Cloud Infrastructure Outlook",
            "selftext": "AWS, Azure, GCP all posting accelerating growth rates.",
            "score": 0,
            "num_comments": 0,
            "subreddit": "Stratechery",
            "url": "https://stratechery.substack.com/p/cloud-infra",
            "created_utc": time.time() - 4500,
            "author": "Ben Thompson",
            "source_platform": "substack",
        },
        {
            "title": "Inflation Persistence",
            "selftext": "Sticky services inflation could keep the Fed on hold longer than expected.",
            "score": 0,
            "num_comments": 0,
            "subreddit": "The Diff",
            "url": "https://thediff.substack.com/p/inflation",
            "created_utc": time.time() - 6000,
            "author": "Byrne Hobart",
            "source_platform": "substack",
        },
    ]


@pytest.fixture
def sample_analysis() -> dict[str, Any]:
    """Sample analysis result matching the analyzer output schema."""
    return {
        "tickers": {
            "NVDA": {
                "symbol": "NVDA",
                "total_mentions": 2,
                "avg_sentiment": 1.5,
                "avg_confidence": 0.85,
                "themes": ["AI CapEx", "data center"],
                "source_publications": ["The Diff", "Stratechery"],
            },
            "AAPL": {
                "symbol": "AAPL",
                "total_mentions": 1,
                "avg_sentiment": 0.5,
                "avg_confidence": 0.6,
                "themes": ["services growth"],
                "source_publications": ["Kyla Scanlon"],
            },
        },
        "themes": ["AI infrastructure spending", "rate cut expectations", "sector rotation"],
        "theses": [
            {
                "title": "AI CapEx Boom",
                "summary": "LLM training demand is driving unprecedented data center investment.",
                "affected_tickers": ["NVDA", "AVGO"],
                "conviction": "high",
                "time_horizon": "medium_term",
                "contrarian": False,
            },
            {
                "title": "Sector rotation from tech to cyclicals",
                "summary": "Money rotating out of growth into value and cyclical names.",
                "affected_tickers": ["XLF", "XLE"],
                "conviction": "medium",
                "time_horizon": "short_term",
                "contrarian": True,
            },
            {
                "title": "Low conviction speculative play",
                "summary": "Penny stock might move.",
                "affected_tickers": ["XYZ"],
                "conviction": "low",
                "time_horizon": "short_term",
                "contrarian": False,
            },
        ],
        "macro_signals": [
            {
                "indicator": "Yield curve",
                "implication": "Recession risk declining as curve un-inverts",
                "affected_sectors": ["financials", "real_estate"],
            },
            {
                "indicator": "CPI trend",
                "implication": "Services inflation remains sticky",
                "affected_sectors": ["consumer_discretionary"],
            },
        ],
        "market_mood": "cautiously bullish",
    }


# ===========================================================================
# TestSubstackFetcher
# ===========================================================================

class TestSubstackFetcher:
    """Tests for src/substack_ear/substack_fetcher.py."""

    @patch("src.substack_ear.substack_fetcher.feedparser.parse")
    @patch("src.substack_ear.substack_fetcher.load_config")
    def test_fetch_articles_basic(self, mock_config, mock_parse):
        """fetch_articles returns articles with correct schema from a mocked feed."""
        mock_config.return_value = SAMPLE_SUBSTACKS_CONFIG

        entry = _make_feed_entry(
            title="Test Title",
            summary="A plain text summary of the article.",
            link="https://thediff.substack.com/p/test",
            author="Byrne Hobart",
        )
        mock_parse.return_value = _make_feed_result(entries=[entry])

        from src.substack_ear.substack_fetcher import fetch_articles
        articles = fetch_articles()

        assert len(articles) > 0
        art = articles[0]
        assert art["title"] == "Test Title"
        assert art["source_platform"] == "substack"
        assert art["score"] == 0
        assert art["num_comments"] == 0
        assert art["subreddit"] == "The Diff"
        assert "url" in art
        assert "created_utc" in art

    @patch("src.substack_ear.substack_fetcher.feedparser.parse")
    @patch("src.substack_ear.substack_fetcher.load_config")
    def test_html_stripping(self, mock_config, mock_parse):
        """HTML tags are stripped from article content."""
        mock_config.return_value = SAMPLE_SUBSTACKS_CONFIG

        entry = _make_feed_entry(
            title="HTML Test",
            content_html="<p>This is <b>bold</b> and <a href='#'>linked</a> text.</p>",
        )
        mock_parse.return_value = _make_feed_result(entries=[entry])

        from src.substack_ear.substack_fetcher import fetch_articles
        articles = fetch_articles()

        assert len(articles) > 0
        selftext = articles[0]["selftext"]
        assert "<p>" not in selftext
        assert "<b>" not in selftext
        assert "<a" not in selftext
        assert "bold" in selftext
        assert "linked" in selftext

    @patch("src.substack_ear.substack_fetcher.feedparser.parse")
    @patch("src.substack_ear.substack_fetcher.load_config")
    def test_article_age_filtering(self, mock_config, mock_parse):
        """Articles older than max_article_age_hours (72h) are filtered out."""
        mock_config.return_value = SAMPLE_SUBSTACKS_CONFIG

        # Create one recent and one old entry
        recent_time = time.localtime(time.time() - 3600)  # 1 hour ago
        old_time = time.localtime(time.time() - 80 * 3600)  # 80 hours ago (>72h)

        recent_entry = _make_feed_entry(title="Recent", published_parsed=recent_time)
        old_entry = _make_feed_entry(title="Old", published_parsed=old_time)

        mock_parse.return_value = _make_feed_result(entries=[recent_entry, old_entry])

        from src.substack_ear.substack_fetcher import fetch_articles
        articles = fetch_articles()

        titles = [a["title"] for a in articles]
        assert "Recent" in titles
        assert "Old" not in titles

    @patch("src.substack_ear.substack_fetcher.feedparser.parse")
    @patch("src.substack_ear.substack_fetcher.load_config")
    def test_max_chars_truncation(self, mock_config, mock_parse):
        """Articles with content > max_article_chars (8000) are truncated."""
        mock_config.return_value = SAMPLE_SUBSTACKS_CONFIG

        long_text = "A" * 10000
        entry = _make_feed_entry(title="Long", content_html=long_text)
        mock_parse.return_value = _make_feed_result(entries=[entry])

        from src.substack_ear.substack_fetcher import fetch_articles
        articles = fetch_articles()

        assert len(articles) > 0
        assert len(articles[0]["selftext"]) == 8000

    @patch("src.substack_ear.substack_fetcher.feedparser.parse")
    @patch("src.substack_ear.substack_fetcher.load_config")
    def test_max_articles_per_newsletter(self, mock_config, mock_parse):
        """Only max_articles_per_newsletter articles are returned per feed."""
        config = {
            "newsletters": {
                "macro": [{"name": "OnlyOne", "slug": "onlyone"}],
            },
            "settings": {
                "max_article_age_hours": 72,
                "max_article_chars": 8000,
                "max_articles_per_newsletter": 2,
            },
        }
        mock_config.return_value = config

        entries = [
            _make_feed_entry(title=f"Article {i}") for i in range(5)
        ]
        mock_parse.return_value = _make_feed_result(entries=entries)

        from src.substack_ear.substack_fetcher import fetch_articles
        articles = fetch_articles()

        assert len(articles) == 2

    @patch("src.substack_ear.substack_fetcher.feedparser.parse")
    @patch("src.substack_ear.substack_fetcher.load_config")
    def test_empty_feed(self, mock_config, mock_parse):
        """feedparser returns no entries -> empty list."""
        mock_config.return_value = SAMPLE_SUBSTACKS_CONFIG
        mock_parse.return_value = _make_feed_result(entries=[])

        from src.substack_ear.substack_fetcher import fetch_articles
        articles = fetch_articles()

        assert articles == []

    @patch("src.substack_ear.substack_fetcher.feedparser.parse")
    @patch("src.substack_ear.substack_fetcher.load_config")
    def test_feed_parse_error(self, mock_config, mock_parse):
        """feedparser.parse raises an exception -> continue to next feed, no crash."""
        mock_config.return_value = SAMPLE_SUBSTACKS_CONFIG
        mock_parse.side_effect = Exception("Network error")

        from src.substack_ear.substack_fetcher import fetch_articles
        articles = fetch_articles()

        # Should not raise; returns empty list
        assert articles == []

    @patch("src.substack_ear.substack_fetcher.feedparser.parse")
    @patch("src.substack_ear.substack_fetcher.load_config")
    def test_schema_fields(self, mock_config, mock_parse):
        """Every returned article has all required schema fields."""
        mock_config.return_value = SAMPLE_SUBSTACKS_CONFIG

        entry = _make_feed_entry(title="Schema Check")
        mock_parse.return_value = _make_feed_result(entries=[entry])

        from src.substack_ear.substack_fetcher import fetch_articles
        articles = fetch_articles()

        required_fields = {
            "title", "selftext", "score", "num_comments",
            "subreddit", "url", "created_utc", "author", "source_platform",
        }
        for article in articles:
            assert required_fields.issubset(article.keys()), (
                f"Missing fields: {required_fields - article.keys()}"
            )

    @patch("src.substack_ear.substack_fetcher.feedparser.parse")
    @patch("src.substack_ear.substack_fetcher.load_config")
    def test_bozo_feed_with_no_entries_skipped(self, mock_config, mock_parse):
        """A bozo feed (malformed) with no entries is skipped gracefully."""
        mock_config.return_value = SAMPLE_SUBSTACKS_CONFIG
        mock_parse.return_value = _make_feed_result(
            entries=[], bozo=True, bozo_exception="Malformed XML"
        )

        from src.substack_ear.substack_fetcher import fetch_articles
        articles = fetch_articles()

        assert articles == []

    @patch("src.substack_ear.substack_fetcher.feedparser.parse")
    @patch("src.substack_ear.substack_fetcher.load_config")
    def test_newsletter_without_slug_skipped(self, mock_config, mock_parse):
        """Newsletters missing a slug are skipped."""
        config = {
            "newsletters": {
                "broken": [{"name": "No Slug Newsletter"}],
            },
            "settings": {"max_article_age_hours": 72, "max_article_chars": 8000, "max_articles_per_newsletter": 3},
        }
        mock_config.return_value = config

        from src.substack_ear.substack_fetcher import fetch_articles
        articles = fetch_articles()

        # parse should never be called since slug is missing
        mock_parse.assert_not_called()
        assert articles == []


# ===========================================================================
# TestSubstackAnalyzer
# ===========================================================================

class TestSubstackAnalyzer:
    """Tests for src/substack_ear/analyzer.py."""

    @patch("src.substack_ear.analyzer.check_budget", return_value=(True, 1.0, 20.0))
    @patch("src.substack_ear.analyzer.record_usage")
    @patch("src.substack_ear.analyzer.get_all_tickers", return_value=["NVDA", "AAPL", "MSFT"])
    @patch("src.substack_ear.analyzer.anthropic.Anthropic")
    def test_analyze_articles_basic(self, mock_anthropic_cls, mock_tickers, mock_usage, mock_budget, sample_articles):
        """analyze_articles returns correct output schema with mocked Anthropic client."""
        llm_response = json.dumps({
            "tickers": [
                {"symbol": "NVDA", "sentiment": 1.5, "confidence": 0.8, "themes": ["AI"], "source_publication": "The Diff"}
            ],
            "theses": [
                {
                    "title": "AI CapEx Boom",
                    "summary": "Data center spending surging.",
                    "affected_tickers": ["NVDA"],
                    "conviction": "high",
                    "time_horizon": "medium_term",
                    "contrarian": False,
                }
            ],
            "macro_signals": [
                {"indicator": "CPI", "implication": "Inflation sticky", "affected_sectors": ["consumer"]}
            ],
            "overall_themes": ["AI infrastructure"],
            "market_mood": "bullish",
        })

        mock_response = MagicMock()
        mock_response.usage.input_tokens = 1000
        mock_response.usage.output_tokens = 500
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = llm_response
        mock_response.content = [text_block]

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_anthropic_cls.return_value = mock_client

        from src.substack_ear.analyzer import analyze_articles
        result = analyze_articles(sample_articles[:2])

        assert "tickers" in result
        assert "themes" in result
        assert "theses" in result
        assert "macro_signals" in result
        assert "market_mood" in result
        assert isinstance(result["tickers"], dict)
        assert isinstance(result["theses"], list)

    def test_ticker_validation_rejects_false_positives(self):
        """Common abbreviations (IT, AI, CEO, etc.) are rejected as tickers."""
        from src.substack_ear.analyzer import _validate_ticker_symbol

        false_positives = ["IT", "AI", "CEO", "IPO", "ETF", "GDP", "FED", "SEC", "YOLO", "FOMO"]
        for symbol in false_positives:
            assert _validate_ticker_symbol(symbol) is None, f"{symbol} should be rejected"

    def test_ticker_validation_accepts_valid(self):
        """Valid ticker symbols are accepted and cleaned."""
        from src.substack_ear.analyzer import _validate_ticker_symbol

        assert _validate_ticker_symbol("AAPL") == "AAPL"
        assert _validate_ticker_symbol("NVDA") == "NVDA"
        assert _validate_ticker_symbol("BRK.B") == "BRK.B"
        assert _validate_ticker_symbol("msft") == "MSFT"  # lowercased -> uppercased

    def test_ticker_validation_rejects_empty_and_long(self):
        """Empty strings and overly long strings are rejected."""
        from src.substack_ear.analyzer import _validate_ticker_symbol

        assert _validate_ticker_symbol("") is None
        assert _validate_ticker_symbol(None) is None
        assert _validate_ticker_symbol("TOOLONGSYMBOL") is None

    def test_parse_llm_response_clean_json(self):
        """Valid JSON string is parsed correctly."""
        from src.substack_ear.analyzer import _parse_llm_response

        data = {
            "tickers": [{"symbol": "AAPL"}],
            "theses": [],
            "macro_signals": [],
            "overall_themes": ["tech"],
            "market_mood": "bullish",
        }
        result = _parse_llm_response(json.dumps(data))

        assert result["tickers"] == [{"symbol": "AAPL"}]
        assert result["market_mood"] == "bullish"

    def test_parse_llm_response_markdown_fences(self):
        """JSON wrapped in ```json ... ``` is stripped and parsed correctly."""
        from src.substack_ear.analyzer import _parse_llm_response

        raw = '```json\n{"tickers": [], "theses": [], "macro_signals": [], "overall_themes": [], "market_mood": "bearish"}\n```'
        result = _parse_llm_response(raw)

        assert result["market_mood"] == "bearish"
        assert result["tickers"] == []

    def test_parse_llm_response_invalid_json(self):
        """Invalid JSON falls back to default empty structure."""
        from src.substack_ear.analyzer import _parse_llm_response

        result = _parse_llm_response("this is not json at all {{{")

        assert result["tickers"] == []
        assert result["theses"] == []
        assert result["macro_signals"] == []
        assert result["overall_themes"] == []
        assert result["market_mood"] == "unknown"

    def test_parse_llm_response_missing_keys(self):
        """JSON with missing keys gets defaults filled in."""
        from src.substack_ear.analyzer import _parse_llm_response

        result = _parse_llm_response('{"tickers": [{"symbol": "TSLA"}]}')

        assert result["tickers"] == [{"symbol": "TSLA"}]
        assert result["theses"] == []
        assert result["macro_signals"] == []
        assert result["overall_themes"] == []
        assert result["market_mood"] == "unknown"

    @patch("src.substack_ear.analyzer.check_budget", return_value=(True, 1.0, 20.0))
    @patch("src.substack_ear.analyzer.record_usage")
    @patch("src.substack_ear.analyzer.get_all_tickers", return_value=["NVDA"])
    @patch("src.substack_ear.analyzer.anthropic.Anthropic")
    def test_batch_processing(self, mock_anthropic_cls, mock_tickers, mock_usage, mock_budget, sample_articles):
        """7 articles are processed in 3 batches (3+3+1)."""
        llm_response = json.dumps({
            "tickers": [],
            "theses": [],
            "macro_signals": [],
            "overall_themes": [],
            "market_mood": "neutral",
        })

        mock_response = MagicMock()
        mock_response.usage.input_tokens = 500
        mock_response.usage.output_tokens = 200
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = llm_response
        mock_response.content = [text_block]

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_anthropic_cls.return_value = mock_client

        from src.substack_ear.analyzer import analyze_articles
        assert len(sample_articles) == 7
        analyze_articles(sample_articles)

        # 7 articles / BATCH_SIZE=3 -> 3 batches
        assert mock_client.messages.create.call_count == 3

    @patch("src.substack_ear.analyzer.check_budget", return_value=(False, 25.0, 20.0))
    @patch("src.substack_ear.analyzer.get_all_tickers", return_value=["NVDA"])
    @patch("src.substack_ear.analyzer.anthropic.Anthropic")
    def test_budget_exceeded_skips_analysis(self, mock_anthropic_cls, mock_tickers, mock_budget, sample_articles):
        """When check_budget returns False, analysis is skipped and returns empty."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client

        from src.substack_ear.analyzer import analyze_articles
        result = analyze_articles(sample_articles[:2])

        # API should not be called
        mock_client.messages.create.assert_not_called()
        # Result should have default empty structure
        assert result["theses"] == []
        assert result["market_mood"] == "unknown"

    def test_empty_articles(self):
        """Empty article list returns default empty structure immediately."""
        from src.substack_ear.analyzer import analyze_articles
        result = analyze_articles([])

        assert result == {
            "tickers": {},
            "themes": [],
            "theses": [],
            "macro_signals": [],
            "market_mood": "unknown",
        }

    def test_aggregate_deduplicates_themes(self):
        """Same theme appearing in multiple batches appears only once."""
        from src.substack_ear.analyzer import _aggregate_results

        batch_results = [
            {"tickers": [], "theses": [], "macro_signals": [], "overall_themes": ["AI spending", "rate cuts"], "market_mood": "bullish"},
            {"tickers": [], "theses": [], "macro_signals": [], "overall_themes": ["AI spending", "oil prices"], "market_mood": "neutral"},
        ]
        result = _aggregate_results(batch_results)

        assert result["themes"] == ["AI spending", "rate cuts", "oil prices"]

    def test_aggregate_averages_sentiment(self):
        """Multiple mentions of the same ticker have their sentiment and confidence averaged."""
        from src.substack_ear.analyzer import _aggregate_results

        batch_results = [
            {
                "tickers": [
                    {"symbol": "NVDA", "sentiment": 2.0, "confidence": 0.9, "themes": ["AI"], "source_publication": "The Diff"},
                ],
                "theses": [],
                "macro_signals": [],
                "overall_themes": [],
                "market_mood": "bullish",
            },
            {
                "tickers": [
                    {"symbol": "NVDA", "sentiment": 1.0, "confidence": 0.7, "themes": ["datacenter"], "source_publication": "Stratechery"},
                ],
                "theses": [],
                "macro_signals": [],
                "overall_themes": [],
                "market_mood": "neutral",
            },
        ]
        result = _aggregate_results(batch_results)

        nvda = result["tickers"]["NVDA"]
        assert nvda["total_mentions"] == 2
        assert nvda["avg_sentiment"] == 1.5  # (2.0 + 1.0) / 2
        assert nvda["avg_confidence"] == 0.8  # (0.9 + 0.7) / 2
        assert "AI" in nvda["themes"]
        assert "datacenter" in nvda["themes"]
        assert "The Diff" in nvda["source_publications"]
        assert "Stratechery" in nvda["source_publications"]

    def test_aggregate_most_common_mood(self):
        """Aggregate picks the most common mood across batches."""
        from src.substack_ear.analyzer import _aggregate_results

        batch_results = [
            {"tickers": [], "theses": [], "macro_signals": [], "overall_themes": [], "market_mood": "bullish"},
            {"tickers": [], "theses": [], "macro_signals": [], "overall_themes": [], "market_mood": "bearish"},
            {"tickers": [], "theses": [], "macro_signals": [], "overall_themes": [], "market_mood": "bullish"},
        ]
        result = _aggregate_results(batch_results)
        assert result["market_mood"] == "bullish"

    def test_aggregate_filters_false_positive_tickers(self):
        """False positive tickers in batch results are filtered out during aggregation."""
        from src.substack_ear.analyzer import _aggregate_results

        batch_results = [
            {
                "tickers": [
                    {"symbol": "AI", "sentiment": 1.0, "confidence": 0.5, "themes": [], "source_publication": ""},
                    {"symbol": "NVDA", "sentiment": 1.0, "confidence": 0.8, "themes": [], "source_publication": ""},
                ],
                "theses": [],
                "macro_signals": [],
                "overall_themes": [],
                "market_mood": "neutral",
            },
        ]
        result = _aggregate_results(batch_results)

        assert "AI" not in result["tickers"]
        assert "NVDA" in result["tickers"]


# ===========================================================================
# TestSubstackTracker
# ===========================================================================

class TestSubstackTracker:
    """Tests for src/substack_ear/tracker.py."""

    @pytest.fixture(autouse=True)
    def _redirect_db(self, tmp_path, monkeypatch):
        """Redirect the tracker DB_PATH to a temporary directory."""
        db_path = tmp_path / "substack_tracker.db"
        monkeypatch.setattr("src.substack_ear.tracker.DB_PATH", db_path)

    def test_record_theses(self, sample_analysis):
        """Inserting theses stores them in the DB and they can be retrieved."""
        from src.substack_ear.tracker import record_theses, get_recent_theses

        record_theses(sample_analysis)
        theses = get_recent_theses(days=1)

        assert len(theses) == 3
        titles = [t["title"] for t in theses]
        assert "AI CapEx Boom" in titles

    def test_record_macro_signals(self, sample_analysis):
        """Inserting macro signals stores them in the DB."""
        from src.substack_ear.tracker import record_macro_signals, get_recent_macro_signals

        record_macro_signals(sample_analysis)
        signals = get_recent_macro_signals(days=1)

        assert len(signals) == 2
        indicators = [s["indicator"] for s in signals]
        assert "Yield curve" in indicators
        assert "CPI trend" in indicators

    def test_get_recent_theses(self, sample_analysis):
        """get_recent_theses returns inserted data correctly."""
        from src.substack_ear.tracker import record_theses, get_recent_theses

        record_theses(sample_analysis)
        theses = get_recent_theses(days=7)

        assert len(theses) == 3
        thesis = next(t for t in theses if t["title"] == "AI CapEx Boom")
        assert thesis["conviction"] == "high"
        assert thesis["time_horizon"] == "medium_term"
        assert thesis["source"] == "substack_ear"
        assert thesis["contrarian"] is False
        assert "NVDA" in thesis["affected_tickers"]

    def test_get_recent_macro_signals(self, sample_analysis):
        """get_recent_macro_signals returns inserted data correctly."""
        from src.substack_ear.tracker import record_macro_signals, get_recent_macro_signals

        record_macro_signals(sample_analysis)
        signals = get_recent_macro_signals(days=7)

        assert len(signals) == 2
        sig = next(s for s in signals if s["indicator"] == "Yield curve")
        assert "financials" in sig["affected_sectors"]

    @patch("src.substack_ear.tracker.publish")
    def test_publish_thesis_signals(self, mock_publish, sample_analysis):
        """Expert thesis and macro framework signals are published to agent bus."""
        from src.substack_ear.tracker import publish_thesis_signals

        # Patch narrative tracker to avoid its DB
        with patch("src.substack_ear.tracker.record_narrative", create=True):
            signals = publish_thesis_signals(sample_analysis)

        # Check published signal types
        signal_types = [s["type"] for s in signals]
        assert "expert_thesis" in signal_types
        assert "macro_framework" in signal_types

        # Verify publish() was called
        assert mock_publish.call_count >= 3  # 2 high/medium theses + 2 macro signals

    @patch("src.substack_ear.tracker.publish")
    def test_sector_rotation_detection(self, mock_publish, sample_analysis):
        """A thesis with 'rotation' in its title triggers a sector_rotation_call signal."""
        from src.substack_ear.tracker import publish_thesis_signals

        with patch("src.substack_ear.tracker.record_narrative", create=True):
            signals = publish_thesis_signals(sample_analysis)

        rotation_signals = [s for s in signals if s["type"] == "sector_rotation_call"]
        assert len(rotation_signals) >= 1
        assert "rotation" in rotation_signals[0]["title"].lower()

    @patch("src.substack_ear.tracker.publish")
    def test_low_conviction_filtered(self, mock_publish, sample_analysis):
        """Low conviction theses are NOT published as expert_thesis signals."""
        from src.substack_ear.tracker import publish_thesis_signals

        with patch("src.substack_ear.tracker.record_narrative", create=True):
            signals = publish_thesis_signals(sample_analysis)

        expert_theses = [s for s in signals if s["type"] == "expert_thesis"]
        for et in expert_theses:
            assert et["conviction"] in ("high", "medium"), (
                f"Low conviction thesis should not be published: {et}"
            )
        # Verify the low conviction thesis was not published
        expert_titles = [s["title"] for s in expert_theses]
        assert "Low conviction speculative play" not in expert_titles

    @patch("src.substack_ear.tracker.publish")
    def test_narrative_tracker_integration(self, mock_publish):
        """record_narrative is called for each thesis with a title and tickers."""
        analysis = {
            "theses": [
                {"title": "Thesis A", "affected_tickers": ["NVDA"], "conviction": "high", "summary": "S"},
                {"title": "Thesis B", "affected_tickers": ["AAPL"], "conviction": "medium", "summary": "S"},
                {"title": "", "affected_tickers": ["MSFT"], "conviction": "medium", "summary": "S"},  # empty title skipped
                {"title": "Thesis C", "affected_tickers": [], "conviction": "medium", "summary": "S"},  # empty tickers skipped
            ],
            "macro_signals": [],
        }

        with patch("src.shared.narrative_tracker.record_narrative", create=True) as mock_narrative:
            from src.substack_ear.tracker import publish_thesis_signals
            publish_thesis_signals(analysis)

            # Only theses with non-empty title AND non-empty tickers trigger record_narrative
            assert mock_narrative.call_count == 2
            # Verify the correct narratives were passed
            called_narratives = [call.kwargs.get("narrative", call.args[0] if call.args else "")
                                 for call in mock_narrative.call_args_list]
            assert "Thesis A" in called_narratives
            assert "Thesis B" in called_narratives

    @patch("src.substack_ear.tracker.publish")
    def test_empty_analysis(self, mock_publish):
        """Empty analysis results in nothing recorded or published."""
        from src.substack_ear.tracker import record_theses, record_macro_signals, publish_thesis_signals

        empty = {"theses": [], "macro_signals": []}
        record_theses(empty)
        record_macro_signals(empty)

        with patch("src.substack_ear.tracker.record_narrative", create=True):
            signals = publish_thesis_signals(empty)

        assert signals == []
        mock_publish.assert_not_called()

    def test_contrarian_stored_correctly(self, sample_analysis):
        """Contrarian flag is stored and retrieved correctly from DB."""
        from src.substack_ear.tracker import record_theses, get_recent_theses

        record_theses(sample_analysis)
        theses = get_recent_theses(days=1)

        contrarian_thesis = next(t for t in theses if t["title"] == "Sector rotation from tech to cyclicals")
        assert contrarian_thesis["contrarian"] is True

        non_contrarian = next(t for t in theses if t["title"] == "AI CapEx Boom")
        assert non_contrarian["contrarian"] is False


# ===========================================================================
# TestSubstackFormatter
# ===========================================================================

class TestSubstackFormatter:
    """Tests for src/substack_ear/formatter.py."""

    @patch("src.substack_ear.formatter.load_watchlist", return_value={"tickers": ["NVDA", "AAPL"]})
    @patch("src.substack_ear.formatter.load_portfolio", return_value={"holdings": [{"ticker": "NVDA"}]})
    def test_format_output_basic(self, mock_portfolio, mock_watchlist, sample_analysis):
        """format_output returns HTML string with expected section headers."""
        from src.substack_ear.formatter import format_output

        output = format_output(sample_analysis)

        assert isinstance(output, str)
        assert "<b>SUBSTACK EAR" in output
        assert "<b>Theses</b>" in output

    @patch("src.substack_ear.formatter.load_watchlist", return_value={"tickers": []})
    @patch("src.substack_ear.formatter.load_portfolio", return_value={"holdings": []})
    def test_thesis_display(self, mock_portfolio, mock_watchlist, sample_analysis):
        """Theses appear with conviction icons (!!!, !!, !)."""
        from src.substack_ear.formatter import format_output

        output = format_output(sample_analysis)

        # High conviction thesis should have "!!!" icon
        assert "!!!" in output  # high conviction
        assert "AI CapEx Boom" in output

    @patch("src.substack_ear.formatter.load_watchlist", return_value={"tickers": []})
    @patch("src.substack_ear.formatter.load_portfolio", return_value={"holdings": []})
    def test_macro_signals_display(self, mock_portfolio, mock_watchlist, sample_analysis):
        """Macro signals section is present with indicator and implication."""
        from src.substack_ear.formatter import format_output

        output = format_output(sample_analysis)

        assert "<b>Macro Signals</b>" in output
        assert "Yield curve" in output
        assert "CPI trend" in output

    @patch("src.substack_ear.formatter.load_watchlist", return_value={"tickers": ["NVDA", "AAPL"]})
    @patch("src.substack_ear.formatter.load_portfolio", return_value={"holdings": [{"ticker": "NVDA"}]})
    def test_portfolio_ticker_highlighting(self, mock_portfolio, mock_watchlist, sample_analysis):
        """Tickers in portfolio/watchlist are highlighted with <b> tags."""
        from src.substack_ear.formatter import format_output

        output = format_output(sample_analysis)

        # NVDA is in portfolio and mentioned in analysis.tickers
        assert "<b>Your Tickers Mentioned</b>" in output
        assert "<code>NVDA</code>" in output

    @patch("src.substack_ear.formatter.load_watchlist", return_value={"tickers": []})
    @patch("src.substack_ear.formatter.load_portfolio", return_value={"holdings": []})
    def test_char_limit(self, mock_portfolio, mock_watchlist):
        """Output exceeding 2000 chars is truncated with '...truncated'."""
        from src.substack_ear.formatter import format_output

        # Create analysis with many long theses to exceed 2000 chars
        big_analysis = {
            "tickers": {},
            "themes": [f"Theme number {i} about something interesting" for i in range(20)],
            "theses": [
                {
                    "title": f"Very Long Thesis Title Number {i}",
                    "summary": "A" * 200,
                    "affected_tickers": ["NVDA", "AAPL", "MSFT"],
                    "conviction": "high",
                    "time_horizon": "long_term",
                    "contrarian": False,
                }
                for i in range(15)
            ],
            "macro_signals": [
                {"indicator": f"Signal {i}", "implication": "B" * 100, "affected_sectors": []}
                for i in range(10)
            ],
            "market_mood": "cautiously optimistic about the long-term outlook",
        }
        output = format_output(big_analysis)

        assert "...truncated" in output
        # The total length (including the truncation marker) should be reasonable
        assert len(output) <= 2200  # some slack for the truncation line

    @patch("src.substack_ear.formatter.load_watchlist", return_value={"tickers": []})
    @patch("src.substack_ear.formatter.load_portfolio", return_value={"holdings": []})
    def test_empty_analysis(self, mock_portfolio, mock_watchlist):
        """Empty analysis produces just the header."""
        from src.substack_ear.formatter import format_output

        empty = {
            "tickers": {},
            "themes": [],
            "theses": [],
            "macro_signals": [],
            "market_mood": "unknown",
        }
        output = format_output(empty)

        assert "<b>SUBSTACK EAR" in output
        # Should not have section headers for empty sections
        assert "<b>Theses</b>" not in output
        assert "<b>Macro Signals</b>" not in output

    @patch("src.substack_ear.formatter.load_watchlist", return_value={"tickers": []})
    @patch("src.substack_ear.formatter.load_portfolio", return_value={"holdings": []})
    def test_contrarian_tag(self, mock_portfolio, mock_watchlist, sample_analysis):
        """Contrarian thesis has [CONTRARIAN] tag in output."""
        from src.substack_ear.formatter import format_output

        output = format_output(sample_analysis)

        assert "[CONTRARIAN]" in output

    @patch("src.substack_ear.formatter.load_watchlist", return_value={"tickers": []})
    @patch("src.substack_ear.formatter.load_portfolio", return_value={"holdings": []})
    def test_html_sanitization(self, mock_portfolio, mock_watchlist):
        """Special characters in titles are HTML-escaped."""
        from src.substack_ear.formatter import format_output

        analysis = {
            "tickers": {},
            "themes": ['<script>alert("xss")</script>'],
            "theses": [
                {
                    "title": 'Thesis with <b>HTML</b> & "quotes"',
                    "summary": "Normal summary",
                    "affected_tickers": [],
                    "conviction": "high",
                    "time_horizon": "short_term",
                    "contrarian": False,
                }
            ],
            "macro_signals": [],
            "market_mood": "unknown",
        }
        output = format_output(analysis)

        # Raw HTML should be escaped
        assert "<script>" not in output
        assert "&lt;script&gt;" in output
        assert "&amp;" in output
        assert "&quot;" in output

    @patch("src.substack_ear.formatter.load_watchlist", return_value={"tickers": ["NVDA"]})
    @patch("src.substack_ear.formatter.load_portfolio", return_value={"holdings": [{"ticker": "AAPL"}]})
    def test_ticker_bold_in_thesis_affected(self, mock_portfolio, mock_watchlist):
        """Affected tickers matching portfolio/watchlist are bolded in thesis lines."""
        from src.substack_ear.formatter import format_output

        analysis = {
            "tickers": {},
            "themes": [],
            "theses": [
                {
                    "title": "Test",
                    "summary": "Summary",
                    "affected_tickers": ["NVDA", "GOOG"],
                    "conviction": "high",
                    "time_horizon": "short_term",
                    "contrarian": False,
                }
            ],
            "macro_signals": [],
            "market_mood": "unknown",
        }
        output = format_output(analysis)

        # NVDA is in watchlist so it should be bolded; GOOG is not
        assert "<b>NVDA</b>" in output

    @patch("src.substack_ear.formatter.load_watchlist", return_value={"tickers": []})
    @patch("src.substack_ear.formatter.load_portfolio", return_value={"holdings": []})
    def test_mood_displayed(self, mock_portfolio, mock_watchlist, sample_analysis):
        """Market mood is shown in the header when not 'unknown'."""
        from src.substack_ear.formatter import format_output

        output = format_output(sample_analysis)

        assert "cautiously bullish" in output

    @patch("src.substack_ear.formatter.load_watchlist", return_value={"tickers": []})
    @patch("src.substack_ear.formatter.load_portfolio", return_value={"holdings": []})
    def test_themes_section(self, mock_portfolio, mock_watchlist, sample_analysis):
        """Themes section is present with expected content."""
        from src.substack_ear.formatter import format_output

        output = format_output(sample_analysis)

        assert "<b>Themes</b>" in output
        assert "AI infrastructure spending" in output


# ===========================================================================
# TestSubstackPipeline
# ===========================================================================

class TestSubstackPipeline:
    """Tests for src/substack_ear/main.py pipeline orchestrator."""

    def test_full_pipeline_success(self, sample_articles, sample_analysis):
        """Full pipeline with all steps mocked returns expected structure."""
        with (
            patch("src.substack_ear.substack_fetcher.fetch_articles", return_value=sample_articles),
            patch("src.substack_ear.analyzer.analyze_articles", return_value=sample_analysis),
            patch("src.substack_ear.tracker.record_theses"),
            patch("src.substack_ear.tracker.record_macro_signals"),
            patch("src.substack_ear.tracker.publish_thesis_signals", return_value=[{"type": "expert_thesis"}]),
            patch("src.substack_ear.formatter.format_output", return_value="<b>SUBSTACK EAR</b>"),
        ):
            from src.substack_ear.main import run
            result = asyncio.get_event_loop().run_until_complete(run())

        assert "formatted" in result
        assert "signals" in result
        assert "stats" in result
        assert "analysis" in result
        assert result["formatted"] == "<b>SUBSTACK EAR</b>"
        assert result["signals"] == [{"type": "expert_thesis"}]
        assert result["stats"]["articles_fetched"] == 7

    def test_pipeline_fetch_failure(self):
        """Pipeline continues with empty data when fetcher fails."""
        with (
            patch("src.substack_ear.substack_fetcher.fetch_articles", side_effect=Exception("Network error")),
            patch("src.substack_ear.tracker.record_theses"),
            patch("src.substack_ear.tracker.record_macro_signals"),
            patch("src.substack_ear.tracker.publish_thesis_signals", return_value=[]),
            patch("src.substack_ear.formatter.format_output", return_value="<b>SUBSTACK EAR</b>\n<i>No articles</i>"),
        ):
            from src.substack_ear.main import run
            result = asyncio.get_event_loop().run_until_complete(run())

        assert result["stats"]["articles_fetched"] == 0
        assert "fetch_error" in result["stats"]

    def test_pipeline_analyze_failure(self, sample_articles):
        """Pipeline continues with empty analysis when analyzer fails."""
        with (
            patch("src.substack_ear.substack_fetcher.fetch_articles", return_value=sample_articles),
            patch("src.substack_ear.analyzer.analyze_articles", side_effect=Exception("API error")),
            patch("src.substack_ear.tracker.record_theses"),
            patch("src.substack_ear.tracker.record_macro_signals"),
            patch("src.substack_ear.tracker.publish_thesis_signals", return_value=[]),
            patch("src.substack_ear.formatter.format_output", return_value="<b>SUBSTACK EAR</b>"),
        ):
            from src.substack_ear.main import run
            result = asyncio.get_event_loop().run_until_complete(run())

        assert result["stats"]["articles_fetched"] == 7
        assert "analysis_error" in result["stats"]
        # The analysis dict should have default values
        assert result["analysis"]["market_mood"] == "unknown"

    def test_pipeline_returns_analysis_summary(self, sample_articles, sample_analysis):
        """Pipeline result.analysis contains summary fields."""
        with (
            patch("src.substack_ear.substack_fetcher.fetch_articles", return_value=sample_articles),
            patch("src.substack_ear.analyzer.analyze_articles", return_value=sample_analysis),
            patch("src.substack_ear.tracker.record_theses"),
            patch("src.substack_ear.tracker.record_macro_signals"),
            patch("src.substack_ear.tracker.publish_thesis_signals", return_value=[]),
            patch("src.substack_ear.formatter.format_output", return_value="<b>output</b>"),
        ):
            from src.substack_ear.main import run
            result = asyncio.get_event_loop().run_until_complete(run())

        analysis_summary = result["analysis"]
        assert analysis_summary["market_mood"] == "cautiously bullish"
        assert analysis_summary["tickers_found"] == 2  # NVDA, AAPL
        assert analysis_summary["theses_count"] == 3
        assert analysis_summary["macro_signals_count"] == 2
        assert "AI infrastructure spending" in analysis_summary["themes"]
