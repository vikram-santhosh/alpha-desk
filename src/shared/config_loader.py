"""YAML config loading with validation for AlphaDesk."""

from pathlib import Path
from typing import Any

import yaml

from src.utils.logger import get_logger

log = get_logger(__name__)

CONFIG_DIR = Path("config")


def load_config(name: str) -> dict[str, Any]:
    """Load a YAML config file from the config/ directory.

    Args:
        name: Config filename without extension (e.g. 'portfolio').

    Returns:
        Parsed YAML as a dict.

    Raises:
        FileNotFoundError: If config file doesn't exist.
        yaml.YAMLError: If YAML is malformed.
    """
    path = CONFIG_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")

    with open(path) as f:
        data = yaml.safe_load(f)

    log.info("Loaded config: %s (%d keys)", name, len(data) if data else 0)
    return data or {}


def load_portfolio() -> dict[str, Any]:
    """Load portfolio holdings config."""
    return load_config("portfolio")


def load_watchlist() -> dict[str, Any]:
    """Load watchlist config."""
    return load_config("watchlist")


def load_subreddits() -> dict[str, Any]:
    """Load subreddits config."""
    return load_config("subreddits")


def load_scout_config() -> dict[str, Any]:
    """Load Alpha Scout config."""
    return load_config("scout")


def load_advisor_config() -> dict[str, Any]:
    """Load Advisor config."""
    return load_config("advisor")


def _normalize_ticker(ticker: Any) -> str:
    """Normalize ticker values for config reconciliation."""
    return str(ticker or "").strip().upper()


def _holdings_by_ticker(holdings: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Map holding rows by normalized ticker, dropping malformed rows."""
    mapped: dict[str, dict[str, Any]] = {}
    for holding in holdings:
        ticker = _normalize_ticker(holding.get("ticker"))
        if not ticker:
            log.warning("Ignoring holding without ticker in config: %s", holding)
            continue
        mapped[ticker] = dict(holding, ticker=ticker)
    return mapped


def reconcile_holdings(
    portfolio_config: dict[str, Any],
    advisor_config: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return actual holdings enriched with advisor ticker metadata.

    ``portfolio.yaml`` owns position facts such as ticker, shares, and cost basis.
    ``advisor.yaml`` may still carry thesis/category metadata for those tickers.
    Tickers present in only one config are logged so config drift is visible.
    """
    portfolio_holdings = portfolio_config.get("holdings") or []
    advisor_holdings = advisor_config.get("holdings") or []
    portfolio_by_ticker = _holdings_by_ticker(portfolio_holdings)
    advisor_by_ticker = _holdings_by_ticker(advisor_holdings)

    portfolio_tickers = set(portfolio_by_ticker)
    advisor_tickers = set(advisor_by_ticker)
    missing_metadata = sorted(portfolio_tickers - advisor_tickers)
    stale_metadata = sorted(advisor_tickers - portfolio_tickers)

    if missing_metadata:
        log.warning(
            "Portfolio holdings missing advisor metadata: %s",
            ", ".join(missing_metadata),
        )
    if stale_metadata:
        log.warning(
            "Advisor holdings metadata not present in portfolio.yaml and will not be treated as held: %s",
            ", ".join(stale_metadata),
        )

    unified: list[dict[str, Any]] = []
    for raw_holding in portfolio_holdings:
        ticker = _normalize_ticker(raw_holding.get("ticker"))
        if not ticker:
            continue
        position = dict(raw_holding, ticker=ticker)
        metadata = advisor_by_ticker.get(ticker, {})

        # Advisor metadata enriches the actual position but never creates one.
        for key, value in metadata.items():
            if key not in {"ticker", "shares", "cost_basis", "entry_price", "portfolio_pct"}:
                position.setdefault(key, value)
        position.setdefault("category", "core")
        position.setdefault("thesis", "")

        if "entry_price" not in position and position.get("cost_basis") is not None:
            position["entry_price"] = position["cost_basis"]

        unified.append(position)

    return unified


def load_unified_holdings(
    *,
    advisor_config: dict[str, Any] | None = None,
    portfolio_config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Load actual portfolio holdings with advisor metadata attached."""
    if advisor_config is None:
        advisor_config = load_advisor_config()
    if portfolio_config is None:
        portfolio_config = load_portfolio()
    return reconcile_holdings(portfolio_config, advisor_config)


def load_advisor_config_with_portfolio() -> dict[str, Any]:
    """Load advisor config with holdings reconciled from portfolio.yaml."""
    config = load_advisor_config()
    config["holdings"] = load_unified_holdings(advisor_config=config)
    return config


def get_all_tickers() -> list[str]:
    """Get combined list of tickers from portfolio and watchlist."""
    portfolio = load_portfolio()
    watchlist = load_watchlist()

    tickers = [h["ticker"] for h in portfolio.get("holdings", [])]
    tickers.extend(watchlist.get("tickers", []))
    return list(dict.fromkeys(tickers))  # deduplicate, preserve order
