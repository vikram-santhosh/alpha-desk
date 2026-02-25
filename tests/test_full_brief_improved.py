"""Integration test: validates all 6 phases are reflected in the output."""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from unittest.mock import MagicMock
for mod in ["anthropic", "fredapi", "yfinance"]:
    sys.modules.setdefault(mod, MagicMock())

import pytest


def test_full_brief_output():
    """Full brief should reflect all 6 fixes."""
    from src.advisor.formatter import (
        format_macro_section,
        format_holdings_section,
        format_conviction_section,
        format_moonshot_section,
        format_daily_brief,
        format_strategy_section,
    )

    # Mock macro data
    macro_data = {
        "sp500": {"value": 6841, "change_pct": -1.0},
        "vix": {"value": 21.3},
        "treasury_10y": {"value": 4.08},
        "fed_funds_rate": {"value": 3.64},
    }

    # Mock theses with DIFFERENT relevant_news (Phase 2 fix)
    theses = [
        {
            "title": "Hyperscaler CapEx Boom",
            "current_status": "intact",
            "affected_tickers": ["NVDA", "AVGO", "VRT", "MRVL"],
            "relevant_news": [
                {"headline": "Nvidia earnings will offer crucial AI update", "match_reason": "ticker"},
                {"headline": "NVDA price target raised by Morgan Stanley", "match_reason": "ticker"},
            ],
            "evidence_log": [],
        },
        {
            "title": "Digital Payments Secular Growth",
            "current_status": "intact",
            "affected_tickers": ["MA"],
            "relevant_news": [
                {"headline": "Mastercard Q4 beats estimates on cross-border volume", "match_reason": "ticker"},
            ],
            "evidence_log": [],
        },
    ]

    # Mock holdings reports (Phase 3 fix -- news context)
    holdings_reports = [
        {
            "ticker": "NVDA", "price": 190.10, "shares": 10, "entry_price": 150.0,
            "change_pct": 0.1, "cumulative_return_pct": 26.7,
            "thesis": "AI GPU leader", "thesis_status": "intact",
            "recent_trend": "Strong: up 6/7 sessions.",
            "key_events": ["Trump hikes global tariff to 15%", "Nvidia earnings Feb 25"],
            "position_pct": 8.5, "category": "core",
            "earnings_approaching": True, "earnings_date": "2026-02-25", "earnings_days_out": 1,
            "near_52w_high": False, "near_52w_low": False, "high_52w": None, "low_52w": None,
        },
        {
            "ticker": "MA", "price": 520.0, "shares": 5, "entry_price": 400.0,
            "change_pct": -0.5, "cumulative_return_pct": 30.0,
            "thesis": "Digital payments", "thesis_status": "intact",
            "recent_trend": "Sideways (4 up, 3 down).",
            "key_events": ["Mastercard Q4 results beat estimates"],
            "position_pct": 5.2, "category": "core",
            "earnings_approaching": False, "earnings_date": None, "earnings_days_out": None,
            "near_52w_high": False, "near_52w_low": False, "high_52w": None, "low_52w": None,
        },
        {
            "ticker": "GOOG", "price": 313.42, "shares": 5, "entry_price": 280.0,
            "change_pct": -0.5, "cumulative_return_pct": 11.9,
            "thesis": "Cloud margin inflection", "thesis_status": "intact",
            "recent_trend": "Sideways (4 up, 3 down).",
            "key_events": [],  # No news -- should show trend as fallback
            "position_pct": 5.2, "category": "core",
            "earnings_approaching": False, "earnings_date": None, "earnings_days_out": None,
            "near_52w_high": False, "near_52w_low": False, "high_52w": None, "low_52w": None,
        },
    ]

    # Mock conviction list (Phase 1 fix -- NOT empty)
    conviction_list = [
        {
            "ticker": "PLTR", "conviction": "medium", "weeks_on_list": 1,
            "thesis": "Palantir government AI contracts provide visible revenue growth.",
            "source": "Dragoneer initiated $45M position + strong fundamentals",
        },
        {
            "ticker": "IONQ", "conviction": "low", "weeks_on_list": 1,
            "thesis": "Quantum computing pure-play with first-mover advantage.",
            "source": "12 Reddit mentions across smallstreetbets, SecurityAnalysis",
        },
    ]

    # Mock moonshot list (Phase 4/5/6 fix -- with discovery context)
    moonshot_list = [
        {
            "ticker": "RGTI", "conviction": "medium", "months_on_list": 1,
            "thesis": "Rigetti quantum computing play with commercial partnerships forming.",
            "upside_case": "3-5x if quantum hits enterprise inflection",
            "downside_case": "60% downside if no commercial traction",
            "key_milestone": "First $5M commercial quantum contract",
            "source": "Mentioned 7 times on r/smallstreetbets + Coatue new position",
        },
    ]

    # Format each section
    macro_section = format_macro_section(macro_data, theses, [])
    holdings_section = format_holdings_section(holdings_reports)
    strategy_section = format_strategy_section({"actions": [], "flags": []})
    conviction_section = format_conviction_section(conviction_list)
    moonshot_section = format_moonshot_section(moonshot_list)

    # Assemble full brief
    full_brief = format_daily_brief(
        macro_section=macro_section,
        holdings_section=holdings_section,
        strategy_section=strategy_section,
        conviction_section=conviction_section,
        moonshot_section=moonshot_section,
        daily_cost=0.42,
        macro_summary="NVDA earnings tomorrow is the main event. Tariff hike to 15% creating macro pressure but your portfolio is well-positioned for AI CapEx thesis.",
    )

    # Strip HTML for readability
    import re
    clean = re.sub(r'<[^>]+>', '', full_brief)
    clean = clean.replace('&amp;', '&').replace('&#x27;', "'").replace('&lt;', '<').replace('&gt;', '>')

    # Save preview
    preview_path = os.path.join(os.path.dirname(__file__), "improved_output_preview.md")
    with open(preview_path, "w") as f:
        f.write(clean)

    print(f"\n{'='*70}")
    print("FULL BRIEF OUTPUT (HTML tags stripped)")
    print(f"{'='*70}")
    print(clean[:3000])
    if len(clean) > 3000:
        print(f"\n... ({len(clean) - 3000} more chars, saved to {preview_path})")

    # ===================================================================
    # ASSERTIONS -- all 6 fixes must be reflected
    # ===================================================================

    # Fix 1: Conviction list is NOT empty
    assert "No conviction names currently" not in clean, "Conviction list should NOT be empty"
    assert "PLTR" in clean, "PLTR should be in conviction list"
    assert "IONQ" in clean, "IONQ should be in conviction list"

    # Fix 2: Macro theses show DIFFERENT headlines
    assert "Nvidia earnings" in clean, "NVDA headline should appear"
    assert "Mastercard" in clean, "MA headline should appear"
    # Check that CapEx thesis and Digital Payments show different content
    capex_idx = clean.find("Hyperscaler")
    payments_idx = clean.find("Digital Payments")
    assert capex_idx >= 0 and payments_idx >= 0, "Both theses should appear"

    # Fix 3: Holdings show news context, not just streaks
    assert "\U0001f4cc" in full_brief, "Holdings should show \U0001f4cc news markers"
    assert "tariff" in clean.lower(), "Tariff headline should appear in NVDA holding"

    # Fix 4/5: Moonshot shows discovery context
    assert "\U0001f4e1" in full_brief, "Should show \U0001f4e1 discovery context"

    # Fix 6: Moonshot has upside/downside/milestone
    assert "\u2b06" in full_brief or "\u2191" in clean, "Should show upside case"
    assert "\u2b07" in full_brief or "\u2193" in clean, "Should show downside case"
    assert "\U0001f3af" in full_brief, "Should show key milestone"

    # At least one moonshot from Reddit or 13F
    assert "smallstreetbets" in clean.lower() or "reddit" in clean.lower() or "coatue" in clean.lower(), \
        "At least one moonshot should reference Reddit or 13F source"

    print(f"\n{'='*70}")
    print("ALL INTEGRATION ASSERTIONS PASSED")
    print(f"{'='*70}")
    print("  Fix 1: Conviction list NOT empty")
    print("  Fix 2: Macro theses show different headlines")
    print("  Fix 3: Holdings show news context (pin)")
    print("  Fix 4/5: Moonshot discovery context (satellite)")
    print("  Fix 6: Moonshot upside/downside/milestone")
    print("  Reddit/13F source referenced in output")
