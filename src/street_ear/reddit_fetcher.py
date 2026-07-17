"""Reddit fetcher for Street Ear.

Fetches posts from configured subreddits. Reddit now blocks most anonymous
traffic, so this authenticates with app-only OAuth when Reddit credentials are
configured (REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET, optionally
REDDIT_USERNAME / REDDIT_PASSWORD) and falls back to the public JSON endpoint
otherwise. Applies score/comment/age filtering with rate limiting.
"""

import os
import time
from datetime import datetime, timezone
from typing import Any

import requests

from src.shared.config_loader import load_subreddits
from src.shared.security import sanitize_html
from src.utils.logger import get_logger

log = get_logger(__name__)

USER_AGENT = "AlphaDesk/0.1 (market research bot)"
BASE_URL = "https://www.reddit.com/r/{sub}/hot.json?limit={limit}"
OAUTH_BASE_URL = "https://oauth.reddit.com/r/{sub}/hot.json?limit={limit}"
TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
REQUEST_TIMEOUT = 15  # seconds
RATE_LIMIT_DELAY = 2.0  # seconds between requests


def _reddit_user_agent() -> str:
    return os.getenv("REDDIT_USER_AGENT") or USER_AGENT


def _authenticate(session: requests.Session) -> bool:
    """Attach an OAuth bearer token to `session` when Reddit credentials are set.

    Uses the password grant when REDDIT_USERNAME/REDDIT_PASSWORD are present
    (script app), otherwise app-only client_credentials. Returns True when the
    session is authenticated; on any failure logs and returns False so the
    caller can fall back to the (often-empty) public endpoint.
    """
    client_id = os.getenv("REDDIT_CLIENT_ID")
    client_secret = os.getenv("REDDIT_CLIENT_SECRET")
    if not client_id or not client_secret:
        return False

    username = os.getenv("REDDIT_USERNAME")
    password = os.getenv("REDDIT_PASSWORD")
    if username and password:
        data = {"grant_type": "password", "username": username, "password": password}
    else:
        data = {"grant_type": "client_credentials"}

    try:
        response = requests.post(
            TOKEN_URL,
            auth=(client_id, client_secret),
            data=data,
            headers={"User-Agent": _reddit_user_agent()},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        token = response.json().get("access_token")
    except Exception as exc:  # network error, 401, bad JSON — degrade, don't crash
        log.warning("Reddit OAuth failed (%s); falling back to unauthenticated public API", exc)
        return False

    if not token:
        log.warning("Reddit OAuth returned no access_token; falling back to unauthenticated public API")
        return False

    session.headers["Authorization"] = f"bearer {token}"
    log.info("Reddit OAuth authenticated (%s grant)", data["grant_type"])
    return True


def _get_all_subreddits(config: dict[str, Any]) -> list[str]:
    """Extract all subreddit names from config (primary + secondary + thematic).

    Args:
        config: Parsed subreddits.yaml config dict.

    Returns:
        Deduplicated list of subreddit names.
    """
    subs: list[str] = []
    for category in ("primary", "secondary", "thematic"):
        subs.extend(config.get(category, []))
    # Deduplicate while preserving order
    return list(dict.fromkeys(subs))


def _fetch_subreddit(
    subreddit: str,
    limit: int,
    session: requests.Session,
    base_url: str = BASE_URL,
) -> list[dict[str, Any]]:
    """Fetch posts from a single subreddit's hot listing.

    Args:
        subreddit: Name of the subreddit (without r/ prefix).
        limit: Maximum number of posts to fetch.
        session: Requests session with proper headers.
        base_url: URL template (public or authenticated oauth.reddit.com).

    Returns:
        List of raw post data dicts from Reddit API.
    """
    url = base_url.format(sub=subreddit, limit=limit)

    try:
        response = session.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except requests.exceptions.Timeout:
        log.warning("Timeout fetching r/%s", subreddit)
        return []
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else "unknown"
        if status == 429:
            log.warning("Rate limited on r/%s — skipping", subreddit)
        elif status == 403:
            log.warning("r/%s is private or quarantined — skipping", subreddit)
        elif status == 404:
            log.warning("r/%s not found — skipping", subreddit)
        else:
            log.error("HTTP %s fetching r/%s: %s", status, subreddit, e)
        return []
    except requests.exceptions.RequestException as e:
        log.error("Request error fetching r/%s: %s", subreddit, e)
        return []

    try:
        data = response.json()
        children = data.get("data", {}).get("children", [])
        return [child.get("data", {}) for child in children]
    except (ValueError, KeyError) as e:
        log.error("Failed to parse response from r/%s: %s", subreddit, e)
        return []


def _filter_posts(
    posts: list[dict[str, Any]],
    min_score: int,
    min_comments: int,
    max_age_hours: int,
) -> list[dict[str, Any]]:
    """Filter posts by score, comment count, and age.

    Args:
        posts: Raw post data dicts from Reddit API.
        min_score: Minimum upvote score threshold.
        min_comments: Minimum comment count threshold.
        max_age_hours: Maximum post age in hours.

    Returns:
        Filtered list of normalized post dicts.
    """
    now = datetime.now(timezone.utc).timestamp()
    max_age_seconds = max_age_hours * 3600
    filtered: list[dict[str, Any]] = []

    for post in posts:
        # Skip stickied/pinned posts (usually mod announcements)
        if post.get("stickied", False):
            continue

        score = post.get("score", 0)
        num_comments = post.get("num_comments", 0)
        created_utc = post.get("created_utc", 0)

        if score < min_score:
            continue
        if num_comments < min_comments:
            continue
        if (now - created_utc) > max_age_seconds:
            continue

        # Sanitize text content to prevent injection
        title = sanitize_html(post.get("title", ""))
        selftext = sanitize_html(post.get("selftext", ""))

        filtered.append({
            "title": title,
            "selftext": selftext[:2000],  # Cap selftext length for efficiency
            "score": score,
            "num_comments": num_comments,
            "subreddit": post.get("subreddit", ""),
            "url": f"https://reddit.com{post.get('permalink', '')}",
            "created_utc": created_utc,
            "author": post.get("author", "[deleted]"),
        })

    return filtered


def fetch_posts() -> list[dict[str, Any]]:
    """Fetch and filter posts from all configured subreddits.

    Loads subreddit config, fetches hot posts from each subreddit with
    rate limiting, and applies score/comment/age filters.

    Returns:
        List of filtered post dicts with keys:
        title, selftext, score, num_comments, subreddit, url, created_utc, author.
    """
    config = load_subreddits()
    settings = config.get("settings", {})

    min_score = settings.get("min_score", 10)
    min_comments = settings.get("min_comments", 5)
    max_age_hours = settings.get("max_post_age_hours", 24)
    posts_per_sub = settings.get("posts_per_sub", 50)

    subreddits = _get_all_subreddits(config)
    log.info(
        "Fetching from %d subreddits (min_score=%d, min_comments=%d, max_age=%dh)",
        len(subreddits), min_score, min_comments, max_age_hours,
    )

    session = requests.Session()
    session.headers.update({"User-Agent": _reddit_user_agent()})

    authenticated = _authenticate(session)
    base_url = OAUTH_BASE_URL if authenticated else BASE_URL
    if not authenticated:
        log.warning(
            "Reddit fetcher is unauthenticated — set REDDIT_CLIENT_ID/REDDIT_CLIENT_SECRET. "
            "Reddit blocks most anonymous traffic, so results will likely be empty."
        )

    all_posts: list[dict[str, Any]] = []

    for i, sub in enumerate(subreddits):
        # Rate limiting: delay between requests (skip delay before first)
        if i > 0:
            time.sleep(RATE_LIMIT_DELAY)

        raw_posts = _fetch_subreddit(sub, posts_per_sub, session, base_url)
        filtered = _filter_posts(raw_posts, min_score, min_comments, max_age_hours)

        log.info(
            "r/%-20s  fetched=%3d  after_filter=%3d",
            sub, len(raw_posts), len(filtered),
        )
        all_posts.extend(filtered)

    # Deduplicate by URL (cross-posted content)
    seen_urls: set[str] = set()
    unique_posts: list[dict[str, Any]] = []
    for post in all_posts:
        if post["url"] not in seen_urls:
            seen_urls.add(post["url"])
            unique_posts.append(post)

    log.info(
        "Total posts: %d (deduplicated from %d)",
        len(unique_posts), len(all_posts),
    )
    return unique_posts
