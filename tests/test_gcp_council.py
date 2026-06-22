from __future__ import annotations

import asyncio
import importlib


def _reload_registry(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "alpha-test")
    monkeypatch.setenv("COUNCIL_ENABLED", "true")
    module = importlib.import_module("src.shared.model_registry")
    return importlib.reload(module)


def test_gcp_council_roster_defaults_to_gemini_claude_grok(monkeypatch):
    registry = _reload_registry(monkeypatch)

    roster = registry.enabled_roster(require_gcp_project=True)

    assert [spec.provider for spec in roster] == [
        registry.CouncilProvider.GCP_GEMINI,
        registry.CouncilProvider.GCP_CLAUDE,
        registry.CouncilProvider.GCP_GROK,
    ]
    assert [spec.model_id for spec in roster] == [
        "gemini-3.1-pro-preview",
        "claude-opus-4-8",
        "xai/grok-4.20-reasoning",
    ]


def test_gcp_council_requires_project_for_runtime_roster(monkeypatch):
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT_ID", raising=False)
    registry = importlib.reload(importlib.import_module("src.shared.model_registry"))

    try:
        registry.enabled_roster(require_gcp_project=True)
    except RuntimeError as exc:
        assert "GOOGLE_CLOUD_PROJECT" in str(exc)
    else:
        raise AssertionError("enabled_roster should require a GCP project")


def test_gcp_council_default_path_requires_enabled_flag(monkeypatch):
    registry = _reload_registry(monkeypatch)
    monkeypatch.setenv("COUNCIL_ENABLED", "false")
    importlib.reload(registry)
    council = importlib.reload(importlib.import_module("src.advisor.council"))

    try:
        asyncio.get_event_loop().run_until_complete(
            council.GCPCouncilClient(timeout_s=1).deliberate(
                council.CouncilRequest(prompt="Rate NVDA"),
            )
        )
    except RuntimeError as exc:
        assert "COUNCIL_ENABLED=true" in str(exc)
    else:
        raise AssertionError("default council path should require COUNCIL_ENABLED")


def test_gcp_council_fans_out_to_all_roster_members(monkeypatch):
    registry = _reload_registry(monkeypatch)
    council = importlib.reload(importlib.import_module("src.advisor.council"))
    calls = []

    def fake_call(self, spec, request):
        calls.append((spec.provider, request.prompt))
        return council.CouncilResponse(
            provider=spec.provider,
            model=spec.model_id,
            label=spec.label,
            text=f"{spec.label}: hold",
            input_tokens=10,
            output_tokens=5,
        )

    monkeypatch.setattr(council.GCPCouncilClient, "_call_model", fake_call)

    roster = registry.enabled_roster(require_gcp_project=False)
    result = asyncio.get_event_loop().run_until_complete(
        council.GCPCouncilClient(timeout_s=1).deliberate(
            council.CouncilRequest(prompt="Rate NVDA"),
            roster=roster,
        )
    )

    assert len(result) == 3
    assert all(item.ok for item in result)
    assert {call[0] for call in calls} == {
        registry.CouncilProvider.GCP_GEMINI,
        registry.CouncilProvider.GCP_CLAUDE,
        registry.CouncilProvider.GCP_GROK,
    }


def test_gcp_council_surfaces_model_errors(monkeypatch):
    registry = _reload_registry(monkeypatch)
    council = importlib.reload(importlib.import_module("src.advisor.council"))

    def fake_call(self, spec, request):
        if spec.provider == registry.CouncilProvider.GCP_GROK:
            raise RuntimeError("quota exhausted")
        return council.CouncilResponse(
            provider=spec.provider,
            model=spec.model_id,
            label=spec.label,
            text="ok",
        )

    monkeypatch.setattr(council.GCPCouncilClient, "_call_model", fake_call)

    result = asyncio.get_event_loop().run_until_complete(
        council.GCPCouncilClient(timeout_s=1).deliberate(
            council.CouncilRequest(prompt="Rate AMZN"),
            roster=registry.enabled_roster(require_gcp_project=False),
        )
    )

    failures = [item for item in result if not item.ok]
    assert len(failures) == 1
    assert failures[0].provider == registry.CouncilProvider.GCP_GROK
    assert "quota exhausted" in failures[0].error
