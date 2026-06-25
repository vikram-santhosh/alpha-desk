"""Macro data fetcher and thesis tracker for AlphaDesk Advisor.

Fetches macro indicators from FRED API and yfinance, then evaluates
existing macro theses against new data and news signals.
"""

import os
import math
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
    "CL=F": "oil_wti",
    "GC=F": "gold",
    "HG=F": "copper",
    "DX-Y.NYB": "usd_index",
    "NG=F": "nat_gas",
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
                if not math.isfinite(latest_close):
                    log.warning("Skipping yfinance ticker %s because latest close is not finite", ticker_symbol)
                    continue
                prev_close = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else None
                change_pct = None
                if prev_close and math.isfinite(prev_close) and prev_close > 0:
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


def update_macro_theses(
    macro_data: dict,
    news_signals: list[dict],
    prediction_markets: list[dict] | None = None,
    *,
    macro_easing_prob_threshold: float = 0.30,
) -> list[dict]:
    """Evaluate existing macro theses against new macro data and news signals.

    Reads current theses from memory, enriches them with today's data points,
    persists any new evidence to the database, and returns enriched dicts.

    Args:
        macro_data: Output from fetch_macro_data().
        news_signals: List of news signal dicts (from News Desk agent bus),
                      each having at least 'headline' and optionally 'tickers', 'category'.
        prediction_markets: Optional prediction-market rows from prediction_market.fetch_prediction_markets().
        macro_easing_prob_threshold: Minimum market-implied cut odds before a rate-easing
                                     thesis is considered intact.

    Returns:
        List of dicts, each with:
          - title: thesis title
          - current_status: status from memory
          - macro_snapshot: relevant macro data points
          - relevant_news: news items that touch this thesis
          - affected_tickers: list of tickers
    """
    from src.advisor.memory import get_all_macro_theses, update_macro_thesis

    prediction_markets = prediction_markets or []
    fed_policy_context = _summarize_fed_policy_markets(
        prediction_markets,
        cut_threshold=macro_easing_prob_threshold,
    )

    theses = get_all_macro_theses()
    if not theses:
        log.warning("No macro theses in memory — seed them first via config")
        return []

    _apply_rate_easing_guardrail(
        theses,
        fed_policy_context,
        cut_threshold=macro_easing_prob_threshold,
        update_macro_thesis=update_macro_thesis,
    )
    theses = get_all_macro_theses()

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
            prediction_context = _match_prediction_markets_to_thesis(
                title,
                affected,
                prediction_markets,
                fed_policy_context,
            )
            if prediction_context:
                macro_snapshot["prediction_markets"] = prediction_context

            results.append({
                "title": title,
                "description": thesis.get("description", ""),
                "current_status": thesis.get("status", "intact"),
                "status": thesis.get("status", "intact"),
                "created_date": thesis.get("created_date"),
                "last_updated": thesis.get("last_updated"),
                "affected_tickers": affected,
                "evidence_log": thesis.get("evidence_log", []),
                "macro_snapshot": macro_snapshot,
                "relevant_news": relevant_news,
                "prediction_context": prediction_context,
            })
        except Exception:
            log.exception("Failed to process thesis: %s", thesis.get("title"))

    log.info("Processed %d macro theses", len(results))
    return results


def _summarize_fed_policy_markets(
    prediction_markets: list[dict],
    *,
    cut_threshold: float,
) -> dict:
    fed_markets = [
        market for market in prediction_markets
        if market.get("category") == "fed_policy" or _looks_like_fed_policy(market.get("title", ""))
    ]
    summary = {
        "markets": fed_markets,
        "cut_probability": None,
        "flat_or_hike_probability": None,
        "implied_path": "unknown",
        "evidence_market": None,
        "threshold": cut_threshold,
    }
    cut_candidates: list[tuple[float, dict]] = []
    flat_or_hike_candidates: list[tuple[float, dict]] = []

    for market in fed_markets:
        try:
            probability = float(market.get("probability", 0))
        except (TypeError, ValueError):
            continue
        probability = max(0.0, min(1.0, probability))
        classification = _classify_fed_policy_market(market.get("title", ""))
        if classification == "cut":
            cut_candidates.append((probability, market))
        elif classification == "flat_or_hike":
            flat_or_hike_candidates.append((probability, market))

    if cut_candidates:
        cut_probability, evidence_market = max(cut_candidates, key=lambda item: item[0])
        summary["cut_probability"] = cut_probability
        summary["evidence_market"] = evidence_market

    if flat_or_hike_candidates:
        flat_or_hike_probability, flat_market = max(flat_or_hike_candidates, key=lambda item: item[0])
        summary["flat_or_hike_probability"] = flat_or_hike_probability
        if summary["cut_probability"] is None:
            summary["cut_probability"] = max(0.0, 1.0 - flat_or_hike_probability)
            summary["evidence_market"] = flat_market

    cut_probability = summary["cut_probability"]
    flat_or_hike_probability = summary["flat_or_hike_probability"]
    if cut_probability is not None and cut_probability >= cut_threshold:
        summary["implied_path"] = "cutting"
    elif flat_or_hike_probability is not None and flat_or_hike_probability >= 0.50:
        summary["implied_path"] = "flat_or_hiking"
    elif cut_probability is not None:
        summary["implied_path"] = "low_cut_odds"

    return summary


def _apply_rate_easing_guardrail(
    theses: list[dict],
    fed_policy_context: dict,
    *,
    cut_threshold: float,
    update_macro_thesis,
) -> None:
    cut_probability = fed_policy_context.get("cut_probability")
    if cut_probability is None:
        return
    if cut_probability >= cut_threshold and fed_policy_context.get("implied_path") != "flat_or_hiking":
        return

    evidence_market = fed_policy_context.get("evidence_market") or {}
    market_title = evidence_market.get("title") or evidence_market.get("market_title") or "fed_policy market"
    platform = evidence_market.get("platform", "prediction market")
    evidence = (
        f"Prediction market {platform} '{market_title}' implies "
        f"{cut_probability * 100:.0f}% rate-cut odds, below the "
        f"{cut_threshold * 100:.0f}% guardrail threshold."
    )
    status = "broken" if cut_probability < cut_threshold / 2 else "weakening"

    for thesis in theses:
        if not _is_rate_easing_thesis(thesis):
            continue
        try:
            update_macro_thesis(thesis["title"], status, evidence=evidence)
            log.info("Macro guardrail marked '%s' as %s", thesis["title"], status)
        except Exception:
            log.exception("Failed to apply macro guardrail to %s", thesis.get("title"))


def _match_prediction_markets_to_thesis(
    thesis_title: str,
    affected_tickers: list[str],
    prediction_markets: list[dict],
    fed_policy_context: dict,
) -> list[dict]:
    title_lower = thesis_title.lower()
    affected = {ticker.upper() for ticker in affected_tickers}
    relevant: list[dict] = []

    for market in prediction_markets:
        category = market.get("category")
        market_tickers = {ticker.upper() for ticker in (market.get("affected_tickers") or [])}
        is_relevant = (
            category in {"fed_policy", "recession", "fiscal_policy"}
            or bool(affected & market_tickers)
            or (category and category.replace("_", " ") in title_lower)
        )
        if not is_relevant:
            continue
        relevant.append({
            "platform": market.get("platform", ""),
            "title": market.get("title") or market.get("market_title", ""),
            "category": category or "",
            "probability": market.get("probability", 0),
            "url": market.get("url", ""),
        })

    if _looks_like_fed_policy(thesis_title) and fed_policy_context.get("cut_probability") is not None:
        relevant.insert(0, {
            "platform": "derived",
            "title": "Market-implied Fed cut odds",
            "category": "fed_policy",
            "probability": fed_policy_context.get("cut_probability", 0),
            "implied_path": fed_policy_context.get("implied_path", "unknown"),
        })

    return relevant[:5]


def _looks_like_fed_policy(text: str) -> bool:
    lower = (text or "").lower()
    return any(term in lower for term in ("fed", "fomc", "rate", "monetary"))


def _classify_fed_policy_market(title: str) -> str:
    lower = (title or "").lower()
    flat_terms = (
        "no rate cut", "no cuts", "zero rate cuts", "hold rates", "rates unchanged",
        "unchanged rates", "pause", "higher for longer",
    )
    cut_terms = ("rate cut", "rate cuts", "cut rates", "cuts rates", "lower rates", "easing")
    hike_terms = ("rate hike", "rate hikes", "hike rates", "raise rates", "higher rates")
    if any(term in lower for term in flat_terms):
        return "flat_or_hike"
    if any(term in lower for term in hike_terms):
        return "flat_or_hike"
    if any(term in lower for term in cut_terms):
        return "cut"
    return "fed_policy"


def _is_rate_easing_thesis(thesis: dict) -> bool:
    text = f"{thesis.get('title', '')} {thesis.get('description', '')}".lower()
    easing_terms = (
        "easing", "rate cut", "rate cuts", "cut rates", "lower rates",
        "dollar weakening", "growth tailwind",
    )
    return any(term in text for term in easing_terms)


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
