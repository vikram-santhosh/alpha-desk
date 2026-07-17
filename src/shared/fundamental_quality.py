"""Shared fundamental-quality rubric.

Single source of truth for "is this company actually good, or just cheap-
looking/hyped" — consumed by both src/alpha_scout/screener.py (the Alpha
Scout composite screen) and src/score_engine/sensors/valuation.py (the
deterministic score engine that powers /api/ideas/fast and the /api/ideas/
today fallback). Before this module existed the two scorers could drift:
the screener's quality rubric caught expensive, thin-margin names (the AFRM
profile) but the score engine's valuation sensor scored purely off a DCF-
style implied CAGR/margin-of-safety that has no opinion on valuation
multiples or margin quality, so the same red flags could resurface via the
score-engine-backed fallback path even after the screener was fixed. Update
both score_fundamental_quality and explain_fundamental_quality together —
they must stay in lockstep so the debug UI's factors always explain the
score it's attached to.
"""
from __future__ import annotations

from typing import Any


def score_fundamental_quality(fundamentals: dict[str, Any]) -> int:
    """Score a candidate on fundamental *quality* (0-100).

    Rewards profitable, sensibly-valued growth and penalises the profile that
    previously slipped through as a false positive: a richly-valued, thin-
    margin name that merely happened to be down off its highs. Uses valuation
    signals (EV/EBITDA, analyst implied upside) rather than treating a high
    multiple as nearly free, and does not treat "down from the 52-week high /
    near the low" as a standalone positive (that rewarded value traps).
    Penalties for losses and extreme multiples are real.
    """
    if not fundamentals:
        return 50  # neutral baseline

    score = 40

    # P/E ratio — a very high trailing multiple is a real headwind, not ~free.
    pe = fundamentals.get("pe_trailing")
    if pe is not None:
        if 10 <= pe <= 30:
            score += 15
        elif 0 < pe < 10:
            score += 10
        elif pe <= 50:
            score += 5
        elif pe <= 60:
            score -= 5
        else:  # >60×
            score -= 10

    # EV/EBITDA — absolute valuation richness (cash-flow basis).
    ev_ebitda = fundamentals.get("ev_to_ebitda")
    if isinstance(ev_ebitda, (int, float)) and ev_ebitda > 0:
        if ev_ebitda > 40:
            score -= 15
        elif ev_ebitda > 25:
            score -= 5
        elif ev_ebitda < 15:
            score += 3

    # Revenue growth
    rev_growth = fundamentals.get("revenue_growth")
    if rev_growth is not None:
        if rev_growth > 0:
            score += 15
            if rev_growth > 0.20:
                score += 10
            elif rev_growth > 0.10:
                score += 5
        elif rev_growth < -0.05:
            score -= 10

    # Profitability — reward strong margins, penalise losses (was: no penalty).
    net_margin = fundamentals.get("net_margin")
    if net_margin is not None:
        if net_margin > 0.20:
            score += 15
        elif net_margin > 0.05:
            score += 10
        elif net_margin > 0:
            score += 4
        elif net_margin < -0.10:
            score -= 20
        else:  # marginally negative
            score -= 12

    gross_margin = fundamentals.get("gross_margin")
    if gross_margin is not None:
        if gross_margin > 0.40:
            score += 10
        elif gross_margin < 0.20:
            score -= 10  # low-margin, low-differentiation business (e.g. box assembly)

    # Free cash flow — penalise cash burn (a cheap multiple on negative FCF is a trap).
    free_cashflow = fundamentals.get("free_cashflow")
    if isinstance(free_cashflow, (int, float)) and free_cashflow < 0:
        score -= 10

    # Analyst implied upside — forward-looking sanity check on price vs. targets.
    implied_upside = fundamentals.get("implied_upside_pct")
    if isinstance(implied_upside, (int, float)):
        if implied_upside > 25:
            score += 8
        elif implied_upside > 10:
            score += 4
        elif implied_upside < 0:
            score -= 8
        # 0-10%: no credit (e.g. the street sees little left in the name)

    # 52-week proximity — only a small mean-reversion nudge, never a value-trap reward.
    pct_from_high = fundamentals.get("pct_from_52w_high")
    if pct_from_high is not None and pct_from_high < -15:
        score += 5

    # Market cap
    market_cap = fundamentals.get("market_cap")
    if market_cap is not None and market_cap > 10_000_000_000:
        score += 5

    return max(0, min(100, score))


def explain_fundamental_quality(fundamentals: dict[str, Any]) -> list[str]:
    """Human-readable, signed factors mirroring ``score_fundamental_quality``'s
    rubric. Powers the cockpit's "why was this scored this way?" debug view.
    Kept in lockstep with ``score_fundamental_quality`` — update both together.
    """
    if not fundamentals:
        return ["No fundamental data — neutral baseline (50)"]

    factors: list[str] = []

    pe = fundamentals.get("pe_trailing")
    if pe is not None:
        if 10 <= pe <= 30:
            factors.append(f"+15 P/E {pe:.0f} (reasonable)")
        elif 0 < pe < 10:
            factors.append(f"+10 P/E {pe:.0f} (cheap)")
        elif pe <= 50:
            factors.append(f"+5 P/E {pe:.0f} (full)")
        elif pe <= 60:
            factors.append(f"-5 P/E {pe:.0f} (expensive)")
        else:
            factors.append(f"-10 P/E {pe:.0f} (very expensive)")

    ev = fundamentals.get("ev_to_ebitda")
    if isinstance(ev, (int, float)) and ev > 0:
        if ev > 40:
            factors.append(f"-15 EV/EBITDA {ev:.0f} (richly valued)")
        elif ev > 25:
            factors.append(f"-5 EV/EBITDA {ev:.0f} (elevated)")
        elif ev < 15:
            factors.append(f"+3 EV/EBITDA {ev:.0f} (cheap)")

    rg = fundamentals.get("revenue_growth")
    if rg is not None:
        if rg > 0.20:
            factors.append(f"+25 revenue growth {rg * 100:.0f}% (strong)")
        elif rg > 0.10:
            factors.append(f"+20 revenue growth {rg * 100:.0f}%")
        elif rg > 0:
            factors.append(f"+15 revenue growth {rg * 100:.0f}%")
        elif rg < -0.05:
            factors.append(f"-10 revenue declining {rg * 100:.0f}%")

    nm = fundamentals.get("net_margin")
    if nm is not None:
        if nm > 0.20:
            factors.append(f"+15 net margin {nm * 100:.0f}% (high quality)")
        elif nm > 0.05:
            factors.append(f"+10 net margin {nm * 100:.0f}%")
        elif nm > 0:
            factors.append(f"+4 net margin {nm * 100:.0f}% (thin)")
        elif nm < -0.10:
            factors.append(f"-20 net margin {nm * 100:.0f}% (deep losses)")
        else:
            factors.append(f"-12 net margin {nm * 100:.0f}% (unprofitable)")

    gm = fundamentals.get("gross_margin")
    if gm is not None:
        if gm > 0.40:
            factors.append(f"+10 gross margin {gm * 100:.0f}%")
        elif gm < 0.20:
            factors.append(f"-10 gross margin {gm * 100:.0f}% (low-margin business)")

    fcf = fundamentals.get("free_cashflow")
    if isinstance(fcf, (int, float)) and fcf < 0:
        factors.append("-10 negative free cash flow (cash burn)")

    iu = fundamentals.get("implied_upside_pct")
    if isinstance(iu, (int, float)):
        if iu > 25:
            factors.append(f"+8 analyst upside {iu:.0f}%")
        elif iu > 10:
            factors.append(f"+4 analyst upside {iu:.0f}%")
        elif iu < 0:
            factors.append(f"-8 analyst downside {iu:.0f}%")
        else:
            factors.append(f"±0 analyst upside {iu:.0f}% (little left)")

    ph = fundamentals.get("pct_from_52w_high")
    if ph is not None and ph < -15:
        factors.append(f"+5 off 52w high {ph:.0f}% (mean-reversion)")

    mc = fundamentals.get("market_cap")
    if mc is not None and mc > 10_000_000_000:
        factors.append("+5 large cap (>$10B)")

    return factors or ["No scoring factors triggered"]
