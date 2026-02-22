"""Multi-dimensional screening engine for Alpha Scout.

Scores candidates across four dimensions:
- Technical (0-100): RSI, MACD, golden/death cross, Bollinger Bands, volume
- Fundamental (0-100): P/E, revenue growth, margins, 52-week proximity, market cap
- Sentiment (0-100): Reddit and news sentiment from agent bus signals
- Diversification (0-100): Sector weight relative to current portfolio

Produces a weighted composite score used to rank candidates for Opus 4.6 synthesis.
"""

from typing import Any

from src.utils.logger import get_logger

log = get_logger(__name__)


def score_technical(analysis: dict[str, Any]) -> int:
    """Score a candidate on technical indicators (0-100).

    Rubric:
        RSI oversold (<30): +25 | RSI neutral (30-50): +10 | RSI overbought: -10
        MACD bullish crossover: +25 | bearish: -15
        Golden cross: +20 | Death cross: -20
        Below lower Bollinger Band: +15 | Unusual volume (>2x): +15
        Price above SMA-200: +10
    """
    if analysis.get("error"):
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


def score_fundamental(fundamentals: dict[str, Any]) -> int:
    """Score a candidate on fundamental metrics (0-100).

    Rubric:
        P/E 10-30: +20 | P/E <10: +10 | P/E >50: -10
        Positive revenue growth: +20 | >20% growth: +10 bonus
        Positive net margin: +15 | Gross margin >40%: +10
        >10% below 52wk high: +15 | Near 52wk low (<10% above): +10
        Market cap >$10B: +5
    """
    if not fundamentals:
        return 50  # neutral baseline

    score = 0

    # P/E ratio
    pe = fundamentals.get("pe_trailing")
    if pe is not None:
        if 10 <= pe <= 30:
            score += 20
        elif 0 < pe < 10:
            score += 10
        elif pe > 50:
            score -= 10

    # Revenue growth
    rev_growth = fundamentals.get("revenue_growth")
    if rev_growth is not None:
        if rev_growth > 0:
            score += 20
            if rev_growth > 0.20:
                score += 10

    # Margins
    net_margin = fundamentals.get("net_margin")
    if net_margin is not None and net_margin > 0:
        score += 15

    gross_margin = fundamentals.get("gross_margin")
    if gross_margin is not None and gross_margin > 0.40:
        score += 10

    # 52-week proximity
    pct_from_high = fundamentals.get("pct_from_52w_high")
    pct_from_low = fundamentals.get("pct_from_52w_low")

    if pct_from_high is not None and pct_from_high < -10:
        score += 15
    if pct_from_low is not None and pct_from_low < 10:
        score += 10

    # Market cap
    market_cap = fundamentals.get("market_cap")
    if market_cap is not None and market_cap > 10_000_000_000:
        score += 5

    return max(0, min(100, score))


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


def screen_candidates(
    candidates: list[dict[str, Any]],
    technicals: dict[str, dict[str, Any]],
    fundamentals: dict[str, dict[str, Any]],
    portfolio_tickers: list[str],
    portfolio_fundamentals: dict[str, dict[str, Any]],
    weights: dict[str, float],
) -> list[dict[str, Any]]:
    """Screen all candidates and compute composite scores.

    Args:
        candidates: List of candidate dicts from candidate_sourcer.
        technicals: Dict of ticker -> technical analysis results.
        fundamentals: Dict of ticker -> fundamental data for candidates.
        portfolio_tickers: Current portfolio ticker list.
        portfolio_fundamentals: Fundamentals for portfolio tickers (for sector weights).
        weights: Dimension weights dict (technical, fundamental, sentiment, diversification).

    Returns:
        List of candidate dicts enriched with scores, sorted by composite descending.
    """
    w_tech = weights.get("technical", 0.30)
    w_fund = weights.get("fundamental", 0.30)
    w_sent = weights.get("sentiment", 0.20)
    w_div = weights.get("diversification", 0.20)

    # Compute portfolio sector weights for diversification scoring
    sector_weights = _compute_portfolio_sector_weights(portfolio_fundamentals, portfolio_tickers)

    scored: list[dict[str, Any]] = []

    for candidate in candidates:
        ticker = candidate["ticker"]

        # Technical score
        tech_data = technicals.get(ticker, {})
        tech_score = score_technical(tech_data)

        # Fundamental score
        fund_data = fundamentals.get(ticker, {})
        fund_score = score_fundamental(fund_data)

        # Sentiment score
        sent_score = score_sentiment(candidate)

        # Diversification score
        candidate_sector = fund_data.get("sector")
        div_score = score_diversification(candidate_sector, sector_weights)

        # Weighted composite
        composite = (
            w_tech * tech_score
            + w_fund * fund_score
            + w_sent * sent_score
            + w_div * div_score
        )

        scored.append({
            **candidate,
            "scores": {
                "technical": tech_score,
                "fundamental": fund_score,
                "sentiment": sent_score,
                "diversification": div_score,
                "composite": round(composite, 1),
            },
            "fundamentals_summary": {
                "pe_trailing": fund_data.get("pe_trailing"),
                "revenue_growth": fund_data.get("revenue_growth"),
                "market_cap": fund_data.get("market_cap"),
                "sector": candidate_sector,
                "pct_from_52w_high": fund_data.get("pct_from_52w_high"),
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
