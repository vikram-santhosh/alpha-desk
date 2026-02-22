"""Opus 4.6 synthesis for Alpha Scout.

Takes the top-N screened candidates and uses Claude to:
- Rank them with investment context
- Generate 2-3 sentence thesis per ticker
- Categorize as "portfolio" (buy) vs "watchlist" (monitor)
- Assign conviction: high / medium / low
"""

import json
from typing import Any

import anthropic

from src.shared.cost_tracker import check_budget, record_usage
from src.utils.logger import get_logger

log = get_logger(__name__)

AGENT_NAME = "alpha_scout"
MODEL = "claude-opus-4-6"


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
    """Use Opus 4.6 to synthesize ranked recommendations.

    Args:
        scored_candidates: Candidates sorted by composite score.
        top_n: Number of top candidates to send to Opus.
        max_portfolio: Max portfolio (buy) recommendations.
        max_watchlist: Max watchlist (monitor) recommendations.

    Returns:
        Dict with:
            portfolio_recs: List of portfolio recommendation dicts.
            watchlist_recs: List of watchlist recommendation dicts.
            raw_synthesis: Raw text from Opus.
    """
    if not scored_candidates:
        return {"portfolio_recs": [], "watchlist_recs": [], "raw_synthesis": ""}

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
        record_usage(AGENT_NAME, usage.input_tokens, usage.output_tokens)

        raw_text = response.content[0].text
        log.info(
            "Synthesis complete: %d tokens in, %d tokens out",
            usage.input_tokens,
            usage.output_tokens,
        )

        return _parse_synthesis(raw_text, scored_candidates)

    except Exception:
        log.exception("Opus synthesis failed — falling back to score-based ranking")
        return _fallback_recommendations(scored_candidates, max_portfolio, max_watchlist)


def _parse_synthesis(raw_text: str, scored_candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """Parse the JSON output from Opus 4.6."""
    # Try to extract JSON from the response
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
            "raw_synthesis": raw_text,
        }

    # Build lookup for scores
    score_lookup = {c["ticker"]: c.get("scores", {}) for c in scored_candidates}
    fund_lookup = {c["ticker"]: c.get("fundamentals_summary", {}) for c in scored_candidates}

    portfolio_recs = []
    for rec in data.get("portfolio", []):
        ticker = rec.get("ticker", "")
        portfolio_recs.append({
            "ticker": ticker,
            "category": "portfolio",
            "conviction": rec.get("conviction", "medium"),
            "thesis": rec.get("thesis", ""),
            "scores": score_lookup.get(ticker, {}),
            "fundamentals_summary": fund_lookup.get(ticker, {}),
        })

    watchlist_recs = []
    for rec in data.get("watchlist", []):
        ticker = rec.get("ticker", "")
        watchlist_recs.append({
            "ticker": ticker,
            "category": "watchlist",
            "conviction": rec.get("conviction", "medium"),
            "thesis": rec.get("thesis", ""),
            "scores": score_lookup.get(ticker, {}),
            "fundamentals_summary": fund_lookup.get(ticker, {}),
        })

    return {
        "portfolio_recs": portfolio_recs,
        "watchlist_recs": watchlist_recs,
        "raw_synthesis": raw_text,
    }


def _fallback_recommendations(
    scored_candidates: list[dict[str, Any]],
    max_portfolio: int,
    max_watchlist: int,
) -> dict[str, Any]:
    """Generate recommendations based purely on composite scores (no Opus)."""
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
        "raw_synthesis": "(fallback — synthesis skipped due to budget or error)",
    }
