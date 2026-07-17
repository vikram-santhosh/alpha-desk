from __future__ import annotations

import importlib

from fastapi.testclient import TestClient


def test_alerts_flag_overweight_positions(monkeypatch):
    app = importlib.reload(importlib.import_module("src.api.app"))

    monkeypatch.setattr(
        app,
        "get_portfolio",
        lambda: app.PortfolioSnapshot(
            positions=[
                app.Position(ticker="NVDA", weight_pct=31.8),
                app.Position(ticker="MSFT", weight_pct=10.0),
            ],
            top_holding_pct=31.8,
            top3_pct=50.0,
            concentration_flag=True,
        ),
    )
    monkeypatch.setattr(app, "_portfolio_threshold", lambda: 15.0)
    monkeypatch.setattr(app, "_db_strategy_alerts", lambda: [])

    client = TestClient(app.app)
    response = client.get("/api/alerts")
    assert response.status_code == 200
    data = response.json()
    # NVDA 31.8 > 15 (and > 22.5) -> critical; MSFT 10 < 15 -> no alert
    assert len(data) == 1
    alert = data[0]
    assert alert["ticker"] == "NVDA"
    assert alert["severity"] == "critical"
    assert alert["currentValue"] == 31.8
    assert alert["thresholdValue"] == 15.0
    assert alert["metric"] == "Position weight"


def test_alerts_merges_db_flags(monkeypatch):
    app = importlib.reload(importlib.import_module("src.api.app"))
    monkeypatch.setattr(
        app,
        "get_portfolio",
        lambda: app.PortfolioSnapshot(positions=[], top_holding_pct=0.0, top3_pct=0.0, concentration_flag=False),
    )
    monkeypatch.setattr(
        app,
        "_db_strategy_alerts",
        lambda: [app.AlertOut(id="x", ticker="ABC", metric="Thesis", severity="warning", firstTriggeredAt="2026", description="d")],
    )
    client = TestClient(app.app)
    data = client.get("/api/alerts").json()
    assert [a["ticker"] for a in data] == ["ABC"]
