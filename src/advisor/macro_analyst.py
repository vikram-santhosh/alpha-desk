"""Macro data fetcher and thesis tracker for AlphaDesk Advisor.

Fetches macro indicators from FRED API and yfinance, then evaluates
existing macro theses against new data and news signals.
"""

import os
from datetime import date, datetime

from src.utils.logger import get_logger

log = get_logger(__name__)

# FRED series we care about
FRED_SERIES = {
    "FEDFUNDS": "fed_funds_rate",
    "DGS10": "treasury_10y",
    "DGS2": "treasury_2y",
    "T10Y2Y": "yield_curve_spread",
}

# yfinance tickers for market data
YF_TICKERS = {
    "^VIX": "vix",
    "^GSPC": "sp500",
}


def _fetch_fred_data() -> dict:
    """Fetch macro series from FRED API. Returns empty dict if key is missing."""
    api_key = os.getenv("FRED_API_KEY", "")
    if not api_key:
        log.warning("FRED_API_KEY not set — skipping FRED data, using yfinance only")
        return {}

    results = {}
    try:
        from fredapi import Fred
        fred = Fred(api_key=api_key)
    except Exception:
        log.exception("Failed to initialize FRED client")
        return {}

    for series_id, label in FRED_SERIES.items():
        try:
            data = fred.get_series(series_id, observation_start="2024-01-01")
            if data is not None and len(data) > 0:
                latest = data.dropna().iloc[-1]
                results[label] = {
                    "value": round(float(latest), 4),
                    "date": str(data.dropna().index[-1].date()),
                    "series": series_id,
                }
                log.info("FRED %s: %.4f", series_id, float(latest))
        except Exception:
            log.exception("Failed to fetch FRED series %s", series_id)

    return results


def _fetch_yfinance_data() -> dict:
    """Fetch VIX and S&P 500 from yfinance."""
    results = {}
    try:
        import yfinance as yf
    except ImportError:
        log.error("yfinance not installed — cannot fetch market data")
        return {}

    for ticker_symbol, label in YF_TICKERS.items():
        try:
            ticker = yf.Ticker(ticker_symbol)
            hist = ticker.history(period="5d")
            if hist is not None and not hist.empty:
                latest_close = float(hist["Close"].iloc[-1])
                prev_close = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else None
                change_pct = None
                if prev_close and prev_close > 0:
                    change_pct = round((latest_close - prev_close) / prev_close * 100, 2)
                results[label] = {
                    "value": round(latest_close, 2),
                    "change_pct": change_pct,
                    "date": str(hist.index[-1].date()),
                }
                log.info("%s (%s): %.2f", label, ticker_symbol, latest_close)
        except Exception:
            log.exception("Failed to fetch yfinance ticker %s", ticker_symbol)

    return results


def fetch_macro_data() -> dict:
    """Fetch all macro indicators from FRED and yfinance.

    Returns a dict with keys like 'fed_funds_rate', 'treasury_10y',
    'yield_curve_spread', 'vix', 'sp500', each containing value/date/change.
    Always returns at least yfinance data even if FRED key is missing.
    """
    log.info("Fetching macro data")
    macro = {}

    # FRED data (rates, yields)
    fred_data = _fetch_fred_data()
    macro.update(fred_data)

    # yfinance data (VIX, S&P 500)
    yf_data = _fetch_yfinance_data()
    macro.update(yf_data)

    # Derived metrics
    if "treasury_10y" in macro and "treasury_2y" in macro:
        spread = macro["treasury_10y"]["value"] - macro["treasury_2y"]["value"]
        macro["yield_curve_spread_calculated"] = round(spread, 4)

    macro["fetched_at"] = datetime.now().isoformat()
    macro["date"] = date.today().isoformat()

    log.info("Macro data: %d indicators fetched", len(macro) - 2)  # exclude meta fields
    return macro


def update_macro_theses(macro_data: dict, news_signals: list[dict]) -> list[dict]:
    """Evaluate existing macro theses against new macro data and news signals.

    Reads current theses from memory, enriches them with today's data points,
    and returns a list of thesis dicts with suggested status updates.
    The orchestrator / Opus synthesis step uses these to update memory.

    Args:
        macro_data: Output from fetch_macro_data().
        news_signals: List of news signal dicts (from News Desk agent bus),
                      each having at least 'headline' and optionally 'tickers', 'category'.

    Returns:
        List of dicts, each with:
          - title: thesis title
          - current_status: status from memory
          - macro_snapshot: relevant macro data points
          - relevant_news: news items that touch this thesis
          - affected_tickers: list of tickers
    """
    from src.advisor.memory import get_all_macro_theses

    theses = get_all_macro_theses()
    if not theses:
        log.warning("No macro theses in memory — seed them first via config")
        return []

    results = []
    for thesis in theses:
        try:
            title = thesis["title"]
            affected = thesis.get("affected_tickers", [])

            # Collect macro data points relevant to this thesis
            macro_snapshot = _extract_relevant_macro(title, macro_data)

            # Find news signals relevant to this thesis
            relevant_news = _match_news_to_thesis(title, affected, news_signals)

            results.append({
                "title": title,
                "description": thesis.get("description", ""),
                "current_status": thesis.get("status", "intact"),
                "created_date": thesis.get("created_date"),
                "last_updated": thesis.get("last_updated"),
                "affected_tickers": affected,
                "evidence_log": thesis.get("evidence_log", []),
                "macro_snapshot": macro_snapshot,
                "relevant_news": relevant_news,
            })
        except Exception:
            log.exception("Failed to process thesis: %s", thesis.get("title"))

    log.info("Processed %d macro theses", len(results))
    return results


def _extract_relevant_macro(thesis_title: str, macro_data: dict) -> dict:
    """Extract macro data points relevant to a specific thesis."""
    title_lower = thesis_title.lower()
    snapshot = {}

    # Fed / rate-related theses
    if any(kw in title_lower for kw in ("fed", "rate", "easing", "monetary")):
        for key in ("fed_funds_rate", "treasury_10y", "treasury_2y",
                     "yield_curve_spread", "yield_curve_spread_calculated"):
            if key in macro_data:
                snapshot[key] = macro_data[key]

    # Market volatility / risk-related theses
    if any(kw in title_lower for kw in ("vix", "volatility", "risk", "recession")):
        if "vix" in macro_data:
            snapshot["vix"] = macro_data["vix"]

    # Broad market / growth theses
    if any(kw in title_lower for kw in ("capex", "growth", "saas", "rotation",
                                         "stimulus", "fiscal", "market")):
        if "sp500" in macro_data:
            snapshot["sp500"] = macro_data["sp500"]
        if "vix" in macro_data:
            snapshot["vix"] = macro_data["vix"]

    # If nothing matched, include everything — let Opus decide relevance
    if not snapshot:
        snapshot = {k: v for k, v in macro_data.items()
                    if k not in ("fetched_at", "date")}

    return snapshot


def _match_news_to_thesis(thesis_title: str, affected_tickers: list[str],
                          news_signals: list[dict]) -> list[dict]:
    """Find news signals relevant to a macro thesis."""
    title_lower = thesis_title.lower()
    keywords = title_lower.split()
    matched = []

    for signal in news_signals:
        try:
            headline = signal.get("headline", "").lower()
            signal_tickers = signal.get("tickers", [])
            category = signal.get("category", "").lower()

            # Match by keyword overlap
            keyword_match = any(kw in headline for kw in keywords if len(kw) > 3)

            # Match by ticker overlap
            ticker_match = bool(
                set(t.upper() for t in signal_tickers) &
                set(t.upper() for t in affected_tickers)
            ) if affected_tickers and signal_tickers else False

            # Match by category
            category_match = any(kw in category for kw in keywords if len(kw) > 3)

            if keyword_match or ticker_match or category_match:
                matched.append({
                    "headline": signal.get("headline", ""),
                    "source": signal.get("source", ""),
                    "tickers": signal_tickers,
                    "match_reason": "keyword" if keyword_match
                                    else "ticker" if ticker_match
                                    else "category",
                })
        except Exception:
            log.exception("Failed to match news signal to thesis")

    return matched[:10]  # Cap at 10 most relevant
