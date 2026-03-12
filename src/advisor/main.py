"""Main orchestrator for the AlphaDesk Advisor.

Runs the full pipeline: loads memory, runs existing agents, fetches
advisor-specific data, synthesizes with Gemini, saves memory state,
and returns the 5-section daily brief.
"""
from __future__ import annotations

import asyncio
import time
from datetime import date
from pathlib import Path
from typing import Any

from src.shared import gemini_compat as anthropic

from src.advisor.run_profile import RunProfile
from src.shared.agent_bus import consume, get_latest_signal_id
from src.shared.config_loader import load_config
from src.shared.cost_tracker import (
    check_budget,
    get_daily_cost,
    get_run_cost,
    record_usage,
)
from src.utils.logger import get_logger

log = get_logger(__name__)

AGENT_NAME = "advisor"
MODEL = "claude-opus-4-6"


def _load_advisor_config() -> dict[str, Any]:
    """Load advisor config, with defaults for missing keys.

    If private/portfolio.yaml exists, merges holdings (and any other keys)
    from there — keeping private data out of the committed config.
    """
    try:
        config = load_config("advisor")
    except Exception:
        log.exception("Failed to load advisor config — using minimal defaults")
        config = {"holdings": [], "macro_theses": [], "superinvestors": [],
                  "strategy": {}, "prediction_markets": {}, "screening": {},
                  "output": {}, "conviction_weights": {}}

    # Merge private portfolio if it exists
    private_path = Path("private/portfolio.yaml")
    if private_path.exists():
        try:
            import yaml
            with open(private_path) as f:
                private = yaml.safe_load(f) or {}
            if "holdings" in private:
                config["holdings"] = private["holdings"]
                log.info("Loaded %d holdings from private/portfolio.yaml", len(private["holdings"]))
            # Merge any other private overrides
            for key in ("macro_theses", "superinvestors"):
                if key in private:
                    config[key] = private[key]
        except Exception:
            log.exception("Failed to load private portfolio — using config defaults")

    return config


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


async def _run_blocking_step(step_name: str, func, *args, default: Any = None) -> Any:
    """Run a blocking function in a worker thread with consistent logging."""
    try:
        return await asyncio.to_thread(func, *args)
    except Exception as exc:
        log.error(
            "%s failed: %s",
            step_name,
            exc,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        return default


def _fetch_prediction_bundle(
    prediction_config: dict[str, Any],
    min_delta_pct: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Fetch and diff prediction-market data in one threaded bundle."""
    from src.advisor.prediction_market import (
        detect_significant_shifts,
        fetch_prediction_markets,
    )

    prediction_data = fetch_prediction_markets(prediction_config)
    prediction_shifts = detect_significant_shifts(min_delta_pct=min_delta_pct)
    return prediction_data, prediction_shifts


def _generate_delta_summary_text(delta_report) -> str:
    """Generate a delta summary with LLM fallback hidden behind one call."""
    from src.advisor.delta_engine import generate_delta_summary

    try:
        client = anthropic.Anthropic()
        return generate_delta_summary(delta_report, anthropic_client=client)
    except Exception:
        log.exception("LLM delta summary failed before fallback")
        return generate_delta_summary(delta_report)


async def run(run_type: str = "morning_full") -> dict[str, Any]:
    """Run the advisor pipeline through the multi-run orchestrator."""
    from src.advisor.run_orchestrator import RunOrchestrator

    orchestrator = RunOrchestrator()
    return await orchestrator.execute(run_type=run_type)


async def _run_pipeline(run_profile: RunProfile) -> dict[str, Any]:
    """Run the complete Advisor pipeline.

    Steps:
        1. Load memory + config
        2. Run Street Ear + News Desk (parallel, for signals)
        3. Fetch market data (prices, technicals, fundamentals)
        4. Fetch advisor-specific data (macro, earnings, prediction markets, superinvestors)
        5. Monitor holdings (daily snapshots with memory)
        6. Run decision engine (conviction, moonshot, strategy)
        7. Gemini synthesis → 5-section brief
        8. Save memory state
        9. Format and return

    Returns:
        Dict with formatted (str), signals (list), stats (dict).
    """
    pipeline_start = time.time()
    log.info(
        "Advisor pipeline starting (%s, run_id=%s, budget=$%.2f)",
        run_profile.run_type,
        run_profile.run_id,
        run_profile.budget_usd,
    )

    # ── Step 1: Load memory + config ──────────────────────────────────
    config = _load_advisor_config()

    from src.advisor.memory import (
        build_memory_context,
        seed_holdings,
        seed_macro_theses,
        save_daily_brief,
        save_run_snapshot,
        increment_conviction_weeks,
    )

    # Seed holdings and macro theses from config (only inserts new ones)
    seed_holdings(config.get("holdings", []))
    seed_macro_theses(config.get("macro_theses", []))

    # Sync entry_price from config into DB (config is source of truth)
    from src.advisor.memory import update_holding
    for h in config.get("holdings", []):
        if h.get("entry_price"):
            try:
                update_holding(h["ticker"], entry_price=h["entry_price"])
            except Exception:
                pass

    # Increment conviction weeks on Mondays
    if date.today().weekday() == 0:
        increment_conviction_weeks()

    memory = build_memory_context()

    # Enrich memory holdings with config data (shares, entry_price, portfolio_pct)
    # that isn't stored in the DB schema
    config_holdings_map = {
        h["ticker"]: h for h in config.get("holdings", [])
    }
    for h in memory["holdings"]:
        cfg = config_holdings_map.get(h["ticker"], {})
        if cfg.get("shares"):
            h["shares"] = cfg["shares"]
        if cfg.get("entry_price") and not h.get("entry_price"):
            h["entry_price"] = cfg["entry_price"]
        if cfg.get("portfolio_pct"):
            h["portfolio_pct"] = cfg["portfolio_pct"]

    log.info("Memory loaded: %d holdings, %d macro theses, %d conviction, %d moonshots",
             len(memory["holdings"]), len(memory["macro_theses"]),
             len(memory["conviction_list"]), len(memory["moonshot_list"]))

    # ── Step 1b-d: Start context loaders in the background ────────────
    retrospective_task: asyncio.Task[str] | None = None
    calibration_task: asyncio.Task[str] | None = None
    preference_task: asyncio.Task[str] | None = None

    try:
        from src.advisor.retrospective import get_latest_retrospective_context

        retrospective_task = asyncio.create_task(
            _run_blocking_step(
                "Load retrospective context",
                get_latest_retrospective_context,
                default="",
            )
        )
    except Exception:
        log.exception("Failed to initialize retrospective context loader")

    try:
        from src.advisor.reasoning_journal import build_calibration_context

        calibration_task = asyncio.create_task(
            _run_blocking_step(
                "Load calibration context",
                build_calibration_context,
                default="",
            )
        )
    except Exception:
        log.exception("Failed to initialize calibration context loader")

    try:
        from src.advisor.feedback_manager import build_preference_context

        preference_task = asyncio.create_task(
            _run_blocking_step(
                "Load user preference context",
                build_preference_context,
                default="",
            )
        )
    except Exception:
        log.exception("Failed to initialize user preference context loader")

    # Build ticker universe: holdings + conviction + moonshots
    holding_tickers = [h["ticker"] for h in memory["holdings"]]
    conviction_tickers = [c["ticker"] for c in memory["conviction_list"]]
    moonshot_tickers = [m["ticker"] for m in memory["moonshot_list"]]
    all_tickers = list(dict.fromkeys(holding_tickers + conviction_tickers + moonshot_tickers))

    # ── Step 2: Run Street Ear + News Desk + Substack Ear + YouTube Ear in parallel
    from src.street_ear.main import run as run_street_ear
    from src.news_desk.main import run as run_news_desk

    # Lazy-import helpers for new ear agents (graceful degradation)
    async def _safe_run_substack():
        try:
            from src.substack_ear.main import run as run_sub
            return await run_sub()
        except Exception:
            log.debug("Substack Ear not available or failed")
            return {"formatted": "", "signals": [], "stats": {}}

    async def _safe_run_youtube():
        try:
            from src.youtube_ear.main import run as run_yt
            return await run_yt()
        except Exception:
            log.debug("YouTube Ear not available or failed")
            return {"formatted": "", "signals": [], "stats": {}}

    log.info("Step 2: Running Street Ear + News Desk + Substack Ear + YouTube Ear")
    street_ear_result, news_desk_result, substack_result, youtube_result = await asyncio.gather(
        _run_agent("Street Ear", run_street_ear),
        _run_agent("News Desk", run_news_desk),
        _run_agent("Substack Ear", _safe_run_substack),
        _run_agent("YouTube Ear", _safe_run_youtube),
    )

    # Read signals without consuming (Portfolio Analyst needs them later)
    agent_bus_signals = consume(mark_consumed=False)

    # Extract Reddit mood + themes from Street Ear (used in synthesis prompt + formatter)
    _reddit_mood = street_ear_result.get("analysis", {}).get("market_mood", "")
    _reddit_themes = street_ear_result.get("analysis", {}).get("themes", [])

    discovery_candidates_task: asyncio.Task[list[dict[str, Any]]] | None = None
    try:
        from src.alpha_scout.candidate_sourcer import source_all_candidates

        discovery_candidates_task = asyncio.create_task(
            _run_blocking_step(
                "Source discovery candidates",
                source_all_candidates,
                all_tickers,
                [{"ticker": t} for t in holding_tickers],
                config,
                default=[],
            )
        )
    except Exception:
        log.exception("Failed to initialize discovery candidate sourcing")

    # ── Step 3-4: Fetch market + advisor data in parallel ─────────────
    from src.portfolio_analyst.price_fetcher import fetch_current_prices, fetch_all_historical
    from src.portfolio_analyst.fundamental_analyzer import fetch_all_fundamentals
    from src.portfolio_analyst.technical_analyzer import analyze_all as run_technical_analysis
    from src.advisor.macro_analyst import fetch_macro_data, update_macro_theses
    from src.advisor.earnings_analyzer import run_earnings_analysis
    from src.advisor.superinvestor_tracker import run_superinvestor_tracking

    async def _fetch_market_data() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        log.info("Step 3: Fetching market data for %d tickers", len(all_tickers))
        step_start = time.time()

        prices_task = asyncio.create_task(
            _run_blocking_step("Fetch prices", fetch_current_prices, all_tickers, default={})
        )
        historical_task = asyncio.create_task(
            _run_blocking_step("Fetch historical data", fetch_all_historical, all_tickers, default={})
        )
        fundamentals_task = asyncio.create_task(
            _run_blocking_step("Fetch fundamentals", fetch_all_fundamentals, all_tickers, default={})
        )

        historical = await historical_task
        technicals_task = asyncio.create_task(
            _run_blocking_step(
                "Run technical analysis",
                run_technical_analysis,
                all_tickers,
                historical,
                default={},
            )
        )

        prices, fundamentals, technicals = await asyncio.gather(
            prices_task,
            fundamentals_task,
            technicals_task,
        )

        log.info("Step 3 completed in %.1fs", time.time() - step_start)
        return prices, fundamentals, technicals

    async def _fetch_advisor_data() -> tuple[
        dict[str, Any],
        list[dict[str, Any]],
        list[dict[str, Any]],
        dict[str, Any],
        dict[str, Any],
    ]:
        log.info("Step 4: Fetching advisor data (macro, earnings, prediction markets, superinvestors)")
        step_start = time.time()

        prediction_config = config.get("prediction_markets", {})
        min_delta_pct = prediction_config.get("alert_delta_pct", 10)

        macro_task = asyncio.create_task(
            _run_blocking_step("Fetch macro data", fetch_macro_data, default={})
        )
        prediction_task = asyncio.create_task(
            _run_blocking_step(
                "Fetch prediction market data",
                _fetch_prediction_bundle,
                prediction_config,
                min_delta_pct,
                default=([], []),
            )
        )
        earnings_task = asyncio.create_task(
            _run_blocking_step(
                "Run earnings analysis",
                run_earnings_analysis,
                all_tickers,
                default={},
            )
        )
        superinvestor_task = asyncio.create_task(
            _run_blocking_step(
                "Run superinvestor tracking",
                run_superinvestor_tracking,
                all_tickers,
                config,
                default={},
            )
        )

        macro_data, prediction_bundle, earnings_data, raw_si_data = await asyncio.gather(
            macro_task,
            prediction_task,
            earnings_task,
            superinvestor_task,
        )
        prediction_data, prediction_shifts = prediction_bundle
        superinvestor_data = (
            raw_si_data.get("smart_money_summaries", {})
            if isinstance(raw_si_data, dict)
            else {}
        )

        log.info("Step 4 completed in %.1fs", time.time() - step_start)
        return (
            macro_data,
            prediction_data,
            prediction_shifts,
            earnings_data,
            superinvestor_data,
        )

    (
        prices,
        fundamentals,
        technicals,
    ), (
        macro_data,
        prediction_data,
        prediction_shifts,
        earnings_data,
        superinvestor_data,
    ) = await asyncio.gather(
        _fetch_market_data(),
        _fetch_advisor_data(),
    )

    # Update macro theses with new data — include macro_event signals from bus
    # Use top_articles (full analyzed articles with all fields) instead of signals
    # (which only contains tracking metadata: {id, type, title} — missing category,
    # tickers, etc. needed by _match_news_to_thesis and holdings_monitor)
    news_signals: list[dict[str, Any]] = []
    for article in news_desk_result.get("top_articles", []):
        news_signals.append({
            "headline": article.get("title", ""),
            "source": article.get("source", ""),
            "tickers": article.get("related_tickers", []),
            "ticker": article.get("related_tickers", [""])[0] if article.get("related_tickers") else "",
            "category": article.get("category", ""),
            "sentiment": article.get("sentiment", 0),
            "summary": article.get("summary", ""),
        })
    # Enrich with macro_event signals from the agent bus so trade/policy/geopolitical
    # events reach the thesis matching even if they came from a previous run
    for bus_signal in agent_bus_signals:
        if bus_signal.get("signal_type") == "macro_event":
            payload = bus_signal.get("payload", {})
            affected = payload.get("affected_tickers", [])
            news_signals.append({
                "headline": payload.get("title", ""),
                "source": payload.get("source", ""),
                "tickers": affected,
                "ticker": affected[0] if affected else "",
                "category": payload.get("category", "macro"),
                "sentiment": payload.get("sentiment", 0),
                "summary": payload.get("summary", ""),
            })
    try:
        updated_theses = update_macro_theses(macro_data, news_signals)
    except Exception:
        log.exception("Failed to update macro theses")
        updated_theses = memory["macro_theses"]

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

    # ── Step 5b: Delta Engine — snapshot + compute changes ─────────────
    from src.advisor.delta_engine import (
        build_snapshot,
        save_today_snapshot,
        compute_deltas,
        format_delta_for_prompt,
    )
    from src.advisor.memory import get_latest_snapshot_before

    log.info("Step 5b: Delta Engine")
    delta_report = None
    delta_summary_task: asyncio.Task[str] | None = None
    delta_prompt_section = ""
    yesterday_snapshot = None
    save_snapshot_task: asyncio.Task[Any] | None = None
    daily_snapshot_saved = False
    try:
        today_snapshot = build_snapshot(
            holdings_reports=holdings_reports,
            fundamentals=fundamentals,
            technicals=technicals,
            macro_data=macro_data,
            conviction_list=memory["conviction_list"],
            moonshot_list=memory["moonshot_list"],
            strategy={},
            earnings_data=earnings_data if isinstance(earnings_data, dict) else {},
            superinvestor_data=superinvestor_data,
            reddit_mood=_reddit_mood,
            reddit_themes=_reddit_themes,
        )
        yesterday_snapshot_task = asyncio.create_task(
            _run_blocking_step(
                "Load previous snapshot",
                get_latest_snapshot_before,
                date.today().isoformat(),
                default=None,
            )
        )
        if run_profile.run_type == "morning_full":
            save_snapshot_task = asyncio.create_task(
                _run_blocking_step(
                    "Save daily snapshot",
                    save_today_snapshot,
                    today_snapshot,
                    default=None,
                )
            )
        yesterday_snapshot = await yesterday_snapshot_task
        if save_snapshot_task is not None:
            await save_snapshot_task
            daily_snapshot_saved = True
    except Exception:
        log.exception("Failed to build/save daily snapshot")
        today_snapshot = {}

    try:
        delta_report = compute_deltas(today_snapshot, yesterday_snapshot)
        delta_summary_task = asyncio.create_task(
            _run_blocking_step(
                "Generate delta summary",
                _generate_delta_summary_text,
                delta_report,
                default="",
            )
        )
        log.info("Delta report: %d high, %d medium, %d low",
                 len(delta_report.high_significance),
                 len(delta_report.medium_significance),
                 len(delta_report.low_significance))
    except Exception:
        log.exception("Failed to compute deltas")
        delta_prompt_section = ""

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
        from src.alpha_scout.screener import screen_candidates

        if discovery_candidates_task is not None:
            discovery_candidates = await discovery_candidates_task

        if discovery_candidates:
            # Fetch data for candidates and screen them
            cand_tickers = [c["ticker"] for c in discovery_candidates[:20]]
            cand_si_tickers = [c["ticker"] for c in discovery_candidates[:10]]

            cand_fundamentals_task = asyncio.create_task(
                _run_blocking_step(
                    "Fetch candidate fundamentals",
                    fetch_all_fundamentals,
                    cand_tickers,
                    default={},
                )
            )
            cand_historical_task = asyncio.create_task(
                _run_blocking_step(
                    "Fetch candidate historical data",
                    fetch_all_historical,
                    cand_tickers,
                    default={},
                )
            )
            cand_superinvestor_task = asyncio.create_task(
                _run_blocking_step(
                    "Fetch candidate superinvestor data",
                    run_superinvestor_tracking,
                    cand_si_tickers,
                    config,
                    default={},
                )
            )

            cand_historical = await cand_historical_task
            cand_technicals_task = asyncio.create_task(
                _run_blocking_step(
                    "Run candidate technical analysis",
                    run_technical_analysis,
                    cand_tickers,
                    cand_historical,
                    default={},
                )
            )

            cand_fundamentals, cand_technicals, cand_si_data = await asyncio.gather(
                cand_fundamentals_task,
                cand_technicals_task,
                cand_superinvestor_task,
            )

            if isinstance(cand_si_data, dict):
                for t, summary in cand_si_data.get("smart_money_summaries", {}).items():
                    if t not in superinvestor_data:
                        superinvestor_data[t] = summary

            discovery_candidates = await _run_blocking_step(
                "Screen discovery candidates",
                screen_candidates,
                discovery_candidates[:20],
                cand_technicals,
                cand_fundamentals,
                holding_tickers,
                fundamentals,
                config.get("conviction_weights", {
                    "technical": 0.30, "fundamental": 0.30,
                    "sentiment": 0.20, "diversification": 0.20,
                }),
                default=discovery_candidates[:20],
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

    # ── Step 6b: Catalyst tracking + event detection ─────────────────
    catalyst_data = {}
    catalyst_prompt_section = ""
    try:
        from src.advisor.catalyst_tracker import run_catalyst_tracking, format_catalysts_for_prompt
        catalyst_data = run_catalyst_tracking(all_tickers)
        catalyst_prompt_section = format_catalysts_for_prompt(catalyst_data.get("catalysts", []))
        log.info("Catalyst tracking: %d catalysts found", len(catalyst_data.get("catalysts", [])))
    except Exception:
        log.exception("Catalyst tracking failed — continuing without catalysts")

    # Extract future-dated events from news articles → persist as catalysts
    try:
        from src.advisor.event_detector import run_event_detection
        top_articles = news_desk_result.get("top_articles", [])
        existing_cats = catalyst_data.get("catalysts", [])
        detected_events = run_event_detection(top_articles, existing_cats)
        if detected_events:
            log.info("Event detection: %d new events extracted from news", len(detected_events))
            # Refresh catalyst data to include newly detected events
            catalyst_data["catalysts"] = existing_cats + detected_events
            catalyst_prompt_section = format_catalysts_for_prompt(catalyst_data["catalysts"])
    except Exception:
        log.exception("Event detection failed — continuing with hardcoded catalysts only")

    # Record conviction additions as structured recommendations for outcome tracking
    try:
        from src.advisor.memory import record_recommendation
        from src.advisor.conviction_manager import build_evidence_items
        from src.shared.schemas import compute_evidence_quality_score
        for added_entry in conviction_result.get("added", []):
            t = added_entry.get("ticker", "")
            if not t:
                continue
            # Build evidence items for this ticker
            si_data = superinvestor_data.get(t)
            earn_data = earnings_data.get("per_ticker", {}).get(t) if isinstance(earnings_data, dict) else None
            fund = fundamentals.get(t, {})
            val = valuation_data.get(t)
            crowd = {}
            for c in discovery_candidates:
                if c.get("ticker") == t:
                    sig = c.get("signal_data", {})
                    if sig.get("sentiment") is not None:
                        crowd["reddit_sentiment"] = sig["sentiment"]
                    break
            evidence_items = build_evidence_items(t, earn_data, crowd, si_data, fund, val)
            eq_score = compute_evidence_quality_score(evidence_items)

            # Fetch actual thesis text from memory for skeptic review
            thesis_text = ""
            try:
                conv_entries = memory.get_conviction_list(active_only=True)
                for ce in conv_entries:
                    if ce.get("ticker") == t:
                        thesis_text = ce.get("thesis", "")
                        break
            except Exception:
                pass

            # Run skeptic challenge on new conviction additions
            rec_dict = {
                "ticker": t,
                "recommendation_date": date.today().isoformat(),
                "action": "BUY",
                "conviction_level": added_entry.get("conviction", "medium"),
                "valuation": val or {},
                "thesis": {"core_argument": thesis_text, "supporting_evidence": [e.to_dict() for e in evidence_items], "evidence_quality_score": eq_score},
                "bear_case": {"primary_risk": ""},
                "analyst_scores": {"composite_score": 0.0},
                "source": "conviction_pipeline",
                "category": "conviction_add",
            }
            try:
                from src.advisor.skeptic_agent import SkepticAgent, apply_skeptic_to_recommendation
                skeptic = SkepticAgent()
                market_ctx = {"vix": macro_data.get("vix", {}).get("value") if isinstance(macro_data.get("vix"), dict) else macro_data.get("vix"),
                              "treasury_10y": macro_data.get("treasury_10y", {}).get("value") if isinstance(macro_data.get("treasury_10y"), dict) else macro_data.get("treasury_10y")}
                skeptic_result = skeptic.challenge_recommendation(rec_dict, market_ctx)
                rec_dict = apply_skeptic_to_recommendation(rec_dict, skeptic_result)
                log.info("Skeptic reviewed %s: modifier=%.2f", t, skeptic_result.get("confidence_modifier", 1.0))
            except Exception:
                log.exception("Skeptic review failed for %s — recording without skeptic", t)

            record_recommendation(rec_dict)
    except Exception:
        log.exception("Failed to record conviction recommendations for outcome tracking")

    # Update moonshot list
    try:
        moonshot_result = update_moonshot_list(
            candidates=discovery_candidates,
            config=config,
            prediction_data=prediction_data,
            earnings_data=earnings_data if isinstance(earnings_data, dict) else {},
            valuation_data=valuation_data,
        )
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

    # ── Step 6c: Record reasoning journal entries ──────────────────────
    try:
        from src.advisor.reasoning_journal import record_daily_reasoning
        for h in holdings_reports:
            t = h.get("ticker", "")
            if not t:
                continue
            chg = h.get("change_pct") or 0
            thesis = h.get("thesis", "")
            thesis_status = h.get("thesis_status", "intact")
            # Determine predicted direction from strategy actions
            action_dir = "flat"
            for a in strategy.get("actions", []):
                if a.get("ticker") == t:
                    act = a.get("action", "").lower()
                    if act in ("buy", "add", "hold"):
                        action_dir = "up"
                    elif act in ("sell", "trim", "reduce"):
                        action_dir = "down"
                    break
            else:
                # No explicit action → default to "up" if thesis intact
                action_dir = "up" if thesis_status == "intact" else "flat"
            record_daily_reasoning(
                ticker=t,
                analyst="composite",
                thesis_snapshot=f"{thesis} (status: {thesis_status})",
                predicted_direction=action_dir,
            )
        log.info("Recorded reasoning journal for %d holdings", len(holdings_reports))
    except Exception:
        log.exception("Failed to record reasoning journal")

    if delta_report is not None:
        if delta_summary_task is not None:
            delta_report.summary = await delta_summary_task
        delta_prompt_section = format_delta_for_prompt(delta_report)

    retrospective_context = await retrospective_task if retrospective_task else ""
    calibration_context = await calibration_task if calibration_task else ""
    preference_context = await preference_task if preference_task else ""

    if retrospective_context:
        log.info("Loaded retrospective context (%d chars)", len(retrospective_context))
    if calibration_context:
        log.info("Loaded calibration context (%d chars)", len(calibration_context))
    if preference_context:
        log.info("Loaded user preference context (%d chars)", len(preference_context))

    # ── Step 7: Analyst Committee synthesis ──────────────────────────────
    log.info("Step 7: Analyst Committee synthesis")

    # Build context strings for the committee editor
    _macro_ctx_parts = []
    for t in updated_theses:
        _macro_ctx_parts.append(f"- {t.get('title')}: {t.get('status', 'intact')}")
    _macro_ctx_str = "\n".join(_macro_ctx_parts) if _macro_ctx_parts else "No macro theses."

    _holdings_ctx_str = "\n".join(
        f"- {h.get('ticker')}: ${h.get('price', 'N/A')} "
        f"({(h.get('change_pct') or 0):+.1f}% today, {(h.get('cumulative_return_pct') or 0):+.1f}% total) "
        f"thesis: {h.get('thesis_status', 'intact')}"
        for h in holdings_reports
    ) if holdings_reports else "No holdings data."

    _conviction_ctx_str = "\n".join(
        f"- {c.get('ticker')}: week {c.get('weeks_on_list', 1)}, "
        f"conviction: {c.get('conviction', 'medium')}, thesis: {c.get('thesis', '')}"
        for c in conviction_result.get("current_list", [])
    ) if conviction_result.get("current_list") else "Conviction list empty."

    _actions_ctx_str = "\n".join(
        f"- {a.get('action', '').upper()} {a.get('ticker')}: {a.get('reason', '')} [urgency: {a.get('urgency', 'low')}]"
        for a in strategy.get("actions", [])
    ) if strategy.get("actions") else "No action recommended."

    # Build mandate breach context for CIO prompt
    _breach_lines = [
        f"{a.get('ticker', '')}: {a.get('reason', '')} [urgency: {a.get('urgency', 'low')}]"
        for a in strategy.get("actions", [])
        if "exceeds max" in (a.get("reason", "") or "").lower()
    ]
    _mandate_breach_ctx = "\n".join(_breach_lines) if _breach_lines else ""

    # Build data context for committee analysts
    _data_context = {
        "fundamentals": fundamentals,
        "holdings_reports": holdings_reports,
        "valuation_data": valuation_data,
        "macro_data": macro_data,
        "strategy": strategy,
        "news_articles": news_desk_result.get("top_articles", []),
        "signals": agent_bus_signals,
        "earnings_data": earnings_data if isinstance(earnings_data, dict) else {},
        "last_signal_id": get_latest_signal_id(),
    }

    # Build signal intelligence context strings for the editor
    # News: top 20 headlines, grouped by ticker relevance
    _news_ctx_lines: list[str] = []
    seen_headlines: set[str] = set()
    for ns in news_signals[:50]:
        headline = (ns.get("headline") or ns.get("title", "")).strip()
        if not headline or headline in seen_headlines:
            continue
        seen_headlines.add(headline)
        ticker = ns.get("ticker", "")
        summary = ns.get("summary", "")
        prefix = f"[{ticker}] " if ticker else ""
        line = f"- {prefix}{headline}"
        if summary:
            line += f" — {summary[:120]}"
        _news_ctx_lines.append(line)
        if len(_news_ctx_lines) >= 20:
            break
    _news_ctx_str = "\n".join(_news_ctx_lines) if _news_ctx_lines else ""

    # Reddit: mood, top themes, and notable ticker mentions from agent bus
    _reddit_parts: list[str] = []
    if _reddit_mood:
        _reddit_parts.append(f"Mood: {_reddit_mood}")
    if _reddit_themes:
        _reddit_parts.append(f"Top themes: {'; '.join(_reddit_themes[:5])}")
    _reddit_ticker_lines: list[str] = []
    for sig in agent_bus_signals:
        if sig.get("agent_name") == "street_ear":
            payload = sig.get("payload", {})
            t = payload.get("ticker") or sig.get("ticker", "")
            sentiment = payload.get("sentiment_score", payload.get("sentiment", ""))
            mentions = payload.get("mention_count", payload.get("mentions", ""))
            subreddit = payload.get("subreddit", "")
            if t:
                parts_line = f"- {t}"
                if sentiment != "":
                    parts_line += f" sentiment: {sentiment}"
                if mentions != "":
                    parts_line += f", mentions: {mentions}"
                if subreddit:
                    parts_line += f" ({subreddit})"
                _reddit_ticker_lines.append(parts_line)
    if _reddit_ticker_lines:
        _reddit_parts.append("Notable ticker mentions:\n" + "\n".join(_reddit_ticker_lines[:10]))
    _reddit_ctx_str = "\n".join(_reddit_parts) if _reddit_parts else ""

    # Substack: expert newsletter signals from agent bus + formatted output
    _substack_lines: list[str] = []
    for sig in agent_bus_signals:
        if sig.get("agent_name") == "substack_ear":
            payload = sig.get("payload", {})
            title = payload.get("title") or payload.get("narrative_title", "")
            summary = payload.get("summary") or payload.get("thesis_summary", "")
            tickers_mentioned = payload.get("tickers", payload.get("affected_tickers", []))
            ticker_str = f" [{', '.join(tickers_mentioned[:3])}]" if tickers_mentioned else ""
            if title:
                line = f"- {title}{ticker_str}"
                if summary:
                    line += f": {summary[:150]}"
                _substack_lines.append(line)
    _substack_ctx_str = "\n".join(_substack_lines) if _substack_lines else ""

    synthesis = {}
    committee_result = None
    try:
        from src.advisor.analyst_committee import run_analyst_committee

        # Build earnings & superinvestor context strings for deep research
        _earnings_ctx_str = _build_earnings_ctx(
            earnings_data if isinstance(earnings_data, dict) else {}
        )
        _superinvestor_ctx_str = _build_superinvestor_ctx(superinvestor_data)

        # Determine priority tickers for deep research
        # Priority: holdings with big moves > all holdings > conviction list
        _deep_tickers: list[str] = []
        _move_threshold = config.get("committee", {}).get("deep_research_move_threshold", 2.0)
        _max_deep = config.get("committee", {}).get("deep_research_max_tickers", 6)
        for h in sorted(holdings_reports, key=lambda x: abs(x.get("change_pct") or 0), reverse=True):
            t = h.get("ticker", "")
            if t and abs(h.get("change_pct") or 0) >= _move_threshold:
                _deep_tickers.append(t)
        # Fill with remaining holdings
        for t in all_tickers[:12]:
            if t not in _deep_tickers:
                _deep_tickers.append(t)
            if len(_deep_tickers) >= _max_deep:
                break
        # Add conviction list tickers
        for c in conviction_result.get("current_list", []):
            ct = c.get("ticker", "")
            if ct and ct not in _deep_tickers:
                _deep_tickers.append(ct)

        committee_result = await run_analyst_committee(
            tickers=all_tickers[:12],
            data_context=_data_context,
            delta_summary=delta_prompt_section,
            retrospective_context=retrospective_context,
            catalyst_section=catalyst_prompt_section,
            macro_context=_macro_ctx_str,
            holdings_context=_holdings_ctx_str,
            conviction_context=_conviction_ctx_str,
            strategy_context=_actions_ctx_str,
            news_context=_news_ctx_str,
            reddit_context=_reddit_ctx_str,
            substack_context=_substack_ctx_str,
            calibration_context=calibration_context,
            preference_context=preference_context,
            earnings_context=_earnings_ctx_str,
            superinvestor_context=_superinvestor_ctx_str,
            deep_research_tickers=_deep_tickers,
            config=config,
            mandate_breach_ctx=_mandate_breach_ctx,
        )

        brief_text = committee_result.get("formatted_brief", "")
        if brief_text and "error" not in committee_result:
            synthesis = {
                "macro_summary": brief_text,
                "formatted_brief": brief_text,
                "committee_result": committee_result,
            }
            log.info("Committee synthesis complete: %d chars", len(brief_text))
        else:
            log.warning("Committee returned no brief — falling back to single-pass synthesis")
            raise ValueError("Committee returned empty brief")

    except Exception:
        log.exception("Analyst committee failed — falling back to single-pass synthesis")
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
            superinvestor_data=superinvestor_data,
            reddit_mood=_reddit_mood,
            reddit_themes=_reddit_themes,
            delta_prompt_section=delta_prompt_section,
            catalyst_prompt_section=catalyst_prompt_section,
            news_signals=news_signals,
        )
        # Preserve committee_result (deep research, analyst reports) even when
        # editor synthesis failed — the verbose formatter can still use them.
        if committee_result is not None:
            synthesis["committee_result"] = committee_result

    # ── Step 8: Save memory state ──────────────────────────────────────
    if run_profile.run_type == "morning_full":
        try:
            # Extract a short macro_summary for memory (first 500 chars of brief)
            _brief_text = synthesis.get("macro_summary", "")
            _macro_for_memory = _brief_text[:500] if _brief_text else "No synthesis available."
            save_daily_brief(
                macro_summary=_macro_for_memory,
                portfolio_actions=strategy.get("actions", []),
                conviction_changes=conviction_result.get("added", []) + conviction_result.get("removed", []),
                moonshot_changes=moonshot_result.get("added", []) + moonshot_result.get("removed", []),
            )
        except Exception:
            log.exception("Failed to save daily brief to memory")

    # ── Step 9: Format output ──────────────────────────────────────────
    from src.advisor.formatter import (
        format_daily_brief,
        format_key_headlines,
        format_macro_section,
        format_holdings_section,
        format_strategy_section,
        format_thesis_exposure_section,
        format_conviction_section,
        format_moonshot_section,
    )

    daily_cost = get_daily_cost()

    # Use Reddit mood + themes extracted after Step 2
    reddit_mood = _reddit_mood
    reddit_themes = _reddit_themes

    try:
        macro_section = format_macro_section(macro_data, updated_theses, prediction_shifts)
        holdings_section = format_holdings_section(holdings_reports)
        strategy_section = format_strategy_section(strategy)
        thesis_exposure_section = format_thesis_exposure_section(
            strategy.get("thesis_exposure", [])
        )
        conviction_section = format_conviction_section(conviction_result.get("current_list", []))
        moonshot_section = format_moonshot_section(moonshot_result.get("current_list", []))

        # Key headlines from news desk
        top_articles = news_desk_result.get("top_articles", [])
        key_headlines_section = format_key_headlines(top_articles)

        # Format catalyst section
        catalyst_formatted = ""
        try:
            catalyst_formatted = catalyst_data.get("formatted", "") if catalyst_data else ""
        except Exception:
            pass

        # If committee produced an enhanced brief, wrap it with structured sections;
        # otherwise use the old format
        committee_brief = synthesis.get("formatted_brief")
        if committee_brief:
            # Build the full v2 formatted output using committee brief as core
            from datetime import datetime as _dt
            today_str = _dt.now().strftime("%b %d, %Y")
            SEPARATOR = "\u2501" * 35

            sections = [
                f"\u2600\ufe0f <b>ALPHADESK DAILY BRIEF \u2014 {today_str}</b>",
                SEPARATOR,
                "",
            ]

            # Committee synthesis is the main body
            sections.append(committee_brief)

            # Key headlines
            if key_headlines_section:
                sections.extend(["", SEPARATOR, "", key_headlines_section])

            # Catalysts
            if catalyst_formatted:
                sections.extend(["", SEPARATOR, "", catalyst_formatted])

            # Thesis exposure
            if thesis_exposure_section:
                sections.extend(["", SEPARATOR, "", thesis_exposure_section])

            # Conviction list
            sections.extend(["", SEPARATOR, "", conviction_section])

            # Moonshots
            sections.extend(["", SEPARATOR, "", moonshot_section])

            # Reddit mood
            if reddit_mood and reddit_mood != "unknown":
                theme_suffix = ""
                if reddit_themes:
                    from src.shared.security import sanitize_html as _san
                    theme_suffix = f" \u2014 {', '.join(_san(t) for t in reddit_themes[:2])}"
                sections.append(f"\n\U0001f4e3 Reddit mood: <b>{reddit_mood}</b>{theme_suffix}")

            # Footer
            sections.extend([
                "",
                SEPARATOR,
                f"AlphaDesk v2.0 | ${daily_cost:.2f} today",
                "/advisor /delta /catalysts /scorecard /retro /cost",
            ])

            formatted = "\n".join(sections)
        else:
            formatted = format_daily_brief(
                macro_section=macro_section,
                holdings_section=holdings_section,
                strategy_section=strategy_section,
                conviction_section=conviction_section,
                moonshot_section=moonshot_section,
                daily_cost=daily_cost,
                macro_summary=synthesis.get("macro_summary"),
                thesis_exposure_section=thesis_exposure_section,
                key_headlines_section=key_headlines_section,
                reddit_mood=reddit_mood,
                reddit_themes=reddit_themes,
            )
    except Exception:
        log.exception("Failed to format brief")
        formatted = "<b>AlphaDesk Advisor</b>\n\nError formatting daily brief."

    # ── Step 9b: Update chat session context for Q&A ──────────────────
    try:
        from src.advisor.chat_session import ChatSession
        import os
        _tg_chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        if _tg_chat_id:
            _chat = ChatSession(_tg_chat_id)
            _brief_for_chat = synthesis.get("formatted_brief", formatted)
            _holdings_summary = _holdings_ctx_str
            _chat.update_brief_context(_brief_for_chat, _holdings_summary)
            log.info("Chat session context updated for Q&A")
    except Exception:
        log.debug("Failed to update chat session context — chat Q&A may lack context")

    # ── Step 10: Generate verbose report ─────────────────────────────
    total_time = time.time() - pipeline_start
    verbose_report_dir = ""
    try:
        from src.advisor.verbose_formatter import VerboseFormatter, save_verbose_report

        # Fetch scorecard for track record section (lightweight)
        _scorecard = {}
        try:
            from src.advisor.memory import get_recommendation_scorecard
            _scorecard = get_recommendation_scorecard(lookback_days=30)
        except Exception:
            log.debug("Could not fetch scorecard for verbose report")

        # Build structured signal lists from agent bus for Signal Intelligence section
        _reddit_sigs: list[dict] = []
        _substack_sigs: list[dict] = []
        _youtube_sigs: list[dict] = []
        for _bus_sig in agent_bus_signals:
            _agent = _bus_sig.get("agent_name", "")
            _payload = _bus_sig.get("payload", {})
            if _agent == "street_ear":
                _t = _payload.get("ticker") or _bus_sig.get("ticker", "")
                if _t:
                    _reddit_sigs.append({
                        "ticker": _t,
                        "sentiment": _payload.get("sentiment_score", _payload.get("sentiment", 0)),
                        "mentions": _payload.get("mention_count", _payload.get("mentions", "")),
                        "subreddit": _payload.get("subreddit", ""),
                    })
            elif _agent == "substack_ear":
                _title = _payload.get("title") or _payload.get("narrative_title", "")
                if _title:
                    _substack_sigs.append({
                        "title": _title,
                        "summary": _payload.get("summary") or _payload.get("thesis_summary", ""),
                        "tickers": _payload.get("tickers", _payload.get("affected_tickers", [])),
                    })
            elif _agent == "youtube_ear":
                _title = _payload.get("title", "")
                if _title:
                    _youtube_sigs.append({
                        "title": _title,
                        "channel": _payload.get("channel", _payload.get("author", "")),
                        "views": _payload.get("views", _payload.get("score", 0)),
                        "tickers": _payload.get("tickers", _payload.get("affected_tickers", [])),
                    })

        formatter = VerboseFormatter(
            holdings_reports=holdings_reports,
            fundamentals=fundamentals,
            technicals=technicals,
            macro_data=macro_data,
            strategy=strategy,
            conviction_result=conviction_result,
            moonshot_result=moonshot_result,
            delta_report=delta_report,
            catalyst_data=catalyst_data,
            committee_result=synthesis.get("committee_result") or {},
            updated_theses=updated_theses,
            prediction_shifts=prediction_shifts,
            news_signals=news_signals,
            top_articles=top_articles,
            earnings_data=earnings_data,
            superinvestor_data=superinvestor_data,
            scorecard=_scorecard,
            reddit_mood=reddit_mood,
            reddit_themes=reddit_themes,
            reddit_signals=_reddit_sigs,
            substack_signals=_substack_sigs,
            youtube_signals=_youtube_sigs,
            daily_cost=daily_cost,
            total_time=total_time,
        )
        md_report = formatter.generate_markdown()
        html_report = formatter.generate_html(md_report)
        paths = save_verbose_report(md_report, html_report)
        verbose_report_dir = paths.get("html", "")
        log.info("Verbose report generated: %d chars MD, %d chars HTML",
                 len(md_report), len(html_report))

        # ── Email delivery ────────────────────────────────────────────
        try:
            from src.shared.email_reporter import EmailReporter
            reporter = EmailReporter()
            if reporter.is_configured():
                # Build subject from CIO brief first line, fallback to date
                _cio_text = (synthesis.get("committee_result") or {}).get("cio_brief", "")
                _first_line = (_cio_text.strip().splitlines() or [""])[0].strip(" #*")
                _today_str = date.today().strftime("%b %d, %Y")
                _subject = f"AlphaDesk {_today_str} — {_first_line}" if _first_line else f"AlphaDesk Daily Report — {_today_str}"
                ok = reporter.send_report(html_report, subject=_subject, plain_text=md_report)
                if ok:
                    log.info("Verbose report emailed: %s", _subject)
            else:
                log.debug("Email not configured — set SMTP_USER, SMTP_PASS, REPORT_EMAIL_TO in .env to enable")
        except Exception:
            log.exception("Failed to send email report — continuing")

    except Exception:
        log.exception("Failed to generate verbose report — continuing without it")

    total_time = time.time() - pipeline_start
    run_cost = get_run_cost()
    last_signal_id = get_latest_signal_id()

    try:
        snapshot_payload = dict(today_snapshot) if isinstance(today_snapshot, dict) else {}
        snapshot_payload["brief_text"] = synthesis.get("formatted_brief", "")
        save_run_snapshot(
            run_id=run_profile.run_id,
            run_type=run_profile.run_type,
            date_str=date.today().isoformat(),
            snapshot_data=snapshot_payload,
            delta=delta_report.to_dict() if delta_report else None,
            run_cost=run_cost,
            run_duration=round(total_time, 1),
            last_signal_id=last_signal_id,
            mirror_to_daily=run_profile.run_type == "morning_full" and not daily_snapshot_saved,
        )
    except Exception:
        log.exception("Failed to persist run snapshot")

    log.info("Advisor pipeline completed in %.1fs", total_time)

    return {
        "formatted": formatted,
        "verbose_report_dir": verbose_report_dir,
        "signals": agent_bus_signals,
        "run_profile": {
            "run_id": run_profile.run_id,
            "run_type": run_profile.run_type,
            "report_format": run_profile.report_format,
            "budget_usd": run_profile.budget_usd,
            "hours_since_last_run": run_profile.hours_since_last_run,
        },
        "stats": {
            "total_time_s": round(total_time, 1),
            "daily_cost": daily_cost,
            "run_cost": run_cost,
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
            "delta_report": delta_report.to_dict() if delta_report else None,
            "catalysts": catalyst_data,
            "committee": synthesis.get("committee_result"),
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


def _build_earnings_ctx(earnings_data: dict[str, Any]) -> str:
    """Build earnings context string for the Opus prompt."""
    if not earnings_data:
        return "No earnings data available."
    per_ticker = earnings_data.get("per_ticker", {}) if isinstance(earnings_data, dict) else {}
    if not per_ticker:
        return "No per-ticker earnings data."
    lines = []
    for ticker, data in per_ticker.items():
        if not isinstance(data, dict):
            continue
        sentiment = data.get("guidance_sentiment", "N/A")
        tone = data.get("management_tone", "N/A")
        surprise = data.get("eps_surprise_pct")
        surprise_str = f", EPS surprise {surprise:+.1f}%" if surprise is not None else ""
        rev_growth = data.get("revenue_growth_yoy")
        rev_str = f", rev growth {rev_growth:+.1f}%" if rev_growth is not None else ""
        guidance = ""
        if data.get("guidance_revenue_low") and data.get("guidance_revenue_high"):
            guidance = f", guidance ${data['guidance_revenue_low']/1e9:.1f}B-${data['guidance_revenue_high']/1e9:.1f}B"
        lines.append(f"- {ticker}: guidance={sentiment}, tone={tone}{surprise_str}{rev_str}{guidance}")
    return "\n".join(lines) if lines else "No recent earnings calls."


def _build_superinvestor_ctx(superinvestor_data: dict[str, Any] | None) -> str:
    """Build superinvestor context string for the Opus prompt."""
    if not superinvestor_data:
        return "No superinvestor data available."
    lines = []
    for ticker, data in superinvestor_data.items():
        if not isinstance(data, dict):
            continue
        count = data.get("superinvestor_count", 0)
        insider = data.get("insider_buying", False)
        holders = data.get("holders", [])
        holder_names = ", ".join(h.get("name", "?") for h in holders[:3]) if holders else "N/A"
        insider_str = " + insider buying" if insider else ""
        if count > 0 or insider:
            lines.append(f"- {ticker}: {count} superinvestors ({holder_names}){insider_str}")
    return "\n".join(lines) if lines else "No notable superinvestor activity."


def _build_thesis_exposure_ctx(thesis_exposure: list[dict]) -> str:
    """Build thesis exposure context for the Opus prompt."""
    if not thesis_exposure:
        return "No thesis exposure data."
    lines = []
    for entry in thesis_exposure:
        thesis = entry.get("thesis", "")
        pct = entry.get("exposure_pct", 0)
        tickers = ", ".join(entry.get("tickers", []))
        warning = entry.get("warning", "")
        warn_str = f" ⚠ {warning}" if warning else ""
        overlaps = entry.get("overlaps_with", [])
        overlap_str = f" [overlaps: {', '.join(overlaps[:2])}]" if overlaps else ""
        lines.append(f"- {thesis}: {pct:.0f}% ({tickers}){warn_str}{overlap_str}")
    return "\n".join(lines)


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
    superinvestor_data: dict[str, Any] | None = None,
    reddit_mood: str = "",
    reddit_themes: list[str] | None = None,
    delta_prompt_section: str = "",
    catalyst_prompt_section: str = "",
    news_signals: list[dict] | None = None,
) -> dict[str, Any]:
    """Use Gemini to enhance the daily brief with narrative and judgment."""
    within_budget, spent, cap = check_budget()
    if not within_budget:
        log.warning("Budget exceeded ($%.2f/$%.2f) — skipping Gemini synthesis", spent, cap)
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
    def _fmt_holding(h: dict) -> str:
        t = h.get("ticker", "???")
        price = h.get("price")
        chg = h.get("change_pct")
        cum = h.get("cumulative_return_pct")
        price_s = f"${price:,.2f}" if price is not None else "N/A"
        chg_s = f"{chg:+.1f}% today" if chg is not None else "N/A"
        cum_s = f"{cum:+.1f}% total" if cum is not None else "N/A"
        status = h.get("thesis_status", "intact")
        trend = h.get("recent_trend", "")
        return f"- {t}: {price_s} ({chg_s}, {cum_s}) — thesis: {status}. {trend}"

    holdings_ctx = "\n".join(
        _fmt_holding(h) for h in holdings_reports
    ) if holdings_reports else "No holdings data."

    # Build top headlines context
    top_headlines = []
    for ns in (news_signals or [])[:10]:
        headline = ns.get("headline") or ns.get("title", "")
        if headline:
            top_headlines.append(headline)
    headlines_ctx = "\n".join(f"- {h}" for h in top_headlines[:5]) if top_headlines else "No headlines."

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

    # Build strategy actions context
    actions_ctx = ""
    if strategy.get("actions"):
        actions_lines = []
        for a in strategy["actions"]:
            actions_lines.append(
                f"- {a.get('action', '').upper()} {a.get('ticker')}: "
                f"{a.get('reason', '')} [urgency: {a.get('urgency', 'low')}]"
            )
        actions_ctx = "\n".join(actions_lines)
    else:
        actions_ctx = "No action recommended."

    # Build moonshot context
    moonshot_ctx = "\n".join(
        f"- {m.get('ticker')}: {m.get('thesis', '')}" for m in moonshot_list
    ) if moonshot_list else "Empty."

    # Build prediction shifts context
    pred_ctx = "\n".join(
        f"- {s.get('market_title')}: {s.get('probability', 0)*100:.0f}% "
        f"({s.get('delta', 0)*100:+.0f}pp)"
        for s in prediction_shifts[:5]
    ) if prediction_shifts else "No significant shifts."

    prompt = f"""You are a senior portfolio manager writing a daily brief for an investor who holds 18 positions in a tech/AI-heavy portfolio.

INVESTOR PROFILE:
- Holds positions for 1+ years. Low churn. Not a trader.
- Current portfolio heavily concentrated in semiconductors and hyperscalers.
- Only recommend changes when thesis is invalidated or opportunity passes the 25% CAGR gate.
- Weight company guidance and smart money over analyst opinions.
- Cares about: thesis integrity, concentration risk, macro tailwinds/headwinds to their specific holdings.

{yesterday_ctx}

{delta_prompt_section}

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
{pred_ctx}

### HOLDINGS
{holdings_ctx}

### EARNINGS & GUIDANCE
{_build_earnings_ctx(earnings_data)}

### SUPERINVESTOR ACTIVITY
{_build_superinvestor_ctx(superinvestor_data)}

### REDDIT SENTIMENT
Mood: {reddit_mood or 'N/A'}
Top themes: {', '.join((reddit_themes or [])[:3]) or 'N/A'}

### TOP NEWS HEADLINES
{headlines_ctx}

### STRATEGY ENGINE OUTPUT
{actions_ctx}

### THESIS EXPOSURE (% of portfolio on each macro thesis)
{_build_thesis_exposure_ctx(strategy.get('thesis_exposure', []))}

### CONVICTION LIST
{conviction_ctx}

### MOONSHOT LIST
{moonshot_ctx}

{catalyst_prompt_section}

## YOUR TASK

Write TWO sections:

**SECTION 1 - WHAT CHANGED TODAY (2-3 sentences)**
Lead with the specific event that matters most for THIS portfolio today — name the headline, not just the data. Reference the actual news catalyst (tariff hike, earnings report, etc.). If nothing material changed, say "Quiet day" and explain why that's fine. Do NOT just summarize the data -- interpret it.

**SECTION 2 - ADVISOR NOTES (2-4 bullet points)**
Specific, actionable observations. Examples of what belongs here:
- If strategy engine recommends trims: Do you agree? Is the reason strong enough to act, or just noise?
- If conviction names are proposed: Are they differentiated from existing holdings, or more of the same tech?
- Concentration risk: Is the portfolio too exposed to one thesis (e.g., all names ride CapEx cycle)?
- What to watch this week: specific catalysts, earnings dates, macro events that matter for this portfolio.
- If nothing is actionable: say so clearly. "Hold. No action needed." is a valid answer.

RULES:
- Be direct. No hedging language ("it might be worth considering"). Either recommend action or don't.
- Cite specific numbers (prices, percentages, dates).
- If the strategy engine's recommendation is wrong or poorly supported, say so.
- Separate the two sections with a blank line. No markdown headers. No bullet points in Section 1.

Respond with ONLY the two sections."""

    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=MODEL,
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )

        if not response.content:
            return {"macro_summary": "Synthesis unavailable — empty response."}
        usage = response.usage
        record_usage(AGENT_NAME, usage.input_tokens, usage.output_tokens, model=MODEL)
        full_text = response.content[0].text

        log.info("Synthesis complete: %d in, %d out", usage.input_tokens, usage.output_tokens)
        return {"macro_summary": full_text}

    except Exception:
        log.exception("Gemini synthesis failed")
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
