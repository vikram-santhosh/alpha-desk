"""Multi-dimensional screening engine for Alpha Scout.

Scores candidates across seven dimensions:
- Technical (0-100): RSI, MACD, golden/death cross, Bollinger Bands, volume
- Fundamental (0-100): P/E, revenue growth, margins, 52-week proximity, market cap
- Sentiment (0-100): Reddit and news sentiment from agent bus signals
- Diversification (0-100): Sector weight relative to current portfolio
- Novelty (0-100): Source freshness and whether the name is already tracked
- Catalyst proximity (0-100): Earnings/catalyst timing and event-bearing source data
- Evidence quality (0-100): Breadth and specificity of source evidence

Produces a normalized weighted composite score used to rank candidates for synthesis.
"""
from __future__ import annotations

from typing import Any

from src.shared.fundamental_quality import (
    explain_fundamental_quality,
    score_fundamental_quality,
)
from src.utils.logger import get_logger

log = get_logger(__name__)


def _is_top_buy_mode(mode: str | None) -> bool:
    return str(mode or "").strip().lower() == "top_buys"


def score_technical(analysis: dict[str, Any], mode: str = "new_discoveries") -> int:
    """Score a candidate on technical indicators (0-100).

    Rubric:
        RSI oversold (<30): +25 | RSI neutral (30-50): +10 | RSI overbought: -10
        MACD bullish crossover: +25 | bearish: -15
        Golden cross: +20 | Death cross: -20
        Below lower Bollinger Band: +15 | Unusual volume (>2x): +15
        Price above SMA-200: +10
    """
    if _is_top_buy_mode(mode):
        return score_top_buy_technical(analysis)

    if not analysis or analysis.get("error"):
        return 50  # neutral baseline for missing data

    score = 0

    # RSI
    rsi_data = analysis.get("rsi", {})
    rsi = rsi_data.get("rsi")
    if rsi is not None:
        if rsi < 30:
            score += 25
        elif 30 <= rsi <= 50:
            score += 10
        elif rsi > 70:
            score -= 10

    # MACD
    macd_data = analysis.get("macd", {})
    if macd_data.get("bullish_crossover"):
        score += 25
    if macd_data.get("bearish_crossover"):
        score -= 15

    # Moving Averages / Crosses
    ma_data = analysis.get("moving_averages", {})
    if ma_data.get("golden_cross"):
        score += 20
    if ma_data.get("death_cross"):
        score -= 20

    # Price above SMA-200
    sma_200 = ma_data.get("sma_200")
    if sma_200 is not None:
        # We need current price — check if it's in the analysis
        # The technical analyzer doesn't store current price directly,
        # but we can infer from bollinger bands middle (SMA-20 ~ current area)
        sma_20 = ma_data.get("sma_20")
        if sma_20 is not None and sma_20 > sma_200:
            score += 10

    # Bollinger Bands
    bb_data = analysis.get("bollinger_bands", {})
    if bb_data.get("below_lower"):
        score += 15

    # Volume
    vol_data = analysis.get("volume", {})
    if vol_data.get("unusual_volume"):
        score += 15

    # Clamp to 0-100
    return max(0, min(100, score))


def score_top_buy_technical(analysis: dict[str, Any]) -> int:
    """Score technicals for top-buy mode.

    Top-buy mode is looking for durable compounders and current buyability,
    not only oversold/reversal setups. A normal uptrend should not score as
    badly as "no signal" just because there was no fresh crossover this week.
    """
    if not analysis or analysis.get("error"):
        return 50

    score = 50

    rsi_data = analysis.get("rsi", {})
    rsi = rsi_data.get("rsi")
    if rsi is not None:
        if 35 <= rsi <= 65:
            score += 8
        elif 30 <= rsi < 35:
            score += 5
        elif 65 < rsi <= 75:
            score += 2
        elif rsi < 25:
            score -= 4
        elif rsi > 80:
            score -= 8

    macd_data = analysis.get("macd", {})
    if macd_data.get("bullish_crossover"):
        score += 12
    if macd_data.get("bearish_crossover"):
        score -= 10

    ma_data = analysis.get("moving_averages", {})
    if ma_data.get("golden_cross"):
        score += 14
    if ma_data.get("death_cross"):
        score -= 20

    sma_20 = ma_data.get("sma_20")
    sma_50 = ma_data.get("sma_50")
    sma_200 = ma_data.get("sma_200")
    if sma_20 is not None and sma_200 is not None:
        if sma_20 > sma_200:
            score += 14
        else:
            score -= 8
    if sma_20 is not None and sma_50 is not None and sma_20 > sma_50:
        score += 5

    bb_data = analysis.get("bollinger_bands", {})
    if bb_data.get("below_lower"):
        score += 5
    if bb_data.get("above_upper"):
        score -= 3

    vol_data = analysis.get("volume", {})
    if vol_data.get("unusual_volume"):
        score += 5

    return max(0, min(100, score))


def score_fundamental(fundamentals: dict[str, Any]) -> int:
    """Score a candidate on fundamental *quality* (0-100).

    Delegates to src.shared.fundamental_quality, the rubric shared with the
    score engine's valuation sensor so both scorers agree on what "good"
    means. See that module's docstring for the rationale.
    """
    return score_fundamental_quality(fundamentals)


def explain_fundamental_factors(fundamentals: dict[str, Any]) -> list[str]:
    """Human-readable, signed factors mirroring ``score_fundamental``'s rubric.

    Powers the cockpit's "why was this scored this way?" debug view.
    Delegates to src.shared.fundamental_quality — update the rubric there.
    """
    return explain_fundamental_quality(fundamentals)


def score_sentiment(candidate: dict[str, Any]) -> int:
    """Score a candidate on sentiment from agent bus signals (0-100).

    Rubric:
        Positive Reddit sentiment (>0.5): +25 | Very positive (>1.0): +15 bonus
        Multiple Reddit mentions: +15 | Multi-sub convergence: +15
        Positive news sentiment: +20 | Negative (<-0.5): -15
        No data: 50 (neutral baseline)
    """
    signal_data = candidate.get("signal_data", {})
    signal_type = candidate.get("signal_type", "")
    source = candidate.get("source", "")

    # No signal data — return neutral
    if not signal_data and signal_type not in ("unusual_mentions", "sentiment_reversal", "multi_sub_convergence"):
        return 50

    score = 0

    # Reddit sentiment
    sentiment = signal_data.get("sentiment") or signal_data.get("avg_sentiment")
    if sentiment is not None:
        if isinstance(sentiment, (int, float)):
            if sentiment > 0.5:
                score += 25
                if sentiment > 1.0:
                    score += 15
            elif sentiment < -0.5:
                score -= 15

    # Multiple mentions
    mentions = signal_data.get("current_mentions") or signal_data.get("mentions")
    if mentions is not None and isinstance(mentions, (int, float)) and mentions > 3:
        score += 15

    # Multi-sub convergence
    if signal_type == "multi_sub_convergence":
        score += 15
    subreddits = signal_data.get("subreddits")
    if isinstance(subreddits, list) and len(subreddits) >= 3:
        score += 15

    # News signals
    if "news" in source.lower():
        relevance = signal_data.get("relevance", 0)
        if relevance and relevance >= 7:
            score += 20
        news_sentiment = signal_data.get("sentiment")
        if news_sentiment is not None and isinstance(news_sentiment, (int, float)):
            if news_sentiment > 0:
                score += 20
            elif news_sentiment < -0.5:
                score -= 15

    # If we got any data at all, ensure a baseline
    if score == 0 and signal_data:
        score = 50

    return max(0, min(100, score))


def score_diversification(
    candidate_sector: str | None,
    portfolio_sector_weights: dict[str, float],
) -> int:
    """Score a candidate on diversification value (0-100).

    Rubric:
        New sector (0% weight): 100
        <10% weight: 80
        10-25%: 60
        25-40%: 40
        >40%: 20
    """
    if not candidate_sector or not portfolio_sector_weights:
        return 80  # Assume some diversification value if unknown

    weight = portfolio_sector_weights.get(candidate_sector, 0.0)

    if weight == 0:
        return 100
    elif weight < 10:
        return 80
    elif weight < 25:
        return 60
    elif weight < 40:
        return 40
    else:
        return 20


def score_novelty(candidate: dict[str, Any], mode: str = "new_discoveries") -> int:
    """Score how fresh a candidate is while avoiding a hard penalty for known winners."""
    source = str(candidate.get("source", "")).lower()
    signal_type = str(candidate.get("signal_type", "")).lower()
    if _is_top_buy_mode(mode):
        if source.startswith("existing_portfolio"):
            return 88
        if source.startswith("existing_watchlist"):
            return 82
    if source.startswith("existing_portfolio"):
        return 45
    if source.startswith("existing_watchlist"):
        return 55
    if any(token in source for token in ("filing", "13f", "thematic", "reddit", "agent_bus")):
        return 80
    if signal_type in {"unusual_mentions", "sentiment_reversal", "multi_sub_convergence"}:
        return 85
    return 65


def score_catalyst_proximity(candidate: dict[str, Any], fundamentals: dict[str, Any]) -> int:
    """Score whether a candidate has near-term events worth reviewing."""
    signal_data = candidate.get("signal_data", {})
    source = str(candidate.get("source", "")).lower()
    score = 50
    if fundamentals.get("next_earnings_date"):
        score += 20
    if any(key in signal_data for key in ("catalyst", "event", "filing_date", "earnings_date")):
        score += 20
    if any(token in source for token in ("filing", "13f", "news", "reddit", "thematic")):
        score += 10
    return max(0, min(100, score))


def score_evidence_quality(candidate: dict[str, Any], fundamentals: dict[str, Any], technicals: dict[str, Any]) -> int:
    """Score source/data breadth so thin candidates do not look as strong as validated names.

    Having fundamentals + a technical read + a signal earns a solid *base*, but the
    top of the range is reserved for *corroboration*: names already in the tracked
    universe (validated by definition) or surfaced by multiple independent sources.
    A lone single-signal discovery (e.g. one supply-chain adjacency plus a golden
    cross) is capped well below a name confirmed across channels, so it cannot
    outrank core holdings on data breadth alone.
    """
    score = 25
    if fundamentals:
        score += 15
    if technicals and not technicals.get("error"):
        score += 10
    if candidate.get("signal_data"):
        score += 5
    if "/" in str(candidate.get("source", "")) or candidate.get("signal_type"):
        score += 5

    corroboration = int(candidate.get("corroboration_count", 1) or 1)
    if _is_existing_candidate(candidate):
        score += 40  # in the portfolio/watchlist already = validated
    else:
        # +18 per additional independent source, capped: a single-source
        # discovery gets no breadth credit and lands ~60.
        score += min(40, max(0, corroboration - 1) * 18)

    return max(0, min(100, score))


def normalize_weights(weights: dict[str, float], mode: str = "new_discoveries") -> dict[str, float]:
    """Return non-negative weights normalized to 1.0 for supported score dimensions."""
    discovery_defaults = {
        "technical": 0.30,
        "fundamental": 0.30,
        "sentiment": 0.15,
        "diversification": 0.10,
        "novelty": 0.05,
        "catalyst_proximity": 0.05,
        "evidence_quality": 0.05,
    }
    top_buy_defaults = {
        "technical": 0.14,
        "fundamental": 0.36,
        "sentiment": 0.06,
        "diversification": 0.04,
        "novelty": 0.03,
        "catalyst_proximity": 0.13,
        "evidence_quality": 0.24,
    }
    if _is_top_buy_mode(mode):
        nested = weights.get("top_buys") if isinstance(weights.get("top_buys"), dict) else None
        source_weights: dict[str, Any] = nested or top_buy_defaults
        supported = top_buy_defaults
    else:
        nested = weights.get("new_discoveries") if isinstance(weights.get("new_discoveries"), dict) else None
        source_weights = nested or weights
        supported = discovery_defaults
    raw = {
        key: max(0.0, float(source_weights.get(key, default) or 0.0))
        for key, default in supported.items()
    }
    total = sum(raw.values())
    if total <= 0:
        raw = dict(supported)
        total = sum(raw.values())
    return {key: value / total for key, value in raw.items()}


def _compute_portfolio_sector_weights(
    fundamentals: dict[str, dict[str, Any]],
    portfolio_tickers: list[str],
) -> dict[str, float]:
    """Compute sector weight percentages for the current portfolio."""
    sector_counts: dict[str, int] = {}
    total = 0

    for ticker in portfolio_tickers:
        fund = fundamentals.get(ticker, {})
        sector = fund.get("sector")
        if sector:
            sector_counts[sector] = sector_counts.get(sector, 0) + 1
            total += 1

    if total == 0:
        return {}

    return {sector: (count / total * 100) for sector, count in sector_counts.items()}


def _is_existing_candidate(candidate: dict[str, Any]) -> bool:
    return str(candidate.get("source", "")).lower().startswith("existing_")


def _top_buy_quality_floor(
    candidate: dict[str, Any],
    fundamentals: dict[str, Any],
    dimension_scores: dict[str, int],
) -> float | None:
    """Return a minimum top-buy score for high-quality tracked names.

    This keeps the top-buy run from treating known holdings/watchlist winners
    like stale discoveries. It is generic: a tracked company must already show
    strong fundamentals and data quality before the floor applies.
    """
    if not _is_existing_candidate(candidate):
        return None
    if dimension_scores["fundamental"] < 85 or dimension_scores["evidence_quality"] < 75:
        return None

    floor = 72.0
    revenue_growth = fundamentals.get("revenue_growth")
    if isinstance(revenue_growth, (int, float)):
        if revenue_growth > 0.20:
            floor += 5.0
        elif revenue_growth > 0.10:
            floor += 3.0
        elif revenue_growth > 0:
            floor += 1.5

    net_margin = fundamentals.get("net_margin")
    if isinstance(net_margin, (int, float)):
        if net_margin > 0.25:
            floor += 4.0
        elif net_margin > 0.15:
            floor += 2.0

    gross_margin = fundamentals.get("gross_margin")
    if isinstance(gross_margin, (int, float)) and gross_margin > 0.55:
        floor += 2.0

    market_cap = fundamentals.get("market_cap")
    if isinstance(market_cap, (int, float)):
        if market_cap > 500_000_000_000:
            floor += 3.0
        elif market_cap > 100_000_000_000:
            floor += 1.5

    pct_from_high = fundamentals.get("pct_from_52w_high")
    if isinstance(pct_from_high, (int, float)):
        if -35 <= pct_from_high <= -8:
            floor += 2.0
        elif pct_from_high < -45:
            floor -= 2.0

    if dimension_scores["technical"] < 25:
        floor -= 3.0

    return max(0.0, min(88.0, floor))


def screen_candidates(
    candidates: list[dict[str, Any]],
    technicals: dict[str, dict[str, Any]],
    fundamentals: dict[str, dict[str, Any]],
    portfolio_tickers: list[str],
    portfolio_fundamentals: dict[str, dict[str, Any]],
    weights: dict[str, float],
    mode: str = "new_discoveries",
) -> list[dict[str, Any]]:
    """Screen all candidates and compute composite scores.

    Args:
        candidates: List of candidate dicts from candidate_sourcer.
        technicals: Dict of ticker -> technical analysis results.
        fundamentals: Dict of ticker -> fundamental data for candidates.
        portfolio_tickers: Current portfolio ticker list.
        portfolio_fundamentals: Fundamentals for portfolio tickers (for sector weights).
        weights: Dimension weights dict. Supported keys are technical,
            fundamental, sentiment, diversification, novelty,
            catalyst_proximity, and evidence_quality.

    Returns:
        List of candidate dicts enriched with scores, sorted by composite descending.
    """
    scout_mode = "top_buys" if _is_top_buy_mode(mode) else "new_discoveries"
    normalized_weights = normalize_weights(weights, mode=scout_mode)

    # Compute portfolio sector weights for diversification scoring
    sector_weights = _compute_portfolio_sector_weights(portfolio_fundamentals, portfolio_tickers)

    scored: list[dict[str, Any]] = []

    for candidate in candidates:
        ticker = candidate["ticker"]

        # Technical score
        tech_data = technicals.get(ticker, {})
        tech_score = score_technical(tech_data, mode=scout_mode)

        # Fundamental score
        fund_data = fundamentals.get(ticker, {})
        fund_score = score_fundamental(fund_data)

        # Sentiment score
        sent_score = score_sentiment(candidate)

        # Diversification score
        candidate_sector = fund_data.get("sector")
        div_score = score_diversification(candidate_sector, sector_weights)
        if scout_mode == "top_buys" and _is_existing_candidate(candidate):
            div_score = max(div_score, 68)

        novelty_score = score_novelty(candidate, mode=scout_mode)
        catalyst_score = score_catalyst_proximity(candidate, fund_data)
        evidence_score = score_evidence_quality(candidate, fund_data, tech_data)

        dimension_scores = {
            "technical": tech_score,
            "fundamental": fund_score,
            "sentiment": sent_score,
            "diversification": div_score,
            "novelty": novelty_score,
            "catalyst_proximity": catalyst_score,
            "evidence_quality": evidence_score,
        }

        composite = sum(
            normalized_weights[name] * score
            for name, score in dimension_scores.items()
        )
        quality_floor = (
            _top_buy_quality_floor(candidate, fund_data, dimension_scores)
            if scout_mode == "top_buys"
            else None
        )
        if quality_floor is not None and quality_floor > composite:
            # Lift high-quality tracked names toward the floor, but PARTIALLY, so
            # genuinely different names keep different scores instead of all being
            # hard-pinned to the same floor value (which made every card read 88).
            composite = composite + 0.5 * (quality_floor - composite)

        scored.append({
            **candidate,
            "scores": {
                **dimension_scores,
                "weights": normalized_weights,
                "composite": round(composite, 1),
                "top_buy_quality_floor": round(quality_floor, 1) if quality_floor is not None else None,
            },
            "fundamentals_summary": {
                "pe_trailing": fund_data.get("pe_trailing"),
                "revenue_growth": fund_data.get("revenue_growth"),
                "net_margin": fund_data.get("net_margin"),
                "gross_margin": fund_data.get("gross_margin"),
                "market_cap": fund_data.get("market_cap"),
                "sector": candidate_sector,
                "pct_from_52w_high": fund_data.get("pct_from_52w_high"),
                "next_earnings_date": fund_data.get("next_earnings_date"),
                "target_mean_price": fund_data.get("target_mean_price"),
                "implied_upside_pct": fund_data.get("implied_upside_pct"),
                "peg_ratio": fund_data.get("peg_ratio"),
                "ev_to_ebitda": fund_data.get("ev_to_ebitda"),
            },
            "technical_summary": tech_data.get("signals_summary", []),
        })

    # Sort by composite score descending
    scored.sort(key=lambda x: x["scores"]["composite"], reverse=True)

    log.info(
        "Screened %d candidates. Top score: %.1f, Bottom: %.1f",
        len(scored),
        scored[0]["scores"]["composite"] if scored else 0,
        scored[-1]["scores"]["composite"] if scored else 0,
    )

    return scored
