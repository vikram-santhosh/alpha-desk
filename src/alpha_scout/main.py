"""Main orchestrator for the AlphaDesk Alpha Scout agent.

Runs the full discovery pipeline: candidate sourcing, market data
fetching, multi-dimensional screening, Gemini synthesis, and
Telegram-formatted output.
"""

import asyncio
import time
from typing import Any

from src.shared.agent_bus import publish
from src.shared.config_loader import get_all_tickers, load_portfolio
from src.utils.logger import get_logger

from src.alpha_scout.candidate_sourcer import source_all_candidates
from src.alpha_scout.formatter import format_discovery_report
from src.alpha_scout.screener import screen_candidates
from src.alpha_scout.synthesizer import synthesize_recommendations

log = get_logger(__name__)

SOURCE_AGENT = "alpha_scout"


def _candidate_ticker(candidate: dict[str, Any]) -> str:
    return str(candidate.get("ticker", "")).upper().strip()


def _candidate_composite(candidate: dict[str, Any]) -> float:
    try:
        return float((candidate.get("scores") or {}).get("composite") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _is_existing_candidate(candidate: dict[str, Any]) -> bool:
    return str(candidate.get("source", "")).lower().startswith("existing_")


def _is_top_buy_core_candidate(candidate: dict[str, Any]) -> bool:
    scores = candidate.get("scores") if isinstance(candidate.get("scores"), dict) else {}
    if not _is_existing_candidate(candidate):
        return False
    return (
        _candidate_composite(candidate) >= 72.0
        and float(scores.get("fundamental") or 0) >= 85.0
        and float(scores.get("evidence_quality") or 0) >= 75.0
    )


def _select_synthesis_candidates(
    scored: list[dict[str, Any]],
    top_n: int,
    scout_mode: str,
) -> list[dict[str, Any]]:
    """Keep top-buy synthesis from dropping high-quality tracked names."""
    if scout_mode != "top_buys" or top_n <= 0:
        return scored

    shortlist = list(scored[:top_n])
    included = {_candidate_ticker(candidate) for candidate in shortlist}
    core_candidates = [
        candidate for candidate in scored if _is_top_buy_core_candidate(candidate)
    ]
    coverage_target = min(len(core_candidates), max(5, min(10, top_n // 2)))

    for candidate in core_candidates[:coverage_target]:
        ticker = _candidate_ticker(candidate)
        if not ticker or ticker in included:
            continue
        if len(shortlist) < top_n:
            shortlist.append(candidate)
        else:
            replace_index = next(
                (
                    index
                    for index in range(len(shortlist) - 1, -1, -1)
                    if not _is_top_buy_core_candidate(shortlist[index])
                ),
                len(shortlist) - 1,
            )
            included.discard(_candidate_ticker(shortlist[replace_index]))
            shortlist[replace_index] = candidate
        included.add(ticker)

    shortlist.sort(key=_candidate_composite, reverse=True)
    return shortlist[:top_n]


def _conviction_for_score(composite: float) -> str:
    if composite >= 78:
        return "high"
    if composite >= 60:
        return "medium"
    return "low"


def _format_pct(value: Any) -> str | None:
    if not isinstance(value, (int, float)):
        return None
    return f"{value * 100:.1f}%"


def _top_buy_thesis(candidate: dict[str, Any]) -> str:
    ticker = _candidate_ticker(candidate)
    scores = candidate.get("scores") if isinstance(candidate.get("scores"), dict) else {}
    fund = candidate.get("fundamentals_summary") if isinstance(candidate.get("fundamentals_summary"), dict) else {}
    composite = _candidate_composite(candidate)
    details: list[str] = []

    revenue_growth = _format_pct(fund.get("revenue_growth"))
    if revenue_growth:
        details.append(f"{revenue_growth} revenue growth")
    net_margin = _format_pct(fund.get("net_margin"))
    if net_margin:
        details.append(f"{net_margin} net margin")
    market_cap = fund.get("market_cap")
    if isinstance(market_cap, (int, float)):
        if market_cap >= 1_000_000_000_000:
            details.append(f"${market_cap / 1_000_000_000_000:.1f}T market cap")
        elif market_cap >= 1_000_000_000:
            details.append(f"${market_cap / 1_000_000_000:.0f}B market cap")
    pct_from_high = fund.get("pct_from_52w_high")
    if isinstance(pct_from_high, (int, float)):
        details.append(f"{pct_from_high:.1f}% from its 52-week high")

    evidence = ", ".join(details[:4]) or "strong fundamental and evidence scores"
    return (
        f"Top-buy mode kept {ticker} in the core shortlist with a {composite:.1f} "
        f"Alpha Scout score, fundamental score {scores.get('fundamental', 0)}, and "
        f"evidence score {scores.get('evidence_quality', 0)}. The setup is backed by {evidence}; "
        "run Model Council before acting on the signal."
    )


def _recommendation_from_candidate(candidate: dict[str, Any], category: str) -> dict[str, Any]:
    composite = _candidate_composite(candidate)
    return {
        "ticker": _candidate_ticker(candidate),
        "category": category,
        "conviction": _conviction_for_score(composite),
        "thesis": _top_buy_thesis(candidate),
        "scores": candidate.get("scores", {}),
        "fundamentals_summary": candidate.get("fundamentals_summary", {}),
        "source": "alpha_scout/top_buy_core_coverage",
    }


def _ensure_top_buy_core_coverage(
    portfolio_recs: list[dict[str, Any]],
    watchlist_recs: list[dict[str, Any]],
    scored: list[dict[str, Any]],
    max_portfolio: int,
    max_watchlist: int,
    scout_mode: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if scout_mode != "top_buys":
        return portfolio_recs, watchlist_recs

    combined: dict[str, dict[str, Any]] = {}
    for rec in portfolio_recs + watchlist_recs:
        ticker = _candidate_ticker(rec)
        if ticker:
            combined[ticker] = dict(rec)

    core_candidates = [
        candidate for candidate in scored if _is_top_buy_core_candidate(candidate)
    ]
    target_count = min(len(core_candidates), max(5, min(10, max_portfolio + max_watchlist)))
    for candidate in core_candidates[:target_count]:
        ticker = _candidate_ticker(candidate)
        if ticker and ticker not in combined:
            combined[ticker] = _recommendation_from_candidate(candidate, "portfolio")

    score_lookup = {_candidate_ticker(candidate): _candidate_composite(candidate) for candidate in scored}
    core_tickers = {_candidate_ticker(candidate) for candidate in core_candidates[:target_count]}
    ordered = sorted(
        combined.values(),
        key=lambda rec: score_lookup.get(_candidate_ticker(rec), _candidate_composite(rec)),
        reverse=True,
    )

    next_portfolio: list[dict[str, Any]] = []
    next_watchlist: list[dict[str, Any]] = []
    for rec in ordered:
        ticker = _candidate_ticker(rec)
        score = score_lookup.get(ticker, _candidate_composite(rec))
        if ticker in core_tickers and score >= 72 and len(next_portfolio) < max_portfolio:
            next_portfolio.append({**rec, "category": "portfolio"})
        elif rec.get("category") == "portfolio" and len(next_portfolio) < max_portfolio:
            next_portfolio.append({**rec, "category": "portfolio"})
        elif len(next_watchlist) < max_watchlist:
            next_watchlist.append({**rec, "category": "watchlist"})

        if len(next_portfolio) >= max_portfolio and len(next_watchlist) >= max_watchlist:
            break

    return next_portfolio, next_watchlist


def _tracked_omission_reason(
    *,
    included: bool,
    scored_candidate: dict[str, Any] | None,
    recommended_as: str | None,
    in_synthesis: bool,
    scout_mode: str,
) -> str:
    if recommended_as:
        return f"Included as {recommended_as}."
    if not included:
        if scout_mode == "new_discoveries":
            return "Excluded from discovery mode because it is already in the portfolio or watchlist."
        return "Not sourced into this run."
    if scored_candidate is None:
        return "Sourced but not scored, usually because market data or screening failed."
    if not in_synthesis:
        return "Scored but did not reach the synthesis shortlist."
    return "Reached synthesis, but the model did not select it for the final list."


def _build_tracked_ticker_checks(
    *,
    existing_tickers: list[str],
    candidate_lookup: dict[str, dict[str, Any]],
    scored: list[dict[str, Any]],
    synthesis_candidates: list[dict[str, Any]],
    portfolio_recs: list[dict[str, Any]],
    watchlist_recs: list[dict[str, Any]],
    scout_mode: str,
) -> dict[str, dict[str, Any]]:
    scored_by_ticker = {_candidate_ticker(candidate): candidate for candidate in scored}
    ranks = {_candidate_ticker(candidate): index + 1 for index, candidate in enumerate(scored)}
    synthesis_tickers = {_candidate_ticker(candidate) for candidate in synthesis_candidates}
    recommended_as = {
        _candidate_ticker(rec): str(rec.get("category") or "recommendation")
        for rec in portfolio_recs + watchlist_recs
        if _candidate_ticker(rec)
    }

    checks: dict[str, dict[str, Any]] = {}
    for ticker in existing_tickers:
        ticker_upper = str(ticker).upper().strip()
        if not ticker_upper:
            continue
        candidate = candidate_lookup.get(ticker_upper)
        scored_candidate = scored_by_ticker.get(ticker_upper)
        included = candidate is not None
        rec_category = recommended_as.get(ticker_upper)
        in_synthesis = ticker_upper in synthesis_tickers
        scores = scored_candidate.get("scores", {}) if scored_candidate else {}
        checks[ticker_upper] = {
            "included": included,
            "source": (candidate or scored_candidate or {}).get("source"),
            "mode": scout_mode,
            "rank": ranks.get(ticker_upper),
            "composite": scores.get("composite"),
            "scores": scores,
            "in_synthesis": in_synthesis,
            "recommended": rec_category is not None,
            "recommended_as": rec_category,
            "omission_reason": _tracked_omission_reason(
                included=included,
                scored_candidate=scored_candidate,
                recommended_as=rec_category,
                in_synthesis=in_synthesis,
                scout_mode=scout_mode,
            ),
        }
    return checks


async def run(mode: str = "top_buys") -> dict[str, Any]:
    """Orchestrate the full Alpha Scout discovery pipeline.

    Steps:
        1. Load config + existing tickers.
        2. Source candidates from all channels.
        3. Fetch market data for candidates.
        4. Multi-dimensional screening.
        5. Gemini synthesis (top N).
        6. Publish discovery signals to agent bus.
        7. Format Telegram output.

    Returns:
        Dict with keys:
            formatted: str — Telegram HTML report.
            signals: list — published signals.
            stats: dict — pipeline statistics.
            recommendations: dict — portfolio_recs + watchlist_recs.
    """
    pipeline_start = time.time()
    scout_mode = "new_discoveries" if mode == "new_discoveries" else "top_buys"
    include_existing = scout_mode == "top_buys"
    log.info("Alpha Scout pipeline starting in %s mode", scout_mode)

    from src.shared import scout_progress
    scout_progress.start(scout_mode)

    # ── Step 1: Load config + existing tickers ────────────────────────
    scout_progress.stage("config", "Loading config & universe")
    try:
        from src.shared.config_loader import load_scout_config
        config = load_scout_config()
    except Exception:
        log.exception("Failed to load scout config — using defaults")
        config = {
            "sources": {"agent_bus": True, "sector_peers": True, "sp500_index": True, "yfinance_screener": True},
            "screening": {"max_candidates": 50, "batch_size": 10, "top_n_for_synthesis": 20},
            "weights": {"technical": 0.30, "fundamental": 0.30, "sentiment": 0.20, "diversification": 0.20},
            "output": {"max_portfolio_recommendations": 5, "max_watchlist_recommendations": 10},
            "sector_peers": {},
        }

    try:
        portfolio_data = load_portfolio()
        holdings = portfolio_data.get("holdings", [])
        existing_tickers = get_all_tickers()
        portfolio_tickers = [h["ticker"] for h in holdings]
    except Exception:
        log.exception("Failed to load portfolio config")
        scout_progress.finish(error="config_load_failed")
        return {
            "formatted": "<b>Alpha Scout</b>\n\nError: could not load portfolio configuration.",
            "signals": [],
            "stats": {"error": "config_load_failed", "mode": scout_mode},
            "recommendations": {"portfolio_recs": [], "watchlist_recs": []},
        }

    log.info(
        "Loaded %d holdings, %d existing tickers",
        len(holdings),
        len(existing_tickers),
    )

    # ── Step 2: Source candidates ──────────────────────────────────────
    scout_progress.stage("source", "Sourcing candidates from all channels")
    step_start = time.time()
    candidate_audit: dict[str, Any] = {}
    try:
        candidates = source_all_candidates(
            existing_tickers,
            holdings,
            config,
            include_existing=include_existing,
            audit=candidate_audit,
        )
    except Exception:
        log.exception("Failed to source candidates")
        candidates = []
    log.info("Step 2 (source candidates) completed in %.2fs — %d candidates", time.time() - step_start, len(candidates))

    if not candidates:
        scout_progress.finish()
        return {
            "formatted": "<b>Alpha Scout</b>\n\n<i>No new candidates found this cycle.</i>",
            "signals": [],
            "stats": {
                "mode": scout_mode,
                "candidates_sourced": 0,
                "total_time_s": round(time.time() - pipeline_start, 1),
                "candidate_audit": candidate_audit,
            },
            "recommendations": {"portfolio_recs": [], "watchlist_recs": []},
        }

    # ── Step 3: Fetch market data for candidates ──────────────────────
    scout_progress.stage("market_data", f"Fetching prices/fundamentals for {len(candidates)} candidates")
    candidate_tickers = [c["ticker"] for c in candidates]
    candidate_lookup = {
        str(c.get("ticker", "")).upper(): c
        for c in candidates
        if c.get("ticker")
    }

    from src.portfolio_analyst.price_fetcher import (
        fetch_all_historical,
        fetch_current_prices,
    )
    from src.portfolio_analyst.fundamental_analyzer import fetch_all_fundamentals

    screening_config = config.get("screening", {})
    batch_size = screening_config.get("batch_size", 10)

    # Fetch in batches to avoid overwhelming APIs
    step_start = time.time()
    all_prices: dict[str, Any] = {}
    all_historical: dict[str, Any] = {}
    all_fundamentals: dict[str, Any] = {}

    for i in range(0, len(candidate_tickers), batch_size):
        batch = candidate_tickers[i : i + batch_size]
        log.info("Fetching data for batch %d-%d of %d", i + 1, min(i + batch_size, len(candidate_tickers)), len(candidate_tickers))

        try:
            prices = await asyncio.to_thread(fetch_current_prices, batch)
            all_prices.update(prices)
        except Exception:
            log.exception("Failed to fetch prices for batch %d", i)

        try:
            historical = await asyncio.to_thread(fetch_all_historical, batch)
            all_historical.update(historical)
        except Exception:
            log.exception("Failed to fetch historical for batch %d", i)

        try:
            fundamentals = await asyncio.to_thread(fetch_all_fundamentals, batch)
            all_fundamentals.update(fundamentals)
        except Exception:
            log.exception("Failed to fetch fundamentals for batch %d", i)

    log.info("Step 3 (market data) completed in %.2fs", time.time() - step_start)

    # Also fetch fundamentals for portfolio tickers (for sector weights in diversification scoring)
    step_start = time.time()
    try:
        portfolio_fundamentals = await asyncio.to_thread(fetch_all_fundamentals, portfolio_tickers)
    except Exception:
        log.exception("Failed to fetch portfolio fundamentals")
        portfolio_fundamentals = {}
    log.info("Portfolio fundamentals fetched in %.2fs", time.time() - step_start)

    # ── Step 4: Multi-dimensional screening ───────────────────────────
    scout_progress.stage("screening", "Scoring candidates across 7 dimensions")
    step_start = time.time()

    from src.portfolio_analyst.technical_analyzer import analyze_all as run_technical_analysis

    try:
        technicals = run_technical_analysis(candidate_tickers, all_historical)
    except Exception:
        log.exception("Failed to run technical analysis")
        technicals = {}

    weights = config.get("weights", {"technical": 0.30, "fundamental": 0.30, "sentiment": 0.20, "diversification": 0.20})

    try:
        scored = screen_candidates(
            candidates=candidates,
            technicals=technicals,
            fundamentals=all_fundamentals,
            portfolio_tickers=portfolio_tickers,
            portfolio_fundamentals=portfolio_fundamentals,
            weights=weights,
            mode=scout_mode,
        )
    except Exception:
        log.exception("Failed to screen candidates")
        scored = []

    log.info("Step 4 (screening) completed in %.2fs", time.time() - step_start)

    # ── Step 5: Gemini synthesis ──────────────────────────────────────
    scout_progress.stage("synthesis", "Synthesizing ranked ideas")
    step_start = time.time()
    top_n = screening_config.get("top_n_for_synthesis", 20)
    output_config = config.get("output", {})
    max_portfolio = output_config.get("max_portfolio_recommendations", 5)
    max_watchlist = output_config.get("max_watchlist_recommendations", 10)
    synthesis_candidates = _select_synthesis_candidates(scored, top_n, scout_mode)

    try:
        synthesis = synthesize_recommendations(
            scored_candidates=synthesis_candidates,
            top_n=len(synthesis_candidates),
            max_portfolio=max_portfolio,
            max_watchlist=max_watchlist,
        )
    except Exception:
        log.exception("Failed to synthesize recommendations")
        synthesis = {"portfolio_recs": [], "watchlist_recs": [], "raw_synthesis": ""}

    portfolio_recs = synthesis.get("portfolio_recs", [])
    watchlist_recs = synthesis.get("watchlist_recs", [])
    portfolio_recs, watchlist_recs = _ensure_top_buy_core_coverage(
        portfolio_recs=portfolio_recs,
        watchlist_recs=watchlist_recs,
        scored=scored,
        max_portfolio=max_portfolio,
        max_watchlist=max_watchlist,
        scout_mode=scout_mode,
    )
    log.info(
        "Step 5 (synthesis) completed in %.2fs — %d portfolio, %d watchlist",
        time.time() - step_start,
        len(portfolio_recs),
        len(watchlist_recs),
    )

    # ── Step 6: Publish discovery signals to agent bus ─────────────────
    scout_progress.stage("publish", "Publishing discovery signals")
    published_signals: list[dict[str, Any]] = []
    for rec in portfolio_recs + watchlist_recs:
        try:
            signal_id = publish(
                signal_type="discovery_recommendation",
                source_agent=SOURCE_AGENT,
                payload={
                    "ticker": rec["ticker"],
                    "category": rec.get("category", "watchlist"),
                    "conviction": rec.get("conviction", "medium"),
                    "thesis": rec.get("thesis", ""),
                    "scores": rec.get("scores", {}),
                },
            )
            published_signals.append({"id": signal_id, "ticker": rec["ticker"]})
        except Exception:
            log.exception("Failed to publish signal for %s", rec.get("ticker"))

    log.info("Published %d discovery signals", len(published_signals))

    # ── Step 7: Format Telegram output ─────────────────────────────────
    total_time = time.time() - pipeline_start
    stats = {
        "mode": scout_mode,
        "candidates_sourced": len(candidates),
        "candidates_screened": len(scored),
        "portfolio_recs": len(portfolio_recs),
        "watchlist_recs": len(watchlist_recs),
        "signals_published": len(published_signals),
        "total_time_s": round(total_time, 1),
        "synthesis_source": synthesis.get("synthesis_source", "unknown"),
        "synthesis_model": synthesis.get("synthesis_model"),
        "synthesis_provider": synthesis.get("synthesis_provider"),
        "synthesis_cost_usd": synthesis.get("synthesis_cost_usd", 0.0),
        "synthesis_candidates": len(synthesis_candidates),
        "candidate_audit": candidate_audit,
        "tracked_ticker_checks": _build_tracked_ticker_checks(
            existing_tickers=existing_tickers,
            candidate_lookup=candidate_lookup,
            scored=scored,
            synthesis_candidates=synthesis_candidates,
            portfolio_recs=portfolio_recs,
            watchlist_recs=watchlist_recs,
            scout_mode=scout_mode,
        ),
    }

    try:
        formatted = format_discovery_report(portfolio_recs, watchlist_recs, stats)
    except Exception:
        log.exception("Failed to format report")
        formatted = "<b>Alpha Scout</b>\n\nError formatting report."

    log.info("Alpha Scout pipeline completed in %.2fs", total_time)
    scout_progress.finish()

    return {
        "formatted": formatted,
        "signals": published_signals,
        "stats": stats,
        "recommendations": {
            "portfolio_recs": portfolio_recs,
            "watchlist_recs": watchlist_recs,
        },
        "scored_candidates": scored,
    }
