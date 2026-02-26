"""Unit tests for src/shared/narrative_tracker.py — narrative propagation tracker.

Tests cover: significant-word extraction, ticker overlap, narrative matching,
record/promote/query narratives, signal outcome tracking, source reliability,
and the context-builder used for Opus synthesis prompts.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from unittest.mock import MagicMock

for mod in ("anthropic", "fredapi", "yfinance"):
    sys.modules.setdefault(mod, MagicMock())

import json
import sqlite3
from datetime import date, datetime, timedelta
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


@pytest.fixture
def tracker():
    """Import the narrative_tracker module after DB paths are monkeypatched."""
    import src.shared.narrative_tracker as nt
    return nt


# ---------------------------------------------------------------------------
# TestSignificantWords
# ---------------------------------------------------------------------------

class TestSignificantWords:

    def test_basic(self, tracker):
        result = tracker._significant_words("AI CapEx cycle will extend for two years")
        assert "capex" in result
        assert "cycle" in result
        assert "extend" in result
        assert "years" in result

    def test_stop_words_filtered(self, tracker):
        result = tracker._significant_words("stock market price company invest trading")
        assert result == set(), f"Expected empty set but got {result}"

    def test_short_words_filtered(self, tracker):
        result = tracker._significant_words("AI to be or not is an ok day")
        assert result == set(), f"Expected empty set but got {result}"

    def test_mixed(self, tracker):
        result = tracker._significant_words("infrastructure spending reaches record levels")
        assert "infrastructure" in result
        assert "spending" in result
        assert "reaches" in result
        assert "record" in result
        assert "levels" in result


# ---------------------------------------------------------------------------
# TestTickerOverlap
# ---------------------------------------------------------------------------

class TestTickerOverlap:

    def test_full_overlap(self, tracker):
        assert tracker._ticker_overlap(["NVDA", "AVGO"], ["NVDA", "AVGO"]) == 1.0

    def test_partial_overlap(self, tracker):
        # Intersection = {NVDA} = 1, min(3,2)=2 → 0.5
        result = tracker._ticker_overlap(["NVDA", "AVGO", "VRT"], ["NVDA", "TSLA"])
        assert result == pytest.approx(0.5)

    def test_no_overlap(self, tracker):
        assert tracker._ticker_overlap(["AAPL"], ["GOOG"]) == 0.0

    def test_empty_lists(self, tracker):
        assert tracker._ticker_overlap([], ["NVDA"]) == 0.0
        assert tracker._ticker_overlap(["NVDA"], []) == 0.0
        assert tracker._ticker_overlap([], []) == 0.0

    def test_case_insensitive(self, tracker):
        assert tracker._ticker_overlap(["nvda"], ["NVDA"]) == 1.0


# ---------------------------------------------------------------------------
# TestNarrativeMatch
# ---------------------------------------------------------------------------

class TestNarrativeMatch:

    def test_matching_narrative(self, tracker):
        assert tracker._narratives_match(
            "AI infrastructure spending will extend for years",
            ["NVDA", "AVGO"],
            "AI infrastructure capex will extend sharply",
            ["NVDA", "AVGO"],
        ) is True

    def test_no_ticker_overlap(self, tracker):
        assert tracker._narratives_match(
            "AI infrastructure spending will extend for years",
            ["NVDA", "AVGO"],
            "AI infrastructure spending will extend for years",
            ["AAPL", "GOOG"],
        ) is False

    def test_no_word_overlap(self, tracker):
        assert tracker._narratives_match(
            "AI infrastructure spending will extend for years",
            ["NVDA", "AVGO"],
            "Biotech pipeline approvals ahead quarterly",
            ["NVDA", "AVGO"],
        ) is False

    def test_case_insensitive(self, tracker):
        assert tracker._narratives_match(
            "AI INFRASTRUCTURE spending will extend for YEARS",
            ["NVDA"],
            "ai infrastructure capex will extend sharply",
            ["NVDA"],
        ) is True


# ---------------------------------------------------------------------------
# TestRecordNarrative
# ---------------------------------------------------------------------------

class TestRecordNarrative:

    def test_new_narrative(self, tracker):
        nid = tracker.record_narrative(
            narrative="AI capex spending thesis",
            source_platform="substack",
            source_detail="fabricated_knowledge",
            affected_tickers=["NVDA", "AVGO"],
            conviction="high",
        )
        assert isinstance(nid, int) and nid > 0

    def test_substack_stage(self, tracker):
        nid = tracker.record_narrative(
            narrative="Unique substack thesis alpha",
            source_platform="substack",
            source_detail="test",
            affected_tickers=["AAPL"],
        )
        rows = tracker._get_db().execute(
            "SELECT current_stage FROM narrative_propagation WHERE id = ?", (nid,)
        ).fetchone()
        assert rows[0] == "expert"

    def test_youtube_stage(self, tracker):
        nid = tracker.record_narrative(
            narrative="Unique youtube thesis alpha",
            source_platform="youtube",
            source_detail="test",
            affected_tickers=["GOOG"],
        )
        row = tracker._get_db().execute(
            "SELECT current_stage FROM narrative_propagation WHERE id = ?", (nid,)
        ).fetchone()
        assert row[0] == "amplified"

    def test_reddit_stage(self, tracker):
        nid = tracker.record_narrative(
            narrative="Unique reddit thesis alpha",
            source_platform="reddit",
            source_detail="test",
            affected_tickers=["TSLA"],
        )
        row = tracker._get_db().execute(
            "SELECT current_stage FROM narrative_propagation WHERE id = ?", (nid,)
        ).fetchone()
        assert row[0] == "mainstream"

    def test_stage_promotion(self, tracker):
        # Insert as expert via substack
        nid = tracker.record_narrative(
            narrative="AI infrastructure spending will extend sharply",
            source_platform="substack",
            source_detail="fab_knowledge",
            affected_tickers=["NVDA", "AVGO"],
        )
        row = tracker._get_db().execute(
            "SELECT current_stage FROM narrative_propagation WHERE id = ?", (nid,)
        ).fetchone()
        assert row[0] == "expert"

        # Same narrative from YouTube → should promote to amplified
        nid2 = tracker.record_narrative(
            narrative="AI infrastructure capex will extend sharply",
            source_platform="youtube",
            source_detail="patrick_boyle",
            affected_tickers=["NVDA", "AVGO"],
        )
        assert nid2 == nid  # Same narrative ID
        row = tracker._get_db().execute(
            "SELECT current_stage FROM narrative_propagation WHERE id = ?", (nid,)
        ).fetchone()
        assert row[0] == "amplified"

    def test_thesis_propagation_signal(self, tracker):
        """Promotion to amplified should publish thesis_propagation signal."""
        tracker.record_narrative(
            narrative="AI infrastructure spending will extend sharply",
            source_platform="substack",
            source_detail="test",
            affected_tickers=["NVDA", "AVGO"],
        )
        # Promote
        with patch("src.shared.narrative_tracker.publish") as mock_pub:
            tracker.record_narrative(
                narrative="AI infrastructure capex will extend sharply",
                source_platform="youtube",
                source_detail="test",
                affected_tickers=["NVDA", "AVGO"],
            )
            mock_pub.assert_called_once()
            call_kwargs = mock_pub.call_args
            assert call_kwargs[1]["signal_type"] == "thesis_propagation" or \
                   call_kwargs[0][0] == "thesis_propagation"

    def test_thesis_confirmed_signal(self, tracker):
        """Promotion to mainstream should publish thesis_confirmed signal."""
        # Start at amplified (youtube)
        tracker.record_narrative(
            narrative="AI infrastructure spending will extend sharply",
            source_platform="youtube",
            source_detail="test",
            affected_tickers=["NVDA", "AVGO"],
        )
        # Promote to mainstream
        with patch("src.shared.narrative_tracker.publish") as mock_pub:
            tracker.record_narrative(
                narrative="AI infrastructure capex will extend sharply",
                source_platform="reddit",
                source_detail="test",
                affected_tickers=["NVDA", "AVGO"],
            )
            mock_pub.assert_called_once()
            args, kwargs = mock_pub.call_args
            assert kwargs.get("signal_type", args[0] if args else None) == "thesis_confirmed"

    def test_confidence_increase_on_promotion(self, tracker):
        nid = tracker.record_narrative(
            narrative="AI infrastructure spending will extend sharply",
            source_platform="substack",
            source_detail="test",
            affected_tickers=["NVDA", "AVGO"],
            conviction="medium",
        )
        before = tracker._get_db().execute(
            "SELECT confidence FROM narrative_propagation WHERE id = ?", (nid,)
        ).fetchone()[0]

        # Promote via YouTube
        tracker.record_narrative(
            narrative="AI infrastructure capex will extend sharply",
            source_platform="youtube",
            source_detail="test",
            affected_tickers=["NVDA", "AVGO"],
        )
        after = tracker._get_db().execute(
            "SELECT confidence FROM narrative_propagation WHERE id = ?", (nid,)
        ).fetchone()[0]

        assert after == pytest.approx(before + 0.15)

    def test_same_stage_confidence_bump(self, tracker):
        nid = tracker.record_narrative(
            narrative="AI infrastructure spending will extend sharply",
            source_platform="substack",
            source_detail="author_a",
            affected_tickers=["NVDA", "AVGO"],
            conviction="medium",
        )
        before = tracker._get_db().execute(
            "SELECT confidence FROM narrative_propagation WHERE id = ?", (nid,)
        ).fetchone()[0]

        # Same stage substack reports again
        tracker.record_narrative(
            narrative="AI infrastructure capex will extend sharply",
            source_platform="substack",
            source_detail="author_b",
            affected_tickers=["NVDA", "AVGO"],
        )
        after = tracker._get_db().execute(
            "SELECT confidence FROM narrative_propagation WHERE id = ?", (nid,)
        ).fetchone()[0]

        assert after == pytest.approx(before + 0.05)

    def test_no_downgrade(self, tracker):
        """Mainstream seeing expert-level platform should not downgrade stage."""
        nid = tracker.record_narrative(
            narrative="AI infrastructure spending will extend sharply",
            source_platform="reddit",
            source_detail="wsb",
            affected_tickers=["NVDA", "AVGO"],
        )
        row = tracker._get_db().execute(
            "SELECT current_stage FROM narrative_propagation WHERE id = ?", (nid,)
        ).fetchone()
        assert row[0] == "mainstream"

        # Now substack reports same → should NOT downgrade
        tracker.record_narrative(
            narrative="AI infrastructure capex will extend sharply",
            source_platform="substack",
            source_detail="test",
            affected_tickers=["NVDA", "AVGO"],
        )
        row = tracker._get_db().execute(
            "SELECT current_stage FROM narrative_propagation WHERE id = ?", (nid,)
        ).fetchone()
        assert row[0] == "mainstream"


# ---------------------------------------------------------------------------
# TestPropagationFlow
# ---------------------------------------------------------------------------

class TestPropagationFlow:

    def test_full_chain(self, tracker):
        """Substack -> YouTube -> Reddit should go expert -> amplified -> mainstream."""
        nid = tracker.record_narrative(
            narrative="AI infrastructure spending will extend sharply for years",
            source_platform="substack",
            source_detail="fab_knowledge",
            affected_tickers=["NVDA", "AVGO"],
        )
        row = tracker._get_db().execute(
            "SELECT current_stage FROM narrative_propagation WHERE id = ?", (nid,)
        ).fetchone()
        assert row[0] == "expert"

        tracker.record_narrative(
            narrative="AI infrastructure capex will extend sharply ahead",
            source_platform="youtube",
            source_detail="patrick_boyle",
            affected_tickers=["NVDA", "AVGO"],
        )
        row = tracker._get_db().execute(
            "SELECT current_stage FROM narrative_propagation WHERE id = ?", (nid,)
        ).fetchone()
        assert row[0] == "amplified"

        tracker.record_narrative(
            narrative="AI infrastructure spending extend sharply going forward",
            source_platform="reddit",
            source_detail="wallstreetbets",
            affected_tickers=["NVDA", "AVGO"],
        )
        row = tracker._get_db().execute(
            "SELECT current_stage FROM narrative_propagation WHERE id = ?", (nid,)
        ).fetchone()
        assert row[0] == "mainstream"


# ---------------------------------------------------------------------------
# TestGetNarratives
# ---------------------------------------------------------------------------

class TestGetNarratives:

    def test_get_propagating_narratives_default(self, tracker):
        # Insert a narrative at amplified stage directly
        tracker.record_narrative(
            narrative="Unique amplified thesis alpha bravo",
            source_platform="youtube",
            source_detail="test",
            affected_tickers=["GOOG"],
        )
        results = tracker.get_propagating_narratives(min_stage="amplified")
        assert len(results) >= 1
        assert results[0]["current_stage"] in ("amplified", "mainstream")

    def test_get_propagating_narratives_excludes_expert(self, tracker):
        tracker.record_narrative(
            narrative="Unique expert thesis delta gamma",
            source_platform="substack",
            source_detail="test",
            affected_tickers=["AAPL"],
        )
        results = tracker.get_propagating_narratives(min_stage="amplified")
        assert all(r["current_stage"] != "expert" for r in results)

    def test_get_recent_narratives(self, tracker):
        tracker.record_narrative(
            narrative="Recent thesis about semiconductor growth",
            source_platform="substack",
            source_detail="test",
            affected_tickers=["NVDA"],
        )
        results = tracker.get_recent_narratives(days=7)
        assert len(results) >= 1
        assert results[0]["narrative"] == "Recent thesis about semiconductor growth"


# ---------------------------------------------------------------------------
# TestSignalOutcomes
# ---------------------------------------------------------------------------

class TestSignalOutcomes:

    def test_record_outcome(self, tracker):
        tracker.record_signal_outcome(
            signal_id=42, signal_type="expert_thesis", ticker="NVDA", price_at_signal=150.0,
        )
        conn = tracker._get_db()
        row = conn.execute("SELECT * FROM signal_outcomes WHERE signal_id = 42").fetchone()
        conn.close()
        assert row is not None
        assert row[3] == "NVDA"  # ticker column

    def test_update_1d_price(self, tracker):
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        conn = tracker._get_db()
        conn.execute(
            "INSERT INTO signal_outcomes "
            "(signal_id, signal_type, ticker, signal_date, price_at_signal, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (100, "expert_thesis", "NVDA", yesterday, 150.0, datetime.now().isoformat()),
        )
        conn.commit()
        conn.close()

        tracker.update_signal_outcomes("NVDA", 155.0)

        conn = tracker._get_db()
        row = conn.execute(
            "SELECT price_after_1d FROM signal_outcomes WHERE signal_id = 100"
        ).fetchone()
        conn.close()
        assert row[0] == 155.0

    def test_update_5d_price(self, tracker):
        five_days_ago = (date.today() - timedelta(days=5)).isoformat()
        conn = tracker._get_db()
        conn.execute(
            "INSERT INTO signal_outcomes "
            "(signal_id, signal_type, ticker, signal_date, price_at_signal, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (200, "expert_thesis", "AAPL", five_days_ago, 170.0, datetime.now().isoformat()),
        )
        conn.commit()
        conn.close()

        tracker.update_signal_outcomes("AAPL", 175.0)

        conn = tracker._get_db()
        row = conn.execute(
            "SELECT price_after_1d, price_after_5d FROM signal_outcomes WHERE signal_id = 200"
        ).fetchone()
        conn.close()
        assert row[0] == 175.0  # 1d also filled
        assert row[1] == 175.0  # 5d filled

    def test_update_20d_price(self, tracker):
        twenty_days_ago = (date.today() - timedelta(days=20)).isoformat()
        conn = tracker._get_db()
        conn.execute(
            "INSERT INTO signal_outcomes "
            "(signal_id, signal_type, ticker, signal_date, price_at_signal, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (300, "expert_thesis", "GOOG", twenty_days_ago, 140.0, datetime.now().isoformat()),
        )
        conn.commit()
        conn.close()

        tracker.update_signal_outcomes("GOOG", 160.0)

        conn = tracker._get_db()
        row = conn.execute(
            "SELECT price_after_1d, price_after_5d, price_after_20d FROM signal_outcomes WHERE signal_id = 300"
        ).fetchone()
        conn.close()
        assert row[0] == 160.0
        assert row[1] == 160.0
        assert row[2] == 160.0


# ---------------------------------------------------------------------------
# TestSourceReliability
# ---------------------------------------------------------------------------

class TestSourceReliability:

    def test_update_reliability(self, tracker):
        """With outcomes data, hit_rate should be calculated."""
        conn = tracker._get_db()
        five_days_ago = (date.today() - timedelta(days=6)).isoformat()
        # Insert 2 correct, 1 incorrect signal outcomes
        for i, (at_price, after_price) in enumerate([(100, 110), (100, 105), (100, 90)]):
            conn.execute(
                "INSERT INTO signal_outcomes "
                "(signal_id, signal_type, ticker, signal_date, price_at_signal, "
                "price_after_5d, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (i + 1, "test_source_expert_thesis", "NVDA", five_days_ago,
                 at_price, after_price, datetime.now().isoformat()),
            )
        conn.commit()
        conn.close()

        with patch("src.shared.narrative_tracker.publish"):
            tracker.update_source_reliability("test_source", "substack")

        results = tracker.get_source_reliability(min_signals=1)
        assert len(results) >= 1
        src = results[0]
        assert src["total_signals"] == 3
        assert src["correct_signals"] == 2
        assert src["hit_rate"] == pytest.approx(2 / 3, abs=0.01)

    def test_get_reliability_by_platform(self, tracker):
        conn = tracker._get_db()
        now = datetime.now().isoformat()
        conn.execute(
            "INSERT INTO source_reliability "
            "(source_name, source_platform, total_signals, correct_signals, hit_rate, last_updated) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("author_a", "substack", 10, 7, 0.7, now),
        )
        conn.execute(
            "INSERT INTO source_reliability "
            "(source_name, source_platform, total_signals, correct_signals, hit_rate, last_updated) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("channel_b", "youtube", 8, 3, 0.375, now),
        )
        conn.commit()
        conn.close()

        substack_results = tracker.get_source_reliability(source_platform="substack", min_signals=5)
        assert len(substack_results) == 1
        assert substack_results[0]["source_name"] == "author_a"

        youtube_results = tracker.get_source_reliability(source_platform="youtube", min_signals=5)
        assert len(youtube_results) == 1
        assert youtube_results[0]["source_name"] == "channel_b"


# ---------------------------------------------------------------------------
# TestBuildContext
# ---------------------------------------------------------------------------

class TestBuildContext:

    def test_no_narratives(self, tracker):
        result = tracker.build_narrative_context()
        assert result == "No actively propagating narratives detected."

    def test_with_propagating(self, tracker):
        # Create a narrative at amplified stage
        tracker.record_narrative(
            narrative="AI infrastructure thesis amplifying strongly across",
            source_platform="youtube",
            source_detail="test_channel",
            affected_tickers=["NVDA", "AVGO"],
        )
        result = tracker.build_narrative_context()
        assert "Propagating Narratives:" in result
        assert "NVDA" in result
        assert "AVGO" in result
        assert "amplified" in result

    def test_expert_only_not_in_context(self, tracker):
        """Expert-stage narratives should NOT appear (default min_stage is amplified)."""
        tracker.record_narrative(
            narrative="Unique expert only thesis about semiconductor growth",
            source_platform="substack",
            source_detail="test",
            affected_tickers=["QCOM"],
        )
        result = tracker.build_narrative_context()
        assert "QCOM" not in result
