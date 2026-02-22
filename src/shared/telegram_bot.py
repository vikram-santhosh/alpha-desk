"""Telegram Bot — commands, scheduling, and message delivery for AlphaDesk.

Uses Telegram Bot API directly via requests (no third-party wrapper).
Supports commands: /brief, /refresh, /portfolio, /news, /trending, /cost, /status
Includes scheduling via the `schedule` library.
"""

import asyncio
import json
import os
import threading
import time
from datetime import datetime
from typing import Any

import requests
import schedule
from dotenv import load_dotenv

from src.shared.cost_tracker import format_cost_report
from src.shared.morning_brief import run as run_morning_brief
from src.shared.morning_brief import run_single_agent
from src.shared.security import authorize_chat
from src.utils.logger import get_logger

log = get_logger(__name__)

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

# Max Telegram message length
MAX_MSG_LEN = 4096


def send_message(chat_id: str, text: str, parse_mode: str = "HTML") -> bool:
    """Send a message via Telegram Bot API.

    Handles message splitting for long messages.

    Args:
        chat_id: Telegram chat ID.
        text: Message text (HTML formatted).
        parse_mode: Parse mode (default HTML).

    Returns:
        True if all message parts were sent successfully.
    """
    if not BOT_TOKEN:
        log.error("TELEGRAM_BOT_TOKEN not set")
        return False

    chunks = _split_message(text)
    success = True

    for chunk in chunks:
        try:
            resp = requests.post(
                f"{BASE_URL}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": chunk,
                    "parse_mode": parse_mode,
                    "disable_web_page_preview": True,
                },
                timeout=30,
            )
            if not resp.ok:
                log.error("Telegram API error: %s %s", resp.status_code, resp.text)
                # Retry without parse mode if HTML fails
                resp2 = requests.post(
                    f"{BASE_URL}/sendMessage",
                    json={
                        "chat_id": chat_id,
                        "text": chunk,
                        "disable_web_page_preview": True,
                    },
                    timeout=30,
                )
                if not resp2.ok:
                    log.error("Telegram retry failed: %s %s", resp2.status_code, resp2.text)
                    success = False
        except requests.RequestException as e:
            log.error("Failed to send message: %s", e)
            success = False

    return success


def _split_message(text: str) -> list[str]:
    """Split a message into chunks that fit Telegram's limit."""
    if len(text) <= MAX_MSG_LEN:
        return [text]

    chunks = []
    while text:
        if len(text) <= MAX_MSG_LEN:
            chunks.append(text)
            break

        # Find a good split point (newline near the limit)
        split_at = text.rfind("\n", 0, MAX_MSG_LEN)
        if split_at == -1:
            split_at = MAX_MSG_LEN

        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")

    return chunks


def get_updates(offset: int | None = None, timeout: int = 30) -> list[dict]:
    """Long-poll for updates from Telegram."""
    if not BOT_TOKEN:
        return []

    params: dict[str, Any] = {"timeout": timeout}
    if offset is not None:
        params["offset"] = offset

    try:
        resp = requests.get(f"{BASE_URL}/getUpdates", params=params, timeout=timeout + 10)
        if resp.ok:
            data = resp.json()
            return data.get("result", [])
    except requests.RequestException as e:
        log.error("Failed to get updates: %s", e)

    return []


async def handle_command(command: str, chat_id: str) -> None:
    """Handle a bot command."""
    log.info("Handling command: %s from chat %s", command, chat_id)

    if not authorize_chat(chat_id):
        send_message(chat_id, "Unauthorized.")
        return

    cmd = command.strip().lower().split()[0] if command.strip() else ""

    if cmd in ("/brief", "/start"):
        send_message(chat_id, "Running morning brief... this may take a few minutes.")
        result = await run_morning_brief()
        send_message(chat_id, result["formatted"])

    elif cmd == "/refresh":
        send_message(chat_id, "Refreshing all agents...")
        result = await run_morning_brief()
        send_message(chat_id, result["formatted"])

    elif cmd == "/portfolio":
        send_message(chat_id, "Fetching portfolio analysis...")
        result = await run_single_agent("portfolio")
        send_message(chat_id, result["formatted"])

    elif cmd == "/news":
        send_message(chat_id, "Fetching news...")
        result = await run_single_agent("news_desk")
        send_message(chat_id, result["formatted"])

    elif cmd == "/trending":
        send_message(chat_id, "Scanning Reddit...")
        result = await run_single_agent("street_ear")
        send_message(chat_id, result["formatted"])

    elif cmd == "/discover":
        send_message(chat_id, "Running Alpha Scout discovery... this may take a few minutes.")
        result = await run_single_agent("alpha_scout")
        send_message(chat_id, result["formatted"])

    elif cmd == "/cost":
        report = format_cost_report()
        send_message(chat_id, report)

    elif cmd == "/status":
        from src.shared.agent_bus import get_recent_signals
        signals = get_recent_signals(limit=10)
        status_lines = [
            f"<b>AlphaDesk Status</b>",
            f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Recent signals: {len(signals)}",
            "",
        ]
        for s in signals[:5]:
            status_lines.append(
                f"  [{s['signal_type']}] {s['source_agent']} — {s['timestamp'][:16]}"
            )
        send_message(chat_id, "\n".join(status_lines))

    elif cmd == "/help":
        help_text = (
            "<b>AlphaDesk Commands</b>\n\n"
            "/brief — Full morning briefing\n"
            "/refresh — Refresh all data\n"
            "/portfolio — Portfolio analysis only\n"
            "/news — Market news only\n"
            "/trending — Reddit intelligence only\n"
            "/discover — Ticker discovery &amp; recommendations\n"
            "/cost — API cost report\n"
            "/status — System status\n"
            "/help — This message"
        )
        send_message(chat_id, help_text)

    else:
        send_message(chat_id, f"Unknown command: {cmd}\nType /help for available commands.")


def _run_scheduled_brief() -> None:
    """Run the scheduled morning brief (called from scheduler thread)."""
    log.info("Running scheduled morning brief")
    try:
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(run_morning_brief())
        loop.close()
        if CHAT_ID:
            send_message(CHAT_ID, result["formatted"])
    except Exception as e:
        log.error("Scheduled brief failed: %s", e, exc_info=True)
        if CHAT_ID:
            send_message(CHAT_ID, f"<b>Scheduled brief failed</b>\n{e}")


def start_scheduler() -> threading.Thread:
    """Start the background scheduler for daily briefs.

    Schedules the morning brief at 7:00 AM daily.
    Returns the scheduler thread.
    """
    schedule.every().day.at("07:00").do(_run_scheduled_brief)
    log.info("Scheduler configured: daily brief at 07:00")

    def _scheduler_loop():
        while True:
            schedule.run_pending()
            time.sleep(60)

    thread = threading.Thread(target=_scheduler_loop, daemon=True)
    thread.start()
    return thread


def run_bot() -> None:
    """Main bot loop — polls for updates and handles commands."""
    log.info("Starting AlphaDesk Telegram bot")

    if not BOT_TOKEN:
        log.error("TELEGRAM_BOT_TOKEN not set — cannot start bot")
        return

    # Start scheduler
    start_scheduler()

    offset = None
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    log.info("Bot polling started. Waiting for commands...")

    while True:
        try:
            updates = get_updates(offset=offset)

            for update in updates:
                offset = update["update_id"] + 1
                message = update.get("message", {})
                text = message.get("text", "")
                chat_id = str(message.get("chat", {}).get("id", ""))

                if text.startswith("/"):
                    loop.run_until_complete(handle_command(text, chat_id))

        except KeyboardInterrupt:
            log.info("Bot stopped by user")
            break
        except Exception as e:
            log.error("Bot loop error: %s", e, exc_info=True)
            time.sleep(5)

    loop.close()


if __name__ == "__main__":
    run_bot()
