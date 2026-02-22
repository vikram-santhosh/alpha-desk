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


def get_all_tickers() -> list[str]:
    """Get combined list of tickers from portfolio and watchlist."""
    portfolio = load_portfolio()
    watchlist = load_watchlist()

    tickers = [h["ticker"] for h in portfolio.get("holdings", [])]
    tickers.extend(watchlist.get("tickers", []))
    return list(dict.fromkeys(tickers))  # deduplicate, preserve order
