"""Signal quality validation and thesis propagation backtest.

Validates that signal payloads contain sufficient fields for downstream
decision-making, that cross-source narrative propagation works end-to-end,
that information ratios favour expert sources, and that edge cases are
handled gracefully.  All tests run offline with mocked data.

Usage:
    pytest tests/test_signal_quality.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from unittest.mock import MagicMock

for mod in ("anthropic", "fredapi", "yfinance", "googleapiclient",
            "googleapiclient.discovery", "youtube_transcript_api"):
    sys.modules.setdefault(mod, MagicMock())

import json
import sqlite3
from datetime import date, datetime, timedelta
from typing import Any
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _isolate_dbs(tmp_path, monkeypatch):
    """Redirect every DB_PATH to tmp_path so tests never touch real data."""
    monkeypatch.setattr("src.shared.narrative_tracker.DB_PATH", tmp_path / "narrative.db")
    monkeypatch.setattr("src.shared.agent_bus.DB_PATH", tmp_path / "bus.db")
    monkeypatch.setattr("src.substack_ear.tracker.DB_PATH", tmp_path / "substack.db")
    monkeypatch.setattr("src.youtube_ear.tracker.DB_PATH", tmp_path / "youtube.db")


@pytest.fixture
def bus():
    import src.shared.agent_bus as ab
    return ab


@pytest.fixture
def narrative():
    import src.shared.narrative_tracker as nt
    return nt


@pytest.fixture
def substack_tracker():
    import src.substack_ear.tracker as st
    return st


@pytest.fixture
def youtube_tracker():
    import src.youtube_ear.tracker as yt
    return yt


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _substack_analysis(**overrides) -> dict[str, Any]:
    """Build a minimal Substack analysis dict that publish_thesis_signals accepts."""
    base: dict[str, Any] = {
        "theses": [
            {
                "title": "AI CapEx thesis",
                "summary": "Hyperscaler capital expenditure will extend through 2026",
                "affected_tickers": ["NVDA", "AVGO"],
                "conviction": "high",
                "time_horizon": "medium_term",
                "contrarian": False,
            },
        ],
        "macro_signals": [
            {
                "indicator": "Yield curve",
                "implication": "Recession risk rising",
                "affected_sectors": ["financials", "real_estate"],
            },
        ],
    }
    base.update(overrides)
    return base


def _youtube_analysis(**overrides) -> dict[str, Any]:
    """Build a minimal YouTube analysis dict that publish_signals accepts."""
    base: dict[str, Any] = {
        "theses": [
            {
                "ticker": "NVDA",
                "direction": "bullish",
                "thesis": "AI infrastructure capex cycle accelerating",
                "confidence": 0.85,
                "source": "Patrick Boyle",
                "themes": ["AI", "capex"],
            },
        ],
        "tickers": {
            "NVDA": {
                "total_mentions": 5,
                "avg_sentiment": 1.2,
                "channels": ["Patrick Boyle", "Joseph Carlson"],
                "themes": ["AI"],
            },
        },
    }
    base.update(overrides)
    return base


def _make_videos(n: int = 3, channel: str = "TestChannel", base_views: int = 10000) -> list[dict]:
    return [
        {
            "subreddit": channel,
            "score": base_views * (i + 1),
            "title": f"Video {i+1}",
            "url": f"https://youtube.com/watch?v=vid{i+1}",
            "selftext": f"Transcript for video {i+1}",
        }
        for i in range(n)
    ]


# ===================================================================
# 1. Signal Schema Quality Audit
# ===================================================================

class TestSignalSchemaQuality:
    """Verify signal payloads contain enough info for downstream decision-making."""

    # -- expert_thesis ---------------------------------------------------

    def test_expert_thesis_has_required_fields(self, substack_tracker, bus):
        analysis = _substack_analysis()
        signals = substack_tracker.publish_thesis_signals(analysis)

        expert = [s for s in signals if s["type"] == "expert_thesis"]
        assert len(expert) >= 1
        required = {"title", "summary", "affected_tickers", "conviction",
                     "time_horizon", "contrarian"}
        for sig in expert:
            missing = required - set(sig.keys())
            assert not missing, f"expert_thesis missing keys: {missing}"

    def test_expert_thesis_values_non_empty(self, substack_tracker, bus):
        analysis = _substack_analysis()
        signals = substack_tracker.publish_thesis_signals(analysis)
        expert = [s for s in signals if s["type"] == "expert_thesis"][0]
        assert expert["title"] != ""
        assert expert["summary"] != ""
        assert len(expert["affected_tickers"]) > 0
        assert expert["conviction"] in ("low", "medium", "high")

    # -- macro_framework -------------------------------------------------

    def test_macro_framework_has_required_fields(self, substack_tracker, bus):
        analysis = _substack_analysis()
        signals = substack_tracker.publish_thesis_signals(analysis)

        macro = [s for s in signals if s["type"] == "macro_framework"]
        assert len(macro) >= 1
        required = {"indicator", "implication", "affected_sectors"}
        for sig in macro:
            missing = required - set(sig.keys())
            assert not missing, f"macro_framework missing keys: {missing}"

    def test_macro_framework_sectors_is_list(self, substack_tracker, bus):
        analysis = _substack_analysis()
        signals = substack_tracker.publish_thesis_signals(analysis)
        macro = [s for s in signals if s["type"] == "macro_framework"][0]
        assert isinstance(macro["affected_sectors"], list)
        assert len(macro["affected_sectors"]) > 0

    # -- sector_rotation_call --------------------------------------------

    def test_sector_rotation_call_has_required_fields(self, substack_tracker, bus):
        analysis = _substack_analysis(theses=[{
            "title": "Energy sector rotation underway",
            "summary": "Sector shift from tech to energy",
            "affected_tickers": ["XOM", "CVX"],
            "conviction": "high",
            "time_horizon": "medium_term",
            "contrarian": False,
        }])
        signals = substack_tracker.publish_thesis_signals(analysis)
        sector = [s for s in signals if s["type"] == "sector_rotation_call"]
        assert len(sector) >= 1
        required = {"title", "affected_tickers", "conviction"}
        for sig in sector:
            missing = required - set(sig.keys())
            assert not missing, f"sector_rotation_call missing keys: {missing}"

    # -- expert_analysis (YouTube) ---------------------------------------

    def test_expert_analysis_has_required_fields(self, youtube_tracker, bus):
        analysis = _youtube_analysis()
        signals = youtube_tracker.publish_signals(analysis)
        assert len(signals) >= 1
        required = {"ticker", "direction", "thesis", "confidence", "source", "themes"}
        for sig in signals:
            missing = required - set(sig.keys())
            assert not missing, f"expert_analysis missing keys: {missing}"

    def test_expert_analysis_confidence_is_numeric(self, youtube_tracker, bus):
        analysis = _youtube_analysis()
        signals = youtube_tracker.publish_signals(analysis)
        for sig in signals:
            assert isinstance(sig["confidence"], (int, float))
            assert 0.0 <= sig["confidence"] <= 1.0

    # -- narrative_amplification (YouTube view spike) --------------------

    def test_narrative_amplification_has_required_fields(self, youtube_tracker, bus, tmp_path, monkeypatch):
        """View spike signal must carry channel, title, views, avg_views,
        spike_multiplier, url, related_tickers."""
        monkeypatch.setattr("src.youtube_ear.tracker.DB_PATH", tmp_path / "youtube.db")

        # Seed historical average (100 views) so spike detector has a baseline
        conn = youtube_tracker._get_db()
        past = (date.today() - timedelta(days=3)).isoformat()
        conn.execute(
            "INSERT INTO channel_view_history (channel_name, date, avg_views, video_count) "
            "VALUES (?, ?, ?, ?)",
            ("SpikeChannel", past, 100, 5),
        )
        conn.commit()
        conn.close()

        videos = [{
            "subreddit": "SpikeChannel",
            "score": 500,  # 5x the 100 avg
            "title": "Breaking AI news",
            "url": "https://youtube.com/watch?v=spike1",
        }]
        analysis = {"tickers": {"NVDA": {"channels": ["SpikeChannel"], "total_mentions": 3}}}

        spikes = youtube_tracker.detect_view_spikes(analysis, videos)
        assert len(spikes) >= 1

        required = {"channel", "title", "views", "avg_views", "multiplier", "url"}
        for spike in spikes:
            missing = required - set(spike.keys())
            assert not missing, f"view spike missing keys: {missing}"

        # Also check that a narrative_amplification signal was published to bus
        consumed = bus.consume(signal_type="narrative_amplification")
        assert len(consumed) >= 1
        payload = consumed[0]["payload"]
        assert "related_tickers" in payload
        assert "spike_multiplier" in payload


# ===================================================================
# 2. Cross-Source Correlation Test
# ===================================================================

class TestCrossSourceCorrelation:
    """Simulate the Substack -> YouTube -> Reddit propagation chain."""

    def test_three_stage_propagation(self, narrative):
        # Day 1: Substack expert publishes AI CapEx thesis
        nid = narrative.record_narrative(
            narrative="AI infrastructure spending extends through years ahead",
            source_platform="substack",
            source_detail="fabricated_knowledge",
            affected_tickers=["NVDA", "AVGO"],
            conviction="high",
        )
        conn = narrative._get_db()
        row = conn.execute(
            "SELECT current_stage, confidence FROM narrative_propagation WHERE id = ?", (nid,)
        ).fetchone()
        conn.close()
        assert row[0] == "expert"
        initial_conf = row[1]

        # Day 2: YouTube discusses same topic -> fuzzy match -> promote
        # Shares "infrastructure" and "spending" as significant words, ticker overlap > 50%
        with patch("src.shared.narrative_tracker.publish") as mock_pub:
            nid2 = narrative.record_narrative(
                narrative="AI infrastructure spending capex cycle accelerating",
                source_platform="youtube",
                source_detail="patrick_boyle",
                affected_tickers=["NVDA", "AVGO"],
                conviction="medium",
            )
            assert nid2 == nid, f"Expected match (nid={nid}), got new narrative (nid2={nid2})"
            mock_pub.assert_called_once()
            args, kwargs = mock_pub.call_args
            sig_type = kwargs.get("signal_type") or (args[0] if args else None)
            assert sig_type == "thesis_propagation"

        conn = narrative._get_db()
        row = conn.execute(
            "SELECT current_stage, confidence FROM narrative_propagation WHERE id = ?", (nid,)
        ).fetchone()
        conn.close()
        assert row[0] == "amplified"
        amplified_conf = row[1]
        assert amplified_conf > initial_conf

        # Day 3: Reddit unusual mentions -> mainstream
        with patch("src.shared.narrative_tracker.publish") as mock_pub:
            nid3 = narrative.record_narrative(
                narrative="AI infrastructure spending extends massively forward",
                source_platform="reddit",
                source_detail="wallstreetbets",
                affected_tickers=["NVDA", "AVGO"],
                conviction="low",
            )
            assert nid3 == nid
            args, kwargs = mock_pub.call_args
            sig_type = kwargs.get("signal_type") or (args[0] if args else None)
            assert sig_type == "thesis_confirmed"

        row = narrative._get_db().execute(
            "SELECT current_stage, confidence FROM narrative_propagation WHERE id = ?", (nid,)
        ).fetchone()
        assert row[0] == "mainstream"
        mainstream_conf = row[1]
        assert mainstream_conf > amplified_conf

    def test_confidence_monotonically_increases(self, narrative):
        """Confidence must increase at each promotion stage."""
        confs = []

        nid = narrative.record_narrative(
            narrative="Semiconductor supply chain constraints tightening ahead",
            source_platform="substack",
            source_detail="test",
            affected_tickers=["NVDA", "AVGO"],
            conviction="medium",
        )
        confs.append(narrative._get_db().execute(
            "SELECT confidence FROM narrative_propagation WHERE id = ?", (nid,)
        ).fetchone()[0])

        narrative.record_narrative(
            narrative="Semiconductor supply chain constraints tightening sharply",
            source_platform="youtube",
            source_detail="test",
            affected_tickers=["NVDA", "AVGO"],
        )
        confs.append(narrative._get_db().execute(
            "SELECT confidence FROM narrative_propagation WHERE id = ?", (nid,)
        ).fetchone()[0])

        narrative.record_narrative(
            narrative="Semiconductor supply chain constraints extremely tight",
            source_platform="reddit",
            source_detail="test",
            affected_tickers=["NVDA", "AVGO"],
        )
        confs.append(narrative._get_db().execute(
            "SELECT confidence FROM narrative_propagation WHERE id = ?", (nid,)
        ).fetchone()[0])

        assert confs[0] < confs[1] < confs[2], f"Confidence not monotonic: {confs}"


# ===================================================================
# 3. Information Ratio Assessment
# ===================================================================

class TestInformationRatio:

    def test_substack_higher_avg_conviction_than_reddit(self, narrative):
        """Substack theses should map to higher confidence than Reddit."""
        # Substack high conviction -> 0.8
        nid_sub = narrative.record_narrative(
            narrative="Expert thesis about semiconductor growth trajectory",
            source_platform="substack",
            source_detail="expert_author",
            affected_tickers=["NVDA"],
            conviction="high",
        )
        sub_conf = narrative._get_db().execute(
            "SELECT confidence FROM narrative_propagation WHERE id = ?", (nid_sub,)
        ).fetchone()[0]

        # Reddit low conviction -> 0.3
        nid_red = narrative.record_narrative(
            narrative="Random retail thesis about biotech moonshot",
            source_platform="reddit",
            source_detail="wsb",
            affected_tickers=["MRNA"],
            conviction="low",
        )
        red_conf = narrative._get_db().execute(
            "SELECT confidence FROM narrative_propagation WHERE id = ?", (nid_red,)
        ).fetchone()[0]

        assert sub_conf > red_conf, (
            f"Substack ({sub_conf}) should have higher confidence than Reddit ({red_conf})"
        )

    def test_view_spike_correlates_with_ticker_mentions(self, youtube_tracker, bus, tmp_path, monkeypatch):
        """Videos with 3x+ avg views that mention tickers produce actionable signals."""
        monkeypatch.setattr("src.youtube_ear.tracker.DB_PATH", tmp_path / "youtube.db")

        # Seed historical avg
        conn = youtube_tracker._get_db()
        past = (date.today() - timedelta(days=5)).isoformat()
        conn.execute(
            "INSERT INTO channel_view_history (channel_name, date, avg_views, video_count) "
            "VALUES (?, ?, ?, ?)",
            ("AI_Channel", past, 1000, 10),
        )
        conn.commit()
        conn.close()

        videos = [{
            "subreddit": "AI_Channel",
            "score": 5000,  # 5x avg
            "title": "NVDA massive AI deal announced",
            "url": "https://youtube.com/watch?v=spike2",
        }]
        analysis = {"tickers": {"NVDA": {"channels": ["AI_Channel"], "total_mentions": 4}}}

        spikes = youtube_tracker.detect_view_spikes(analysis, videos)
        assert len(spikes) == 1
        assert spikes[0]["multiplier"] >= 3.0

        # Check bus has signal with related tickers
        consumed = bus.consume(signal_type="narrative_amplification")
        assert len(consumed) == 1
        assert "NVDA" in consumed[0]["payload"]["related_tickers"]

    def test_multi_channel_convergence_higher_signal(self, youtube_tracker, bus):
        """Ticker across 2+ channels triggers expert_analysis convergence signal."""
        analysis = {
            "tickers": {
                "NVDA": {
                    "channels": ["Patrick Boyle", "Joseph Carlson"],
                    "total_mentions": 8,
                    "avg_sentiment": 1.5,
                    "themes": ["AI"],
                },
                "AAPL": {
                    "channels": ["Joseph Carlson"],
                    "total_mentions": 2,
                    "avg_sentiment": 0.5,
                    "themes": ["iPhone"],
                },
            }
        }
        convergences = youtube_tracker.detect_multi_channel_convergence(analysis)
        conv_tickers = [c["ticker"] for c in convergences]
        assert "NVDA" in conv_tickers, "NVDA with 2 channels should converge"
        assert "AAPL" not in conv_tickers, "AAPL with 1 channel should not"

    def test_single_channel_not_convergence(self, youtube_tracker):
        analysis = {
            "tickers": {
                "GOOG": {
                    "channels": ["OneChannel"],
                    "total_mentions": 10,
                    "avg_sentiment": 1.0,
                    "themes": ["search"],
                },
            }
        }
        convergences = youtube_tracker.detect_multi_channel_convergence(analysis)
        assert len(convergences) == 0


# ===================================================================
# 4. Edge Cases
# ===================================================================

class TestEdgeCases:

    # -- Empty inputs ---------------------------------------------------

    def test_empty_analysis_publishes_nothing(self, substack_tracker):
        signals = substack_tracker.publish_thesis_signals({"theses": [], "macro_signals": []})
        assert signals == []

    def test_empty_youtube_theses_publishes_nothing(self, youtube_tracker):
        signals = youtube_tracker.publish_signals({"theses": []})
        assert signals == []

    def test_no_videos_view_spike_returns_empty(self, youtube_tracker):
        spikes = youtube_tracker.detect_view_spikes({}, [])
        assert spikes == []

    def test_no_tickers_convergence_returns_empty(self, youtube_tracker):
        convergences = youtube_tracker.detect_multi_channel_convergence({"tickers": {}})
        assert convergences == []

    # -- YouTube video with no transcript -> skipped, no crash ----------

    def test_youtube_thesis_no_ticker_skipped(self, youtube_tracker):
        """Thesis with empty ticker should be silently skipped."""
        youtube_tracker.record_theses({
            "theses": [
                {"ticker": "", "direction": "bullish", "thesis": "Something", "confidence": 0.8, "source": "X"},
            ]
        })
        conn = youtube_tracker._get_db()
        count = conn.execute("SELECT COUNT(*) FROM theses").fetchone()[0]
        conn.close()
        assert count == 0

    def test_youtube_thesis_no_text_skipped(self, youtube_tracker):
        """Thesis with empty thesis text should be silently skipped."""
        youtube_tracker.record_theses({
            "theses": [
                {"ticker": "NVDA", "direction": "bullish", "thesis": "", "confidence": 0.8, "source": "X"},
            ]
        })
        conn = youtube_tracker._get_db()
        count = conn.execute("SELECT COUNT(*) FROM theses").fetchone()[0]
        conn.close()
        assert count == 0

    # -- Very long articles -> truncated at limits ----------------------

    def test_substack_long_article_truncated(self):
        from src.substack_ear.analyzer import _format_articles_for_prompt
        article = {
            "subreddit": "TestPub",
            "author": "Author",
            "title": "Long article",
            "selftext": "A" * 50000,
        }
        result = _format_articles_for_prompt([article])
        assert len(result) < 50000
        assert "..." in result

    def test_youtube_long_transcript_truncated(self):
        from src.youtube_ear.analyzer import _format_videos_for_prompt
        video = {
            "subreddit": "Channel",
            "score": 10000,
            "num_comments": 50,
            "title": "Long video",
            "selftext": "B" * 50000,
            "duration_seconds": 3600,
        }
        result = _format_videos_for_prompt([video])
        assert len(result) < 50000
        assert "..." in result

    # -- Ticker false positive filtering --------------------------------

    def test_ticker_false_positives_filtered_substack(self):
        from src.substack_ear.analyzer import _validate_ticker_symbol
        false_positives = ["IT", "AI", "EV", "CEO", "A", "BE", "SO", "ALL",
                           "DD", "IPO", "ETF", "GDP", "CPI", "FED", "SEC",
                           "FDA", "DOJ", "US", "UK", "EU", "WSB"]
        for fp in false_positives:
            assert _validate_ticker_symbol(fp) is None, f"{fp} should be filtered"

    def test_ticker_false_positives_filtered_youtube(self):
        from src.youtube_ear.analyzer import _validate_ticker_symbol
        false_positives = ["IT", "AI", "EV", "CEO", "A", "BE", "SO", "ALL",
                           "DD", "IPO", "ETF", "GDP", "CPI", "FED", "SEC",
                           "FDA", "DOJ", "US", "UK", "EU", "WSB"]
        for fp in false_positives:
            assert _validate_ticker_symbol(fp) is None, f"{fp} should be filtered"

    def test_valid_tickers_pass_validation_substack(self):
        from src.substack_ear.analyzer import _validate_ticker_symbol
        for sym in ["AAPL", "NVDA", "TSLA", "GOOG", "MSFT"]:
            assert _validate_ticker_symbol(sym) == sym

    def test_valid_tickers_pass_validation_youtube(self):
        from src.youtube_ear.analyzer import _validate_ticker_symbol
        for sym in ["AAPL", "NVDA", "TSLA", "GOOG", "MSFT"]:
            assert _validate_ticker_symbol(sym) == sym

    # -- Unicode / special characters in titles -------------------------

    def test_unicode_title_substack(self, substack_tracker, bus):
        analysis = _substack_analysis(theses=[{
            "title": "Unicorn thesis \u2014 \u00e9mergent AI \u2192 growth \ud83d\ude80",
            "summary": "Testing unicode handling in thesis titles",
            "affected_tickers": ["NVDA"],
            "conviction": "high",
            "time_horizon": "medium_term",
            "contrarian": False,
        }])
        signals = substack_tracker.publish_thesis_signals(analysis)
        assert len(signals) >= 1
        assert "\u2014" in signals[0]["title"]

    def test_unicode_title_youtube(self, youtube_tracker, bus):
        analysis = _youtube_analysis(theses=[{
            "ticker": "NVDA",
            "direction": "bullish",
            "thesis": "AI growth thesis \u2014 \u00e9mergent technology \ud83d\ude80",
            "confidence": 0.9,
            "source": "Channel\u2122",
            "themes": ["AI"],
        }])
        signals = youtube_tracker.publish_signals(analysis)
        assert len(signals) >= 1

    # -- Budget exceeded mid-analysis -> remaining batches skipped ------

    def test_budget_exceeded_skips_batch_substack(self):
        from src.substack_ear.analyzer import _analyze_batch
        with patch("src.substack_ear.analyzer.check_budget", return_value=(False, 5.0, 5.0)):
            result = _analyze_batch([], [], MagicMock())
            assert result["tickers"] == []
            assert result["theses"] == []

    def test_budget_exceeded_skips_batch_youtube(self):
        from src.youtube_ear.analyzer import _analyze_batch
        with patch("src.youtube_ear.analyzer.check_budget", return_value=(False, 5.0, 5.0)):
            result = _analyze_batch([], [], MagicMock())
            assert result["tickers"] == []
            assert result["theses"] == []

    # -- Duplicate theses from same source -> deduplication -------------

    def test_duplicate_narrative_from_same_source_deduped(self, narrative):
        """Same narrative from same platform should update confidence, not insert new."""
        nid1 = narrative.record_narrative(
            narrative="AI infrastructure spending thesis extending forward",
            source_platform="substack",
            source_detail="author_a",
            affected_tickers=["NVDA", "AVGO"],
            conviction="high",
        )
        nid2 = narrative.record_narrative(
            narrative="AI infrastructure spending thesis extending sharply",
            source_platform="substack",
            source_detail="author_b",
            affected_tickers=["NVDA", "AVGO"],
            conviction="medium",
        )
        assert nid1 == nid2, "Same narrative should reuse existing ID"

        conn = narrative._get_db()
        count = conn.execute("SELECT COUNT(*) FROM narrative_propagation").fetchone()[0]
        conn.close()
        assert count == 1

    # -- Narrative matching with partial ticker overlap ------------------

    def test_narrative_exactly_50pct_ticker_overlap_no_match(self, narrative):
        """Overlap must be >50%, so exactly 50% should NOT match."""
        result = narrative._narratives_match(
            "AI infrastructure spending extends forward clearly",
            ["NVDA", "AVGO", "VRT", "MRVL"],
            "AI infrastructure spending extends forward sharply",
            ["NVDA", "AVGO", "QCOM", "AMD"],
        )
        # 2/4 = 50% exactly, needs >50% so this should be False
        assert result is False

    def test_narrative_above_50pct_ticker_overlap_matches(self, narrative):
        """Overlap >50% should match (assuming 2+ significant word overlap)."""
        result = narrative._narratives_match(
            "AI infrastructure spending extends forward clearly",
            ["NVDA", "AVGO", "VRT"],
            "AI infrastructure spending extends forward sharply",
            ["NVDA", "AVGO"],
        )
        # 2/2 = 100% on smaller set
        assert result is True

    # -- Narrative matching with exactly 1 significant word overlap ------

    def test_one_significant_word_overlap_no_match(self, narrative):
        """Need 2+ significant words overlapping; 1 is not enough."""
        result = narrative._narratives_match(
            "AI infrastructure thesis extends forward",
            ["NVDA", "AVGO"],
            "infrastructure bottleneck manufacturing delays",
            ["NVDA", "AVGO"],
        )
        # "infrastructure" is the only shared significant word
        assert result is False

    def test_two_significant_words_overlap_matches(self, narrative):
        """2 significant words + ticker overlap should match."""
        result = narrative._narratives_match(
            "AI infrastructure spending extends forward",
            ["NVDA", "AVGO"],
            "infrastructure spending bottleneck easing slowly",
            ["NVDA", "AVGO"],
        )
        # "infrastructure" and "spending" overlap
        assert result is True

    # -- Low conviction thesis NOT published by YouTube ------------------

    def test_youtube_low_confidence_thesis_not_published(self, youtube_tracker):
        """YouTube publish_signals enforces 0.6 minimum confidence."""
        analysis = _youtube_analysis(theses=[{
            "ticker": "GOOG",
            "direction": "bearish",
            "thesis": "Weak search revenue outlook",
            "confidence": 0.4,  # below 0.6 threshold
            "source": "Random",
            "themes": ["search"],
        }])
        signals = youtube_tracker.publish_signals(analysis)
        assert len(signals) == 0

    # -- Low conviction thesis NOT published by Substack -----------------

    def test_substack_low_conviction_thesis_not_published(self, substack_tracker):
        """Substack publish_thesis_signals only publishes high/medium conviction."""
        analysis = _substack_analysis(theses=[{
            "title": "Speculative idea",
            "summary": "Low conviction thesis",
            "affected_tickers": ["XYZ"],
            "conviction": "low",
            "time_horizon": "short_term",
            "contrarian": False,
        }])
        signals = substack_tracker.publish_thesis_signals(analysis)
        expert = [s for s in signals if s["type"] == "expert_thesis"]
        assert len(expert) == 0


# ===================================================================
# 5. Backtest Thesis Propagation (5-day simulation)
# ===================================================================

class TestBacktestThesisPropagation:

    def test_five_day_simulation(self, narrative):
        """Simulate 5 days of multi-source data and verify propagation outcomes."""
        # Day 1: Substack thesis "Hyperscaler CapEx extends" [NVDA, AVGO, VRT]
        nid1 = narrative.record_narrative(
            narrative="Hyperscaler CapEx extends through fiscal years ahead",
            source_platform="substack",
            source_detail="fabricated_knowledge",
            affected_tickers=["NVDA", "AVGO", "VRT"],
            conviction="high",
        )
        stage = narrative._get_db().execute(
            "SELECT current_stage FROM narrative_propagation WHERE id = ?", (nid1,)
        ).fetchone()[0]
        assert stage == "expert"

        # Day 2: YouTube "AI infrastructure spending boom" [NVDA, AVGO]
        nid1b = narrative.record_narrative(
            narrative="AI infrastructure spending boom extends through years",
            source_platform="youtube",
            source_detail="patrick_boyle",
            affected_tickers=["NVDA", "AVGO"],
            conviction="medium",
        )
        assert nid1b == nid1
        stage = narrative._get_db().execute(
            "SELECT current_stage FROM narrative_propagation WHERE id = ?", (nid1,)
        ).fetchone()[0]
        assert stage == "amplified"

        # Day 3: Reddit spike on NVDA (unusual_mentions)
        nid1c = narrative.record_narrative(
            narrative="Hyperscaler infrastructure CapEx spending continuing",
            source_platform="reddit",
            source_detail="wallstreetbets",
            affected_tickers=["NVDA", "AVGO", "VRT"],
            conviction="low",
        )
        assert nid1c == nid1
        stage = narrative._get_db().execute(
            "SELECT current_stage FROM narrative_propagation WHERE id = ?", (nid1,)
        ).fetchone()[0]
        assert stage == "mainstream"

        # Day 4: Substack thesis "Energy sector rotation" [XOM, CVX, SLB]
        nid2 = narrative.record_narrative(
            narrative="Energy sector rotation thesis defensives outperform",
            source_platform="substack",
            source_detail="odd_lots",
            affected_tickers=["XOM", "CVX", "SLB"],
            conviction="medium",
        )
        assert nid2 != nid1  # different narrative
        stage = narrative._get_db().execute(
            "SELECT current_stage FROM narrative_propagation WHERE id = ?", (nid2,)
        ).fetchone()[0]
        assert stage == "expert"

        # Day 5: YouTube "Energy stocks undervalued" [XOM, CVX]
        nid2b = narrative.record_narrative(
            narrative="Energy sector rotation stocks undervalued defensives",
            source_platform="youtube",
            source_detail="joseph_carlson",
            affected_tickers=["XOM", "CVX"],
            conviction="medium",
        )
        assert nid2b == nid2
        stage = narrative._get_db().execute(
            "SELECT current_stage FROM narrative_propagation WHERE id = ?", (nid2,)
        ).fetchone()[0]
        assert stage == "amplified"

        # Verify: First narrative reaches "mainstream", second reaches "amplified"
        propagating = narrative.get_propagating_narratives(min_stage="amplified")
        stages = {p["id"]: p["current_stage"] for p in propagating}
        assert stages[nid1] == "mainstream"
        assert stages[nid2] == "amplified"

    def test_source_reliability_tracking(self, narrative):
        """Source reliability updates correctly after signal outcomes."""
        # Record signal outcomes
        narrative.record_signal_outcome(
            signal_id=1, signal_type="substack_expert_thesis", ticker="NVDA", price_at_signal=100.0,
        )
        narrative.record_signal_outcome(
            signal_id=2, signal_type="substack_expert_thesis", ticker="AVGO", price_at_signal=50.0,
        )

        # Simulate 5-day price updates
        conn = narrative._get_db()
        five_days_ago = (date.today() - timedelta(days=5)).isoformat()
        conn.execute(
            "UPDATE signal_outcomes SET signal_date = ?", (five_days_ago,)
        )
        conn.commit()
        conn.close()

        narrative.update_signal_outcomes("NVDA", 110.0)  # +10%
        narrative.update_signal_outcomes("AVGO", 55.0)    # +10%

        with patch("src.shared.narrative_tracker.publish"):
            narrative.update_source_reliability("substack", "substack")

        results = narrative.get_source_reliability(min_signals=1)
        assert len(results) >= 1
        assert results[0]["total_signals"] >= 2
        assert results[0]["correct_signals"] >= 2
        assert results[0]["hit_rate"] > 0.0

    def test_build_narrative_context_readable(self, narrative):
        """build_narrative_context() returns readable Opus-friendly summary."""
        # Create an amplified narrative
        narrative.record_narrative(
            narrative="Hyperscaler CapEx extends through fiscal years ahead",
            source_platform="substack",
            source_detail="fabricated_knowledge",
            affected_tickers=["NVDA", "AVGO"],
            conviction="high",
        )
        narrative.record_narrative(
            narrative="Hyperscaler CapEx infrastructure extends through years",
            source_platform="youtube",
            source_detail="patrick_boyle",
            affected_tickers=["NVDA", "AVGO"],
        )

        context = narrative.build_narrative_context()
        assert "Propagating Narratives:" in context
        assert "NVDA" in context
        assert "AVGO" in context
        assert "amplified" in context
        assert "substack" in context.lower() or "fabricated" in context.lower()
        # Should be human-readable, not JSON
        assert "{" not in context


# ===================================================================
# 6. Conviction Consistency Check
# ===================================================================

class TestConvictionConsistency:

    def test_conviction_to_confidence_mapping(self, narrative):
        """low/medium/high convictions map to 0.3/0.5/0.8 confidence scores."""
        expected = {"low": 0.3, "medium": 0.5, "high": 0.8}
        for conv, expected_conf in expected.items():
            nid = narrative.record_narrative(
                narrative=f"Unique thesis for {conv} conviction check only",
                source_platform="substack",
                source_detail="test",
                affected_tickers=[f"T{conv.upper()[:3]}"],
                conviction=conv,
            )
            actual = narrative._get_db().execute(
                "SELECT confidence FROM narrative_propagation WHERE id = ?", (nid,)
            ).fetchone()[0]
            assert actual == pytest.approx(expected_conf), (
                f"conviction={conv}: expected {expected_conf}, got {actual}"
            )

    def test_youtube_confidence_threshold_enforced(self, youtube_tracker):
        """YouTube publish_signals skips theses below 0.6 confidence."""
        low_conf = _youtube_analysis(theses=[{
            "ticker": "GOOG",
            "direction": "bullish",
            "thesis": "Good thesis but low confidence",
            "confidence": 0.55,
            "source": "TestChannel",
            "themes": ["search"],
        }])
        signals = youtube_tracker.publish_signals(low_conf)
        assert len(signals) == 0

        high_conf = _youtube_analysis(theses=[{
            "ticker": "GOOG",
            "direction": "bullish",
            "thesis": "Good thesis with high confidence",
            "confidence": 0.75,
            "source": "TestChannel",
            "themes": ["search"],
        }])
        signals = youtube_tracker.publish_signals(high_conf)
        assert len(signals) == 1

    def test_youtube_exactly_0_6_published(self, youtube_tracker):
        """Confidence of exactly 0.6 should NOT be published (< 0.6 check)."""
        analysis = _youtube_analysis(theses=[{
            "ticker": "MSFT",
            "direction": "bullish",
            "thesis": "Boundary test thesis at exactly 0.6",
            "confidence": 0.6,
            "source": "TestChannel",
            "themes": ["cloud"],
        }])
        signals = youtube_tracker.publish_signals(analysis)
        # The code uses `confidence < 0.6: continue`, so 0.6 should pass
        assert len(signals) == 1

    def test_agent_bus_signal_types_valid(self, bus):
        """All signal types published by our modules are registered in SIGNAL_TYPES."""
        expected_types = {
            "expert_thesis", "macro_framework", "sector_rotation_call",
            "expert_analysis", "narrative_amplification",
            "thesis_propagation", "thesis_confirmed", "source_quality_update",
        }
        for sig_type in expected_types:
            assert sig_type in bus.SIGNAL_TYPES, f"{sig_type} not in SIGNAL_TYPES"

    def test_unregistered_signal_type_raises(self, bus):
        """Publishing an unregistered signal type should raise ValueError."""
        with pytest.raises(ValueError, match="Unknown signal type"):
            bus.publish(
                signal_type="made_up_signal",
                source_agent="test",
                payload={"test": True},
            )

    def test_substack_conviction_filter(self, substack_tracker):
        """Only high and medium conviction theses are published as expert_thesis."""
        for conviction, should_publish in [("high", True), ("medium", True), ("low", False)]:
            analysis = _substack_analysis(theses=[{
                "title": f"Thesis with {conviction} conviction",
                "summary": "Testing conviction filter",
                "affected_tickers": ["AAPL"],
                "conviction": conviction,
                "time_horizon": "medium_term",
                "contrarian": False,
            }], macro_signals=[])
            signals = substack_tracker.publish_thesis_signals(analysis)
            expert = [s for s in signals if s["type"] == "expert_thesis"]
            if should_publish:
                assert len(expert) == 1, f"{conviction} should be published"
            else:
                assert len(expert) == 0, f"{conviction} should NOT be published"

    def test_bus_consume_marks_consumed(self, bus):
        """Consuming signals marks them consumed, preventing double-reads."""
        bus.publish("expert_thesis", "test", {"title": "consume test"})
        first = bus.consume(signal_type="expert_thesis")
        assert len(first) == 1
        second = bus.consume(signal_type="expert_thesis")
        assert len(second) == 0

    def test_bus_consume_filter_by_source(self, bus):
        """Can filter consumed signals by source_agent."""
        bus.publish("expert_thesis", "substack_ear", {"from": "substack"})
        bus.publish("expert_thesis", "youtube_ear", {"from": "youtube"})
        sub_only = bus.consume(signal_type="expert_thesis", source_agent="substack_ear")
        assert len(sub_only) == 1
        assert sub_only[0]["payload"]["from"] == "substack"
