"""FastAPI surface for the on-demand AlphaDesk research cockpit."""
from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import asdict, is_dataclass
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


class RunRequest(BaseModel):
    ticker: str = Field(min_length=1)
    models: list[str] = Field(default_factory=list)


class DoneEvent(BaseModel):
    cost_usd: float = 0.0
    degraded_reasons: list[str] = Field(default_factory=list)


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
                    degraded_reasons=["Council skipped because COUNCIL_COST_CAP_USD is 0."]
                )
                yield _sse("done", done)
                return

            result = _apply_cost_guardrail(await _run_council(ticker_value, model_ids))
            for panel_result in result.panel:
                yield _sse("panel_model_result", panel_result)
            yield _sse("judge_result", result.judge)
            yield _sse("verdict", result.verdict)
            yield _sse(
                "done",
                DoneEvent(cost_usd=result.cost_usd, degraded_reasons=result.degraded_reasons),
            )
        except asyncio.TimeoutError:
            yield _sse("done", DoneEvent(degraded_reasons=["Council timed out before completion."]))
        except Exception as exc:
            log.exception("Council stream failed")
            yield _sse("error", {"message": str(exc) or "Fusion call failed"})

    return StreamingResponse(event_generator(), media_type="text/event-stream")


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
        return await _run_openrouter_fusion(ticker, models)
    prompt = _council_prompt(ticker)
    raw_result = await council.deliberate(prompt=prompt, max_tokens=1400)
    return _normalize_council_result(ticker, raw_result, models)


async def _run_openrouter_fusion(ticker: str, models: list[str]) -> CouncilResult:
    """Run OpenRouter Fusion and parse its structured AlphaDesk payload."""
    return await asyncio.to_thread(_run_openrouter_fusion_sync, ticker, models)


def _run_openrouter_fusion_sync(ticker: str, models: list[str]) -> CouncilResult:
    from openai import OpenAI

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.environ["OPENROUTER_API_KEY"],
    )
    extra_body: dict[str, Any] = {"tool_choice": "required"}
    if models:
        extra_body["tools"] = [
            {
                "type": "openrouter:fusion",
                "parameters": {
                    "analysis_models": models[:8],
                    "model": os.getenv("OPENROUTER_FUSION_JUDGE", "anthropic/claude-opus-4.8"),
                },
            }
        ]

    response = client.chat.completions.create(
        model=os.getenv("OPENROUTER_FUSION_MODEL", "openrouter/fusion"),
        messages=[
            {
                "role": "system",
                "content": (
                    "You are AlphaDesk's investment research chair. "
                    "Use Fusion deliberation, surface disagreement, and return only valid JSON."
                ),
            },
            {"role": "user", "content": _fusion_json_prompt(ticker)},
        ],
        extra_body=extra_body,
        extra_headers={
            "HTTP-Referer": os.getenv("OPENROUTER_SITE_URL", "http://localhost:5173"),
            "X-Title": "AlphaDesk Cockpit",
        },
        timeout=float(os.getenv("COUNCIL_MODEL_TIMEOUT_S", "60")),
    )
    content = response.choices[0].message.content
    if not content:
        raise RuntimeError("Fusion call returned an empty response.")
    parsed = _extract_json_object(content)
    result = CouncilResult.model_validate(parsed)

    usage = getattr(response, "usage", None)
    cost = _openrouter_cost(response)
    if cost is None and usage is not None:
        cost = 0.0
    if cost is not None:
        result = result.model_copy(update={"cost_usd": cost})
    return result


def _normalize_council_result(ticker: str, raw_result: Any, models: list[str]) -> CouncilResult:
    if isinstance(raw_result, CouncilResult):
        return raw_result
    raw_payload = _to_plain_data(raw_result)
    if isinstance(raw_payload, dict) and {"panel", "judge", "verdict"}.issubset(raw_payload):
        return CouncilResult.model_validate(raw_payload)

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
    return value


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
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise RuntimeError("Fusion response did not contain a JSON object.") from None
        parsed = json.loads(cleaned[start : end + 1])
    if not isinstance(parsed, dict):
        raise RuntimeError("Fusion response JSON must be an object.")
    return parsed


def _openrouter_cost(response: Any) -> Optional[float]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
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
    return f"""
Run an AlphaDesk investment council for {ticker}.

Return ONLY a JSON object matching this schema:
{{
  "panel": [
    {{
      "model_id": "provider/model-id",
      "label": "Human label",
      "rating": "Buy|Overweight|Hold|Underweight|Sell",
      "confidence": 0.0,
      "thesis": "One-line thesis",
      "dissent": false
    }}
  ],
  "judge": {{
    "consensus": ["point"],
    "contradictions": ["point"],
    "blind_spots": ["point"],
    "crowded_narrative_flag": {{"topic": "optional", "note": "optional"}}
  }},
  "verdict": {{
    "ticker": "{ticker}",
    "rating": "Buy|Overweight|Hold|Underweight|Sell",
    "conviction": 0.0,
    "conviction_label": "Short label",
    "scenarios": [
      {{"name": "Bull", "probability": 0.0, "ret_pct": 0.0}},
      {{"name": "Base", "probability": 0.0, "ret_pct": 0.0}},
      {{"name": "Bear", "probability": 0.0, "ret_pct": 0.0}}
    ],
    "catalysts": ["catalyst"],
    "risks": ["risk"]
  }},
  "cost_usd": 0.0,
  "degraded_reasons": []
}}

Rules:
- Surface disagreement explicitly; set dissent=true for panel ratings that diverge from the modal rating.
- Do not present consensus as truth. If the thesis is crowded, populate crowded_narrative_flag.
- Use only the five allowed rating strings.
""".strip()
