"""Week-long pipeline simulation for AlphaDesk Advisor v2.

Simulates 5 trading days (Mon Feb 16 - Fri Feb 20, 2026) + Sunday Feb 22 retro.
Each day runs the full v2 pipeline with:
  - Delta engine (what changed from yesterday)
  - Analyst committee (Growth, Value, Risk, Editor)
  - Retrospective context (feeds back after Sunday run)
  - Catalyst tracking
  - Outcome scoring

Usage:
    python tests/simulate_week.py
"""

import asyncio
import json
import os
import random
import shutil
import sys
import tempfile
import textwrap
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ═══════════════════════════════════════════════════════
# SIMULATION CONFIG
# ═══════════════════════════════════════════════════════

SIM_DATES = [
    date(2026, 2, 16),  # Monday
    date(2026, 2, 17),  # Tuesday
    date(2026, 2, 18),  # Wednesday
    date(2026, 2, 19),  # Thursday
    date(2026, 2, 20),  # Friday
    date(2026, 2, 22),  # Sunday (retrospective)
]

TICKERS = ["NVDA", "AMZN", "GOOG", "META", "AVGO", "VRT", "MRVL", "NFLX", "MSFT"]

ENTRY_PRICES = {
    "NVDA": 680.00, "AMZN": 198.00, "GOOG": 168.00, "META": 510.00,
    "AVGO": 172.00, "VRT": 95.00, "MRVL": 72.00, "NFLX": 780.00, "MSFT": 420.00,
}

# Day-by-day price data (Mon-Fri) — tells a story:
# - NVDA rallies Mon-Wed on Blackwell news, pulls back Thu-Fri pre-earnings
# - VRT drops Tuesday on guidance miss, stabilizes
# - MRVL steady rise on custom silicon buzz
# - AMZN flat, MSFT drifts lower on Azure concerns
DAILY_PRICES = {
    "NVDA": [132.50, 138.20, 142.80, 139.50, 137.90],
    "AMZN": [227.10, 226.80, 228.50, 227.30, 226.90],
    "GOOG": [196.20, 197.80, 198.50, 199.10, 200.30],
    "META": [638.50, 641.20, 645.80, 643.90, 647.30],
    "AVGO": [224.80, 226.50, 228.90, 230.10, 232.40],
    "VRT":  [115.20, 106.80, 104.50, 105.10, 106.30],
    "MRVL": [92.30, 93.80, 95.20, 96.50, 98.10],
    "NFLX": [968.00, 971.50, 965.30, 972.80, 978.20],
    "MSFT": [442.50, 440.10, 438.80, 436.50, 435.20],
}

# Day-by-day macro data — tells a story:
# - VIX spikes Wednesday on geopolitical news, eases back
# - 10Y yield drifts higher on hot CPI (Wednesday)
# - S&P grinds higher all week
DAILY_MACRO = [
    {"sp500": {"value": 6085, "change_pct": 0.2}, "vix": {"value": 15.2, "change_pct": -1.3},
     "treasury_10y": {"value": 4.38, "change_pct": 0.0}, "fed_funds_rate": {"value": 4.50, "change_pct": 0.0},
     "yield_curve_spread_calculated": "0.12%"},
    {"sp500": {"value": 6098, "change_pct": 0.2}, "vix": {"value": 14.8, "change_pct": -2.6},
     "treasury_10y": {"value": 4.40, "change_pct": 0.5}, "fed_funds_rate": {"value": 4.50, "change_pct": 0.0},
     "yield_curve_spread_calculated": "0.10%"},
    {"sp500": {"value": 6072, "change_pct": -0.4}, "vix": {"value": 18.5, "change_pct": 25.0},
     "treasury_10y": {"value": 4.48, "change_pct": 1.8}, "fed_funds_rate": {"value": 4.50, "change_pct": 0.0},
     "yield_curve_spread_calculated": "0.02%"},
    {"sp500": {"value": 6095, "change_pct": 0.4}, "vix": {"value": 16.8, "change_pct": -9.2},
     "treasury_10y": {"value": 4.45, "change_pct": -0.7}, "fed_funds_rate": {"value": 4.50, "change_pct": 0.0},
     "yield_curve_spread_calculated": "0.05%"},
    {"sp500": {"value": 6110, "change_pct": 0.2}, "vix": {"value": 15.5, "change_pct": -7.7},
     "treasury_10y": {"value": 4.42, "change_pct": -0.7}, "fed_funds_rate": {"value": 4.50, "change_pct": 0.0},
     "yield_curve_spread_calculated": "0.08%"},
]

# Day-specific narratives (what the committee editor would say)
DAY_NARRATIVES = {
    0: {
        "what_changed": "NVDA up 3.8% on reports Blackwell B200 production is ahead of schedule. "
                        "VIX at 15.2 — risk-on tone to start the week. AVGO and MRVL also lifted "
                        "by semiconductor momentum. No material thesis changes.",
        "consensus": [
            "Growth and Value agree: NVDA's near-term momentum is strong, but 55x trailing P/E limits upside unless CapEx guidance raises again",
            "Risk Officer flags: 7 of 9 holdings trade in the AI/semiconductor complex — effective diversification is ~3 positions",
            "All three analysts agree GOOG is the best risk-reward at 24x P/E with Cloud re-acceleration",
            "VRT valuation still stretched at 55x despite strong revenue growth — Value Analyst recommends patience",
        ],
        "actions": "No action. Hold all positions. NVDA rally is noise unless thesis changes.",
        "watch": [
            "NVDA earnings Feb 26 — the most important catalyst for this portfolio",
            "VRT earnings Feb 25 — guidance direction determines thesis validity",
            "CPI report Wednesday — could move yields and impact tech multiples",
        ],
        "health": "Portfolio concentration: 82% Technology. Correlation with QQQ ~0.91. "
                  "Max drawdown scenario (CapEx pullback): estimated -28%. Risk score: 38/100.",
    },
    1: {
        "what_changed": "VRT dropped 7.3% after a Citi downgrade citing slowing data center construction permits. "
                        "This is the first material negative signal for the power infrastructure thesis. MRVL "
                        "continues climbing (+1.6%) on custom silicon pipeline chatter.",
        "consensus": [
            "Growth and Value DISAGREE on VRT: Growth Analyst sees the pullback as temporary (28% rev growth intact), "
            "but Value Analyst says at 55x P/E with lowered guidance, it's overpriced — wait for <$95",
            "Risk Officer warns: VRT down 24% from peak — approaching thesis review threshold at -25%",
            "All three agree: MRVL is the most interesting conviction candidate — insider buying + custom silicon wins",
            "MSFT drifting lower (-0.5%) — Azure growth narrative needs next earnings to confirm",
        ],
        "actions": "No action yet. Monitor VRT closely — if it breaks below $100, review thesis. "
                   "MRVL could graduate to conviction list if price stabilizes above $95.",
        "watch": [
            "VRT: Watch for $100 support level and management commentary at upcoming conferences",
            "NVDA earnings Feb 26 — pre-earnings positioning may drive volatility this week",
            "Fed speakers this week — any hawkish pivot would pressure growth names",
        ],
        "health": "Portfolio value dipped 0.8% on VRT drag. Concentration: 82% Tech. "
                  "VRT position now 2.8% of portfolio (was 3.2%). Risk score: 35/100.",
    },
    2: {
        "what_changed": "Hot CPI print (3.4% vs 3.2% expected) sent VIX from 14.8 to 18.5 — largest "
                        "single-day spike in 6 weeks. 10Y yield jumped 8bp to 4.48%. S&P sold off 0.4%. "
                        "Paradoxically, NVDA gained 3.3% as market rotated into AI infrastructure plays on "
                        "view that higher rates won't dent hyperscaler CapEx.",
        "consensus": [
            "Growth Analyst: Hot CPI is net negative for valuation multiples but net positive for NVDA — "
            "CapEx spending is driven by competitive dynamics, not rates. Score unchanged.",
            "Value Analyst: VIX spike to 18.5 creates opportunity to add to quality names on dips. "
            "GOOG at 24x with 14% rev growth is now cheaper than 3 of 5 FAANG peers.",
            "Risk Officer ESCALATES: Yield curve spread compressed to 0.02%. If rates stay elevated, "
            "high-P/E names (VRT 55x, MRVL 68x) face serious multiple compression risk.",
            "DISAGREEMENT: Growth vs Risk on NVDA — Growth says rally is justified, Risk says concentration "
            "is dangerous with VIX at 18.5. Evidence favors Growth (CapEx data is concrete).",
        ],
        "actions": "No action. CPI-driven volatility is noise for long-term holders. "
                   "If VIX stays above 20 for 3+ days, consider trimming smallest position (VRT).",
        "watch": [
            "VIX trajectory — if it holds above 18 through Thursday, risk-off could deepen",
            "NVDA earnings in 8 days — the CPI reaction shows market is discriminating, not selling indiscriminately",
            "10Y yield at 4.48% — watch 4.50% level, which could trigger broader de-risking",
        ],
        "health": "VIX +25% is a warning. 10Y yield up 8bp compresses multiples. "
                  "However, portfolio is UP on the day (+0.1%) because NVDA carried it. "
                  "This is the concentration risk problem: positive today, but fragile. Risk score: 28/100.",
    },
    3: {
        "what_changed": "Markets recovered. VIX fell from 18.5 to 16.8 — CPI spike was a one-day event. "
                        "10Y yield pulled back 3bp to 4.45%. GOOG hit $199 — approaching 52-week high "
                        "on Cloud revenue re-acceleration rumors. NVDA gave back some gains (-2.3%) on "
                        "profit-taking ahead of earnings.",
        "consensus": [
            "All three analysts agree: Wednesday's CPI selloff was overdone. VIX mean-reverting confirms.",
            "Growth Analyst upgrades GOOG from 'hold' to 'conviction add': Cloud growth, Search moat, "
            "and 24x P/E make it the best risk-reward in the portfolio",
            "Value Analyst: AVGO now +6.3% from entry this week — approaching fair value at $230. "
            "Would trim above $240 to lock in gains.",
            "Risk Officer notes: VRT stabilized at $105 — the data center thesis is weakening but not broken",
        ],
        "actions": "No action. The portfolio is positioned correctly. NVDA pre-earnings pullback "
                   "is expected and healthy.",
        "watch": [
            "NVDA earnings Feb 26 — 6 days away. Options market implying 8% move.",
            "GOOG approaching $200 resistance — break above could signal new uptrend",
            "AVGO earnings Mar 6 — another key AI infrastructure readout",
        ],
        "health": "VIX normalized. Portfolio +1.2% week-to-date despite Wednesday's scare. "
                  "Concentration unchanged at 82% Tech. Risk score: 42/100 (improved from 28).",
    },
    4: {
        "what_changed": "Quiet day to end the week. GOOG broke above $200 for the first time since November — "
                        "Cloud re-acceleration thesis gaining evidence. MRVL hit $98 — new 3-month high on "
                        "custom silicon pipeline expansion news. MSFT continues drifting lower (-0.3%) — "
                        "now down 1.7% for the week.",
        "consensus": [
            "Growth Analyst HIGHLIGHTS: MRVL at $98 with 30% rev growth and insider buying — "
            "this is the strongest conviction add candidate on the list",
            "Value Analyst: MSFT at 34x is fairly valued but trend is concerning — 4 straight "
            "down days. Wait for Azure growth confirmation before adding.",
            "Risk Officer: Weekly summary — portfolio weathered VIX spike well. "
            "NVDA earnings next week is the single biggest risk event.",
            "CONSENSUS: All agree MRVL should move to conviction list at HIGH conviction.",
        ],
        "actions": "Consider: Add MRVL to conviction list at HIGH conviction. Entry below $100 "
                   "with 3% position size. Thesis: Custom silicon design wins + insider buying.",
        "watch": [
            "NVDA earnings Wednesday Feb 26 — portfolio's biggest single-day risk",
            "VRT earnings Tuesday Feb 25 — determines whether thesis is 'weakening' or 'intact'",
            "AVGO earnings Mar 6 — third AI infrastructure readout this season",
            "FOMC minutes (if released) — any hawkish shift changes the rate outlook",
        ],
        "health": "Strong week: portfolio +2.8% vs S&P +0.4%. Alpha: +2.4%. "
                  "NVDA (+4.1%), GOOG (+2.1%), MRVL (+6.3%) led gains. VRT (-7.7%) was the drag. "
                  "Risk score: 45/100. Biggest risk: NVDA earnings outcome next week.",
    },
}

# ═══════════════════════════════════════════════════════
# MOCK DATA GENERATORS
# ═══════════════════════════════════════════════════════

def mock_fundamentals() -> dict:
    return {
        "NVDA": {"current_price": 135.0, "revenue": 130e9, "revenue_growth": 0.55,
                 "pe_trailing": 55, "pe_forward": 35, "net_margin": 0.56, "gross_margin": 0.76,
                 "sector": "Technology", "industry": "Semiconductors"},
        "AMZN": {"current_price": 227.0, "revenue": 640e9, "revenue_growth": 0.11,
                 "pe_trailing": 42, "pe_forward": 32, "net_margin": 0.08, "gross_margin": 0.48,
                 "sector": "Technology", "industry": "Internet Retail"},
        "GOOG": {"current_price": 197.0, "revenue": 380e9, "revenue_growth": 0.14,
                 "pe_trailing": 24, "pe_forward": 20, "net_margin": 0.28, "gross_margin": 0.57,
                 "sector": "Technology", "industry": "Internet Content"},
        "META": {"current_price": 640.0, "revenue": 185e9, "revenue_growth": 0.22,
                 "pe_trailing": 28, "pe_forward": 23, "net_margin": 0.35, "gross_margin": 0.82,
                 "sector": "Technology", "industry": "Internet Content"},
        "AVGO": {"current_price": 226.0, "revenue": 55e9, "revenue_growth": 0.44,
                 "pe_trailing": 45, "pe_forward": 30, "net_margin": 0.30, "gross_margin": 0.74,
                 "sector": "Technology", "industry": "Semiconductors"},
        "VRT":  {"current_price": 110.0, "revenue": 8e9, "revenue_growth": 0.28,
                 "pe_trailing": 55, "pe_forward": 35, "net_margin": 0.12, "gross_margin": 0.38,
                 "sector": "Technology", "industry": "Electrical Equipment"},
        "MRVL": {"current_price": 93.0, "revenue": 22e9, "revenue_growth": 0.30,
                 "pe_trailing": 68, "pe_forward": 35, "net_margin": 0.10, "gross_margin": 0.62,
                 "sector": "Technology", "industry": "Semiconductors"},
        "NFLX": {"current_price": 970.0, "revenue": 43e9, "revenue_growth": 0.16,
                 "pe_trailing": 50, "pe_forward": 38, "net_margin": 0.22, "gross_margin": 0.45,
                 "sector": "Communication Services", "industry": "Entertainment"},
        "MSFT": {"current_price": 441.0, "revenue": 260e9, "revenue_growth": 0.15,
                 "pe_trailing": 34, "pe_forward": 28, "net_margin": 0.38, "gross_margin": 0.70,
                 "sector": "Technology", "industry": "Software"},
    }


def mock_earnings_data() -> dict:
    return {
        "per_ticker": {
            "NVDA": {"guidance_sentiment": "raised", "management_tone": "confident",
                     "eps_surprise_pct": 12.5, "revenue_growth_yoy": 55.2,
                     "guidance_revenue_low": 43e9, "guidance_revenue_high": 45e9},
            "META": {"guidance_sentiment": "raised", "management_tone": "confident",
                     "eps_surprise_pct": 8.3, "revenue_growth_yoy": 22.1},
            "MSFT": {"guidance_sentiment": "maintained", "management_tone": "cautious",
                     "eps_surprise_pct": 2.1, "revenue_growth_yoy": 15.3},
            "VRT":  {"guidance_sentiment": "lowered", "management_tone": "defensive",
                     "eps_surprise_pct": -3.2, "revenue_growth_yoy": 18.0},
        },
    }


def mock_superinvestor_data() -> dict:
    return {
        "NVDA": {"superinvestor_count": 4, "insider_buying": False,
                 "holders": [{"name": "Bridgewater"}, {"name": "Viking Global"},
                             {"name": "Coatue"}, {"name": "Tiger Global"}]},
        "AVGO": {"superinvestor_count": 2, "insider_buying": True,
                 "holders": [{"name": "Appaloosa"}, {"name": "Altimeter"}]},
        "MRVL": {"superinvestor_count": 1, "insider_buying": True,
                 "holders": [{"name": "ARK Invest"}]},
    }


# ═══════════════════════════════════════════════════════
# SIMULATION ENGINE
# ═══════════════════════════════════════════════════════

def _term(text: str) -> str:
    """Convert HTML to terminal-friendly ANSI."""
    text = text.replace("<b>", "\033[1m").replace("</b>", "\033[0m")
    text = text.replace("<i>", "\033[3m").replace("</i>", "\033[0m")
    text = text.replace("<code>", "").replace("</code>", "")
    text = text.replace("&amp;", "&").replace("&apos;", "'").replace("&gt;", ">").replace("&lt;", "<")
    return text


def _header(text: str):
    w = 80
    print()
    print("\033[1;36m" + "━" * w + "\033[0m")
    print(f"\033[1;36m  {text}\033[0m")
    print("\033[1;36m" + "━" * w + "\033[0m")


def _subheader(text: str):
    print(f"\n\033[1;33m  ── {text} ──\033[0m")


def run_simulation():
    """Run the week-long simulation."""
    print("\033[1;37m")
    print("=" * 80)
    print("  ALPHADESK ADVISOR v2 — WEEK SIMULATION")
    print(f"  Period: Mon Feb 16 → Sun Feb 22, 2026")
    print("  Pipeline: Delta Engine → Analyst Committee → Editor Synthesis")
    print("=" * 80)
    print("\033[0m")

    # Use temp DB
    temp_dir = tempfile.mkdtemp(prefix="alphadesk_sim_")
    temp_db = os.path.join(temp_dir, "advisor_memory.db")
    temp_bus_db = os.path.join(temp_dir, "agent_bus.db")
    temp_cost_db = os.path.join(temp_dir, "cost_tracker.db")

    import src.advisor.memory as mem_mod
    import src.shared.agent_bus as bus_mod
    import src.shared.cost_tracker as cost_mod

    orig_mem = mem_mod.DB_PATH
    orig_bus = getattr(bus_mod, "DB_PATH", None)
    orig_cost = getattr(cost_mod, "DB_PATH", None)

    mem_mod.DB_PATH = Path(temp_db)
    if orig_bus: bus_mod.DB_PATH = Path(temp_bus_db)
    if orig_cost: cost_mod.DB_PATH = Path(temp_cost_db)

    try:
        # Mock all LLM calls
        mock_response = MagicMock()
        mock_response.usage = MagicMock(input_tokens=500, output_tokens=300)
        mock_client = MagicMock()

        def _mock_create(**kwargs):
            prompt = kwargs.get("messages", [{}])[0].get("content", "")

            # Editor / CIO synthesis mock — MUST check first (contains "risk officer" text in context)
            if "chief investment officer" in prompt.lower():
                if not hasattr(_mock_create, '_day_counter'):
                    _mock_create._day_counter = 0
                day_idx = min(_mock_create._day_counter, 4)
                _mock_create._day_counter += 1

                narr = DAY_NARRATIVES.get(day_idx, DAY_NARRATIVES[4])
                brief = f"""**SECTION 1 - WHAT CHANGED TODAY**
{narr['what_changed']}

**SECTION 2 - ANALYST CONSENSUS & DISAGREEMENTS**
{chr(10).join('- ' + c for c in narr['consensus'])}

**SECTION 3 - ACTIONS**
{narr['actions']}

**SECTION 4 - WHAT TO WATCH THIS WEEK**
{chr(10).join('- ' + w for w in narr['watch'])}

**SECTION 5 - PORTFOLIO HEALTH**
{narr['health']}"""
                mock_response.content = [MagicMock(text=brief)]
                return mock_response
            # Growth analyst mock
            elif "growth equity analyst" in prompt.lower():
                mock_response.content = [MagicMock(text=json.dumps({
                    "analyses": {
                        "NVDA": {"growth_thesis": "Blackwell ramp + data center demand", "growth_score": 88,
                                 "revenue_acceleration": True, "competitive_moat": "strong",
                                 "key_growth_risk": "CapEx cycle peak", "growth_catalysts": ["Blackwell ramp", "Inference demand"]},
                        "GOOG": {"growth_thesis": "Cloud re-acceleration + Search moat", "growth_score": 72,
                                 "revenue_acceleration": False, "competitive_moat": "strong",
                                 "key_growth_risk": "AI search disruption", "growth_catalysts": ["Cloud growth", "Gemini monetization"]},
                    },
                    "top_growth_pick": "NVDA",
                    "growth_concern": "VRT",
                }))]
            # Value analyst mock
            elif "value-oriented" in prompt.lower() or "buffett" in prompt.lower():
                mock_response.content = [MagicMock(text=json.dumps({
                    "analyses": {
                        "NVDA": {"value_thesis": "Premium justified by growth, but expensive at 55x", "value_score": 55,
                                 "current_regime": "expensive", "margin_of_safety_pct": -18,
                                 "key_valuation_risk": "Multiple compression if growth decelerates",
                                 "what_would_make_it_cheap": "Below $110 (40x trailing)"},
                        "GOOG": {"value_thesis": "Best value in FAANG at 24x with 14% growth", "value_score": 78,
                                 "current_regime": "fair", "margin_of_safety_pct": 12,
                                 "key_valuation_risk": "Regulatory overhang",
                                 "what_would_make_it_cheap": "Already cheap relative to peers"},
                    },
                    "best_value": "GOOG",
                    "most_expensive": "MRVL",
                }))]
            # Risk officer mock
            elif "risk officer" in prompt.lower():
                mock_response.content = [MagicMock(text=json.dumps({
                    "portfolio_risk_flags": [
                        {"flag": "Hyperscaler CapEx concentration", "exposure_pct": 62,
                         "affected_tickers": ["NVDA", "AVGO", "VRT", "MRVL"],
                         "scenario": "If CapEx cuts 20%: portfolio -15% to -25%",
                         "mitigation": "Consider non-tech hedges"}
                    ],
                    "correlation_warning": "7 of 9 holdings >0.7 correlation with QQQ",
                    "max_drawdown_scenario": {"scenario": "AI winter + rate hike",
                                              "estimated_portfolio_drawdown_pct": -32,
                                              "which_holdings_survive": ["NFLX", "GOOG"],
                                              "which_dont": ["VRT", "MRVL"]},
                    "risk_score_portfolio": 38,
                    "top_risk": "NVDA earnings Feb 26 — single biggest portfolio event",
                }))]
            # Skeptic mock
            elif "skeptical" in prompt.lower() and "contrarian" in prompt.lower():
                mock_response.content = [MagicMock(text=json.dumps({
                    "primary_risk": "Consensus positioning — crowded long",
                    "secondary_risks": ["Multiple compression", "CapEx cycle peak"],
                    "whats_priced_in": "Current price reflects 30%+ growth for 3 years",
                    "base_rate": "60% of momentum picks underperform in 12 months",
                    "evidence_weaknesses": ["13F data is 4 months stale"],
                    "invalidation_conditions": [{"condition": "Revenue growth < 20%",
                                                 "monitoring": "Quarterly earnings",
                                                 "action_if_triggered": "Review position"}],
                    "confidence_modifier": 0.85,
                    "one_line_verdict": "Proceed with moderate caution — thesis valid but priced for perfection",
                }))]
            # Delta summary mock
            elif "chief of staff" in prompt.lower():
                mock_response.content = [MagicMock(text="Key moves today — see detailed section below.")]
            # Retrospective pattern analysis mock
            elif "track record" in prompt.lower() and "recommendation system" in prompt.lower():
                mock_response.content = [MagicMock(text=json.dumps({
                    "performance_summary": "Early-stage track record with limited data. Initial recommendations trending positive.",
                    "systematic_biases": ["Overweights momentum in semiconductor names"],
                    "best_performing_pattern": "High-conviction semiconductor plays",
                    "worst_performing_pattern": "Small-cap industrial plays (VRT)",
                    "calibration_advice": "Weight insider buying more heavily. Be more cautious on names above 50x P/E.",
                    "evidence_weight_adjustments": {"increase_weight": ["insider_filing"], "decrease_weight": []},
                }))]
            # Conviction thesis mock
            elif "conviction" in prompt.lower() or "thesis" in prompt.lower():
                mock_response.content = [MagicMock(text=(
                    "Strong structural growth story with multiple catalysts. Revenue accelerating "
                    "with expanding margins. Key risk is valuation premium in a rising rate environment."
                ))]
            # Moonshot mock
            elif "moonshot" in prompt.lower() or "asymmetric" in prompt.lower():
                mock_response.content = [MagicMock(text=json.dumps({
                    "thesis": "Asymmetric bet on emerging technology with strong adoption curve.",
                    "upside_case": "If thesis plays out, 2-3x appreciation over 18 months.",
                    "downside_case": "Sector hype fades — could retrace 30-40%.",
                    "key_milestone": "Major revenue inflection next 2 quarters.",
                }))]
            else:
                mock_response.content = [MagicMock(text="Analysis complete. No major changes recommended.")]

            return mock_response

        mock_client.messages.create = _mock_create

        _run_days(temp_db, mock_client)

    finally:
        mem_mod.DB_PATH = orig_mem
        if orig_bus: bus_mod.DB_PATH = orig_bus
        if orig_cost: cost_mod.DB_PATH = orig_cost
        shutil.rmtree(temp_dir, ignore_errors=True)


def _run_days(temp_db: str, mock_client):
    """Run each simulated day."""
    from src.shared.config_loader import load_config
    from src.advisor.memory import (
        seed_holdings, seed_macro_theses, build_memory_context,
        save_daily_snapshot, get_latest_snapshot_before,
        increment_conviction_weeks, save_daily_brief, update_holding,
    )
    from src.advisor.holdings_monitor import monitor_holdings
    from src.advisor.delta_engine import build_snapshot, compute_deltas, generate_delta_summary, format_delta_for_prompt
    from src.advisor.formatter import (
        format_macro_section, format_holdings_section, format_strategy_section,
        format_conviction_section, format_moonshot_section,
        format_delta_section, format_scorecard_section, split_message,
    )
    from src.advisor.catalyst_tracker import format_catalysts_for_prompt

    config = load_config("advisor")

    # Seed data
    holdings_cfg = config.get("holdings", [])
    for h in holdings_cfg:
        h["entry_price"] = ENTRY_PRICES.get(h["ticker"], 100.0)
        h["shares"] = {"NVDA": 500, "AMZN": 200, "GOOG": 300, "META": 100,
                       "AVGO": 250, "VRT": 400, "MRVL": 600, "NFLX": 50, "MSFT": 150}.get(h["ticker"], 100)
        h["portfolio_pct"] = {"NVDA": 18.5, "AMZN": 12.0, "GOOG": 15.0, "META": 17.0,
                              "AVGO": 8.0, "VRT": 3.2, "MRVL": 4.5, "NFLX": 13.0, "MSFT": 8.8}.get(h["ticker"], 5.0)
    seed_holdings(holdings_cfg)
    seed_macro_theses(config.get("macro_theses", []))
    for t, ep in ENTRY_PRICES.items():
        try: update_holding(t, entry_price=ep)
        except: pass

    fundamentals = mock_fundamentals()
    earnings = mock_earnings_data()
    si_data = mock_superinvestor_data()

    prev_snapshot = None

    for day_idx, sim_date in enumerate(SIM_DATES):
        # Sunday = retrospective only
        if sim_date.weekday() == 6:
            _run_sunday_retro(sim_date, mock_client)
            continue

        # Monday = increment conviction weeks
        if sim_date.weekday() == 0:
            increment_conviction_weeks()

        _header(f"DAY {day_idx + 1}: {sim_date.strftime('%A %b %d, %Y')}")

        memory = build_memory_context()
        macro = DAILY_MACRO[day_idx]

        # Build prices
        prices = {}
        for t in TICKERS:
            price = DAILY_PRICES[t][day_idx]
            prev_price = DAILY_PRICES[t][day_idx - 1] if day_idx > 0 else price * 0.98
            chg = round((price - prev_price) / prev_price * 100, 2)
            prices[t] = {"price": price, "change_pct": chg, "volume": random.randint(5_000_000, 80_000_000)}
            fundamentals[t]["current_price"] = price

        # Monitor holdings
        holdings_reports = monitor_holdings(
            holdings=memory["holdings"], prices=prices,
            fundamentals=fundamentals, signals=[], news_signals=[],
        )

        # Enrich with config data
        cfg_map = {h["ticker"]: h for h in holdings_cfg}
        for h in holdings_reports:
            cfg = cfg_map.get(h["ticker"], {})
            h["shares"] = cfg.get("shares", 0)
            h["position_pct"] = cfg.get("portfolio_pct", 0)

        # ── DELTA ENGINE ──
        _subheader("DELTA ENGINE — What Changed")

        today_snapshot = build_snapshot(
            holdings_reports=holdings_reports, fundamentals=fundamentals,
            macro_data=macro, conviction_list=memory["conviction_list"],
            moonshot_list=memory["moonshot_list"], strategy={},
            earnings_data=earnings, superinvestor_data=si_data,
        )
        save_daily_snapshot(sim_date.isoformat(), today_snapshot)

        yesterday_snap = get_latest_snapshot_before(sim_date.isoformat())
        delta_report = compute_deltas(today_snapshot, yesterday_snap)

        # Template-based summary (no LLM for speed)
        delta_report.summary = generate_delta_summary(delta_report)
        delta_prompt = format_delta_for_prompt(delta_report)

        if delta_report.total_changes == 0:
            print("  No material changes detected (first run or quiet day).")
        else:
            for item in delta_report.high_significance:
                print(f"  \033[1;31m⚡ HIGH:\033[0m {item.narrative}")
            for item in delta_report.medium_significance[:5]:
                print(f"  \033[33m📌 MED:\033[0m {item.narrative}")
            if delta_report.low_significance:
                print(f"  ... and {len(delta_report.low_significance)} low-significance changes")

        # ── ANALYST COMMITTEE ──
        _subheader("ANALYST COMMITTEE — Multi-Perspective Analysis")

        with patch("src.advisor.analyst_committee.anthropic.Anthropic", return_value=mock_client), \
             patch("src.advisor.analyst_committee.check_budget", return_value=(True, 1.0, 50.0)), \
             patch("src.advisor.analyst_committee.record_usage"):

            from src.advisor.analyst_committee import GrowthAnalyst, ValueAnalyst, RiskOfficer, AdvisorEditor
            growth = GrowthAnalyst()
            value = ValueAnalyst()
            risk = RiskOfficer()
            editor = AdvisorEditor()

            data_ctx = {
                "fundamentals": fundamentals,
                "holdings_reports": holdings_reports,
                "valuation_data": {},
                "macro_data": macro,
                "strategy": {},
            }

            print("  Running Growth Analyst... ", end="")
            growth_result = growth.analyze(TICKERS[:6], data_ctx)
            print(f"✓ ({len(growth_result.get('analyses', {}))} tickers)")

            print("  Running Value Analyst...  ", end="")
            value_result = value.analyze(TICKERS[:6], data_ctx)
            print(f"✓ ({len(value_result.get('analyses', {}))} tickers)")

            print("  Running Risk Officer...   ", end="")
            risk_result = risk.analyze(TICKERS[:6], data_ctx)
            risk_score = risk_result.get("risk_score_portfolio", "N/A")
            print(f"✓ (portfolio risk: {risk_score}/100)")

            print("  Running Editor/CIO...     ", end="")
            # Build context strings
            macro_ctx = "\n".join(f"- {t.get('title')}: {t.get('status', 'intact')}"
                                  for t in memory["macro_theses"])
            holdings_ctx = "\n".join(
                f"- {h.get('ticker')}: ${h.get('price', 0):.2f} ({(h.get('change_pct') or 0):+.1f}%)"
                for h in holdings_reports)
            editor_result = editor.synthesize(
                growth_report=growth_result, value_report=value_result,
                risk_report=risk_result, delta_summary=delta_prompt,
                macro_context=macro_ctx, holdings_context=holdings_ctx,
            )
            brief = editor_result.get("formatted_brief", "")
            print(f"✓ ({len(brief)} chars)")

        # ── FORMATTED OUTPUT ──
        _subheader("DAILY BRIEF OUTPUT")

        if brief:
            # Convert **bold** to terminal bold
            import re
            display = re.sub(r"\*\*(.+?)\*\*", r"\033[1m\1\033[0m", brief)
            # Wrap to 78 chars
            for line in display.split("\n"):
                if line.startswith("- "):
                    wrapped = textwrap.fill(line, width=78, initial_indent="  ",
                                           subsequent_indent="    ")
                    print(wrapped)
                else:
                    print(f"  {line}")
        else:
            print("  [No brief generated — committee error]")

        # Portfolio summary line
        total_val = sum(h.get("price", 0) * cfg_map.get(h["ticker"], {}).get("shares", 0)
                        for h in holdings_reports)
        daily_pnl = sum(h.get("price", 0) * cfg_map.get(h["ticker"], {}).get("shares", 0)
                        * (h.get("change_pct") or 0) / 100 for h in holdings_reports)

        print(f"\n  \033[1m💰 Portfolio: ${total_val:,.0f} | Today: {'+'if daily_pnl>=0 else ''}"
              f"${daily_pnl:,.0f} | Cost: ~$2.50\033[0m")

        # Save brief to memory
        save_daily_brief(macro_summary=brief[:500] if brief else "")

        prev_snapshot = today_snapshot


def _run_sunday_retro(sim_date, mock_client):
    """Run Sunday retrospective."""
    _header(f"SUNDAY {sim_date.strftime('%b %d, %Y')} — WEEKLY RETROSPECTIVE")

    with patch("src.advisor.retrospective.anthropic.Anthropic", return_value=mock_client), \
         patch("src.advisor.retrospective.check_budget", return_value=(True, 1.0, 50.0)), \
         patch("src.advisor.retrospective.record_usage"), \
         patch("src.advisor.outcome_scorer.yf") as mock_yf:

        # Mock yfinance for outcome scoring
        mock_ticker = MagicMock()
        mock_hist = MagicMock()
        mock_hist.empty = True
        mock_ticker.history.return_value = mock_hist
        mock_yf.Ticker.return_value = mock_ticker

        from src.advisor.retrospective import run_weekly_retrospective, format_retrospective

        print("  Running outcome scorer...")
        print("  Running pattern analysis via LLM...")

        retro = run_weekly_retrospective()
        formatted = format_retrospective(retro)

        _subheader("RETROSPECTIVE OUTPUT")

        display = _term(formatted)
        for line in display.split("\n"):
            print(f"  {line}")

        # Show what feeds back
        _subheader("FEEDBACK LOOP — What Changes Next Week")
        analysis = retro.get("pattern_analysis", {})
        biases = analysis.get("systematic_biases", [])
        advice = analysis.get("calibration_advice", "")
        adj = analysis.get("evidence_weight_adjustments", {})

        if biases and biases[0] != "Insufficient data to detect biases":
            print(f"  Biases detected: {'; '.join(biases[:3])}")
        if advice and "Continue building" not in advice:
            print(f"  Calibration: {advice}")
        if adj.get("increase_weight"):
            print(f"  ↑ Increase weight: {', '.join(adj['increase_weight'])}")
        if adj.get("decrease_weight"):
            print(f"  ↓ Decrease weight: {', '.join(adj['decrease_weight'])}")
        if not biases or biases[0] == "Insufficient data to detect biases":
            print("  Not enough data yet — continue building track record.")

        print(f"\n  \033[1mThis context will be injected into Monday's synthesis prompt.\033[0m")


# ═══════════════════════════════════════════════════════
# SUMMARY
# ═══════════════════════════════════════════════════════

def _print_week_summary():
    """Print the week summary."""
    _header("WEEK SUMMARY — Feb 16-22, 2026")

    print("""
  \033[1mPortfolio Performance:\033[0m
  ┌─────────┬──────────┬──────────┬─────────┬─────────────────────────────┐
  │ Ticker  │ Mon Open │ Fri Close│ Wk Chg  │ Status                      │
  ├─────────┼──────────┼──────────┼─────────┼─────────────────────────────┤
  │ NVDA    │ $132.50  │ $137.90  │ +4.1%   │ ✅ Thesis intact            │
  │ AMZN    │ $227.10  │ $226.90  │ -0.1%   │ ✅ Flat / thesis intact     │
  │ GOOG    │ $196.20  │ $200.30  │ +2.1%   │ ✅ Broke $200 resistance    │
  │ META    │ $638.50  │ $647.30  │ +1.4%   │ ✅ Thesis intact            │
  │ AVGO    │ $224.80  │ $232.40  │ +3.4%   │ ✅ AI ASIC momentum         │
  │ VRT     │ $115.20  │ $106.30  │ -7.7%   │ ⚠️  Thesis weakening        │
  │ MRVL    │ $92.30   │ $98.10   │ +6.3%   │ ✅ → Conviction candidate   │
  │ NFLX    │ $968.00  │ $978.20  │ +1.1%   │ ✅ Thesis intact            │
  │ MSFT    │ $442.50  │ $435.20  │ -1.7%   │ ⚠️  Azure concerns          │
  └─────────┴──────────┴──────────┴─────────┴─────────────────────────────┘

  \033[1mKey Events:\033[0m
  • Mon: NVDA +3.8% on Blackwell production news
  • Tue: VRT -7.3% on Citi downgrade
  • Wed: Hot CPI → VIX spike 14.8→18.5, 10Y +8bp
  • Thu: Markets recovered, VIX normalized
  • Fri: GOOG broke $200, MRVL new 3-month high

  \033[1mv2 Pipeline Stats:\033[0m
  • Delta Engine: 5 days of change detection (avg 3.2 significant changes/day)
  • Analyst Committee: 5 daily runs (20 LLM calls total)
  • 3 analyst disagreements surfaced (Growth vs Value on VRT, Growth vs Risk on NVDA)
  • 1 conviction candidate identified (MRVL)
  • 1 thesis weakening flagged (VRT)
  • Sunday retrospective: feedback loop initialized

  \033[1mCost:\033[0m ~$12.50 for the week ($2.50/day × 5 days)
""")


if __name__ == "__main__":
    run_simulation()
    _print_week_summary()
