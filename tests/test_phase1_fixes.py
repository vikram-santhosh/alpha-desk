"""Phase 1 regression tests: thesis lookup and agent-bus source_agent key."""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from typing import Any

import pytest


def _make_agent_bus_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "agent_bus.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            signal_type TEXT NOT NULL,
            source_agent TEXT NOT NULL,
            payload TEXT NOT NULL,
            consumed INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def tmp_data_dir(monkeypatch, tmp_path):
    """Isolate the agent bus DB to a temp directory."""
    monkeypatch.setenv("ALPHADESK_DATA_DIR", str(tmp_path))
    return tmp_path


def test_thesis_lookup_uses_memory_dict_not_callable(tmp_data_dir):
    """memory['conviction_list'] is a dict-list, not a callable."""
    import importlib
    from src.advisor import memory

    memory = importlib.reload(memory)

    # Seed a holding + conviction entry so the DB has data
    memory.seed_holdings([{"ticker": "NVDA", "thesis": "AI GPU leader"}])
    memory.upsert_conviction(
        ticker="NVDA",
        conviction="high",
        thesis="AI CapEx beneficiary — dominant GPU franchise",
    )

    built = memory.build_memory_context()
    assert isinstance(built, dict)
    assert "conviction_list" in built
    assert isinstance(built["conviction_list"], list)

    ticker = "NVDA"
    thesis_text = ""
    for ce in built.get("conviction_list", []):
        if ce.get("ticker") == ticker:
            thesis_text = ce.get("thesis", "")
            break

    assert thesis_text == "AI CapEx beneficiary — dominant GPU franchise"


def test_bus_signals_use_source_agent_not_agent_name(tmp_data_dir):
    """Signals are read with source_agent, matching what agent_bus publishes."""
    import importlib

    import json

    from src.shared import agent_bus

    agent_bus = importlib.reload(agent_bus)

    # Publish signals using the same key agent_bus actually writes
    agent_bus.publish(
        signal_type="unusual_mentions",
        source_agent="street_ear",
        payload={
            "ticker": "NVDA",
            "sentiment_score": 0.7,
            "mention_count": 42,
            "subreddit": "wallstreetbets",
        },
    )
    agent_bus.publish(
        signal_type="expert_thesis",
        source_agent="substack_ear",
        payload={
            "title": "The AI buildout continues",
            "summary": "Cloud capex is accelerating",
            "tickers": ["NVDA"],
        },
    )

    signals = agent_bus.consume(mark_consumed=False)
    assert len(signals) == 2

    # Simulate the same filtering logic main.py uses after the fix
    reddit_lines = []
    substack_lines = []
    for sig in signals:
        _agent = sig.get("source_agent", "")
        _payload = sig.get("payload", {})
        if _agent == "street_ear":
            t = _payload.get("ticker") or sig.get("ticker", "")
            if t:
                reddit_lines.append(t)
        elif _agent == "substack_ear":
            title = _payload.get("title") or _payload.get("narrative_title", "")
            if title:
                substack_lines.append(title)

    assert reddit_lines == ["NVDA"]
    assert substack_lines == ["The AI buildout continues"]

    # Ensure the old key is not populated by agent_bus
    for sig in signals:
        assert "agent_name" not in sig or sig.get("agent_name") is None
        assert sig.get("source_agent") in ("street_ear", "substack_ear")
