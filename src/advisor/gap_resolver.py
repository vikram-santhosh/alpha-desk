"""Reactive data-gap resolver for the analyst committee.

When committee analysts flag missing information — competitor data, sector
comparisons, unclear macro impacts — this module fetches it on-demand via
yfinance (free) or a Flash LLM call (cheap).  Results are formatted as
supplementary research and injected into the CIO synthesis prompt so the
final brief has fewer blind spots.

This makes the pipeline reactive rather than strictly linear: analysts can
request data they need *after* seeing what's available.
"""

import asyncio
import json
import re
from typing import Any

import yfinance as yf

from src.shared import gemini_compat as anthropic
from src.shared.cost_tracker import check_budget, record_usage
from src.utils.logger import get_logger

log = get_logger(__name__)

AGENT_NAME = "gap_resolver"
MODEL = "claude-haiku-4-5"  # maps to gemini-2.5-flash via compat shim

GAP_TYPES = {
    "missing_competitor_data": "Fetch competitor fundamentals via yfinance",
    "sector_comparison_needed": "Fetch sector peers and compare metrics",
    "unclear_impact": "Use LLM to reason about impact based on available data",
    "missing_fundamentals": "Fetch specific fundamental metrics via yfinance",
    "historical_pattern": "Check historical price action during similar events",
}

_PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}

# Regex to extract uppercase ticker-like symbols (1-5 letters) from text
_TICKER_RE = re.compile(r"\b([A-Z]{1,5})\b")

# Common English words that look like tickers but aren't
_TICKER_STOPWORDS = {
    "I", "A", "AN", "AM", "AS", "AT", "BE", "BY", "DO", "GO", "HE",
    "IF", "IN", "IS", "IT", "ME", "MY", "NO", "OF", "ON", "OR", "SO",
    "TO", "UP", "US", "WE", "AND", "ARE", "BUT", "CAN", "DID", "FOR",
    "GET", "GOT", "HAS", "HAD", "HER", "HIM", "HIS", "HOW", "ITS",
    "LET", "MAY", "NEW", "NOT", "NOW", "OLD", "OUR", "OUT", "OWN",
    "RUN", "SAY", "SHE", "THE", "TOO", "USE", "WAS", "WAY", "WHO",
    "WHY", "YET", "YOU", "ALL", "ANY", "FEW", "REV", "NET", "YOY",
    "NEED", "ALSO", "BEEN", "COME", "EACH", "FIND", "FROM", "HAVE",
    "INTO", "JUST", "LIKE", "LONG", "MAKE", "MANY", "MORE", "MOST",
    "MUCH", "MUST", "NAME", "ONLY", "OVER", "SAME", "SOME", "SUCH",
    "THAN", "THEM", "THEN", "THEY", "THIS", "VERY", "WELL", "WHAT",
    "WHEN", "WILL", "WITH", "YEAR", "YOUR", "HIGH", "GROWTH", "RISK",
    "DATA", "DOES", "WOULD", "COULD", "THAT", "ABOUT", "AFTER", "BEING",
    "THESE", "THEIR", "THERE", "WHERE", "WHICH", "WHILE", "CHINA",
    "UNCLEAR", "IMPACT", "SECTOR", "COMPARE",
}


def _extract_tickers(text: str) -> list[str]:
    """Pull plausible ticker symbols from free-form text."""
    candidates = _TICKER_RE.findall(text)
    return [t for t in dict.fromkeys(candidates) if t not in _TICKER_STOPWORDS]


def _fmt_pct(value: float | None) -> str:
    """Format a decimal ratio as a percentage string."""
    if value is None:
        return "N/A"
    return f"{value * 100:.1f}%"


def _fmt_market_cap(value: float | int | None) -> str:
    """Format market cap in human-readable form."""
    if value is None:
        return "N/A"
    if value >= 1e12:
        return f"${value / 1e12:.2f}T"
    if value >= 1e9:
        return f"${value / 1e9:.1f}B"
    if value >= 1e6:
        return f"${value / 1e6:.0f}M"
    return f"${value:,.0f}"


def _safe_info(ticker_symbol: str) -> dict[str, Any]:
    """Fetch yfinance .info for a ticker, returning empty dict on failure."""
    try:
        return yf.Ticker(ticker_symbol).info or {}
    except Exception:
        log.warning("yfinance .info failed for %s", ticker_symbol)
        return {}


class GapResolver:
    """Resolves data gaps identified by analyst committee analysts."""

    MAX_GAPS = 5          # Process at most 5 gaps per run
    TIMEOUT_SECONDS = 45  # Total timeout for all gap resolution

    def __init__(self):
        self.client = anthropic.Anthropic()

    async def resolve_gaps(
        self,
        gaps: list[dict],
        existing_context: dict,
    ) -> list[dict]:
        """Resolve data gaps identified by analysts.

        Args:
            gaps: List of gap dicts from analyst reports:
                [
                    {
                        "gap_type": "missing_competitor_data",
                        "ticker": "NVDA",
                        "description": "Need AMD and INTC revenue growth for comparison",
                        "requesting_analyst": "growth",
                        "priority": "high"
                    },
                    {
                        "gap_type": "unclear_impact",
                        "ticker": "AAPL",
                        "description": "How would 25% tariffs on China affect iPhone margins?",
                        "requesting_analyst": "risk",
                        "priority": "medium"
                    },
                ]
            existing_context: Dict with available data:
                {
                    "fundamentals": {ticker: {...}},
                    "macro_data": {...},
                    "holdings_reports": [...]
                }

        Returns:
            List of resolved gap dicts with resolution text, source,
            and confidence score.
        """
        if not gaps:
            return []

        # Sort by priority and cap at MAX_GAPS
        sorted_gaps = sorted(
            gaps,
            key=lambda g: _PRIORITY_ORDER.get(g.get("priority", "low"), 2),
        )
        capped = sorted_gaps[: self.MAX_GAPS]

        log.info(
            "Resolving %d data gaps (of %d submitted, max %d)",
            len(capped), len(gaps), self.MAX_GAPS,
        )

        try:
            results = await asyncio.wait_for(
                self._resolve_all(capped, existing_context),
                timeout=self.TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            log.warning(
                "Gap resolution timed out after %ds — returning partial results",
                self.TIMEOUT_SECONDS,
            )
            results = []

        return results

    async def _resolve_all(
        self,
        gaps: list[dict],
        existing_context: dict,
    ) -> list[dict]:
        """Resolve every gap, collecting partial results on failure."""
        tasks = [self._resolve_one(gap, existing_context) for gap in gaps]
        raw = await asyncio.gather(*tasks, return_exceptions=True)

        results: list[dict] = []
        for gap, outcome in zip(gaps, raw):
            if isinstance(outcome, Exception):
                log.warning(
                    "Gap resolution failed for %s/%s: %s",
                    gap.get("gap_type"), gap.get("ticker"), outcome,
                )
                continue
            if outcome is not None:
                results.append(outcome)

        return results

    async def _resolve_one(
        self,
        gap: dict,
        existing_context: dict,
    ) -> dict | None:
        """Dispatch a single gap to the appropriate resolver."""
        gap_type = gap.get("gap_type", "")
        dispatch = {
            "missing_competitor_data": self._resolve_competitor_data,
            "sector_comparison_needed": self._resolve_sector_comparison,
            "unclear_impact": self._resolve_unclear_impact,
            "missing_fundamentals": self._resolve_missing_fundamentals,
            "historical_pattern": self._resolve_historical_pattern,
        }

        resolver = dispatch.get(gap_type)
        if resolver is None:
            log.warning("Unknown gap type: %s", gap_type)
            return None

        result = await resolver(gap, existing_context)
        if result is not None:
            log.info(
                "Resolved gap: %s for %s via %s",
                gap_type, gap.get("ticker"), result.get("source", "unknown"),
            )
        return result

    # ── Individual resolvers ──────────────────────────────────────────

    async def _resolve_competitor_data(
        self, gap: dict, existing_context: dict
    ) -> dict:
        """Fetch competitor fundamentals via yfinance."""
        description = gap.get("description", "")
        tickers = _extract_tickers(description)
        if not tickers:
            tickers = _extract_tickers(gap.get("ticker", ""))

        comparisons: list[str] = []
        for t in tickers[:5]:
            info = await asyncio.to_thread(_safe_info, t)
            if not info:
                comparisons.append(f"{t}: data unavailable")
                continue
            rev_growth = _fmt_pct(info.get("revenueGrowth"))
            pe_fwd = info.get("forwardPE")
            pe_str = f"{pe_fwd:.1f}" if pe_fwd is not None else "N/A"
            margin = _fmt_pct(info.get("profitMargins"))
            mcap = _fmt_market_cap(info.get("marketCap"))
            comparisons.append(
                f"{t}: Rev growth {rev_growth} YoY, P/E(f) {pe_str}, "
                f"Net margin {margin}, Mkt cap {mcap}"
            )

        return {
            "gap_type": gap.get("gap_type"),
            "ticker": gap.get("ticker"),
            "requesting_analyst": gap.get("requesting_analyst"),
            "resolution": ". ".join(comparisons) + ".",
            "source": "yfinance",
            "confidence": 0.9,
        }

    async def _resolve_sector_comparison(
        self, gap: dict, existing_context: dict
    ) -> dict:
        """Fetch sector peers and compare key metrics."""
        ticker = gap.get("ticker", "")
        info = await asyncio.to_thread(_safe_info, ticker)
        sector = info.get("sector", "Unknown")

        # Try to get recommended/similar symbols
        peer_symbols: list[str] = []
        rec = info.get("recommendedSymbols")
        if rec and isinstance(rec, list):
            peer_symbols = [
                s.get("symbol", s) if isinstance(s, dict) else str(s)
                for s in rec[:5]
            ]

        if not peer_symbols:
            # Fallback: extract any tickers mentioned in the description
            peer_symbols = _extract_tickers(gap.get("description", ""))[:5]

        lines = [f"{ticker} sector: {sector}"]
        for peer in peer_symbols[:5]:
            peer_info = await asyncio.to_thread(_safe_info, peer)
            if not peer_info:
                continue
            rev_growth = _fmt_pct(peer_info.get("revenueGrowth"))
            pe = peer_info.get("forwardPE")
            pe_str = f"{pe:.1f}" if pe is not None else "N/A"
            margin = _fmt_pct(peer_info.get("profitMargins"))
            lines.append(
                f"  {peer}: Rev growth {rev_growth}, P/E(f) {pe_str}, Margin {margin}"
            )

        return {
            "gap_type": gap.get("gap_type"),
            "ticker": ticker,
            "requesting_analyst": gap.get("requesting_analyst"),
            "resolution": "\n".join(lines),
            "source": "yfinance",
            "confidence": 0.85,
        }

    async def _resolve_unclear_impact(
        self, gap: dict, existing_context: dict
    ) -> dict:
        """Use Flash LLM to reason about an unclear impact."""
        within_budget, spent, cap = check_budget()
        if not within_budget:
            log.warning("Budget exceeded ($%.2f / $%.2f) — skipping LLM gap resolution", spent, cap)
            return {
                "gap_type": gap.get("gap_type"),
                "ticker": gap.get("ticker"),
                "requesting_analyst": gap.get("requesting_analyst"),
                "resolution": "Budget exceeded — unable to perform LLM reasoning.",
                "source": "skipped",
                "confidence": 0.0,
            }

        ticker = gap.get("ticker", "")
        question = gap.get("description", "")
        fundamentals = existing_context.get("fundamentals", {}).get(ticker, {})
        macro_data = existing_context.get("macro_data", {})

        prompt = f"""You are a senior financial analyst. Answer this specific question concisely (3-5 sentences max).

QUESTION: {question}

TICKER: {ticker}
AVAILABLE FUNDAMENTALS: {json.dumps(fundamentals, default=str)[:1500]}
MACRO CONTEXT: {json.dumps(macro_data, default=str)[:1000]}

Be specific with numbers and mechanisms. State your confidence level (low/medium/high) and key assumptions."""

        response = await asyncio.to_thread(
            self.client.messages.create,
            model=MODEL,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )

        usage = response.usage
        record_usage(AGENT_NAME, usage.input_tokens, usage.output_tokens, model=MODEL)
        log.info("Gap resolver LLM call: %d in, %d out", usage.input_tokens, usage.output_tokens)

        return {
            "gap_type": gap.get("gap_type"),
            "ticker": ticker,
            "requesting_analyst": gap.get("requesting_analyst"),
            "resolution": response.content[0].text.strip(),
            "source": "llm_reasoning",
            "confidence": 0.6,
        }

    async def _resolve_missing_fundamentals(
        self, gap: dict, existing_context: dict
    ) -> dict:
        """Fetch specific fundamental metrics via yfinance."""
        ticker = gap.get("ticker", "")
        info = await asyncio.to_thread(_safe_info, ticker)

        if not info:
            return {
                "gap_type": gap.get("gap_type"),
                "ticker": ticker,
                "requesting_analyst": gap.get("requesting_analyst"),
                "resolution": f"Unable to fetch fundamentals for {ticker}.",
                "source": "yfinance",
                "confidence": 0.0,
            }

        # Build a comprehensive snapshot
        metrics = {
            "Revenue growth": _fmt_pct(info.get("revenueGrowth")),
            "Gross margin": _fmt_pct(info.get("grossMargins")),
            "Operating margin": _fmt_pct(info.get("operatingMargins")),
            "Net margin": _fmt_pct(info.get("profitMargins")),
            "P/E (trailing)": info.get("trailingPE"),
            "P/E (forward)": info.get("forwardPE"),
            "EPS (trailing)": info.get("trailingEps"),
            "EPS (forward)": info.get("forwardEps"),
            "Market cap": _fmt_market_cap(info.get("marketCap")),
            "Beta": info.get("beta"),
            "52w high": info.get("fiftyTwoWeekHigh"),
            "52w low": info.get("fiftyTwoWeekLow"),
            "Sector": info.get("sector"),
            "Industry": info.get("industry"),
        }

        parts = []
        for label, value in metrics.items():
            if value is not None:
                val_str = f"{value:.2f}" if isinstance(value, float) else str(value)
                parts.append(f"{label}: {val_str}")

        return {
            "gap_type": gap.get("gap_type"),
            "ticker": ticker,
            "requesting_analyst": gap.get("requesting_analyst"),
            "resolution": f"{ticker} fundamentals — " + ", ".join(parts) + ".",
            "source": "yfinance",
            "confidence": 0.9,
        }

    async def _resolve_historical_pattern(
        self, gap: dict, existing_context: dict
    ) -> dict:
        """Check historical price action and analyse pattern via LLM."""
        ticker = gap.get("ticker", "")

        # Fetch 1 year of daily prices
        try:
            hist = await asyncio.to_thread(
                yf.download, ticker, period="1y", progress=False
            )
        except Exception:
            log.warning("yfinance download failed for %s", ticker)
            hist = None

        if hist is None or hist.empty:
            return {
                "gap_type": gap.get("gap_type"),
                "ticker": ticker,
                "requesting_analyst": gap.get("requesting_analyst"),
                "resolution": f"Unable to fetch historical data for {ticker}.",
                "source": "yfinance",
                "confidence": 0.0,
            }

        # Summarise price history for the LLM
        close_col = "Close"
        if isinstance(hist.columns, __import__("pandas").MultiIndex):
            close_col = ("Close", ticker)

        try:
            closes = hist[close_col].dropna()
        except KeyError:
            closes = hist.iloc[:, 0].dropna()

        if closes.empty:
            return {
                "gap_type": gap.get("gap_type"),
                "ticker": ticker,
                "requesting_analyst": gap.get("requesting_analyst"),
                "resolution": f"No close prices available for {ticker}.",
                "source": "yfinance",
                "confidence": 0.0,
            }

        price_start = float(closes.iloc[0])
        price_end = float(closes.iloc[-1])
        price_high = float(closes.max())
        price_low = float(closes.min())
        total_return = (price_end - price_start) / price_start * 100

        price_summary = (
            f"{ticker} 1Y: ${price_start:.2f} -> ${price_end:.2f} "
            f"({total_return:+.1f}%), High ${price_high:.2f}, Low ${price_low:.2f}"
        )

        within_budget, spent, cap = check_budget()
        if not within_budget:
            return {
                "gap_type": gap.get("gap_type"),
                "ticker": ticker,
                "requesting_analyst": gap.get("requesting_analyst"),
                "resolution": price_summary,
                "source": "yfinance",
                "confidence": 0.4,
            }

        question = gap.get("description", "")

        prompt = f"""You are a technical/macro analyst. The user wants to understand a historical price pattern.

QUESTION: {question}

TICKER: {ticker}
PRICE HISTORY (1Y): {price_summary}

Provide a concise (3-5 sentence) analysis of the pattern described. Reference specific price levels and percentage moves. State confidence (low/medium/high)."""

        response = await asyncio.to_thread(
            self.client.messages.create,
            model=MODEL,
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )

        usage = response.usage
        record_usage(AGENT_NAME, usage.input_tokens, usage.output_tokens, model=MODEL)
        log.info("Gap resolver historical LLM: %d in, %d out", usage.input_tokens, usage.output_tokens)

        return {
            "gap_type": gap.get("gap_type"),
            "ticker": ticker,
            "requesting_analyst": gap.get("requesting_analyst"),
            "resolution": response.content[0].text.strip(),
            "source": "yfinance+llm",
            "confidence": 0.5,
        }


# ═══════════════════════════════════════════════════════
# STANDALONE HELPERS
# ═══════════════════════════════════════════════════════

_SOURCE_LABELS = {
    "yfinance": "yfinance",
    "llm_reasoning": "LLM reasoning",
    "yfinance+llm": "yfinance + LLM",
    "skipped": "skipped",
}


def format_supplementary_research(resolutions: list[dict]) -> str:
    """Format resolved gaps into a text section for the CIO prompt.

    Args:
        resolutions: List of resolved gap dicts from GapResolver.resolve_gaps.

    Returns:
        Formatted markdown-ish text ready to inject into the editor prompt.
        Returns empty string if there are no resolutions.
    """
    if not resolutions:
        return ""

    lines = ["## SUPPLEMENTARY RESEARCH", ""]

    for r in resolutions:
        analyst = r.get("requesting_analyst", "unknown")
        ticker = r.get("ticker", "")
        gap_type = r.get("gap_type", "")
        resolution = r.get("resolution", "")
        source = _SOURCE_LABELS.get(r.get("source", ""), r.get("source", "unknown"))
        confidence = r.get("confidence", 0.0)

        # Friendly label for the gap type
        type_label = gap_type.replace("_", " ")

        lines.append(f"[{analyst.capitalize()} analyst requested] {ticker} {type_label}:")
        for res_line in resolution.split("\n"):
            lines.append(f"  {res_line}")
        lines.append(f"  Source: {source} (confidence: {confidence})")
        lines.append("")

    return "\n".join(lines)


def parse_gaps_from_analyst_output(analyst_output: dict) -> list[dict]:
    """Extract and normalise data gaps from analyst JSON output.

    Committee analysts may include a ``data_gaps`` list in their output.
    This function normalises those entries into the standard gap format
    expected by :class:`GapResolver`.

    Args:
        analyst_output: Raw dict returned by a committee analyst. Expected
            to optionally contain a ``data_gaps`` key with a list of gap
            descriptions.

    Returns:
        List of normalised gap dicts, possibly empty.
    """
    raw_gaps = analyst_output.get("data_gaps", [])
    if not raw_gaps or not isinstance(raw_gaps, list):
        return []

    normalised: list[dict] = []
    for item in raw_gaps:
        if isinstance(item, str):
            # Bare string — treat as unclear_impact with medium priority
            normalised.append({
                "gap_type": "unclear_impact",
                "ticker": "",
                "description": item,
                "requesting_analyst": analyst_output.get("analyst", "unknown"),
                "priority": "medium",
            })
            continue

        if not isinstance(item, dict):
            continue

        gap = {
            "gap_type": item.get("gap_type", item.get("type", "unclear_impact")),
            "ticker": item.get("ticker", ""),
            "description": item.get("description", item.get("detail", "")),
            "requesting_analyst": item.get(
                "requesting_analyst",
                item.get("analyst", analyst_output.get("analyst", "unknown")),
            ),
            "priority": item.get("priority", "medium"),
        }

        # Validate gap_type; default to unclear_impact if unrecognised
        if gap["gap_type"] not in GAP_TYPES:
            gap["gap_type"] = "unclear_impact"

        normalised.append(gap)

    return normalised
