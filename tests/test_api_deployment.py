from __future__ import annotations

import importlib

from fastapi.testclient import TestClient


def test_deployment_plan_persists_payload(monkeypatch):
    api_app = importlib.reload(importlib.import_module("src.api.app"))

    async def fake_generate(inputs):
        # Echo a couple of input fields so we can assert they were threaded through.
        assert inputs.capital == 100000.0
        return {
            "markdown": "# Deployment Plan\n\nBottom line: deploy carefully.",
            "model": "z-ai/glm-5.2",
            "cost_usd": 0.0123,
            "generated_at": "2026-06-27T09:00:00+00:00",
            "evidence_pack": {
                "mandate": {"capital": 100000.0, "return_target": "30-40%"},
                "diagnosis": {"hhi": 2500.0, "top1_pct": 45.0, "top3_pct": 77.0, "n_holdings": 6},
                "candidate_ideas": {"ideas": [{"ticker": "ABC"}, {"ticker": "XYZ"}]},
                "macro": {"note": "no live macro in pack — analyst judgment"},
            },
        }

    monkeypatch.setattr("src.advisor.deployment_planner.generate_deployment_plan", fake_generate)
    monkeypatch.setattr(
        api_app.deployment_store, "save_deployment_run", lambda payload: (5, "2026-06-27T09:00:01")
    )
    client = TestClient(api_app.app)

    response = client.post("/api/deployment/plan", json={"capital": 100000})

    assert response.status_code == 200
    payload = response.json()
    assert payload["run_id"] == 5
    assert payload["model"] == "z-ai/glm-5.2"
    assert payload["markdown"].startswith("# Deployment Plan")
    assert payload["cost_usd"] == 0.0123
    assert payload["mandate"]["capital"] == 100000.0
    assert payload["stats"]["top1_pct"] == 45.0
    assert payload["stats"]["candidate_count"] == 2
    # The macro "note" should surface as a degraded reason, not be silently dropped.
    assert any("Macro" in reason for reason in payload["degraded_reasons"])


def test_latest_deployment_404(monkeypatch):
    api_app = importlib.reload(importlib.import_module("src.api.app"))
    monkeypatch.setattr(api_app.deployment_store, "latest_deployment_run", lambda: None)
    client = TestClient(api_app.app)

    response = client.get("/api/deployment/runs/latest")

    assert response.status_code == 404
    assert response.json()["detail"] == "No saved deployment plan found."
