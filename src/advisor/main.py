"""Main orchestrator for the AlphaDesk Advisor.

Runs the full pipeline: loads memory, runs existing agents, fetches
advisor-specific data, synthesizes with Opus 4.6, saves memory state,
and returns the 5-section daily brief.
"""

import asyncio
import time
from datetime import date
from typing import Any

import anthropic

from src.shared.agent_bus import consume
from src.shared.config_loader import load_config
from src.shared.cost_tracker import check_budget, get_daily_cost, record_usage
from src.utils.logger import get_logger

log = get_logger(__name__)

AGENT_NAME = "advisor"
MODEL = "claude-opus-4-6"


def _load_advisor_config() -> dict[str, Any]:
    """Load advisor config, with defaults for missing keys."""
    try:
        return load_config("advisor")
    except Exception:
        log.exception("Failed to load advisor config — using minimal defaults")
        return {"holdings": [], "macro_theses": [], "superinvestors": [],
                "strategy": {}, "prediction_markets": {}, "screening": {},
                "output": {}, "conviction_weights": {}}


async def _run_agent(name: str, run_fn) -> dict[str, Any]:
    """Run an agent with error handling and timing."""
    start = time.time()
    try:
        result = await run_fn()
        log.info("Agent %s completed in %.1fs", name, time.time() - start)
        return result
    except Exception as e:
        log.error("Agent %s failed after %.1fs: %s", name, time.time() - start, e, exc_info=True)
        return {"formatted": f"<b>{name}</b>\n<i>Agent error: {e}</i>", "signals": [], "stats": {}}


async def run() -> dict[str, Any]:
    """Run the complete Advisor pipeline.

    Steps:
        1. Load memory + config
        2. Run Street Ear + News Desk (parallel, for signals)
        3. Fetch market data (prices, technicals, fundamentals)
        4. Fetch advisor-specific data (macro, earnings, prediction markets, superinvestors)
        5. Monitor holdings (daily snapshots with memory)
        6. Run decision engine (conviction, moonshot, strategy)
        7. Opus 4.6 synthesis → 5-section brief
        8. Save memory state
        9. Format and return

    Returns:
        Dict with formatted (str), signals (list), stats (dict).
    """
    pipeline_start = time.time()
    log.info("Advisor pipeline starting")

    # ── Step 1: Load memory + config ──────────────────────────────────
    config = _load_advisor_config()

    from src.advisor.memory import (
        build_memory_context,
        seed_holdings,
        seed_macro_theses,
        save_daily_brief,
        increment_conviction_weeks,
    )

    # Seed holdings and macro theses from config (only inserts new ones)
    seed_holdings(config.get("holdings", []))
    seed_macro_theses(config.get("macro_theses", []))

    # Increment conviction weeks on Mondays
    if date.today().weekday() == 0:
        increment_conviction_weeks()

    memory = build_memory_context()
    log.info("Memory loaded: %d holdings, %d macro theses, %d conviction, %d moonshots",
             len(memory["holdings"]), len(memory["macro_theses"]),
             len(memory["conviction_list"]), len(memory["moonshot_list"]))

    # Build ticker universe: holdings + conviction + moonshots
    holding_tickers = [h["ticker"] for h in memory["holdings"]]
    conviction_tickers = [c["ticker"] for c in memory["conviction_list"]]
    moonshot_tickers = [m["ticker"] for m in memory["moonshot_list"]]
    all_tickers = list(dict.fromkeys(holding_tickers + conviction_tickers + moonshot_tickers))

    # ── Step 2: Run Street Ear + News Desk in parallel ────────────────
    from src.street_ear.main import run as run_street_ear
    from src.news_desk.main import run as run_news_desk

    log.info("Step 2: Running Street Ear + News Desk")
    street_ear_result, news_desk_result = await asyncio.gather(
        _run_agent("Street Ear", run_street_ear),
        _run_agent("News Desk", run_news_desk),
    )

    # Read signals without consuming (Portfolio Analyst needs them later)
    agent_bus_signals = consume(mark_consumed=False)

    # ── Step 3: Fetch market data ──────────────────────────────────────
    from src.portfolio_analyst.price_fetcher import fetch_current_prices, fetch_all_historical
    from src.portfolio_analyst.fundamental_analyzer import fetch_all_fundamentals
    from src.portfolio_analyst.technical_analyzer import analyze_all as run_technical_analysis

    log.info("Step 3: Fetching market data for %d tickers", len(all_tickers))
    step_start = time.time()

    try:
        prices = await asyncio.to_thread(fetch_current_prices, all_tickers)
    except Exception:
        log.exception("Failed to fetch prices")
        prices = {}

    try:
        historical = await asyncio.to_thread(fetch_all_historical, all_tickers)
    except Exception:
        log.exception("Failed to fetch historical data")
        historical = {}

    try:
        fundamentals = await asyncio.to_thread(fetch_all_fundamentals, all_tickers)
    except Exception:
        log.exception("Failed to fetch fundamentals")
        fundamentals = {}

    try:
        technicals = run_technical_analysis(all_tickers, historical)
    except Exception:
        log.exception("Failed to run technical analysis")
        technicals = {}

    log.info("Step 3 completed in %.1fs", time.time() - step_start)

    # ── Step 4: Fetch advisor-specific data ────────────────────────────
    from src.advisor.macro_analyst import fetch_macro_data, update_macro_theses
    from src.advisor.prediction_market import fetch_prediction_markets, detect_significant_shifts
    from src.advisor.earnings_analyzer import run_earnings_analysis
    from src.advisor.superinvestor_tracker import run_superinvestor_tracking

    log.info("Step 4: Fetching advisor data (macro, earnings, prediction markets, superinvestors)")
    step_start = time.time()

    try:
        macro_data = await asyncio.to_thread(fetch_macro_data)
    except Exception:
        log.exception("Failed to fetch macro data")
        macro_data = {}

    try:
        prediction_data = await asyncio.to_thread(
            fetch_prediction_markets, config.get("prediction_markets", {}))
    except Exception:
        log.exception("Failed to fetch prediction markets")
        prediction_data = []

    try:
        prediction_shifts = detect_significant_shifts(
            min_delta_pct=config.get("prediction_markets", {}).get("alert_delta_pct", 10))
    except Exception:
        log.exception("Failed to detect prediction shifts")
        prediction_shifts = []

    try:
        earnings_data = await asyncio.to_thread(run_earnings_analysis, all_tickers)
    except Exception:
        log.exception("Failed to run earnings analysis")
        earnings_data = {}

    try:
        superinvestor_data = await asyncio.to_thread(
            run_superinvestor_tracking, all_tickers, config)
    except Exception:
        log.exception("Failed to run superinvestor tracking")
        superinvestor_data = {}

    # Update macro theses with new data
    news_signals = news_desk_result.get("signals", [])
    try:
        updated_theses = update_macro_theses(macro_data, news_signals)
    except Exception:
        log.exception("Failed to update macro theses")
        updated_theses = memory["macro_theses"]

    log.info("Step 4 completed in %.1fs", time.time() - step_start)

    # ── Step 5: Monitor holdings ───────────────────────────────────────
    from src.advisor.holdings_monitor import monitor_holdings, build_holdings_narrative

    log.info("Step 5: Monitoring holdings")
    try:
        holdings_reports = monitor_holdings(
            holdings=memory["holdings"],
            prices=prices,
            fundamentals=fundamentals,
            signals=agent_bus_signals,
            news_signals=news_signals,
        )
    except Exception:
        log.exception("Failed to monitor holdings")
        holdings_reports = []

    holdings_narrative = build_holdings_narrative(holdings_reports)

    # ── Step 6: Decision engine ────────────────────────────────────────
    from src.advisor.valuation_engine import compute_target_price
    from src.advisor.conviction_manager import update_conviction_list
    from src.advisor.moonshot_manager import update_moonshot_list
    from src.advisor.strategy_engine import generate_strategy

    log.info("Step 6: Running decision engine")
    step_start = time.time()

    # Compute valuations for all tickers
    valuation_data = {}
    for ticker in all_tickers:
        try:
            fund = fundamentals.get(ticker, {})
            earn = earnings_data.get("per_ticker", {}).get(ticker) if isinstance(earnings_data, dict) else None
            val_result = compute_target_price(ticker, fund, earn)
            # Enrich with P/E data from fundamentals for strategy engine
            if not val_result.get("insufficient_data"):
                val_result["pe_trailing"] = fund.get("pe_trailing")
                val_result["pe_forward"] = fund.get("pe_forward")
            valuation_data[ticker] = val_result
        except Exception:
            log.debug("Failed to compute valuation for %s", ticker)

    # Source candidates from Alpha Scout for conviction/moonshot pipeline
    discovery_candidates = []
    try:
        from src.alpha_scout.candidate_sourcer import source_all_candidates
        from src.alpha_scout.screener import screen_candidates

        discovery_candidates = source_all_candidates(
            existing_tickers=all_tickers,
            holdings=[{"ticker": t} for t in holding_tickers],
            config=config,
        )
        if discovery_candidates:
            # Fetch data for candidates and screen them
            cand_tickers = [c["ticker"] for c in discovery_candidates[:20]]
            cand_fundamentals = await asyncio.to_thread(
                fetch_all_fundamentals, cand_tickers
            )
            cand_historical = await asyncio.to_thread(
                fetch_all_historical, cand_tickers
            )
            cand_technicals = run_technical_analysis(cand_tickers, cand_historical)

            discovery_candidates = screen_candidates(
                candidates=discovery_candidates[:20],
                technicals=cand_technicals,
                fundamentals=cand_fundamentals,
                portfolio_tickers=holding_tickers,
                portfolio_fundamentals=fundamentals,
                weights=config.get("conviction_weights", {
                    "technical": 0.30, "fundamental": 0.30,
                    "sentiment": 0.20, "diversification": 0.20,
                }),
            )
            # Compute valuations for top candidates
            for cand in discovery_candidates[:10]:
                t = cand["ticker"]
                try:
                    cand_fund = cand_fundamentals.get(t, {})
                    valuation_data[t] = compute_target_price(t, cand_fund)
                except Exception:
                    pass

            log.info("Sourced %d discovery candidates for conviction pipeline", len(discovery_candidates))
    except Exception:
        log.exception("Failed to source discovery candidates")

    # Update conviction list
    try:
        conviction_result = update_conviction_list(
            candidates=discovery_candidates,
            superinvestor_data=superinvestor_data,
            earnings_data=earnings_data if isinstance(earnings_data, dict) else {},
            prediction_data=prediction_data,
            valuation_data=valuation_data,
            config=config,
        )
    except Exception:
        log.exception("Failed to update conviction list")
        conviction_result = {"current_list": memory["conviction_list"], "added": [], "removed": []}

    # Update moonshot list
    try:
        moonshot_result = update_moonshot_list(candidates=discovery_candidates, config=config)
    except Exception:
        log.exception("Failed to update moonshot list")
        moonshot_result = {"current_list": memory["moonshot_list"], "added": [], "removed": []}

    # Generate strategy
    try:
        strategy = generate_strategy(
            holdings_reports=holdings_reports,
            macro_theses=updated_theses,
            valuation_data=valuation_data,
            config=config,
        )
    except Exception:
        log.exception("Failed to generate strategy")
        strategy = {"actions": [], "flags": [], "summary": "Strategy generation failed."}

    log.info("Step 6 completed in %.1fs", time.time() - step_start)

    # ── Step 7: Opus 4.6 synthesis ─────────────────────────────────────
    log.info("Step 7: Opus synthesis")
    synthesis = _synthesize_brief(
        memory=memory,
        macro_data=macro_data,
        updated_theses=updated_theses,
        prediction_shifts=prediction_shifts,
        holdings_reports=holdings_reports,
        strategy=strategy,
        conviction_list=conviction_result.get("current_list", []),
        moonshot_list=moonshot_result.get("current_list", []),
        earnings_data=earnings_data,
    )

    # ── Step 8: Save memory state ──────────────────────────────────────
    try:
        save_daily_brief(
            macro_summary=synthesis.get("macro_summary"),
            portfolio_actions=strategy.get("actions", []),
            conviction_changes=conviction_result.get("added", []) + conviction_result.get("removed", []),
            moonshot_changes=moonshot_result.get("added", []) + moonshot_result.get("removed", []),
        )
    except Exception:
        log.exception("Failed to save daily brief to memory")

    # ── Step 9: Format output ──────────────────────────────────────────
    from src.advisor.formatter import (
        format_daily_brief,
        format_macro_section,
        format_holdings_section,
        format_strategy_section,
        format_conviction_section,
        format_moonshot_section,
    )

    daily_cost = get_daily_cost()

    try:
        macro_section = format_macro_section(macro_data, updated_theses, prediction_shifts)
        holdings_section = format_holdings_section(holdings_reports)
        strategy_section = format_strategy_section(strategy)
        conviction_section = format_conviction_section(conviction_result.get("current_list", []))
        moonshot_section = format_moonshot_section(moonshot_result.get("current_list", []))

        # If Opus produced an enhanced brief, use it; otherwise use structured sections
        opus_brief = synthesis.get("formatted_brief")
        if opus_brief:
            formatted = opus_brief
        else:
            formatted = format_daily_brief(
                macro_section=macro_section,
                holdings_section=holdings_section,
                strategy_section=strategy_section,
                conviction_section=conviction_section,
                moonshot_section=moonshot_section,
                daily_cost=daily_cost,
            )
    except Exception:
        log.exception("Failed to format brief")
        formatted = "<b>AlphaDesk Advisor</b>\n\nError formatting daily brief."

    total_time = time.time() - pipeline_start
    log.info("Advisor pipeline completed in %.1fs", total_time)

    return {
        "formatted": formatted,
        "signals": agent_bus_signals,
        "stats": {
            "total_time_s": round(total_time, 1),
            "daily_cost": daily_cost,
            "holdings_count": len(holdings_reports),
            "conviction_count": len(conviction_result.get("current_list", [])),
            "moonshot_count": len(moonshot_result.get("current_list", [])),
            "actions_count": len(strategy.get("actions", [])),
        },
        "sections": {
            "macro": macro_data,
            "holdings": holdings_reports,
            "strategy": strategy,
            "conviction": conviction_result,
            "moonshots": moonshot_result,
        },
    }


def _macro_val(macro_data: dict, key: str) -> str:
    """Extract a value from macro_data (handles nested dicts)."""
    v = macro_data.get(key)
    if v is None:
        return "N/A"
    if isinstance(v, dict):
        val = v.get("value")
        return f"{val:.2f}" if val is not None else "N/A"
    if isinstance(v, (int, float)):
        return f"{v:.2f}"
    return str(v)


def _macro_chg(macro_data: dict, key: str) -> str:
    """Extract change_pct from macro_data."""
    v = macro_data.get(key)
    if isinstance(v, dict):
        chg = v.get("change_pct")
        if chg is not None:
            return f"{chg:+.1f}%"
    return "N/A"


def _synthesize_brief(
    memory: dict[str, Any],
    macro_data: dict[str, Any],
    updated_theses: list[dict[str, Any]],
    prediction_shifts: list[dict[str, Any]],
    holdings_reports: list[dict[str, Any]],
    strategy: dict[str, Any],
    conviction_list: list[dict[str, Any]],
    moonshot_list: list[dict[str, Any]],
    earnings_data: dict[str, Any],
) -> dict[str, Any]:
    """Use Opus 4.6 to enhance the daily brief with narrative and judgment."""
    within_budget, spent, cap = check_budget()
    if not within_budget:
        log.warning("Budget exceeded ($%.2f/$%.2f) — skipping Opus synthesis", spent, cap)
        return {"macro_summary": "Budget exceeded — synthesis skipped."}

    # Build yesterday's context
    yesterday = memory.get("yesterday_brief")
    yesterday_ctx = ""
    if yesterday:
        yesterday_ctx = f"""
## WHAT YOU SAID YESTERDAY
Macro: {yesterday.get('macro_summary', 'N/A')}
Actions recommended: {len(yesterday.get('portfolio_actions', []))}
Conviction changes: {len(yesterday.get('conviction_changes', []))}
"""

    # Build holdings context
    holdings_ctx = "\n".join(
        f"- {h.get('ticker')}: ${h.get('price', 0):,.2f} ({h.get('change_pct', 0):+.1f}% today, "
        f"{h.get('cumulative_return_pct', 0):+.1f}% total) — thesis: {h.get('thesis_status', 'intact')}. "
        f"{h.get('recent_trend', '')}"
        for h in holdings_reports
    ) if holdings_reports else "No holdings data."

    # Build conviction context
    conviction_ctx = "\n".join(
        f"- {c.get('ticker')}: week {c.get('weeks_on_list', 1)}, "
        f"conviction: {c.get('conviction', 'medium')}, thesis: {c.get('thesis', '')}"
        for c in conviction_list
    ) if conviction_list else "Conviction list is empty."

    # Build macro context
    macro_ctx_parts = []
    for t in updated_theses:
        macro_ctx_parts.append(f"- {t.get('title')}: {t.get('status', 'intact')}")
    macro_ctx = "\n".join(macro_ctx_parts) if macro_ctx_parts else "No macro theses."

    prompt = f"""You are a senior portfolio manager writing a daily brief for an investor.

INVESTOR PROFILE:
- Holds positions for 1+ years. Low churn. Not a trader.
- Prefers undervalued stocks but open to momentum with strong evidence.
- Current portfolio is tech/AI-heavy by conviction.
- Only recommend changes if thesis is invalidated or opportunity is exceptional (25% CAGR minimum).
- Weight crowd sentiment and company guidance over analyst opinions.

{yesterday_ctx}

## TODAY'S DATA

### MACRO
S&P 500: {_macro_val(macro_data, 'sp500')} ({_macro_chg(macro_data, 'sp500')})
VIX: {_macro_val(macro_data, 'vix')}
10Y Yield: {_macro_val(macro_data, 'treasury_10y')}%
Fed Rate: {_macro_val(macro_data, 'fed_funds_rate')}%
Yield Curve: {macro_data.get('yield_curve_spread_calculated', 'N/A')}

### MACRO THESES STATUS
{macro_ctx}

### PREDICTION MARKET SHIFTS
{chr(10).join(f"- {s.get('market_title')}: {s.get('probability', 0)*100:.0f}% ({s.get('delta', 0)*100:+.0f}pp)" for s in prediction_shifts[:5]) if prediction_shifts else "No significant shifts."}

### HOLDINGS
{holdings_ctx}

### STRATEGY ENGINE OUTPUT
Actions: {len(strategy.get('actions', []))}
{chr(10).join(f"- {a.get('action').upper()} {a.get('ticker')}: {a.get('reason', '')}" for a in strategy.get('actions', [])) if strategy.get('actions') else "No action recommended."}

### CONVICTION LIST
{conviction_ctx}

### MOONSHOT LIST
{chr(10).join(f"- {m.get('ticker')}: {m.get('thesis', '')}" for m in moonshot_list) if moonshot_list else "Empty."}

Produce a concise 2-3 paragraph MACRO SUMMARY that connects the dots between macro forces, how they affect the portfolio, and any actionable implications. Focus on what CHANGED today. If nothing material changed, say so.

Respond with ONLY the macro summary text. No headers."""

    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=MODEL,
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}],
        )

        usage = response.usage
        record_usage(AGENT_NAME, usage.input_tokens, usage.output_tokens)
        macro_summary = response.content[0].text

        log.info("Synthesis complete: %d in, %d out", usage.input_tokens, usage.output_tokens)
        return {"macro_summary": macro_summary}

    except Exception:
        log.exception("Opus synthesis failed")
        return {"macro_summary": "Synthesis unavailable — review sections below."}


async def run_single_section(section_name: str) -> dict[str, Any]:
    """Run a single section of the advisor brief."""
    config = _load_advisor_config()

    from src.advisor.memory import build_memory_context, seed_holdings, seed_macro_theses
    seed_holdings(config.get("holdings", []))
    seed_macro_theses(config.get("macro_theses", []))
    memory = build_memory_context()

    holding_tickers = [h["ticker"] for h in memory["holdings"]]

    if section_name == "macro":
        from src.advisor.macro_analyst import fetch_macro_data, update_macro_theses
        from src.advisor.prediction_market import detect_significant_shifts
        from src.advisor.formatter import format_macro_section

        macro_data = await asyncio.to_thread(fetch_macro_data)
        theses = update_macro_theses(macro_data, [])
        shifts = detect_significant_shifts()
        formatted = format_macro_section(macro_data, theses, shifts)
        return {"formatted": formatted}

    elif section_name == "holdings":
        from src.portfolio_analyst.price_fetcher import fetch_current_prices
        from src.portfolio_analyst.fundamental_analyzer import fetch_all_fundamentals
        from src.advisor.holdings_monitor import monitor_holdings
        from src.advisor.formatter import format_holdings_section

        prices = await asyncio.to_thread(fetch_current_prices, holding_tickers)
        fundamentals = await asyncio.to_thread(fetch_all_fundamentals, holding_tickers)
        reports = monitor_holdings(memory["holdings"], prices, fundamentals, [], [])
        formatted = format_holdings_section(reports)
        return {"formatted": formatted}

    elif section_name == "conviction":
        from src.advisor.formatter import format_conviction_section
        formatted = format_conviction_section(memory["conviction_list"])
        return {"formatted": formatted}

    elif section_name == "moonshot":
        from src.advisor.formatter import format_moonshot_section
        formatted = format_moonshot_section(memory["moonshot_list"])
        return {"formatted": formatted}

    elif section_name == "action":
        from src.advisor.strategy_engine import generate_strategy
        from src.advisor.formatter import format_strategy_section
        strategy = generate_strategy([], memory["macro_theses"], {}, config)
        formatted = format_strategy_section(strategy)
        return {"formatted": formatted}

    return {"formatted": f"Unknown section: {section_name}"}
