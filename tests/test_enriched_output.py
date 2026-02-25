"""Test enriched output format for conviction and moonshot sections."""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from unittest.mock import MagicMock
for mod in ["anthropic", "fredapi", "yfinance"]:
    sys.modules.setdefault(mod, MagicMock())

import pytest


def test_conviction_section_with_source():
    """Conviction section should show discovery source."""
    from src.advisor.formatter import format_conviction_section

    conviction_list = [
        {
            "ticker": "PLTR",
            "conviction": "medium",
            "weeks_on_list": 1,
            "thesis": "Palantir's government AI contracts provide visible revenue growth with 25% CAGR potential.",
            "source": "Dragoneer initiated $45M position + strong fundamentals",
        },
        {
            "ticker": "IONQ",
            "conviction": "low",
            "weeks_on_list": 1,
            "thesis": "Quantum computing pure-play with first-mover advantage in trapped-ion technology.",
            "source": "12 Reddit mentions across smallstreetbets, SecurityAnalysis",
        },
    ]

    output = format_conviction_section(conviction_list)

    print(f"\n{'='*60}")
    print("Enriched Conviction Section")
    print(f"{'='*60}")
    print(output)

    assert "📡" in output, "Should contain 📡 discovery source emoji"
    assert "Dragoneer" in output, "Should show Dragoneer source"
    assert "Reddit mentions" in output, "Should show Reddit source"
    assert "PLTR" in output
    assert "IONQ" in output

    print("\n  ✅ Conviction section shows discovery source!")


def test_moonshot_section_with_source():
    """Moonshot section should show why this surfaced."""
    from src.advisor.formatter import format_moonshot_section

    moonshot_list = [
        {
            "ticker": "IONQ",
            "conviction": "medium",
            "months_on_list": 1,
            "thesis": "Quantum computing pure-play with 40% revenue growth and commercial contracts.",
            "upside_case": "2-5x if quantum hits inflection point in enterprise computing",
            "downside_case": "50% downside if no commercial traction by 2027",
            "key_milestone": "First $10M commercial quantum contract",
            "source": "Mentioned 12 times on r/smallstreetbets, r/SecurityAnalysis + Coatue new position",
        },
    ]

    output = format_moonshot_section(moonshot_list)

    print(f"\n{'='*60}")
    print("Enriched Moonshot Section")
    print(f"{'='*60}")
    print(output)

    assert "📡" in output, "Should contain 📡 source emoji"
    assert "surfaced" in output.lower(), "Should contain 'Why this surfaced'"
    assert "⬆" in output, "Should show upside case"
    assert "⬇" in output, "Should show downside case"
    assert "🎯" in output, "Should show key milestone"
    assert "IONQ" in output

    print("\n  ✅ Moonshot section shows discovery context!")


def test_empty_source_graceful():
    """Sections should work gracefully when source is empty."""
    from src.advisor.formatter import format_conviction_section, format_moonshot_section

    conviction_no_source = [
        {"ticker": "XYZ", "conviction": "low", "weeks_on_list": 2, "thesis": "Test thesis"},
    ]
    output = format_conviction_section(conviction_no_source)
    assert "📡" not in output, "No source = no source line"
    assert "XYZ" in output

    moonshot_no_source = [
        {"ticker": "ABC", "conviction": "medium", "months_on_list": 1,
         "thesis": "Test thesis", "upside_case": "2x", "downside_case": "50% loss",
         "key_milestone": "Q1 earnings"},
    ]
    output = format_moonshot_section(moonshot_no_source)
    assert "📡" not in output, "No source = no source line"
    assert "ABC" in output

    print("\n  ✅ Empty source handled gracefully!")
