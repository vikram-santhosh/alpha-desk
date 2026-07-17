"""Best-effort web search helpers for research grounding."""
from __future__ import annotations

import os

import requests

from src.utils.logger import get_logger

log = get_logger(__name__)

DEFAULT_TIMEOUT_S = 8


def search(query: str, *, max_results: int = 5) -> list[dict[str, str]]:
    """Return normalized web search results from the configured HTTP provider."""
    query = (query or "").strip()
    if not query or max_results <= 0:
        return []

    try:
        return _search_with_http_provider(query, max_results=max_results)
    except Exception as exc:
        log.warning("HTTP web search failed: %s", exc)
        return []


def _search_with_http_provider(query: str, *, max_results: int) -> list[dict[str, str]]:
    api_key = os.getenv("WEB_SEARCH_API_KEY")
    if not api_key:
        return []

    provider = (os.getenv("WEB_SEARCH_PROVIDER") or "brave").strip().lower()
    timeout = float(os.getenv("WEB_SEARCH_TIMEOUT_S", str(DEFAULT_TIMEOUT_S)))

    if provider == "tavily":
        response = requests.post(
            "https://api.tavily.com/search",
            json={"api_key": api_key, "query": query, "max_results": max_results},
            timeout=timeout,
        )
        response.raise_for_status()
        data = response.json()
        return [
            _normalize_result(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=item.get("content", ""),
                published=item.get("published_date", ""),
            )
            for item in (data.get("results") or [])[:max_results]
            if item.get("url")
        ]

    if provider == "serpapi":
        response = requests.get(
            "https://serpapi.com/search.json",
            params={"engine": "google", "q": query, "api_key": api_key, "num": max_results},
            timeout=timeout,
        )
        response.raise_for_status()
        data = response.json()
        return [
            _normalize_result(
                title=item.get("title", ""),
                url=item.get("link", ""),
                snippet=item.get("snippet", ""),
                published=item.get("date", ""),
            )
            for item in (data.get("organic_results") or [])[:max_results]
            if item.get("link")
        ]

    response = requests.get(
        "https://api.search.brave.com/res/v1/web/search",
        params={"q": query, "count": max_results},
        headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
        timeout=timeout,
    )
    response.raise_for_status()
    data = response.json()
    return [
        _normalize_result(
            title=item.get("title", ""),
            url=item.get("url", ""),
            snippet=item.get("description", ""),
            published=item.get("age", ""),
        )
        for item in ((data.get("web") or {}).get("results") or [])[:max_results]
        if item.get("url")
    ]


def _normalize_result(
    *,
    title: str,
    url: str,
    snippet: str,
    published: str,
) -> dict[str, str]:
    return {
        "title": str(title or url or "Untitled result").strip(),
        "url": str(url or "").strip(),
        "snippet": str(snippet or "").strip(),
        "published": str(published or "").strip(),
    }
