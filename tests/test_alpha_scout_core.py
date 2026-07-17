from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from src.alpha_scout import main as scout_main
from src.alpha_scout import synthesizer
from src.alpha_scout.candidate_sourcer import source_all_candidates
from src.alpha_scout.screener import normalize_weights, screen_candidates


def _scored_candidate(ticker: str, composite: float = 72.0) -> dict:
    return {
        "ticker": ticker,
        "source": "unit_test",
        "scores": {"composite": composite, "technical": 70, "fundamental": 74},
        "fundamentals_summary": {"sector": "Technology", "pe_trailing": 22},
    }


def test_top_buys_mode_keeps_existing_portfolio_and_watchlist_tickers():
    audit: dict = {}
    candidates = source_all_candidates(
        existing_tickers=["AMZN", "META", "AVGO"],
        holdings=[{"ticker": "AMZN"}],
        config={
            "sources": {
                "agent_bus": False,
                "sector_peers": False,
                "sp500_index": False,
                "yfinance_screener": False,
                "supply_chain": False,
                "thematic_scanner": False,
                "superinvestor_13f": False,
                "reddit_moonshot": False,
                "filing_scanner": False,
            },
            "screening": {"max_candidates": 50},
        },
        include_existing=True,
        audit=audit,
    )

    tickers = [candidate["ticker"] for candidate in candidates]
    assert tickers == ["AMZN", "META", "AVGO"]
    assert audit["source_counts"]["existing universe"] == 3
    assert audit["excluded_existing"] == []


def test_new_discoveries_mode_excludes_existing_tickers():
    audit: dict = {}
    candidates = source_all_candidates(
        existing_tickers=["AMZN"],
        holdings=[{"ticker": "AMZN"}],
        config={
            "sources": {
                "agent_bus": False,
                "sector_peers": True,
                "sp500_index": False,
                "yfinance_screener": False,
                "supply_chain": False,
                "thematic_scanner": False,
                "superinvestor_13f": False,
                "reddit_moonshot": False,
                "filing_scanner": False,
            },
            "screening": {"max_candidates": 50},
            "sector_peers": {"Consumer Cyclical": ["AMZN", "TSLA"]},
        },
        include_existing=False,
        audit=audit,
    )

    assert [candidate["ticker"] for candidate in candidates] == ["TSLA"]
    assert audit["excluded_existing"][0]["ticker"] == "AMZN"


def test_screener_normalizes_configured_weights_and_scores_full_rubric():
    weights = normalize_weights({
        "technical": 0.20,
        "fundamental": 0.25,
        "sentiment": 0.10,
        "diversification": 0.15,
        "novelty": 0.10,
        "catalyst_proximity": 0.10,
        "evidence_quality": 0.10,
    })

    assert round(sum(weights.values()), 6) == 1.0

    scored = screen_candidates(
        candidates=[
            {
                "ticker": "META",
                "source": "existing_watchlist",
                "signal_type": "watchlist",
                "signal_data": {"cohort": "watchlist", "catalyst": "earnings"},
            }
        ],
        technicals={"META": {}},
        fundamentals={
            "META": {
                "pe_trailing": 28,
                "revenue_growth": 0.16,
                "net_margin": 0.25,
                "gross_margin": 0.80,
                "market_cap": 1_500_000_000_000,
                "sector": "Communication Services",
                "next_earnings_date": "2026-07-25",
            }
        },
        portfolio_tickers=["AMZN"],
        portfolio_fundamentals={"AMZN": {"sector": "Consumer Cyclical"}},
        weights=weights,
    )

    scores = scored[0]["scores"]
    assert "novelty" in scores
    assert "catalyst_proximity" in scores
    assert "evidence_quality" in scores
    assert scores["composite"] > 60


def test_top_buy_scoring_lifts_tracked_quality_names():
    scored = screen_candidates(
        candidates=[
            {
                "ticker": "META",
                "source": "existing_watchlist",
                "signal_type": "watchlist",
                "signal_data": {"cohort": "watchlist"},
            },
            {
                "ticker": "NOVL",
                "source": "agent_bus/street_ear",
                "signal_type": "unusual_mentions",
                "signal_data": {"sentiment": 0.7, "mentions": 8},
            },
        ],
        technicals={"META": {}, "NOVL": {}},
        fundamentals={
            "META": {
                "pe_trailing": 24,
                "revenue_growth": 0.22,
                "net_margin": 0.32,
                "gross_margin": 0.80,
                "market_cap": 1_500_000_000_000,
                "sector": "Communication Services",
                "pct_from_52w_high": -18,
                "next_earnings_date": "2026-07-25",
            },
            "NOVL": {
                "pe_trailing": 22,
                "revenue_growth": 0.05,
                "net_margin": 0.06,
                "gross_margin": 0.45,
                "market_cap": 20_000_000_000,
                "sector": "Technology",
            },
        },
        portfolio_tickers=["AMZN"],
        portfolio_fundamentals={"AMZN": {"sector": "Consumer Cyclical"}},
        weights={
            "technical": 0.20,
            "fundamental": 0.25,
            "sentiment": 0.10,
            "diversification": 0.15,
            "novelty": 0.10,
            "catalyst_proximity": 0.10,
            "evidence_quality": 0.10,
        },
        mode="top_buys",
    )

    meta = next(candidate for candidate in scored if candidate["ticker"] == "META")
    assert meta["scores"]["composite"] >= 80
    assert meta["scores"]["novelty"] >= 80
    assert meta["scores"]["weights"]["fundamental"] > meta["scores"]["weights"]["novelty"]


def test_score_fundamental_penalises_expensive_thin_margin_names():
    """A richly-valued, thin-margin name with little analyst upside (AFRM's real
    profile) must not score like a high-quality compounder, and being down off the
    highs is not, by itself, a reason to score well."""
    from src.alpha_scout.screener import score_fundamental

    afrm_like = {
        "pe_trailing": 72.0, "pe_forward": 21.0, "ev_to_ebitda": 53.7,
        "revenue_growth": 0.33, "net_margin": 0.10, "gross_margin": 0.48,
        "implied_upside_pct": 5.5, "pct_from_52w_high": -20.5,
        "market_cap": 26_000_000_000,
    }
    quality = {
        "pe_trailing": 25.0, "ev_to_ebitda": 18.0,
        "revenue_growth": 0.30, "net_margin": 0.40, "gross_margin": 0.70,
        "implied_upside_pct": 35.0, "pct_from_52w_high": -12.0,
        "market_cap": 1_000_000_000_000,
    }
    afrm_score = score_fundamental(afrm_like)
    quality_score = score_fundamental(quality)
    assert afrm_score < 80, afrm_score
    assert quality_score >= 95, quality_score
    assert afrm_score < quality_score

    # Outright losses are penalised, not treated as neutral.
    lossmaker = dict(afrm_like, net_margin=-0.15)
    assert score_fundamental(lossmaker) < afrm_score


def test_score_fundamental_penalises_low_quality_cheap_name():
    """A cheap, fast-growing name with a thin gross margin and negative free cash
    flow (SMCI's profile) must not score top-tier just because its multiple is low."""
    from src.alpha_scout.screener import score_fundamental

    smci_like = {
        "pe_trailing": 16, "ev_to_ebitda": 16, "revenue_growth": 1.2,
        "net_margin": 0.04, "gross_margin": 0.08, "free_cashflow": -7e9,
        "implied_upside_pct": 21, "pct_from_52w_high": -50, "market_cap": 20e9,
    }
    quality = {
        "pe_trailing": 25, "ev_to_ebitda": 18, "revenue_growth": 0.30,
        "net_margin": 0.40, "gross_margin": 0.70, "free_cashflow": 30e9,
        "implied_upside_pct": 35, "pct_from_52w_high": -12, "market_cap": 1e12,
    }
    assert score_fundamental(smci_like) < score_fundamental(quality)
    assert score_fundamental(smci_like) < 90  # not top-tier despite cheap multiple


def test_thin_single_source_discovery_does_not_outrank_tracked_name():
    """Regression: a non-tracked name surfaced by a lone signal (e.g. a supply-chain
    adjacency + one golden cross, as AFRM was) must not outrank a tracked watchlist
    name in top_buys, even when its raw fundamentals look strong. Evidence-breadth
    scoring should keep it below validated names."""
    scored = screen_candidates(
        candidates=[
            {
                "ticker": "AFRM",  # not in portfolio/watchlist; single thin source
                "source": "agent_bus/portfolio_analyst",
                "signal_type": "technical_signal",
                "signal_data": {"signals": ["Golden Cross"]},
                "corroboration_count": 1,
                "corroborating_sources": ["agent_bus/portfolio_analyst"],
            },
            {
                "ticker": "NVDA",  # tracked watchlist name
                "source": "existing_watchlist",
                "signal_type": "watchlist",
                "signal_data": {"cohort": "watchlist"},
                "corroboration_count": 1,
                "corroborating_sources": ["existing_watchlist"],
            },
        ],
        technicals={
            "AFRM": {"moving_averages": {"golden_cross": True}, "signals_summary": ["Golden Cross"]},
            "NVDA": {},
        },
        fundamentals={
            "AFRM": {
                "pe_trailing": None, "revenue_growth": 0.30, "net_margin": 0.05,
                "gross_margin": 0.50, "market_cap": 40_000_000_000,
                "sector": "Financial Services", "pct_from_52w_high": -12,
            },
            "NVDA": {
                "pe_trailing": 45, "revenue_growth": 0.50, "net_margin": 0.50,
                "gross_margin": 0.75, "market_cap": 3_000_000_000_000,
                "sector": "Technology", "pct_from_52w_high": -8,
            },
        },
        portfolio_tickers=["NVDA"],
        portfolio_fundamentals={"NVDA": {"sector": "Technology"}},
        weights={},
        mode="top_buys",
    )

    by_ticker = {c["ticker"]: c["scores"] for c in scored}
    assert by_ticker["NVDA"]["composite"] > by_ticker["AFRM"]["composite"]
    # A lone-source discovery must not max the evidence dimension like a validated name.
    assert by_ticker["AFRM"]["evidence_quality"] < by_ticker["NVDA"]["evidence_quality"]
    assert scored[0]["ticker"] == "NVDA"


def test_top_buy_synthesis_shortlist_keeps_core_tracked_candidates():
    scored = [
        {
            "ticker": f"NEW{i}",
            "source": "agent_bus/street_ear",
            "scores": {"composite": 95 - i, "fundamental": 80, "evidence_quality": 90},
        }
        for i in range(20)
    ]
    scored.append({
        "ticker": "NVDA",
        "source": "existing_watchlist",
        "scores": {"composite": 82, "fundamental": 100, "evidence_quality": 100},
    })

    shortlist = scout_main._select_synthesis_candidates(scored, 20, "top_buys")

    assert len(shortlist) == 20
    assert "NVDA" in {candidate["ticker"] for candidate in shortlist}


def test_top_buy_core_coverage_adds_missing_tracked_recommendations():
    scored = [
        {
            "ticker": "META",
            "source": "existing_watchlist",
            "scores": {"composite": 84, "fundamental": 100, "evidence_quality": 100},
            "fundamentals_summary": {
                "revenue_growth": 0.24,
                "net_margin": 0.30,
                "gross_margin": 0.80,
                "market_cap": 1_500_000_000_000,
                "pct_from_52w_high": -16,
            },
        }
    ]

    portfolio, watchlist = scout_main._ensure_top_buy_core_coverage(
        portfolio_recs=[],
        watchlist_recs=[],
        scored=scored,
        max_portfolio=5,
        max_watchlist=10,
        scout_mode="top_buys",
    )

    assert portfolio[0]["ticker"] == "META"
    assert portfolio[0]["source"] == "alpha_scout/top_buy_core_coverage"
    assert watchlist == []


def test_synthesis_parser_extracts_embedded_json_from_model_text():
    result = synthesizer._parse_synthesis(
        """
        Here is the concise answer:
        {"portfolio":[{"ticker":"meta","conviction":"HIGH","thesis":"AI ad tools are compounding."}],
         "watchlist":[{"ticker":"SHOP","conviction":"medium","thesis":"Watch for margin confirmation."}]}
        """,
        [_scored_candidate("META"), _scored_candidate("SHOP", 64)],
    )

    assert result["portfolio_recs"][0]["ticker"] == "META"
    assert result["portfolio_recs"][0]["conviction"] == "high"
    assert result["watchlist_recs"][0]["ticker"] == "SHOP"


def test_synthesize_recommendations_requests_json_mode(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ALPHA_SCOUT_SYNTHESIS_PROVIDER", raising=False)
    monkeypatch.setattr(synthesizer, "check_budget", lambda: (True, 0.0, 100.0))
    monkeypatch.setattr(synthesizer, "record_usage", lambda *args, **kwargs: 0.01)

    synthesis_text = (
        '{"portfolio":[{"ticker":"META","conviction":"high",'
        '"thesis":"AI ad tools are compounding."}],"watchlist":[]}'
    )
    response = SimpleNamespace(
        usage=SimpleNamespace(input_tokens=100, output_tokens=50),
        model="gemini-2.5-flash",
        content=[SimpleNamespace(text=synthesis_text)],
    )
    fake_messages = MagicMock()
    fake_messages.create.return_value = response
    monkeypatch.setattr(
        synthesizer.anthropic,
        "Anthropic",
        lambda: SimpleNamespace(messages=fake_messages),
    )

    result = synthesizer.synthesize_recommendations([_scored_candidate("META")])

    kwargs = fake_messages.create.call_args.kwargs
    assert kwargs["response_mime_type"] == "application/json"
    assert kwargs["temperature"] == 0.2
    assert result["synthesis_source"] == "llm_json"
    assert result["portfolio_recs"][0]["source"] == "alpha_scout/llm_synthesis"


def test_synthesize_recommendations_repairs_messy_paid_output(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ALPHA_SCOUT_SYNTHESIS_PROVIDER", raising=False)
    monkeypatch.setattr(synthesizer, "check_budget", lambda: (True, 0.0, 100.0))
    monkeypatch.setattr(synthesizer, "record_usage", lambda *args, **kwargs: 0.01)

    messy_response = SimpleNamespace(
        usage=SimpleNamespace(input_tokens=100, output_tokens=20),
        model="gemini-2.5-flash",
        content=[SimpleNamespace(text="Portfolio: META high because AI ad tools are compounding.")],
    )
    repaired_text = (
        '{"portfolio":[{"ticker":"META","conviction":"high",'
        '"thesis":"AI ad tools are compounding."}],"watchlist":[]}'
    )
    repaired_response = SimpleNamespace(
        usage=SimpleNamespace(input_tokens=60, output_tokens=40),
        model="gemini-2.5-flash",
        content=[SimpleNamespace(text=repaired_text)],
    )
    fake_messages = MagicMock()
    fake_messages.create.side_effect = [messy_response, repaired_response]
    monkeypatch.setattr(
        synthesizer.anthropic,
        "Anthropic",
        lambda: SimpleNamespace(messages=fake_messages),
    )

    result = synthesizer.synthesize_recommendations([_scored_candidate("META")])

    assert fake_messages.create.call_count == 2
    assert result["synthesis_source"] == "llm_repaired_json"
    assert result["portfolio_recs"][0]["ticker"] == "META"


def test_synthesize_recommendations_prefers_openrouter_when_key_exists(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("ALPHA_SCOUT_OPENROUTER_MODEL", "anthropic/claude-opus-4.8")
    monkeypatch.delenv("ALPHA_SCOUT_SYNTHESIS_PROVIDER", raising=False)
    monkeypatch.setattr(synthesizer, "check_budget", lambda: (True, 0.0, 100.0))
    monkeypatch.setattr(synthesizer, "record_usage", lambda *args, **kwargs: 0.01)

    captured: dict = {}
    synthesis_text = (
        '{"portfolio":[{"ticker":"META","conviction":"high",'
        '"thesis":"OpenRouter thesis."}],"watchlist":[]}'
    )

    def fake_completion(request_body, request_headers, timeout_s):
        captured["request_body"] = request_body
        captured["request_headers"] = request_headers
        captured["timeout_s"] = timeout_s
        return {
            "model": request_body["model"],
            "choices": [{"message": {"content": synthesis_text}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, "cost": 0.123},
        }

    monkeypatch.setattr(synthesizer, "_openrouter_completion_raw", fake_completion)

    result = synthesizer.synthesize_recommendations([_scored_candidate("META")])

    assert captured["request_body"]["model"] == "z-ai/glm-5.2"
    assert captured["request_body"]["response_format"]["type"] == "json_schema"
    assert "maxItems" not in json.dumps(captured["request_body"]["response_format"])
    assert captured["request_headers"]["Authorization"] == "Bearer test-key"
    assert result["synthesis_provider"] == "openrouter"
    assert result["synthesis_model"] == "z-ai/glm-5.2"
    assert result["synthesis_cost_usd"] == 0.123
    assert result["portfolio_recs"][0]["thesis"] == "OpenRouter thesis."


def test_forced_openrouter_without_key_does_not_fall_back_to_gemini(monkeypatch):
    monkeypatch.setenv("ALPHA_SCOUT_SYNTHESIS_PROVIDER", "openrouter")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(synthesizer, "check_budget", lambda: (True, 0.0, 100.0))

    def fail_if_gemini_used():
        raise AssertionError("Gemini/compat backend should not be used")

    monkeypatch.setattr(synthesizer.anthropic, "Anthropic", fail_if_gemini_used)

    result = synthesizer.synthesize_recommendations([_scored_candidate("META")])

    assert result["synthesis_source"] == "error_fallback"
    assert result["portfolio_recs"][0]["ticker"] == "META"
