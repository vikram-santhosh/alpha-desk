from __future__ import annotations

import importlib


class _FakeResponse:
    status_code = 200
    text = ""

    def json(self):
        return {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000},
        }


def test_openrouter_alias_costs_are_recorded_with_resolved_model(monkeypatch, tmp_path):
    captured: dict[str, object] = {}

    def fake_post(url, *, headers, json, timeout):
        captured["url"] = url
        captured["model"] = json["model"]
        captured["messages"] = json["messages"]
        return _FakeResponse()

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("ALPHADESK_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("requests.post", fake_post)

    gemini_compat = importlib.reload(importlib.import_module("src.shared.gemini_compat"))
    cost_tracker = importlib.reload(importlib.import_module("src.shared.cost_tracker"))
    monkeypatch.setattr(cost_tracker, "_load_daily_cap", lambda: 20.0)

    client = gemini_compat.Anthropic()
    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=128,
        messages=[{"role": "user", "content": "hello"}],
        temperature=0.2,
    )

    assert captured["model"] == "moonshotai/kimi-k2.6"
    assert response.model == "moonshotai/kimi-k2.6"
    assert response.content[0].text == "ok"
    assert response.usage.input_tokens == 1_000_000

    cost = cost_tracker.record_usage(
        "unit_test_agent",
        response.usage.input_tokens,
        response.usage.output_tokens,
        model="claude-opus-4-6",
        response=response,
    )

    assert cost == 2.65
    assert cost_tracker.get_budget_pressure() == 2.65 / 20.0
