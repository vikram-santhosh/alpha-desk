"""Markdown-to-Telegram-HTML converter for AlphaDesk.

Converts common markdown artifacts from LLM-generated prose into
Telegram-safe HTML tags before inserting into formatted output.
"""
from __future__ import annotations

import re


def md_to_telegram_html(text: str) -> str:
    """Convert markdown formatting to Telegram-compatible HTML.

    Handles:
      **bold**  →  <b>bold</b>
      *italic*  →  <i>italic</i>
      `code`    →  <code>code</code>
      ## Header →  <b>Header</b>
      - item    →  • item
      Fixes missing spaces between percentages and text.
    """
    if not text:
        return text

    # Strip markdown headers (## Header → bold)
    text = re.sub(r"^#{1,6}\s+(.+)$", r"<b>\1</b>", text, flags=re.MULTILINE)

    # Bold: **text** → <b>text</b>
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)

    # Italic: *text* → <i>text</i> (but not inside bold tags)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", text)

    # Inline code: `text` → <code>text</code>
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)

    # Bullet lists: "- item" → "• item"
    text = re.sub(r"^- ", "• ", text, flags=re.MULTILINE)

    # Fix missing space between percentage and following word
    # e.g., "5.2%driven" → "5.2% driven"
    text = re.sub(r"(\d+\.?\d*%)([A-Za-z])", r"\1 \2", text)

    # Fix missing space after closing parens before word
    text = re.sub(r"\)([A-Za-z])", r") \1", text)

    return text
