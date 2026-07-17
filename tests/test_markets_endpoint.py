from __future__ import annotations

import importlib

from fastapi.testclient import TestClient


def test_markets_payload_maps_and_normalizes():
    app = importlib.import_module("src.api.app")
    raw = [
        {"platform": "polymarket", "title": "Fed cuts by July?", "probability": 0.42, "url": "https://poly/x"},
        {"platform": "kalshi", "title": "Recession in 2026?", "probability": 63.0},  # already 0-100
        {"title": ""},  # skipped (no title)
        "notadict",  # skipped
    ]
    out = app._markets_payload(raw)
    assert len(out) == 2
    assert out[0].question == "Fed cuts by July?"
    assert out[0].probability == 42.0  # 0.42 -> 42
    assert out[0].modelEstimate == 42.0
    assert out[0].source == "Polymarket"
    assert out[0].id == "https://poly/x"
    assert len(out[0].sevenDaySparkline) == 2
    assert out[1].probability == 63.0  # already 0-100, left as-is


def test_markets_endpoint(monkeypatch):
    app = importlib.reload(importlib.import_module("src.api.app"))
    monkeypatch.setattr(
        "src.advisor.prediction_market.fetch_prediction_markets",
        lambda cfg: [{"platform": "kalshi", "title": "X?", "probability": 0.5}],
    )
    client = TestClient(app.app)
    response = client.get("/api/markets")
    assert response.status_code == 200
    data = response.json()
    assert data[0]["question"] == "X?"
    assert data[0]["probability"] == 50.0
    assert data[0]["source"] == "Kalshi"
