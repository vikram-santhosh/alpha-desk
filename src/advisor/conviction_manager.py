"""Conviction list manager for AlphaDesk Advisor.

Maintains a persistent conviction list of 3-5 names that evolves over weeks.
Names are added based on multi-source evidence scoring and the 25% CAGR gate.
Names persist until evidence weakens, not because something new appeared.
"""
from __future__ import annotations

from datetime import date

from src.shared import gemini_compat as anthropic

from src.advisor import memory
from src.advisor.valuation_engine import passes_investment_gate
from src.shared.cost_tracker import check_budget, record_usage
from src.shared.schemas import (
    EvidenceItem,
    compute_recency_decay,
    BASE_WEIGHTS,
)
from src.utils.logger import get_logger

log = get_logger(__name__)

_THESIS_AGENT = "advisor_conviction"
_MODEL = "claude-opus-4-6"
DEFAULT_CONVICTION_WEIGHTS = {
    "company_guidance": 0.30,
    "fundamentals": 0.28,
    "smart_money": 0.22,
    "analyst_consensus": 0.12,
    "crowd_sentiment": 0.08,
}


def evidence_test(
    ticker: str,
    guidance_data: dict | None,
    crowd_data: dict | None,
    smart_money_data: dict | None,
    fundamentals: dict | None,
    valuation: dict | None,
    *,
    gate_config: dict | None = None,
    role: str = "growth",
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
        gate_config = gate_config or {}
        passes, gate_reason = passes_investment_gate(
            valuation,
            min_cagr=gate_config.get("min_cagr_pct", 25),
            min_mos=gate_config.get("min_margin_of_safety_pct", 15),
            role=role,
            gate_by_role=gate_config.get("gate_by_role", {}),
        )
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


def build_evidence_items(
    ticker: str,
    guidance_data: dict | None,
    crowd_data: dict | None,
    smart_money_data: dict | None,
    fundamentals: dict | None,
    valuation: dict | None,
) -> list[EvidenceItem]:
    """Build weighted EvidenceItem objects from the same data as evidence_test.

    This produces structured evidence with proper weights and recency decay,
    complementing the legacy pass/fail evidence_test for backward compatibility.
    """
    items: list[EvidenceItem]  = []
    today = date.today().isoformat()

    # 1. Company guidance
    if guidance_data:
        sentiment = guidance_data.get("guidance_sentiment", "")
        tone = guidance_data.get("management_tone", "")
        if sentiment == "raised" and tone == "confident":
            items.append(EvidenceItem(
                source="earnings_transcript", date=today,
                claim="Guidance raised, tone confident",
                base_weight=BASE_WEIGHTS["earnings_guidance_raised_confident"],
                recency_days=7,
            ))
        elif sentiment == "raised" or tone == "confident":
            items.append(EvidenceItem(
                source="earnings_transcript", date=today,
                claim=f"Guidance {sentiment}, tone {tone}",
                base_weight=BASE_WEIGHTS["earnings_guidance_raised"],
                recency_days=7,
            ))
        elif sentiment == "maintained" and tone != "defensive":
            items.append(EvidenceItem(
                source="earnings_transcript", date=today,
                claim=f"Guidance maintained, tone {tone}",
                base_weight=BASE_WEIGHTS["earnings_guidance_maintained"],
                recency_days=7,
            ))
        elif sentiment == "lowered" or tone == "defensive":
            items.append(EvidenceItem(
                source="earnings_transcript", date=today,
                claim=f"Guidance {sentiment}, tone {tone} (negative)",
                base_weight=BASE_WEIGHTS["earnings_guidance_lowered"],
                recency_days=7,
            ))

    # 2. Crowd sentiment
    if crowd_data:
        reddit_sentiment = crowd_data.get("reddit_sentiment")
        mentions = crowd_data.get("mentions", 0)
        if reddit_sentiment is not None:
            if reddit_sentiment > 0.7 and mentions > 10:
                items.append(EvidenceItem(
                    source="reddit_sentiment", date=today,
                    claim=f"Strong Reddit sentiment ({reddit_sentiment:.2f}, {mentions} mentions)",
                    base_weight=BASE_WEIGHTS["reddit_strong_positive"],
                    recency_days=3,
                ))
            elif reddit_sentiment > 0.5:
                items.append(EvidenceItem(
                    source="reddit_sentiment", date=today,
                    claim=f"Moderate Reddit sentiment ({reddit_sentiment:.2f})",
                    base_weight=BASE_WEIGHTS["reddit_moderate_positive"],
                    recency_days=3,
                ))
            elif reddit_sentiment > 0.3:
                items.append(EvidenceItem(
                    source="reddit_sentiment", date=today,
                    claim=f"Weak positive Reddit sentiment ({reddit_sentiment:.2f})",
                    base_weight=BASE_WEIGHTS["reddit_weak_positive"],
                    recency_days=3,
                ))
            elif reddit_sentiment < -0.3 and mentions > 5:
                items.append(EvidenceItem(
                    source="reddit_sentiment", date=today,
                    claim=f"Negative Reddit sentiment ({reddit_sentiment:.2f})",
                    base_weight=BASE_WEIGHTS["reddit_negative"],
                    recency_days=3,
                ))

        pred_prob = crowd_data.get("prediction_market_probability")
        if pred_prob is not None:
            if pred_prob > 0.7:
                items.append(EvidenceItem(
                    source="prediction_market", date=today,
                    claim=f"Prediction market favorable ({pred_prob:.0%})",
                    base_weight=BASE_WEIGHTS["prediction_market_favorable"],
                    recency_days=1,
                ))
            elif pred_prob < 0.3:
                items.append(EvidenceItem(
                    source="prediction_market", date=today,
                    claim=f"Prediction market unfavorable ({pred_prob:.0%})",
                    base_weight=BASE_WEIGHTS["prediction_market_unfavorable"],
                    recency_days=1,
                ))

    # 3. Smart money
    if smart_money_data:
        si_count = smart_money_data.get("superinvestor_count", 0)
        insider_buying = smart_money_data.get("insider_buying", False)

        if insider_buying:
            items.append(EvidenceItem(
                source="insider_filing", date=today,
                claim="Insider buying detected",
                base_weight=BASE_WEIGHTS["insider_purchase_small"],
                recency_days=14,
            ))
        if si_count >= 3:
            items.append(EvidenceItem(
                source="superinvestor_13f", date=today,
                claim=f"{si_count} superinvestors holding",
                base_weight=BASE_WEIGHTS["superinvestor_3plus"],
                recency_days=45,
            ))
        elif si_count >= 2:
            items.append(EvidenceItem(
                source="superinvestor_13f", date=today,
                claim=f"{si_count} superinvestors holding",
                base_weight=BASE_WEIGHTS["superinvestor_2"],
                recency_days=45,
            ))
        elif si_count >= 1:
            items.append(EvidenceItem(
                source="superinvestor_13f", date=today,
                claim=f"{si_count} superinvestor holding",
                base_weight=BASE_WEIGHTS["superinvestor_existing"],
                recency_days=45,
            ))

    # 4. Fundamentals
    if fundamentals:
        rev_growth = fundamentals.get("revenue_growth")
        net_margin = fundamentals.get("net_margin")
        gross_margin = fundamentals.get("gross_margin")

        if rev_growth is not None and net_margin is not None and gross_margin is not None:
            if rev_growth > 0.30 and net_margin > 0.15 and gross_margin > 0.50:
                items.append(EvidenceItem(
                    source="fundamental_data", date=today,
                    claim=f"Strong fundamentals: rev growth {rev_growth:.0%}, margin {net_margin:.0%}",
                    base_weight=BASE_WEIGHTS["fundamentals_strong"],
                    recency_days=7,
                ))
            elif rev_growth > 0.15 and net_margin > 0 and gross_margin > 0.30:
                items.append(EvidenceItem(
                    source="fundamental_data", date=today,
                    claim=f"Moderate fundamentals: rev growth {rev_growth:.0%}",
                    base_weight=BASE_WEIGHTS["fundamentals_moderate"],
                    recency_days=7,
                ))
            elif rev_growth > 0 and net_margin is not None and net_margin > 0:
                items.append(EvidenceItem(
                    source="fundamental_data", date=today,
                    claim=f"Positive fundamentals: rev growth {rev_growth:.0%}",
                    base_weight=BASE_WEIGHTS["fundamentals_weak"],
                    recency_days=7,
                ))
            elif rev_growth is not None and rev_growth < 0:
                items.append(EvidenceItem(
                    source="fundamental_data", date=today,
                    claim=f"Declining fundamentals: rev growth {rev_growth:.0%}",
                    base_weight=BASE_WEIGHTS["fundamentals_declining"],
                    recency_days=7,
                ))

    # 5. Valuation
    if valuation and not valuation.get("insufficient_data"):
        cagr = valuation.get("implied_cagr", 0)
        mos = valuation.get("margin_of_safety", 0)
        if cagr > 35 and mos > 25:
            items.append(EvidenceItem(
                source="fundamental_data", date=today,
                claim=f"Attractive valuation: CAGR {cagr:.1f}%, MoS {mos:.1f}%",
                base_weight=BASE_WEIGHTS["valuation_attractive"],
                recency_days=1,
            ))
        elif cagr > 25 and mos > 15:
            items.append(EvidenceItem(
                source="fundamental_data", date=today,
                claim=f"Fair valuation: CAGR {cagr:.1f}%",
                base_weight=BASE_WEIGHTS["valuation_fair"],
                recency_days=1,
            ))
        elif cagr > 15:
            items.append(EvidenceItem(
                source="fundamental_data", date=today,
                claim=f"Moderate valuation: CAGR {cagr:.1f}%",
                base_weight=BASE_WEIGHTS["valuation_moderate"],
                recency_days=1,
            ))
        elif cagr < 0:
            items.append(EvidenceItem(
                source="fundamental_data", date=today,
                claim=f"Stretched valuation: negative CAGR {cagr:.1f}%",
                base_weight=BASE_WEIGHTS["valuation_stretched"],
                recency_days=1,
            ))

    # Compute weighted scores
    for item in items:
        item.weighted_score = item.base_weight * compute_recency_decay(item.recency_days)

    return items


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


def _determine_weighted_conviction(score: float) -> str:
    """Map weighted 0-1 conviction score to conviction level."""
    if score >= 0.70:
        return "high"
    if score >= 0.45:
        return "medium"
    return "low"


def _get_conviction_weights(config: dict | None) -> dict[str, float]:
    raw = (config or {}).get("conviction_weights") or {}
    weights = {
        key: float(raw.get(key, default))
        for key, default in DEFAULT_CONVICTION_WEIGHTS.items()
    }
    total = sum(weights.values())
    if total <= 0:
        return dict(DEFAULT_CONVICTION_WEIGHTS)
    return {key: value / total for key, value in weights.items()}


def score_weighted_conviction(
    *,
    guidance_data: dict | None,
    crowd_data: dict | None,
    smart_money_data: dict | None,
    fundamentals: dict | None,
    valuation: dict | None,
    weights: dict[str, float] | None = None,
) -> dict:
    """Score conviction dimensions using the configured hierarchy weights."""
    normalized_weights = weights or DEFAULT_CONVICTION_WEIGHTS
    dimensions = {
        "company_guidance": _score_company_guidance(guidance_data),
        "fundamentals": _score_fundamentals(fundamentals, valuation),
        "smart_money": _score_smart_money(smart_money_data),
        "analyst_consensus": _score_analyst_consensus(fundamentals),
        "crowd_sentiment": _score_crowd(crowd_data),
    }
    score = sum(normalized_weights.get(key, 0.0) * value for key, value in dimensions.items())
    return {
        "score": round(max(0.0, min(1.0, score)), 4),
        "dimension_scores": dimensions,
    }


def _score_company_guidance(guidance_data: dict | None) -> float:
    if not guidance_data:
        return 0.0
    sentiment = guidance_data.get("guidance_sentiment", "")
    tone = guidance_data.get("management_tone", "")
    if sentiment == "raised" and tone == "confident":
        return 1.0
    if sentiment == "raised" or tone == "confident":
        return 0.80
    if sentiment == "maintained" and tone != "defensive":
        return 0.55
    if sentiment == "lowered" or tone == "defensive":
        return 0.0
    return 0.20


def _score_fundamentals(fundamentals: dict | None, valuation: dict | None) -> float:
    if not fundamentals:
        return 0.0
    rev_growth = fundamentals.get("revenue_growth")
    net_margin = fundamentals.get("net_margin")
    gross_margin = fundamentals.get("gross_margin")
    score = 0.0
    if isinstance(rev_growth, (int, float)):
        if rev_growth > 0.30:
            score += 0.40
        elif rev_growth > 0.15:
            score += 0.30
        elif rev_growth > 0:
            score += 0.15
    if isinstance(net_margin, (int, float)):
        if net_margin > 0.15:
            score += 0.30
        elif net_margin > 0:
            score += 0.15
    if isinstance(gross_margin, (int, float)):
        if gross_margin > 0.50:
            score += 0.20
        elif gross_margin > 0.30:
            score += 0.10
    if valuation and not valuation.get("insufficient_data"):
        cagr = valuation.get("implied_cagr")
        mos = valuation.get("margin_of_safety")
        if isinstance(cagr, (int, float)) and cagr >= 25:
            score += 0.05
        if isinstance(mos, (int, float)) and mos >= 15:
            score += 0.05
    return max(0.0, min(1.0, score))


def _score_smart_money(smart_money_data: dict | None) -> float:
    if not smart_money_data:
        return 0.0
    si_count = smart_money_data.get("superinvestor_count", 0) or 0
    insider_buying = bool(smart_money_data.get("insider_buying", False))
    if si_count >= 3 and insider_buying:
        return 1.0
    if si_count >= 3:
        return 0.90
    if si_count >= 2 or insider_buying:
        return 0.75
    if si_count >= 1:
        return 0.50
    return 0.0


def _score_analyst_consensus(fundamentals: dict | None) -> float:
    if not fundamentals:
        return 0.0
    rating = str(
        fundamentals.get("analyst_rating")
        or fundamentals.get("recommendation_key")
        or fundamentals.get("recommendation")
        or ""
    ).lower()
    if "strong_buy" in rating or "strong buy" in rating:
        return 1.0
    if "buy" in rating or "outperform" in rating:
        return 0.75
    if "hold" in rating or "neutral" in rating:
        return 0.35

    current_price = fundamentals.get("current_price") or fundamentals.get("price")
    target_price = fundamentals.get("target_mean_price") or fundamentals.get("analyst_target_price")
    if isinstance(current_price, (int, float)) and isinstance(target_price, (int, float)) and current_price > 0:
        upside = (target_price - current_price) / current_price
        if upside > 0.25:
            return 0.85
        if upside > 0.10:
            return 0.60
        if upside > 0:
            return 0.35
    return 0.0


def _score_crowd(crowd_data: dict | None) -> float:
    if not crowd_data:
        return 0.0
    score = 0.0
    reddit_sentiment = crowd_data.get("reddit_sentiment")
    mentions = crowd_data.get("mentions", 0) or 0
    if isinstance(reddit_sentiment, (int, float)):
        if reddit_sentiment > 0.70 and mentions > 10:
            score = max(score, 1.0)
        elif reddit_sentiment > 0.50:
            score = max(score, 0.70)
        elif reddit_sentiment > 0.30:
            score = max(score, 0.45)
        elif reddit_sentiment < -0.30:
            score = max(score, 0.0)

    pred_prob = crowd_data.get("prediction_market_probability")
    if isinstance(pred_prob, (int, float)):
        if pred_prob > 0.70:
            score = max(score, 0.85)
        elif pred_prob > 0.60:
            score = max(score, 0.60)
        elif pred_prob < 0.30:
            score = min(score, 0.20)
    return max(0.0, min(1.0, score))


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
    conviction_weights = _get_conviction_weights(config)
    min_weighted_score = strategy.get("min_weighted_conviction_score", min_evidence / 5)

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
        earn_data = earnings_data.get("per_ticker", {}).get(ticker) if isinstance(earnings_data, dict) else None
        fund_data = _extract_fundamentals_from_candidates(ticker, candidates)
        val_data = valuation_data.get(ticker)
        crowd = _build_crowd_data(ticker, candidates, prediction_by_ticker)

        sources_passing, descriptions = evidence_test(
            ticker,
            earn_data,
            crowd,
            si_data,
            fund_data,
            val_data,
            gate_config=strategy,
            role=entry.get("role") or entry.get("category") or "growth",
        )
        weighted = score_weighted_conviction(
            guidance_data=earn_data,
            crowd_data=crowd,
            smart_money_data=si_data,
            fundamentals=fund_data,
            valuation=val_data,
            weights=conviction_weights,
        )
        weighted_score = weighted["score"]

        old_conviction = entry.get("conviction", "medium")
        new_conviction = _determine_weighted_conviction(weighted_score)

        # If evidence has weakened below threshold, consider removal
        if weighted_score < min_weighted_score:
            memory.remove_conviction(ticker, f"Weighted evidence weakened to {weighted_score:.2f}")
            removed.append({"ticker": ticker, "reason": f"Weighted evidence {weighted_score:.2f}"})
            log.info("Removed %s from conviction list: weighted evidence %.2f", ticker, weighted_score)
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
        def _candidate_weighted_sort_score(candidate: dict) -> tuple[float, float]:
            ticker = candidate.get("ticker", "")
            si_data = superinvestor_data.get(ticker)
            earn_data = earnings_data.get("per_ticker", {}).get(ticker) if isinstance(earnings_data, dict) else None
            fund_data = _fundamentals_for_candidate(candidate)
            val_data = valuation_data.get(ticker)
            crowd = _build_crowd_data(ticker, [candidate], prediction_by_ticker)
            weighted = score_weighted_conviction(
                guidance_data=earn_data,
                crowd_data=crowd,
                smart_money_data=si_data,
                fundamentals=fund_data,
                valuation=val_data,
                weights=conviction_weights,
            )
            return weighted["score"], candidate.get("scores", {}).get("composite", 0)

        # Sort candidates by weighted conviction first, screener score second.
        sorted_candidates = sorted(
            candidates,
            key=_candidate_weighted_sort_score,
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
            earn_data = earnings_data.get("per_ticker", {}).get(ticker) if isinstance(earnings_data, dict) else None
            fund_data = _fundamentals_for_candidate(candidate)
            val_data = valuation_data.get(ticker)
            crowd = _build_crowd_data(ticker, [candidate], prediction_by_ticker)

            sources_passing, descriptions = evidence_test(
                ticker,
                earn_data,
                crowd,
                si_data,
                fund_data,
                val_data,
                gate_config=strategy,
                role=candidate.get("role") or candidate.get("category") or "growth",
            )
            weighted = score_weighted_conviction(
                guidance_data=earn_data,
                crowd_data=crowd,
                smart_money_data=si_data,
                fundamentals=fund_data,
                valuation=val_data,
                weights=conviction_weights,
            )
            weighted_score = weighted["score"]

            # Relaxed threshold for discovery candidates (new names)
            min_evidence_discovery = max(min_evidence - 1, 2)
            min_weighted_discovery = strategy.get(
                "min_weighted_conviction_score_discovery",
                min_evidence_discovery / 5,
            )
            if weighted_score < min_weighted_discovery:
                log.debug(
                    "Skipping %s: weighted evidence %.2f below %.2f",
                    ticker, weighted_score, min_weighted_discovery,
                )
                continue

            conviction = _determine_weighted_conviction(weighted_score)
            thesis = _generate_thesis_via_opus(
                ticker, candidate, descriptions, valuation=valuation_data.get(ticker),
            )

            # Build source description from candidate data
            cand_source = candidate.get("source", "")
            if candidate.get("signal_type") == "superinvestor_new_position":
                fund = candidate.get("signal_data", {}).get("fund_name", candidate.get("signal_data", {}).get("investor", ""))
                val = candidate.get("signal_data", {}).get("position_value", candidate.get("signal_data", {}).get("value_usd"))
                cand_source = f"{fund} initiated ${val/1e6:.0f}M position" if val else f"{fund} new position"
            elif candidate.get("signal_type") == "reddit_moonshot":
                mc = candidate.get("signal_data", {}).get("mention_count", 0)
                subs = candidate.get("signal_data", {}).get("top_subreddits", [])
                cand_source = f"{mc} Reddit mentions across {', '.join(subs[:2])}"

            memory.upsert_conviction(
                ticker=ticker,
                conviction=conviction,
                thesis=thesis,
                pros=[d for d in descriptions if d.startswith("PASS")][:5],
                cons=[d for d in descriptions if d.startswith("FAIL")][:5],
                source=cand_source or candidate.get("source"),
            )

            added.append({
                "ticker": ticker,
                "conviction": conviction,
                "evidence_sources": sources_passing,
                "weighted_score": weighted_score,
                "dimension_scores": weighted["dimension_scores"],
            })
            current_tickers.add(ticker)
            slots_available -= 1
            log.info("Added %s to conviction list: conviction=%s, weighted=%.2f",
                     ticker, conviction, weighted_score)

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


def _fundamentals_for_candidate(candidate: dict) -> dict:
    fund_data = dict(candidate.get("fundamentals_summary") or {})
    if candidate.get("signal_data"):
        for key, value in candidate["signal_data"].items():
            if key not in fund_data:
                fund_data[key] = value
    return fund_data


def _build_crowd_data(
    ticker: str,
    candidates: list[dict],
    prediction_by_ticker: dict[str, dict],
) -> dict | None:
    """Build crowd data dict from candidates and prediction markets."""
    crowd: dict = {}

    # Reddit sentiment from candidate signal data
    # First check the candidate with matching ticker
    for c in candidates:
        if c.get("ticker") == ticker:
            signal = c.get("signal_data", {})
            sentiment = signal.get("sentiment") or signal.get("avg_sentiment")
            if sentiment is not None:
                crowd["reddit_sentiment"] = sentiment
                mentions = signal.get("mentions")
                if mentions is not None:
                    crowd["mentions"] = mentions
            break

    # If no direct match, scan all candidates for any signal_data mentioning this ticker
    if "reddit_sentiment" not in crowd:
        for c in candidates:
            signal = c.get("signal_data", {})
            if not signal:
                continue
            # Check if this candidate's signal data references our ticker
            mentioned_tickers = signal.get("tickers", [])
            if ticker in mentioned_tickers:
                sentiment = signal.get("sentiment") or signal.get("avg_sentiment")
                if sentiment is not None:
                    crowd["reddit_sentiment"] = sentiment
                    mentions = signal.get("mentions")
                    if mentions is not None:
                        crowd["mentions"] = mentions
                    break
            # Also accept if the candidate itself has sentiment and matches loosely
            if c.get("ticker") == ticker:
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
        record_usage(_THESIS_AGENT, usage.input_tokens, usage.output_tokens, model=response.model)
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
