"""13F Filing Scanner for AlphaDesk.

Scans SEC EDGAR for superinvestor 13F filings and identifies new positions
by comparing current holdings to previous filings stored in memory.
"""

from typing import Any

from src.utils.logger import get_logger

log = get_logger(__name__)


def scan_new_positions(
    config: dict[str, Any],
    exclude_tickers: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Scan all configured superinvestors for new 13F positions.

    Wraps the existing superinvestor_tracker's get_new_positions_as_candidates()
    and enriches the output with position_value and pct_of_portfolio data.

    Args:
        config: Advisor config dict (must have 'superinvestors' key).
        exclude_tickers: Set of tickers to exclude (portfolio holdings).

    Returns:
        List of candidate dicts compatible with the AlphaDesk candidate schema.
    """
    exclude = {t.upper() for t in (exclude_tickers or set())}
    candidates: list[dict] = []

    try:
        from src.advisor.superinvestor_tracker import get_new_positions_as_candidates
        raw_candidates = get_new_positions_as_candidates(config)
    except ImportError:
        log.warning("superinvestor_tracker not available — skipping 13F scan")
        return []
    except Exception:
        log.exception("Failed to run 13F position scan")
        return []

    for raw in raw_candidates:
        ticker = raw.get("ticker", "").upper()
        if not ticker or ticker in exclude:
            continue

        signal_data = raw.get("signal_data", {})
        fund_name = signal_data.get("investor", "Unknown")
        position_value = signal_data.get("value_usd")
        shares = signal_data.get("shares")

        # Filter: exclude tiny positions (< $5M if value is known)
        if position_value is not None and position_value < 5_000_000:
            log.debug("Excluding %s — position value $%.1fM < $5M threshold",
                      ticker, position_value / 1e6)
            continue

        candidate = {
            "ticker": ticker,
            "source": f"13f_new_position/{fund_name.replace(' ', '_')}",
            "signal_type": "superinvestor_new_position",
            "signal_data": {
                "fund_name": fund_name,
                "position_value": position_value,
                "shares": shares,
                "pct_of_portfolio": None,  # FMP doesn't always provide this
                "filing_date": raw.get("signal_data", {}).get("filing_date"),
            },
            "scores": {"composite": 60},
            "fundamentals_summary": {},
        }
        candidates.append(candidate)

    log.info("13F scanner: %d new position candidates (excl %d portfolio tickers)",
             len(candidates), len(exclude))
    return candidates
