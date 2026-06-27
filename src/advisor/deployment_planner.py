"""Capital-deployment plan generator.

Turns AlphaDesk's scattered analytical agents into a single decision-grade
deployment document (the "deploy $X today" report):

    1. Load current holdings + weights (config/portfolio.yaml)
    2. Enrich each with live fundamentals (sector, fwd P/E, 52-wk range)
    3. Deterministic diagnosis (HHI, top-1/top-3, sector gaps via exposure_analyzer)
    4. Candidate ideas from the deterministic score engine
    5. Best-effort macro snapshot
    6. Assemble a grounded EVIDENCE PACK (real numbers, stamped as_of)
    7. ONE synthesis call to a heavy allowlisted model (Kimi K2.6 / GLM 5.2)
       that renders the 10-section Markdown report from the pack.

The single-synthesis design mirrors how a strong analyst produces the report:
gather grounded data, then write. It keeps cost to ~1 LLM call rather than
dozens of per-section agent calls.
"""
from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Optional

import requests

from src.advisor.exposure_analyzer import analyze_exposure_gaps
from src.shared.config_loader import load_config
from src.shared.prompt_loader import load_prompt
from src.utils.logger import get_logger

log = get_logger(__name__)

# Long-form synthesis model (allowlisted). GLM 5.2 is a strong long-form writer.
# NOTE: the allowlisted OpenRouter models (GLM 5.2, Kimi K2.6) route through a
# reasoning stage that consumes the token budget and leaves `content` null — so
# we explicitly disable reasoning for this straight long-form generation.
SYNTHESIS_MODEL = os.getenv("OPENROUTER_DEPLOYMENT_MODEL", "z-ai/glm-5.2")
SYNTHESIS_MAX_TOKENS = int(os.getenv("OPENROUTER_DEPLOYMENT_MAX_TOKENS", "9000"))


@dataclass
class DeploymentInputs:
    capital: float = 100_000.0
    return_target: str = "30-40% total return over 12 months"
    account_type: str = "taxable"
    constraints: str = "Reducing concentration is the #1 goal; concentrated single-stock positions are acceptable."
    themes: list[str] = field(
        default_factory=lambda: [
            "AI infrastructure / datacenter",
            "precious-metals miners",
            "defense / aerospace",
            "copper / critical minerals",
            "nuclear / uranium",
        ]
    )


# ── Holdings + weights (deterministic, from config) ──────────────────────────

def _load_current_holdings() -> list[dict[str, Any]]:
    """Holdings with weight_pct computed from shares × cost_basis (cost-basis
    proxy, same method as /api/portfolio). Returns [] on any failure."""
    try:
        cfg = load_config("portfolio")
    except Exception:
        log.exception("deployment_planner: failed to load portfolio config")
        return []

    raw = cfg.get("holdings", []) or []
    values: list[tuple[str, float, dict]] = []
    for h in raw:
        ticker = str(h.get("ticker", "")).upper().strip()
        if not ticker:
            continue
        weight = h.get("weight_pct")
        if weight is None:
            shares = float(h.get("shares", 0) or 0)
            basis = float(h.get("cost_basis", 0) or 0)
            weight = shares * basis
        values.append((ticker, float(weight or 0), h))

    total = sum(v for _, v, _ in values)
    if total <= 0:
        return []

    holdings = []
    for ticker, value, raw_h in values:
        holdings.append(
            {
                "ticker": ticker,
                "position_pct": round(value / total * 100.0, 1),
                "shares": raw_h.get("shares"),
                "cost_basis": raw_h.get("cost_basis"),
            }
        )
    return holdings


def _enrich_with_fundamentals(holdings: list[dict[str, Any]]) -> None:
    """Best-effort: attach sector, fwd P/E, 52-wk range, etc. Mutates in place.
    Never raises — a holding without fundamentals just keeps sector 'Unknown'."""
    try:
        from src.portfolio_analyst.fundamental_analyzer import fetch_fundamentals
    except Exception:
        log.warning("deployment_planner: fundamentals fetcher unavailable")
        return

    for h in holdings:
        try:
            f = fetch_fundamentals(h["ticker"])
        except Exception as exc:
            log.warning("deployment_planner: fundamentals failed for %s: %s", h["ticker"], exc)
            continue
        if not isinstance(f, dict):
            continue
        h["sector"] = f.get("sector") or "Unknown"
        h["company"] = f.get("short_name") or h["ticker"]
        h["price"] = f.get("current_price")
        h["pe_forward"] = f.get("pe_forward")
        h["pe_trailing"] = f.get("pe_trailing")
        h["revenue_growth"] = f.get("revenue_growth")
        h["market_cap"] = f.get("market_cap")
        h["pct_from_52w_high"] = f.get("pct_from_52w_high")
        h["fifty_two_week_high"] = f.get("fifty_two_week_high")
        h["fifty_two_week_low"] = f.get("fifty_two_week_low")
        h["beta"] = f.get("beta")


def _diagnosis(holdings: list[dict[str, Any]]) -> dict[str, Any]:
    """HHI, top-1, top-3, sector breakdown, zero-exposure gaps."""
    weights = sorted((h.get("position_pct", 0) for h in holdings), reverse=True)
    hhi = round(sum(w * w for w in weights), 1)
    exposure = analyze_exposure_gaps(holdings)
    return {
        "hhi": hhi,
        "top1_pct": round(weights[0], 1) if weights else 0.0,
        "top3_pct": round(sum(weights[:3]), 1),
        "n_holdings": len(holdings),
        "sector_breakdown": exposure.get("sector_breakdown", {}),
        "zero_exposure_sectors": exposure.get("zero_exposure_sectors", []),
        "gaps": exposure.get("gaps", []),
        "gap_summary": exposure.get("gap_summary", ""),
        "safety_score": exposure.get("safety_score"),
    }


# ── Candidate ideas (deterministic score engine) ─────────────────────────────

async def _candidate_ideas(top_n: int = 12) -> dict[str, Any]:
    """Top scored candidates from the score engine. Degrades to empty."""
    try:
        from src.score_engine.engine import run_scoring
        from src.score_engine.signals import RunRequest

        result = await run_scoring(RunRequest(depth="standard", top_n=top_n))
        ideas = []
        for s in result.top:
            ideas.append(
                {
                    "ticker": s.ticker,
                    "score": s.score,
                    "platforms_reporting": s.platforms_reporting,
                    "evidence": [b.get("evidence") for b in (s.breakdown or [])][:4],
                }
            )
        return {
            "snapshot_id": result.snapshot_id,
            "as_of": str(date.today()),
            "diagnostics": result.diagnostics,
            "ideas": ideas,
        }
    except Exception:
        log.exception("deployment_planner: score engine unavailable")
        return {"ideas": [], "as_of": str(date.today()), "note": "score engine unavailable"}


def _macro_snapshot() -> dict[str, Any]:
    """Best-effort live macro snapshot. Degrades to a note."""
    try:
        from src.advisor.macro_analyst import fetch_macro_data

        data = fetch_macro_data()
        if isinstance(data, dict) and data:
            return {"as_of": str(date.today()), "data": data}
    except Exception:
        log.info("deployment_planner: live macro fetch unavailable, leaving to analyst judgment")
    return {"as_of": str(date.today()), "note": "no live macro in pack — analyst judgment / verify live"}


# ── Evidence pack + synthesis ────────────────────────────────────────────────

def build_evidence_pack(inputs: DeploymentInputs, candidates: dict[str, Any]) -> dict[str, Any]:
    holdings = _load_current_holdings()
    _enrich_with_fundamentals(holdings)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mandate": {
            "capital": inputs.capital,
            "return_target": inputs.return_target,
            "account_type": inputs.account_type,
            "constraints": inputs.constraints,
            "tracked_themes": inputs.themes,
        },
        "current_holdings": holdings,
        "diagnosis": _diagnosis(holdings),
        "candidate_ideas": candidates,
        "macro": _macro_snapshot(),
    }


def _synthesize(inputs: DeploymentInputs, evidence_pack: dict[str, Any]) -> str:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is required to synthesize a deployment plan")

    system_prompt = load_prompt(
        "deployment_planner",
        capital=f"${inputs.capital:,.0f}",
        account_type=inputs.account_type,
        return_target=inputs.return_target,
        constraints=inputs.constraints,
        themes=", ".join(inputs.themes),
        evidence_pack=json.dumps(evidence_pack, indent=2, default=str),
    )

    resp = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": os.getenv("OPENROUTER_SITE_URL", "http://localhost:5173"),
            "X-Title": "AlphaDesk Deployment Planner",
            "Content-Type": "application/json",
        },
        json={
            "model": SYNTHESIS_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": (
                        f"Generate the full deployment plan for ${inputs.capital:,.0f} "
                        f"({inputs.return_target}) using the evidence pack. "
                        "Follow every required section in order."
                    ),
                },
            ],
            "max_tokens": SYNTHESIS_MAX_TOKENS,
            "temperature": 0.4,
            # The allowlisted models route through a reasoning stage that would
            # otherwise consume the whole budget and leave content null.
            "reasoning": {"enabled": False},
        },
        timeout=float(os.getenv("OPENROUTER_DEPLOYMENT_TIMEOUT_S", "300")),
    )
    resp.raise_for_status()
    data = _parse_openrouter_body(resp.text)
    try:
        choice = data["choices"][0]
        message = choice["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Unexpected OpenRouter response: {exc}; body={json.dumps(data)[:500]}")

    content = message.get("content")
    if not content:
        # Defensive: if reasoning slipped through and ate the budget, surface it
        # clearly rather than writing a null report.
        finish = choice.get("finish_reason")
        reasoning = message.get("reasoning")
        if reasoning and finish == "length":
            raise RuntimeError(
                "Synthesis produced no content (reasoning consumed the token budget); "
                "raise OPENROUTER_DEPLOYMENT_MAX_TOKENS or check the reasoning toggle."
            )
        raise RuntimeError(f"Synthesis returned empty content (finish_reason={finish}).")
    return content


def _parse_openrouter_body(raw_text: str) -> dict[str, Any]:
    """Parse an OpenRouter chat completion body.

    For long non-streaming requests OpenRouter interleaves SSE-style keep-alive
    comment lines (": OPENROUTER PROCESSING") with the final JSON, which breaks
    a naive json.loads. Fall back to extracting the outermost JSON object.
    """
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        start = raw_text.find("{")
        end = raw_text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(raw_text[start : end + 1])
        raise RuntimeError("OpenRouter response did not contain JSON.") from None


async def generate_deployment_plan(inputs: Optional[DeploymentInputs] = None) -> dict[str, Any]:
    """Full pipeline: gather grounded evidence → synthesize the Markdown report."""
    inputs = inputs or DeploymentInputs()
    candidates = await _candidate_ideas()
    evidence_pack = build_evidence_pack(inputs, candidates)
    markdown = await asyncio.to_thread(_synthesize, inputs, evidence_pack)
    return {
        "markdown": markdown,
        "evidence_pack": evidence_pack,
        "model": SYNTHESIS_MODEL,
        "generated_at": evidence_pack["generated_at"],
    }
