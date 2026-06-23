"""Best-effort web search helpers for research grounding."""
from __future__ import annotations

import os
from typing import Any

import requests

from src.utils.logger import get_logger

log = get_logger(__name__)

DEFAULT_TIMEOUT_S = 8


def search(query: str, *, max_results: int = 5) -> list[dict[str, str]]:
    """Return normalized web search results.

    Gemini Google Search grounding is tried first when Vertex configuration is
    present. A generic HTTP search provider can be enabled with
    ``WEB_SEARCH_API_KEY`` and ``WEB_SEARCH_PROVIDER``.
    """
    query = (query or "").strip()
    if not query or max_results <= 0:
        return []

    try:
        results = _search_with_gemini_grounding(query, max_results=max_results)
        if results:
            return results[:max_results]
    except Exception as exc:
        log.warning("Gemini grounded web search failed: %s", exc)

    try:
        return _search_with_http_provider(query, max_results=max_results)
    except Exception as exc:
        log.warning("HTTP web search failed: %s", exc)
        return []


def _search_with_gemini_grounding(query: str, *, max_results: int) -> list[dict[str, str]]:
    project = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT")
    location = os.getenv("GOOGLE_CLOUD_LOCATION") or os.getenv("GCP_LOCATION") or "us-central1"
    if not project:
        return []

    from google import genai
    from google.genai import types

    client = genai.Client(vertexai=True, project=project, location=location)
    tool = types.Tool(google_search=types.GoogleSearch())
    config = types.GenerateContentConfig(
        tools=[tool],
        max_output_tokens=512,
        temperature=0.0,
    )
    response = client.models.generate_content(
        model=os.getenv("WEB_SEARCH_GEMINI_MODEL", "gemini-3.1-flash-lite-preview"),
        contents=f"Search the web for current, primary-source evidence: {query}",
        config=config,
    )
    return _results_from_grounding_metadata(response, max_results=max_results)


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


def _results_from_grounding_metadata(response: Any, *, max_results: int) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    response_text = getattr(response, "text", "") or ""

    for candidate in getattr(response, "candidates", []) or []:
        metadata = _get_attr(candidate, "grounding_metadata") or _get_attr(candidate, "groundingMetadata")
        chunks = _get_attr(metadata, "grounding_chunks") or _get_attr(metadata, "groundingChunks") or []
        for chunk in chunks:
            web = _get_attr(chunk, "web")
            url = _get_attr(web, "uri") or _get_attr(web, "url")
            if not url or url in seen_urls:
                continue
            title = _get_attr(web, "title") or url
            results.append(
                _normalize_result(
                    title=str(title),
                    url=str(url),
                    snippet=response_text[:500],
                    published="",
                )
            )
            seen_urls.add(url)
            if len(results) >= max_results:
                return results

    return results


def _get_attr(value: Any, name: str) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


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
