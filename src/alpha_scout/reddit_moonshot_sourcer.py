"""Reddit moonshot candidate sourcer for AlphaDesk.

Scans small-cap and value-oriented subreddits to find non-obvious ticker
candidates with unusual Reddit traction. Complements the S&P 500/screener
pipeline with grassroots discovery.
"""
from __future__ import annotations

import re
import time
from collections import defaultdict
from typing import Any

import requests

from src.shared.config_loader import load_subreddits
from src.shared.security import sanitize_ticker
from src.utils.logger import get_logger

log = get_logger(__name__)

USER_AGENT = "AlphaDesk/0.1 (market research bot)"
BASE_URL = "https://www.reddit.com/r/{sub}/hot.json?limit={limit}"
REQUEST_TIMEOUT = 15
RATE_LIMIT_DELAY = 2.0

MOONSHOT_SUBREDDITS = [
    "smallstreetbets",
    "pennystocks",
    "valueinvesting",
    "SecurityAnalysis",
    "Biotechplays",
    "spacs",
    "thecorporation",
    "undervaluedstonks",
]

# Regex to find $TICKER or standalone uppercase words that look like tickers
_TICKER_PATTERN = re.compile(r'\$([A-Z]{2,5})\b|(?<!\w)([A-Z]{2,5})(?!\w)')

# Common words that look like tickers but aren't
_TICKER_BLACKLIST = {
    "THE", "AND", "FOR", "ARE", "BUT", "NOT", "YOU", "ALL", "CAN", "HAD",
    "HER", "WAS", "ONE", "OUR", "OUT", "DAY", "GET", "HAS", "HIM", "HIS",
    "HOW", "ITS", "LET", "MAY", "NEW", "NOW", "OLD", "SEE", "WAY", "WHO",
    "DID", "GOT", "HIT", "BIG", "LOW", "TOP", "PUT", "RUN", "SAY", "SHE",
    "TOO", "USE", "IPO", "ETF", "CEO", "CFO", "DD", "AI", "GDP", "ATH",
    "LOL", "IMO", "FOMO", "YOLO", "WSB", "HODL", "BULL", "BEAR", "PUTS",
    "CALL", "LONG", "SHORT", "PUMP", "DUMP", "RISK", "SELL", "BUY", "HOLD",
    "MOON", "GAIN", "LOSS", "CASH", "DEBT", "FUND", "STOCK", "EDIT",
    "JUST", "LIKE", "THIS", "THAT", "WITH", "FROM", "HAVE", "BEEN",
    "WILL", "WHAT", "WHEN", "YOUR", "SOME", "THEM", "THAN", "EACH",
    "MAKE", "MADE", "VERY", "MUCH", "ALSO", "MORE", "DOES", "OVER",
    "SUCH", "INTO", "YEAR", "BACK", "MOST", "ONLY", "COME", "TAKE",
    "GOOD", "WELL", "DOWN", "EVEN", "LAST", "SAME", "ABLE", "WEEK",
    "LOOK", "WORK", "NEED", "MANY", "REAL", "HIGH", "PART", "GROW",
    "SAID", "LOVE", "HALF", "PLAY", "MOVE", "BEST", "KEEP",
}

MAX_MCAP_USD = 50_000_000_000  # $50B — exclude mega-caps


def _extract_tickers_from_text(text: str) -> list[str]:
    """Extract potential stock tickers from text using regex.

    Looks for $TICKER patterns and standalone uppercase 2-5 letter words.
    Filters out common English words and known non-ticker patterns.
    """
    matches = _TICKER_PATTERN.findall(text)
    tickers = set()
    for dollar_match, standalone_match in matches:
        ticker = dollar_match or standalone_match
        if ticker and ticker.upper() not in _TICKER_BLACKLIST:
            tickers.add(ticker.upper())
    return list(tickers)


def _validate_tickers(tickers: list[str]) -> dict[str, dict]:
    """Validate tickers using yfinance quick info lookup.

    Returns dict of valid tickers mapped to basic info (market_cap, name).
    """
    valid = {}
    try:
        import yfinance as yf
    except ImportError:
        log.warning("yfinance not installed — cannot validate tickers")
        return valid

    for ticker in tickers:
        try:
            t = yf.Ticker(ticker)
            info = t.fast_info
            market_cap = getattr(info, "market_cap", None)
            if market_cap and market_cap > 0:
                valid[ticker] = {
                    "market_cap": market_cap,
                    "name": getattr(info, "currency", ticker),
                }
        except Exception:
            pass  # Invalid ticker, skip silently

    return valid


def _fetch_subreddit_posts(
    subreddit: str, limit: int, session: requests.Session,
) -> list[dict[str, Any]]:
    """Fetch posts from a single subreddit's hot listing."""
    url = BASE_URL.format(sub=subreddit, limit=limit)
    try:
        response = session.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        data = response.json()
        children = data.get("data", {}).get("children", [])
        return [child.get("data", {}) for child in children]
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else "unknown"
        if status == 429:
            log.warning("Rate limited on r/%s — skipping", subreddit)
        elif status in (403, 404):
            log.debug("r/%s unavailable (HTTP %s) — skipping", subreddit, status)
        else:
            log.warning("HTTP %s fetching r/%s", status, subreddit)
        return []
    except Exception:
        log.exception("Error fetching r/%s", subreddit)
        return []


def source_moonshot_candidates(
    exclude_tickers: set[str] | None = None,
    config: dict | None = None,
) -> list[dict[str, Any]]:
    """Scan moonshot subreddits and return ticker candidates.

    Args:
        exclude_tickers: Set of tickers to exclude (portfolio + watchlist).
        config: Optional config dict with subreddits settings.

    Returns:
        List of candidate dicts compatible with the AlphaDesk candidate schema.
    """
    exclude = {t.upper() for t in (exclude_tickers or set())}
    settings = {}
    if config:
        settings = config.get("settings", {})

    min_score = settings.get("min_score", 5)  # Lower threshold for moonshot subs
    posts_per_sub = settings.get("posts_per_sub", 50)

    # Load moonshot subreddits from config or use defaults
    subreddits_config = load_subreddits() if not config else config
    moonshot_subs = subreddits_config.get("moonshot", MOONSHOT_SUBREDDITS)
    if not moonshot_subs:
        moonshot_subs = MOONSHOT_SUBREDDITS

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    # Track ticker mentions across all posts
    ticker_mentions: dict[str, list[dict]] = defaultdict(list)

    for i, sub in enumerate(moonshot_subs):
        if i > 0:
            time.sleep(RATE_LIMIT_DELAY)

        posts = _fetch_subreddit_posts(sub, posts_per_sub, session)
        log.info("r/%-20s fetched=%3d", sub, len(posts))

        for post in posts:
            if post.get("stickied", False):
                continue
            score = post.get("score", 0)
            if score < min_score:
                continue

            title = post.get("title", "")
            selftext = post.get("selftext", "")[:2000]
            combined_text = f"{title} {selftext}"

            tickers_found = _extract_tickers_from_text(combined_text)

            for ticker in tickers_found:
                if ticker in exclude:
                    continue
                ticker_mentions[ticker].append({
                    "title": title[:200],
                    "score": score,
                    "num_comments": post.get("num_comments", 0),
                    "subreddit": sub,
                    "url": f"https://reddit.com{post.get('permalink', '')}",
                })

    # Filter to tickers with at least 2 mentions
    candidates_raw = {
        ticker: posts for ticker, posts in ticker_mentions.items()
        if len(posts) >= 2
    }

    if not candidates_raw:
        log.info("Reddit moonshot: no candidates with 2+ mentions")
        return []

    # Validate tickers with yfinance
    all_candidate_tickers = list(candidates_raw.keys())
    valid_tickers = _validate_tickers(all_candidate_tickers)

    # Build scored candidates
    scored_candidates: list[dict] = []
    for ticker, posts in candidates_raw.items():
        if ticker not in valid_tickers:
            continue

        info = valid_tickers[ticker]
        market_cap = info.get("market_cap", 0)

        # Exclude mega-caps
        if market_cap and market_cap > MAX_MCAP_USD:
            log.debug("Excluding %s — market cap $%.1fB > $50B", ticker, market_cap / 1e9)
            continue

        mention_count = len(posts)
        total_score = sum(p["score"] for p in posts)
        subreddits_seen = list(set(p["subreddit"] for p in posts))
        subreddit_diversity = len(subreddits_seen)
        sample_titles = list(set(p["title"] for p in posts))[:3]

        # Sentiment divergence: high variance in scores = interesting debate
        if mention_count > 1:
            scores = [p["score"] for p in posts]
            mean_score = sum(scores) / len(scores)
            variance = sum((s - mean_score) ** 2 for s in scores) / len(scores)
            sentiment_divergence = min(1.0, (variance ** 0.5) / (mean_score + 1))
        else:
            sentiment_divergence = 0.0

        # Composite score: weighted by mentions, score, and diversity
        composite = min(100, int(
            mention_count * 5
            + min(total_score / 100, 30)
            + subreddit_diversity * 10
            + sentiment_divergence * 10
        ))

        scored_candidates.append({
            "ticker": ticker,
            "source": f"reddit_moonshot/{'+'.join(subreddits_seen[:3])}",
            "signal_type": "reddit_moonshot",
            "signal_data": {
                "mention_count": mention_count,
                "total_score": total_score,
                "top_subreddits": subreddits_seen[:5],
                "sample_titles": sample_titles,
                "sentiment_divergence": round(sentiment_divergence, 2),
                "market_cap": market_cap,
            },
            "scores": {
                "composite": composite,
                "sentiment": min(100, int(total_score / max(mention_count, 1))),
            },
            "fundamentals_summary": {
                "market_cap": market_cap,
            },
        })

    # Sort by composite score descending
    scored_candidates.sort(
        key=lambda c: c["scores"]["composite"], reverse=True
    )

    # Return top 10
    result = scored_candidates[:10]
    log.info(
        "Reddit moonshot: %d candidates (from %d tickers with 2+ mentions, %d validated)",
        len(result), len(candidates_raw), len(valid_tickers),
    )
    return result
