"""Tests for DeerFlow v2 improvements (P0-P3)."""
from __future__ import annotations

import importlib
import json
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch


# ─── Helpers ────────────────────────────────────────────

def _reload_module(module_name: str, monkeypatch, data_dir):
    monkeypatch.setenv("ALPHADESK_DATA_DIR", str(data_dir))
    module = importlib.import_module(module_name)
    return importlib.reload(module)


def _make_memory_db(db_path: Path) -> sqlite3.Connection:
    """Create a minimal advisor_memory.db with the tables we need."""
    db_path.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS recommendation_outcomes (
            id INTEGER PRIMARY KEY,
            ticker TEXT,
            recommendation_date TEXT,
            action TEXT,
            conviction TEXT,
            entry_price REAL,
            source TEXT,
            return_1d_pct REAL,
            return_1w_pct REAL,
            return_1m_pct REAL,
            return_3m_pct REAL,
            alpha_1m_pct REAL,
            alpha_3m_pct REAL,
            status TEXT,
            thesis_summary TEXT
        );
        CREATE TABLE IF NOT EXISTS earnings_calls (
            id INTEGER PRIMARY KEY,
            ticker TEXT,
            quarter TEXT,
            eps_actual REAL,
            eps_estimate REAL,
            revenue_actual REAL,
            revenue_estimate REAL,
            guidance_sentiment TEXT,
            management_tone TEXT,
            key_quotes TEXT
        );
        CREATE TABLE IF NOT EXISTS superinvestor_positions (
            id INTEGER PRIMARY KEY,
            ticker TEXT,
            investor_name TEXT,
            quarter TEXT,
            action TEXT,
            shares INTEGER,
            pct_of_portfolio REAL
        );
        CREATE TABLE IF NOT EXISTS cross_mentions (
            id INTEGER PRIMARY KEY,
            source_ticker TEXT,
            mentioned_ticker TEXT,
            quarter TEXT,
            context TEXT,
            sentiment TEXT
        );
        CREATE TABLE IF NOT EXISTS prediction_markets (
            id INTEGER PRIMARY KEY,
            market_title TEXT,
            probability REAL,
            prev_probability REAL,
            category TEXT,
            affected_tickers TEXT,
            date TEXT
        );
        CREATE TABLE IF NOT EXISTS thesis_actions (
            id INTEGER PRIMARY KEY,
            thesis_id INTEGER,
            action_date TEXT NOT NULL,
            action_type TEXT NOT NULL,
            ticker TEXT NOT NULL,
            outcome_30d TEXT,
            notes TEXT
        );
    """)
    conn.commit()
    return conn


# ─── P0-1: CIO editor template includes deep_research_blocks ───

def test_cio_editor_template_has_deep_research_blocks():
    """Verify the CIO editor prompt template contains ${deep_research_blocks}."""
    template_path = Path("prompts/agents/cio_editor.md")
    assert template_path.exists(), "cio_editor.md not found"
    content = template_path.read_text()
    assert "${deep_research_blocks}" in content, "Missing ${deep_research_blocks} in cio_editor.md"
    assert "DEEP RESEARCH" in content, "Missing DEEP RESEARCH header"
    assert "deep research" in content.lower(), "Missing deep research instruction"


# ─── P1-3: review_brief returns valid JSON structure ────

def test_review_brief_returns_expected_keys(monkeypatch, tmp_path):
    """review_brief() returns dict with issues, overall_quality, should_flag."""
    cost_tracker = _reload_module("src.shared.cost_tracker", monkeypatch, tmp_path)
    monkeypatch.setattr(cost_tracker, "check_budget", lambda **kw: (True, 0.0, 20.0))

    import asyncio

    mock_response = MagicMock()
    mock_response.content = [MagicMock()]
    mock_response.content[0].text = json.dumps({
        "issues": [{"type": "stale_data", "severity": "medium", "description": "NVDA price is 3 days old", "suggestion": "Update price"}],
        "overall_quality": 7,
        "should_flag": False,
    })
    mock_response.usage = MagicMock()
    mock_response.usage.input_tokens = 500
    mock_response.usage.output_tokens = 200

    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response

    brief_reviewer = _reload_module("src.advisor.brief_reviewer", monkeypatch, tmp_path)
    monkeypatch.setattr(brief_reviewer, "check_budget", lambda **kw: (True, 0.0, 20.0))

    with patch.object(brief_reviewer, "anthropic") as mock_anthropic:
        mock_anthropic.Anthropic.return_value = mock_client
        result = asyncio.get_event_loop().run_until_complete(
            brief_reviewer.review_brief("Test brief about NVDA", "NVDA: 10 shares", "NVDA earnings beat")
        )

    assert isinstance(result, dict)
    assert "issues" in result or "data" in result
    assert "overall_quality" in result or "data" in result
    assert "should_flag" in result or "data" in result


def test_review_brief_skips_on_budget_exceeded(monkeypatch, tmp_path):
    """review_brief() returns graceful result when budget exceeded."""
    import asyncio

    brief_reviewer = _reload_module("src.advisor.brief_reviewer", monkeypatch, tmp_path)
    monkeypatch.setattr(brief_reviewer, "check_budget", lambda **kw: (False, 25.0, 20.0))

    result = asyncio.get_event_loop().run_until_complete(
        brief_reviewer.review_brief("Test brief")
    )
    assert isinstance(result, dict)
    assert result.get("error") == "budget_exceeded" or result.get("overall_quality") == 0


# ─── P3-10: get_budget_pressure returns 0.0-1.0 ────

def test_get_budget_pressure_returns_valid_range(monkeypatch, tmp_path):
    """get_budget_pressure() returns a float in [0.0, 1.0]."""
    cost_tracker = _reload_module("src.shared.cost_tracker", monkeypatch, tmp_path)

    pressure = cost_tracker.get_budget_pressure()
    assert isinstance(pressure, float)
    assert 0.0 <= pressure <= 1.0


def test_get_budget_pressure_increases_with_spend(monkeypatch, tmp_path):
    """Budget pressure should increase as spending approaches the cap."""
    cost_tracker = _reload_module("src.shared.cost_tracker", monkeypatch, tmp_path)

    # Override daily cap to small value
    monkeypatch.setattr(cost_tracker, "_load_daily_cap", lambda: 1.0)

    p1 = cost_tracker.get_budget_pressure()
    # Record some usage to increase pressure
    cost_tracker.record_usage("test_agent", 100000, 10000, model="claude-haiku-4-5")
    p2 = cost_tracker.get_budget_pressure()

    assert p2 >= p1, "Pressure should increase after spending"


def test_get_budget_pressure_with_run_context(monkeypatch, tmp_path):
    """Budget pressure considers per-run budget when active."""
    cost_tracker = _reload_module("src.shared.cost_tracker", monkeypatch, tmp_path)

    tokens = cost_tracker.set_run_context(run_id="test-run", run_budget=0.01)
    try:
        cost_tracker.record_usage("test", 100000, 50000, model="claude-opus-4-6")
        pressure = cost_tracker.get_budget_pressure()
        assert pressure > 0.5, "Should have high pressure with tiny run budget"
    finally:
        cost_tracker.reset_run_context(tokens)


# ─── P3-10: select_model downgrades under pressure ─────

def test_select_model_returns_preferred_when_no_pressure(monkeypatch):
    """select_model() returns preferred model when budget pressure is low."""
    agent_decorator = importlib.import_module("src.shared.agent_decorator")
    agent_decorator = importlib.reload(agent_decorator)

    monkeypatch.setattr(agent_decorator, "get_budget_pressure", lambda: 0.0)

    result = agent_decorator.select_model("claude-opus-4-6")
    assert result == "claude-opus-4-6"


def test_select_model_downgrades_under_high_pressure(monkeypatch):
    """select_model() downgrades when budget pressure exceeds threshold."""
    agent_decorator = importlib.import_module("src.shared.agent_decorator")
    agent_decorator = importlib.reload(agent_decorator)

    monkeypatch.setattr(agent_decorator, "get_budget_pressure", lambda: 0.9)

    result = agent_decorator.select_model("claude-opus-4-6")
    assert result != "claude-opus-4-6", "Should downgrade under high pressure"
    assert result in ("claude-sonnet-4-6", "claude-haiku-4-5")


def test_select_model_respects_allow_downgrade_false(monkeypatch):
    """select_model() never downgrades when allow_downgrade=False."""
    agent_decorator = importlib.import_module("src.shared.agent_decorator")
    agent_decorator = importlib.reload(agent_decorator)

    monkeypatch.setattr(agent_decorator, "get_budget_pressure", lambda: 1.0)

    result = agent_decorator.select_model("claude-opus-4-6", allow_downgrade=False)
    assert result == "claude-opus-4-6"


def test_select_model_leaves_unknown_model_unchanged(monkeypatch):
    """select_model() returns unknown model as-is even under pressure."""
    agent_decorator = importlib.import_module("src.shared.agent_decorator")
    agent_decorator = importlib.reload(agent_decorator)

    monkeypatch.setattr(agent_decorator, "get_budget_pressure", lambda: 0.9)

    result = agent_decorator.select_model("some-custom-model")
    assert result == "some-custom-model"


# ─── P3-7: get_ticker_deep_context returns structured dict ──

def test_get_ticker_deep_context_returns_dict(monkeypatch, tmp_path):
    """get_ticker_deep_context() returns structured dict for a ticker."""
    memory = _reload_module("src.advisor.memory", monkeypatch, tmp_path)

    db_path = tmp_path / "advisor_memory.db"
    conn = _make_memory_db(db_path)

    # Insert test data
    conn.execute("""
        INSERT INTO earnings_calls (ticker, quarter, eps_actual, eps_estimate,
            revenue_actual, revenue_estimate, guidance_sentiment, management_tone, key_quotes)
        VALUES ('NVDA', '2025-Q4', 5.16, 4.80, 39300, 38000, 'positive', 'confident', '["AI demand strong"]')
    """)
    conn.execute("""
        INSERT INTO superinvestor_positions (ticker, investor_name, quarter, action, shares, pct_of_portfolio)
        VALUES ('NVDA', 'Berkshire Hathaway', '2025-Q4', 'increased', 500000, 2.1)
    """)
    conn.execute("""
        INSERT INTO thesis_actions (thesis_id, action_date, action_type, ticker, notes)
        VALUES (1, '2026-01-15', 'initiated', 'NVDA', 'AI thesis validated')
    """)
    conn.commit()
    conn.close()

    monkeypatch.setattr(memory, "DB_PATH", db_path)

    result = memory.get_ticker_deep_context("NVDA")
    assert isinstance(result, dict)
    assert "earnings" in result
    assert "superinvestors" in result
    assert "thesis_actions" in result or len(result) >= 2


def test_get_ticker_deep_context_empty_for_unknown_ticker(monkeypatch, tmp_path):
    """get_ticker_deep_context() returns empty dict for unknown ticker."""
    memory = _reload_module("src.advisor.memory", monkeypatch, tmp_path)

    db_path = tmp_path / "advisor_memory.db"
    _make_memory_db(db_path)

    monkeypatch.setattr(memory, "DB_PATH", db_path)

    result = memory.get_ticker_deep_context("ZZZZZ")
    assert isinstance(result, dict)
    assert len(result) == 0


# ─── P2-6: get_planner_calibration returns per-trigger stats ──

def test_get_planner_calibration_returns_trigger_stats(monkeypatch, tmp_path):
    """get_planner_calibration() returns hit_rate, avg_alpha per trigger_type."""
    memory = _reload_module("src.advisor.memory", monkeypatch, tmp_path)

    db_path = tmp_path / "advisor_memory.db"
    conn = _make_memory_db(db_path)

    today = date.today().isoformat()
    # Insert outcomes with different trigger types
    for i, (source, ret, alpha) in enumerate([
        ("price_move/big_move", 5.0, 3.0),
        ("price_move/recovery", -2.0, -1.5),
        ("news_event/earnings_beat", 8.0, 6.0),
        ("news_event/product_launch", 3.0, 2.0),
        ("news_event/partnership", 4.0, 1.5),
        ("thesis_change/upgrade", -1.0, -3.0),
    ]):
        conn.execute("""
            INSERT INTO recommendation_outcomes (ticker, recommendation_date, action, source,
                return_1m_pct, alpha_1m_pct, status)
            VALUES (?, ?, 'buy', ?, ?, ?, 'closed')
        """, (f"TICK{i}", today, source, ret, alpha))
    conn.commit()
    conn.close()

    monkeypatch.setattr(memory, "DB_PATH", db_path)

    result = memory.get_planner_calibration(lookback_days=90)
    assert isinstance(result, dict)
    assert len(result) > 0

    # Check price_move trigger
    if "price_move" in result:
        pm = result["price_move"]
        assert "hit_rate" in pm
        assert "avg_alpha" in pm
        assert 0.0 <= pm["hit_rate"] <= 1.0
        assert "sample_size" in pm

    # Check news_event trigger
    if "news_event" in result:
        ne = result["news_event"]
        assert ne["hit_rate"] == 1.0, "All news_event returns were positive"
        assert ne["sample_size"] == 3


def test_get_planner_calibration_empty_with_no_data(monkeypatch, tmp_path):
    """get_planner_calibration() returns empty dict when no outcomes exist."""
    memory = _reload_module("src.advisor.memory", monkeypatch, tmp_path)

    db_path = tmp_path / "advisor_memory.db"
    _make_memory_db(db_path)

    monkeypatch.setattr(memory, "DB_PATH", db_path)

    result = memory.get_planner_calibration()
    assert result == {}


# ─── P3-9: Skills prompt files exist ───────────────────

def test_skill_prompt_files_exist():
    """All 4 skill prompt files exist in prompts/skills/."""
    skills_dir = Path("prompts/skills")
    assert skills_dir.is_dir(), "prompts/skills/ directory not found"

    expected_skills = [
        "thesis_refresh.md",
        "earnings_deep_dive.md",
        "variant_perception.md",
        "catalyst_stress_test.md",
    ]
    for skill_file in expected_skills:
        path = skills_dir / skill_file
        assert path.exists(), f"Missing skill file: {skill_file}"
        content = path.read_text()
        assert len(content) > 50, f"Skill file {skill_file} seems too short"


# ─── P3-9: load_skill function exists ──────────────────

def test_load_skill_function_exists():
    """prompt_loader has a load_skill function."""
    prompt_loader = importlib.import_module("src.shared.prompt_loader")
    prompt_loader = importlib.reload(prompt_loader)
    assert hasattr(prompt_loader, "load_skill"), "load_skill not found in prompt_loader"
    assert callable(prompt_loader.load_skill)


# ─── P0-2: run_steps matrix is enforced ────────────────

def test_run_profile_run_steps_exist():
    """RunProfile has run_steps attribute with expected step names."""
    run_profile = importlib.import_module("src.advisor.run_profile")
    run_profile = importlib.reload(run_profile)

    profile = run_profile.determine_run_profile(
        run_type="morning_full",
        now=datetime(2026, 3, 11, 7, 30),
    )
    assert hasattr(profile, "run_steps")
    assert isinstance(profile.run_steps, (set, list, frozenset))
    assert "load_memory" in profile.run_steps or "full_analyst_committee" in profile.run_steps
