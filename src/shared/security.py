"""Security utilities: env validation, input sanitization, auth."""

import html
import os
import re
from pathlib import Path

from dotenv import load_dotenv

from src.utils.logger import get_logger

log = get_logger(__name__)

REQUIRED_KEYS = [
    "ANTHROPIC_API_KEY",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
]

OPTIONAL_KEYS = [
    "FINNHUB_API_KEY",
    "NEWSAPI_KEY",
    "DAILY_COST_CAP",
]


def validate_env() -> dict[str, str]:
    """Load .env and validate all required keys are present.

    Returns:
        Dict of all env vars (required + optional that exist).

    Raises:
        EnvironmentError: If any required key is missing.
    """
    load_dotenv()

    missing = [k for k in REQUIRED_KEYS if not os.getenv(k)]
    if missing:
        raise EnvironmentError(
            f"Missing required environment variables: {', '.join(missing)}"
        )

    env = {}
    for k in REQUIRED_KEYS + OPTIONAL_KEYS:
        val = os.getenv(k)
        if val:
            env[k] = val

    log.info(
        "Environment validated: %d required, %d optional loaded",
        len(REQUIRED_KEYS),
        len(env) - len(REQUIRED_KEYS),
    )
    return env


def sanitize_html(text: str) -> str:
    """Escape HTML special characters to prevent injection in Telegram messages."""
    return html.escape(text, quote=True)


def sanitize_ticker(ticker: str) -> str:
    """Validate and sanitize a stock ticker symbol.

    Returns:
        Uppercased ticker with only alphanumeric chars and dots.

    Raises:
        ValueError: If ticker is invalid.
    """
    cleaned = re.sub(r"[^A-Za-z0-9.]", "", ticker).upper()
    if not cleaned or len(cleaned) > 10:
        raise ValueError(f"Invalid ticker: {ticker!r}")
    return cleaned


def authorize_chat(chat_id: str | int) -> bool:
    """Check if a Telegram chat ID is authorized."""
    allowed = os.getenv("TELEGRAM_CHAT_ID", "")
    return str(chat_id) == str(allowed)


def check_no_secrets_in_path(path: Path) -> bool:
    """Check that a file path doesn't point to a secrets file."""
    dangerous = {".env", "credentials.json", "secrets.yaml", "token.json"}
    return path.name not in dangerous
