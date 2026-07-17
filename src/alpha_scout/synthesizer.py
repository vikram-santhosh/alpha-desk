"""LLM synthesis for Alpha Scout.

Takes the top-N screened candidates and uses an LLM to:
- Rank them with investment context
- Generate 2-3 sentence thesis per ticker
- Categorize as "portfolio" (buy) vs "watchlist" (monitor)
- Assign conviction: high / medium / low
"""
from __future__ import annotations

import ast
import json
import os
import urllib.error
import urllib.request
from datetime import date
from typing import Any

from src.shared import gemini_compat as anthropic

from src.shared.cost_tracker import check_budget, record_usage
from src.shared.schemas import (
    Recommendation,
    Thesis,
    WhyNow,
    BearCase,
    InvalidationCondition,
    AnalystScores,
    EvidenceItem,
    validate_recommendation,
)
from src.utils.logger import get_logger

log = get_logger(__name__)

AGENT_NAME = "alpha_scout"
MODEL = os.getenv("ALPHA_SCOUT_SYNTHESIS_MODEL", "claude-sonnet-4-6")
OPENROUTER_DEFAULT_MODEL = "z-ai/glm-5.2"


def _build_candidate_summary(candidate: dict[str, Any]) -> str:
    """Build a compact text summary of a candidate for the synthesis prompt."""
    ticker = candidate["ticker"]
    scores = candidate.get("scores", {})
    fund = candidate.get("fundamentals_summary", {})
    tech_signals = candidate.get("technical_summary", [])
    source = candidate.get("source", "unknown")

    parts = [
        f"**{ticker}** (source: {source})",
        f"  Composite: {scores.get('composite', 0):.1f} | "
        f"Tech: {scores.get('technical', 0)} | "
        f"Fund: {scores.get('fundamental', 0)} | "
        f"Sent: {scores.get('sentiment', 0)} | "
        f"Div: {scores.get('diversification', 0)}",
    ]

    # Fundamentals
    pe = fund.get("pe_trailing")
    rev_growth = fund.get("revenue_growth")
    market_cap = fund.get("market_cap")
    sector = fund.get("sector", "Unknown")
    pct_high = fund.get("pct_from_52w_high")

    fund_parts = [f"Sector: {sector}"]
    if pe is not None:
        fund_parts.append(f"P/E: {pe:.1f}")
    if rev_growth is not None:
        fund_parts.append(f"Rev Growth: {rev_growth * 100:.1f}%")
    if market_cap is not None:
        if market_cap >= 1e12:
            fund_parts.append(f"MCap: ${market_cap / 1e12:.1f}T")
        elif market_cap >= 1e9:
            fund_parts.append(f"MCap: ${market_cap / 1e9:.1f}B")
        else:
            fund_parts.append(f"MCap: ${market_cap / 1e6:.0f}M")
    if pct_high is not None:
        fund_parts.append(f"{pct_high:+.1f}% from 52wk high")

    parts.append(f"  {' | '.join(fund_parts)}")

    # Technical signals
    if tech_signals:
        parts.append(f"  Signals: {', '.join(tech_signals[:3])}")

    # Sentiment source data
    signal_data = candidate.get("signal_data", {})
    sentiment = signal_data.get("sentiment") or signal_data.get("avg_sentiment")
    if sentiment is not None:
        parts.append(f"  Sentiment: {sentiment}")

    return "\n".join(parts)


def synthesize_recommendations(
    scored_candidates: list[dict[str, Any]],
    top_n: int = 20,
    max_portfolio: int = 5,
    max_watchlist: int = 10,
) -> dict[str, Any]:
    """Use an LLM to synthesize ranked recommendations.

    Args:
        scored_candidates: Candidates sorted by composite score.
        top_n: Number of top candidates to send to the model.
        max_portfolio: Max portfolio (buy) recommendations.
        max_watchlist: Max watchlist (monitor) recommendations.

    Returns:
        Dict with:
            portfolio_recs: List of portfolio recommendation dicts.
            watchlist_recs: List of watchlist recommendation dicts.
            raw_synthesis: Raw text from the model.
    """
    if not scored_candidates:
        return {
            "portfolio_recs": [],
            "watchlist_recs": [],
            "raw_synthesis": "",
            "synthesis_source": "empty",
        }

    # Check budget
    within_budget, spent, cap = check_budget()
    if not within_budget:
        log.warning("Budget exceeded ($%.2f/$%.2f) — skipping synthesis", spent, cap)
        return _fallback_recommendations(
            scored_candidates,
            max_portfolio,
            max_watchlist,
            synthesis_source="budget_fallback",
        )

    top_candidates = scored_candidates[:top_n]
    candidate_text = "\n\n".join(
        _build_candidate_summary(c) for c in top_candidates
    )

    prompt = f"""You are an expert equity research analyst. Analyze these {len(top_candidates)} stock candidates and produce investment recommendations.

## CANDIDATES (ranked by quantitative composite score)

{candidate_text}

## TASK

Evaluate each candidate and categorize into TWO groups:

1. **PORTFOLIO RECOMMENDATIONS** (up to {max_portfolio}) — Stocks to BUY. These should have strong fundamentals, favorable technicals, and a clear catalyst or value thesis. Highest conviction picks.

2. **WATCHLIST RECOMMENDATIONS** (up to {max_watchlist}) — Stocks to MONITOR. Interesting but need more confirmation — perhaps technicals aren't quite right yet, or you want to see the next earnings report.

For each recommendation, provide:
- **ticker**: The stock symbol
- **category**: "portfolio" or "watchlist"
- **conviction**: "high", "medium", or "low"
- **thesis**: A 2-3 sentence investment thesis explaining WHY. Reference specific data points (P/E, growth, signals, sector dynamics).

Respond ONLY with valid JSON in this exact format:
{{
  "portfolio": [
    {{"ticker": "XYZ", "conviction": "high", "thesis": "..."}},
  ],
  "watchlist": [
    {{"ticker": "ABC", "conviction": "medium", "thesis": "..."}},
  ]
}}"""

    try:
        completion = _call_synthesis_model(
            prompt=prompt,
            max_tokens=2000,
            temperature=0.2,
            max_portfolio=max_portfolio,
            max_watchlist=max_watchlist,
        )
        raw_text = str(completion["text"])
        model = str(completion["model"])
        input_tokens = int(completion.get("input_tokens") or 0)
        output_tokens = int(completion.get("output_tokens") or 0)
        cost_usd = float(completion.get("cost_usd") or 0.0)
        log.info(
            "Synthesis complete via %s/%s: %d tokens in, %d tokens out",
            completion.get("provider", "llm"),
            model,
            input_tokens,
            output_tokens,
        )

        parsed = _parse_synthesis(raw_text, scored_candidates)
        if _has_any_recommendations(parsed):
            parsed["synthesis_source"] = "llm_json"
            parsed["synthesis_model"] = model
            parsed["synthesis_provider"] = completion.get("provider")
            parsed["synthesis_cost_usd"] = cost_usd
            return parsed

        repaired = _repair_synthesis(
            raw_text=raw_text,
            scored_candidates=scored_candidates,
            max_portfolio=max_portfolio,
            max_watchlist=max_watchlist,
        )
        if _has_any_recommendations(repaired):
            repaired["synthesis_source"] = "llm_repaired_json"
            repaired["synthesis_model"] = repaired.get("synthesis_model") or model
            repaired["synthesis_provider"] = repaired.get("synthesis_provider") or completion.get("provider")
            repaired["synthesis_cost_usd"] = cost_usd + float(repaired.get("synthesis_cost_usd") or 0.0)
            repaired["raw_synthesis"] = f"{raw_text}\n\n--- JSON repair ---\n{repaired.get('raw_synthesis', '')}"
            return repaired

        log.warning("LLM synthesis produced no usable recommendations — falling back to score ranking")
        fallback = _fallback_recommendations(
            scored_candidates,
            max_portfolio,
            max_watchlist,
            synthesis_source="score_fallback",
        )
        fallback["raw_synthesis"] = raw_text
        fallback["synthesis_model"] = model
        fallback["synthesis_provider"] = completion.get("provider")
        fallback["synthesis_cost_usd"] = cost_usd
        return fallback

    except Exception:
        log.exception("LLM synthesis failed — falling back to score-based ranking")
        return _fallback_recommendations(
            scored_candidates,
            max_portfolio,
            max_watchlist,
            synthesis_source="error_fallback",
        )


def _call_synthesis_model(
    *,
    prompt: str,
    max_tokens: int,
    temperature: float,
    max_portfolio: int,
    max_watchlist: int,
) -> dict[str, Any]:
    if _use_openrouter():
        return _call_openrouter_synthesis(
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            max_portfolio=max_portfolio,
            max_watchlist=max_watchlist,
        )
    return _call_compat_synthesis(
        prompt=prompt,
        max_tokens=max_tokens,
        temperature=temperature,
    )


def _use_openrouter() -> bool:
    provider = os.getenv("ALPHA_SCOUT_SYNTHESIS_PROVIDER", "").strip().lower()
    has_key = bool(os.getenv("OPENROUTER_API_KEY"))
    if provider in {"openrouter", "or"}:
        if not has_key:
            raise RuntimeError("ALPHA_SCOUT_SYNTHESIS_PROVIDER=openrouter requires OPENROUTER_API_KEY.")
        return True
    if provider in {"anthropic", "gemini", "compat", "gemini_compat"}:
        return False
    return has_key


def _call_compat_synthesis(
    *,
    prompt: str,
    max_tokens: int,
    temperature: float,
) -> dict[str, Any]:
    client = anthropic.Anthropic()
    response = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
        response_mime_type="application/json",
        temperature=temperature,
    )
    usage = response.usage
    cost_usd = record_usage(
        AGENT_NAME,
        usage.input_tokens,
        usage.output_tokens,
        model=response.model,
    )
    return {
        "text": response.content[0].text,
        "model": response.model,
        "provider": getattr(client, "backend", "compat"),
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cost_usd": cost_usd,
    }


def _call_openrouter_synthesis(
    *,
    prompt: str,
    max_tokens: int,
    temperature: float,
    max_portfolio: int,
    max_watchlist: int,
) -> dict[str, Any]:
    model = os.getenv(
        "ALPHA_SCOUT_OPENROUTER_MODEL",
        os.getenv("OPENROUTER_IDEA_MODEL", OPENROUTER_DEFAULT_MODEL),
    )
    if _is_openrouter_opus_model(model):
        log.warning("Refusing Opus model for Alpha Scout synthesis; using %s instead", OPENROUTER_DEFAULT_MODEL)
        model = OPENROUTER_DEFAULT_MODEL
    request_body = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are AlphaDesk's Alpha Scout synthesis analyst. "
                    "Return only valid JSON. Treat outputs as research support, not personalized financial advice."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "alpha_scout_synthesis",
                "strict": True,
                "schema": _synthesis_json_schema(max_portfolio, max_watchlist),
            },
        },
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    headers = _openrouter_headers()
    timeout_s = float(
        os.getenv(
            "ALPHA_SCOUT_SYNTHESIS_TIMEOUT_S",
            os.getenv("COUNCIL_MODEL_TIMEOUT_S", "120"),
        )
    )
    try:
        response_data = _openrouter_completion_raw(request_body, headers, timeout_s)
    except RuntimeError as exc:
        if "response_format" not in str(exc) and "json_schema" not in str(exc):
            raise
        relaxed_body = dict(request_body)
        relaxed_body.pop("response_format", None)
        response_data = _openrouter_completion_raw(relaxed_body, headers, timeout_s)

    text = _openrouter_choice_payload(response_data)
    if not text:
        raise RuntimeError("OpenRouter synthesis returned an empty response.")

    input_tokens, output_tokens = _openrouter_usage_tokens(response_data)
    response_model = str(response_data.get("model") or model)
    tracked_cost = 0.0
    if input_tokens or output_tokens:
        tracked_cost = record_usage(
            AGENT_NAME,
            input_tokens,
            output_tokens,
            model=response_model,
        )
    provider_cost = _openrouter_cost(response_data)
    if provider_cost is not None:
        tracked_cost = provider_cost
    return {
        "text": text,
        "model": response_model,
        "provider": "openrouter",
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": tracked_cost,
    }


def _synthesis_json_schema(max_portfolio: int, max_watchlist: int) -> dict[str, Any]:
    rec_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["ticker", "conviction", "thesis"],
        "properties": {
            "ticker": {"type": "string"},
            "conviction": {"type": "string", "enum": ["high", "medium", "low"]},
            "thesis": {"type": "string"},
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["portfolio", "watchlist"],
        "properties": {
            "portfolio": {
                "type": "array",
                "items": rec_schema,
            },
            "watchlist": {
                "type": "array",
                "items": rec_schema,
            },
        },
    }


def _is_openrouter_opus_model(model_id: str) -> bool:
    return "opus" in model_id.lower()


def _openrouter_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
        "HTTP-Referer": os.getenv("OPENROUTER_SITE_URL", "http://localhost:5173"),
        "X-Title": "AlphaDesk Cockpit",
    }


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
        raise RuntimeError(f"OpenRouter synthesis failed with HTTP {exc.code}: {body}") from None
    except Exception as exc:
        raise RuntimeError(f"OpenRouter synthesis failed: {exc}") from exc

    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        start = raw_text.find("{")
        end = raw_text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(raw_text[start : end + 1])
        raise RuntimeError("OpenRouter synthesis response did not contain JSON.") from None


def _openrouter_choice_payload(response_data: dict[str, Any]) -> str | None:
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
            parts = [
                str(item.get("text") if isinstance(item, dict) else item)
                for item in content
                if item
            ]
            text = "\n".join(part for part in parts if part.strip())
            if text:
                return text
        for tool_call in message.get("tool_calls") or []:
            if not isinstance(tool_call, dict):
                continue
            function = tool_call.get("function")
            if isinstance(function, dict) and function.get("arguments"):
                return str(function["arguments"])
            if tool_call.get("arguments"):
                return str(tool_call["arguments"])
        for key in ("parsed", "output_text", "output", "text"):
            value = message.get(key)
            if value not in (None, "", [], {}):
                return str(value)
    for key in ("parsed", "output_text", "output", "text"):
        value = choice.get(key)
        if value not in (None, "", [], {}):
            return str(value)
    return None


def _openrouter_usage_tokens(response_data: dict[str, Any]) -> tuple[int, int]:
    usage = response_data.get("usage")
    if not isinstance(usage, dict):
        return 0, 0
    input_tokens = _first_int(
        usage.get("prompt_tokens"),
        usage.get("input_tokens"),
        usage.get("prompt_token_count"),
    )
    output_tokens = _first_int(
        usage.get("completion_tokens"),
        usage.get("output_tokens"),
        usage.get("candidates_token_count"),
    )
    return input_tokens, output_tokens


def _openrouter_cost(response_data: dict[str, Any]) -> float | None:
    usage = response_data.get("usage")
    if not isinstance(usage, dict):
        return None
    for key in ("cost", "cost_usd", "total_cost"):
        value = usage.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    return None


def _first_int(*values: Any) -> int:
    for value in values:
        try:
            if value is not None:
                return int(value)
        except (TypeError, ValueError):
            continue
    return 0


def _parse_synthesis(raw_text: str, scored_candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """Parse the JSON output from the synthesis model."""
    data = _load_synthesis_json(raw_text)
    if data is None:
        log.error("Failed to parse synthesis JSON")
        return {
            "portfolio_recs": [],
            "watchlist_recs": [],
            "raw_synthesis": raw_text,
            "synthesis_source": "parse_failed",
        }

    # Build lookup for scores
    score_lookup = {
        str(c["ticker"]).upper(): c.get("scores", {}) for c in scored_candidates
    }
    fund_lookup = {
        str(c["ticker"]).upper(): c.get("fundamentals_summary", {})
        for c in scored_candidates
    }
    normalized = {
        str(key).lower().replace(" ", "_"): value
        for key, value in data.items()
    }
    portfolio = _as_recommendation_list(
        normalized.get("portfolio")
        or normalized.get("portfolio_recommendations")
        or normalized.get("portfolio_recs")
    )
    watchlist = _as_recommendation_list(
        normalized.get("watchlist")
        or normalized.get("watchlist_recommendations")
        or normalized.get("watchlist_recs")
    )

    portfolio_recs = []
    for rec in portfolio:
        ticker = str(rec.get("ticker", "")).strip().upper()
        if ticker not in score_lookup:
            log.warning("Synthesis returned unknown ticker %s; skipping", ticker)
            continue
        portfolio_recs.append({
            "ticker": ticker,
            "category": "portfolio",
            "conviction": _normalize_conviction(rec.get("conviction")),
            "thesis": str(rec.get("thesis") or ""),
            "scores": score_lookup.get(ticker, {}),
            "fundamentals_summary": fund_lookup.get(ticker, {}),
            "source": "alpha_scout/llm_synthesis",
        })

    watchlist_recs = []
    for rec in watchlist:
        ticker = str(rec.get("ticker", "")).strip().upper()
        if ticker not in score_lookup:
            log.warning("Synthesis returned unknown ticker %s; skipping", ticker)
            continue
        watchlist_recs.append({
            "ticker": ticker,
            "category": "watchlist",
            "conviction": _normalize_conviction(rec.get("conviction")),
            "thesis": str(rec.get("thesis") or ""),
            "scores": score_lookup.get(ticker, {}),
            "fundamentals_summary": fund_lookup.get(ticker, {}),
            "source": "alpha_scout/llm_synthesis",
        })

    return {
        "portfolio_recs": portfolio_recs,
        "watchlist_recs": watchlist_recs,
        "raw_synthesis": raw_text,
        "synthesis_source": "llm_json",
    }


def _load_synthesis_json(raw_text: str) -> dict[str, Any] | None:
    """Load a synthesis JSON object from plain JSON, fences, or surrounding prose."""
    text = raw_text.strip()
    candidates = [text]

    fenced = _extract_fenced_content(text)
    if fenced:
        candidates.append(fenced)

    embedded = _extract_json_object_text(text)
    if embedded:
        candidates.append(embedded)

    seen: set[str] = set()
    for candidate in candidates:
        candidate = candidate.strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            try:
                parsed = ast.literal_eval(candidate)
            except (SyntaxError, ValueError):
                continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _extract_fenced_content(text: str) -> str | None:
    if "```" not in text:
        return None
    parts = text.split("```")
    if len(parts) < 3:
        return None
    fenced = parts[1].strip()
    if fenced.lower().startswith("json"):
        fenced = fenced[4:].strip()
    return fenced


def _extract_json_object_text(text: str) -> str | None:
    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def _as_recommendation_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _normalize_conviction(value: Any) -> str:
    conviction = str(value or "medium").strip().lower()
    if conviction in {"high", "medium", "low"}:
        return conviction
    return "medium"


def _has_any_recommendations(synthesis: dict[str, Any] | None) -> bool:
    if not isinstance(synthesis, dict):
        return False
    return bool(synthesis.get("portfolio_recs") or synthesis.get("watchlist_recs"))


def _repair_synthesis(
    *,
    raw_text: str,
    scored_candidates: list[dict[str, Any]],
    max_portfolio: int,
    max_watchlist: int,
) -> dict[str, Any]:
    allowed_tickers = [
        str(candidate.get("ticker", "")).upper()
        for candidate in scored_candidates
        if candidate.get("ticker")
    ]
    repair_prompt = f"""Convert this Alpha Scout model output into valid JSON.

Rules:
- Return only JSON.
- Keep only tickers from this allowed list: {", ".join(allowed_tickers[:50])}.
- Preserve the model's recommendation intent where possible.
- If the model text is unusable, choose the strongest allowed tickers based on the evidence in the text.
- Use this exact shape:
{{
  "portfolio": [
    {{"ticker": "XYZ", "conviction": "high", "thesis": "..."}}
  ],
  "watchlist": [
    {{"ticker": "ABC", "conviction": "medium", "thesis": "..."}}
  ]
}}
- Return up to {max_portfolio} portfolio names and up to {max_watchlist} watchlist names.

Raw model output:
{raw_text}"""

    try:
        completion = _call_synthesis_model(
            prompt=repair_prompt,
            max_tokens=1400,
            temperature=0,
            max_portfolio=max_portfolio,
            max_watchlist=max_watchlist,
        )
        repaired_text = str(completion["text"])
        parsed = _parse_synthesis(repaired_text, scored_candidates)
        parsed["raw_synthesis"] = repaired_text
        parsed["synthesis_model"] = completion["model"]
        parsed["synthesis_provider"] = completion.get("provider")
        parsed["synthesis_cost_usd"] = completion.get("cost_usd", 0.0)
        return parsed
    except Exception:
        log.exception("Synthesis JSON repair failed")
        return {
            "portfolio_recs": [],
            "watchlist_recs": [],
            "raw_synthesis": raw_text,
            "synthesis_source": "repair_failed",
        }


def _fallback_recommendations(
    scored_candidates: list[dict[str, Any]],
    max_portfolio: int,
    max_watchlist: int,
    synthesis_source: str = "score_fallback",
) -> dict[str, Any]:
    """Generate recommendations based purely on composite scores (no LLM call)."""
    portfolio_recs = []
    watchlist_recs = []

    for index, candidate in enumerate(scored_candidates):
        composite = candidate.get("scores", {}).get("composite", 0)
        ticker = candidate["ticker"]

        rec = {
            "ticker": ticker,
            "conviction": "high" if composite >= 70 else "medium" if composite >= 50 else "low",
            "thesis": f"Composite score {composite:.1f}. Source: {candidate.get('source', 'unknown')}.",
            "scores": candidate.get("scores", {}),
            "fundamentals_summary": candidate.get("fundamentals_summary", {}),
            "source": candidate.get("source", "unknown"),
            "corroboration_count": candidate.get("corroboration_count", 1),
            "corroborating_sources": candidate.get("corroborating_sources", []),
            "synthesis_source": synthesis_source,
        }

        top_ranked = index < max_portfolio and composite >= 45
        if (composite >= 60 or top_ranked) and len(portfolio_recs) < max_portfolio:
            rec["category"] = "portfolio"
            portfolio_recs.append(rec)
        elif len(watchlist_recs) < max_watchlist:
            rec["category"] = "watchlist"
            watchlist_recs.append(rec)

        if len(portfolio_recs) >= max_portfolio and len(watchlist_recs) >= max_watchlist:
            break

    return {
        "portfolio_recs": portfolio_recs,
        "watchlist_recs": watchlist_recs,
        "raw_synthesis": "(fallback — synthesis skipped due to budget or error)",
        "synthesis_source": synthesis_source,
    }


def recs_to_structured(
    portfolio_recs: list[dict], watchlist_recs: list[dict],
) -> list[Recommendation]:
    """Convert legacy recommendation dicts into structured Recommendation objects.

    Best-effort: populates what's available, validates, and logs any issues.
    Returns only valid Recommendation objects.
    """
    structured = []
    today = date.today().isoformat()

    for rec_dict in portfolio_recs + watchlist_recs:
        ticker = rec_dict.get("ticker", "")
        category = rec_dict.get("category", "watchlist")
        conviction = rec_dict.get("conviction", "medium")
        thesis_text = rec_dict.get("thesis", "")
        scores = rec_dict.get("scores", {})
        fund = rec_dict.get("fundamentals_summary", {})

        action = "BUY" if category == "portfolio" else "WATCH"

        try:
            rec = Recommendation(
                ticker=ticker,
                recommendation_date=today,
                action=action,
                category="conviction_add" if category == "portfolio" else "watchlist",
                conviction_level=conviction,
                why_now=WhyNow(
                    catalyst="Quantitative screening + LLM synthesis",
                    what_changed="Identified by Alpha Scout discovery pipeline",
                    timing_signal=f"Composite score: {scores.get('composite', 0):.1f}",
                ),
                thesis=Thesis(
                    core_argument=thesis_text,
                    supporting_evidence=[
                        EvidenceItem(
                            source="fundamental_data",
                            date=today,
                            claim=f"Revenue growth {fund.get('revenue_growth', 0):.0%}" if fund.get("revenue_growth") else "Fundamentals screened",
                            base_weight=2.0,
                            recency_days=7,
                        ),
                        EvidenceItem(
                            source="technical_signal",
                            date=today,
                            claim=f"Technical score {scores.get('technical', 0)}",
                            base_weight=1.5,
                            recency_days=1,
                        ),
                    ],
                    evidence_quality_score=scores.get("composite", 50.0),
                ),
                valuation=fund,
                bear_case=BearCase(
                    primary_risk="Quantitative screen — full bear case pending skeptic review",
                    base_rate="Most screened candidates underperform the index",
                    whats_priced_in="Market consensus reflected in current price",
                ),
                invalidation_conditions=[
                    InvalidationCondition(
                        condition=f"{ticker} drops 20% from current levels",
                        monitoring="Daily price check",
                        action_if_triggered="Review thesis and consider exit",
                    ),
                ],
                sizing=None,
                analyst_scores=AnalystScores(
                    growth_score=scores.get("fundamental", 50),
                    value_score=50,
                    risk_score=50,
                    catalyst_proximity_score=50,
                    novelty_score=50,
                    diversification_score=scores.get("diversification", 50),
                    composite_score=scores.get("composite", 50.0),
                    skeptic_confidence_modifier=1.0,
                ),
                source=rec_dict.get("source", "alpha_scout"),
            )

            errors = validate_recommendation(rec)
            if errors:
                log.warning("Validation issues for %s: %s", ticker, errors)

            structured.append(rec)

        except Exception:
            log.exception("Failed to create structured rec for %s", ticker)

    return structured
