"""Integration tests for AlphaDesk v2.1 changes.

Tests cover:
  - Sprint 1: Duplicate email removal, stateful mandate breach, portfolio header, html_utils
  - Sprint 2: Research depth tiering, report_style.yaml loading
  - Sprint 3: Macro commodity tickers, LunarCrush client, macro scanner, moonshot archetypes
  - Sprint 4: Idea generator, supply chain screener
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ═══════════════════════════════════════════════════════
# SPRINT 1: Fix Delivery & Noise
# ═══════════════════════════════════════════════════════


class TestDuplicateEmailRemoval:
    """Verify telegram_bot.py no longer sends email."""

    def test_no_email_send_in_telegram_bot(self):
        """Grep for email send code in telegram_bot.py — should be removed."""
        bot_path = Path("src/shared/telegram_bot.py")
        if not bot_path.exists():
            pytest.skip("telegram_bot.py not found")
        content = bot_path.read_text()
        assert "EmailReporter" not in content or content.count("EmailReporter") == 0, (
            "telegram_bot.py should not contain EmailReporter — email is sent from advisor/main.py"
        )

    def test_email_still_in_advisor_main(self):
        """advisor/main.py should still have email delivery."""
        main_path = Path("src/advisor/main.py")
        if not main_path.exists():
            pytest.skip("main.py not found")
        content = main_path.read_text()
        assert "EmailReporter" in content, "advisor/main.py should retain email delivery"


class TestStatefulMandateBreach:
    """Test stateful mandate breach detection."""

    @pytest.fixture(autouse=True)
    def _setup_db(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.advisor.memory.DB_PATH", tmp_path / "test.db")

    def test_breach_state_lifecycle(self):
        from src.advisor.memory import get_breach_state, upsert_breach_state, clear_breach_state

        # Initially no breach
        assert get_breach_state("Technology", "sector_concentration_Technology") is None

        # Record breach
        upsert_breach_state("Technology", "sector_concentration_Technology", 85.0)
        state = get_breach_state("Technology", "sector_concentration_Technology")
        assert state is not None
        assert state["last_alerted_weight"] == 85.0

        # Update breach (weight changed)
        upsert_breach_state("Technology", "sector_concentration_Technology", 90.0)
        state = get_breach_state("Technology", "sector_concentration_Technology")
        assert state["last_alerted_weight"] == 90.0

        # Clear breach
        clear_breach_state("Technology", "sector_concentration_Technology")
        assert get_breach_state("Technology", "sector_concentration_Technology") is None


class TestPortfolioHeader:
    """Verify portfolio header is replaced with minimal footer."""

    def test_no_total_header(self):
        from src.advisor.formatter import format_holdings_section

        reports = [
            {"ticker": "NVDA", "price": 100.0, "shares": 10, "entry_price": 80.0,
             "change_pct": 1.5, "position_pct": 50, "category": "core",
             "thesis_status": "intact", "thesis": "AI", "key_events": [],
             "cumulative_return_pct": 25.0},
            {"ticker": "AMZN", "price": 200.0, "shares": 5, "entry_price": 150.0,
             "change_pct": -0.5, "position_pct": 50, "category": "core",
             "thesis_status": "intact", "thesis": "Cloud", "key_events": [],
             "cumulative_return_pct": 33.0},
        ]
        result = format_holdings_section(reports)
        assert "Total:" not in result, "Portfolio header with Total should be removed"
        assert "positions tracked" in result, "Should show position count"


class TestHtmlUtils:
    """Test markdown-to-Telegram-HTML conversion."""

    def test_bold_conversion(self):
        from src.shared.html_utils import md_to_telegram_html
        assert md_to_telegram_html("**hello**") == "<b>hello</b>"

    def test_italic_conversion(self):
        from src.shared.html_utils import md_to_telegram_html
        assert md_to_telegram_html("*hello*") == "<i>hello</i>"

    def test_header_conversion(self):
        from src.shared.html_utils import md_to_telegram_html
        assert md_to_telegram_html("## Title") == "<b>Title</b>"

    def test_bullet_conversion(self):
        from src.shared.html_utils import md_to_telegram_html
        assert md_to_telegram_html("- item") == "• item"

    def test_percentage_spacing(self):
        from src.shared.html_utils import md_to_telegram_html
        assert md_to_telegram_html("5.2%driven") == "5.2% driven"

    def test_empty_input(self):
        from src.shared.html_utils import md_to_telegram_html
        assert md_to_telegram_html("") == ""


# ═══════════════════════════════════════════════════════
# SPRINT 2: Research Intelligence
# ═══════════════════════════════════════════════════════


class TestResearchDepth:
    """Test tiered research depth determination."""

    def test_deep_dive_on_large_move(self):
        from src.advisor.strategy_engine import determine_research_depth
        assert determine_research_depth({"change_pct": 5.0}) == "deep_dive"

    def test_deep_dive_on_thesis_weakening(self):
        from src.advisor.strategy_engine import determine_research_depth
        assert determine_research_depth({"thesis_status": "weakening"}) == "deep_dive"

    def test_deep_dive_on_earnings_within_7d(self):
        from src.advisor.strategy_engine import determine_research_depth
        h = {"earnings_approaching": True, "earnings_days_out": 5}
        assert determine_research_depth(h) == "deep_dive"

    def test_incremental_on_news(self):
        from src.advisor.strategy_engine import determine_research_depth
        h = {"key_events": ["Some news"], "thesis_status": "intact", "change_pct": 1.0}
        assert determine_research_depth(h) == "incremental"

    def test_status_quo_default(self):
        from src.advisor.strategy_engine import determine_research_depth
        h = {"thesis_status": "intact", "change_pct": 0.5}
        assert determine_research_depth(h) == "status_quo"

    def test_prompt_templates_exist(self):
        from src.advisor.strategy_engine import RESEARCH_PROMPTS
        assert "status_quo" in RESEARCH_PROMPTS
        assert "incremental" in RESEARCH_PROMPTS
        assert "deep_dive" in RESEARCH_PROMPTS


class TestReportStyleConfig:
    """Test report_style.yaml exists and loads."""

    def test_config_exists(self):
        assert Path("config/report_style.yaml").exists()

    def test_config_loads(self):
        import yaml
        with open("config/report_style.yaml") as f:
            config = yaml.safe_load(f)
        assert "telegram" in config
        assert "email" in config
        assert "research_depth" in config


# ═══════════════════════════════════════════════════════
# SPRINT 3: Macro Intelligence & LunarCrush
# ═══════════════════════════════════════════════════════


class TestMacroCommodityTickers:
    """Test expanded macro data tickers."""

    def test_commodity_tickers_added(self):
        from src.advisor.macro_analyst import YF_TICKERS
        assert "CL=F" in YF_TICKERS, "Oil WTI should be in YF_TICKERS"
        assert "GC=F" in YF_TICKERS, "Gold should be in YF_TICKERS"
        assert "HG=F" in YF_TICKERS, "Copper should be in YF_TICKERS"
        assert "DX-Y.NYB" in YF_TICKERS, "USD index should be in YF_TICKERS"
        assert "NG=F" in YF_TICKERS, "Natural gas should be in YF_TICKERS"


class TestLunarCrushClient:
    """Test LunarCrush API client (without real API calls)."""

    def test_no_key_returns_none(self, monkeypatch):
        monkeypatch.delenv("LUNARCRUSH_API_KEY", raising=False)
        from src.shared.lunarcrush import get_stock_social_metrics
        assert get_stock_social_metrics("AAPL") is None

    def test_no_key_returns_empty_list(self, monkeypatch):
        monkeypatch.delenv("LUNARCRUSH_API_KEY", raising=False)
        from src.shared.lunarcrush import get_trending_stocks, get_trending_topics
        assert get_trending_stocks() == []
        assert get_trending_topics() == []


class TestMacroScanner:
    """Test macro theme discovery."""

    @patch("src.advisor.macro_scanner.anthropic.Anthropic")
    def test_scan_returns_themes(self, mock_anthropic_cls):
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=json.dumps([
            {"title": "New Theme", "description": "Emerging trend",
             "affected_tickers": ["XYZ"], "confidence": 0.7, "source_signals": "news"}
        ]))]
        mock_response.usage = MagicMock(input_tokens=100, output_tokens=50)
        mock_client.messages.create.return_value = mock_response

        from src.advisor.macro_scanner import scan_for_emerging_themes
        themes = scan_for_emerging_themes(
            news_signals=[{"headline": "Test headline"}],
            existing_theses=[{"title": "Existing Thesis"}],
        )
        assert len(themes) == 1
        assert themes[0]["title"] == "New Theme"

    def test_empty_signals_returns_empty(self):
        from src.advisor.macro_scanner import scan_for_emerging_themes
        assert scan_for_emerging_themes([], []) == []


class TestMoonshotArchetypes:
    """Test non-tech moonshot archetypes."""

    def test_defense_sector_in_config(self):
        import yaml
        with open("config/advisor.yaml") as f:
            config = yaml.safe_load(f)
        sectors = config["moonshot"]["thematic_sectors"]
        assert "defense_aerospace" in sectors
        assert "gold_miners" in sectors
        assert "energy_infrastructure" in sectors
        assert "uranium" in sectors
        assert "infrastructure_build" in sectors
        assert "commodity_supercycle" in sectors

    def test_macro_driven_candidates(self):
        from src.advisor.moonshot_manager import get_macro_driven_candidates
        theses = [{"title": "Gold Price Rally", "status": "intact"}]
        mc = {"thematic_sectors": {"gold_miners": ["NEM", "GOLD"]}}
        candidates = get_macro_driven_candidates(theses, mc)
        assert len(candidates) > 0
        assert candidates[0]["ticker"] in ("NEM", "GOLD")


class TestGeopoliticalScoring:
    """Test geopolitical keyword scoring in news analyzer."""

    def test_tariff_article_scores_high(self):
        from src.news_desk.analyzer import score_geopolitical_relevance
        article = {"title": "New tariff on Chinese imports", "summary": "Trade war escalation"}
        score = score_geopolitical_relevance(article)
        assert score >= 3

    def test_normal_article_scores_zero(self):
        from src.news_desk.analyzer import score_geopolitical_relevance
        article = {"title": "Company reports Q3 earnings", "summary": "Revenue up 10%"}
        score = score_geopolitical_relevance(article)
        assert score == 0


# ═══════════════════════════════════════════════════════
# SPRINT 4: Novel Idea Generation & Supply Chain
# ═══════════════════════════════════════════════════════


class TestIdeaGenerator:
    """Test idea generator module."""

    @pytest.fixture(autouse=True)
    def _setup_db(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.advisor.memory.DB_PATH", tmp_path / "test.db")

    def test_should_run_on_first_call(self):
        from src.advisor.idea_generator import should_run_ideas
        assert should_run_ideas() is True

    def test_format_ideas_section_empty(self):
        from src.advisor.idea_generator import format_ideas_section
        assert format_ideas_section([]) == ""

    def test_format_ideas_section_with_ideas(self):
        from src.advisor.idea_generator import format_ideas_section
        ideas = [{"ticker": "XYZ", "theme": "Test Theme", "thesis": "Test thesis", "source_signals": "news"}]
        result = format_ideas_section(ideas)
        assert "NEW IDEA" in result
        assert "XYZ" in result
        assert "Test Theme" in result


class TestGeneratedIdeasMemory:
    """Test generated_ideas table in memory."""

    @pytest.fixture(autouse=True)
    def _setup_db(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.advisor.memory.DB_PATH", tmp_path / "test.db")

    def test_save_and_retrieve_ideas(self):
        from src.advisor.memory import save_generated_idea, get_recent_ideas, get_last_idea_date
        save_generated_idea(theme="AI Cooling", thesis="Test thesis", ticker="COOL")
        ideas = get_recent_ideas(lookback_days=7)
        assert len(ideas) == 1
        assert ideas[0]["theme"] == "AI Cooling"
        assert get_last_idea_date() == date.today().isoformat()


class TestSupplyChain:
    """Test supply chain module."""

    def test_supply_chain_map_exists(self):
        from src.advisor.supply_chain import SUPPLY_CHAIN_MAP
        assert "NVDA" in SUPPLY_CHAIN_MAP
        assert "suppliers" in SUPPLY_CHAIN_MAP["NVDA"]
        assert "customers" in SUPPLY_CHAIN_MAP["NVDA"]

    def test_find_second_order_plays(self):
        from src.advisor.supply_chain import find_second_order_plays
        reports = [
            {"ticker": "NVDA", "change_pct": 5.0, "sector": "Technology"},
        ]
        candidates = find_second_order_plays(reports, existing_tickers={"NVDA", "AVGO"})
        # Should find supply chain related tickers not in existing
        tickers = [c["ticker"] for c in candidates]
        assert "NVDA" not in tickers
        assert "AVGO" not in tickers

    def test_no_plays_for_small_moves(self):
        from src.advisor.supply_chain import find_second_order_plays
        reports = [
            {"ticker": "NVDA", "change_pct": 1.0},
        ]
        candidates = find_second_order_plays(reports, existing_tickers=set())
        assert len(candidates) == 0


# ═══════════════════════════════════════════════════════
# SPRINT 5: Email Template & Config
# ═══════════════════════════════════════════════════════


class TestEmailTemplate:
    """Test HTML email template."""

    def test_wrap_email_html(self):
        from src.shared.email_template import wrap_email_html
        result = wrap_email_html("<p>Hello</p>", subject="Test Report")
        assert "<!DOCTYPE html>" in result
        assert "AlphaDesk" in result
        assert "<p>Hello</p>" in result
        assert "Test Report" in result


class TestLunarCrushEnvKey:
    """Verify .env has LunarCrush key."""

    def test_env_has_lunarcrush_key(self):
        env_path = Path(".env")
        if not env_path.exists():
            pytest.skip(".env not found")
        content = env_path.read_text()
        assert "LUNARCRUSH_API_KEY" in content


class TestVersionBump:
    """Verify version string updated."""

    def test_version_is_2_1(self):
        main_path = Path("src/advisor/main.py")
        if not main_path.exists():
            pytest.skip("main.py not found")
        content = main_path.read_text()
        assert "v2.1" in content
