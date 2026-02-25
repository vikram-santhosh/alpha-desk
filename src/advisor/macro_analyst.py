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

    # Derived metrics — only compute if FRED spread is missing
    if "yield_curve_spread" not in macro and "treasury_10y" in macro and "treasury_2y" in macro:
        spread = macro["treasury_10y"]["value"] - macro["treasury_2y"]["value"]
        macro["yield_curve_spread_calculated"] = round(spread, 4)
    elif "yield_curve_spread" in macro:
        macro["yield_curve_spread_calculated"] = macro["yield_curve_spread"].get("value")

    macro["fetched_at"] = datetime.now().isoformat()
    macro["date"] = date.today().isoformat()

    log.info("Macro data: %d indicators fetched", len(macro) - 2)  # exclude meta fields
    return macro


def update_macro_theses(macro_data: dict, news_signals: list[dict]) -> list[dict]:
    """Evaluate existing macro theses against new macro data and news signals.

    Reads current theses from memory, enriches them with today's data points,
    persists any new evidence to the database, and returns enriched dicts.

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
    from src.advisor.memory import get_all_macro_theses, update_macro_thesis

    theses = get_all_macro_theses()
    if not theses:
        log.warning("No macro theses in memory — seed them first via config")
        return []

    # First pass: persist evidence for each thesis
    for thesis in theses:
        try:
            title = thesis["title"]
            affected = thesis.get("affected_tickers", [])
            relevant_news = _match_news_to_thesis(title, affected, news_signals)

            if relevant_news:
                evidence_parts = []
                for news in relevant_news[:5]:
                    headline = news.get("headline", "")
                    reason = news.get("match_reason", "")
                    evidence_parts.append(f"[{reason}] {headline}")
                evidence_str = "; ".join(evidence_parts)
                update_macro_thesis(title, thesis.get("status", "intact"), evidence=evidence_str)
                log.info("Persisted %d evidence items for thesis '%s'", len(relevant_news), title)
        except Exception:
            log.exception("Failed to persist evidence for thesis: %s", thesis.get("title"))

    # Re-read all theses once to get updated evidence_logs
    theses = get_all_macro_theses()

    # Second pass: build enriched results
    results = []
    for thesis in theses:
        try:
            title = thesis["title"]
            affected = thesis.get("affected_tickers", [])
            macro_snapshot = _extract_relevant_macro(title, macro_data)
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
    """Return all macro data for every thesis.

    The macro dataset is only ~6 indicators — token cost of including all is
    negligible. Previous keyword-based filtering caused blind spots (e.g.,
    missing tariff impact on growth theses, trade policy effects on rate
    expectations). Let Opus decide what's relevant.
    """
    return {k: v for k, v in macro_data.items() if k not in ("fetched_at", "date")}


def _match_news_to_thesis(thesis_title: str, affected_tickers: list[str],
                          news_signals: list[dict]) -> list[dict]:
    """Find news signals relevant to a macro thesis.

    Matching priority:
    1. Keyword match — thesis title words appear in headline (most specific)
    2. Ticker overlap — signal tickers intersect with thesis tickers
    3. Broad macro fallback — only category="macro" articles get blanket-matched
       to all theses. Geopolitical/regulatory require keyword or ticker match
       to avoid diluting every thesis with irrelevant news.
    """
    title_lower = thesis_title.lower()
    keywords = [w for w in title_lower.split() if len(w) > 3]
    matched = []

    for signal in news_signals:
        try:
            headline = (signal.get("headline") or signal.get("title", "")).lower()
            signal_tickers = signal.get("tickers") or signal.get("affected_tickers") or []
            category = (signal.get("category") or "").lower()

            match_reason = None

            # Priority 1: Keyword match from thesis title (most specific)
            if any(kw in headline for kw in keywords):
                match_reason = "keyword"

            # Priority 2: Ticker overlap
            elif affected_tickers and signal_tickers:
                if set(t.upper() for t in affected_tickers) & set(t.upper() for t in signal_tickers):
                    match_reason = "ticker"

            # Priority 3: Category keyword match
            elif any(kw in category for kw in keywords):
                match_reason = "category"

            # macro_broad fallback removed — it caused every macro article to
            # appear under every thesis, creating duplicate headline spam.
            # Only keyword, ticker, and category matches are specific enough.

            if match_reason:
                matched.append({
                    "headline": signal.get("headline") or signal.get("title", ""),
                    "source": signal.get("source", ""),
                    "tickers": signal_tickers,
                    "match_reason": match_reason,
                })
        except Exception:
            log.exception("Failed to match news signal to thesis")

    return matched[:5]
