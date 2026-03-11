"""Priority-aware prompt context compression for AlphaDesk."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.utils.logger import get_logger

log = get_logger(__name__)

DEFAULT_PRIORITY_ORDER = {
    "mandate_breaches": 100,
    "holdings": 90,
    "holdings_data": 90,
    "analyst_reports": 80,
    "delta_summary": 70,
    "delta": 70,
    "news": 60,
    "reddit": 50,
    "substack": 40,
}


@dataclass
class ContextSection:
    name: str
    content: str
    priority: int


class ContextBudget:
    """Collects prompt sections and truncates low-priority content first."""

    def __init__(self, token_budget: int = 12000):
        self.token_budget = max(int(token_budget), 256)
        self._sections: list[ContextSection] = []

    def add_section(self, name: str, content: Any, priority: int | str) -> None:
        text = str(content or "").strip()
        if not text:
            return

        resolved_priority = self._resolve_priority(priority)
        self._sections.append(ContextSection(name=name, content=text, priority=resolved_priority))

    def render(self) -> str:
        if not self._sections:
            return ""

        sections = sorted(
            enumerate(self._sections),
            key=lambda item: (-item[1].priority, item[0]),
        )

        remaining_tokens = self.token_budget
        rendered: list[str] = []

        for _, section in sections:
            section_text = f"## {section.name}\n{section.content}"
            section_tokens = self.estimate_tokens(section_text)
            if section_tokens <= remaining_tokens:
                rendered.append(section_text)
                remaining_tokens -= section_tokens
                continue

            truncated = self._truncate_to_budget(section_text, remaining_tokens)
            if truncated:
                rendered.append(truncated)
                remaining_tokens = 0
            break

        combined = "\n\n".join(rendered).strip()
        log.debug(
            "ContextBudget rendered %d/%d sections into ~%d tokens",
            len(rendered),
            len(self._sections),
            self.estimate_tokens(combined),
        )
        return combined

    @staticmethod
    def estimate_tokens(text: str) -> int:
        if not text:
            return 0
        return max(1, len(text) // 4)

    def _resolve_priority(self, priority: int | str) -> int:
        if isinstance(priority, int):
            return priority
        return DEFAULT_PRIORITY_ORDER.get(str(priority).lower(), 10)

    def _truncate_to_budget(self, text: str, token_budget: int) -> str:
        if token_budget <= 16:
            return ""

        char_budget = token_budget * 4
        if char_budget >= len(text):
            return text

        clipped = text[: max(char_budget - 24, 0)].rstrip()
        last_break = max(clipped.rfind("\n"), clipped.rfind(". "))
        if last_break > char_budget * 0.6:
            clipped = clipped[:last_break].rstrip()

        if not clipped:
            return ""
        return clipped + "\n[truncated]"
