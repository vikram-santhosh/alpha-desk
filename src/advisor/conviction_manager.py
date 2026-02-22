"""Conviction list manager for AlphaDesk Advisor.

Maintains a persistent conviction list of 3-5 names that evolves over weeks.
Names are added based on multi-source evidence scoring and the 25% CAGR gate.
Names persist until evidence weakens, not because something new appeared.
"""

import anthropic

from src.advisor import memory
from src.advisor.valuation_engine import compute_target_price, passes_investment_gate
from src.shared.cost_tracker import check_budget, record_usage
from src.utils.logger import get_logger

log = get_logger(__name__)

_THESIS_AGENT = "advisor_conviction"
_MODEL = "claude-opus-4-6"


def evidence_test(
    ticker: str,
    guidance_data: dict | None,
    crowd_data: dict | None,
    smart_money_data: dict | None,
    fundamentals: dict | None,
    valuation: dict | None,
) -> tuple[int, list[str]]:
    """Test a ticker against 5 evidence sources.

    Evidence sources:
        1. Company guidance: raised or positive tone
        2. Crowd: Reddit sentiment positive + prediction markets favorable
        3. Smart money: superinvestors holding + insiders buying
        4. Numbers: revenue growing, ROIC > 15%, margins positive
        5. Valuation: passes 25% CAGR gate

    Args:
        ticker: Stock ticker.
        guidance_data: Earnings call data dict (from earnings_analyzer/memory).
        crowd_data: Dict with reddit_sentiment, prediction_market_probability keys.
        smart_money_data: Dict with superinvestor_count, insider_buying keys.
        fundamentals: Fundamentals dict from fundamental_analyzer.
        valuation: Valuation dict from valuation_engine.

    Returns:
        Tuple of (sources_passing 0-5, list of pass/fail descriptions).
    """
    sources_passing = 0
    descriptions = []

    # 1. Company guidance
    if guidance_data:
        sentiment = guidance_data.get("guidance_sentiment", "")
        tone = guidance_data.get("management_tone", "")
        if sentiment in ("raised",) or tone in ("confident",):
            sources_passing += 1
            descriptions.append(
                f"PASS Company guidance: sentiment={sentiment}, tone={tone}"
            )
        elif sentiment in ("maintained",) and tone not in ("defensive",):
            sources_passing += 1
            descriptions.append(
                f"PASS Company guidance: maintained guidance, tone={tone}"
            )
        else:
            descriptions.append(
                f"FAIL Company guidance: sentiment={sentiment or 'N/A'}, tone={tone or 'N/A'}"
            )
    else:
        descriptions.append("FAIL Company guidance: no earnings data available")

    # 2. Crowd (Reddit + prediction markets)
    if crowd_data:
        reddit_positive = False
        prediction_favorable = False

        reddit_sentiment = crowd_data.get("reddit_sentiment")
        if reddit_sentiment is not None and reddit_sentiment > 0.3:
            reddit_positive = True

        pred_prob = crowd_data.get("prediction_market_probability")
        if pred_prob is not None and pred_prob > 0.6:
            prediction_favorable = True

        # Also accept if just one strong signal
        if reddit_positive or prediction_favorable:
            sources_passing += 1
            parts = []
            if reddit_positive:
                parts.append(f"Reddit sentiment +{reddit_sentiment:.2f}")
            if prediction_favorable:
                parts.append(f"prediction mkt {pred_prob:.0%}")
            descriptions.append(f"PASS Crowd: {', '.join(parts)}")
        else:
            descriptions.append(
                f"FAIL Crowd: Reddit={reddit_sentiment}, prediction={pred_prob}"
            )
    else:
        descriptions.append("FAIL Crowd: no crowd data available")

    # 3. Smart money
    if smart_money_data:
        si_count = smart_money_data.get("superinvestor_count", 0)
        insider_buying = smart_money_data.get("insider_buying", False)

        if si_count >= 2 or insider_buying:
            sources_passing += 1
            parts = []
            if si_count >= 2:
                parts.append(f"{si_count} superinvestors holding")
            if insider_buying:
                parts.append("insider buying detected")
            descriptions.append(f"PASS Smart money: {', '.join(parts)}")
        elif si_count >= 1:
            sources_passing += 1
            descriptions.append(f"PASS Smart money: {si_count} superinvestor holding")
        else:
            descriptions.append("FAIL Smart money: no superinvestor or insider activity")
    else:
        descriptions.append("FAIL Smart money: no data available")

    # 4. Numbers (fundamentals)
    if fundamentals:
        rev_growth = fundamentals.get("revenue_growth")
        net_margin = fundamentals.get("net_margin")
        gross_margin = fundamentals.get("gross_margin")

        checks_passed = 0
        if rev_growth is not None and rev_growth > 0:
            checks_passed += 1
        if net_margin is not None and net_margin > 0:
            checks_passed += 1
        if gross_margin is not None and gross_margin > 0.3:
            checks_passed += 1

        if checks_passed >= 2:
            sources_passing += 1
            descriptions.append(
                f"PASS Numbers: rev_growth={_fmt_pct(rev_growth)}, "
                f"net_margin={_fmt_pct(net_margin)}, gross_margin={_fmt_pct(gross_margin)}"
            )
        else:
            descriptions.append(
                f"FAIL Numbers: rev_growth={_fmt_pct(rev_growth)}, "
                f"net_margin={_fmt_pct(net_margin)}, gross_margin={_fmt_pct(gross_margin)}"
            )
    else:
        descriptions.append("FAIL Numbers: no fundamentals available")

    # 5. Valuation (CAGR gate)
    if valuation and not valuation.get("insufficient_data"):
        passes, gate_reason = passes_investment_gate(valuation)
        if passes:
            sources_passing += 1
            descriptions.append(
                f"PASS Valuation: CAGR {valuation.get('implied_cagr', 0):.1f}%, "
                f"MoS {valuation.get('margin_of_safety', 0):.1f}%"
            )
        else:
            descriptions.append(f"FAIL Valuation: {gate_reason}")
    else:
        reason = valuation.get("reason", "no valuation data") if valuation else "no valuation data"
        descriptions.append(f"FAIL Valuation: {reason}")

    log.info("%s evidence test: %d/5 sources passing", ticker, sources_passing)
    return sources_passing, descriptions


def _fmt_pct(val: float | None) -> str:
    """Format a float as a percentage string or N/A."""
    if val is None:
        return "N/A"
    return f"{val * 100:.1f}%"


def _determine_conviction(sources_passing: int) -> str:
    """Map evidence count to conviction level."""
    if sources_passing >= 4:
        return "high"
    elif sources_passing >= 3:
        return "medium"
    else:
        return "low"


def update_conviction_list(
    candidates: list[dict],
    superinvestor_data: dict,
    earnings_data: dict,
    prediction_data: list[dict],
    valuation_data: dict,
    config: dict,
) -> dict:
    """Update the persistent conviction list with latest data.

    Takes all data sources, reviews existing entries, evaluates new candidates,
    and maintains the conviction list in memory.

    Args:
        candidates: Scored candidates from Alpha Scout screener.
        superinvestor_data: Dict mapping ticker -> superinvestor info.
        earnings_data: Dict mapping ticker -> latest earnings call data.
        prediction_data: List of prediction market entries.
        valuation_data: Dict mapping ticker -> valuation from valuation_engine.
        config: Advisor config dict.

    Returns:
        Dict with current_list, added, removed, upgraded lists.
    """
    strategy = config.get("strategy", {})
    min_evidence = strategy.get("min_evidence_sources", 2)
    output_config = config.get("output", {})
    max_entries = output_config.get("max_conviction_list", 5)

    current_list = memory.get_conviction_list(active_only=True)
    current_tickers = {entry["ticker"] for entry in current_list}

    added = []
    removed = []
    upgraded = []

    # Build a prediction lookup by ticker
    prediction_by_ticker: dict[str, dict] = {}
    for pred in prediction_data:
        for t in pred.get("affected_tickers", []):
            if t not in prediction_by_ticker:
                prediction_by_ticker[t] = pred

    # --- Phase 1: Review existing entries ---
    for entry in current_list:
        ticker = entry["ticker"]

        # Gather evidence data for this ticker
        si_data = superinvestor_data.get(ticker)
        earn_data = earnings_data.get(ticker)
        fund_data = _extract_fundamentals_from_candidates(ticker, candidates)
        val_data = valuation_data.get(ticker)
        crowd = _build_crowd_data(ticker, candidates, prediction_by_ticker)

        sources_passing, descriptions = evidence_test(
            ticker, earn_data, crowd, si_data, fund_data, val_data,
        )

        old_conviction = entry.get("conviction", "medium")
        new_conviction = _determine_conviction(sources_passing)

        # If evidence has weakened below threshold, consider removal
        if sources_passing < 2:
            memory.remove_conviction(ticker, f"Evidence weakened to {sources_passing}/5")
            removed.append({"ticker": ticker, "reason": f"Evidence {sources_passing}/5"})
            log.info("Removed %s from conviction list: evidence %d/5", ticker, sources_passing)
            continue

        # Update conviction level if changed
        if new_conviction != old_conviction:
            if _conviction_rank(new_conviction) > _conviction_rank(old_conviction):
                upgraded.append({
                    "ticker": ticker,
                    "from": old_conviction,
                    "to": new_conviction,
                })
                log.info("Upgraded %s conviction: %s -> %s", ticker, old_conviction, new_conviction)

            memory.upsert_conviction(
                ticker=ticker,
                conviction=new_conviction,
                thesis=entry.get("thesis", ""),
                pros=descriptions[:3],
                cons=[d for d in descriptions if d.startswith("FAIL")][:3],
            )

    # Refresh list after updates
    current_list = memory.get_conviction_list(active_only=True)
    current_tickers = {entry["ticker"] for entry in current_list}
    slots_available = max_entries - len(current_list)

    # --- Phase 2: Evaluate new candidates ---
    if slots_available > 0 and candidates:
        # Sort candidates by composite score descending
        sorted_candidates = sorted(
            candidates,
            key=lambda c: c.get("scores", {}).get("composite", 0),
            reverse=True,
        )

        for candidate in sorted_candidates:
            if slots_available <= 0:
                break

            ticker = candidate.get("ticker", "")
            if ticker in current_tickers:
                continue

            # Skip holdings (they're already in portfolio)
            holdings_tickers = {h.get("ticker") for h in config.get("holdings", [])}
            if ticker in holdings_tickers:
                continue

            # Gather evidence data
            si_data = superinvestor_data.get(ticker)
            earn_data = earnings_data.get(ticker)
            fund_data = candidate.get("fundamentals_summary") or {}
            # Merge full fundamentals if available in candidate signal_data
            if candidate.get("signal_data"):
                for k, v in candidate["signal_data"].items():
                    if k not in fund_data:
                        fund_data[k] = v
            val_data = valuation_data.get(ticker)
            crowd = _build_crowd_data(ticker, [candidate], prediction_by_ticker)

            sources_passing, descriptions = evidence_test(
                ticker, earn_data, crowd, si_data, fund_data, val_data,
            )

            if sources_passing < min_evidence:
                log.debug(
                    "Skipping %s: only %d/%d evidence sources",
                    ticker, sources_passing, min_evidence,
                )
                continue

            conviction = _determine_conviction(sources_passing)
            thesis = _generate_thesis_via_opus(
                ticker, candidate, descriptions, valuation=valuation_data.get(ticker),
            )

            memory.upsert_conviction(
                ticker=ticker,
                conviction=conviction,
                thesis=thesis,
                pros=[d for d in descriptions if d.startswith("PASS")][:5],
                cons=[d for d in descriptions if d.startswith("FAIL")][:5],
            )

            added.append({
                "ticker": ticker,
                "conviction": conviction,
                "evidence_sources": sources_passing,
            })
            current_tickers.add(ticker)
            slots_available -= 1
            log.info("Added %s to conviction list: conviction=%s, evidence=%d/5",
                     ticker, conviction, sources_passing)

    # Increment weeks for all active entries (done weekly in orchestrator,
    # but safe to call — memory layer handles idempotency)

    final_list = memory.get_conviction_list(active_only=True)

    result = {
        "current_list": final_list,
        "added": added,
        "removed": removed,
        "upgraded": upgraded,
    }

    log.info(
        "Conviction update: %d active, +%d added, -%d removed, %d upgraded",
        len(final_list), len(added), len(removed), len(upgraded),
    )
    return result


def _conviction_rank(level: str) -> int:
    """Return numeric rank for conviction level comparison."""
    return {"low": 0, "medium": 1, "high": 2}.get(level, 0)


def _extract_fundamentals_from_candidates(
    ticker: str, candidates: list[dict],
) -> dict | None:
    """Try to find fundamentals for a ticker from the candidates list."""
    for c in candidates:
        if c.get("ticker") == ticker:
            return c.get("fundamentals_summary") or {}
    return None


def _build_crowd_data(
    ticker: str,
    candidates: list[dict],
    prediction_by_ticker: dict[str, dict],
) -> dict | None:
    """Build crowd data dict from candidates and prediction markets."""
    crowd: dict = {}

    # Reddit sentiment from candidate signal data
    for c in candidates:
        if c.get("ticker") == ticker:
            signal = c.get("signal_data", {})
            sentiment = signal.get("sentiment") or signal.get("avg_sentiment")
            if sentiment is not None:
                crowd["reddit_sentiment"] = sentiment
            break

    # Prediction market probability
    pred = prediction_by_ticker.get(ticker)
    if pred:
        crowd["prediction_market_probability"] = pred.get("probability")

    return crowd if crowd else {}


def _generate_thesis_via_opus(
    ticker: str,
    candidate: dict,
    descriptions: list[str],
    valuation: dict | None = None,
) -> str:
    """Generate an investment thesis for a conviction list entry via Opus.

    Falls back to template-based thesis if budget is exceeded or API fails.
    """
    within_budget, spent, cap = check_budget()
    if not within_budget:
        log.warning("Budget exceeded ($%.2f/$%.2f) — fallback thesis for %s", spent, cap, ticker)
        return _build_thesis_fallback(ticker, candidate, descriptions)

    scores = candidate.get("scores", {})
    fund = candidate.get("fundamentals_summary", {})

    evidence_passing = [d for d in descriptions if d.startswith("PASS")]
    evidence_failing = [d for d in descriptions if d.startswith("FAIL")]

    valuation_ctx = ""
    if valuation and not valuation.get("insufficient_data"):
        valuation_ctx = (
            f"Target price: ${valuation.get('target_price', 0):.2f}, "
            f"implied CAGR: {valuation.get('implied_cagr', 0):.1f}%, "
            f"margin of safety: {valuation.get('margin_of_safety', 0):.1f}%"
        )

    mcap = fund.get("market_cap")
    mcap_str = f"${mcap / 1e9:.1f}B" if mcap else "N/A"

    prompt = f"""Write a concise 2-3 sentence investment thesis for {ticker} as a conviction watchlist candidate.

DATA:
- Composite score: {scores.get('composite', 'N/A')}/100
- Market cap: {mcap_str}
- Revenue growth: {_fmt_pct(fund.get('revenue_growth'))}
- Net margin: {_fmt_pct(fund.get('net_margin'))}
- P/E trailing: {fund.get('pe_trailing', 'N/A')}
- Sector: {fund.get('sector', 'N/A')}
- Source: {candidate.get('source', 'N/A')}
- Valuation: {valuation_ctx or 'N/A'}

EVIDENCE PASSING:
{chr(10).join(evidence_passing) if evidence_passing else 'None'}

EVIDENCE FAILING:
{chr(10).join(evidence_failing) if evidence_failing else 'None'}

RULES:
- Be specific: cite numbers (growth rate, P/E, CAGR).
- State the core WHY: what catalyst or structural advantage makes this interesting.
- Mention the key risk in one clause.
- Do NOT use bullet points. Write prose. 2-3 sentences max.
- Respond with ONLY the thesis text, no headers or labels."""

    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=_MODEL,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        if not response.content:
            log.warning("Empty Opus response for %s", ticker)
            return _build_thesis_fallback(ticker, candidate, descriptions)
        usage = response.usage
        record_usage(_THESIS_AGENT, usage.input_tokens, usage.output_tokens)
        thesis = response.content[0].text.strip()
        log.info("Opus thesis for %s (%d in, %d out)", ticker, usage.input_tokens, usage.output_tokens)
        return thesis
    except Exception:
        log.exception("Opus thesis failed for %s — using fallback", ticker)
        return _build_thesis_fallback(ticker, candidate, descriptions)


def _build_thesis_fallback(ticker: str, candidate: dict, descriptions: list[str]) -> str:
    """Fallback: build a template thesis from candidate data and evidence."""
    fund = candidate.get("fundamentals_summary", {})
    sector = fund.get("sector", "")
    rev_growth = fund.get("revenue_growth")
    parts = []
    if sector:
        parts.append(sector)
    if rev_growth is not None:
        parts.append(f"{rev_growth * 100:.0f}% revenue growth")
    passing = [d.replace("PASS ", "") for d in descriptions if d.startswith("PASS")]
    if passing:
        parts.append("; ".join(p.split(":")[0] for p in passing))
    return f"{ticker} — " + ", ".join(parts) if parts else f"{ticker} — conviction list candidate"
