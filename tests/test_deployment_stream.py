from __future__ import annotations

import importlib

from fastapi.testclient import TestClient

from src.advisor import deployment_planner as dp


class _StreamResp:
    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    def raise_for_status(self) -> None:
        pass

    def iter_lines(self, decode_unicode: bool = False):
        yield from self._lines


def test_synthesize_stream_parses_sse_and_accumulates(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    lines = [
        ": OPENROUTER PROCESSING",  # keep-alive comment — ignored
        'data: {"choices":[{"delta":{"content":"# Plan\\n"}}]}',
        'data: {"choices":[{"delta":{"content":"Bottom line."}}]}',
        'data: {"usage":{"prompt_tokens":100,"completion_tokens":50},"choices":[{"delta":{}}]}',
        "data: [DONE]",
    ]
    monkeypatch.setattr(dp.requests, "post", lambda *a, **k: _StreamResp(lines))
    monkeypatch.setattr("src.shared.cost_tracker.record_usage", lambda *a, **k: 0.0123)

    items = list(dp._synthesize_stream(dp.DeploymentInputs(capital=100_000), {"mandate": {}}))
    deltas = [i for i in items if isinstance(i, str)]
    done = items[-1]
    assert deltas == ["# Plan\n", "Bottom line."]
    assert isinstance(done, dict) and done["done"] is True
    assert done["markdown"] == "# Plan\nBottom line."
    assert done["cost"] == 0.0123


def test_deployment_stream_endpoint_emits_sse_events(monkeypatch):
    app = importlib.reload(importlib.import_module("src.api.app"))

    monkeypatch.setattr(dp, "_load_current_holdings", lambda: [{"ticker": "NVDA"}])

    async def fake_candidates():
        return {"ideas": []}

    async def fake_sentiment(tickers):
        return {}

    def fake_pack(inputs, candidates, sentiment):
        return {"generated_at": "2026-06-28", "mandate": {"capital": inputs.capital}, "diagnosis": {}, "candidate_ideas": {"ideas": []}, "macro": {}}

    def fake_stream(inputs, pack):
        yield "# Plan\n"
        yield "Body."
        yield {"done": True, "markdown": "# Plan\nBody.", "cost": 0.01}

    monkeypatch.setattr(dp, "_candidate_ideas", fake_candidates)
    monkeypatch.setattr(dp, "_holdings_sentiment", fake_sentiment)
    monkeypatch.setattr(dp, "build_evidence_pack", fake_pack)
    monkeypatch.setattr(dp, "_synthesize_stream", fake_stream)
    monkeypatch.setattr(app.deployment_store, "save_deployment_run", lambda payload: (9, "2026-06-28T00:00:00"))

    client = TestClient(app.app)
    response = client.get("/api/deployment/stream?capital=100000")
    assert response.status_code == 200
    body = response.text
    assert "event: progress" in body
    assert "event: chunk" in body
    assert "event: done" in body
    assert "Plan" in body
