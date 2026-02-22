"""AlphaDesk News Desk — market news intelligence pipeline.

Fetches news from Finnhub and NewsAPI, analyzes with Claude Opus 4.6,
publishes inter-agent signals, and formats Telegram-ready digests.
"""

from src.news_desk.main import run

__all__ = ["run"]
