"""Earnings call intelligence for AlphaDesk Advisor.

Fetches earnings data (beat/miss, guidance, transcripts) and analyzes
transcripts with Opus to extract forward-looking signals, management tone,
cross-company mentions, and CapEx guidance. Stores everything in memory
for use by the daily brief.

Primary source: Financial Modeling Prep (FMP) API if FMP_API_KEY is set.
Fallback: yfinance earnings data.
"""

import json
import os
from datetime import date, datetime
from typing import Any

import anthropic
import requests
import yfinance as yf

from src.advisor import memory
from src.shared.cost_tracker import check_budget, record_usage
from src.utils.logger import get_logger

log = get_logger(__name__)

FMP_API_KEY = os.getenv("FMP_API_KEY", "")
FMP_BASE = "https://financialmodelingprep.com/api/v3"


def _current_quarter() -> tuple[int, int]:
    """Return (year, quarter_number) for the most recently completed quarter."""
    today = date.today()
    month = today.month
    # Current calendar quarter (1-4)
    current_q = (month - 1) // 3 + 1
    # Most recently *completed* quarter is one before current
    completed_q = current_q - 1
    if completed_q == 0:
        return today.year - 1, 4
    return today.year, completed_q


def _quarter_label(year: int, quarter: int) -> str:
    """Format a quarter label like '2025Q4'."""
    return f"{year}Q{quarter}"


# ═══════════════════════════════════════════════════════
# DATA FETCHING
# ═══════════════════════════════════════════════════════

def _fetch_fmp_transcript(ticker: str, year: int, quarter: int) -> str | None:
    """Fetch an earnings call transcript from Financial Modeling Prep."""
    if not FMP_API_KEY:
        return None
    url = f"{FMP_BASE}/earning_call_transcript/{ticker}"
    params = {"quarter": quarter, "year": year, "apikey": FMP_API_KEY}
    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data and isinstance(data, list) and len(data) > 0:
            return data[0].get("content", "")
    except Exception:
        log.exception("FMP transcript fetch failed for %s Q%d %d", ticker, quarter, year)
    return None


def _fetch_fmp_earnings_surprise(ticker: str) -> dict[str, Any] | None:
    """Fetch the latest earnings surprise (beat/miss) from FMP."""
    if not FMP_API_KEY:
        return None
    url = f"{FMP_BASE}/earnings-surprises/{ticker}"
    params = {"apikey": FMP_API_KEY}
    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data and isinstance(data, list) and len(data) > 0:
            latest = data[0]
            return {
                "eps_actual": latest.get("actualEarningResult"),
                "eps_estimate": latest.get("estimatedEarning"),
                "date": latest.get("date"),
            }
    except Exception:
        log.exception("FMP earnings surprise fetch failed for %s", ticker)
    return None


def _fetch_yfinance_earnings(ticker: str) -> dict[str, Any]:
    """Fallback: fetch earnings data from yfinance."""
    result: dict[str, Any] = {}
    try:
        tk = yf.Ticker(ticker)

        # Earnings history (actual vs estimate EPS)
        hist = tk.earnings_history
        if hist is not None and not hist.empty:
            latest = hist.iloc[0]
            result["eps_actual"] = _safe_float(latest.get("epsActual"))
            result["eps_estimate"] = _safe_float(latest.get("epsEstimate"))

        # Earnings dates (upcoming and past)
        dates = tk.earnings_dates
        if dates is not None and not dates.empty:
            past = dates[dates.index <= datetime.now()]
            if not past.empty:
                last_row = past.iloc[0]
                if "EPS Estimate" in last_row.index:
                    result.setdefault("eps_estimate", _safe_float(last_row.get("EPS Estimate")))
                if "Reported EPS" in last_row.index:
                    result.setdefault("eps_actual", _safe_float(last_row.get("Reported EPS")))
                if "Surprise(%)" in last_row.index:
                    result["surprise_pct"] = _safe_float(last_row.get("Surprise(%)"))

        # Revenue forecasts
        rev = tk.revenue_forecasts
        if rev is not None and not rev.empty:
            result["revenue_estimate"] = _safe_float(rev.iloc[0].get("avg"))

    except Exception:
        log.exception("yfinance earnings fetch failed for %s", ticker)
    return result


def _safe_float(val: Any) -> float | None:
    """Safely convert a value to float, returning None on failure."""
    if val is None:
        return None
    try:
        f = float(val)
        # pandas NaN check
        if f != f:
            return None
        return f
    except (ValueError, TypeError):
        return None


def fetch_earnings_data(tickers: list[str]) -> dict[str, dict]:
    """Fetch earnings data for a list of tickers.

    Primary source: FMP API (if FMP_API_KEY is set).
    Fallback: yfinance earnings data.

    Returns dict mapping ticker -> earnings data dict with keys:
        eps_actual, eps_estimate, revenue_actual, revenue_estimate,
        surprise_pct, transcript (if available), quarter, year.
    """
    year, quarter = _current_quarter()
    label = _quarter_label(year, quarter)
    results: dict[str, dict] = {}

    for ticker in tickers:
        log.info("Fetching earnings data for %s (%s)", ticker, label)
        data: dict[str, Any] = {"ticker": ticker, "quarter": label, "year": year, "quarter_num": quarter}

        # Try FMP first for earnings surprise data
        fmp_surprise = _fetch_fmp_earnings_surprise(ticker)
        if fmp_surprise:
            data["eps_actual"] = fmp_surprise.get("eps_actual")
            data["eps_estimate"] = fmp_surprise.get("eps_estimate")
            data["call_date"] = fmp_surprise.get("date", date.today().isoformat())
            log.info("FMP earnings surprise loaded for %s", ticker)

        # Try FMP for transcript
        transcript = _fetch_fmp_transcript(ticker, year, quarter)
        if transcript:
            data["transcript"] = transcript
            log.info("FMP transcript loaded for %s (%d chars)", ticker, len(transcript))

        # Fallback to yfinance if we don't have EPS data
        if data.get("eps_actual") is None:
            yf_data = _fetch_yfinance_earnings(ticker)
            if yf_data:
                data.update({k: v for k, v in yf_data.items() if k not in data or data[k] is None})
                log.info("yfinance earnings loaded for %s", ticker)

        data.setdefault("call_date", date.today().isoformat())
        results[ticker] = data

    log.info("Fetched earnings data for %d tickers", len(results))
    return results


# ═══════════════════════════════════════════════════════
# TRANSCRIPT ANALYSIS (OPUS)
# ═══════════════════════════════════════════════════════

_TRANSCRIPT_PROMPT = """\
You are a senior equity analyst. Analyze this earnings call transcript for {ticker} ({quarter}).

Extract the following as JSON (no markdown, just raw JSON):

{{
  "guidance_sentiment": "raised" | "maintained" | "lowered" | "withdrawn" | "not_discussed",
  "key_quotes": ["<top 3-5 forward-looking management quotes>"],
  "management_tone": "confident" | "cautious" | "defensive",
  "mentioned_companies": ["<list of other public company tickers mentioned>"],
  "capex_guidance": <number in billions USD if mentioned, else null>,
  "transcript_summary": "<2-3 sentence summary focusing on guidance, demand signals, and key risks>",
  "guidance_revenue_low": <number if mentioned, else null>,
  "guidance_revenue_high": <number if mentioned, else null>,
  "guidance_eps_low": <number if mentioned, else null>,
  "guidance_eps_high": <number if mentioned, else null>
}}

Rules:
- For mentioned_companies, use standard US ticker symbols (e.g. NVDA, MSFT, GOOG). Only include publicly traded companies.
- For key_quotes, pick the most forward-looking statements about demand, pricing, market share, new products, or competitive dynamics.
- guidance_sentiment: "raised" if forward guidance was increased vs prior quarter, "lowered" if decreased, "maintained" if reiterated, "withdrawn" if pulled, "not_discussed" if no forward guidance given.
- capex_guidance should be in billions of USD (e.g. 80.0 for $80B).
- Be precise. Do not hallucinate numbers.

TRANSCRIPT:
{transcript}
"""


def analyze_transcript(ticker: str, transcript_text: str) -> dict[str, Any]:
    """Analyze an earnings call transcript using Opus.

    Extracts guidance sentiment, key quotes, management tone, mentioned
    companies, CapEx guidance, and a summary.

    Returns dict matching the earnings_calls table schema fields.
    """
    year, quarter = _current_quarter()
    label = _quarter_label(year, quarter)

    # Budget check before expensive Opus call
    within_budget, spent, cap = check_budget()
    if not within_budget:
        log.warning("Budget exceeded ($%.2f / $%.2f) — skipping transcript analysis for %s",
                     spent, cap, ticker)
        return {
            "ticker": ticker,
            "quarter": label,
            "call_date": date.today().isoformat(),
            "transcript_summary": "Skipped — daily API budget exceeded.",
        }

    # Truncate very long transcripts to stay within token limits
    max_chars = 100_000
    if len(transcript_text) > max_chars:
        transcript_text = transcript_text[:max_chars] + "\n\n[TRANSCRIPT TRUNCATED]"

    prompt = _TRANSCRIPT_PROMPT.format(
        ticker=ticker,
        quarter=label,
        transcript=transcript_text,
    )

    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )

        # Record cost
        usage = response.usage
        record_usage("advisor_earnings", usage.input_tokens, usage.output_tokens)

        # Parse the JSON response
        raw_text = response.content[0].text.strip()
        # Handle potential markdown code blocks in response
        if raw_text.startswith("```"):
            raw_text = raw_text.split("\n", 1)[1]
            if raw_text.endswith("```"):
                raw_text = raw_text[:-3]
            raw_text = raw_text.strip()
        analysis = json.loads(raw_text)

        result: dict[str, Any] = {
            "ticker": ticker,
            "quarter": label,
            "call_date": date.today().isoformat(),
            "guidance_sentiment": analysis.get("guidance_sentiment"),
            "key_quotes": analysis.get("key_quotes", []),
            "management_tone": analysis.get("management_tone"),
            "mentioned_companies": analysis.get("mentioned_companies", []),
            "capex_guidance": analysis.get("capex_guidance"),
            "transcript_summary": analysis.get("transcript_summary"),
            "guidance_revenue_low": analysis.get("guidance_revenue_low"),
            "guidance_revenue_high": analysis.get("guidance_revenue_high"),
            "guidance_eps_low": analysis.get("guidance_eps_low"),
            "guidance_eps_high": analysis.get("guidance_eps_high"),
        }
        log.info("Transcript analysis complete for %s: tone=%s, sentiment=%s, mentions=%d companies",
                 ticker, result.get("management_tone"), result.get("guidance_sentiment"),
                 len(result.get("mentioned_companies", [])))
        return result

    except json.JSONDecodeError:
        log.exception("Failed to parse Opus response as JSON for %s", ticker)
        return {
            "ticker": ticker,
            "quarter": label,
            "call_date": date.today().isoformat(),
            "transcript_summary": "Transcript analysis failed — could not parse model response.",
        }
    except Exception:
        log.exception("Transcript analysis failed for %s", ticker)
        return {
            "ticker": ticker,
            "quarter": label,
            "call_date": date.today().isoformat(),
            "transcript_summary": "Transcript analysis failed — API error.",
        }


# ═══════════════════════════════════════════════════════
# CROSS-MENTION DETECTION
# ═══════════════════════════════════════════════════════

def detect_cross_mentions(earnings_data: dict[str, dict],
                          tracked_tickers: list[str]) -> list[dict[str, Any]]:
    """Detect cross-company mentions across earnings data.

    Looks through mentioned_companies in each ticker's earnings analysis
    and finds references to tickers in the tracked set (holdings + conviction list).
    Creates cross_mention records and stores them via memory.

    Args:
        earnings_data: Dict of ticker -> earnings data (must include 'mentioned_companies').
        tracked_tickers: List of tickers we care about (holdings + conviction list).

    Returns:
        List of cross-mention dicts.
    """
    tracked_set = {t.upper() for t in tracked_tickers}
    cross_mentions: list[dict[str, Any]] = []

    for source_ticker, data in earnings_data.items():
        mentioned = data.get("mentioned_companies", [])
        if not mentioned:
            continue

        quarter = data.get("quarter", _quarter_label(*_current_quarter()))
        summary = data.get("transcript_summary", "")

        for mentioned_ticker in mentioned:
            mentioned_upper = mentioned_ticker.upper()
            # Skip self-mentions
            if mentioned_upper == source_ticker.upper():
                continue
            # Only track mentions of tickers we care about
            if mentioned_upper not in tracked_set:
                continue

            # Determine relationship category from context
            category = _infer_relationship(source_ticker, mentioned_upper, summary)
            sentiment = _infer_mention_sentiment(summary, mentioned_upper)

            context = f"Mentioned in {source_ticker} earnings call ({quarter})"
            if summary:
                context = f"{context}. Context: {summary[:200]}"

            mention = {
                "source_ticker": source_ticker.upper(),
                "mentioned_ticker": mentioned_upper,
                "quarter": quarter,
                "context": context,
                "sentiment": sentiment,
                "category": category,
            }
            cross_mentions.append(mention)

            # Store in memory
            memory.upsert_cross_mention(
                source_ticker=mention["source_ticker"],
                mentioned_ticker=mention["mentioned_ticker"],
                quarter=mention["quarter"],
                context=mention["context"],
                sentiment=mention["sentiment"],
                category=mention["category"],
            )
            log.info("Cross-mention: %s mentioned %s (%s, %s)",
                     source_ticker, mentioned_upper, category, sentiment)

    log.info("Detected %d cross-mentions across %d earnings calls",
             len(cross_mentions), len(earnings_data))
    return cross_mentions


def _infer_relationship(source: str, mentioned: str, context: str) -> str:
    """Infer the relationship category between two companies from context.

    Returns one of: supplier, competitor, partner, customer.
    Uses simple keyword matching as a heuristic.
    """
    ctx_lower = context.lower()

    supplier_kw = ["supply", "supplier", "chips from", "hardware from", "infrastructure from",
                    "powered by", "built on", "using"]
    partner_kw = ["partner", "partnership", "collaboration", "working with", "joint",
                   "together with", "alliance"]
    competitor_kw = ["compete", "competitor", "competition", "versus", "compared to",
                     "market share", "ahead of", "behind"]
    customer_kw = ["customer", "client", "buyer", "purchased", "ordered",
                    "deployed", "adopted"]

    for kw in partner_kw:
        if kw in ctx_lower:
            return "partner"
    for kw in supplier_kw:
        if kw in ctx_lower:
            return "supplier"
    for kw in customer_kw:
        if kw in ctx_lower:
            return "customer"
    for kw in competitor_kw:
        if kw in ctx_lower:
            return "competitor"

    return "partner"  # Default assumption for co-mentioned companies


def _infer_mention_sentiment(context: str, mentioned_ticker: str) -> str:
    """Infer sentiment of a cross-mention (positive/neutral/negative)."""
    ctx_lower = context.lower()
    ticker_lower = mentioned_ticker.lower()

    negative_kw = ["concern", "risk", "challenge", "decline", "losing", "weakness",
                    "headwind", "replacing", "displacing"]
    positive_kw = ["growth", "strong", "accelerat", "demand", "expand", "increase",
                    "opportunity", "benefit", "partnership"]

    neg_score = sum(1 for kw in negative_kw if kw in ctx_lower)
    pos_score = sum(1 for kw in positive_kw if kw in ctx_lower)

    if pos_score > neg_score:
        return "positive"
    if neg_score > pos_score:
        return "negative"
    return "neutral"


# ═══════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ═══════════════════════════════════════════════════════

def run_earnings_analysis(tickers: list[str]) -> dict[str, Any]:
    """Run the full earnings analysis pipeline.

    1. Fetch earnings data for all tickers
    2. Analyze transcripts (only for new quarters not already in DB)
    3. Detect cross-mentions among tracked tickers
    4. Store everything in memory

    Args:
        tickers: List of ticker symbols to analyze.

    Returns:
        Summary dict with per-ticker earnings status and cross-mentions.
    """
    log.info("Starting earnings analysis for %d tickers", len(tickers))
    year, quarter = _current_quarter()
    label = _quarter_label(year, quarter)

    # Step 1: Check what we already have in memory
    already_analyzed: set[str] = set()
    for ticker in tickers:
        history = memory.get_earnings_history(ticker, quarters=1)
        if history and history[0].get("quarter") == label:
            already_analyzed.add(ticker)
            log.info("Already have %s earnings for %s — skipping", label, ticker)

    tickers_to_fetch = [t for t in tickers if t not in already_analyzed]

    if not tickers_to_fetch:
        log.info("All tickers already analyzed for %s", label)
        return {
            "quarter": label,
            "tickers_analyzed": 0,
            "tickers_skipped": len(already_analyzed),
            "cross_mentions": [],
            "per_ticker": {t: {"status": "already_in_db"} for t in tickers},
        }

    # Step 2: Fetch earnings data
    earnings_data = fetch_earnings_data(tickers_to_fetch)

    # Step 3: Analyze transcripts where available
    for ticker, data in earnings_data.items():
        transcript = data.get("transcript")
        if transcript:
            analysis = analyze_transcript(ticker, transcript)
            # Merge analysis results back into earnings data
            data.update(analysis)
        else:
            log.info("No transcript available for %s — storing basic earnings data", ticker)

        # Store in memory
        call_data = {
            "ticker": ticker,
            "quarter": data.get("quarter", label),
            "call_date": data.get("call_date", date.today().isoformat()),
            "revenue_actual": data.get("revenue_actual"),
            "revenue_estimate": data.get("revenue_estimate"),
            "eps_actual": data.get("eps_actual"),
            "eps_estimate": data.get("eps_estimate"),
            "guidance_revenue_low": data.get("guidance_revenue_low"),
            "guidance_revenue_high": data.get("guidance_revenue_high"),
            "guidance_eps_low": data.get("guidance_eps_low"),
            "guidance_eps_high": data.get("guidance_eps_high"),
            "guidance_sentiment": data.get("guidance_sentiment"),
            "key_quotes": data.get("key_quotes", []),
            "capex_guidance": data.get("capex_guidance"),
            "mentioned_companies": data.get("mentioned_companies", []),
            "management_tone": data.get("management_tone"),
            "transcript_summary": data.get("transcript_summary"),
        }
        memory.upsert_earnings_call(call_data)
        log.info("Stored earnings data for %s (%s)", ticker, label)

    # Step 4: Detect cross-mentions (use all tickers as the tracked set)
    cross_mentions = detect_cross_mentions(earnings_data, tickers)

    # Build per-ticker summary
    per_ticker: dict[str, dict] = {}
    for t in tickers:
        if t in already_analyzed:
            per_ticker[t] = {"status": "already_in_db"}
        elif t in earnings_data:
            d = earnings_data[t]
            per_ticker[t] = {
                "status": "analyzed" if d.get("transcript") else "basic_data_only",
                "eps_actual": d.get("eps_actual"),
                "eps_estimate": d.get("eps_estimate"),
                "guidance_sentiment": d.get("guidance_sentiment"),
                "management_tone": d.get("management_tone"),
                "mentioned_companies": d.get("mentioned_companies", []),
            }
        else:
            per_ticker[t] = {"status": "no_data"}

    summary = {
        "quarter": label,
        "tickers_analyzed": len(tickers_to_fetch),
        "tickers_skipped": len(already_analyzed),
        "transcripts_analyzed": sum(
            1 for d in earnings_data.values() if d.get("transcript")
        ),
        "cross_mentions": cross_mentions,
        "per_ticker": per_ticker,
    }

    log.info("Earnings analysis complete: %d analyzed, %d skipped, %d cross-mentions",
             summary["tickers_analyzed"], summary["tickers_skipped"], len(cross_mentions))
    return summary
