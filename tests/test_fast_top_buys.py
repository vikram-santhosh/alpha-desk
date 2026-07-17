from __future__ import annotations

import importlib

from fastapi.testclient import TestClient


def test_score_result_maps_to_cards_with_real_evidence():
    app = importlib.reload(importlib.import_module("src.api.app"))
    result = {
        "top": [
            {
                "ticker": "NVDA",
                "score": 8.4,
                "platforms_reporting": ["earnings", "valuation"],
                "breakdown": [
                    {"sensor": "earnings", "direction": "BULL", "evidence": "EPS beat +26%"},
                    {"sensor": "valuation", "direction": "BEAR", "evidence": "Rich on FCF"},
                ],
            },
            {
                "ticker": "MU",
                "score": 7.2,
                "platforms_reporting": ["earnings"],
                "breakdown": [{"sensor": "earnings", "direction": "BULL", "evidence": "Memory upcycle"}],
            },
        ]
    }
    out = app._idea_scout_from_score_result(result, 12)
    assert out.scout_mode == "top_buys"
    assert [i.ticker for i in out.ideas] == ["NVDA", "MU"]
    nvda = out.ideas[0]
    assert abs(nvda.score - 0.84) < 1e-9
    assert "EPS beat +26%" in nvda.catalysts
    assert "Rich on FCF" in nvda.risks
    assert nvda.source == "score_engine"
    # Not the old "Alpha Scout composite score X" boilerplate.
    assert "composite score" not in nvda.thesis.lower()


def test_fast_top_buys_endpoint(monkeypatch):
    app = importlib.reload(importlib.import_module("src.api.app"))

    async def fake_result(limit):
        return {
            "top": [
                {
                    "ticker": "AAPL",
                    "score": 9.0,
                    "platforms_reporting": ["news"],
                    "breakdown": [{"sensor": "news", "direction": "BULL", "evidence": "Strong guidance"}],
                }
            ]
        }

    monkeypatch.setattr(app, "_fast_score_result", fake_result)
    client = TestClient(app.app)
    response = client.get("/api/ideas/fast?limit=5")
    assert response.status_code == 200
    data = response.json()
    assert data["ideas"][0]["ticker"] == "AAPL"
    assert data["ideas"][0]["source"] == "score_engine"
    assert "Strong guidance" in data["ideas"][0]["catalysts"]
    assert data["data_source_checks"][0]["status"] == "validated"
