"""Source citation tracking for AlphaDesk research outputs."""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit


@dataclass
class Citation:
    citation_id: int
    url: str
    title: str
    source_agent: str
    published_at: str = ""


class CitationRegistry:
    def __init__(self) -> None:
        self._by_url: dict[str, Citation] = {}
        self._ordered: list[Citation] = []

    def register(
        self,
        url: str,
        title: str,
        source_agent: str,
        published_at: str = "",
    ) -> int:
        normalized = self._normalize_url(url)
        if not normalized:
            normalized = f"inline:{len(self._ordered) + 1}"

        existing = self._by_url.get(normalized)
        if existing is not None:
            return existing.citation_id

        citation = Citation(
            citation_id=len(self._ordered) + 1,
            url=url,
            title=title or url or "Untitled source",
            source_agent=source_agent,
            published_at=published_at,
        )
        self._ordered.append(citation)
        self._by_url[normalized] = citation
        return citation.citation_id

    def format_for_prompt(self) -> str:
        if not self._ordered:
            return ""
        lines = ["## SOURCES"]
        for citation in self._ordered:
            meta = f" ({citation.source_agent}"
            if citation.published_at:
                meta += f", {citation.published_at}"
            meta += ")"
            lines.append(f"[{citation.citation_id}] {citation.title}{meta} — {citation.url}")
        return "\n".join(lines)

    def format_for_html(self) -> str:
        if not self._ordered:
            return ""
        items = []
        for citation in self._ordered:
            meta = citation.source_agent
            if citation.published_at:
                meta = f"{meta} · {citation.published_at}"
            items.append(
                f'<li><a href="{citation.url}">{citation.citation_id}. {citation.title}</a>'
                f' <span style="color:#64748b">{meta}</span></li>'
            )
        return "<div class=\"citations\"><h3>Sources</h3><ol>" + "".join(items) + "</ol></div>"

    def as_list(self) -> list[dict[str, str | int]]:
        return [
            {
                "citation_id": citation.citation_id,
                "url": citation.url,
                "title": citation.title,
                "source_agent": citation.source_agent,
                "published_at": citation.published_at,
            }
            for citation in self._ordered
        ]

    def _normalize_url(self, url: str) -> str:
        if not url:
            return ""
        parts = urlsplit(url)
        normalized = parts._replace(query="", fragment="")
        return urlunsplit(normalized)
