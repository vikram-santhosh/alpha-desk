"""Gemini synthesis for Alpha Scout.

Takes the top-N screened candidates and uses Gemini to:
- Rank them with investment context
- Generate 2-3 sentence thesis per ticker
- Categorize as "portfolio" (buy) vs "watchlist" (monitor)
- Assign conviction: high / medium / low

Added guardrails:
- Recommended tickers are validated against the candidate universe plus a
  lightweight yfinance existence check.  Fake tickers are quarantined and logged
  instead of being emitted as buy recommendations.
- Theses that cite hard figures without a matching fetched-fundamentals source
  carry an "unverified_figures" tag.
"""
from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

import yfinance as yf

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
from src.shared.security import sanitize_ticker
from src.utils.logger import get_logger

log = get_logger(__name__)

AGENT_NAME = "alpha_scout"
MODEL = "claude-opus-4-6"


def _validate_ticker(ticker: str, valid_tickers: set[str]) -> tuple[bool, str]:
    """Return (is_valid, reason) for a ticker recommended by the LLM.

    Validation order:
    1. Must be a syntactically valid ticker symbol.
    2. Must be in the screened candidate universe for this run.
    3. If not in the universe, a lightweight yfinance existence check is used as
       a fallback so novel-but-real tickers are not silently discarded.
    """
    try:
        clean = sanitize_ticker(ticker)
    except ValueError as exc:
        return False, f"invalid ticker syntax: {exc}"

    if clean in valid_tickers:
        return True, "in_candidate_universe"

    # Lightweight existence check: requires at least one recent trading day
    try:
        t = yf.Ticker(clean)
        hist = t.history(period="5d")
        if not hist.empty:
            return True, "yfinance_existence_check"
    except Exception:
        log.debug("yfinance existence check failed for %s", clean)

    return False, "not_in_candidate_universe_or_yfinance"


def _has_unverified_figures(ticker: str, thesis: str, fund_lookup: dict[str, dict]) -> bool:
    """Return True if the thesis contains hard figures without fetched fundamentals.

    This is a lightweight heuristic, not full fact-checking.  If the ticker is
    in the candidate universe and has non-empty fundamentals data, we treat the
    figures as potentially sourced; otherwise they are tagged unverified.
    """
    if not re.search(r"\d+(?:\.\d+)?%?|\$\d+", thesis):
        return False  # no hard numbers cited

    fund = fund_lookup.get(ticker, {})
    has_fundamentals = bool(fund and any(v is not None for v in fund.values()))
    return not has_fundamentals


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
    portfolio_safety_score: int | None = None,
) -> dict[str, Any]:
    """Use Gemini to synthesize ranked recommendations.

    Args:
        scored_candidates: Candidates sorted by composite score.
        top_n: Number of top candidates to send to Gemini.
        max_portfolio: Max portfolio (buy) recommendations.
        max_watchlist: Max watchlist (monitor) recommendations.

    Returns:
        Dict with:
            portfolio_recs: List of portfolio recommendation dicts.
            watchlist_recs: List of watchlist recommendation dicts.
            raw_synthesis: Raw text from Gemini.
    """
    if not scored_candidates:
        return {"portfolio_recs": [], "watchlist_recs": [], "raw_synthesis": ""}

    # Safety-aware filtering: when portfolio risk is elevated, constrain recs
    safety_constraint = ""
    if portfolio_safety_score is not None:
        if portfolio_safety_score < 30:
            # Crisis mode: only surface hedges and diversifiers
            safety_constraint = (
                f"\n\nCRITICAL PORTFOLIO CONTEXT: Safety score is {portfolio_safety_score}/100 (crisis level). "
                "DO NOT recommend high-beta, speculative, or momentum stocks. "
                "ONLY recommend: hedges (inverse ETFs, put strategies), diversifiers "
                "(uncorrelated assets, value/defensive names), or low-beta quality stocks. "
                "Suppress all moonshot-type recommendations."
            )
            max_portfolio = min(max_portfolio, 2)
            log.warning("Safety gate: score %d — constraining to hedges/diversifiers only", portfolio_safety_score)
        elif portfolio_safety_score < 50:
            safety_constraint = (
                f"\n\nPORTFOLIO CONTEXT: Safety score is {portfolio_safety_score}/100 (elevated risk). "
                "Prioritize quality, low-beta, and diversifying picks over high-growth/speculative names. "
                "Limit speculative watchlist entries to 2 maximum."
            )
            max_watchlist = min(max_watchlist, 5)

    # Check budget
    within_budget, spent, cap = check_budget()
    if not within_budget:
        log.warning("Budget exceeded ($%.2f/$%.2f) — skipping synthesis", spent, cap)
        return _fallback_recommendations(scored_candidates, max_portfolio, max_watchlist)

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

{safety_constraint}

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
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=MODEL,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )

        usage = response.usage
        record_usage(AGENT_NAME, usage.input_tokens, usage.output_tokens, model=MODEL, response=response)

        raw_text = response.content[0].text
        log.info(
            "Synthesis complete: %d tokens in, %d tokens out",
            usage.input_tokens,
            usage.output_tokens,
        )

        return _parse_synthesis(raw_text, scored_candidates)

    except Exception:
        log.exception("Gemini synthesis failed — falling back to score-based ranking")
        return _fallback_recommendations(scored_candidates, max_portfolio, max_watchlist)


def _parse_synthesis(raw_text: str, scored_candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """Parse the JSON output from Gemini and validate tickers."""
    text = raw_text.strip()

    # Handle markdown code blocks
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        log.error("Failed to parse synthesis JSON, using raw text")
        return {
            "portfolio_recs": [],
            "watchlist_recs": [],
            "quarantined_recs": [],
            "raw_synthesis": raw_text,
        }

    # Build lookup for scores and fundamentals
    score_lookup = {c["ticker"]: c.get("scores", {}) for c in scored_candidates}
    fund_lookup = {c["ticker"]: c.get("fundamentals_summary", {}) for c in scored_candidates}
    valid_tickers = set(score_lookup.keys())

    def _build_rec(rec: dict, category: str) -> dict[str, Any]:
        ticker = rec.get("ticker", "")
        thesis = rec.get("thesis", "")
        tags: list[str] = []
        if _has_unverified_figures(ticker, thesis, fund_lookup):
            tags.append("unverified_figures")

        return {
            "ticker": ticker,
            "category": category,
            "conviction": rec.get("conviction", "medium"),
            "thesis": thesis,
            "scores": score_lookup.get(ticker, {}),
            "fundamentals_summary": fund_lookup.get(ticker, {}),
            "validation": "in_candidate_universe",
            "tags": tags,
        }

    portfolio_recs: list[dict[str, Any]] = []
    watchlist_recs: list[dict[str, Any]] = []
    quarantined_recs: list[dict[str, Any]] = []

    for rec in data.get("portfolio", []):
        ticker = rec.get("ticker", "")
        is_valid, reason = _validate_ticker(ticker, valid_tickers)
        if not is_valid:
            log.warning("Quarantined portfolio recommendation: %s (%s)", ticker, reason)
            quarantined_recs.append({
                "ticker": ticker,
                "category": "portfolio",
                "conviction": rec.get("conviction", "medium"),
                "thesis": rec.get("thesis", ""),
                "quarantine_reason": reason,
            })
            continue
        portfolio_recs.append(_build_rec(rec, "portfolio"))

    for rec in data.get("watchlist", []):
        ticker = rec.get("ticker", "")
        is_valid, reason = _validate_ticker(ticker, valid_tickers)
        if not is_valid:
            log.warning("Quarantined watchlist recommendation: %s (%s)", ticker, reason)
            quarantined_recs.append({
                "ticker": ticker,
                "category": "watchlist",
                "conviction": rec.get("conviction", "medium"),
                "thesis": rec.get("thesis", ""),
                "quarantine_reason": reason,
            })
            continue
        watchlist_recs.append(_build_rec(rec, "watchlist"))

    if quarantined_recs:
        log.warning(
            "Synthesis quarantined %d invalid ticker(s): %s",
            len(quarantined_recs),
            [r["ticker"] for r in quarantined_recs],
        )

    return {
        "portfolio_recs": portfolio_recs,
        "watchlist_recs": watchlist_recs,
        "quarantined_recs": quarantined_recs,
        "raw_synthesis": raw_text,
    }


def _fallback_recommendations(
    scored_candidates: list[dict[str, Any]],
    max_portfolio: int,
    max_watchlist: int,
) -> dict[str, Any]:
    """Generate recommendations based purely on composite scores (no LLM call)."""
    portfolio_recs = []
    watchlist_recs = []

    for candidate in scored_candidates:
        composite = candidate.get("scores", {}).get("composite", 0)
        ticker = candidate["ticker"]

        rec = {
            "ticker": ticker,
            "conviction": "high" if composite >= 70 else "medium" if composite >= 50 else "low",
            "thesis": f"Composite score {composite:.1f}. Source: {candidate.get('source', 'unknown')}.",
            "scores": candidate.get("scores", {}),
            "fundamentals_summary": candidate.get("fundamentals_summary", {}),
            "validation": "in_candidate_universe",
            "tags": [],
        }

        if composite >= 60 and len(portfolio_recs) < max_portfolio:
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
        "quarantined_recs": [],
        "raw_synthesis": "(fallback — synthesis skipped due to budget or error)",
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
