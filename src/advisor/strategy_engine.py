"""Portfolio strategy engine for AlphaDesk Advisor.

Produces add/trim/hold recommendations with a strong low-churn bias.
Default is "no action". Only recommends changes when evidence is strong
and multi-factor (thesis invalidation, concentration risk, extreme
valuation, or major negative catalyst).
"""

from src.advisor import memory
from src.advisor.valuation_engine import passes_investment_gate
from src.utils.logger import get_logger

log = get_logger(__name__)


def should_trim(
    holding: dict,
    valuation: dict,
    config: dict,
) -> tuple[bool, str]:
    """Check if a holding should be trimmed.

    Criteria:
        - Position % > max_position_pct (concentration risk)
        - Valuation > 2x historical P/E average (extreme stretch)
        - Thesis weakening or invalidated

    Args:
        holding: Holding dict from memory (has ticker, thesis_status, etc.).
        valuation: Valuation dict from valuation_engine.
        config: Advisor config dict.

    Returns:
        Tuple of (should_trim, reason).
    """
    strategy = config.get("strategy", {})
    max_position_pct = strategy.get("max_position_pct", 15)

    ticker = holding.get("ticker", "")
    reasons = []

    # Concentration check
    position_pct = holding.get("position_pct")
    if position_pct is not None and position_pct > max_position_pct:
        reasons.append(
            f"Position {position_pct:.1f}% exceeds max {max_position_pct}%"
        )

    # Valuation stretch check
    if valuation and not valuation.get("insufficient_data"):
        # Use implied_cagr — if CAGR is very negative, valuation is stretched
        cagr = valuation.get("implied_cagr", 0)
        if cagr < 0:
            reasons.append(
                f"Negative implied CAGR ({cagr:.1f}%): overvalued at current price"
            )

        # Check margin of safety — if negative, currently above target
        mos = valuation.get("margin_of_safety", 0)
        if mos < -20:
            reasons.append(
                f"Trading {abs(mos):.0f}% above target price (${valuation.get('target_price', 0):,.0f})"
            )

        # If we have P/E data (enriched by main.py), flag extreme multiples
        pe_current = valuation.get("pe_trailing") or valuation.get("pe_forward")
        if pe_current is not None and pe_current > 80:
            reasons.append(f"Extreme P/E: {pe_current:.1f}")

    # Thesis check
    thesis_status = holding.get("thesis_status", "intact")
    if thesis_status == "invalidated":
        reasons.append("Thesis INVALIDATED")
    elif thesis_status == "weakening":
        # Weakening alone is not enough — need to check duration
        notes = holding.get("notes", "") or ""
        if "weakening" in notes.lower() and "quarter" in notes.lower():
            reasons.append("Thesis weakening for multiple quarters")

    if reasons:
        return True, f"{ticker}: " + "; ".join(reasons)

    return False, ""


def should_add(
    conviction_entry: dict,
    valuation: dict,
    config: dict,
) -> tuple[bool, str]:
    """Check if a conviction list name should be added to portfolio.

    Criteria:
        - On conviction list >= conviction_promotion_weeks (default 3)
        - Passes 25% CAGR gate
        - Has >= min_evidence_sources (default 3)

    Args:
        conviction_entry: Conviction list entry from memory.
        valuation: Valuation dict from valuation_engine.
        config: Advisor config dict.

    Returns:
        Tuple of (should_add, reason).
    """
    strategy = config.get("strategy", {})
    promotion_weeks = strategy.get("conviction_promotion_weeks", 3)
    min_cagr = strategy.get("min_cagr_pct", 25)
    min_mos = strategy.get("min_margin_of_safety_pct", 15)
    min_evidence = strategy.get("min_evidence_sources", 3)

    ticker = conviction_entry.get("ticker", "")
    weeks_on_list = conviction_entry.get("weeks_on_list", 0)
    conviction = conviction_entry.get("conviction", "low")

    # Time check
    if weeks_on_list < promotion_weeks:
        return False, (
            f"{ticker}: only {weeks_on_list} weeks on list "
            f"(need {promotion_weeks})"
        )

    # CAGR gate check
    passes_gate, gate_reason = passes_investment_gate(
        valuation, min_cagr=min_cagr, min_mos=min_mos,
    )
    if not passes_gate:
        return False, f"{ticker}: {gate_reason}"

    # Conviction level check — need at least medium
    if conviction == "low":
        return False, f"{ticker}: conviction too low ({conviction})"

    # Count evidence from pros (each PASS line is one source)
    pros = conviction_entry.get("pros", [])
    evidence_count = sum(1 for p in pros if isinstance(p, str) and "PASS" in p)
    if evidence_count < min_evidence:
        return False, (
            f"{ticker}: only {evidence_count}/{min_evidence} evidence sources"
        )

    cagr = valuation.get("implied_cagr", 0)
    mos = valuation.get("margin_of_safety", 0)
    return True, (
        f"{ticker}: {weeks_on_list} weeks on list, conviction={conviction}, "
        f"CAGR={cagr:.1f}%, MoS={mos:.1f}%, evidence={evidence_count}/5"
    )


def generate_strategy(
    holdings_reports: list[dict],
    macro_theses: list[dict],
    valuation_data: dict,
    config: dict,
) -> dict:
    """Generate portfolio strategy recommendations.

    CRITICAL: Defaults to "no action". Only recommends changes when
    evidence strongly warrants it.

    Args:
        holdings_reports: List of holding dicts enriched with current data
            (price, position_pct, thesis_status, etc.).
        macro_theses: Active macro theses with status.
        valuation_data: Dict mapping ticker -> valuation from valuation_engine.
        config: Advisor config dict.

    Returns:
        Dict with actions, flags, and summary.
    """
    actions = []
    new_flags = []

    existing_flags = memory.get_active_flags()
    existing_flag_keys = {
        (f["ticker"], f["flag_type"]) for f in existing_flags
    }

    # --- Check existing holdings for trim signals ---
    for holding in holdings_reports:
        ticker = holding.get("ticker", "")
        val = valuation_data.get(ticker, {})

        trim, trim_reason = should_trim(holding, val, config)
        if trim:
            actions.append({
                "ticker": ticker,
                "action": "trim",
                "reason": trim_reason,
                "urgency": _assess_urgency(holding, val),
            })

            # Flag it if not already flagged
            flag_key = (ticker, "consider_trim")
            if flag_key not in existing_flag_keys:
                memory.add_flag(ticker, "consider_trim", trim_reason)
                new_flags.append({
                    "ticker": ticker,
                    "flag_type": "consider_trim",
                    "description": trim_reason,
                })
                existing_flag_keys.add(flag_key)
        else:
            # Check for watch-level concerns
            thesis_status = holding.get("thesis_status", "intact")
            if thesis_status == "weakening":
                flag_key = (ticker, "watch_thesis")
                if flag_key not in existing_flag_keys:
                    desc = f"{ticker}: thesis weakening, monitoring"
                    memory.add_flag(ticker, "watch_thesis", desc)
                    new_flags.append({
                        "ticker": ticker,
                        "flag_type": "watch_thesis",
                        "description": desc,
                    })
                    existing_flag_keys.add(flag_key)

    # --- Check conviction list for add signals ---
    conviction_list = memory.get_conviction_list(active_only=True)
    for entry in conviction_list:
        ticker = entry.get("ticker", "")
        val = valuation_data.get(ticker, {})

        add, add_reason = should_add(entry, val, config)
        if add:
            actions.append({
                "ticker": ticker,
                "action": "add",
                "reason": add_reason,
                "urgency": "medium",
            })

            flag_key = (ticker, "consider_add")
            if flag_key not in existing_flag_keys:
                memory.add_flag(ticker, "consider_add", add_reason)
                new_flags.append({
                    "ticker": ticker,
                    "flag_type": "consider_add",
                    "description": add_reason,
                })
                existing_flag_keys.add(flag_key)

    # --- Check macro theses for portfolio-level flags ---
    for thesis in macro_theses:
        status = thesis.get("status", "intact")
        if status in ("weakening", "invalidated"):
            affected = thesis.get("affected_tickers", [])
            for ticker in affected:
                flag_key = (ticker, "macro_headwind")
                if flag_key not in existing_flag_keys:
                    desc = (
                        f"{ticker}: macro thesis '{thesis.get('title', '')}' "
                        f"is {status}"
                    )
                    memory.add_flag(
                        ticker, "macro_headwind", desc,
                        trigger_condition=f"thesis status: {status}",
                    )
                    new_flags.append({
                        "ticker": ticker,
                        "flag_type": "macro_headwind",
                        "description": desc,
                    })
                    existing_flag_keys.add(flag_key)

    # --- Build summary ---
    if not actions:
        summary = "NO CHANGES RECOMMENDED TODAY. All holdings theses intact."
    else:
        add_count = sum(1 for a in actions if a["action"] == "add")
        trim_count = sum(1 for a in actions if a["action"] == "trim")
        parts = []
        if add_count:
            parts.append(f"{add_count} potential add(s)")
        if trim_count:
            parts.append(f"{trim_count} potential trim(s)")
        summary = f"Strategy review: {', '.join(parts)}. See details below."

    result = {
        "actions": actions,
        "flags": new_flags,
        "existing_flags": existing_flags,
        "summary": summary,
    }

    log.info(
        "Strategy: %d actions, %d new flags, summary=%s",
        len(actions), len(new_flags), summary,
    )
    return result


def _assess_urgency(holding: dict, valuation: dict) -> str:
    """Assess urgency of a trim recommendation."""
    thesis_status = holding.get("thesis_status", "intact")

    if thesis_status == "invalidated":
        return "high"

    position_pct = holding.get("position_pct")
    strategy_max = 15  # default
    if position_pct is not None and position_pct > strategy_max * 1.5:
        return "high"

    cagr = valuation.get("implied_cagr", 0) if valuation else 0
    if cagr < -10:
        return "high"

    return "low"
