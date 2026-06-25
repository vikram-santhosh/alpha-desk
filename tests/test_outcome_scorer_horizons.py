"""Tests for outcome_scorer horizon-accurate returns."""
from __future__ import annotations

import importlib
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest


# Global test reference date/price used by the mock yfinance history.
_REC_DATE: date | None = None
_ENTRY_PRICE: float | None = None


def _make_memory_db(db_path: Path) -> sqlite3.Connection:
    """Create a minimal advisor_memory.db with the tables we need."""
    db_path.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS recommendation_outcomes (
            id INTEGER PRIMARY KEY,
            ticker TEXT NOT NULL,
            recommendation_date TEXT NOT NULL,
            action TEXT NOT NULL,
            conviction TEXT NOT NULL,
            entry_price REAL NOT NULL,
            target_price REAL,
            thesis_summary TEXT,
            bear_case_summary TEXT,
            invalidation_conditions TEXT,
            evidence_quality_score REAL,
            composite_score REAL,
            source TEXT,
            category TEXT,
            price_1d REAL, return_1d_pct REAL,
            price_1w REAL, return_1w_pct REAL,
            price_1m REAL, return_1m_pct REAL,
            price_3m REAL, return_3m_pct REAL,
            spy_return_1d_pct REAL, alpha_1d_pct REAL,
            spy_return_1w_pct REAL, alpha_1w_pct REAL,
            spy_return_1m_pct REAL, alpha_1m_pct REAL,
            spy_return_3m_pct REAL, alpha_3m_pct REAL,
            thesis_played_out INTEGER,
            invalidation_triggered INTEGER DEFAULT 0,
            invalidation_detail TEXT,
            user_rating INTEGER,
            status TEXT DEFAULT 'open',
            closed_date TEXT,
            closed_reason TEXT,
            updated_at TEXT NOT NULL,
            UNIQUE(ticker, recommendation_date, action)
        );
    """)
    conn.commit()
    return conn


def _build_history(ticker: str, start: date, end: date) -> pd.DataFrame:
    """Build a mock yfinance history for a ticker."""
    rec_date = _REC_DATE or start
    entry_price = _ENTRY_PRICE or {"NVDA": 100.0, "SPY": 400.0}.get(ticker, 50.0)
    days = []
    current = start
    while current <= end:
        days.append(current)
        current += timedelta(days=1)

    def price_for(day: date) -> float:
        delta = (day - rec_date).days
        if ticker == "NVDA":
            return entry_price + delta * 0.5
        if ticker == "SPY":
            return entry_price + delta * 0.2
        return entry_price

    df = pd.DataFrame({
        "Close": [price_for(d) for d in days],
    }, index=pd.to_datetime(days))
    return df


def _mock_ticker(ticker: str):
    """Return a mock yfinance.Ticker that serves deterministic price history."""
    mock = MagicMock()

    def history(*, start=None, end=None, period=None, **kwargs):
        if period == "5d":
            end_date = date.today()
            start_date = end_date - timedelta(days=5)
        else:
            start_date = datetime.fromisoformat(start).date() if start else date.today() - timedelta(days=7)
            end_date = datetime.fromisoformat(end).date() if end else date.today() + timedelta(days=1)
        return _build_history(ticker, start_date, end_date)

    mock.history = history
    return mock


def _reload_memory(monkeypatch, tmp_path):
    monkeypatch.setenv("ALPHADESK_DATA_DIR", str(tmp_path))
    memory = importlib.import_module("src.advisor.memory")
    return importlib.reload(memory)


def test_score_all_outcomes_uses_horizon_prices(monkeypatch, tmp_path):
    """Return columns for different horizons must reflect as-of-date prices, not today's price."""
    global _REC_DATE, _ENTRY_PRICE

    memory = _reload_memory(monkeypatch, tmp_path)
    db_path = tmp_path / "advisor_memory.db"
    conn = _make_memory_db(db_path)
    monkeypatch.setattr(memory, "DB_PATH", db_path)

    today = date.today()
    rec_date = today - timedelta(days=95)
    entry_price = 100.0
    _REC_DATE = rec_date
    _ENTRY_PRICE = entry_price

    conn.execute("""
        INSERT INTO recommendation_outcomes
        (ticker, recommendation_date, action, conviction, entry_price, status, updated_at)
        VALUES (?, ?, 'buy', 'high', ?, 'open', ?)
    """, ("NVDA", rec_date.isoformat(), entry_price, datetime.now().isoformat()))
    conn.commit()
    conn.close()

    scorer = importlib.import_module("src.advisor.outcome_scorer")
    scorer = importlib.reload(scorer)

    with patch("yfinance.Ticker", side_effect=_mock_ticker):
        scorecard = scorer.score_all_outcomes()

    _REC_DATE = None
    _ENTRY_PRICE = None

    rec = memory.get_recommendations_by_ticker("NVDA")[0]

    assert rec["price_1d"] is not None
    assert rec["price_1w"] is not None
    assert rec["price_1m"] is not None
    assert rec["price_3m"] is not None

    assert rec["return_1d_pct"] < rec["return_1w_pct"] < rec["return_1m_pct"] < rec["return_3m_pct"]

    assert rec["return_1d_pct"] == pytest.approx(0.5, abs=0.01)
    assert rec["return_1w_pct"] == pytest.approx(3.5, abs=0.01)
    assert rec["return_1m_pct"] == pytest.approx(15.0, abs=0.01)
    assert rec["return_3m_pct"] == pytest.approx(45.0, abs=0.01)

    assert rec["spy_return_1d_pct"] is not None
    assert rec["spy_return_1w_pct"] is not None
    assert rec["spy_return_1m_pct"] is not None
    assert rec["spy_return_3m_pct"] is not None

    assert rec["alpha_1d_pct"] == pytest.approx(rec["return_1d_pct"] - rec["spy_return_1d_pct"], abs=0.01)
    assert rec["alpha_1w_pct"] == pytest.approx(rec["return_1w_pct"] - rec["spy_return_1w_pct"], abs=0.01)
    assert rec["alpha_1m_pct"] == pytest.approx(rec["return_1m_pct"] - rec["spy_return_1m_pct"], abs=0.01)
    assert rec["alpha_3m_pct"] == pytest.approx(rec["return_3m_pct"] - rec["spy_return_3m_pct"], abs=0.01)



def test_score_all_outcomes_skips_missing_horizon_price(monkeypatch, tmp_path):
    """If a horizon price cannot be fetched, the column is left null (no backfill)."""
    memory = _reload_memory(monkeypatch, tmp_path)
    db_path = tmp_path / "advisor_memory.db"
    conn = _make_memory_db(db_path)
    monkeypatch.setattr(memory, "DB_PATH", db_path)

    today = date.today()
    rec_date = today - timedelta(days=35)

    conn.execute("""
        INSERT INTO recommendation_outcomes
        (ticker, recommendation_date, action, conviction, entry_price, status, updated_at)
        VALUES (?, ?, 'buy', 'medium', 100.0, 'open', ?)
    """, ("FAKECO", rec_date.isoformat(), datetime.now().isoformat()))
    conn.commit()
    conn.close()

    scorer = importlib.import_module("src.advisor.outcome_scorer")
    scorer = importlib.reload(scorer)

    def empty_ticker(ticker: str):
        mock = MagicMock()
        mock.history.return_value = pd.DataFrame({"Close": []})
        return mock

    with patch("yfinance.Ticker", side_effect=empty_ticker):
        scorer.score_all_outcomes()

    rec = memory.get_recommendations_by_ticker("FAKECO")[0]
    assert rec["price_1m"] is None
    assert rec["return_1m_pct"] is None
