"""Moonshot idea manager for AlphaDesk Advisor.

Tracks 1-2 high-risk/high-reward asymmetric bets that persist across weeks.
Moonshots don't need to pass the 25% CAGR gate but DO need a clear
asymmetric thesis (upside case vs downside case).

Six moonshot archetypes:
    1. small_cap_disruptor  — <$30B mkt cap, >30% rev growth, social buzz
    2. catalyst_driven      — binary event ahead (earnings, regulation, contract)
    3. contrarian_turnaround — >30% off highs with improving fundamentals
    4. pre_ipo_proxy        — public equity proxy for unlisted companies (OpenAI, Anthropic, SpaceX)
    5. commodity_thematic   — gold, silver, bitcoin, thematic ETFs
    6. thematic_sector      — space tech, quantum, nuclear, robotics
"""

import json

from src.shared import gemini_compat as anthropic

from src.advisor import memory
from src.shared.cost_tracker import check_budget, record_usage
from src.utils.logger import get_logger

log = get_logger(__name__)

_AGENT_NAME = "advisor_moonshot"
_MODEL = "claude-opus-4-6"


def update_moonshot_list(
    candidates: list[dict],
    config: dict,
    prediction_data: list[dict] | None = None,
    earnings_data: dict | None = None,
    valuation_data: dict | None = None,
) -> dict:
    """Update the persistent moonshot list.

    Reviews existing moonshots, evaluates screener candidates + config seeds,
    and maintains 1-2 active moonshot ideas.

    Args:
        candidates: Scored candidates from Alpha Scout screener.
        config: Advisor config dict.
        prediction_data: List of prediction market entries.
        earnings_data: Dict with per_ticker earnings data.
        valuation_data: Dict mapping ticker -> valuation from valuation_engine.

    Returns:
        Dict with current_list, added, removed.
    """
    output_config = config.get("output", {})
    max_moonshots = output_config.get("max_moonshots", 2)
    strategy = config.get("strategy", {})
    moonshot_max_pct = strategy.get("moonshot_max_pct", 3)
    moonshot_config = config.get("moonshot", {})

    current_list = memory.get_moonshot_list(active_only=True)
    current_tickers = {entry["ticker"] for entry in current_list}

    added = []
    removed = []

    # Build prediction lookup by ticker
    prediction_by_ticker: dict[str, dict] = {}
    if prediction_data:
        for pred in prediction_data:
            for t in pred.get("affected_tickers", []):
                if t not in prediction_by_ticker:
                    prediction_by_ticker[t] = pred

    # Build seed candidate lookup from config (archetypes 4-6)
    seed_candidates = _build_seed_candidates(moonshot_config)

    # --- Phase 1: Review existing moonshots ---
    for entry in current_list:
        ticker = entry["ticker"]
        candidate_match = _find_candidate(ticker, candidates)

        if candidate_match:
            scores = candidate_match.get("scores", {})
            fund_summary = candidate_match.get("fundamentals_summary", {})

            rev_growth = fund_summary.get("revenue_growth")
            if rev_growth is not None and rev_growth < -0.20:
                memory.remove_moonshot(ticker, "Revenue declining >20%")
                removed.append({"ticker": ticker, "reason": "Revenue declining >20%"})
                continue

            composite = scores.get("composite", 0)
            new_conviction = "high" if composite > 60 else "medium" if composite > 40 else "low"

            if new_conviction != entry.get("conviction"):
                memory.upsert_moonshot(
                    ticker=ticker,
                    conviction=new_conviction,
                    thesis=entry.get("thesis", ""),
                    upside_case=entry.get("upside_case"),
                    downside_case=entry.get("downside_case"),
                    key_milestone=entry.get("key_milestone"),
                    max_position_pct=moonshot_max_pct,
                )

    # Refresh after updates
    current_list = memory.get_moonshot_list(active_only=True)
    current_tickers = {entry["ticker"] for entry in current_list}
    slots_available = max_moonshots - len(current_list)

    # --- Phase 2: Consider new moonshots ---
    if slots_available > 0:
        holdings_tickers = {h.get("ticker") for h in config.get("holdings", [])}

        # Merge screener candidates + seed candidates
        all_candidates = list(candidates) + seed_candidates

        # Sort by composite score (seeds get default 50)
        sorted_candidates = sorted(
            all_candidates,
            key=lambda c: c.get("scores", {}).get("composite", 50),
            reverse=True,
        )

        for candidate in sorted_candidates:
            if slots_available <= 0:
                break

            ticker = candidate.get("ticker", "")
            if ticker in current_tickers or ticker in holdings_tickers:
                continue

            archetype = _has_asymmetric_profile(
                candidate, prediction_by_ticker, moonshot_config,
            )
            if archetype is None:
                continue

            thesis, upside_case, downside_case, key_milestone = _generate_moonshot_thesis(
                ticker, candidate, archetype,
                valuation_data.get(ticker) if valuation_data else None,
            )

            # Build discovery source description
            discovery_source = _build_discovery_narrative(candidate)

            memory.upsert_moonshot(
                ticker=ticker,
                conviction="medium",
                thesis=thesis,
                upside_case=upside_case,
                downside_case=downside_case,
                key_milestone=key_milestone,
                max_position_pct=moonshot_max_pct,
                source=discovery_source,
            )

            added.append({"ticker": ticker, "thesis": thesis, "archetype": archetype})
            current_tickers.add(ticker)
            slots_available -= 1
            log.info("Added %s to moonshot list (archetype=%s)", ticker, archetype)

    final_list = memory.get_moonshot_list(active_only=True)

    result = {
        "current_list": final_list,
        "added": added,
        "removed": removed,
    }

    log.info(
        "Moonshot update: %d active, +%d added, -%d removed",
        len(final_list), len(added), len(removed),
    )
    return result


# ═══════════════════════════════════════════════════════
# ARCHETYPE DETECTION
# ═══════════════════════════════════════════════════════

def _has_asymmetric_profile(
    candidate: dict,
    prediction_by_ticker: dict | None = None,
    moonshot_config: dict | None = None,
) -> str | None:
    """Check if a candidate matches one of six moonshot archetypes.

    Returns the archetype name if matched, or None if no match.
    """
    mc = moonshot_config or {}
    scores = candidate.get("scores", {})
    fund = candidate.get("fundamentals_summary", {})
    signal_data = candidate.get("signal_data", {})
    ticker = candidate.get("ticker", "")

    market_cap = fund.get("market_cap")
    revenue_growth = fund.get("revenue_growth")
    pct_from_high = fund.get("pct_from_52w_high")
    sentiment_score = scores.get("sentiment", 0)

    # If candidate already has explicit asymmetric fields, accept
    if candidate.get("upside_case") and candidate.get("downside_case"):
        return candidate.get("archetype", "explicit")

    # --- Archetype 4: Pre-IPO proxy (check first — config-seeded) ---
    proxy_tickers = {p["ticker"] for p in mc.get("pre_ipo_proxies", [])}
    if ticker in proxy_tickers:
        return "pre_ipo_proxy"

    # --- Archetype 5: Commodity / thematic ETF ---
    commodity_tickers = {c["ticker"] for c in mc.get("commodity_tickers", [])}
    if ticker in commodity_tickers:
        return "commodity_thematic"

    # --- Archetype 6: Thematic sector ---
    for _sector, tickers_list in mc.get("thematic_sectors", {}).items():
        if ticker in tickers_list:
            return "thematic_sector"

    # --- Archetype 1: Small-cap disruptor ---
    disruptor_cap = mc.get("disruptor_max_market_cap", 30_000_000_000)
    disruptor_growth = mc.get("disruptor_min_rev_growth", 0.30)
    disruptor_sentiment = mc.get("disruptor_min_sentiment", 40)

    if (market_cap is not None and market_cap < disruptor_cap
            and revenue_growth is not None and revenue_growth > disruptor_growth
            and sentiment_score >= disruptor_sentiment):
        return "small_cap_disruptor"

    # --- Archetype 2: Catalyst-driven ---
    # Must be sub-$50B -- mega-caps are not moonshots
    catalyst_max_cap = mc.get("catalyst_max_market_cap", 50_000_000_000)
    catalyst_composite = mc.get("catalyst_min_composite", 45)
    has_catalyst = False

    next_earnings = fund.get("next_earnings_date") or signal_data.get("next_earnings_date")
    if next_earnings:
        has_catalyst = True

    if prediction_by_ticker and ticker in prediction_by_ticker:
        has_catalyst = True

    signal_type = candidate.get("signal_type", "")
    if signal_type in ("earnings_surprise", "sentiment_reversal", "guidance_change", "breaking_news"):
        has_catalyst = True

    if (has_catalyst
            and scores.get("composite", 0) >= catalyst_composite
            and (market_cap is None or market_cap < catalyst_max_cap)):
        return "catalyst_driven"

    # --- Archetype 3: Contrarian turnaround ---
    # Must be sub-$50B -- mega-caps recovering from a drawdown are not moonshots
    turnaround_max_cap = mc.get("turnaround_max_market_cap", 50_000_000_000)
    turnaround_pct = mc.get("turnaround_max_pct_from_high", -30)
    turnaround_sentiment = mc.get("turnaround_min_sentiment", 50)

    if (pct_from_high is not None and pct_from_high <= turnaround_pct
            and (market_cap is None or market_cap < turnaround_max_cap)):
        if revenue_growth is not None and revenue_growth > 0:
            return "contrarian_turnaround"
        if sentiment_score >= turnaround_sentiment:
            return "contrarian_turnaround"

    return None


# ═══════════════════════════════════════════════════════
# SEED CANDIDATE BUILDER
# ═══════════════════════════════════════════════════════

def _build_seed_candidates(moonshot_config: dict) -> list[dict]:
    """Build candidate dicts from config-seeded moonshot entries.

    These are pre-IPO proxies, commodity ETFs, and thematic sector plays
    that don't come from the screener pipeline.
    """
    seeds: list[dict] = []

    for proxy in moonshot_config.get("pre_ipo_proxies", []):
        seeds.append({
            "ticker": proxy["ticker"],
            "source": "config/pre_ipo_proxy",
            "signal_type": "pre_ipo_proxy",
            "signal_data": {"exposure": proxy.get("exposure", "")},
            "scores": {"composite": 55},
            "fundamentals_summary": {},
            "archetype": "pre_ipo_proxy",
        })

    for commodity in moonshot_config.get("commodity_tickers", []):
        seeds.append({
            "ticker": commodity["ticker"],
            "source": "config/commodity",
            "signal_type": "commodity_thematic",
            "signal_data": {"exposure": commodity.get("exposure", "")},
            "scores": {"composite": 50},
            "fundamentals_summary": {},
            "archetype": "commodity_thematic",
        })

    # Thematic sectors — only include the first ticker per sector as representative
    for sector_name, tickers in moonshot_config.get("thematic_sectors", {}).items():
        for t in tickers[:2]:  # max 2 per sector to avoid flooding
            seeds.append({
                "ticker": t,
                "source": f"config/thematic/{sector_name}",
                "signal_type": "thematic_sector",
                "signal_data": {"sector_theme": sector_name},
                "scores": {"composite": 45},
                "fundamentals_summary": {},
                "archetype": "thematic_sector",
            })

    return seeds


# ═══════════════════════════════════════════════════════
# DISCOVERY NARRATIVE
# ═══════════════════════════════════════════════════════

def _build_discovery_narrative(candidate: dict) -> str:
    """Build a human-readable discovery narrative from candidate signal_data.

    Translates signal_data into readable text explaining WHY this stock surfaced.
    """
    signal_type = candidate.get("signal_type", "")
    signal_data = candidate.get("signal_data", {})
    source = candidate.get("source", "")

    if signal_type == "reddit_moonshot":
        mention_count = signal_data.get("mention_count", 0)
        top_subs = signal_data.get("top_subreddits", [])
        subs_str = ", ".join(f"r/{s}" for s in top_subs[:3])
        return f"Mentioned {mention_count} times on {subs_str} in the last 24h"

    elif signal_type == "superinvestor_new_position":
        fund_name = signal_data.get("fund_name", "Unknown fund")
        value = signal_data.get("position_value")
        if value and value > 0:
            return f"{fund_name} initiated ${value / 1e6:.0f}M position"
        return f"{fund_name} initiated new position"

    elif signal_type == "screener_hit":
        screener = signal_data.get("screener", "")
        return f"Hit {screener} screen on yfinance"

    elif signal_type == "sector_peer":
        sector = signal_data.get("sector", "")
        return f"Sector peer in {sector}"

    elif signal_type == "pre_ipo_proxy":
        exposure = signal_data.get("exposure", "")
        return f"Pre-IPO exposure: {exposure}"

    elif signal_type == "commodity_thematic":
        exposure = signal_data.get("exposure", "")
        return f"Commodity play: {exposure}"

    elif signal_type == "thematic_sector":
        theme = signal_data.get("sector_theme", "").replace("_", " ").title()
        return f"Thematic sector play: {theme}"

    elif source:
        return f"Sourced from {source}"

    return "Discovery candidate"


# ═══════════════════════════════════════════════════════
# OPUS THESIS GENERATION
# ═══════════════════════════════════════════════════════

def _generate_moonshot_thesis(
    ticker: str,
    candidate: dict,
    archetype: str,
    valuation: dict | None = None,
) -> tuple[str, str, str, str]:
    """Generate moonshot thesis, upside/downside cases, and key milestone via Opus.

    Returns:
        (thesis, upside_case, downside_case, key_milestone) tuple.
    """
    within_budget, spent, cap = check_budget()
    if not within_budget:
        log.warning("Budget exceeded — template moonshot for %s", ticker)
        return _moonshot_fallback(ticker, candidate, archetype)

    scores = candidate.get("scores", {})
    fund = candidate.get("fundamentals_summary", {})
    signal_data = candidate.get("signal_data", {})

    mcap = fund.get("market_cap")
    mcap_str = f"${mcap / 1e9:.1f}B" if mcap else "N/A"

    valuation_ctx = ""
    if valuation and not valuation.get("insufficient_data"):
        valuation_ctx = (
            f"Bull target: ${valuation.get('bull_target', 0):.2f}, "
            f"Bear target: ${valuation.get('bear_target', 0):.2f}, "
            f"implied CAGR: {valuation.get('implied_cagr', 0):.1f}%"
        )

    # Extra context for config-seeded archetypes
    exposure = signal_data.get("exposure", "")
    sector_theme = signal_data.get("sector_theme", "")
    extra_ctx = ""
    if exposure:
        extra_ctx = f"\nEXPOSURE: {exposure}"
    if sector_theme:
        extra_ctx = f"\nTHEMATIC SECTOR: {sector_theme.replace('_', ' ').title()}"

    # Discovery context for the prompt
    discovery_narrative = _build_discovery_narrative(candidate)
    discovery_ctx = f"\nDISCOVERY CONTEXT: {candidate.get('source', 'N/A')}"
    discovery_ctx += f"\nWHY THIS SURFACED: {discovery_narrative}"

    prompt = f"""You are analyzing {ticker} as a potential moonshot (asymmetric bet) for a long-term investor.

ARCHETYPE: {archetype.replace('_', ' ').title()}
MARKET CAP: {mcap_str}
REVENUE GROWTH: {fund.get('revenue_growth', 'N/A')}
PCT FROM 52W HIGH: {fund.get('pct_from_52w_high', 'N/A')}%
SECTOR: {fund.get('sector', 'N/A')}
VALUATION: {valuation_ctx or 'N/A'}
SOURCE: {candidate.get('source', 'N/A')}{extra_ctx}{discovery_ctx}

Generate four fields as a JSON object:
1. "thesis": 2-3 sentence investment thesis for WHY this is an asymmetric bet. Cite specific numbers or catalysts.
2. "upside_case": 1-2 sentences describing the bull scenario and rough magnitude (e.g. "2-3x over 18 months if...")
3. "downside_case": 1-2 sentences describing what goes wrong and rough loss (e.g. "30-40% downside if...")
4. "key_milestone": One specific, observable event that will confirm or invalidate the thesis.

Respond with ONLY valid JSON, no markdown code blocks."""

    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=_MODEL,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )

        usage = response.usage
        record_usage(_AGENT_NAME, usage.input_tokens, usage.output_tokens, model=_MODEL)

        if not response.content:
            log.warning("Empty Opus response for %s", ticker)
            return _moonshot_fallback(ticker, candidate, archetype)

        raw = response.content[0].text.strip()
        # Strip markdown code blocks if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()

        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            log.warning("Failed to parse JSON from Opus for %s, using fallback", ticker)
            return _moonshot_fallback(ticker, candidate, archetype)

        log.info("Opus moonshot thesis for %s (%d in, %d out)",
                 ticker, usage.input_tokens, usage.output_tokens)

        return (
            data.get("thesis", f"{ticker} — {archetype} moonshot"),
            data.get("upside_case", "High growth potential if thesis plays out"),
            data.get("downside_case", "Significant downside if thesis fails"),
            data.get("key_milestone", "Monitor next earnings report"),
        )
    except Exception:
        log.exception("Opus moonshot thesis failed for %s — using fallback", ticker)
        return _moonshot_fallback(ticker, candidate, archetype)


def _moonshot_fallback(
    ticker: str, candidate: dict, archetype: str,
) -> tuple[str, str, str, str]:
    """Template-based fallback for moonshot thesis generation."""
    fund = candidate.get("fundamentals_summary", {})
    signal_data = candidate.get("signal_data", {})
    rev_growth = fund.get("revenue_growth")
    pct_from_high = fund.get("pct_from_52w_high")
    exposure = signal_data.get("exposure", "")
    sector_theme = signal_data.get("sector_theme", "")

    if archetype == "small_cap_disruptor":
        growth_str = f"{rev_growth * 100:.0f}%" if rev_growth else "high"
        return (
            f"{ticker} — Small-cap disruptor with {growth_str} revenue growth and strong social buzz",
            "Multi-bagger potential if growth sustains and market re-rates",
            "Growth deceleration or competitive entry could compress multiple 40-50%",
            "Next quarterly earnings revenue growth rate",
        )
    elif archetype == "catalyst_driven":
        return (
            f"{ticker} — Catalyst-driven opportunity with binary event ahead",
            "Positive catalyst resolution could drive 30-50%+ re-rating",
            "Negative catalyst outcome could trigger 20-30% sell-off",
            "Upcoming catalyst event resolution",
        )
    elif archetype == "contrarian_turnaround":
        drop_str = f"{pct_from_high:.0f}%" if pct_from_high else ">30%"
        return (
            f"{ticker} — Contrarian turnaround, {drop_str} off highs with improving fundamentals",
            "Mean reversion to historical levels could deliver 40-80% upside",
            "Value trap risk if fundamentals continue deteriorating — further 20-30% downside",
            "Two consecutive quarters of improving revenue growth",
        )
    elif archetype == "pre_ipo_proxy":
        return (
            f"{ticker} — Pre-IPO exposure: {exposure}",
            f"If the unlisted company IPOs or grows rapidly, {ticker} benefits from direct exposure",
            "Partnership unwinds or unlisted company falters — limited but real drag on valuation",
            "Next quarterly disclosure of partnership metrics or investment valuation",
        )
    elif archetype == "commodity_thematic":
        return (
            f"{ticker} — {exposure}" if exposure else f"{ticker} — Commodity/thematic play",
            "Macro tailwinds (inflation, central bank policy, demand cycle) drive sustained appreciation",
            "Macro reversal or demand destruction compress prices 20-30%",
            "Next Fed meeting or major macro data release",
        )
    elif archetype == "thematic_sector":
        theme = sector_theme.replace("_", " ").title() if sector_theme else "Emerging sector"
        return (
            f"{ticker} — {theme} play with asymmetric risk/reward",
            f"Sector takes off — early movers in {theme.lower()} see 2-5x re-rating",
            "Sector hype fades without commercial traction — 40-60% drawdown",
            "First major commercial contract or revenue milestone",
        )
    else:
        return (
            f"{ticker} — Asymmetric bet candidate",
            "High growth potential if thesis plays out",
            "Significant downside if thesis fails",
            "Monitor next earnings report",
        )


# ═══════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════

def _find_candidate(ticker: str, candidates: list[dict]) -> dict | None:
    """Find a candidate by ticker in the candidates list."""
    for c in candidates:
        if c.get("ticker") == ticker:
            return c
    return None
