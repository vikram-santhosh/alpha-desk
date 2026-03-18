"""Second-order play discovery via supply chain relationships.

Maps supply chain relationships (suppliers, customers, competitors) to find
investment opportunities when a primary holding moves significantly.  When a
holding has |change_pct| > 3%, the module surfaces related tickers that are
NOT already in the portfolio as potential second-order plays.
"""
from __future__ import annotations

from typing import Any

from src.utils.logger import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Fallback static map — used when config/supply_chain.yaml is unavailable
# ---------------------------------------------------------------------------
SUPPLY_CHAIN_MAP: dict[str, dict[str, list[str]]] = {
    "NVDA": {
        "suppliers": ["TSM", "AVGO", "MRVL"],
        "customers": ["MSFT", "GOOG", "META", "AMZN"],
        "competitors": ["AMD", "INTC"],
    },
    "AMZN": {
        "suppliers": ["NVDA", "INTC"],
        "customers": [],
        "competitors": ["MSFT", "GOOG"],
    },
    "GOOG": {
        "suppliers": ["TSM", "NVDA", "MRVL"],
        "customers": [],
        "competitors": ["META", "MSFT", "AMZN"],
    },
    "META": {
        "suppliers": ["NVDA", "TSM", "MRVL"],
        "customers": [],
        "competitors": ["GOOG", "SNAP", "PINS"],
    },
    "MSFT": {
        "suppliers": ["NVDA", "AMD", "INTC", "TSM"],
        "customers": [],
        "competitors": ["GOOG", "AMZN", "CRM"],
    },
    "AVGO": {
        "suppliers": ["TSM", "ASML"],
        "customers": ["AAPL", "MSFT", "GOOG", "META"],
        "competitors": ["MRVL", "QCOM", "TXN"],
    },
    "VRT": {
        "suppliers": [],
        "customers": ["EQIX", "DLR", "MSFT", "GOOG", "AMZN"],
        "competitors": ["ETN", "ROK", "EMR"],
    },
    "MRVL": {
        "suppliers": ["TSM", "ASML"],
        "customers": ["MSFT", "AMZN", "GOOG", "META"],
        "competitors": ["AVGO", "QCOM"],
    },
    "NFLX": {
        "suppliers": [],
        "customers": [],
        "competitors": ["DIS", "WBD", "CMCSA", "AMZN"],
    },
    "AAPL": {
        "suppliers": ["TSM", "AVGO", "QCOM", "TXN"],
        "customers": [],
        "competitors": ["GOOG", "MSFT"],
    },
    "AMD": {
        "suppliers": ["TSM", "ASML", "KLAC", "LRCX"],
        "customers": ["MSFT", "GOOG", "META", "AMZN"],
        "competitors": ["NVDA", "INTC", "QCOM"],
    },
    "TSM": {
        "suppliers": ["ASML", "KLAC", "LRCX", "AMAT"],
        "customers": ["AAPL", "NVDA", "AMD", "AVGO", "QCOM", "MRVL"],
        "competitors": ["INTC", "GFS"],
    },
}

_CHANGE_THRESHOLD = 3.0  # percent — only look at holdings moving more than this
_MAX_CANDIDATES = 5


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------
def load_supply_chain_map() -> dict[str, dict[str, list[str]]]:
    """Load the supply chain map from *config/supply_chain.yaml*.

    Falls back to the in-module ``SUPPLY_CHAIN_MAP`` if the file is missing
    or cannot be parsed.
    """
    try:
        from src.shared.config_loader import load_config

        raw: dict[str, Any] = load_config("supply_chain")
        # Normalise: ensure every value is a dict of string -> list[str]
        chain_map: dict[str, dict[str, list[str]]] = {}
        for ticker, relations in raw.items():
            if not isinstance(relations, dict):
                continue
            chain_map[ticker] = {
                rel_type: [str(t) for t in tickers]
                for rel_type, tickers in relations.items()
                if isinstance(tickers, list)
            }
        log.info("Loaded supply chain map from YAML (%d tickers)", len(chain_map))
        return chain_map
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not load supply_chain.yaml, using fallback: %s", exc)
        return SUPPLY_CHAIN_MAP


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------
_RELATION_LABELS: dict[str, str] = {
    "suppliers": "supplier of",
    "customers": "customer of",
    "competitors": "competitor of",
    "adjacent": "adjacent to",
}


def find_second_order_plays(
    holdings_reports: list[dict],
    existing_tickers: set[str],
) -> list[dict]:
    """Discover second-order plays from supply chain relationships.

    For each holding whose absolute daily change exceeds the threshold,
    look up related tickers and return those that are *not* already held.

    Args:
        holdings_reports: List of holding report dicts.  Each must contain
            at least ``ticker`` (str) and ``change_pct`` (float).
        existing_tickers: Set of tickers already in the portfolio or
            watchlist — candidates found here are excluded.

    Returns:
        Up to ``_MAX_CANDIDATES`` candidate dicts, each with:
        - ``ticker`` — the related ticker
        - ``source`` — human-readable description of the relationship
        - ``signal_type`` — always ``"supply_chain"``
        - ``signal_data`` — dict with ``primary_ticker``, ``relationship``,
          ``primary_change_pct``
    """
    chain_map = load_supply_chain_map()
    candidates: list[dict] = []
    seen: set[str] = set()

    # Sort by magnitude of change so the strongest movers are processed first
    sorted_reports = sorted(
        holdings_reports,
        key=lambda r: abs(r.get("change_pct", 0.0)),
        reverse=True,
    )

    for report in sorted_reports:
        ticker: str = report.get("ticker", "")
        change_pct: float = report.get("change_pct", 0.0)

        if abs(change_pct) < _CHANGE_THRESHOLD:
            continue

        relations = chain_map.get(ticker)
        if not relations:
            continue

        direction = "up" if change_pct > 0 else "down"

        for rel_type, related_tickers in relations.items():
            label = _RELATION_LABELS.get(rel_type, rel_type)
            for related in related_tickers:
                if related in existing_tickers or related in seen:
                    continue
                seen.add(related)

                candidates.append(
                    {
                        "ticker": related,
                        "source": f"{related} is {label} {ticker} ({direction} {abs(change_pct):.1f}%)",
                        "signal_type": "supply_chain",
                        "signal_data": {
                            "primary_ticker": ticker,
                            "relationship": rel_type,
                            "primary_change_pct": change_pct,
                        },
                    }
                )

                if len(candidates) >= _MAX_CANDIDATES:
                    log.info(
                        "Found %d second-order candidates (capped)",
                        len(candidates),
                    )
                    return candidates

    log.info("Found %d second-order candidates", len(candidates))
    return candidates
