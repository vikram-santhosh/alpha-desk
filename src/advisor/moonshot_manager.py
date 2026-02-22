"""Moonshot idea manager for AlphaDesk Advisor.

Tracks 1-2 high-risk/high-reward asymmetric bets that persist across weeks.
Moonshots don't need to pass the 25% CAGR gate but DO need a clear
asymmetric thesis (upside case vs downside case).
"""

from src.advisor import memory
from src.utils.logger import get_logger

log = get_logger(__name__)


def update_moonshot_list(
    candidates: list[dict],
    config: dict,
) -> dict:
    """Update the persistent moonshot list.

    Reviews existing moonshots, optionally adds new candidates that have
    a clear asymmetric risk/reward profile.

    Args:
        candidates: Scored candidates from Alpha Scout screener or
            manual additions. Each should have at minimum: ticker, and
            optionally: thesis, upside_case, downside_case, key_milestone.
        config: Advisor config dict.

    Returns:
        Dict with current_list, added, removed.
    """
    output_config = config.get("output", {})
    max_moonshots = output_config.get("max_moonshots", 2)
    strategy = config.get("strategy", {})
    moonshot_max_pct = strategy.get("moonshot_max_pct", 3)

    current_list = memory.get_moonshot_list(active_only=True)
    current_tickers = {entry["ticker"] for entry in current_list}

    added = []
    removed = []

    # --- Phase 1: Review existing moonshots ---
    for entry in current_list:
        ticker = entry["ticker"]

        # Check if thesis is still alive — look for the candidate in new data
        candidate_match = _find_candidate(ticker, candidates)

        # If candidate data available, check for red flags
        if candidate_match:
            scores = candidate_match.get("scores", {})
            fund_summary = candidate_match.get("fundamentals_summary", {})

            # Remove if fundamentals have collapsed
            rev_growth = fund_summary.get("revenue_growth")
            if rev_growth is not None and rev_growth < -0.20:
                _remove_moonshot(ticker, "Revenue declining >20%")
                removed.append({"ticker": ticker, "reason": "Revenue declining >20%"})
                continue

            # Update conviction based on score
            composite = scores.get("composite", 0)
            if composite > 60:
                new_conviction = "high"
            elif composite > 40:
                new_conviction = "medium"
            else:
                new_conviction = "low"

            # Update if conviction changed
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
    if slots_available > 0 and candidates:
        # Holdings to exclude
        holdings_tickers = {h.get("ticker") for h in config.get("holdings", [])}
        # Conviction list tickers to exclude (moonshots are separate)
        conviction_tickers = {
            e["ticker"] for e in memory.get_conviction_list(active_only=True)
        }

        # Sort by composite score, look for asymmetric profiles
        sorted_candidates = sorted(
            candidates,
            key=lambda c: c.get("scores", {}).get("composite", 0),
            reverse=True,
        )

        for candidate in sorted_candidates:
            if slots_available <= 0:
                break

            ticker = candidate.get("ticker", "")
            if ticker in current_tickers or ticker in holdings_tickers:
                continue
            if ticker in conviction_tickers:
                continue

            # Moonshots need an asymmetric profile
            if not _has_asymmetric_profile(candidate):
                continue

            thesis = candidate.get("thesis", "")
            if not thesis:
                signal_data = candidate.get("signal_data", {})
                thesis = signal_data.get("thesis", f"{ticker} — moonshot candidate")

            upside_case = candidate.get("upside_case", "High growth potential if thesis plays out")
            downside_case = candidate.get("downside_case", "Significant downside if thesis fails")
            key_milestone = candidate.get("key_milestone")

            memory.upsert_moonshot(
                ticker=ticker,
                conviction="medium",
                thesis=thesis,
                upside_case=upside_case,
                downside_case=downside_case,
                key_milestone=key_milestone,
                max_position_pct=moonshot_max_pct,
            )

            added.append({"ticker": ticker, "thesis": thesis})
            current_tickers.add(ticker)
            slots_available -= 1
            log.info("Added %s to moonshot list", ticker)

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


def _find_candidate(ticker: str, candidates: list[dict]) -> dict | None:
    """Find a candidate by ticker in the candidates list."""
    for c in candidates:
        if c.get("ticker") == ticker:
            return c
    return None


def _remove_moonshot(ticker: str, reason: str) -> None:
    """Remove a moonshot by setting status to removed in DB."""
    conn = memory._get_db()
    now = __import__("datetime").datetime.now().isoformat()
    conn.execute(
        "UPDATE moonshot_list SET status = 'removed', updated_at = ? WHERE ticker = ? AND status = 'active'",
        (now, ticker),
    )
    conn.commit()
    conn.close()
    log.info("Removed moonshot %s: %s", ticker, reason)


def _has_asymmetric_profile(candidate: dict) -> bool:
    """Check if a candidate has asymmetric risk/reward characteristics.

    Looks for: high sentiment + speculative growth + reasonable market cap,
    or explicit upside/downside cases in the candidate data.
    """
    # If candidate already has explicit asymmetric fields, accept
    if candidate.get("upside_case") and candidate.get("downside_case"):
        return True

    scores = candidate.get("scores", {})
    fund_summary = candidate.get("fundamentals_summary", {})

    # High sentiment + small/mid cap is a moonshot profile
    sentiment_score = scores.get("sentiment", 0)
    market_cap = fund_summary.get("market_cap")

    if sentiment_score >= 60 and market_cap is not None and market_cap < 50_000_000_000:
        return True

    # High technical + fundamental divergence (beaten down but improving)
    tech_score = scores.get("technical", 0)
    fund_score = scores.get("fundamental", 0)
    if tech_score >= 60 and fund_score >= 50:
        return True

    # Strong revenue growth in smaller company
    rev_growth = fund_summary.get("revenue_growth")
    if rev_growth is not None and rev_growth > 0.30 and market_cap is not None and market_cap < 30_000_000_000:
        return True

    return False
