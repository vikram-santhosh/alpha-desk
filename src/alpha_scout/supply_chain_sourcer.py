"""Supply-chain candidate sourcing for Alpha Scout v2.

Explores the value chain around each holding to find related tickers
that aren't in the current portfolio. Uses a static supply chain map
(loaded from config) with optional LLM enrichment.
"""

from collections import Counter
from typing import Any

import yaml

from src.utils.logger import get_logger

log = get_logger(__name__)

_SUPPLY_CHAIN_MAP: dict | None = None


def _load_supply_chain_map() -> dict:
    """Load supply chain map from config/supply_chain.yaml."""
    global _SUPPLY_CHAIN_MAP
    if _SUPPLY_CHAIN_MAP is not None:
        return _SUPPLY_CHAIN_MAP

    try:
        with open("config/supply_chain.yaml") as f:
            _SUPPLY_CHAIN_MAP = yaml.safe_load(f) or {}
    except FileNotFoundError:
        log.warning("config/supply_chain.yaml not found — supply chain sourcing disabled")
        _SUPPLY_CHAIN_MAP = {}
    except Exception:
        log.exception("Failed to load supply chain map")
        _SUPPLY_CHAIN_MAP = {}

    return _SUPPLY_CHAIN_MAP


def source_from_supply_chain(
    holdings: list[dict[str, Any]],
    existing_tickers: set[str],
) -> list[dict[str, Any]]:
    """Source candidates from supply chain relationships of holdings.

    For each holding, look up the supply chain map and create candidates
    from related tickers not already in the portfolio.

    Priority: competitors > adjacent > suppliers > customers.

    Args:
        holdings: Portfolio holdings list (each with 'ticker' key).
        existing_tickers: Set of tickers already tracked (to exclude).

    Returns:
        List of candidate dicts with source, signal_type, signal_data.
    """
    chain_map = _load_supply_chain_map()
    if not chain_map:
        return []

    candidates: list[dict[str, Any]] = []
    ticker_appearances: Counter = Counter()
    existing_upper = {t.upper() for t in existing_tickers}

    # Priority order for relationship types
    relationship_priority = ["competitors", "adjacent", "suppliers", "customers"]

    for holding in holdings:
        holding_ticker = holding.get("ticker", "")
        chain = chain_map.get(holding_ticker, {})
        if not chain:
            continue

        for rel_type in relationship_priority:
            related_tickers = chain.get(rel_type, [])
            for related in related_tickers:
                related_upper = related.upper()
                if related_upper in existing_upper:
                    continue

                ticker_appearances[related_upper] += 1
                candidates.append({
                    "ticker": related,
                    "source": f"supply_chain/{holding_ticker}/{rel_type}",
                    "signal_type": "supply_chain",
                    "signal_data": {
                        "holding": holding_ticker,
                        "relationship": rel_type,
                        "multi_chain_count": ticker_appearances[related_upper],
                    },
                })

    # Deduplicate — keep first occurrence but update multi_chain_count
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for cand in candidates:
        t = cand["ticker"].upper()
        if t in seen:
            continue
        seen.add(t)
        # Update with final count
        cand["signal_data"]["multi_chain_count"] = ticker_appearances[t]
        unique.append(cand)

    # Sort by multi_chain_count descending (tickers appearing in multiple chains first)
    unique.sort(key=lambda c: -c["signal_data"]["multi_chain_count"])

    log.info(
        "Supply chain sourced %d unique candidates from %d holdings (%d raw)",
        len(unique), len(holdings), len(candidates),
    )
    return unique


def compute_multi_chain_bonus(ticker: str, appearances: int) -> int:
    """Bonus score for tickers that appear in multiple holdings' chains."""
    if appearances >= 4:
        return 30
    if appearances >= 3:
        return 20
    if appearances >= 2:
        return 10
    return 0
