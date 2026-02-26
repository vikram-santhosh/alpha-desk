"""Unit tests for the YouTube Ear module.

Tests cover: youtube_fetcher, analyzer, tracker, formatter, and main pipeline.
All external dependencies (YouTube API, transcript API, Anthropic API, SQLite)
are mocked so tests run fully offline.
"""

import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
import sqlite3
import time
from datetime import datetime, timezone, date
from unittest.mock import MagicMock, patch, PropertyMock

# Pre-mock heavy external packages so imports don't fail
for mod in [
    "anthropic",
    "googleapiclient",
    "googleapiclient.discovery",
    "youtube_transcript_api",
    "fredapi",
    "yfinance",
]:
    sys.modules.setdefault(mod, MagicMock())

import pytest

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

SAMPLE_CONFIG = {
    "settings": {
        "youtube_api_key_env": "YOUTUBE_API_KEY",
        "max_video_age_hours": 48,
        "max_transcript_chars": 6000,
        "max_videos_per_channel": 3,
        "min_view_count": 1000,
    },
    "channels": {
        "macro": [
            {"name": "Patrick Boyle", "channel_id": "UC_ch1"},
            {"name": "Joseph Carlson", "channel_id": "UC_ch2"},
        ],
    },
}


def _make_video(
    title="Test Video",
    channel="TestChannel",
    views=50000,
    comments=100,
    transcript="AAPL is looking bullish with strong earnings ahead.",
    video_id="vid123",
    age_hours=6,
    duration_seconds=900,
):
    """Build a sample video dict matching the fetcher schema."""
    return {
        "title": title,
        "selftext": transcript,
        "score": views,
        "num_comments": comments,
        "subreddit": channel,
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "created_utc": time.time() - (age_hours * 3600),
        "author": channel,
        "source_platform": "youtube",
        "duration_seconds": duration_seconds,
    }


SAMPLE_VIDEOS = [
    _make_video(title="AAPL Deep Dive", channel="Patrick Boyle", video_id="v1"),
    _make_video(title="NVDA Bull Case", channel="Joseph Carlson", video_id="v2"),
]

SAMPLE_LLM_JSON = {
    "tickers": [
        {
            "symbol": "AAPL",
            "mentions": 5,
            "sentiment": 1.5,
            "confidence": 0.85,
            "themes": ["strong earnings", "AI integration"],
            "notable_quote": "Apple is undervalued...",
            "source_channels": ["Patrick Boyle"],
        },
        {
            "symbol": "NVDA",
            "mentions": 3,
            "sentiment": 2.0,
            "confidence": 0.9,
            "themes": ["AI infrastructure"],
            "notable_quote": "NVDA dominates...",
            "source_channels": ["Joseph Carlson"],
        },
    ],
    "theses": [
        {
            "ticker": "AAPL",
            "direction": "bullish",
            "thesis": "Apple AI play undervalued relative to peers",
            "confidence": 0.85,
            "source": "Patrick Boyle",
            "themes": ["AI", "services growth"],
        },
    ],
    "macro_signals": ["rate cut expectations building"],
    "overall_themes": ["AI infrastructure spending"],
    "market_mood": "cautiously bullish",
}


def _make_analysis():
    """Build a sample aggregated analysis dict."""
    return {
        "tickers": {
            "AAPL": {
                "symbol": "AAPL",
                "total_mentions": 5,
                "avg_sentiment": 1.5,
                "avg_confidence": 0.85,
                "themes": ["strong earnings", "AI integration"],
                "notable_quotes": ["Apple is undervalued..."],
                "channels": ["Patrick Boyle", "Joseph Carlson"],
            },
            "NVDA": {
                "symbol": "NVDA",
                "total_mentions": 3,
                "avg_sentiment": 2.0,
                "avg_confidence": 0.9,
                "themes": ["AI infrastructure"],
                "notable_quotes": ["NVDA dominates..."],
                "channels": ["Joseph Carlson"],
            },
        },
        "theses": [
            {
                "ticker": "AAPL",
                "direction": "bullish",
                "thesis": "Apple AI play undervalued relative to peers",
                "confidence": 0.85,
                "source": "Patrick Boyle",
                "themes": ["AI", "services growth"],
            },
        ],
        "macro_signals": ["rate cut expectations building"],
        "themes": ["AI infrastructure spending"],
        "market_mood": "cautiously bullish",
    }


# ============================================================================
# TestYouTubeFetcher
# ============================================================================


class TestYouTubeFetcher:
    """Tests for src/youtube_ear/youtube_fetcher.py."""

    def test_parse_duration_full(self):
        """PT1H2M3S should parse to 3723 seconds."""
        from src.youtube_ear.youtube_fetcher import _parse_duration

        assert _parse_duration("PT1H2M3S") == 3723

    def test_parse_duration_minutes_only(self):
        """PT15M33S should parse to 933 seconds."""
        from src.youtube_ear.youtube_fetcher import _parse_duration

        assert _parse_duration("PT15M33S") == 933

    def test_parse_duration_seconds_only(self):
        """PT45S should parse to 45 seconds."""
        from src.youtube_ear.youtube_fetcher import _parse_duration

        assert _parse_duration("PT45S") == 45

    def test_parse_duration_invalid(self):
        """Empty or invalid duration should return 0."""
        from src.youtube_ear.youtube_fetcher import _parse_duration

        assert _parse_duration("") == 0
        assert _parse_duration(None) == 0
        assert _parse_duration("INVALID") == 0

    @patch("src.youtube_ear.youtube_fetcher._get_transcript")
    @patch("src.youtube_ear.youtube_fetcher._build_youtube_service")
    @patch("src.youtube_ear.youtube_fetcher.load_config")
    @patch.dict(os.environ, {"YOUTUBE_API_KEY": "test-key-123"})
    def test_fetch_videos_basic(self, mock_config, mock_build, mock_transcript):
        """fetch_videos should return videos with the correct schema."""
        mock_config.return_value = SAMPLE_CONFIG
        mock_transcript.return_value = "This is a transcript about AAPL."

        now = datetime.now(timezone.utc)
        published_at = now.isoformat().replace("+00:00", "Z")

        # Mock YouTube search API
        mock_service = MagicMock()
        mock_build.return_value = mock_service

        mock_service.search().list().execute.return_value = {
            "items": [
                {
                    "id": {"videoId": "abc123"},
                    "snippet": {
                        "title": "AAPL Analysis",
                        "publishedAt": published_at,
                    },
                }
            ]
        }
        mock_service.videos().list().execute.return_value = {
            "items": [
                {
                    "id": "abc123",
                    "statistics": {"viewCount": "50000", "commentCount": "200"},
                    "contentDetails": {"duration": "PT15M33S"},
                }
            ]
        }

        from src.youtube_ear.youtube_fetcher import fetch_videos

        videos = fetch_videos()

        assert len(videos) >= 1
        v = videos[0]
        assert v["title"] == "AAPL Analysis"
        assert v["source_platform"] == "youtube"
        assert v["score"] == 50000
        assert v["duration_seconds"] == 933

    @patch("src.youtube_ear.youtube_fetcher.load_config")
    @patch.dict(os.environ, {}, clear=True)
    def test_no_api_key(self, mock_config):
        """Missing YOUTUBE_API_KEY should return empty list."""
        mock_config.return_value = SAMPLE_CONFIG
        os.environ.pop("YOUTUBE_API_KEY", None)

        from src.youtube_ear.youtube_fetcher import fetch_videos

        result = fetch_videos()
        assert result == []

    @patch("src.youtube_ear.youtube_fetcher._get_transcript")
    @patch("src.youtube_ear.youtube_fetcher._build_youtube_service")
    @patch("src.youtube_ear.youtube_fetcher.load_config")
    @patch.dict(os.environ, {"YOUTUBE_API_KEY": "test-key-123"})
    def test_min_view_filter(self, mock_config, mock_build, mock_transcript):
        """Videos with views below min_view_count should be filtered out."""
        mock_config.return_value = SAMPLE_CONFIG
        mock_transcript.return_value = "transcript text"

        now = datetime.now(timezone.utc)
        published_at = now.isoformat().replace("+00:00", "Z")

        mock_service = MagicMock()
        mock_build.return_value = mock_service

        mock_service.search().list().execute.return_value = {
            "items": [
                {
                    "id": {"videoId": "low_views_vid"},
                    "snippet": {"title": "Low Views", "publishedAt": published_at},
                }
            ]
        }
        mock_service.videos().list().execute.return_value = {
            "items": [
                {
                    "id": "low_views_vid",
                    "statistics": {"viewCount": "500", "commentCount": "10"},
                    "contentDetails": {"duration": "PT10M"},
                }
            ]
        }

        from src.youtube_ear.youtube_fetcher import fetch_videos

        videos = fetch_videos()
        assert len(videos) == 0

    @patch("src.youtube_ear.youtube_fetcher._get_transcript")
    @patch("src.youtube_ear.youtube_fetcher._build_youtube_service")
    @patch("src.youtube_ear.youtube_fetcher.load_config")
    @patch.dict(os.environ, {"YOUTUBE_API_KEY": "test-key-123"})
    def test_no_transcript(self, mock_config, mock_build, mock_transcript):
        """Videos with no transcript available should be skipped."""
        mock_config.return_value = SAMPLE_CONFIG
        mock_transcript.return_value = None  # No transcript

        now = datetime.now(timezone.utc)
        published_at = now.isoformat().replace("+00:00", "Z")

        mock_service = MagicMock()
        mock_build.return_value = mock_service

        mock_service.search().list().execute.return_value = {
            "items": [
                {
                    "id": {"videoId": "no_trans_vid"},
                    "snippet": {"title": "No Transcript", "publishedAt": published_at},
                }
            ]
        }
        mock_service.videos().list().execute.return_value = {
            "items": [
                {
                    "id": "no_trans_vid",
                    "statistics": {"viewCount": "5000", "commentCount": "50"},
                    "contentDetails": {"duration": "PT12M"},
                }
            ]
        }

        from src.youtube_ear.youtube_fetcher import fetch_videos

        videos = fetch_videos()
        assert len(videos) == 0

    def test_transcript_truncation(self):
        """Long transcripts should be capped at max_chars."""
        from src.youtube_ear.youtube_fetcher import _get_transcript

        long_text = "word " * 5000  # ~25000 chars

        with patch("youtube_transcript_api.YouTubeTranscriptApi") as mock_api:
            mock_api.get_transcript.return_value = [{"text": long_text}]
            result = _get_transcript("test_vid", max_chars=6000)

        assert result is not None
        assert len(result) <= 6000

    @patch("src.youtube_ear.youtube_fetcher._get_transcript")
    @patch("src.youtube_ear.youtube_fetcher._build_youtube_service")
    @patch("src.youtube_ear.youtube_fetcher.load_config")
    @patch.dict(os.environ, {"YOUTUBE_API_KEY": "test-key-123"})
    def test_age_filtering(self, mock_config, mock_build, mock_transcript):
        """Videos older than max_video_age_hours should be filtered out."""
        mock_config.return_value = SAMPLE_CONFIG
        mock_transcript.return_value = "Some transcript"

        # Published 72 hours ago (beyond 48h threshold)
        old_time = datetime.fromtimestamp(
            time.time() - 72 * 3600, tz=timezone.utc
        )
        published_at = old_time.isoformat().replace("+00:00", "Z")

        mock_service = MagicMock()
        mock_build.return_value = mock_service

        mock_service.search().list().execute.return_value = {
            "items": [
                {
                    "id": {"videoId": "old_vid"},
                    "snippet": {"title": "Old Video", "publishedAt": published_at},
                }
            ]
        }
        # Videos list should not even be called since all are filtered by age
        mock_service.videos().list().execute.return_value = {"items": []}

        from src.youtube_ear.youtube_fetcher import fetch_videos

        videos = fetch_videos()
        assert len(videos) == 0

    @patch("src.youtube_ear.youtube_fetcher._get_transcript")
    @patch("src.youtube_ear.youtube_fetcher._build_youtube_service")
    @patch("src.youtube_ear.youtube_fetcher.load_config")
    @patch.dict(os.environ, {"YOUTUBE_API_KEY": "test-key-123"})
    def test_schema_fields(self, mock_config, mock_build, mock_transcript):
        """Every returned video must contain all required schema fields."""
        mock_config.return_value = SAMPLE_CONFIG
        mock_transcript.return_value = "Transcript text here"

        now = datetime.now(timezone.utc)
        published_at = now.isoformat().replace("+00:00", "Z")

        mock_service = MagicMock()
        mock_build.return_value = mock_service

        mock_service.search().list().execute.return_value = {
            "items": [
                {
                    "id": {"videoId": "schema_vid"},
                    "snippet": {"title": "Schema Test", "publishedAt": published_at},
                }
            ]
        }
        mock_service.videos().list().execute.return_value = {
            "items": [
                {
                    "id": "schema_vid",
                    "statistics": {"viewCount": "10000", "commentCount": "50"},
                    "contentDetails": {"duration": "PT20M"},
                }
            ]
        }

        from src.youtube_ear.youtube_fetcher import fetch_videos

        videos = fetch_videos()
        assert len(videos) >= 1

        required_fields = {
            "title", "selftext", "score", "num_comments", "subreddit",
            "url", "created_utc", "author", "source_platform", "duration_seconds",
        }
        for field in required_fields:
            assert field in videos[0], f"Missing field: {field}"


# ============================================================================
# TestYouTubeAnalyzer
# ============================================================================


class TestYouTubeAnalyzer:
    """Tests for src/youtube_ear/analyzer.py."""

    @patch("src.youtube_ear.analyzer.anthropic")
    @patch("src.youtube_ear.analyzer.get_all_tickers")
    @patch("src.youtube_ear.analyzer.check_budget")
    @patch("src.youtube_ear.analyzer.record_usage")
    def test_analyze_videos_basic(self, mock_record, mock_budget, mock_tickers, mock_anthropic):
        """analyze_videos should return correct aggregated structure."""
        mock_budget.return_value = (True, 1.0, 20.0)
        mock_tickers.return_value = ["AAPL", "NVDA", "TSLA"]

        mock_client = MagicMock()
        mock_anthropic.Anthropic.return_value = mock_client

        # Build mock response
        mock_response = MagicMock()
        mock_response.usage.input_tokens = 1000
        mock_response.usage.output_tokens = 500
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = json.dumps(SAMPLE_LLM_JSON)
        mock_response.content = [text_block]
        mock_client.messages.create.return_value = mock_response

        from src.youtube_ear.analyzer import analyze_videos

        result = analyze_videos(SAMPLE_VIDEOS)

        assert "tickers" in result
        assert "theses" in result
        assert "macro_signals" in result
        assert "themes" in result
        assert "market_mood" in result
        assert isinstance(result["tickers"], dict)
        assert "AAPL" in result["tickers"]

    def test_ticker_validation(self):
        """False positive tickers should be rejected; valid tickers accepted."""
        from src.youtube_ear.analyzer import _validate_ticker_symbol

        # Valid tickers
        assert _validate_ticker_symbol("AAPL") == "AAPL"
        assert _validate_ticker_symbol("NVDA") == "NVDA"
        assert _validate_ticker_symbol("BRK.B") == "BRK.B"
        assert _validate_ticker_symbol("tsla") == "TSLA"

        # False positives
        assert _validate_ticker_symbol("IT") is None
        assert _validate_ticker_symbol("CEO") is None
        assert _validate_ticker_symbol("ETF") is None
        assert _validate_ticker_symbol("YOLO") is None
        assert _validate_ticker_symbol("GDP") is None
        assert _validate_ticker_symbol("AI") is None
        assert _validate_ticker_symbol("FED") is None

        # Invalid inputs
        assert _validate_ticker_symbol("") is None
        assert _validate_ticker_symbol(None) is None

    def test_parse_llm_response_clean_json(self):
        """Clean JSON should be parsed correctly."""
        from src.youtube_ear.analyzer import _parse_llm_response

        result = _parse_llm_response(json.dumps(SAMPLE_LLM_JSON))
        assert result["market_mood"] == "cautiously bullish"
        assert len(result["tickers"]) == 2

    def test_parse_llm_response_markdown_fences(self):
        """JSON wrapped in markdown code fences should be handled."""
        from src.youtube_ear.analyzer import _parse_llm_response

        fenced = "```json\n" + json.dumps(SAMPLE_LLM_JSON) + "\n```"
        result = _parse_llm_response(fenced)
        assert result["market_mood"] == "cautiously bullish"
        assert len(result["tickers"]) == 2

    def test_parse_llm_response_invalid_json(self):
        """Invalid JSON should return default empty structure."""
        from src.youtube_ear.analyzer import _parse_llm_response

        result = _parse_llm_response("this is not json {{{")
        assert result["tickers"] == []
        assert result["theses"] == []
        assert result["market_mood"] == "unknown"

    @patch("src.youtube_ear.analyzer.anthropic")
    @patch("src.youtube_ear.analyzer.get_all_tickers")
    @patch("src.youtube_ear.analyzer.check_budget")
    @patch("src.youtube_ear.analyzer.record_usage")
    def test_batch_processing(self, mock_record, mock_budget, mock_tickers, mock_anthropic):
        """10 videos should produce 3 batches (4+4+2)."""
        mock_budget.return_value = (True, 1.0, 20.0)
        mock_tickers.return_value = ["AAPL"]

        mock_client = MagicMock()
        mock_anthropic.Anthropic.return_value = mock_client

        mock_response = MagicMock()
        mock_response.usage.input_tokens = 500
        mock_response.usage.output_tokens = 200
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = json.dumps({
            "tickers": [],
            "theses": [],
            "macro_signals": [],
            "overall_themes": [],
            "market_mood": "neutral",
        })
        mock_response.content = [text_block]
        mock_client.messages.create.return_value = mock_response

        videos = [_make_video(video_id=f"v{i}") for i in range(10)]

        from src.youtube_ear.analyzer import analyze_videos

        analyze_videos(videos)

        # BATCH_SIZE is 4, so 10 videos -> ceil(10/4) = 3 calls
        assert mock_client.messages.create.call_count == 3

    @patch("src.youtube_ear.analyzer.anthropic")
    @patch("src.youtube_ear.analyzer.get_all_tickers")
    @patch("src.youtube_ear.analyzer.check_budget")
    def test_budget_exceeded(self, mock_budget, mock_tickers, mock_anthropic):
        """When budget is exceeded, should return empty results."""
        mock_budget.return_value = (False, 25.0, 20.0)
        mock_tickers.return_value = []

        mock_client = MagicMock()
        mock_anthropic.Anthropic.return_value = mock_client

        from src.youtube_ear.analyzer import analyze_videos

        result = analyze_videos(SAMPLE_VIDEOS)

        # Budget exceeded means no API calls
        mock_client.messages.create.assert_not_called()
        assert result["market_mood"] == "unknown"

    def test_empty_videos(self):
        """Empty videos list should return default structure."""
        from src.youtube_ear.analyzer import analyze_videos

        result = analyze_videos([])
        assert result["tickers"] == {}
        assert result["theses"] == []
        assert result["market_mood"] == "unknown"

    def test_aggregate_sentiment_weighted(self):
        """Sentiment should be weighted by mention count."""
        from src.youtube_ear.analyzer import _aggregate_results

        batch_results = [
            {
                "tickers": [
                    {
                        "symbol": "AAPL",
                        "mentions": 3,
                        "sentiment": 2.0,
                        "confidence": 0.9,
                        "themes": [],
                        "notable_quote": "",
                        "source_channels": ["Ch1"],
                    }
                ],
                "theses": [],
                "macro_signals": [],
                "overall_themes": [],
                "market_mood": "bullish",
            },
            {
                "tickers": [
                    {
                        "symbol": "AAPL",
                        "mentions": 1,
                        "sentiment": -1.0,
                        "confidence": 0.5,
                        "themes": [],
                        "notable_quote": "",
                        "source_channels": ["Ch2"],
                    }
                ],
                "theses": [],
                "macro_signals": [],
                "overall_themes": [],
                "market_mood": "bearish",
            },
        ]
        result = _aggregate_results(batch_results)

        # total_mentions = 3 + 1 = 4
        # sentiment_sum = (2.0 * 3) + (-1.0 * 1) = 5.0
        # avg_sentiment = 5.0 / 4 = 1.25
        assert result["tickers"]["AAPL"]["total_mentions"] == 4
        assert result["tickers"]["AAPL"]["avg_sentiment"] == 1.25

    def test_aggregate_channels_merged(self):
        """Channels from multiple batches should be merged and deduplicated."""
        from src.youtube_ear.analyzer import _aggregate_results

        batch_results = [
            {
                "tickers": [
                    {
                        "symbol": "NVDA",
                        "mentions": 2,
                        "sentiment": 1.0,
                        "confidence": 0.8,
                        "themes": ["AI"],
                        "notable_quote": "",
                        "source_channels": ["Patrick Boyle", "Joseph Carlson"],
                    }
                ],
                "theses": [],
                "macro_signals": [],
                "overall_themes": [],
                "market_mood": "bullish",
            },
            {
                "tickers": [
                    {
                        "symbol": "NVDA",
                        "mentions": 1,
                        "sentiment": 1.5,
                        "confidence": 0.7,
                        "themes": ["datacenter"],
                        "notable_quote": "",
                        "source_channels": ["Joseph Carlson", "Graham Stephan"],
                    }
                ],
                "theses": [],
                "macro_signals": [],
                "overall_themes": [],
                "market_mood": "bullish",
            },
        ]
        result = _aggregate_results(batch_results)

        channels = result["tickers"]["NVDA"]["channels"]
        # Should be deduplicated and sorted
        assert "Patrick Boyle" in channels
        assert "Joseph Carlson" in channels
        assert "Graham Stephan" in channels
        assert len(channels) == 3


# ============================================================================
# TestYouTubeTracker
# ============================================================================


class TestYouTubeTracker:
    """Tests for src/youtube_ear/tracker.py."""

    @pytest.fixture(autouse=True)
    def _setup_db(self, tmp_path, monkeypatch):
        """Point tracker DB_PATH to a temp directory for each test."""
        db_file = tmp_path / "youtube_tracker.db"
        monkeypatch.setattr("src.youtube_ear.tracker.DB_PATH", db_file)

    @patch("src.youtube_ear.tracker.publish")
    def test_record_scan(self, mock_publish):
        """record_scan should insert mention data into the DB."""
        from src.youtube_ear.tracker import record_scan, _get_db

        analysis = _make_analysis()
        record_scan(analysis)

        conn = _get_db()
        rows = conn.execute("SELECT ticker, mention_count FROM mention_history").fetchall()
        conn.close()

        tickers_in_db = {r[0] for r in rows}
        assert "AAPL" in tickers_in_db
        assert "NVDA" in tickers_in_db

    @patch("src.youtube_ear.tracker.publish")
    def test_record_scan_upsert(self, mock_publish):
        """Running record_scan twice on the same day should aggregate counts."""
        from src.youtube_ear.tracker import record_scan, _get_db

        analysis = _make_analysis()
        record_scan(analysis)
        record_scan(analysis)

        conn = _get_db()
        row = conn.execute(
            "SELECT mention_count FROM mention_history WHERE ticker = 'AAPL'"
        ).fetchone()
        conn.close()

        # 5 + 5 = 10 (upserted)
        assert row[0] == 10

    @patch("src.youtube_ear.tracker.publish")
    def test_record_theses(self, mock_publish):
        """record_theses should insert theses into the DB."""
        from src.youtube_ear.tracker import record_theses, _get_db

        analysis = _make_analysis()
        record_theses(analysis)

        conn = _get_db()
        rows = conn.execute("SELECT ticker, direction, thesis FROM theses").fetchall()
        conn.close()

        assert len(rows) == 1
        assert rows[0][0] == "AAPL"
        assert rows[0][1] == "bullish"

    @patch("src.youtube_ear.tracker.publish")
    def test_detect_view_spikes(self, mock_publish):
        """Videos with >3x avg views should be flagged as spikes."""
        from src.youtube_ear.tracker import detect_view_spikes, _get_db

        # Seed historical average: 10000 views
        conn = _get_db()
        yesterday = (date.today().isoformat())
        from datetime import timedelta

        past_date = (date.today() - timedelta(days=3)).isoformat()
        conn.execute(
            "INSERT INTO channel_view_history (channel_name, date, avg_views, video_count) "
            "VALUES (?, ?, ?, ?)",
            ("Patrick Boyle", past_date, 10000, 2),
        )
        conn.commit()
        conn.close()

        # Video with 50000 views (5x the 10000 avg)
        videos = [_make_video(channel="Patrick Boyle", views=50000, video_id="spike")]
        analysis = _make_analysis()

        spikes = detect_view_spikes(analysis, videos)

        assert len(spikes) == 1
        assert spikes[0]["channel"] == "Patrick Boyle"
        assert spikes[0]["multiplier"] >= 3.0
        # Should have published narrative_amplification signal
        mock_publish.assert_called()
        call_args = mock_publish.call_args
        assert call_args[1]["signal_type"] == "narrative_amplification"

    @patch("src.youtube_ear.tracker.publish")
    def test_no_view_spikes(self, mock_publish):
        """Videos with normal views should not be flagged."""
        from src.youtube_ear.tracker import detect_view_spikes, _get_db

        # Seed historical average: 50000 views
        conn = _get_db()
        from datetime import timedelta

        past_date = (date.today() - timedelta(days=3)).isoformat()
        conn.execute(
            "INSERT INTO channel_view_history (channel_name, date, avg_views, video_count) "
            "VALUES (?, ?, ?, ?)",
            ("Patrick Boyle", past_date, 50000, 5),
        )
        conn.commit()
        conn.close()

        # Video with 60000 views (1.2x avg -- not a spike)
        videos = [_make_video(channel="Patrick Boyle", views=60000, video_id="normal")]
        analysis = _make_analysis()

        spikes = detect_view_spikes(analysis, videos)
        assert len(spikes) == 0

    @patch("src.youtube_ear.tracker.publish")
    def test_multi_channel_convergence(self, mock_publish):
        """Ticker mentioned in 2+ channels should be flagged."""
        from src.youtube_ear.tracker import detect_multi_channel_convergence

        analysis = _make_analysis()
        # AAPL has channels ["Patrick Boyle", "Joseph Carlson"] -> 2 channels
        convergences = detect_multi_channel_convergence(analysis)

        assert len(convergences) >= 1
        conv_tickers = {c["ticker"] for c in convergences}
        assert "AAPL" in conv_tickers

        # NVDA only has 1 channel, so should NOT be flagged
        assert "NVDA" not in conv_tickers

        # Should publish expert_analysis signal
        mock_publish.assert_called()

    @patch("src.youtube_ear.tracker.publish")
    def test_no_convergence(self, mock_publish):
        """Tickers in only 1 channel each should not be flagged."""
        from src.youtube_ear.tracker import detect_multi_channel_convergence

        analysis = {
            "tickers": {
                "AAPL": {
                    "symbol": "AAPL",
                    "total_mentions": 3,
                    "avg_sentiment": 1.0,
                    "avg_confidence": 0.8,
                    "themes": [],
                    "notable_quotes": [],
                    "channels": ["Patrick Boyle"],  # only 1 channel
                },
                "NVDA": {
                    "symbol": "NVDA",
                    "total_mentions": 2,
                    "avg_sentiment": 1.5,
                    "avg_confidence": 0.9,
                    "themes": [],
                    "notable_quotes": [],
                    "channels": ["Joseph Carlson"],  # only 1 channel
                },
            }
        }

        convergences = detect_multi_channel_convergence(analysis)
        assert len(convergences) == 0

    @patch("src.shared.narrative_tracker.record_narrative")
    @patch("src.youtube_ear.tracker.publish")
    def test_publish_signals(self, mock_publish, mock_record_narrative):
        """High confidence theses (>=0.6) should be published."""
        from src.youtube_ear.tracker import publish_signals

        analysis = _make_analysis()
        # The thesis has confidence 0.85 -> should be published
        published = publish_signals(analysis)

        assert len(published) == 1
        assert published[0]["ticker"] == "AAPL"
        assert published[0]["confidence"] == 0.85
        mock_publish.assert_called()

    @patch("src.shared.narrative_tracker.record_narrative")
    @patch("src.youtube_ear.tracker.publish")
    def test_low_confidence_filtered(self, mock_publish, mock_record_narrative):
        """Theses with confidence < 0.6 should not be published."""
        from src.youtube_ear.tracker import publish_signals

        analysis = {
            "theses": [
                {
                    "ticker": "TSLA",
                    "direction": "bearish",
                    "thesis": "Tesla facing competition",
                    "confidence": 0.4,
                    "source": "Some Channel",
                    "themes": ["EV competition"],
                },
            ],
        }
        published = publish_signals(analysis)
        assert len(published) == 0

    @patch("src.shared.narrative_tracker.record_narrative")
    @patch("src.youtube_ear.tracker.publish")
    def test_narrative_tracker_called(self, mock_publish, mock_record_narrative):
        """record_narrative should be called for qualifying theses."""
        from src.youtube_ear.tracker import publish_signals

        analysis = _make_analysis()
        publish_signals(analysis)

        # The thesis has confidence 0.85 >= 0.6 so record_narrative should be called
        mock_record_narrative.assert_called_once()
        call_args = mock_record_narrative.call_args
        # record_narrative uses keyword args
        assert call_args.kwargs.get("source_platform") == "youtube"


# ============================================================================
# TestYouTubeFormatter
# ============================================================================


class TestYouTubeFormatter:
    """Tests for src/youtube_ear/formatter.py."""

    def test_format_output_basic(self):
        """All sections should be present in output."""
        from src.youtube_ear.formatter import format_output

        analysis = _make_analysis()
        view_spikes = [
            {
                "channel": "Patrick Boyle",
                "title": "Spike Video",
                "views": 500000,
                "avg_views": 50000,
                "multiplier": 10.0,
                "url": "https://youtube.com/watch?v=spike",
            }
        ]
        convergences = [
            {"ticker": "AAPL", "channel_count": 2, "channels": ["Patrick Boyle", "Joseph Carlson"]},
        ]
        videos = SAMPLE_VIDEOS

        output = format_output(analysis, view_spikes, convergences, videos)

        assert "YOUTUBE EAR" in output
        assert "Top Discussed" in output
        assert "AAPL" in output
        assert "Expert Theses" in output
        assert "Macro Signals" in output
        assert "View Spikes" in output
        assert "Multi-Channel Convergence" in output
        assert "Themes" in output

    def test_sentiment_indicators(self):
        """Sentiment values should map to correct color indicators."""
        from src.youtube_ear.formatter import _sentiment_indicator

        # Bullish -> green circle
        green = _sentiment_indicator(1.5)
        assert "\U0001f7e2" in green

        # Bearish -> red circle
        red = _sentiment_indicator(-1.5)
        assert "\U0001f534" in red

        # Neutral -> white circle
        white = _sentiment_indicator(0.0)
        assert "\u26aa" in white

    def test_view_spike_formatting(self):
        """View spike section should render spike data."""
        from src.youtube_ear.formatter import format_output

        analysis = {"tickers": {}, "theses": [], "macro_signals": [], "themes": [], "market_mood": "unknown"}
        spikes = [
            {
                "channel": "Test Channel",
                "title": "Viral Video",
                "views": 1_000_000,
                "avg_views": 100_000,
                "multiplier": 10.0,
                "url": "https://youtube.com",
            }
        ]

        output = format_output(analysis, spikes, [], [])
        assert "View Spikes" in output
        assert "10.0x avg" in output

    def test_convergence_formatting(self):
        """Multi-channel convergence section should render correctly."""
        from src.youtube_ear.formatter import format_output

        analysis = {"tickers": {}, "theses": [], "macro_signals": [], "themes": [], "market_mood": "unknown"}
        convergences = [
            {"ticker": "NVDA", "channel_count": 3, "channels": ["Ch1", "Ch2", "Ch3"]},
        ]

        output = format_output(analysis, [], convergences, [])
        assert "Multi-Channel Convergence" in output
        assert "NVDA" in output
        assert "3 channels" in output

    def test_char_limit(self):
        """Output exceeding 2000 chars should be truncated."""
        from src.youtube_ear.formatter import format_output, MAX_OUTPUT_CHARS

        # Create analysis with long channel names and themes to exceed 2000 chars
        long_channel = "A Very Long Channel Name That Adds Characters " * 3
        big_tickers = {}
        for i in range(50):
            sym = f"T{i:03d}"
            big_tickers[sym] = {
                "symbol": sym,
                "total_mentions": 10 + i,  # varied to avoid dedup in sorted
                "avg_sentiment": 1.0,
                "avg_confidence": 0.8,
                "themes": [f"long theme description number {j} for ticker {sym}" for j in range(5)],
                "notable_quotes": ["A very long notable quote that pads the output significantly " * 3],
                "channels": [long_channel, f"Another Long Channel {i}"],
            }
        long_thesis = "This is an extremely detailed investment thesis with lots of supporting arguments and analysis " * 5
        analysis = {
            "tickers": big_tickers,
            "theses": [{"ticker": f"T{i:03d}", "direction": "bullish",
                        "thesis": long_thesis, "confidence": 0.9,
                        "source": "A Very Detailed Source Name"} for i in range(20)],
            "macro_signals": [f"A long macro signal description about economic indicator number {i}" for i in range(10)],
            "themes": [f"A comprehensive theme about market trend number {i} and its implications" for i in range(10)],
            "market_mood": "bullish",
        }
        view_spikes = [
            {"channel": long_channel, "title": "A spike video with a very long title " * 3,
             "views": 500000, "avg_views": 50000, "multiplier": 10.0,
             "url": "https://youtube.com/watch?v=spike"} for _ in range(5)
        ]
        convergences = [
            {"ticker": f"T{i:03d}", "channel_count": 5,
             "channels": [long_channel] + [f"Channel {j}" for j in range(5)]}
            for i in range(5)
        ]

        output = format_output(analysis, view_spikes, convergences, SAMPLE_VIDEOS)
        # The formatter caps at MAX_OUTPUT_CHARS plus the truncation line
        assert len(output) <= MAX_OUTPUT_CHARS + 100
        assert "truncated" in output

    def test_empty_data(self):
        """Empty analysis should be handled gracefully."""
        from src.youtube_ear.formatter import format_output

        analysis = {
            "tickers": {},
            "theses": [],
            "macro_signals": [],
            "themes": [],
            "market_mood": "unknown",
        }

        output = format_output(analysis, [], [], [])
        assert "YOUTUBE EAR" in output
        assert isinstance(output, str)


# ============================================================================
# TestYouTubePipeline
# ============================================================================


class TestYouTubePipeline:
    """Tests for src/youtube_ear/main.py (async pipeline orchestrator)."""

    @patch("src.youtube_ear.main.asyncio")
    def test_full_pipeline_success(self, mock_asyncio):
        """Full pipeline with all steps succeeding should return correct structure."""
        analysis = _make_analysis()
        videos = SAMPLE_VIDEOS

        # Make asyncio.to_thread run synchronously
        async def fake_to_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        mock_asyncio.to_thread = fake_to_thread

        with patch("src.youtube_ear.youtube_fetcher.fetch_videos", return_value=videos), \
             patch("src.youtube_ear.analyzer.analyze_videos", return_value=analysis), \
             patch("src.youtube_ear.tracker.record_scan"), \
             patch("src.youtube_ear.tracker.record_theses"), \
             patch("src.youtube_ear.tracker.detect_view_spikes", return_value=[]), \
             patch("src.youtube_ear.tracker.detect_multi_channel_convergence", return_value=[]), \
             patch("src.youtube_ear.tracker.publish_signals", return_value=[]), \
             patch("src.youtube_ear.formatter.format_output", return_value="<b>test</b>"):

            import asyncio as real_asyncio
            from src.youtube_ear.main import run

            result = real_asyncio.get_event_loop().run_until_complete(run())

        assert "formatted" in result
        assert "signals" in result
        assert "stats" in result
        assert "analysis" in result
        assert result["stats"]["videos_fetched"] == 2

    @patch("src.youtube_ear.main.asyncio")
    def test_pipeline_fetch_failure(self, mock_asyncio):
        """Pipeline should handle fetch failure gracefully."""

        async def fake_to_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        mock_asyncio.to_thread = fake_to_thread

        def failing_fetch():
            raise ConnectionError("API down")

        with patch("src.youtube_ear.youtube_fetcher.fetch_videos", side_effect=failing_fetch), \
             patch("src.youtube_ear.tracker.record_scan"), \
             patch("src.youtube_ear.tracker.record_theses"), \
             patch("src.youtube_ear.tracker.detect_view_spikes", return_value=[]), \
             patch("src.youtube_ear.tracker.detect_multi_channel_convergence", return_value=[]), \
             patch("src.youtube_ear.tracker.publish_signals", return_value=[]), \
             patch("src.youtube_ear.formatter.format_output", return_value="<b>error</b>"):

            import asyncio as real_asyncio
            from src.youtube_ear.main import run

            result = real_asyncio.get_event_loop().run_until_complete(run())

        assert result["stats"]["videos_fetched"] == 0
        assert "fetch_error" in result["stats"]

    @patch("src.youtube_ear.main.asyncio")
    def test_pipeline_no_videos(self, mock_asyncio):
        """Pipeline with no fetched videos should show zero stats."""

        async def fake_to_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        mock_asyncio.to_thread = fake_to_thread

        with patch("src.youtube_ear.youtube_fetcher.fetch_videos", return_value=[]), \
             patch("src.youtube_ear.tracker.record_scan"), \
             patch("src.youtube_ear.tracker.record_theses"), \
             patch("src.youtube_ear.tracker.detect_view_spikes", return_value=[]), \
             patch("src.youtube_ear.tracker.detect_multi_channel_convergence", return_value=[]), \
             patch("src.youtube_ear.tracker.publish_signals", return_value=[]), \
             patch("src.youtube_ear.formatter.format_output", return_value="<b>no data</b>"):

            import asyncio as real_asyncio
            from src.youtube_ear.main import run

            result = real_asyncio.get_event_loop().run_until_complete(run())

        assert result["stats"]["videos_fetched"] == 0
        assert result["stats"]["tickers_found"] == 0
        assert result["stats"]["theses_found"] == 0
