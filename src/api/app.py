"""FastAPI surface for the on-demand AlphaDesk research cockpit."""
from __future__ import annotations

import asyncio
import json
import math
import os
import re
import urllib.error
import urllib.request
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from typing import Any, AsyncGenerator, Literal, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

# NOTE: .env is loaded by the server launcher (run_api.py), not at import time —
# importing this module (e.g. in tests) must not mutate the process environment.

from src.advisor import council
from src.api import run_store
from src.shared.config_loader import load_config
from src.shared.model_registry import enabled_roster
from src.utils.logger import get_logger

log = get_logger(__name__)

Rating = Literal["Buy", "Overweight", "Hold", "Underweight", "Sell"]
SourceStatus = Literal["validated", "configured", "unavailable"]
MacroThemeStatus = Literal["risk_on", "neutral", "risk_off"]
MacroTrend = Literal["up", "down", "flat"]


class PanelVerdict(BaseModel):
    model_id: str
    label: str
    rating: Rating
    confidence: float = Field(ge=0.0, le=1.0)
    thesis: str
    dissent: bool = False
    accepted_claims: list[str] = Field(default_factory=list)
    rejected_claims: list[str] = Field(default_factory=list)
    challenges: list[str] = Field(default_factory=list)


class CrowdedFlag(BaseModel):
    topic: str
    note: str


class JudgeAnalysis(BaseModel):
    consensus: list[str]
    contradictions: list[str]
    blind_spots: list[str]
    crowded_narrative_flag: Optional[CrowdedFlag] = None


class Scenario(BaseModel):
    name: Literal["Bull", "Base", "Bear"]
    probability: float = Field(ge=0.0, le=1.0)
    ret_pct: float


class Verdict(BaseModel):
    ticker: str
    rating: Rating
    conviction: float = Field(ge=0.0, le=1.0)
    conviction_label: str
    scenarios: list[Scenario]
    catalysts: list[str]
    risks: list[str]


class CouncilResult(BaseModel):
    run_id: Optional[int] = None
    saved_at: Optional[str] = None
    panel: list[PanelVerdict]
    judge: JudgeAnalysis
    verdict: Verdict
    cost_usd: float = Field(ge=0.0)
    degraded_reasons: list[str] = Field(default_factory=list)
    execution_mode: str = "unknown"


class RunRequest(BaseModel):
    ticker: str = Field(min_length=1)
    models: list[str] = Field(default_factory=list)


class DoneEvent(BaseModel):
    cost_usd: float = 0.0
    degraded_reasons: list[str] = Field(default_factory=list)
    council_mode: str = "unknown"
    run_id: Optional[int] = None
    saved_at: Optional[str] = None


class Position(BaseModel):
    ticker: str
    weight_pct: float
    rating: Optional[Rating] = None


class PortfolioSnapshot(BaseModel):
    positions: list[Position]
    top_holding_pct: float
    top3_pct: float
    concentration_flag: bool


class ModelOption(BaseModel):
    model_id: str
    label: str
    provider: str
    enabled: bool


class TopIdea(BaseModel):
    rank: int = Field(ge=1, le=12)
    ticker: str = Field(min_length=1)
    company: str
    theme: str
    score: float = Field(ge=0.0, le=1.0)
    horizon: str
    thesis: str
    catalysts: list[str]
    risks: list[str]
    source: str


class DataSourceCheck(BaseModel):
    source: str
    status: SourceStatus
    detail: str
    checked_at: str


class IdeaScoutAudit(BaseModel):
    mode: str = "unknown"
    source_counts: dict[str, int] = Field(default_factory=dict)
    raw_candidates: int = 0
    unique_candidates: int = 0
    capped_candidates: int = 0
    existing_universe_count: int = 0
    excluded_existing: list[dict[str, Any]] = Field(default_factory=list)
    tracked_ticker_checks: dict[str, dict[str, Any]] = Field(default_factory=dict)


class IdeaScoutResult(BaseModel):
    run_id: Optional[int] = None
    saved_at: Optional[str] = None
    as_of: str
    universe: str
    scout_mode: str = "unknown"
    ideas: list[TopIdea]
    data_source_checks: list[DataSourceCheck]
    audit: IdeaScoutAudit = Field(default_factory=IdeaScoutAudit)
    cost_usd: float = Field(ge=0.0)
    degraded_reasons: list[str] = Field(default_factory=list)
    disclaimer: str


class MacroRegimeResponse(BaseModel):
    call: str
    score: int = Field(ge=0, le=100)
    confidence: int = Field(ge=0, le=100)
    rationale: str
    agent: str
    scannedAt: str
    source: Literal["backend", "mock"] = "backend"
    sourceDetail: Optional[str] = None
    degradedReasons: list[str] = Field(default_factory=list)


class MacroThemeResponse(BaseModel):
    id: str
    title: str
    status: MacroThemeStatus
    confidence: int = Field(ge=0, le=100)
    trend: MacroTrend
    bullets: list[str]
    agent: str
    scannedAt: str


class MacroDashboardResponse(BaseModel):
    regime: MacroRegimeResponse
    themes: list[MacroThemeResponse]
    degraded_reasons: list[str] = Field(default_factory=list)


class IdeaScoutRunSummary(BaseModel):
    run_id: int
    saved_at: str
    scout_mode: str
    as_of: str
    idea_count: int
    cost_usd: float


class CouncilRunSummary(BaseModel):
    run_id: int
    saved_at: str
    ticker: str
    models: list[str]
    panel_count: int
    cost_usd: float
    execution_mode: str


DEFAULT_OPENROUTER_ANALYSIS_MODELS = [
    ModelOption(
        model_id="z-ai/glm-5.2",
        label="GLM 5.2",
        provider="z-ai",
        enabled=True,
    ),
    ModelOption(
        model_id="moonshotai/kimi-k2.6",
        label="Kimi K2.6",
        provider="moonshotai",
        enabled=True,
    ),
    ModelOption(
        model_id="deepseek/deepseek-v4-pro",
        label="DeepSeek V4 Pro",
        provider="deepseek",
        enabled=True,
    ),
    ModelOption(
        model_id="google/gemini-3.5-flash",
        label="Gemini 3.5 Flash",
        provider="google",
        enabled=True,
    ),
]

# Inference is restricted to four OpenRouter models: GLM 5.2, Kimi K2.6,
# Gemini 3.5 Flash, DeepSeek V4. Legacy names alias onto that set (heavy →
# Kimi, pro/flash → Gemini 3.5 Flash, anything else → GLM 5.2).
OPENROUTER_MODEL_ALIASES = {
    "claude-opus-4-8": "moonshotai/kimi-k2.6",
    "gemini-flash-3.5": "google/gemini-3.5-flash",
    "gemini-3.5-flash": "google/gemini-3.5-flash",
    "gemini-3.1-pro-preview": "google/gemini-3.5-flash",
    "kimi-k2.6": "moonshotai/kimi-k2.6",
    "moonshotai/kimi-k2.6": "moonshotai/kimi-k2.6",
    "deepseek-v4-pro": "deepseek/deepseek-v4-pro",
    "glm-5.2": "z-ai/glm-5.2",
    "xai/grok-4.20-reasoning": "z-ai/glm-5.2",
}


app = FastAPI(title="AlphaDesk Cockpit API")
app.add_middleware(
    CORSMiddleware,
    # Local personal tool: allow any localhost port (dev server may vary).
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/council/models", response_model=list[ModelOption])
def get_council_models() -> list[ModelOption]:
    """Return the configured council roster for UI chips."""
    if os.getenv("OPENROUTER_API_KEY"):
        return _openrouter_model_options()

    roster = enabled_roster(require_gcp_project=False)
    return [
        ModelOption(
            model_id=spec.model_id,
            label=spec.label,
            provider=spec.provider.value,
            enabled=spec.enabled,
        )
        for spec in roster
    ]


@app.post("/api/council/run", response_model=CouncilResult)
async def run_council(request: RunRequest) -> CouncilResult:
    """Run the council and return the complete result as JSON."""
    ticker = _clean_ticker(request.ticker)
    if not ticker:
        raise HTTPException(status_code=400, detail="ticker is required")
    models = request.models or [model.model_id for model in get_council_models() if model.enabled]
    result = await _run_council(ticker, models)
    result = _apply_cost_guardrail(result)
    return _save_council_result(result, ticker, models)


@app.get("/api/council/stream")
async def stream_council(
    ticker: str = Query(..., min_length=1),
    models: str = Query(default=""),
) -> StreamingResponse:
    """Stream a council deliberation using server-sent events."""
    ticker_value = _clean_ticker(ticker)
    if not ticker_value:
        raise HTTPException(status_code=400, detail="ticker is required")
    model_ids = _parse_models(models)
    if not model_ids:
        model_ids = [model.model_id for model in get_council_models() if model.enabled]

    async def event_generator() -> AsyncGenerator[str, None]:
        yield _sse("panel_started", {"ticker": ticker_value, "models": model_ids})
        try:
            if _cost_cap_usd() <= 0:
                done = DoneEvent(
                    degraded_reasons=["Council skipped because COUNCIL_COST_CAP_USD is 0."],
                    council_mode="skipped",
                )
                yield _sse("done", done)
                return

            if os.getenv("OPENROUTER_API_KEY"):
                async for event_name, event_data in _stream_openrouter_council_events(
                    ticker_value,
                    model_ids,
                ):
                    yield _sse(event_name, event_data)
                return

            result = _apply_cost_guardrail(
                await asyncio.wait_for(
                    _run_council(ticker_value, model_ids),
                    timeout=_stream_timeout_s(),
                )
            )
            result = _save_council_result(result, ticker_value, model_ids)
            for panel_result in result.panel:
                yield _sse("panel_model_result", panel_result)
            yield _sse("judge_result", result.judge)
            yield _sse("verdict", result.verdict)
            yield _sse(
                "done",
                DoneEvent(
                    cost_usd=result.cost_usd,
                    degraded_reasons=result.degraded_reasons,
                    council_mode=result.execution_mode,
                    run_id=result.run_id,
                    saved_at=result.saved_at,
                ),
            )
        except asyncio.TimeoutError:
            yield _sse(
                "done",
                DoneEvent(
                    degraded_reasons=["Council timed out before completion."],
                    council_mode="timeout",
                ),
            )
        except Exception as exc:
            log.exception("Council stream failed")
            yield _sse("error", {"message": str(exc) or "Council call failed"})

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/council/runs/latest", response_model=CouncilResult)
def latest_council_run(
    ticker: Optional[str] = Query(default=None),
) -> CouncilResult:
    """Return the most recent saved council result without starting a new model run."""
    ticker_value = _clean_ticker(ticker or "") if ticker else None
    payload = run_store.latest_council_run(ticker_value)
    if payload is None:
        raise HTTPException(status_code=404, detail="No saved council run found.")
    return CouncilResult.model_validate(payload)


@app.get("/api/council/runs", response_model=list[CouncilRunSummary])
def list_council_runs(
    limit: int = Query(default=20, ge=1, le=100),
    ticker: Optional[str] = Query(default=None),
) -> list[CouncilRunSummary]:
    """Return saved council run summaries from the local SQLite store."""
    ticker_value = _clean_ticker(ticker or "") if ticker else None
    return [CouncilRunSummary.model_validate(item) for item in run_store.list_council_runs(limit, ticker_value)]


@app.get("/api/ideas/today", response_model=IdeaScoutResult)
async def scout_today_ideas(
    limit: int = Query(default=12, ge=10, le=12),
    mode: Literal["top_buys", "new_discoveries"] = Query(default="top_buys"),
) -> IdeaScoutResult:
    """Return a broad top-ideas screen for the cockpit."""
    if not _mock_alpha_scout_enabled():
        try:
            pipeline_result = await asyncio.wait_for(
                _run_alpha_scout_pipeline(mode=mode),
                timeout=_alpha_scout_timeout_s(),
            )
            return _save_idea_scout_result(_idea_scout_from_alpha_scout(pipeline_result, limit), mode)
        except Exception as exc:
            log.exception("Alpha Scout full pipeline failed; falling back to direct idea scout")
            fallback_reason = f"Alpha Scout full pipeline failed: {exc}"
    else:
        fallback_reason = "Alpha Scout full pipeline skipped because ALPHA_SCOUT_MOCK=1."

    if os.getenv("OPENROUTER_API_KEY"):
        result = await asyncio.to_thread(_run_openrouter_idea_scout_sync, limit)
    else:
        result = _mock_today_ideas(limit)
    return _save_idea_scout_result(_with_alpha_scout_fallback_reason(result, fallback_reason), mode)


@app.get("/api/ideas/runs/latest", response_model=IdeaScoutResult)
def latest_idea_scout_run(
    mode: Optional[Literal["top_buys", "new_discoveries"]] = Query(default=None),
) -> IdeaScoutResult:
    """Return the most recent saved Alpha Scout result without starting a new run."""
    payload = run_store.latest_idea_scout_run(mode)
    if payload is None:
        raise HTTPException(status_code=404, detail="No saved Alpha Scout run found.")
    return IdeaScoutResult.model_validate(payload)


@app.get("/api/ideas/runs", response_model=list[IdeaScoutRunSummary])
def list_idea_scout_runs(
    limit: int = Query(default=20, ge=1, le=100),
    mode: Optional[Literal["top_buys", "new_discoveries"]] = Query(default=None),
) -> list[IdeaScoutRunSummary]:
    """Return saved Alpha Scout run summaries from the local SQLite store."""
    return [IdeaScoutRunSummary.model_validate(item) for item in run_store.list_idea_scout_runs(limit, mode)]


@app.get("/api/portfolio", response_model=PortfolioSnapshot)
def get_portfolio() -> PortfolioSnapshot:
    """Return a lightweight portfolio snapshot for the cockpit."""
    try:
        config = load_config("portfolio")
    except Exception:
        log.exception("Failed to load portfolio config")
        return PortfolioSnapshot(
            positions=[],
            top_holding_pct=0.0,
            top3_pct=0.0,
            concentration_flag=False,
        )

    raw_holdings = config.get("holdings", []) or []
    values: list[tuple[str, float]] = []
    for holding in raw_holdings:
        ticker = str(holding.get("ticker", "")).upper().strip()
        if not ticker:
            continue
        weight = holding.get("weight_pct")
        if weight is None:
            shares = float(holding.get("shares", 0) or 0)
            basis = float(holding.get("cost_basis", 0) or 0)
            weight = shares * basis
        values.append((ticker, float(weight or 0)))

    total = sum(value for _, value in values)
    if total <= 0:
        return PortfolioSnapshot(
            positions=[],
            top_holding_pct=0.0,
            top3_pct=0.0,
            concentration_flag=False,
        )

    positions = [
        Position(ticker=ticker, weight_pct=round(value / total * 100.0, 2))
        for ticker, value in values
    ]
    weights = sorted((position.weight_pct for position in positions), reverse=True)
    top_holding = weights[0] if weights else 0.0
    top3 = round(sum(weights[:3]), 2)
    max_position_pct = _portfolio_threshold()
    concentration_flag = top_holding > max_position_pct or top3 > min(60.0, max_position_pct * 3)
    return PortfolioSnapshot(
        positions=positions,
        top_holding_pct=round(top_holding, 2),
        top3_pct=top3,
        concentration_flag=concentration_flag,
    )


@app.get("/api/macro", response_model=MacroDashboardResponse)
async def get_macro_dashboard() -> MacroDashboardResponse:
    """Return live backend macro regime data for the dashboard."""
    return await asyncio.to_thread(_build_macro_dashboard)


@app.get("/api/macro/regime", response_model=MacroRegimeResponse)
async def get_macro_regime() -> MacroRegimeResponse:
    """Return the current backend macro regime."""
    return (await asyncio.to_thread(_build_macro_dashboard)).regime


@app.get("/api/macro/themes", response_model=list[MacroThemeResponse])
async def get_macro_themes() -> list[MacroThemeResponse]:
    """Return current backend macro themes."""
    return (await asyncio.to_thread(_build_macro_dashboard)).themes


# ── Score engine (deterministic, breadth-gated Top Buys) ─────────────────────

def _score_result_to_dict(result) -> dict:
    from src.score_engine.signals import Direction
    top = []
    for ts in result.top:
        breakdown = []
        for b in ts.breakdown:
            bd = dict(b)
            if isinstance(bd.get("direction"), Direction):
                bd["direction"] = bd["direction"].name
            breakdown.append(bd)
        top.append({
            "ticker": ts.ticker,
            "score": ts.score,
            "platforms_reporting": ts.platforms_reporting,
            "platforms_failed": ts.platforms_failed,
            "breakdown": breakdown,
        })
    return {
        "top": top,
        "snapshot_id": result.snapshot_id,
        "weights_version": result.weights_version,
        "diagnostics": result.diagnostics,
    }


@app.get("/api/score/top-buys")
async def get_score_top_buys() -> dict:
    """Return the most recent saved score snapshot (fast, no LLM)."""
    from src.score_engine.snapshot import list_snapshots, load_snapshot
    from src.score_engine.aggregator import score_tickers
    from src.score_engine.weights import load_weights
    from src.score_engine.signals import RunResult

    rows = list_snapshots(limit=1)
    if not rows:
        raise HTTPException(status_code=404, detail="No score snapshots yet — run the engine")
    snap = load_snapshot(rows[0]["snapshot_id"])
    if snap is None:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    scores = snap["scores"] or score_tickers(snap["signals"], load_weights(), [])
    ranked = sorted(scores, key=lambda s: (-s.score, s.ticker))[:10]
    result = RunResult(
        top=ranked,
        snapshot_id=snap["snapshot_id"],
        weights_version=snap["weights_version"],
        diagnostics={
            "elapsed_s": 0.0,
            "signals_collected": len(snap["signals"]),
            "sensors_ok": sorted({sig.sensor for sig in snap["signals"]}),
            "sensors_empty": [],
            "sensors_failed": [],
            "tickers_scored": len(scores),
        },
    )
    return _score_result_to_dict(result)


@app.post("/api/score/run")
async def post_score_run(payload: dict | None = None) -> dict:
    """Run the full score engine (gathers sensors, may take ~20s)."""
    from src.score_engine.engine import run_scoring
    from src.score_engine.signals import RunRequest

    payload = payload or {}
    req = RunRequest(top_n=int(payload.get("top_n", 10)), depth=payload.get("depth", "standard"))
    result = await run_scoring(req)
    return _score_result_to_dict(result)


def _build_macro_dashboard() -> MacroDashboardResponse:
    degraded_reasons: list[str] = []
    scanned_at = datetime.now().isoformat()
    try:
        macro_data = _fetch_live_macro_data()
    except Exception as exc:
        log.exception("Failed to fetch backend macro data")
        macro_data = {"fetched_at": scanned_at, "date": date.today().isoformat()}
        degraded_reasons.append(f"Backend macro data fetch failed: {exc}")

    scanned_at = _first_text(macro_data.get("fetched_at")) or scanned_at
    indicator_count = _macro_indicator_count(macro_data)
    source_detail = (
        f"Backend fetched {indicator_count} macro indicators from FRED/yfinance."
        if indicator_count
        else "Backend returned no live macro indicators; using configured theses."
    )
    if degraded_reasons:
        source_detail = f"{source_detail} {' '.join(degraded_reasons)}"

    themes = _macro_themes_for_dashboard(macro_data, scanned_at, degraded_reasons)
    regime = _macro_regime_for_dashboard(
        macro_data=macro_data,
        scanned_at=scanned_at,
        source_detail=source_detail,
        degraded_reasons=degraded_reasons,
    )
    return MacroDashboardResponse(
        regime=regime,
        themes=themes,
        degraded_reasons=degraded_reasons,
    )


def _fetch_live_macro_data() -> dict[str, Any]:
    from src.advisor.macro_analyst import fetch_macro_data

    data = fetch_macro_data()
    return data if isinstance(data, dict) else {}


def _macro_theses_from_memory_or_config(degraded_reasons: list[str]) -> list[dict[str, Any]]:
    try:
        from src.advisor.memory import get_all_macro_theses, seed_macro_theses

        theses = get_all_macro_theses()
        if theses:
            return theses

        config_theses = (_safe_load_config("advisor").get("macro_theses") or [])
        if isinstance(config_theses, list) and config_theses:
            seed_macro_theses(config_theses)
            return get_all_macro_theses() or list(config_theses)
    except Exception as exc:
        log.exception("Failed to read macro theses from advisor memory")
        degraded_reasons.append(f"Macro thesis memory unavailable: {exc}")

    config_theses = (_safe_load_config("advisor").get("macro_theses") or [])
    return list(config_theses) if isinstance(config_theses, list) else []


def _macro_regime_for_dashboard(
    *,
    macro_data: dict[str, Any],
    scanned_at: str,
    source_detail: str,
    degraded_reasons: list[str],
) -> MacroRegimeResponse:
    score = _macro_regime_score(macro_data)
    confidence = _macro_regime_confidence(macro_data)
    call = _macro_regime_call(score)
    rationale = _macro_regime_rationale(macro_data, score, degraded_reasons)
    return MacroRegimeResponse(
        call=call,
        score=score,
        confidence=confidence,
        rationale=rationale,
        agent="Backend Macro Scanner",
        scannedAt=scanned_at,
        source="backend",
        sourceDetail=source_detail,
        degradedReasons=degraded_reasons,
    )


def _macro_themes_for_dashboard(
    macro_data: dict[str, Any],
    scanned_at: str,
    degraded_reasons: list[str],
) -> list[MacroThemeResponse]:
    themes = [
        _macro_theme_from_thesis(thesis, index, macro_data, scanned_at)
        for index, thesis in enumerate(_macro_theses_from_memory_or_config(degraded_reasons))
    ]
    themes = [theme for theme in themes if theme is not None]
    if themes:
        return themes[:8]
    return _fallback_macro_themes_from_data(macro_data, scanned_at)


def _macro_theme_from_thesis(
    thesis: dict[str, Any],
    index: int,
    macro_data: dict[str, Any],
    scanned_at: str,
) -> Optional[MacroThemeResponse]:
    title = _first_text(thesis.get("title"))
    if not title:
        return None

    raw_status = _first_text(thesis.get("current_status") or thesis.get("status")).lower()
    status = _macro_theme_status(raw_status, title, macro_data)
    affected = [
        _clean_ticker(_first_text(ticker))
        for ticker in (thesis.get("affected_tickers") or [])
    ]
    affected = [ticker for ticker in affected if ticker]
    evidence_log = thesis.get("evidence_log") if isinstance(thesis.get("evidence_log"), list) else []

    bullets: list[str] = []
    description = _first_text(thesis.get("description"))
    if description:
        bullets.append(description)
    if affected:
        bullets.append(f"Exposed tickers: {', '.join(affected[:6])}")
    if evidence_log:
        latest = evidence_log[-1] if isinstance(evidence_log[-1], dict) else {}
        evidence = _first_text(latest.get("evidence") if isinstance(latest, dict) else latest)
        if evidence:
            bullets.append(evidence[:160])
    bullets.extend(_macro_indicator_bullets(macro_data)[: max(0, 3 - len(bullets))])
    if not bullets:
        bullets.append("Configured macro thesis is active in the advisor layer.")

    confidence = min(88, 54 + len(affected) * 3 + min(12, len(evidence_log) * 2))
    return MacroThemeResponse(
        id=_macro_theme_id(title, index),
        title=title,
        status=status,
        confidence=confidence,
        trend=_macro_theme_trend(raw_status, status),
        bullets=bullets[:3],
        agent="Backend Macro Scanner",
        scannedAt=scanned_at,
    )


def _fallback_macro_themes_from_data(
    macro_data: dict[str, Any],
    scanned_at: str,
) -> list[MacroThemeResponse]:
    bullets = _macro_indicator_bullets(macro_data)
    if not bullets:
        bullets = ["No FRED/yfinance macro indicators were available from the backend."]
    return [
        MacroThemeResponse(
            id="macro-indicators",
            title="Live Macro Indicators",
            status="neutral",
            confidence=_macro_regime_confidence(macro_data),
            trend="flat",
            bullets=bullets[:3],
            agent="Backend Macro Scanner",
            scannedAt=scanned_at,
        )
    ]


def _macro_theme_id(title: str, index: int) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug or f"macro-theme-{index + 1}"


def _macro_theme_status(
    raw_status: str,
    title: str,
    macro_data: dict[str, Any],
) -> MacroThemeStatus:
    if raw_status in {"strengthening", "risk_on", "risk-on", "strong"}:
        return "risk_on"
    if raw_status in {"weakening", "broken", "invalidated", "risk_off", "risk-off"}:
        return "risk_off"

    title_lower = title.lower()
    score = _macro_regime_score(macro_data)
    if any(token in title_lower for token in ("ai", "capex", "infrastructure")) and score >= 45:
        return "risk_on"
    if any(token in title_lower for token in ("fed", "easing", "liquidity")):
        return "risk_on" if score >= 60 else "neutral"
    return "neutral"


def _macro_theme_trend(raw_status: str, status: MacroThemeStatus) -> MacroTrend:
    if raw_status in {"strengthening", "strong"}:
        return "up"
    if raw_status in {"weakening", "broken", "invalidated"}:
        return "down"
    if status == "risk_on":
        return "up"
    if status == "risk_off":
        return "down"
    return "flat"


def _macro_regime_score(macro_data: dict[str, Any]) -> int:
    score = 50.0
    vix = _macro_indicator_value(macro_data, "vix")
    sp500_change = _macro_indicator_change(macro_data, "sp500")
    treasury_10y = _macro_indicator_value(macro_data, "treasury_10y")
    spread = _macro_indicator_value(macro_data, "yield_curve_spread_calculated", "yield_curve_spread")
    usd_change = _macro_indicator_change(macro_data, "usd_index")
    oil_change = _macro_indicator_change(macro_data, "oil_wti")

    if vix is not None:
        if vix <= 16:
            score += 12
        elif vix <= 22:
            score += 6
        elif vix >= 30:
            score -= 16
        else:
            score -= 6
    if sp500_change is not None:
        score += max(-8.0, min(8.0, sp500_change * 2.0))
    if treasury_10y is not None:
        if treasury_10y >= 5:
            score -= 8
        elif treasury_10y >= 4.5:
            score -= 4
        elif treasury_10y <= 3.75:
            score += 4
    if spread is not None:
        if spread >= 0.25:
            score += 4
        elif spread <= -0.25:
            score -= 5
    if usd_change is not None:
        if usd_change >= 0.5:
            score -= 3
        elif usd_change <= -0.5:
            score += 3
    if oil_change is not None:
        if oil_change >= 3:
            score -= 3
        elif oil_change <= -3:
            score += 3
    return int(max(0, min(100, round(score))))


def _macro_regime_confidence(macro_data: dict[str, Any]) -> int:
    indicator_count = _macro_indicator_count(macro_data)
    return int(max(35, min(90, 44 + indicator_count * 6)))


def _macro_regime_call(score: int) -> str:
    if score >= 70:
        return "Risk-On"
    if score >= 56:
        return "Cautiously Risk-On"
    if score >= 45:
        return "Mixed / Neutral"
    if score >= 30:
        return "Risk-Off Watch"
    return "Risk-Off"


def _macro_regime_rationale(
    macro_data: dict[str, Any],
    score: int,
    degraded_reasons: list[str],
) -> str:
    bullets = _macro_indicator_bullets(macro_data)
    if bullets:
        return (
            f"Backend macro scan scores the regime at {score}/100. "
            + " ".join(bullets[:4])
        )
    if degraded_reasons:
        return "Backend macro scan is degraded; configured advisor theses are being shown until live indicators recover."
    return "Backend macro scan completed, but no live macro indicators were available."


def _macro_indicator_bullets(macro_data: dict[str, Any]) -> list[str]:
    labels = {
        "vix": "VIX",
        "sp500": "S&P 500",
        "treasury_10y": "10Y Treasury",
        "treasury_2y": "2Y Treasury",
        "yield_curve_spread": "10Y-2Y spread",
        "yield_curve_spread_calculated": "10Y-2Y spread",
        "fed_funds_rate": "Fed funds",
        "oil_wti": "WTI crude",
        "gold": "Gold",
        "copper": "Copper",
        "usd_index": "US dollar index",
        "nat_gas": "Natural gas",
    }
    bullets: list[str] = []
    for key, label in labels.items():
        item = macro_data.get(key)
        if not isinstance(item, dict):
            if key != "yield_curve_spread_calculated":
                continue
            value = _first_numeric(item)
            if value is None:
                continue
            bullets.append(f"{label}: {value:.2f} points")
            continue
        value = _first_numeric(item.get("value"))
        if value is None:
            continue
        change = _first_numeric(item.get("change_pct"))
        suffix = f" ({change:+.2f}%)" if change is not None else ""
        unit = "%" if key in {"treasury_10y", "treasury_2y", "fed_funds_rate", "yield_curve_spread"} else ""
        bullets.append(f"{label}: {value:,.2f}{unit}{suffix}")
    return bullets


def _macro_indicator_value(macro_data: dict[str, Any], *keys: str) -> Optional[float]:
    for key in keys:
        item = macro_data.get(key)
        if isinstance(item, dict):
            value = _first_numeric(item.get("value"))
        else:
            value = _first_numeric(item)
        if value is not None:
            return value
    return None


def _macro_indicator_change(macro_data: dict[str, Any], key: str) -> Optional[float]:
    item = macro_data.get(key)
    if not isinstance(item, dict):
        return None
    return _first_numeric(item.get("change_pct"))


def _macro_indicator_count(macro_data: dict[str, Any]) -> int:
    return sum(
        1
        for key, value in macro_data.items()
        if key not in {"fetched_at", "date"} and value not in (None, {}, [])
    )


async def _run_council(ticker: str, models: list[str]) -> CouncilResult:
    """Run the underlying council and normalize it into the Phase-F contract."""
    if os.getenv("OPENROUTER_API_KEY"):
        return await _run_openrouter_council(ticker, models)
    prompt = _council_prompt(ticker)
    raw_result = await council.deliberate(prompt=prompt, max_tokens=1400)
    return _normalize_council_result(ticker, raw_result, models)


async def _run_openrouter_council(ticker: str, models: list[str]) -> CouncilResult:
    """Run a direct OpenRouter model council with an adversarial review round."""
    selected_models = _openrouter_analysis_models(models)
    execution_mode = "openrouter_mock" if _mock_openrouter_enabled() else "openrouter_live"
    if _mock_openrouter_enabled():
        tasks = [_run_openrouter_panel_model_async(ticker, model_id) for model_id in selected_models]
        results = await asyncio.gather(*tasks, return_exceptions=True)
    else:
        results = []
        for model_id in selected_models:
            try:
                results.append(await _run_openrouter_panel_model_async(ticker, model_id))
            except Exception as exc:
                results.append(exc)

    panel: list[PanelVerdict] = []
    degraded_reasons: list[str] = []
    if _mock_openrouter_enabled():
        degraded_reasons.append("OpenRouter mock mode active; council output is deterministic test data.")
    cost_usd = 0.0
    for model_id, result in zip(selected_models, results):
        if isinstance(result, Exception):
            degraded_reasons.append(f"{_label_from_model_id(model_id)} failed: {result}")
            panel.append(
                PanelVerdict(
                    model_id=model_id,
                    label=_label_from_model_id(model_id),
                    rating="Hold",
                    confidence=0.0,
                    thesis="Model call failed before returning a thesis.",
                    dissent=False,
                )
            )
            continue
        verdict, cost = result
        panel.append(verdict)
        cost_usd += cost
        if _is_degraded_panel_response(verdict):
            degraded_reasons.append(f"{verdict.label} returned incomplete or unstructured output after retry.")

    if not _mock_openrouter_enabled() and len(panel) > 1:
        critiqued_by_id: dict[str, PanelVerdict] = {}
        for item in panel:
            if item.confidence <= 0 or _is_degraded_panel_response(item):
                continue
            try:
                result = await _run_openrouter_cross_exam_async(
                    ticker,
                    item.model_id,
                    item,
                    panel,
                )
            except Exception as exc:
                degraded_reasons.append(f"{item.label} cross-examination failed: {exc}")
                continue
            verdict, cost = result
            critiqued_by_id[verdict.model_id] = _merge_cross_exam_verdict(item, verdict)
            cost_usd += cost
        if critiqued_by_id:
            panel = [critiqued_by_id.get(item.model_id, item) for item in panel]

    return _synthesize_openrouter_council(ticker, panel, cost_usd, degraded_reasons).model_copy(
        update={"execution_mode": execution_mode}
    )


async def _stream_openrouter_council_events(
    ticker: str,
    models: list[str],
) -> AsyncGenerator[tuple[str, Any], None]:
    """Yield OpenRouter council SSE payloads as each seat completes."""
    selected_models = _openrouter_analysis_models(models)
    execution_mode = "openrouter_mock" if _mock_openrouter_enabled() else "openrouter_live"
    panel: list[PanelVerdict] = []
    degraded_reasons: list[str] = []
    if _mock_openrouter_enabled():
        degraded_reasons.append("OpenRouter mock mode active; council output is deterministic test data.")
    cost_usd = 0.0
    total = len(selected_models)

    yield "progress", {
        "phase": "panel",
        "message": f"Launching {total} OpenRouter council seats.",
        "completed": 0,
        "total": total,
    }
    async for model_id, result in _openrouter_panel_results_as_completed(ticker, selected_models):
        if isinstance(result, Exception):
            verdict = _failed_panel_verdict(ticker, model_id, result)
            degraded_reasons.append(f"{_label_from_model_id(model_id)} failed: {result}")
            cost = 0.0
        else:
            verdict, cost = result
            if _is_degraded_panel_response(verdict):
                degraded_reasons.append(
                    f"{verdict.label} returned incomplete or unstructured output after retry."
                )
        panel.append(verdict)
        cost_usd += cost
        yield "panel_model_result", verdict
        yield "progress", {
            "phase": "panel",
            "message": f"{verdict.label} returned an initial thesis.",
            "model_id": verdict.model_id,
            "completed": len(panel),
            "total": total,
        }

    if not panel:
        raise RuntimeError("OpenRouter council returned no panel results.")

    if not _mock_openrouter_enabled() and len(panel) > 1:
        usable_panel = [item for item in panel if item.confidence > 0 and not _is_degraded_panel_response(item)]
        if usable_panel:
            yield "progress", {
                "phase": "cross_exam",
                "message": f"Cross-examining {len(usable_panel)} usable council seats.",
                "completed": 0,
                "total": len(usable_panel),
            }
        completed_cross_exam = 0
        async for item, result in _openrouter_cross_exam_results_as_completed(ticker, usable_panel, panel):
            completed_cross_exam += 1
            if isinstance(result, Exception):
                degraded_reasons.append(f"{item.label} cross-examination failed: {result}")
                yield "progress", {
                    "phase": "cross_exam",
                    "message": f"{item.label} cross-examination degraded; keeping its first-pass thesis.",
                    "model_id": item.model_id,
                    "completed": completed_cross_exam,
                    "total": len(usable_panel),
                }
                continue
            critique, cost = result
            cost_usd += cost
            merged = _merge_cross_exam_verdict(item, critique)
            panel = [merged if existing.model_id == item.model_id else existing for existing in panel]
            yield "panel_model_result", merged
            yield "progress", {
                "phase": "cross_exam",
                "message": f"{merged.label} completed cross-examination.",
                "model_id": merged.model_id,
                "completed": completed_cross_exam,
                "total": len(usable_panel),
            }

    result = _synthesize_openrouter_council(ticker, panel, cost_usd, degraded_reasons).model_copy(
        update={"execution_mode": execution_mode}
    )
    result = _apply_cost_guardrail(result)
    result = _save_council_result(result, ticker, models)
    yield "judge_result", result.judge
    yield "verdict", result.verdict
    yield "done", DoneEvent(
        cost_usd=result.cost_usd,
        degraded_reasons=result.degraded_reasons,
        council_mode=result.execution_mode,
        run_id=result.run_id,
        saved_at=result.saved_at,
    )


async def _openrouter_panel_results_as_completed(
    ticker: str,
    selected_models: list[str],
) -> AsyncGenerator[tuple[str, tuple[PanelVerdict, float] | Exception], None]:
    async def run_one(model_id: str) -> tuple[str, tuple[PanelVerdict, float] | Exception]:
        try:
            result = await asyncio.wait_for(
                _run_openrouter_panel_model_async(ticker, model_id),
                timeout=_model_timeout_s(),
            )
            return model_id, result
        except Exception as exc:
            return model_id, exc

    tasks = [asyncio.create_task(run_one(model_id)) for model_id in selected_models]
    for task in asyncio.as_completed(tasks):
        yield await task


async def _openrouter_cross_exam_results_as_completed(
    ticker: str,
    usable_panel: list[PanelVerdict],
    full_panel: list[PanelVerdict],
) -> AsyncGenerator[tuple[PanelVerdict, tuple[PanelVerdict, float] | Exception], None]:
    async def run_one(item: PanelVerdict) -> tuple[PanelVerdict, tuple[PanelVerdict, float] | Exception]:
        try:
            result = await asyncio.wait_for(
                _run_openrouter_cross_exam_async(ticker, item.model_id, item, full_panel),
                timeout=_model_timeout_s(),
            )
            return item, result
        except Exception as exc:
            return item, exc

    tasks = [asyncio.create_task(run_one(item)) for item in usable_panel]
    for task in asyncio.as_completed(tasks):
        yield await task


async def _run_openrouter_panel_model_async(ticker: str, model_id: str) -> tuple[PanelVerdict, float]:
    return await asyncio.to_thread(_run_openrouter_panel_model_sync, ticker, model_id)


async def _run_openrouter_cross_exam_async(
    ticker: str,
    model_id: str,
    own_verdict: PanelVerdict,
    panel: list[PanelVerdict],
) -> tuple[PanelVerdict, float]:
    return await asyncio.to_thread(
        _run_openrouter_cross_exam_sync,
        ticker,
        model_id,
        own_verdict,
        panel,
    )


def _failed_panel_verdict(ticker: str, model_id: str, exc: Exception) -> PanelVerdict:
    message = str(exc) or exc.__class__.__name__
    if isinstance(exc, asyncio.TimeoutError):
        message = f"Timed out after {_model_timeout_s():.0f}s."
    return PanelVerdict(
        model_id=model_id,
        label=_label_from_model_id(model_id),
        rating="Hold",
        confidence=0.0,
        thesis=f"{_label_from_model_id(model_id)} did not return a reliable thesis for {ticker}: {message}",
        dissent=False,
        accepted_claims=[],
        rejected_claims=["This seat produced no usable evidence for or against the claim."],
        challenges=["Retry this model or remove it from the roster if provider latency persists."],
    )


def _run_openrouter_panel_model_sync(ticker: str, model_id: str) -> tuple[PanelVerdict, float]:
    if _mock_openrouter_enabled():
        return _mock_openrouter_panel_model(ticker, model_id), 0.0

    return _run_openrouter_panel_prompt_sync(
        ticker=ticker,
        model_id=model_id,
        prompt=_panel_model_json_prompt(ticker, model_id),
        system=(
            "You are one AlphaDesk investment council seat. "
            "Return only valid JSON and keep the thesis concise."
        ),
    )


def _run_openrouter_cross_exam_sync(
    ticker: str,
    model_id: str,
    own_verdict: PanelVerdict,
    panel: list[PanelVerdict],
) -> tuple[PanelVerdict, float]:
    return _run_openrouter_panel_prompt_sync(
        ticker=ticker,
        model_id=model_id,
        prompt=_panel_cross_exam_json_prompt(ticker, model_id, own_verdict, panel),
        system=(
            "You are an adversarial AlphaDesk investment council seat. "
            "Critically accept or reject claims from other models. Return only valid JSON."
        ),
    )


def _merge_cross_exam_verdict(initial: PanelVerdict, critique: PanelVerdict) -> PanelVerdict:
    if _is_degraded_panel_response(critique):
        return initial
    return critique


def _is_degraded_panel_response(verdict: PanelVerdict) -> bool:
    text = " ".join([verdict.thesis, *verdict.challenges, *verdict.rejected_claims]).lower()
    return (
        "returned an empty response" in text
        or "returned unstructured text" in text
        or "treat this seat as lower-confidence" in text
        or "retry this model" in text
        or "returned truncated json" in text
        or "incomplete structured output" in text
        or verdict.thesis.strip().startswith("{")
    )


def _run_openrouter_panel_prompt_sync(
    *,
    ticker: str,
    model_id: str,
    prompt: str,
    system: str,
) -> tuple[PanelVerdict, float]:
    request_headers = {
        "Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
        "HTTP-Referer": os.getenv("OPENROUTER_SITE_URL", "http://localhost:5173"),
        "X-Title": "AlphaDesk Cockpit",
    }
    request_body = {
        "model": model_id,
        "messages": [
            {
                "role": "system",
                "content": system,
            },
            {"role": "user", "content": prompt},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "alphadesk_panel_verdict",
                "strict": True,
                "schema": _panel_verdict_json_schema(),
            },
        },
        "max_tokens": _openrouter_model_max_tokens(),
        "temperature": 0.2,
    }

    timeout_s = _model_timeout_s()
    try:
        response_data = _openrouter_completion_raw(request_body, request_headers, timeout_s)
    except RuntimeError as exc:
        if "response_format" in str(exc) or "json_schema" in str(exc):
            response_data = _openrouter_relaxed_panel_completion(request_body, request_headers, timeout_s)
        else:
            try:
                response_data = _openrouter_relaxed_panel_completion(request_body, request_headers, timeout_s)
            except RuntimeError:
                raise exc
    try:
        panel = _panel_from_openrouter_response(response_data, ticker, model_id)
    except RuntimeError:
        response_data = _openrouter_relaxed_panel_completion(request_body, request_headers, timeout_s)
        panel = _panel_from_openrouter_response(response_data, ticker, model_id)
    cost_usd = _openrouter_cost(response_data) or 0.0
    if _is_degraded_panel_response(panel):
        try:
            retry_data = _openrouter_relaxed_panel_completion(request_body, request_headers, timeout_s)
            retry_panel = _panel_from_openrouter_response(retry_data, ticker, model_id)
            cost_usd += _openrouter_cost(retry_data) or 0.0
            if not _is_degraded_panel_response(retry_panel):
                panel = retry_panel
        except RuntimeError:
            pass
    return panel, cost_usd


def _openrouter_relaxed_panel_completion(
    request_body: dict[str, Any],
    request_headers: dict[str, str],
    timeout_s: float,
) -> dict[str, Any]:
    relaxed_body = dict(request_body)
    relaxed_body.pop("response_format", None)
    relaxed_body["messages"] = [
        {
            **message,
            "content": (
                f"{message.get('content', '')}\n\nReturn only a JSON object. "
                "Do not use markdown, prose, or code fences."
            ),
        }
        if isinstance(message, dict) and message.get("role") == "user"
        else message
        for message in request_body.get("messages", [])
    ]
    relaxed_body["max_tokens"] = max(_openrouter_model_max_tokens(), 900)
    return _openrouter_completion_raw(relaxed_body, request_headers, timeout_s)


def _panel_from_openrouter_response(
    response_data: dict[str, Any],
    ticker: str,
    model_id: str,
) -> PanelVerdict:
    payload = _openrouter_choice_payload(response_data)
    if payload is None:
        parsed = _plain_panel_from_empty_response(ticker, model_id)
    else:
        try:
            parsed = _extract_json_object(payload) if isinstance(payload, str) else payload
        except RuntimeError:
            if not isinstance(payload, str):
                raise
            parsed = _plain_panel_from_text(ticker, model_id, payload)
    reasons: list[str] = []
    repaired = _repair_panel_item(parsed, reasons)
    repaired["model_id"] = model_id
    repaired["label"] = _label_from_model_id(model_id)
    repaired["rating"] = _map_openrouter_rating(repaired.get("rating"))
    repaired["confidence"] = _score_from_openrouter_number(repaired.get("confidence"))
    return PanelVerdict.model_validate(repaired)


def _plain_panel_from_empty_response(ticker: str, model_id: str) -> dict[str, Any]:
    return {
        "model_id": model_id,
        "label": _label_from_model_id(model_id),
        "rating": "Hold",
        "confidence": 0.35,
        "thesis": f"{model_id} returned an empty response for {ticker}; keep this seat cautious.",
        "dissent": False,
        "accepted_claims": [],
        "rejected_claims": ["Empty model response cannot validate other seats' claims."],
        "challenges": ["Retry this model or inspect provider availability before relying on it."],
    }


def _plain_panel_from_text(ticker: str, model_id: str, text: str) -> dict[str, Any]:
    cleaned = " ".join(text.strip().split())
    fragment = _panel_from_json_fragment(ticker, model_id, cleaned)
    if fragment is not None:
        return fragment
    if _looks_like_incomplete_json(cleaned):
        return {
            "model_id": model_id,
            "label": _label_from_model_id(model_id),
            "rating": "Hold",
            "confidence": 0.35,
            "thesis": (
                f"{_label_from_model_id(model_id)} returned incomplete structured output "
                f"for {ticker}; no reliable thesis was available from this seat."
            ),
            "dissent": False,
            "accepted_claims": [],
            "rejected_claims": [],
            "challenges": [],
        }

    rating: Rating = "Hold"
    lower = cleaned.lower()
    if any(token in lower for token in ("sell", "avoid", "overvalued")):
        rating = "Underweight"
    elif any(token in lower for token in ("buy", "strong upside", "attractive")):
        rating = "Buy"
    elif any(token in lower for token in ("overweight", "constructive")):
        rating = "Overweight"
    thesis = cleaned[:420] if cleaned else f"{model_id} returned unstructured analysis for {ticker}."
    return {
        "model_id": model_id,
        "label": _label_from_model_id(model_id),
        "rating": rating,
        "confidence": 0.5,
        "thesis": thesis,
        "dissent": False,
        "accepted_claims": [],
        "rejected_claims": [],
        "challenges": ["Model returned unstructured text; treat this seat as lower-confidence."],
    }


def _looks_like_incomplete_json(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    return (
        stripped.startswith("{")
        or stripped.startswith("[")
        or '"model_id"' in stripped
        or '"rating"' in stripped
        or '"thesis"' in stripped
    )


def _panel_from_json_fragment(ticker: str, model_id: str, text: str) -> Optional[dict[str, Any]]:
    if "{" not in text or "\"rating\"" not in text:
        return None

    def field(name: str) -> str:
        match = re.search(rf'"{re.escape(name)}"\s*:\s*"((?:\\.|[^"\\])*)', text)
        if not match:
            return ""
        return match.group(1).replace('\\"', '"').replace("\\'", "'")

    def number_field(name: str, fallback: float) -> float:
        match = re.search(rf'"{re.escape(name)}"\s*:\s*([0-9]+(?:\.[0-9]+)?)', text)
        if not match:
            return fallback
        try:
            return float(match.group(1))
        except ValueError:
            return fallback

    rating = _map_openrouter_rating(field("rating"))
    thesis = field("thesis") or f"{model_id} returned a truncated JSON response for {ticker}."
    accepted = _string_array_fragment("accepted_claims", text)
    rejected = _string_array_fragment("rejected_claims", text)
    challenges = _string_array_fragment("challenges", text)
    return {
        "model_id": model_id,
        "label": _label_from_model_id(model_id),
        "rating": rating,
        "confidence": number_field("confidence", 0.5),
        "thesis": thesis[:420],
        "dissent": False,
        "accepted_claims": accepted[:4],
        "rejected_claims": rejected[:4],
        "challenges": challenges[:4],
    }


def _string_array_fragment(name: str, text: str) -> list[str]:
    match = re.search(rf'"{re.escape(name)}"\s*:\s*\[(.*?)(?:\]|\s*,\s*"[a-zA-Z_]+")', text)
    if not match:
        return []
    return [
        item.replace('\\"', '"').replace("\\'", "'")
        for item in re.findall(r'"((?:\\.|[^"\\])*)"', match.group(1))
        if item.strip()
    ]


def _mock_openrouter_panel_model(ticker: str, model_id: str) -> PanelVerdict:
    rating_by_model: dict[str, Rating] = {
        "google/gemini-3.5-flash": "Overweight",
        "moonshotai/kimi-k2.7-code": "Buy",
        "deepseek/deepseek-v4-pro": "Hold",
        "z-ai/glm-5.2": "Overweight",
    }
    confidence_by_rating = {
        "Buy": 0.78,
        "Overweight": 0.68,
        "Hold": 0.56,
        "Underweight": 0.44,
        "Sell": 0.32,
    }
    rating = rating_by_model.get(model_id, "Hold")
    return PanelVerdict(
        model_id=model_id,
        label=_label_from_model_id(model_id),
        rating=rating,
        confidence=confidence_by_rating[rating],
        thesis=(
            f"{ticker} shows enough upside for a {rating} seat, while valuation and execution risk "
            "keep the council honest."
        ),
        dissent=False,
    )


async def _run_alpha_scout_pipeline(mode: str = "top_buys") -> dict[str, Any]:
    from src.alpha_scout import main as alpha_scout_main

    return await alpha_scout_main.run(mode=mode)


def _idea_scout_from_alpha_scout(result: dict[str, Any], limit: int) -> IdeaScoutResult:
    recommendations = result.get("recommendations") if isinstance(result, dict) else {}
    if not isinstance(recommendations, dict):
        recommendations = {}
    recs = [
        *list(recommendations.get("portfolio_recs") or []),
        *list(recommendations.get("watchlist_recs") or []),
    ]
    if not recs and isinstance(result, dict):
        recs = list(result.get("scored_candidates") or [])
    ideas = [_top_idea_from_alpha_scout_rec(rec, index) for index, rec in enumerate(recs[:limit])]
    ideas = [idea for idea in ideas if idea is not None]
    if not ideas:
        stats = result.get("stats") if isinstance(result, dict) else {}
        raise RuntimeError(f"Alpha Scout returned no recommendations. Stats: {stats}")

    stats = result.get("stats") if isinstance(result, dict) else {}
    if not isinstance(stats, dict):
        stats = {}
    checks = _idea_source_checks(scout_mode="alpha_scout", alpha_scout_stats=stats)
    audit = _idea_audit_from_alpha_scout_stats(stats)
    if isinstance(result, dict):
        ideas = _apply_top_buy_tracked_coverage(ideas, result.get("scored_candidates"), limit, audit)
    degraded = _as_string_list(result.get("degraded_reasons") if isinstance(result, dict) else None)
    synthesis_source = str(stats.get("synthesis_source") or "")
    if result.get("formatted") and "No new candidates" in str(result.get("formatted")):
        degraded.append("Alpha Scout completed but found no new candidates.")
    if not recommendations.get("portfolio_recs") and result.get("scored_candidates"):
        if synthesis_source in {"llm_json", "llm_repaired_json"}:
            degraded.append("Alpha Scout model returned no buy bucket; displaying watchlist recommendations.")
        else:
            degraded.append("Alpha Scout synthesis returned no buy bucket; ranked scored candidates directly.")
    if synthesis_source in {"score_fallback", "error_fallback", "budget_fallback", "parse_failed", "repair_failed"}:
        degraded.append(f"Alpha Scout synthesis source was {synthesis_source}; score-based ranking may be in use.")

    return IdeaScoutResult(
        as_of=date.today().isoformat(),
        universe=(
            "Alpha Scout top-buy pipeline"
            if audit.mode == "top_buys"
            else "Alpha Scout new-discovery pipeline"
        ),
        scout_mode=audit.mode,
        ideas=ideas,
        data_source_checks=checks,
        audit=audit,
        cost_usd=float(_first_numeric(stats.get("synthesis_cost_usd"), 0.0) or 0.0),
        degraded_reasons=degraded,
        disclaimer="Research candidates from Alpha Scout; verify live prices, news, and suitability before trading.",
    )


def _apply_top_buy_tracked_coverage(
    ideas: list[TopIdea],
    scored_candidates: Any,
    limit: int,
    audit: IdeaScoutAudit,
) -> list[TopIdea]:
    if audit.mode != "top_buys" or not isinstance(scored_candidates, list):
        return ideas

    coverage_target = min(10, max(3, limit - 2))
    tracked_candidates = []
    for candidate in scored_candidates:
        if not isinstance(candidate, dict):
            continue
        source = str(candidate.get("source") or "")
        if not source.startswith("existing_"):
            continue
        composite = _first_numeric((candidate.get("scores") or {}).get("composite"), 0.0) or 0.0
        if composite < 60:
            continue
        tracked_candidates.append(candidate)

    tracked_candidates.sort(
        key=lambda candidate: _first_numeric((candidate.get("scores") or {}).get("composite"), 0.0) or 0.0,
        reverse=True,
    )
    required_tickers = [
        _clean_ticker(str(candidate.get("ticker") or ""))
        for candidate in tracked_candidates[:coverage_target]
    ]
    required_tickers = [ticker for ticker in required_tickers if ticker]
    if not required_tickers:
        return ideas

    by_ticker = {idea.ticker: idea for idea in ideas}
    merged = list(ideas)
    for candidate in tracked_candidates:
        ticker = _clean_ticker(str(candidate.get("ticker") or ""))
        if ticker not in required_tickers or ticker in by_ticker:
            continue
        idea = _top_idea_from_alpha_scout_rec(candidate, min(len(merged), limit - 1))
        if idea is None:
            continue
        if len(merged) >= limit:
            remove_index = next(
                (
                    index
                    for index in range(len(merged) - 1, -1, -1)
                    if not merged[index].source.startswith("existing_")
                ),
                len(merged) - 1,
            )
            removed = merged.pop(remove_index)
            by_ticker.pop(removed.ticker, None)
        merged.append(idea)
        by_ticker[ticker] = idea

    merged.sort(key=lambda idea: idea.score, reverse=True)
    return [
        idea.model_copy(update={"rank": index + 1})
        for index, idea in enumerate(merged[:limit])
    ]


def _idea_audit_from_alpha_scout_stats(stats: dict[str, Any]) -> IdeaScoutAudit:
    raw_audit = stats.get("candidate_audit") if isinstance(stats, dict) else {}
    if not isinstance(raw_audit, dict):
        raw_audit = {}
    source_counts = raw_audit.get("source_counts")
    if not isinstance(source_counts, dict):
        source_counts = {}
    return IdeaScoutAudit(
        mode=_first_text(stats.get("mode")) or _first_text(raw_audit.get("mode")) or "unknown",
        source_counts={
            str(source): int(_first_numeric(count, 0) or 0)
            for source, count in source_counts.items()
        },
        raw_candidates=int(_first_numeric(raw_audit.get("raw_candidates"), 0) or 0),
        unique_candidates=int(_first_numeric(raw_audit.get("unique_candidates"), 0) or 0),
        capped_candidates=int(_first_numeric(raw_audit.get("capped_candidates"), 0) or 0),
        existing_universe_count=int(_first_numeric(raw_audit.get("existing_universe_count"), 0) or 0),
        excluded_existing=list(raw_audit.get("excluded_existing") or []),
        tracked_ticker_checks=(
            stats.get("tracked_ticker_checks")
            if isinstance(stats.get("tracked_ticker_checks"), dict)
            else {}
        ),
    )


def _top_idea_from_alpha_scout_rec(rec: Any, index: int) -> Optional[TopIdea]:
    if not isinstance(rec, dict):
        return None
    ticker = _clean_ticker(str(rec.get("ticker") or ""))
    if not ticker:
        return None
    scores = rec.get("scores") if isinstance(rec.get("scores"), dict) else {}
    fund = rec.get("fundamentals_summary") if isinstance(rec.get("fundamentals_summary"), dict) else {}
    composite = _first_numeric(scores.get("composite"), 50.0) or 50.0
    category = _first_text(rec.get("category")) or "watchlist"
    conviction = _first_text(rec.get("conviction")) or "medium"
    sector = _first_text(fund.get("sector")) or "Alpha Scout discovery"
    thesis = _first_text(rec.get("thesis")) or f"Alpha Scout ranked {ticker} from its discovery pipeline."
    return TopIdea(
        rank=index + 1,
        ticker=ticker,
        company=_first_text(rec.get("company")) or ticker,
        theme=f"{category.title()} · {sector}",
        score=max(0.0, min(1.0, composite / 100.0)),
        horizon="6-18 months",
        thesis=thesis,
        catalysts=[
            f"Alpha Scout composite score {composite:.1f}",
            f"Conviction: {conviction}",
        ],
        risks=[
            "Requires follow-up council validation before action.",
            "Quantitative screen may miss fresh news or liquidity risk.",
        ],
        source=_first_text(rec.get("source")) or "alpha_scout",
    )


def _with_alpha_scout_fallback_reason(result: IdeaScoutResult, reason: str) -> IdeaScoutResult:
    checks = [
        DataSourceCheck(
            source="Alpha Scout pipeline",
            status="unavailable",
            detail=reason,
            checked_at=date.today().isoformat(),
        ),
        *result.data_source_checks,
    ]
    return result.model_copy(
        update={
            "data_source_checks": checks,
            "degraded_reasons": [reason, *result.degraded_reasons],
        }
    )


def _save_idea_scout_result(result: IdeaScoutResult, run_mode: str | None = None) -> IdeaScoutResult:
    try:
        run_id, saved_at = run_store.save_idea_scout_run(
            run_mode or result.scout_mode,
            result.model_dump(mode="json"),
        )
    except Exception as exc:
        log.exception("Failed to persist Alpha Scout run")
        return result.model_copy(
            update={
                "degraded_reasons": [
                    *result.degraded_reasons,
                    f"Alpha Scout run completed but local SQLite persistence failed: {exc}",
                ]
            }
        )
    return result.model_copy(update={"run_id": run_id, "saved_at": saved_at})


def _save_council_result(result: CouncilResult, ticker: str, models: list[str]) -> CouncilResult:
    try:
        run_id, saved_at = run_store.save_council_run(
            ticker,
            models,
            result.model_dump(mode="json"),
        )
    except Exception as exc:
        log.exception("Failed to persist council run")
        return result.model_copy(
            update={
                "degraded_reasons": [
                    *result.degraded_reasons,
                    f"Council completed but local SQLite persistence failed: {exc}",
                ]
            }
        )
    return result.model_copy(update={"run_id": run_id, "saved_at": saved_at})


def _run_openrouter_idea_scout_sync(limit: int) -> IdeaScoutResult:
    if _mock_openrouter_enabled():
        return _mock_today_ideas(limit)

    model_id = _non_opus_openrouter_model(os.getenv("OPENROUTER_IDEA_MODEL", "z-ai/glm-5.2"))
    request_headers = {
        "Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
        "HTTP-Referer": os.getenv("OPENROUTER_SITE_URL", "http://localhost:5173"),
        "X-Title": "AlphaDesk Cockpit",
    }
    request_body = {
        "model": model_id,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are AlphaDesk's equity idea scout. Return only valid JSON. "
                    "Frame outputs as research candidates, not personal financial advice."
                ),
            },
            {"role": "user", "content": _idea_scout_json_prompt(limit)},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "alphadesk_idea_scout_result",
                "strict": True,
                "schema": _idea_scout_json_schema(),
            },
        },
        "max_tokens": _openrouter_idea_max_tokens(),
        "temperature": 0.25,
    }

    timeout_s = float(os.getenv("IDEA_SCOUT_TIMEOUT_S", os.getenv("COUNCIL_MODEL_TIMEOUT_S", "60")))
    try:
        response_data = _openrouter_completion_raw(request_body, request_headers, timeout_s)
    except RuntimeError as exc:
        if "response_format" not in str(exc) and "json_schema" not in str(exc):
            raise
        relaxed_body = dict(request_body)
        relaxed_body.pop("response_format", None)
        response_data = _openrouter_completion_raw(relaxed_body, request_headers, timeout_s)

    payload = _openrouter_choice_payload(response_data)
    if payload is None:
        raise RuntimeError("Idea scout returned an empty response.")
    parsed = _extract_json_object(payload) if isinstance(payload, str) else payload
    result, repair_reasons = _repair_idea_scout_payload(parsed, limit)
    result = result.model_copy(update={"data_source_checks": _idea_source_checks(scout_mode="openrouter")})
    cost = _openrouter_cost(response_data)
    if cost is not None:
        result = result.model_copy(update={"cost_usd": cost})
    if repair_reasons:
        result = result.model_copy(update={"degraded_reasons": [*result.degraded_reasons, *repair_reasons]})
    return result


def _mock_today_ideas(limit: int = 12) -> IdeaScoutResult:
    rows = [
        ("NVDA", "NVIDIA", "AI accelerators", 0.91, "AI infrastructure demand still compounds, but expectations are crowded."),
        ("MSFT", "Microsoft", "AI platform cash flows", 0.88, "Azure AI attach and enterprise distribution can support durable earnings."),
        ("AMZN", "Amazon", "AWS and retail margin recovery", 0.85, "AWS reacceleration plus logistics efficiency gives multiple ways to win."),
        ("AVGO", "Broadcom", "AI networking and custom silicon", 0.84, "AI networking demand and VMware synergies can offset cyclicality."),
        ("GOOGL", "Alphabet", "AI search and cloud", 0.82, "Search durability, cloud scale, and optionality remain under-debated versus peers."),
        ("META", "Meta Platforms", "AI-driven ad efficiency", 0.80, "AI ranking gains and disciplined opex can keep free cash flow resilient."),
        ("TSM", "Taiwan Semiconductor", "advanced-node foundry", 0.79, "Leading-edge foundry share gives leveraged exposure to AI capex."),
        ("LLY", "Eli Lilly", "obesity and metabolic care", 0.77, "GLP-1 demand and pipeline breadth support a long growth runway."),
        ("VRT", "Vertiv", "data-center power and cooling", 0.76, "Power and thermal bottlenecks make data-center infrastructure a durable theme."),
        ("CRWD", "CrowdStrike", "cloud security consolidation", 0.74, "Security platform consolidation can sustain growth if retention stays strong."),
        ("RKLB", "Rocket Lab", "space infrastructure", 0.70, "Launch cadence and spacecraft systems create asymmetric upside with execution risk."),
        ("V", "Visa", "global payments quality", 0.68, "High-margin payment volume remains a defensive compounder if consumer stress stays contained."),
    ]
    ideas = [
        TopIdea(
            rank=index + 1,
            ticker=ticker,
            company=company,
            theme=theme,
            score=score,
            horizon="6-18 months",
            thesis=thesis,
            catalysts=[
                f"{theme.title()} data points improve",
                "Next earnings update confirms margin or revenue durability",
            ],
            risks=[
                "Crowded positioning or valuation compression",
                "Macro slowdown reduces risk appetite",
            ],
            source="Mock AlphaDesk broad screen",
        )
        for index, (ticker, company, theme, score, thesis) in enumerate(rows[:limit])
    ]
    return IdeaScoutResult(
        as_of=date.today().isoformat(),
        universe="US-listed liquid equities and ADRs",
        scout_mode="mock",
        ideas=ideas,
        data_source_checks=_idea_source_checks(scout_mode="mock"),
        cost_usd=0.0,
        degraded_reasons=[],
        disclaimer="Research candidates only; verify live prices, news, and suitability before trading.",
    )


def _repair_idea_scout_payload(payload: Any, limit: int) -> tuple[IdeaScoutResult, list[str]]:
    if not isinstance(payload, dict):
        raise RuntimeError("Idea scout returned an unsupported result shape.")

    reasons: list[str] = []
    raw_ideas = payload.get("ideas")
    if not isinstance(raw_ideas, list):
        raise RuntimeError("Idea scout returned no ideas.")

    ideas: list[TopIdea] = []
    for index, item in enumerate(raw_ideas[:limit]):
        if not isinstance(item, dict):
            reasons.append("Idea scout returned a non-object idea; skipped it.")
            continue
        repaired = dict(item)
        ticker = _clean_ticker(str(repaired.get("ticker") or ""))
        if not ticker:
            reasons.append("Idea scout returned an idea without a ticker; skipped it.")
            continue
        raw_rank = int(_first_numeric(repaired.get("rank"), index + 1) or index + 1)
        repaired["rank"] = max(1, min(12, raw_rank))
        repaired["ticker"] = ticker
        repaired["company"] = _first_text(repaired.get("company")) or ticker
        repaired["theme"] = _first_text(repaired.get("theme")) or "Broad equity screen"
        repaired["score"] = _score_from_openrouter_number(repaired.get("score") or repaired.get("conviction"))
        repaired["horizon"] = _first_text(repaired.get("horizon")) or "6-18 months"
        repaired["thesis"] = _first_text(repaired.get("thesis")) or "Idea scout returned no thesis."
        repaired["catalysts"] = _extract_bullet_items(repaired.get("catalysts"))[:3] or ["Next company update"]
        repaired["risks"] = _extract_bullet_items(repaired.get("risks"))[:3] or ["Valuation or macro risk"]
        repaired["source"] = _first_text(repaired.get("source")) or "OpenRouter idea scout"
        ideas.append(TopIdea.model_validate(repaired))

    if not ideas:
        raise RuntimeError("Idea scout returned no valid ticker ideas.")

    return (
        IdeaScoutResult(
            as_of=_first_text(payload.get("as_of")) or date.today().isoformat(),
            universe=_first_text(payload.get("universe")) or "US-listed liquid equities and ADRs",
            scout_mode="openrouter",
            ideas=ideas,
            data_source_checks=_repair_source_checks(payload.get("data_source_checks")),
            cost_usd=float(_first_numeric(payload.get("cost_usd"), 0.0) or 0.0),
            degraded_reasons=_as_string_list(payload.get("degraded_reasons")),
            disclaimer=(
                _first_text(payload.get("disclaimer"))
                or "Research candidates only; verify live prices, news, and suitability before trading."
            ),
        ),
        reasons,
    )


def _idea_source_checks(
    scout_mode: Literal["mock", "openrouter", "alpha_scout"],
    alpha_scout_stats: Optional[dict[str, Any]] = None,
) -> list[DataSourceCheck]:
    checked_at = date.today().isoformat()
    checks: list[DataSourceCheck] = []

    if scout_mode == "alpha_scout":
        stats = alpha_scout_stats or {}
        raw_audit = stats.get("candidate_audit") if isinstance(stats.get("candidate_audit"), dict) else {}
        source_counts = raw_audit.get("source_counts") if isinstance(raw_audit.get("source_counts"), dict) else {}
        synthesis_source = _first_text(stats.get("synthesis_source")) or "unknown"
        synthesis_model = _first_text(stats.get("synthesis_model"))
        synthesis_provider = _first_text(stats.get("synthesis_provider"))
        synthesis_detail = f"Synthesis: {synthesis_source}"
        if synthesis_provider:
            synthesis_detail += f" via {synthesis_provider}"
        if synthesis_model:
            synthesis_detail += f" on {synthesis_model}"
        checks.append(
            DataSourceCheck(
                source="Alpha Scout pipeline",
                status="validated",
                detail=(
                    f"{int(_first_numeric(stats.get('candidates_sourced'), 0) or 0)} sourced, "
                    f"{int(_first_numeric(stats.get('candidates_screened'), 0) or 0)} screened, "
                    f"{int(_first_numeric(stats.get('portfolio_recs'), 0) or 0)} portfolio recs, "
                    f"{int(_first_numeric(stats.get('watchlist_recs'), 0) or 0)} watchlist recs, "
                    f"{int(_first_numeric(stats.get('signals_published'), 0) or 0)} signals published. "
                    f"{synthesis_detail}."
                ),
                checked_at=checked_at,
            )
        )
        for source_name, count in sorted(source_counts.items()):
            count_value = int(_first_numeric(count, 0) or 0)
            checks.append(
                DataSourceCheck(
                    source=f"{str(source_name).title()} result",
                    status="validated" if count_value > 0 else "configured",
                    detail=f"Pipeline attempted this source and received {count_value} raw candidates.",
                    checked_at=checked_at,
                )
            )
    elif scout_mode == "mock":
        checks.append(
            DataSourceCheck(
                source="OpenRouter scout",
                status="configured",
                detail="Mock mode active; no external model call was made.",
                checked_at=checked_at,
            )
        )
    else:
        checks.append(
            DataSourceCheck(
                source="OpenRouter scout",
                status="validated",
                detail=f"{_non_opus_openrouter_model(os.getenv('OPENROUTER_IDEA_MODEL', 'z-ai/glm-5.2'))} returned structured ideas.",
                checked_at=checked_at,
            )
        )

    scout_config = _safe_load_config("scout")
    advisor_config = _safe_load_config("advisor")
    portfolio_config = _safe_load_config("portfolio")
    sources_config = scout_config.get("sources") or {}

    if scout_mode == "alpha_scout":
        checks.extend([
            _module_config_check(
                source="Agent bus",
                module="src.shared.agent_bus",
                enabled=bool(sources_config.get("agent_bus")),
                configured_detail="Alpha Scout read available signals from the shared agent bus.",
                unavailable_detail="Enable sources.agent_bus in config/scout.yaml or fix agent bus imports.",
                checked_at=checked_at,
            ),
            _module_config_check(
                source="Supply chain",
                module="src.alpha_scout.supply_chain_sourcer",
                enabled=bool(sources_config.get("supply_chain")),
                configured_detail="Alpha Scout included supply-chain sourcing from current holdings.",
                unavailable_detail="Enable sources.supply_chain in config/scout.yaml or fix supply-chain imports.",
                checked_at=checked_at,
            ),
            _module_config_check(
                source="Sector peers",
                module="src.alpha_scout.candidate_sourcer",
                enabled=bool(sources_config.get("sector_peers")),
                configured_detail="Alpha Scout included configured sector peer maps.",
                unavailable_detail="Enable sources.sector_peers in config/scout.yaml.",
                checked_at=checked_at,
            ),
            _module_config_check(
                source="S&P 500 index",
                module="lxml",
                enabled=bool(sources_config.get("sp500_index")),
                configured_detail="Alpha Scout can parse S&P 500 constituents.",
                unavailable_detail="Install lxml or disable sources.sp500_index in config/scout.yaml.",
                checked_at=checked_at,
            ),
            _module_config_check(
                source="Superinvestor 13F",
                module="src.advisor.superinvestor_tracker",
                enabled=bool(sources_config.get("superinvestor_13f")),
                configured_detail="Alpha Scout included superinvestor 13F candidate sourcing.",
                unavailable_detail="Enable sources.superinvestor_13f in config/scout.yaml or fix 13F imports.",
                checked_at=checked_at,
            ),
            _module_config_check(
                source="Filing scanner",
                module="src.alpha_scout.filing_scanner",
                enabled=bool(sources_config.get("filing_scanner")),
                configured_detail="Alpha Scout included filing scanner candidate sourcing.",
                unavailable_detail="Enable sources.filing_scanner in config/scout.yaml or fix filing scanner imports.",
                checked_at=checked_at,
            ),
            _module_config_check(
                source="Thematic scanner",
                module="src.alpha_scout.thematic_scanner",
                enabled=bool(sources_config.get("thematic_scanner")),
                configured_detail="Alpha Scout has thematic scanner enabled; it runs when themes are provided.",
                unavailable_detail="Enable sources.thematic_scanner in config/scout.yaml or fix thematic scanner imports.",
                checked_at=checked_at,
            ),
        ])

    checks.append(_module_config_check(
        source="YFinance screeners",
        module="yfinance",
        enabled=bool(sources_config.get("yfinance_screener")),
        configured_detail=(
            "Alpha Scout attempted yfinance screeners and market-data fetches."
            if scout_mode == "alpha_scout"
            else "Screener source is enabled in config/scout.yaml."
        ),
        unavailable_detail="Install yfinance or enable yfinance_screener in config/scout.yaml.",
        checked_at=checked_at,
    ))
    checks.append(_module_config_check(
        source="Reddit moonshot",
        module="src.alpha_scout.reddit_moonshot_sourcer",
        enabled=bool(sources_config.get("reddit_moonshot")),
        configured_detail=(
            "Alpha Scout included Reddit moonshot sourcing in this pipeline run."
            if scout_mode == "alpha_scout"
            else "Reddit moonshot source is configured; not fetched during this scout request."
        ),
        unavailable_detail="Enable reddit_moonshot in config/scout.yaml or fix the sourcer import.",
        checked_at=checked_at,
    ))

    prediction_markets = advisor_config.get("prediction_markets") or {}
    checks.append(_module_config_check(
        source="Kalshi prediction markets",
        module="src.advisor.prediction_market",
        enabled=bool(prediction_markets.get("kalshi")),
        configured_detail=(
            "Kalshi is enabled in config/advisor.yaml; Alpha Scout does not query prediction markets yet."
            if scout_mode == "alpha_scout"
            else "Kalshi is enabled in config/advisor.yaml; not queried during this scout request."
        ),
        unavailable_detail="Enable prediction_markets.kalshi or fix prediction_market imports.",
        checked_at=checked_at,
    ))
    checks.append(_module_config_check(
        source="Polymarket prediction markets",
        module="src.advisor.prediction_market",
        enabled=bool(prediction_markets.get("polymarket")),
        configured_detail=(
            "Polymarket is enabled in config/advisor.yaml; Alpha Scout does not query prediction markets yet."
            if scout_mode == "alpha_scout"
            else "Polymarket is enabled in config/advisor.yaml; not queried during this scout request."
        ),
        unavailable_detail="Enable prediction_markets.polymarket or fix prediction_market imports.",
        checked_at=checked_at,
    ))

    holdings = portfolio_config.get("holdings")
    if isinstance(holdings, list) and holdings:
        checks.append(
            DataSourceCheck(
                source="Portfolio config",
                status="validated",
                detail=f"{len(holdings)} holdings loaded for top-buy inclusion and concentration context.",
                checked_at=checked_at,
            )
        )
    else:
        checks.append(
            DataSourceCheck(
                source="Portfolio config",
                status="unavailable",
                detail="No holdings loaded from config/portfolio.yaml.",
                checked_at=checked_at,
            )
        )

    roster_count = len(_openrouter_model_options()) if os.getenv("OPENROUTER_API_KEY") else len(enabled_roster(require_gcp_project=False))
    checks.append(
        DataSourceCheck(
            source="Council roster",
            status="validated" if roster_count > 0 else "unavailable",
            detail=f"{roster_count} council models available for follow-up runs.",
            checked_at=checked_at,
        )
    )
    return checks


def _module_config_check(
    source: str,
    module: str,
    enabled: bool,
    configured_detail: str,
    unavailable_detail: str,
    checked_at: str,
) -> DataSourceCheck:
    if not enabled:
        return DataSourceCheck(
            source=source,
            status="unavailable",
            detail=unavailable_detail,
            checked_at=checked_at,
        )
    try:
        __import__(module)
    except Exception as exc:
        return DataSourceCheck(
            source=source,
            status="unavailable",
            detail=f"{unavailable_detail} Import failed: {exc}",
            checked_at=checked_at,
        )
    return DataSourceCheck(
        source=source,
        status="configured",
        detail=configured_detail,
        checked_at=checked_at,
    )


def _repair_source_checks(value: Any) -> list[DataSourceCheck]:
    if not isinstance(value, list):
        return []
    checks: list[DataSourceCheck] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "").strip().lower()
        if status not in {"validated", "configured", "unavailable"}:
            status = "configured"
        source = _first_text(item.get("source"))
        if not source:
            continue
        checks.append(
            DataSourceCheck(
                source=source,
                status=status,  # type: ignore[arg-type]
                detail=_first_text(item.get("detail")) or "Source check returned without detail.",
                checked_at=_first_text(item.get("checked_at")) or date.today().isoformat(),
            )
        )
    return checks


def _safe_load_config(name: str) -> dict[str, Any]:
    try:
        config = load_config(name)
    except Exception:
        log.exception("Failed to load %s config for source checks", name)
        return {}
    return config if isinstance(config, dict) else {}


def _synthesize_openrouter_council(
    ticker: str,
    panel: list[PanelVerdict],
    cost_usd: float,
    degraded_reasons: list[str],
) -> CouncilResult:
    if not panel:
        raise RuntimeError("OpenRouter council returned no panel results.")

    marked_panel = _mark_dissent(panel)
    rating = _modal_rating(marked_panel)
    conviction = round(sum(item.confidence for item in marked_panel) / len(marked_panel), 2)
    contradictions = [
        f"{item.label} ({item.rating}) diverges from the modal rating."
        for item in marked_panel
        if item.rating != rating
    ]
    if not contradictions:
        contradictions = ["The direct model council returned no rating-level dissent."]
    claim_rejections = [
        f"{item.label}: {claim}"
        for item in marked_panel
        for claim in item.rejected_claims[:2]
    ]
    claim_challenges = [
        f"{item.label}: {claim}"
        for item in marked_panel
        for claim in item.challenges[:2]
    ]
    claim_acceptances = [
        f"{item.label}: {claim}"
        for item in marked_panel
        for claim in item.accepted_claims[:2]
    ]

    bullish = _panel_bullets(marked_panel, {"Buy", "Overweight"})
    bearish = _panel_bullets(marked_panel, {"Underweight", "Sell"})
    cautious = _panel_bullets(marked_panel, {"Hold"})
    crowded_flag = None
    if len(marked_panel) >= 3:
        positive = sum(1 for item in marked_panel if item.rating in {"Buy", "Overweight"})
        if positive >= len(marked_panel) - 1:
            crowded_flag = CrowdedFlag(
                topic="Consensus view",
                note="Most direct council models clustered bullish; treat the verdict as a crowded narrative check.",
            )

    judge = JudgeAnalysis(
        consensus=[
            f"Modal rating: {rating}",
            f"Average conviction: {conviction:.2f}",
            *(claim_acceptances[:2] or []),
        ],
        contradictions=(claim_rejections or contradictions)[:4],
        blind_spots=(
            claim_challenges
            or bearish
            or cautious
            or ["No explicit blind spot returned by the direct council."]
        )[:4],
        crowded_narrative_flag=crowded_flag,
    )
    verdict = Verdict(
        ticker=ticker,
        rating=rating,
        conviction=conviction,
        conviction_label="Direct OpenRouter council synthesis",
        scenarios=_scenarios_from_targets(None, None, None, conviction),
        catalysts=(claim_acceptances or bullish or [item.thesis for item in marked_panel])[:4],
        risks=(
            claim_rejections
            or claim_challenges
            or bearish
            or cautious
            or ["No explicit risk thesis returned by the direct council."]
        )[:4],
    )
    return CouncilResult(
        panel=marked_panel,
        judge=judge,
        verdict=verdict,
        cost_usd=round(cost_usd, 6),
        degraded_reasons=degraded_reasons,
    )


async def _run_openrouter_fusion(ticker: str, models: list[str]) -> CouncilResult:
    """Run OpenRouter Fusion and parse its structured AlphaDesk payload."""
    return await asyncio.to_thread(_run_openrouter_fusion_sync, ticker, models)


def _run_openrouter_fusion_sync(ticker: str, models: list[str]) -> CouncilResult:
    extra_body: dict[str, Any] = {"tool_choice": "required"}
    analysis_models = _openrouter_analysis_models(models)
    if analysis_models:
        extra_body["tools"] = [
            {
                "type": "openrouter:fusion",
                "parameters": {
                    "analysis_models": analysis_models,
                    "model": _non_opus_openrouter_model(os.getenv("OPENROUTER_FUSION_JUDGE", "z-ai/glm-5.2")),
                },
            }
        ]
    extra_body["plugins"] = [{"id": "response-healing"}]

    request_body = {
        "model": os.getenv("OPENROUTER_FUSION_MODEL", "openrouter/fusion"),
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are AlphaDesk's investment research chair. "
                    "Use Fusion deliberation, surface disagreement, and return only valid JSON."
                ),
            },
            {"role": "user", "content": _fusion_json_prompt(ticker)},
        ],
        "tool_choice": "required",
        "tools": extra_body.get("tools", []),
        "plugins": extra_body["plugins"],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "alphadesk_council_result",
                "strict": True,
                "schema": _council_result_json_schema(),
            },
        },
        "max_tokens": _openrouter_max_tokens(),
        "temperature": 0,
    }
    raw_request_body = {
        "model": request_body["model"],
        "messages": request_body["messages"],
        "tool_choice": "required",
        "max_tokens": request_body["max_tokens"],
        "temperature": 0,
    }

    request_headers = {
        "Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
        "HTTP-Referer": os.getenv("OPENROUTER_SITE_URL", "http://localhost:5173"),
        "X-Title": "AlphaDesk Cockpit",
    }

    response: Any = None
    if not os.getenv("OPENROUTER_FORCE_RAW_HTTP"):
        try:
            from openai import OpenAI

            client = OpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=os.environ["OPENROUTER_API_KEY"],
            )
            response = client.chat.completions.create(
                **request_body,
                extra_body=extra_body,
                extra_headers=request_headers,
                timeout=float(os.getenv("COUNCIL_MODEL_TIMEOUT_S", "60")),
            )
        except Exception:
            response = None

    if response is None:
        response = _openrouter_completion_raw(raw_request_body, request_headers, float(os.getenv("COUNCIL_MODEL_TIMEOUT_S", "60")))

    response_data = _to_plain_data(response)
    payload = _openrouter_choice_payload(response_data)
    if payload is None:
        raise RuntimeError("Fusion call returned an empty response.")
    if isinstance(payload, str):
        parsed = _extract_json_object(payload)
    else:
        parsed = payload
    result, repair_reasons = _normalize_openrouter_payload(parsed, ticker, analysis_models)
    if repair_reasons:
        result = result.model_copy(
            update={"degraded_reasons": [*result.degraded_reasons, *repair_reasons]}
        )

    usage = response_data.get("usage")
    cost = _openrouter_cost(response_data)
    if cost is None and usage is not None:
        cost = 0.0
    if cost is not None:
        result = result.model_copy(update={"cost_usd": cost})
    return result


def _normalize_openrouter_payload(
    payload: Any,
    ticker: str,
    requested_models: list[str],
) -> tuple[CouncilResult, list[str]]:
    normalized = _unwrap_openrouter_value(payload)
    reasons: list[str] = []

    if not isinstance(normalized, dict):
        raise RuntimeError("Fusion returned an unsupported result shape.")

    if {"panel", "judge", "verdict"}.issubset(normalized):
        repaired, repair_reasons = _repair_openrouter_payload(normalized, ticker)
        result = CouncilResult.model_validate(repaired)
        return result, repair_reasons

    if isinstance(normalized.get("panel"), list):
        repaired, repair_reasons = _repair_openrouter_payload(normalized, ticker)
        result = CouncilResult.model_validate(repaired)
        return result, repair_reasons

    envelope = normalized.get("investment_council") or normalized.get("investment_committee") or normalized
    if not isinstance(envelope, dict):
        raise RuntimeError("Fusion returned an unsupported result shape.")

    seats = envelope.get("seats") or normalized.get("council_seats") or []
    if not isinstance(seats, list) or not seats:
        raise RuntimeError("Fusion returned no council seats.")

    panel = [
        _panel_verdict_from_openrouter_seat(seat, index, requested_models, reasons)
        for index, seat in enumerate(seats)
    ]
    panel = _mark_dissent(panel)

    consensus_rating = _map_openrouter_rating(
        envelope.get("consensus_rating")
        or normalized.get("consensus_rating")
        or envelope.get("rating")
        or normalized.get("rating")
        or _modal_rating(panel)
    )
    conviction = _score_from_openrouter_number(
        envelope.get("consensus_conviction_score")
        or normalized.get("consensus_conviction_score")
        or envelope.get("conviction_score")
        or normalized.get("conviction_score")
        or sum(item.confidence for item in panel) / len(panel)
    )
    price_target = _first_numeric(
        envelope.get("consensus_price_target"),
        normalized.get("consensus_price_target"),
        envelope.get("price_target"),
        normalized.get("price_target"),
    )
    implied_return = _first_numeric(
        envelope.get("implied_return_pct"),
        normalized.get("implied_return_pct"),
    )
    time_horizon = str(envelope.get("time_horizon") or normalized.get("time_horizon") or "12 Months")

    judge = _judge_from_openrouter_envelope(normalized, envelope, panel, consensus_rating)
    verdict = _verdict_from_openrouter_envelope(
        ticker=ticker,
        normalized=normalized,
        envelope=envelope,
        panel=panel,
        consensus_rating=consensus_rating,
        conviction=conviction,
        price_target=price_target,
        implied_return=implied_return,
        time_horizon=time_horizon,
    )

    result = CouncilResult(
        panel=panel,
        judge=judge,
        verdict=verdict,
        cost_usd=0.0,
        degraded_reasons=[],
    )
    if normalized.get("investment_council") or normalized.get("investment_committee") or normalized.get("council_seats"):
        reasons.append("Fusion returned an AlphaDesk-mapped investment envelope; normalized into the cockpit contract.")
    return result, reasons


def _panel_verdict_from_openrouter_seat(
    seat: Any,
    index: int,
    requested_models: list[str],
    reasons: list[str],
) -> PanelVerdict:
    if not isinstance(seat, dict):
        reasons.append("Fusion returned a non-object council seat; replaced it with a degraded placeholder.")
        model_id = requested_models[index] if index < len(requested_models) else f"seat-{index + 1}"
        return PanelVerdict(
            model_id=model_id,
            label=f"Seat {index + 1}",
            rating="Hold",
            confidence=0.0,
            thesis="Fusion returned an incomplete council seat.",
            dissent=False,
        )

    model_id = requested_models[index] if index < len(requested_models) else str(seat.get("model_id") or seat.get("model") or f"seat-{index + 1}")
    label = str(seat.get("role") or seat.get("seat_type") or seat.get("label") or _label_from_model_id(model_id))
    rating = _map_openrouter_rating(seat.get("stance") or seat.get("rating") or seat.get("recommendation"))
    confidence = _score_from_openrouter_number(
        seat.get("conviction_score") or seat.get("confidence") or seat.get("conviction")
    )
    thesis = _first_text(
        seat.get("thesis_summary")
        or seat.get("thesis")
        or seat.get("summary")
        or seat.get("analysis")
        or seat.get("content")
        or (seat.get("core_arguments") or [None])[0]
    )
    if not thesis:
        thesis = "Fusion returned an incomplete council seat."
        reasons.append("Fusion payload omitted seat thesis; rendered a degraded placeholder.")
    return PanelVerdict(
        model_id=model_id,
        label=label,
        rating=rating,
        confidence=confidence,
        thesis=thesis,
        dissent=bool(seat.get("dissent", False)),
    )


def _judge_from_openrouter_envelope(
    normalized: dict[str, Any],
    envelope: dict[str, Any],
    panel: list[PanelVerdict],
    consensus_rating: Rating,
) -> JudgeAnalysis:
    consensus = _as_string_list(
        envelope.get("consensus")
        or envelope.get("consensus_points")
        or normalized.get("consensus")
        or normalized.get("consensus_points")
    )
    if not consensus:
        consensus = [
            f"Consensus rating: {consensus_rating}",
            f"Consensus conviction: {envelope.get('consensus_conviction_score') or normalized.get('consensus_conviction_score') or 'n/a'}",
        ]

    contradictions = _as_string_list(
        envelope.get("contradictions")
        or envelope.get("debates")
        or normalized.get("contradictions")
        or normalized.get("debates")
    )
    if not contradictions:
        modal = _modal_rating(panel)
        contradictions = [
            f"{item.label} ({item.rating}) diverges from the modal rating." for item in panel if item.rating != modal
        ]
    if not contradictions:
        contradictions = ["Fusion did not return an explicit contradiction field."]

    blind_spots = _as_string_list(
        envelope.get("blind_spots")
        or envelope.get("risks")
        or normalized.get("blind_spots")
        or normalized.get("risks")
    )
    if not blind_spots:
        blind_spots = [item.thesis for item in panel if item.rating in {"Underweight", "Sell"}][:2]
    if not blind_spots:
        blind_spots = ["Fusion did not return an explicit blind-spot field."]

    crowded_flag = _crowded_flag_from_any(
        envelope.get("crowded_narrative_flag")
        or envelope.get("narrative_flag")
        or normalized.get("crowded_narrative_flag")
        or normalized.get("narrative_flag")
    )
    if crowded_flag is None and len(panel) >= 3:
        bullish = sum(1 for item in panel if item.rating in {"Buy", "Overweight"})
        if bullish >= max(2, len(panel) - 1):
            crowded_flag = CrowdedFlag(
                topic="Consensus view",
                note="Fusion returned a clustered bullish council; confidence adjusted down.",
            )

    return JudgeAnalysis(
        consensus=consensus,
        contradictions=contradictions,
        blind_spots=blind_spots,
        crowded_narrative_flag=crowded_flag,
    )


def _verdict_from_openrouter_envelope(
    ticker: str,
    normalized: dict[str, Any],
    envelope: dict[str, Any],
    panel: list[PanelVerdict],
    consensus_rating: Rating,
    conviction: float,
    price_target: Optional[float],
    implied_return: Optional[float],
    time_horizon: str,
) -> Verdict:
    current_price = _first_numeric(
        envelope.get("current_price_usd"),
        normalized.get("current_price_usd"),
        _dig_number(normalized, ["market_context", "current_price_usd"]),
        _dig_number(normalized, ["market_snapshot", "current_price_usd"]),
    )
    target = price_target or _first_numeric(
        _dig_number(normalized, ["market_context", "valuation_metrics", "forward_pe_12m"]),
        _dig_number(normalized, ["market_snapshot", "valuation_metrics", "forward_pe_12m"]),
    )
    scenarios = _scenarios_from_targets(current_price, target, implied_return, conviction)
    catalysts = _extract_bullet_items(
        envelope.get("catalysts")
        or envelope.get("key_drivers")
        or normalized.get("catalysts")
        or normalized.get("key_drivers")
    )
    if not catalysts:
        catalysts = _panel_bullets(panel, {"Buy", "Overweight"})
    risks = _extract_bullet_items(
        envelope.get("risks")
        or envelope.get("key_risks")
        or normalized.get("risks")
        or normalized.get("key_risks")
    )
    if not risks:
        risks = _panel_bullets(panel, {"Underweight", "Sell"})

    conviction_label = str(
        envelope.get("conviction_label")
        or normalized.get("conviction_label")
        or f"{time_horizon} synthesis"
    )

    return Verdict(
        ticker=ticker,
        rating=consensus_rating,
        conviction=conviction,
        conviction_label=conviction_label,
        scenarios=scenarios,
        catalysts=catalysts[:4] if catalysts else ["Fusion did not return explicit catalysts."],
        risks=risks[:4] if risks else ["Fusion did not return explicit risks."],
    )


def _unwrap_openrouter_value(value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped[:1] in {"{", "[", "\""}:
            try:
                return _unwrap_openrouter_value(json.loads(stripped))
            except Exception:
                return value
        return value
    if isinstance(value, list):
        return [_unwrap_openrouter_value(item) for item in value]
    if isinstance(value, dict):
        if "completionState" in value and "type" in value:
            kind = value.get("type")
            if kind in {"Number", "String", "Boolean"}:
                return _unwrap_openrouter_value(value.get("value"))
            if kind == "Array":
                items = value.get("items") or []
                return [_unwrap_openrouter_value(item) for item in items]
            if kind == "Object":
                entries = value.get("entries")
                if isinstance(entries, list):
                    unwrapped: dict[str, Any] = {}
                    for entry in entries:
                        if isinstance(entry, (list, tuple)) and len(entry) == 2:
                            unwrapped[str(entry[0])] = _unwrap_openrouter_value(entry[1])
                    if unwrapped:
                        return unwrapped
        return {key: _unwrap_openrouter_value(item) for key, item in value.items()}
    return value


def _map_openrouter_rating(value: Any) -> Rating:
    text = str(value or "").strip().upper()
    if text in {"BUY", "OVERWEIGHT", "HOLD", "UNDERWEIGHT", "SELL"}:
        return text.title()  # type: ignore[return-value]
    if "STRONG BUY" in text or ("BUY" in text and "OVERWEIGHT" not in text):
        return "Buy"
    if "OVERWEIGHT" in text or "OUTPERFORM" in text:
        return "Overweight"
    if "UNDERWEIGHT" in text or "UNDERPERFORM" in text:
        return "Underweight"
    if "SELL" in text or "REDUCE" in text:
        return "Sell"
    if "HOLD" in text or "NEUTRAL" in text:
        return "Hold"
    return "Hold"


def _score_from_openrouter_number(value: Any) -> float:
    if isinstance(value, (int, float)):
        return max(0.0, min(1.0, float(value)))
    text = str(value or "").strip().upper()
    mapping = {
        "VERY HIGH": 0.9,
        "HIGH": 0.82,
        "MEDIUM-HIGH": 0.68,
        "MEDIUM HIGH": 0.68,
        "MEDIUM": 0.58,
        "LOW": 0.42,
    }
    for key, score in mapping.items():
        if key in text:
            return score
    try:
        return max(0.0, min(1.0, float(text)))
    except ValueError:
        return 0.5


def _first_numeric(*values: Any) -> Optional[float]:
    for value in values:
        if isinstance(value, (int, float)):
            number = float(value)
            if math.isfinite(number):
                return number
            continue
        if value is None:
            continue
        try:
            text = str(value).strip()
            if text:
                number = float(text.replace("$", "").replace("T", "").replace("B", ""))
                if math.isfinite(number):
                    return number
        except ValueError:
            continue
    return None


def _first_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    return ""


def _as_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            text = _first_text(item)
            if text:
                result.append(text)
        return result
    text = _first_text(value)
    return [text] if text else []


def _extract_bullet_items(value: Any) -> list[str]:
    if isinstance(value, list):
        bullets: list[str] = []
        for item in value:
            if isinstance(item, dict):
                text = _first_text(item.get("text") or item.get("thesis") or item.get("summary") or item.get("value"))
            else:
                text = _first_text(item)
            if text:
                bullets.append(text)
        return bullets
    if isinstance(value, dict):
        for key in ("items", "bullets", "points", "core_arguments", "arguments", "risks"):
            if key in value:
                return _extract_bullet_items(value[key])
    text = _first_text(value)
    return [text] if text else []


def _panel_bullets(panel: list[PanelVerdict], allowed_ratings: set[str]) -> list[str]:
    bullets: list[str] = []
    for item in panel:
        if item.rating in allowed_ratings and item.thesis:
            bullets.append(item.thesis)
    return bullets


def _crowded_flag_from_any(value: Any) -> Optional[CrowdedFlag]:
    if isinstance(value, CrowdedFlag):
        return value
    if isinstance(value, dict):
        topic = _first_text(value.get("topic"))
        note = _first_text(value.get("note"))
        if topic or note:
            return CrowdedFlag(topic=topic or "Consensus view", note=note or "Crowded narrative flag returned by Fusion.")
    return None


def _dig_number(value: Any, path: list[str]) -> Optional[float]:
    current = value
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return _first_numeric(current)


def _scenarios_from_targets(
    current_price: Optional[float],
    target_price: Optional[float],
    implied_return: Optional[float],
    conviction: float,
) -> list[Scenario]:
    if current_price and target_price and current_price > 0:
        base_ret = round((target_price / current_price - 1.0) * 100.0, 1)
    elif implied_return is not None:
        base_ret = round(float(implied_return), 1)
    else:
        base_ret = round((conviction - 0.5) * 40.0, 1)

    bull = round(base_ret + max(10.0, abs(base_ret) * 0.6), 1)
    bear = round(base_ret - max(20.0, abs(base_ret) * 1.2), 1)
    return [
        Scenario(name="Bull", probability=0.35, ret_pct=bull),
        Scenario(name="Base", probability=0.5, ret_pct=base_ret),
        Scenario(name="Bear", probability=0.15, ret_pct=bear),
    ]


def _repair_openrouter_payload(payload: dict[str, Any], ticker: str) -> tuple[dict[str, Any], list[str]]:
    repaired = dict(payload)
    reasons: list[str] = []

    if not isinstance(repaired.get("panel"), list):
        repaired["panel"] = []
        reasons.append("Fusion payload omitted panel results; rendered an empty panel.")
    repaired["panel"] = [_repair_panel_item(item, reasons) for item in repaired["panel"]]

    if "judge" not in repaired or not isinstance(repaired.get("judge"), dict):
        repaired["judge"] = {
            "consensus": [],
            "contradictions": [],
            "blind_spots": ["Fusion omitted structured judge analysis."],
            "crowded_narrative_flag": None,
        }
        reasons.append("Fusion payload omitted structured judge analysis.")

    if "verdict" not in repaired or not isinstance(repaired.get("verdict"), dict):
        repaired["verdict"] = _fallback_verdict(ticker, repaired["panel"])
        reasons.append("Fusion payload omitted structured verdict; rendered a degraded fallback.")

    if "cost_usd" not in repaired:
        repaired["cost_usd"] = 0.0
        reasons.append("Fusion payload omitted cost_usd; OpenRouter usage metadata was used when available.")
    if "degraded_reasons" not in repaired:
        repaired["degraded_reasons"] = []

    judge = repaired.get("judge")
    if isinstance(judge, dict) and "crowded_narrative_flag" not in judge:
        judge["crowded_narrative_flag"] = None
    if isinstance(judge, dict):
        judge["consensus"] = _as_string_list(judge.get("consensus") or judge.get("consensus_points"))
        judge["contradictions"] = _as_string_list(judge.get("contradictions") or judge.get("debates"))
        judge["blind_spots"] = _as_string_list(judge.get("blind_spots") or judge.get("risks"))
        judge["crowded_narrative_flag"] = _crowded_flag_from_any(
            judge.get("crowded_narrative_flag") or judge.get("narrative_flag")
        )

    verdict = repaired.get("verdict")
    if isinstance(verdict, dict):
        verdict.setdefault("ticker", ticker)
        verdict.setdefault("rating", _rating_from_panel(repaired["panel"]))
        verdict.setdefault("conviction", _confidence_from_panel(repaired["panel"]))
        verdict.setdefault("conviction_label", "Degraded fallback from partial Fusion payload")
        for key in ("scenarios", "catalysts", "risks"):
            if key not in verdict:
                verdict[key] = []
                reasons.append(f"Fusion payload omitted verdict.{key}; rendered it as empty.")
        verdict["rating"] = _map_openrouter_rating(verdict.get("rating"))
        verdict["conviction"] = _score_from_openrouter_number(verdict.get("conviction"))
        verdict["catalysts"] = _extract_bullet_items(verdict.get("catalysts"))
        verdict["risks"] = _extract_bullet_items(verdict.get("risks"))
        if not verdict.get("scenarios"):
            verdict["scenarios"] = _scenarios_from_targets(
                _first_numeric(verdict.get("current_price_usd")),
                _first_numeric(verdict.get("consensus_price_target")),
                _first_numeric(verdict.get("implied_return_pct")),
                _score_from_openrouter_number(verdict.get("conviction")),
            )

    return repaired, reasons


def _repair_panel_item(item: Any, reasons: list[str]) -> dict[str, Any]:
    if not isinstance(item, dict):
        reasons.append("Fusion returned a non-object panel entry; replaced it with a degraded placeholder.")
        return {
            "model_id": "unknown",
            "label": "Unknown model",
            "rating": "Hold",
            "confidence": 0.0,
            "thesis": "Fusion returned an incomplete panel entry.",
            "dissent": False,
        }

    repaired = dict(item)
    model_id = str(repaired.get("model_id") or repaired.get("model") or "unknown")
    repaired["model_id"] = model_id
    repaired.setdefault("label", _label_from_model_id(model_id))
    repaired.setdefault("rating", "Hold")
    repaired.setdefault("confidence", 0.0)
    repaired.setdefault(
        "thesis",
        str(repaired.get("analysis") or repaired.get("content") or "Fusion returned an incomplete panel entry."),
    )
    repaired.setdefault("dissent", False)
    repaired["accepted_claims"] = _extract_bullet_items(
        repaired.get("accepted_claims") or repaired.get("accepted") or []
    )[:4]
    repaired["rejected_claims"] = _extract_bullet_items(
        repaired.get("rejected_claims") or repaired.get("rejected") or []
    )[:4]
    repaired["challenges"] = _extract_bullet_items(
        repaired.get("challenges") or repaired.get("open_questions") or repaired.get("critiques") or []
    )[:4]
    for key in ("confidence", "thesis"):
        if key not in item:
            reasons.append(f"Fusion payload omitted panel.{key}; rendered a degraded placeholder.")
    return repaired


def _fallback_verdict(ticker: str, panel: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "rating": _rating_from_panel(panel),
        "conviction": _confidence_from_panel(panel),
        "conviction_label": "Degraded fallback from partial Fusion payload",
        "scenarios": [],
        "catalysts": [],
        "risks": ["Fusion omitted structured verdict."],
    }


def _rating_from_panel(panel: list[dict[str, Any]]) -> Rating:
    counts: dict[str, int] = {}
    for item in panel:
        rating = item.get("rating")
        if rating in {"Buy", "Overweight", "Hold", "Underweight", "Sell"}:
            counts[str(rating)] = counts.get(str(rating), 0) + 1
    if not counts:
        return "Hold"
    return max(counts.items(), key=lambda pair: pair[1])[0]  # type: ignore[return-value]


def _confidence_from_panel(panel: list[dict[str, Any]]) -> float:
    confidences = [
        float(item.get("confidence"))
        for item in panel
        if isinstance(item.get("confidence"), (int, float))
    ]
    if not confidences:
        return 0.0
    return round(sum(confidences) / len(confidences), 2)


def _openrouter_analysis_models(models: list[str]) -> list[str]:
    selected = models or [model.model_id for model in _openrouter_model_options() if model.enabled]
    analysis_models: list[str] = []
    for model in selected:
        normalized = OPENROUTER_MODEL_ALIASES.get(model, model)
        if normalized == os.getenv("OPENROUTER_FUSION_MODEL", "openrouter/fusion"):
            continue
        if _is_opus_openrouter_model(normalized):
            continue
        if normalized not in analysis_models:
            analysis_models.append(normalized)
    return analysis_models[:8]


def _openrouter_model_options() -> list[ModelOption]:
    configured = os.getenv("OPENROUTER_ANALYSIS_MODELS", "").strip()
    if not configured:
        return DEFAULT_OPENROUTER_ANALYSIS_MODELS

    options: list[ModelOption] = []
    for model_id in [item.strip() for item in configured.split(",") if item.strip()]:
        if _is_opus_openrouter_model(model_id):
            continue
        options.append(
            ModelOption(
                model_id=model_id,
                label=_label_from_model_id(model_id),
                provider=model_id.split("/", 1)[0] if "/" in model_id else "openrouter",
                enabled=True,
            )
        )
    return options or DEFAULT_OPENROUTER_ANALYSIS_MODELS


def _is_opus_openrouter_model(model_id: str) -> bool:
    return "opus" in model_id.lower()


def _non_opus_openrouter_model(model_id: str) -> str:
    return "z-ai/glm-5.2" if _is_opus_openrouter_model(model_id) else model_id


def _label_from_model_id(model_id: str) -> str:
    name = model_id.split("/")[-1]
    return name.replace("-", " ").replace(".", " ").title()


def _normalize_council_result(ticker: str, raw_result: Any, models: list[str]) -> CouncilResult:
    if isinstance(raw_result, CouncilResult):
        return raw_result.model_copy(update={"execution_mode": raw_result.execution_mode or "gcp_council"})
    raw_payload = _to_plain_data(raw_result)
    if isinstance(raw_payload, dict) and {"panel", "judge", "verdict"}.issubset(raw_payload):
        result = CouncilResult.model_validate(raw_payload)
        return result.model_copy(update={"execution_mode": result.execution_mode or "gcp_council"})

    if isinstance(raw_payload, list):
        panel = [_panel_from_text_response(item) for item in raw_payload]
        if not panel:
            raise RuntimeError("Council returned no panel results.")
        panel = _mark_dissent(panel)
        rating = _modal_rating(panel)
        return CouncilResult(
            panel=panel,
            judge=JudgeAnalysis(
                consensus=["Panel completed, but no structured judge payload was returned."],
                contradictions=[],
                blind_spots=["Structured Fusion judge analysis was unavailable."],
            ),
            verdict=Verdict(
                ticker=ticker,
                rating=rating,
                conviction=round(sum(item.confidence for item in panel) / len(panel), 2),
                conviction_label="Preliminary — structured judge unavailable",
                scenarios=[
                    Scenario(name="Bull", probability=0.25, ret_pct=0.0),
                    Scenario(name="Base", probability=0.50, ret_pct=0.0),
                    Scenario(name="Bear", probability=0.25, ret_pct=0.0),
                ],
                catalysts=[],
                risks=["Structured verdict unavailable from council output."],
            ),
            cost_usd=0.0,
            degraded_reasons=["Council output was normalized from unstructured model responses."],
            execution_mode="gcp_council",
        )

    raise RuntimeError("Council returned an unsupported result shape.")


def _panel_from_text_response(item: dict[str, Any]) -> PanelVerdict:
    error = item.get("error")
    text = str(item.get("text") or "").strip()
    if error:
        thesis = f"Model failed: {error}"
        confidence = 0.0
        rating: Rating = "Hold"
    else:
        thesis = text.splitlines()[0][:180] if text else "No thesis returned."
        confidence = 0.5
        rating = "Hold"
    return PanelVerdict(
        model_id=str(item.get("model") or item.get("model_id") or "unknown"),
        label=str(item.get("label") or item.get("model") or "Unknown model"),
        rating=rating,
        confidence=confidence,
        thesis=thesis,
        dissent=False,
    )


def _mark_dissent(panel: list[PanelVerdict]) -> list[PanelVerdict]:
    modal = _modal_rating(panel)
    return [item.model_copy(update={"dissent": item.rating != modal}) for item in panel]


def _modal_rating(panel: list[PanelVerdict]) -> Rating:
    counts: dict[str, int] = {}
    for item in panel:
        counts[item.rating] = counts.get(item.rating, 0) + 1
    return max(counts.items(), key=lambda pair: pair[1])[0]  # type: ignore[return-value]


def _to_plain_data(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump()
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [_to_plain_data(item) for item in value]
    if isinstance(value, dict):
        return {key: _to_plain_data(item) for key, item in value.items()}
    if hasattr(value, "__dict__"):
        return {
            key: _to_plain_data(item)
            for key, item in vars(value).items()
            if not key.startswith("_")
        }
    return value


def _openrouter_choice_payload(response_data: dict[str, Any]) -> Any:
    choices = response_data.get("choices")
    if not isinstance(choices, list) or not choices:
        return None

    choice = choices[0]
    if not isinstance(choice, dict):
        return None

    message = choice.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                text = _first_text(
                    item.get("text") if isinstance(item, dict) else item
                )
                if text:
                    parts.append(text)
            if parts:
                return "\n".join(parts)
        for tool_call in message.get("tool_calls") or []:
            if not isinstance(tool_call, dict):
                continue
            function = tool_call.get("function")
            if isinstance(function, dict):
                arguments = function.get("arguments")
                if arguments not in (None, "", [], {}):
                    return arguments
            arguments = tool_call.get("arguments")
            if arguments not in (None, "", [], {}):
                return arguments
        for key in ("parsed", "output_text", "output", "text"):
            value = message.get(key)
            if value not in (None, "", [], {}):
                return value

    for key in ("parsed", "output_text", "output", "text"):
        value = choice.get(key)
        if value not in (None, "", [], {}):
            return value

    return None


def _openrouter_completion_raw(
    request_body: dict[str, Any],
    request_headers: dict[str, str],
    timeout_s: float,
) -> dict[str, Any]:
    payload = json.dumps(request_body).encode("utf-8")
    headers = dict(request_headers)
    headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=payload,
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            raw_text = response.read().decode(charset, errors="replace")
    except urllib.error.HTTPError as exc:
        charset = exc.headers.get_content_charset() if exc.headers is not None else None
        body = exc.read().decode(charset or "utf-8", errors="replace")
        raise RuntimeError(f"OpenRouter raw request failed with HTTP {exc.code}: {body}") from None
    except Exception as exc:
        raise RuntimeError(f"OpenRouter raw request failed: {exc}") from exc

    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        start = raw_text.find("{")
        end = raw_text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(raw_text[start : end + 1])
        raise RuntimeError("OpenRouter raw response did not contain JSON.") from None


def _apply_cost_guardrail(result: CouncilResult) -> CouncilResult:
    cap = _cost_cap_usd()
    if result.cost_usd <= cap:
        return result
    reasons = list(result.degraded_reasons)
    reasons.append(f"Council cost ${result.cost_usd:.2f} exceeded cap ${cap:.2f}.")
    return result.model_copy(update={"degraded_reasons": reasons})


def _sse(event: str, data: Any) -> str:
    payload = _to_plain_data(data)
    return f"event: {event}\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n"


def _parse_models(models: str) -> list[str]:
    return [model.strip() for model in models.split(",") if model.strip()]


def _extract_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        parsed = json.loads(cleaned, strict=False)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise RuntimeError("Fusion response did not contain a JSON object.") from None
        parsed = json.loads(cleaned[start : end + 1], strict=False)
    if not isinstance(parsed, dict):
        raise RuntimeError("Fusion response JSON must be an object.")
    return parsed


def _openrouter_cost(response: Any) -> Optional[float]:
    usage = response.get("usage") if isinstance(response, dict) else getattr(response, "usage", None)
    if usage is None:
        return None
    if isinstance(usage, dict):
        for key in ("cost", "cost_usd", "total_cost"):
            value = usage.get(key)
            if value is not None:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    return None
    else:
        for attr in ("cost", "cost_usd", "total_cost"):
            value = getattr(usage, attr, None)
            if value is not None:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    return None
    return None


def _clean_ticker(ticker: str) -> str:
    return ticker.strip().upper()


def _cost_cap_usd() -> float:
    try:
        return float(os.getenv("COUNCIL_COST_CAP_USD", "2.00"))
    except ValueError:
        return 2.0


def _stream_timeout_s() -> float:
    try:
        return float(os.getenv("COUNCIL_STREAM_TIMEOUT_S", os.getenv("COUNCIL_MODEL_TIMEOUT_S", "60")))
    except ValueError:
        return 60.0


def _model_timeout_s() -> float:
    try:
        return float(os.getenv("COUNCIL_MODEL_TIMEOUT_S", "60"))
    except ValueError:
        return 60.0


def _openrouter_max_tokens() -> int:
    try:
        return max(64, int(os.getenv("OPENROUTER_MAX_TOKENS", "2400")))
    except ValueError:
        return 2400


def _openrouter_model_max_tokens() -> int:
    try:
        return max(64, int(os.getenv("OPENROUTER_MODEL_MAX_TOKENS", "420")))
    except ValueError:
        return 420


def _openrouter_idea_max_tokens() -> int:
    try:
        return max(512, int(os.getenv("OPENROUTER_IDEA_MAX_TOKENS", "2200")))
    except ValueError:
        return 2200


def _mock_openrouter_enabled() -> bool:
    return os.getenv("OPENROUTER_MOCK", "").strip().lower() in {"1", "true", "yes"}


def _mock_alpha_scout_enabled() -> bool:
    return os.getenv("ALPHA_SCOUT_MOCK", "").strip().lower() in {"1", "true", "yes"}


def _alpha_scout_timeout_s() -> float:
    try:
        return float(os.getenv("ALPHA_SCOUT_TIMEOUT_S", "180"))
    except ValueError:
        return 180.0


def _portfolio_threshold() -> float:
    try:
        advisor = load_config("advisor")
        strategy = advisor.get("strategy", {}) or {}
        return float(strategy.get("max_position_pct", 15))
    except Exception:
        return 15.0


def _council_prompt(ticker: str) -> str:
    return (
        "Run an AlphaDesk investment council on this ticker or idea. "
        "Return the rating, confidence, thesis, contradictions, blind spots, "
        f"scenario returns, catalysts, and risks for: {ticker}"
    )


def _fusion_json_prompt(ticker: str) -> str:
    return (
        f"Return one JSON object for an AlphaDesk council on {ticker}. "
        "Use keys: panel, judge, verdict, cost_usd, degraded_reasons. "
        "panel items need model_id, label, rating, confidence, thesis, dissent. "
        "judge needs consensus, contradictions, blind_spots, crowded_narrative_flag. "
        "verdict needs ticker, rating, conviction, conviction_label, scenarios, catalysts, risks. "
        "Use ratings only from Buy, Overweight, Hold, Underweight, Sell. "
        "Set dissent true when a seat differs from the modal rating. "
        "Always include crowded_narrative_flag. No markdown."
    )


def _panel_model_json_prompt(ticker: str, model_id: str) -> str:
    return (
        f"Analyze {ticker} as council seat {model_id}. "
        "Return JSON with model_id, label, rating, confidence, thesis, dissent, "
        "accepted_claims, rejected_claims, and challenges. "
        "rating must be Buy, Overweight, Hold, Underweight, or Sell. "
        "confidence must be 0 to 1. "
        "thesis should be one sentence with the main catalyst and risk. "
        "For the first pass, put your own strongest assumptions in accepted_claims, "
        "your rejected market assumptions in rejected_claims, and due-diligence questions in challenges. "
        "Set dissent false; the server will mark dissent after all models vote."
    )


def _panel_cross_exam_json_prompt(
    ticker: str,
    model_id: str,
    own_verdict: PanelVerdict,
    panel: list[PanelVerdict],
) -> str:
    claims = [
        {
            "model_id": item.model_id,
            "rating": item.rating,
            "confidence": item.confidence,
            "thesis": item.thesis,
        }
        for item in panel
    ]
    return (
        f"Reassess {ticker} as council seat {model_id} after reading the other model claims. "
        f"Your first-pass view was {own_verdict.rating} at {own_verdict.confidence:.2f}: {own_verdict.thesis}\n"
        f"All council claims: {json.dumps(claims, separators=(',', ':'))}\n"
        "Return JSON with model_id, label, rating, confidence, thesis, dissent, accepted_claims, "
        "rejected_claims, and challenges. accepted_claims must name claims from other models you accept. "
        "rejected_claims must name claims from other models you reject or discount. "
        "challenges must be skeptical questions or missing evidence that could change the verdict. "
        "Revise rating/confidence if the cross-examination changes your view. "
        "Use only ratings Buy, Overweight, Hold, Underweight, or Sell. No markdown."
    )


def _idea_scout_json_prompt(limit: int) -> str:
    return (
        f"Today is {date.today().isoformat()}. Find the top {limit} US-listed stocks or ADRs "
        "worth researching today for a growth-oriented public-equity portfolio. "
        "Use a broad lens across AI infrastructure, software, semis, healthcare, consumer, fintech, "
        "industrials, energy, and special situations. Avoid penny stocks and illiquid microcaps. "
        "Return one JSON object with as_of, universe, ideas, data_source_checks, cost_usd, degraded_reasons, and disclaimer. "
        "Each idea needs rank, ticker, company, theme, score from 0 to 1, horizon, one-sentence thesis, "
        "2-3 catalysts, 2-3 risks, and source. The output is research candidates only, not personal advice. "
        "Set data_source_checks to an empty array; the server will replace it with verified checks. "
        "No markdown."
    )


def _idea_scout_json_schema() -> dict[str, Any]:
    source_check = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "source": {"type": "string"},
            "status": {"type": "string", "enum": ["validated", "configured", "unavailable"]},
            "detail": {"type": "string"},
            "checked_at": {"type": "string"},
        },
        "required": ["source", "status", "detail", "checked_at"],
    }
    idea = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "rank": {"type": "integer", "minimum": 1, "maximum": 12},
            "ticker": {"type": "string"},
            "company": {"type": "string"},
            "theme": {"type": "string"},
            "score": {"type": "number", "minimum": 0, "maximum": 1},
            "horizon": {"type": "string"},
            "thesis": {"type": "string"},
            "catalysts": {"type": "array", "items": {"type": "string"}},
            "risks": {"type": "array", "items": {"type": "string"}},
            "source": {"type": "string"},
        },
        "required": [
            "rank",
            "ticker",
            "company",
            "theme",
            "score",
            "horizon",
            "thesis",
            "catalysts",
            "risks",
            "source",
        ],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "as_of": {"type": "string"},
            "universe": {"type": "string"},
            "ideas": {"type": "array", "minItems": 10, "maxItems": 12, "items": idea},
            "data_source_checks": {"type": "array", "items": source_check},
            "cost_usd": {"type": "number", "minimum": 0},
            "degraded_reasons": {"type": "array", "items": {"type": "string"}},
            "disclaimer": {"type": "string"},
        },
        "required": [
            "as_of",
            "universe",
            "ideas",
            "data_source_checks",
            "cost_usd",
            "degraded_reasons",
            "disclaimer",
        ],
    }


def _panel_verdict_json_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "model_id": {"type": "string"},
            "label": {"type": "string"},
            "rating": {
                "type": "string",
                "enum": ["Buy", "Overweight", "Hold", "Underweight", "Sell"],
            },
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "thesis": {"type": "string"},
            "dissent": {"type": "boolean"},
            "accepted_claims": {"type": "array", "items": {"type": "string"}},
            "rejected_claims": {"type": "array", "items": {"type": "string"}},
            "challenges": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "model_id",
            "label",
            "rating",
            "confidence",
            "thesis",
            "dissent",
            "accepted_claims",
            "rejected_claims",
            "challenges",
        ],
    }


def _council_result_json_schema() -> dict[str, Any]:
    rating_enum = ["Buy", "Overweight", "Hold", "Underweight", "Sell"]
    panel_verdict = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "model_id": {"type": "string"},
            "label": {"type": "string"},
            "rating": {"type": "string", "enum": rating_enum},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "thesis": {"type": "string"},
            "dissent": {"type": "boolean"},
            "accepted_claims": {"type": "array", "items": {"type": "string"}},
            "rejected_claims": {"type": "array", "items": {"type": "string"}},
            "challenges": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "model_id",
            "label",
            "rating",
            "confidence",
            "thesis",
            "dissent",
            "accepted_claims",
            "rejected_claims",
            "challenges",
        ],
    }
    crowded_flag = {
        "type": ["object", "null"],
        "additionalProperties": False,
        "properties": {
            "topic": {"type": "string"},
            "note": {"type": "string"},
        },
        "required": ["topic", "note"],
    }
    scenario = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "name": {"type": "string", "enum": ["Bull", "Base", "Bear"]},
            "probability": {"type": "number", "minimum": 0, "maximum": 1},
            "ret_pct": {"type": "number"},
        },
        "required": ["name", "probability", "ret_pct"],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "panel": {"type": "array", "items": panel_verdict},
            "judge": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "consensus": {"type": "array", "items": {"type": "string"}},
                    "contradictions": {"type": "array", "items": {"type": "string"}},
                    "blind_spots": {"type": "array", "items": {"type": "string"}},
                    "crowded_narrative_flag": crowded_flag,
                },
                "required": [
                    "consensus",
                    "contradictions",
                    "blind_spots",
                    "crowded_narrative_flag",
                ],
            },
            "verdict": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "ticker": {"type": "string"},
                    "rating": {"type": "string", "enum": rating_enum},
                    "conviction": {"type": "number", "minimum": 0, "maximum": 1},
                    "conviction_label": {"type": "string"},
                    "scenarios": {"type": "array", "items": scenario},
                    "catalysts": {"type": "array", "items": {"type": "string"}},
                    "risks": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "ticker",
                    "rating",
                    "conviction",
                    "conviction_label",
                    "scenarios",
                    "catalysts",
                    "risks",
                ],
            },
            "cost_usd": {"type": "number", "minimum": 0},
            "degraded_reasons": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["panel", "judge", "verdict", "cost_usd", "degraded_reasons"],
    }
