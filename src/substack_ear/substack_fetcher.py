"""Substack RSS fetcher for Substack Ear.

Fetches recent articles from configured Substack newsletters via RSS feeds.
Strips HTML from content and returns articles in a schema compatible with
the Reddit post format used downstream.
"""

import re
import time
from html.parser import HTMLParser
from typing import Any

import feedparser

from src.shared.config_loader import load_config
from src.utils.logger import get_logger

log = get_logger(__name__)


class _HTMLTextExtractor(HTMLParser):
    """Strip HTML tags and extract plain text."""

    def __init__(self):
        super().__init__()
        self._text: list[str] = []

    def handle_data(self, data: str) -> None:
        self._text.append(data)

    def get_text(self) -> str:
        return "".join(self._text)


def _strip_html(html_content: str) -> str:
    """Remove HTML tags and return plain text."""
    extractor = _HTMLTextExtractor()
    try:
        extractor.feed(html_content)
        return extractor.get_text()
    except Exception:
        # Fallback to regex if parser fails
        return re.sub(r"<[^>]+>", "", html_content)


def fetch_articles() -> list[dict[str, Any]]:
    """Fetch recent articles from all configured Substack newsletters.

    Loads newsletter config from config/substacks.yaml, fetches RSS feeds,
    strips HTML, and returns articles in the standard post schema.

    Returns:
        List of article dicts matching the Reddit post schema:
        - title, selftext, score, num_comments, subreddit (publication name),
          url, created_utc, author, source_platform
    """
    config = load_config("substacks")
    newsletters_config = config.get("newsletters", {})
    settings = config.get("settings", {})

    max_age_hours = settings.get("max_article_age_hours", 72)
    max_chars = settings.get("max_article_chars", 8000)
    max_per_newsletter = settings.get("max_articles_per_newsletter", 3)

    cutoff_time = time.time() - (max_age_hours * 3600)

    all_articles: list[dict[str, Any]] = []

    # Flatten all newsletter categories
    all_newsletters: list[dict[str, str]] = []
    for _category, newsletters in newsletters_config.items():
        if isinstance(newsletters, list):
            all_newsletters.extend(newsletters)

    log.info("Fetching articles from %d newsletters", len(all_newsletters))

    for newsletter in all_newsletters:
        name = newsletter.get("name", "Unknown")
        slug = newsletter.get("slug", "")
        if not slug:
            log.warning("Skipping newsletter with no slug: %s", name)
            continue

        feed_url = f"https://{slug}.substack.com/feed"

        try:
            feed = feedparser.parse(feed_url)

            if feed.bozo and not feed.entries:
                log.warning("Failed to parse feed for %s (%s): %s", name, feed_url, feed.bozo_exception)
                continue

            count = 0
            for entry in feed.entries:
                if count >= max_per_newsletter:
                    break

                # Parse publication time
                published_parsed = entry.get("published_parsed")
                if published_parsed:
                    created_utc = time.mktime(published_parsed)
                else:
                    created_utc = time.time()

                # Skip old articles
                if created_utc < cutoff_time:
                    continue

                # Extract content — prefer content field, fall back to summary
                raw_content = ""
                if hasattr(entry, "content") and entry.content:
                    raw_content = entry.content[0].get("value", "")
                elif hasattr(entry, "summary"):
                    raw_content = entry.summary or ""

                # Strip HTML and cap length
                selftext = _strip_html(raw_content)
                if len(selftext) > max_chars:
                    selftext = selftext[:max_chars]

                article = {
                    "title": entry.get("title", ""),
                    "selftext": selftext,
                    "score": 0,
                    "num_comments": 0,
                    "subreddit": name,
                    "url": entry.get("link", ""),
                    "created_utc": created_utc,
                    "author": entry.get("author", name),
                    "source_platform": "substack",
                }
                all_articles.append(article)
                count += 1

            log.info("Fetched %d articles from %s", count, name)

        except Exception as e:
            log.error("Error fetching %s (%s): %s", name, feed_url, e)
            continue

    log.info("Total articles fetched: %d", len(all_articles))
    return all_articles
