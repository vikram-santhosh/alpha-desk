"""FastAPI surface for the on-demand AlphaDesk research cockpit."""
from __future__ import annotations

import asyncio
import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import asdict, is_dataclass
from datetime import date
from typing import Any, Generator, Literal, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.advisor import council
from src.shared.config_loader import load_config
from src.shared.model_registry import enabled_roster
from src.utils.logger import get_logger

log = get_logger(__name__)

Rating = Literal["Buy", "Overweight", "Hold", "Underweight", "Sell"]
SourceStatus = Literal["validated", "configured", "unavailable"]


class PanelVerdict(BaseModel):
    model_id: str
    label: str
    rating: Rating
    confidence: float = Field(ge=0.0, le=1.0)
    thesis: str
    dissent: bool = False


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
    as_of: str
    universe: str
    scout_mode: str = "unknown"
    ideas: list[TopIdea]
    data_source_checks: list[DataSourceCheck]
    audit: IdeaScoutAudit = Field(default_factory=IdeaScoutAudit)
    cost_usd: float = Field(ge=0.0)
    degraded_reasons: list[str] = Field(default_factory=list)
    disclaimer: str


DEFAULT_OPENROUTER_ANALYSIS_MODELS = [
    ModelOption(
        model_id="google/gemini-3.5-flash",
        label="Gemini 3.5 Flash",
        provider="google",
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
        model_id="z-ai/glm-5.2",
        label="GLM 5.2",
        provider="z-ai",
        enabled=True,
    ),
]

OPENROUTER_MODEL_ALIASES = {
    "claude-opus-4-8": "anthropic/claude-opus-4.8",
    "gemini-flash-3.5": "google/gemini-3.5-flash",
    "gemini-3.5-flash": "google/gemini-3.5-flash",
    "gemini-3.1-pro-preview": "google/gemini-3.1-pro-preview",
    "kimi-k2.6": "moonshotai/kimi-k2.6",
    "deepseek-v4-pro": "deepseek/deepseek-v4-pro",
    "glm-5.2": "z-ai/glm-5.2",
    "xai/grok-4.20-reasoning": "x-ai/grok-4.3",
}


app = FastAPI(title="AlphaDesk Cockpit API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
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
    return _apply_cost_guardrail(result)


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

    async def event_generator() -> Generator[str, None, None]:
        yield _sse("panel_started", {"ticker": ticker_value, "models": model_ids})
        try:
            if _cost_cap_usd() <= 0:
                done = DoneEvent(
                    degraded_reasons=["Council skipped because COUNCIL_COST_CAP_USD is 0."],
                    council_mode="skipped",
                )
                yield _sse("done", done)
                return

            result = _apply_cost_guardrail(
                await asyncio.wait_for(
                    _run_council(ticker_value, model_ids),
                    timeout=_stream_timeout_s(),
                )
            )
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
            return _idea_scout_from_alpha_scout(pipeline_result, limit)
        except Exception as exc:
            log.exception("Alpha Scout full pipeline failed; falling back to direct idea scout")
            fallback_reason = f"Alpha Scout full pipeline failed: {exc}"
    else:
        fallback_reason = "Alpha Scout full pipeline skipped because ALPHA_SCOUT_MOCK=1."

    if os.getenv("OPENROUTER_API_KEY"):
        result = await asyncio.to_thread(_run_openrouter_idea_scout_sync, limit)
    else:
        result = _mock_today_ideas(limit)
    return _with_alpha_scout_fallback_reason(result, fallback_reason)


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


async def _run_council(ticker: str, models: list[str]) -> CouncilResult:
    """Run the underlying council and normalize it into the Phase-F contract."""
    if os.getenv("OPENROUTER_API_KEY"):
        return await _run_openrouter_council(ticker, models)
    prompt = _council_prompt(ticker)
    raw_result = await council.deliberate(prompt=prompt, max_tokens=1400)
    return _normalize_council_result(ticker, raw_result, models)


async def _run_openrouter_council(ticker: str, models: list[str]) -> CouncilResult:
    """Run a direct OpenRouter model council without the Fusion server tool."""
    selected_models = _openrouter_analysis_models(models)
    execution_mode = "openrouter_mock" if _mock_openrouter_enabled() else "openrouter_live"
    tasks = [
        asyncio.to_thread(_run_openrouter_panel_model_sync, ticker, model_id)
        for model_id in selected_models
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

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

    return _synthesize_openrouter_council(ticker, panel, cost_usd, degraded_reasons).model_copy(
        update={"execution_mode": execution_mode}
    )


def _run_openrouter_panel_model_sync(ticker: str, model_id: str) -> tuple[PanelVerdict, float]:
    if _mock_openrouter_enabled():
        return _mock_openrouter_panel_model(ticker, model_id), 0.0

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
                    "You are one AlphaDesk investment council seat. "
                    "Return only valid JSON and keep the thesis concise."
                ),
            },
            {"role": "user", "content": _panel_model_json_prompt(ticker, model_id)},
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

    timeout_s = float(os.getenv("COUNCIL_MODEL_TIMEOUT_S", "60"))
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
        raise RuntimeError("Model returned an empty response.")
    parsed = _extract_json_object(payload) if isinstance(payload, str) else payload
    reasons: list[str] = []
    repaired = _repair_panel_item(parsed, reasons)
    repaired["model_id"] = model_id
    repaired["label"] = _label_from_model_id(model_id)
    repaired["rating"] = _map_openrouter_rating(repaired.get("rating"))
    repaired["confidence"] = _score_from_openrouter_number(repaired.get("confidence"))
    panel = PanelVerdict.model_validate(repaired)
    return panel, _openrouter_cost(response_data) or 0.0


def _mock_openrouter_panel_model(ticker: str, model_id: str) -> PanelVerdict:
    rating_by_model: dict[str, Rating] = {
        "google/gemini-3.5-flash": "Overweight",
        "moonshotai/kimi-k2.6": "Buy",
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
    if result.get("formatted") and "No new candidates" in str(result.get("formatted")):
        degraded.append("Alpha Scout completed but found no new candidates.")
    if not recommendations.get("portfolio_recs") and result.get("scored_candidates"):
        degraded.append("Alpha Scout synthesis returned no buy bucket; ranked scored candidates directly.")

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
        cost_usd=0.0,
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


def _run_openrouter_idea_scout_sync(limit: int) -> IdeaScoutResult:
    if _mock_openrouter_enabled():
        return _mock_today_ideas(limit)

    model_id = os.getenv("OPENROUTER_IDEA_MODEL", "google/gemini-3.5-flash")
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
        checks.append(
            DataSourceCheck(
                source="Alpha Scout pipeline",
                status="validated",
                detail=(
                    f"{int(_first_numeric(stats.get('candidates_sourced'), 0) or 0)} sourced, "
                    f"{int(_first_numeric(stats.get('candidates_screened'), 0) or 0)} screened, "
                    f"{int(_first_numeric(stats.get('portfolio_recs'), 0) or 0)} portfolio recs, "
                    f"{int(_first_numeric(stats.get('watchlist_recs'), 0) or 0)} watchlist recs, "
                    f"{int(_first_numeric(stats.get('signals_published'), 0) or 0)} signals published."
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
                detail=f"{os.getenv('OPENROUTER_IDEA_MODEL', 'google/gemini-3.5-flash')} returned structured ideas.",
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
        ],
        contradictions=contradictions,
        blind_spots=(bearish or cautious or ["No explicit blind spot returned by the direct council."])[:3],
        crowded_narrative_flag=crowded_flag,
    )
    verdict = Verdict(
        ticker=ticker,
        rating=rating,
        conviction=conviction,
        conviction_label="Direct OpenRouter council synthesis",
        scenarios=_scenarios_from_targets(None, None, None, conviction),
        catalysts=(bullish or [item.thesis for item in marked_panel])[:4],
        risks=(bearish or cautious or ["No explicit risk thesis returned by the direct council."])[:4],
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
                    "model": os.getenv("OPENROUTER_FUSION_JUDGE", "anthropic/claude-opus-4.8"),
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
            return float(value)
        if value is None:
            continue
        try:
            text = str(value).strip()
            if text:
                return float(text.replace("$", "").replace("T", "").replace("B", ""))
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
        if normalized not in analysis_models:
            analysis_models.append(normalized)
    return analysis_models[:8]


def _openrouter_model_options() -> list[ModelOption]:
    configured = os.getenv("OPENROUTER_ANALYSIS_MODELS", "").strip()
    if not configured:
        return DEFAULT_OPENROUTER_ANALYSIS_MODELS

    options: list[ModelOption] = []
    for model_id in [item.strip() for item in configured.split(",") if item.strip()]:
        options.append(
            ModelOption(
                model_id=model_id,
                label=_label_from_model_id(model_id),
                provider=model_id.split("/", 1)[0] if "/" in model_id else "openrouter",
                enabled=True,
            )
        )
    return options or DEFAULT_OPENROUTER_ANALYSIS_MODELS


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
        "Return JSON with model_id, label, rating, confidence, thesis, dissent. "
        "rating must be Buy, Overweight, Hold, Underweight, or Sell. "
        "confidence must be 0 to 1. "
        "thesis should be one sentence with the main catalyst and risk. "
        "Set dissent false; the server will mark dissent after all models vote."
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
        },
        "required": ["model_id", "label", "rating", "confidence", "thesis", "dissent"],
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
        },
        "required": ["model_id", "label", "rating", "confidence", "thesis", "dissent"],
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
