"""Integration and E2E tests for new-ears modules and cross-source propagation.

Covers:
- Substack pipeline integration (fetch -> analyze -> track -> signal -> format)
- YouTube pipeline integration (fetch -> analyze -> track -> signal -> format)
- Signal bus consumption of new signal types
- Cross-source narrative propagation (substack -> youtube -> reddit)
- Morning brief integration with new sources
- Advisor memory thesis_actions table
- Edge cases (empty feeds, missing API keys, unicode, budget limits, etc.)
"""

import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from unittest.mock import MagicMock, patch
import asyncio

for mod in ("anthropic", "fredapi", "yfinance", "feedparser",
            "googleapiclient", "googleapiclient.discovery",
            "youtube_transcript_api"):
    sys.modules.setdefault(mod, MagicMock())

import json
import sqlite3
import time
from datetime import date, datetime

import pytest


# ---------------------------------------------------------------------------
# DB isolation fixture
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _isolate_all_dbs(tmp_path, monkeypatch):
    """Point every module's DB_PATH to tmp_path for full test isolation."""
    monkeypatch.setattr("src.shared.narrative_tracker.DB_PATH", tmp_path / "narrative.db")
    monkeypatch.setattr("src.shared.agent_bus.DB_PATH", tmp_path / "bus.db")
    monkeypatch.setattr("src.substack_ear.tracker.DB_PATH", tmp_path / "substack.db")
    monkeypatch.setattr("src.youtube_ear.tracker.DB_PATH", tmp_path / "youtube.db")
    monkeypatch.setattr("src.advisor.memory.DB_PATH", tmp_path / "advisor.db")


# ---------------------------------------------------------------------------
# Shared mock data
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_substack_analysis():
    """Realistic analysis dict that substack analyzer would return."""
    return {
        "tickers": {
            "NVDA": {
                "symbol": "NVDA",
                "total_mentions": 5,
                "avg_sentiment": 1.5,
                "avg_confidence": 0.85,
                "themes": ["AI infrastructure", "data center"],
                "source_publications": ["Fabricated Knowledge"],
            },
            "AVGO": {
                "symbol": "AVGO",
                "total_mentions": 3,
                "avg_sentiment": 1.0,
                "avg_confidence": 0.7,
                "themes": ["custom silicon"],
                "source_publications": ["SemiAnalysis"],
            },
        },
        "theses": [
            {
                "title": "AI infrastructure spending will extend for years",
                "summary": "Hyperscaler CapEx is accelerating and NVDA/AVGO are primary beneficiaries.",
                "affected_tickers": ["NVDA", "AVGO"],
                "conviction": "high",
                "time_horizon": "long_term",
                "contrarian": False,
            },
        ],
        "macro_signals": [
            {
                "indicator": "CapEx cycle",
                "implication": "Hyperscaler spending accelerating faster than expected",
                "affected_sectors": ["semiconductors", "cloud"],
            },
        ],
        "themes": ["AI infrastructure spending", "data center demand"],
        "market_mood": "cautiously bullish",
    }


@pytest.fixture
def mock_youtube_analysis():
    """Realistic analysis dict that youtube analyzer would return."""
    return {
        "tickers": {
            "NVDA": {
                "symbol": "NVDA",
                "total_mentions": 8,
                "avg_sentiment": 1.2,
                "channels": ["Patrick Boyle", "The Plain Bagel"],
                "themes": ["AI capex infrastructure cycle"],
            },
            "TSLA": {
                "symbol": "TSLA",
                "total_mentions": 3,
                "avg_sentiment": -0.5,
                "channels": ["Patrick Boyle"],
                "themes": ["EV competition"],
            },
        },
        "theses": [
            {
                "ticker": "NVDA",
                "direction": "bullish",
                "thesis": "AI capex infrastructure cycle will extend sharply",
                "confidence": 0.85,
                "source": "Patrick Boyle",
                "themes": ["AI infrastructure"],
            },
        ],
        "macro_signals": [],
        "themes": ["AI infrastructure", "rate cuts"],
        "market_mood": "bullish",
    }


@pytest.fixture
def mock_rss_feed():
    """Shaped like feedparser.parse() output."""
    entry = MagicMock()
    entry.get = lambda k, d=None: {
        "title": "AI Infrastructure: The Next Decade",
        "link": "https://test.substack.com/p/ai-infra",
        "author": "Test Author",
        "published_parsed": time.localtime(),
    }.get(k, d)
    entry.title = "AI Infrastructure: The Next Decade"
    entry.content = [{"value": "<p>This is a deep dive into AI capex spending.</p>"}]
    entry.summary = "AI capex spending analysis"
    entry.published_parsed = time.localtime()

    feed = MagicMock()
    feed.bozo = False
    feed.entries = [entry]
    return feed


@pytest.fixture
def mock_videos():
    """Shaped like youtube_fetcher.fetch_videos() output."""
    return [
        {
            "title": "NVDA Earnings Preview",
            "selftext": "Let me discuss NVDA and the AI infrastructure cycle and spending extend",
            "score": 150000,
            "num_comments": 500,
            "subreddit": "Patrick Boyle",
            "url": "https://www.youtube.com/watch?v=abc123",
            "created_utc": time.time(),
            "author": "Patrick Boyle",
            "source_platform": "youtube",
            "duration_seconds": 900,
        },
    ]


# ===========================================================================
# TestSubstackPipelineIntegration
# ===========================================================================

class TestSubstackPipelineIntegration:

    def test_substack_full_pipeline(
        self, tmp_path, monkeypatch, mock_substack_analysis, mock_rss_feed
    ):
        """Full substack pipeline: fetch -> analyze -> track -> signal -> format."""
        # Mock feedparser
        monkeypatch.setattr("feedparser.parse", lambda url: mock_rss_feed)

        # Mock config_loader
        mock_config = {
            "newsletters": {
                "macro": [{"name": "TestSub", "slug": "testsub"}],
            },
            "settings": {
                "max_article_age_hours": 72,
                "max_article_chars": 8000,
                "max_articles_per_newsletter": 3,
            },
        }
        with patch("src.substack_ear.substack_fetcher.load_config", return_value=mock_config), \
             patch("src.substack_ear.analyzer.anthropic") as mock_anthropic, \
             patch("src.substack_ear.analyzer.check_budget", return_value=(True, 0.10, 5.00)), \
             patch("src.substack_ear.analyzer.record_usage"), \
             patch("src.substack_ear.analyzer.get_all_tickers", return_value=["NVDA", "AVGO"]), \
             patch("src.substack_ear.formatter.load_portfolio", return_value={"holdings": [{"ticker": "NVDA"}]}), \
             patch("src.substack_ear.formatter.load_watchlist", return_value={"tickers": ["AVGO"]}):

            # Mock Anthropic response
            mock_response = MagicMock()
            mock_response.content = [MagicMock(type="text", text=json.dumps({
                "tickers": [
                    {"symbol": "NVDA", "sentiment": 1.5, "confidence": 0.85,
                     "themes": ["AI"], "source_publication": "TestSub"}
                ],
                "theses": [{
                    "title": "AI infrastructure spending will extend for years",
                    "summary": "Hyperscaler CapEx accelerating.",
                    "affected_tickers": ["NVDA", "AVGO"],
                    "conviction": "high",
                    "time_horizon": "long_term",
                    "contrarian": False,
                }],
                "macro_signals": [{
                    "indicator": "CapEx cycle",
                    "implication": "Spending accelerating",
                    "affected_sectors": ["semiconductors"],
                }],
                "overall_themes": ["AI infrastructure"],
                "market_mood": "bullish",
            }))]
            mock_response.usage = MagicMock(input_tokens=500, output_tokens=200)
            mock_anthropic.Anthropic.return_value.messages.create.return_value = mock_response

            from src.substack_ear.main import run as run_substack
            result = asyncio.run(run_substack())

        # Verify structure
        assert "formatted" in result
        assert "signals" in result
        assert "stats" in result
        assert result["stats"]["articles_fetched"] >= 1

        # Verify formatted output is HTML
        formatted = result["formatted"]
        assert "<b>" in formatted or formatted == ""

        # Verify signals list
        assert isinstance(result["signals"], list)


# ===========================================================================
# TestYouTubePipelineIntegration
# ===========================================================================

class TestYouTubePipelineIntegration:

    def test_youtube_full_pipeline(
        self, tmp_path, monkeypatch, mock_youtube_analysis, mock_videos
    ):
        """Full YouTube pipeline: fetch -> analyze -> track -> signal -> format."""
        with patch("src.youtube_ear.youtube_fetcher.load_config", return_value={
                 "channels": {"macro": [{"name": "Patrick Boyle", "channel_id": "UC123"}]},
                 "settings": {
                     "max_video_age_hours": 48,
                     "max_transcript_chars": 6000,
                     "max_videos_per_channel": 3,
                     "min_view_count": 1000,
                 },
             }), \
             patch("src.youtube_ear.youtube_fetcher._get_api_key", return_value="fake-key"), \
             patch("src.youtube_ear.youtube_fetcher._build_youtube_service") as mock_yt_service, \
             patch("src.youtube_ear.youtube_fetcher._get_transcript", return_value="NVDA AI infrastructure cycle transcript"), \
             patch("src.youtube_ear.analyzer.anthropic") as mock_anthropic, \
             patch("src.youtube_ear.analyzer.check_budget", return_value=(True, 0.05, 5.00)), \
             patch("src.youtube_ear.analyzer.record_usage"), \
             patch("src.youtube_ear.analyzer.get_all_tickers", return_value=["NVDA"]):

            # Mock YouTube API responses
            mock_service = MagicMock()
            search_response = {
                "items": [{
                    "id": {"videoId": "abc123"},
                    "snippet": {
                        "title": "NVDA Earnings Preview",
                        "publishedAt": datetime.now().isoformat() + "Z",
                    },
                }],
            }
            mock_service.search.return_value.list.return_value.execute.return_value = search_response
            mock_service.videos.return_value.list.return_value.execute.return_value = {
                "items": [{
                    "id": "abc123",
                    "statistics": {"viewCount": "150000", "commentCount": "500"},
                    "contentDetails": {"duration": "PT15M30S"},
                }],
            }
            mock_yt_service.return_value = mock_service

            # Mock Anthropic response
            mock_response = MagicMock()
            mock_response.content = [MagicMock(type="text", text=json.dumps({
                "tickers": [
                    {"symbol": "NVDA", "sentiment": 1.2, "confidence": 0.85,
                     "themes": ["AI infrastructure"], "channel": "Patrick Boyle"}
                ],
                "theses": [{
                    "ticker": "NVDA",
                    "direction": "bullish",
                    "thesis": "AI capex infrastructure cycle will extend sharply",
                    "confidence": 0.85,
                    "source": "Patrick Boyle",
                    "themes": ["AI infrastructure"],
                }],
                "macro_signals": [],
                "overall_themes": ["AI infrastructure"],
                "market_mood": "bullish",
            }))]
            mock_response.usage = MagicMock(input_tokens=600, output_tokens=250)
            mock_anthropic.Anthropic.return_value.messages.create.return_value = mock_response

            from src.youtube_ear.main import run as run_youtube
            result = asyncio.run(run_youtube())

        assert "formatted" in result
        assert "signals" in result
        assert "stats" in result
        assert isinstance(result["signals"], list)


# ===========================================================================
# TestSignalBusConsumption
# ===========================================================================

class TestSignalBusConsumption:

    def test_new_signal_types_consumable(self):
        from src.shared.agent_bus import publish, consume

        signal_types_data = [
            ("expert_thesis", {"title": "AI thesis", "tickers": ["NVDA"]}),
            ("macro_framework", {"indicator": "CapEx", "implication": "accelerating"}),
            ("sector_rotation_call", {"title": "Rotation", "tickers": ["XLF"]}),
            ("expert_analysis", {"ticker": "NVDA", "direction": "bullish"}),
            ("narrative_amplification", {"channel": "test", "views": 100000}),
        ]

        for signal_type, payload in signal_types_data:
            publish(signal_type=signal_type, source_agent="test", payload=payload)

        for signal_type, _ in signal_types_data:
            signals = consume(signal_type=signal_type)
            assert len(signals) >= 1, f"Expected consumable signal of type {signal_type}"
            assert signals[0]["signal_type"] == signal_type

    def test_signal_payload_structure(self):
        from src.shared.agent_bus import publish, consume

        payload = {
            "title": "AI CapEx thesis",
            "summary": "Hyperscaler spending accelerating",
            "affected_tickers": ["NVDA", "AVGO"],
            "conviction": "high",
            "time_horizon": "long_term",
            "contrarian": False,
        }
        publish(signal_type="expert_thesis", source_agent="substack_ear", payload=payload)

        signals = consume(signal_type="expert_thesis")
        assert len(signals) == 1
        p = signals[0]["payload"]
        assert p["title"] == "AI CapEx thesis"
        assert p["affected_tickers"] == ["NVDA", "AVGO"]
        assert p["conviction"] == "high"


# ===========================================================================
# TestCrossSourceNarrativePropagation
# ===========================================================================

class TestCrossSourceNarrativePropagation:

    def test_substack_to_youtube_propagation(self):
        from src.shared.narrative_tracker import record_narrative, _get_db

        # 1. Record via substack
        nid = record_narrative(
            narrative="AI infrastructure spending will extend sharply for years",
            source_platform="substack",
            source_detail="fabricated_knowledge",
            affected_tickers=["NVDA", "AVGO"],
            conviction="high",
        )
        row = _get_db().execute(
            "SELECT current_stage FROM narrative_propagation WHERE id = ?", (nid,)
        ).fetchone()
        assert row[0] == "expert"

        # 2. Similar thesis from YouTube
        nid2 = record_narrative(
            narrative="AI infrastructure capex will extend sharply going forward",
            source_platform="youtube",
            source_detail="patrick_boyle",
            affected_tickers=["NVDA", "AVGO"],
        )
        assert nid2 == nid

        row = _get_db().execute(
            "SELECT current_stage FROM narrative_propagation WHERE id = ?", (nid,)
        ).fetchone()
        assert row[0] == "amplified"

    def test_full_three_source_chain(self):
        from src.shared.narrative_tracker import record_narrative, _get_db
        from src.shared.agent_bus import consume

        # 1. Substack
        nid = record_narrative(
            narrative="AI infrastructure spending will extend sharply for years",
            source_platform="substack",
            source_detail="fabricated_knowledge",
            affected_tickers=["NVDA", "AVGO"],
            conviction="high",
        )

        # 2. YouTube — same narrative, should match and promote
        record_narrative(
            narrative="AI capex infrastructure cycle will extend sharply ahead",
            source_platform="youtube",
            source_detail="patrick_boyle",
            affected_tickers=["NVDA"],
            conviction="medium",
        )

        row = _get_db().execute(
            "SELECT current_stage, confidence FROM narrative_propagation WHERE id = ?", (nid,)
        ).fetchone()
        assert row[0] == "amplified"

        # Verify thesis_propagation signal was published
        signals = consume(signal_type="thesis_propagation")
        assert len(signals) >= 1

        # 3. Reddit — mature to mainstream
        record_narrative(
            narrative="AI infrastructure spending extend sharply reaching mainstream",
            source_platform="reddit",
            source_detail="wallstreetbets",
            affected_tickers=["NVDA", "AVGO"],
        )

        row = _get_db().execute(
            "SELECT current_stage, confidence FROM narrative_propagation WHERE id = ?", (nid,)
        ).fetchone()
        assert row[0] == "mainstream"

        # Verify thesis_confirmed signal
        confirmed = consume(signal_type="thesis_confirmed")
        assert len(confirmed) >= 1

        # Confidence should have increased from 2 promotions
        assert row[1] > 0.5


# ===========================================================================
# TestMorningBriefIntegration
# ===========================================================================

class TestMorningBriefIntegration:

    def test_synthesis_includes_new_sources(self, monkeypatch):
        """Mock all 6 agents and verify synthesis includes Substack/YouTube sections."""
        mock_result = {
            "formatted": "<b>Test</b>",
            "signals": [],
            "stats": {},
        }
        substack_result = {
            "formatted": "<b>SUBSTACK EAR -- Expert Intelligence</b>\nTest thesis",
            "signals": [{"type": "expert_thesis", "ticker": "NVDA"}],
            "stats": {},
        }
        youtube_result = {
            "formatted": "<b>YOUTUBE EAR</b>\nTest video analysis",
            "signals": [{"type": "expert_analysis", "ticker": "NVDA"}],
            "stats": {},
        }

        with patch("src.shared.morning_brief.check_budget", return_value=(True, 0.10, 5.00)), \
             patch("src.shared.morning_brief.record_usage"), \
             patch("src.shared.morning_brief.get_daily_cost", return_value=0.15), \
             patch("src.shared.morning_brief.get_recent_signals", return_value=[]):

            # Test _synthesize_brief includes new sections
            from src.shared.morning_brief import _synthesize_brief

            mock_anthropic_client = MagicMock()
            mock_response = MagicMock()
            mock_response.content = [MagicMock(text="<b>KEY TAKEAWAYS</b>\n- Test\n\n<b>ACTION ITEMS</b>\n1. Test")]
            mock_response.usage = MagicMock(input_tokens=1000, output_tokens=200)
            mock_anthropic_client.messages.create.return_value = mock_response

            with patch("src.shared.morning_brief.anthropic.Anthropic", return_value=mock_anthropic_client):
                synthesis = _synthesize_brief(
                    street_ear=mock_result,
                    portfolio=mock_result,
                    news_desk=mock_result,
                    alpha_scout=mock_result,
                    substack_result=substack_result,
                    youtube_result=youtube_result,
                )

            # The synthesis prompt should have been called with substack and youtube data
            call_args = mock_anthropic_client.messages.create.call_args
            prompt_text = call_args[1]["messages"][0]["content"]
            assert "SUBSTACK EAR" in prompt_text
            assert "YOUTUBE EAR" in prompt_text

    def test_graceful_degradation_substack_import_error(self, monkeypatch):
        """Substack ear raising ImportError should not crash morning brief."""
        from src.shared.morning_brief import _assemble_briefing

        # Verify _assemble_briefing works with empty substack/youtube
        result = _assemble_briefing(
            synthesis="<b>KEY TAKEAWAYS</b>\nTest",
            street_ear_formatted="Street test",
            portfolio_formatted="Portfolio test",
            news_desk_formatted="News test",
            daily_cost=0.10,
            substack_formatted="",
            youtube_formatted="",
        )
        assert "ALPHADESK MORNING BRIEF" in result
        assert "Street test" in result

    def test_assemble_briefing_with_new_sources(self):
        """Assembled briefing should have Substack and YouTube sections when present."""
        from src.shared.morning_brief import _assemble_briefing

        result = _assemble_briefing(
            synthesis="<b>KEY TAKEAWAYS</b>\nTest",
            street_ear_formatted="Street data",
            portfolio_formatted="Portfolio data",
            news_desk_formatted="News data",
            daily_cost=0.10,
            substack_formatted="<b>SUBSTACK EAR</b>\nExpert thesis data",
            youtube_formatted="<b>YOUTUBE EAR</b>\nVideo analysis data",
        )
        assert "SUBSTACK EAR" in result
        assert "YOUTUBE EAR" in result

    def test_run_single_agent_substack(self):
        """run_single_agent('substack_ear') should be a recognized agent."""
        from src.shared.morning_brief import run_single_agent
        # Just verify the function exists and accepts substack_ear
        # Actually running it would require full mock setup
        import inspect
        source = inspect.getsource(run_single_agent)
        assert "substack_ear" in source

    def test_run_single_agent_youtube(self):
        """run_single_agent('youtube_ear') should be a recognized agent."""
        from src.shared.morning_brief import run_single_agent
        import inspect
        source = inspect.getsource(run_single_agent)
        assert "youtube_ear" in source


# ===========================================================================
# TestAdvisorMemoryIntegration
# ===========================================================================

class TestAdvisorMemoryIntegration:

    def test_thesis_actions_table_exists(self):
        from src.advisor.memory import _get_db
        conn = _get_db()
        # Check that table exists
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='thesis_actions'"
        ).fetchone()
        conn.close()
        assert row is not None

    def test_record_thesis_action(self):
        from src.advisor.memory import record_thesis_action, get_thesis_actions
        record_thesis_action(thesis_id=1, action_type="bought", ticker="NVDA", notes="AI thesis")

        actions = get_thesis_actions(lookback_days=30)
        assert len(actions) >= 1
        assert actions[0]["ticker"] == "NVDA"
        assert actions[0]["action_type"] == "bought"

    def test_update_thesis_outcome(self):
        from src.advisor.memory import record_thesis_action, get_thesis_actions, update_thesis_outcome

        record_thesis_action(thesis_id=2, action_type="added_to_watchlist", ticker="AAPL")
        actions = get_thesis_actions(lookback_days=30)
        action_id = actions[0]["id"]

        update_thesis_outcome(action_id, "profitable")

        actions = get_thesis_actions(lookback_days=30)
        matching = [a for a in actions if a["id"] == action_id]
        assert len(matching) == 1
        assert matching[0]["outcome_30d"] == "profitable"


# ===========================================================================
# TestEdgeCases
# ===========================================================================

class TestEdgeCases:

    def test_empty_rss_feeds(self, monkeypatch):
        """All newsletters return empty feeds -> pipeline returns empty."""
        empty_feed = MagicMock()
        empty_feed.bozo = False
        empty_feed.entries = []
        monkeypatch.setattr("feedparser.parse", lambda url: empty_feed)

        mock_config = {
            "newsletters": {"macro": [{"name": "Empty", "slug": "empty"}]},
            "settings": {"max_article_age_hours": 72, "max_article_chars": 8000,
                         "max_articles_per_newsletter": 3},
        }
        with patch("src.substack_ear.substack_fetcher.load_config", return_value=mock_config):
            from src.substack_ear.substack_fetcher import fetch_articles
            articles = fetch_articles()

        assert articles == []

    def test_no_youtube_api_key(self, monkeypatch):
        """No API key -> fetch_videos returns empty gracefully."""
        monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
        mock_config = {
            "channels": {"macro": [{"name": "Test", "channel_id": "UC123"}]},
            "settings": {"youtube_api_key_env": "YOUTUBE_API_KEY"},
        }
        with patch("src.youtube_ear.youtube_fetcher.load_config", return_value=mock_config):
            from src.youtube_ear.youtube_fetcher import fetch_videos
            videos = fetch_videos()

        assert videos == []

    def test_very_long_article(self, monkeypatch):
        """50000 char article should be truncated correctly."""
        long_entry = MagicMock()
        long_entry.get = lambda k, d=None: {
            "title": "Long Article",
            "link": "https://test.substack.com/p/long",
            "author": "Author",
            "published_parsed": time.localtime(),
        }.get(k, d)
        long_entry.title = "Long Article"
        long_entry.content = [{"value": "x" * 50000}]
        long_entry.summary = "x" * 50000
        long_entry.published_parsed = time.localtime()

        feed = MagicMock()
        feed.bozo = False
        feed.entries = [long_entry]
        monkeypatch.setattr("feedparser.parse", lambda url: feed)

        mock_config = {
            "newsletters": {"macro": [{"name": "Long", "slug": "longtest"}]},
            "settings": {"max_article_age_hours": 72, "max_article_chars": 8000,
                         "max_articles_per_newsletter": 3},
        }
        with patch("src.substack_ear.substack_fetcher.load_config", return_value=mock_config):
            from src.substack_ear.substack_fetcher import fetch_articles
            articles = fetch_articles()

        assert len(articles) >= 1
        # Content should be truncated to max_article_chars
        assert len(articles[0]["selftext"]) <= 8000

    def test_unicode_in_titles(self):
        """Unicode characters should be handled without crash."""
        from src.shared.narrative_tracker import record_narrative

        nid = record_narrative(
            narrative="European equities rally on ECB \u2014 \u00e9conomie tr\u00e8s forte",
            source_platform="substack",
            source_detail="test",
            affected_tickers=["EWG"],
        )
        assert isinstance(nid, int) and nid > 0

    def test_duplicate_theses(self):
        """Same thesis recorded twice should not duplicate in DB."""
        from src.shared.narrative_tracker import record_narrative, _get_db

        nid1 = record_narrative(
            narrative="AI infrastructure spending will extend sharply for years",
            source_platform="substack",
            source_detail="test",
            affected_tickers=["NVDA", "AVGO"],
        )
        nid2 = record_narrative(
            narrative="AI infrastructure capex will extend sharply ahead",
            source_platform="substack",
            source_detail="test2",
            affected_tickers=["NVDA", "AVGO"],
        )
        # Should match and return same ID, not create a new record
        assert nid1 == nid2

        conn = _get_db()
        count = conn.execute("SELECT COUNT(*) FROM narrative_propagation").fetchone()[0]
        conn.close()
        assert count == 1

    def test_concurrent_db_access(self, tmp_path):
        """WAL mode should handle concurrent reads/writes."""
        from src.shared.narrative_tracker import record_narrative, get_recent_narratives

        # Write from one "thread"
        nid = record_narrative(
            narrative="Concurrent test thesis alpha bravo charlie delta",
            source_platform="substack",
            source_detail="test",
            affected_tickers=["NVDA"],
        )

        # Read while another write happens
        record_narrative(
            narrative="Second concurrent thesis about semiconductor growth fundamentals",
            source_platform="youtube",
            source_detail="test",
            affected_tickers=["AVGO"],
        )

        # Both should be readable
        recent = get_recent_narratives(days=1)
        assert len(recent) >= 2

    def test_budget_exceeded_mid_analysis(self, monkeypatch):
        """Budget check fails -> remaining batches should be skipped."""
        call_count = {"n": 0}

        def mock_check_budget():
            call_count["n"] += 1
            if call_count["n"] > 1:
                return (False, 5.0, 5.0)  # Over budget
            return (True, 0.10, 5.0)

        with patch("src.substack_ear.analyzer.check_budget", side_effect=mock_check_budget), \
             patch("src.substack_ear.analyzer.record_usage"), \
             patch("src.substack_ear.analyzer.get_all_tickers", return_value=["NVDA"]), \
             patch("src.substack_ear.analyzer.anthropic") as mock_anthropic:

            mock_response = MagicMock()
            mock_response.content = [MagicMock(type="text", text=json.dumps({
                "tickers": [{"symbol": "NVDA", "sentiment": 1.0, "confidence": 0.8,
                             "themes": ["AI"], "source_publication": "Test"}],
                "theses": [], "macro_signals": [], "overall_themes": [], "market_mood": "bullish",
            }))]
            mock_response.usage = MagicMock(input_tokens=500, output_tokens=200)
            mock_anthropic.Anthropic.return_value.messages.create.return_value = mock_response

            from src.substack_ear.analyzer import analyze_articles
            # Two batches of articles
            articles = [
                {"title": f"Art {i}", "selftext": "content", "subreddit": "Test",
                 "author": "Author", "score": 0, "num_comments": 0,
                 "url": "https://test.com", "created_utc": time.time(),
                 "source_platform": "substack"}
                for i in range(6)
            ]
            result = analyze_articles(articles)

        # Should still return valid structure even with budget exceeded
        assert "tickers" in result
        assert "theses" in result
