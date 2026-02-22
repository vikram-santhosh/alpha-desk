"""Data retention enforcement — cleans up old runtime data."""

from pathlib import Path

from src.shared.agent_bus import clear_old_signals
from src.utils.logger import get_logger

log = get_logger(__name__)

DATA_DIR = Path("data")


def cleanup_logs(max_size_mb: int = 50) -> None:
    """Truncate log files if they exceed the size limit."""
    log_file = DATA_DIR / "alphadesk.log"
    if log_file.exists() and log_file.stat().st_size > max_size_mb * 1024 * 1024:
        # Keep the last 10000 lines
        lines = log_file.read_text().splitlines()
        log_file.write_text("\n".join(lines[-10000:]) + "\n")
        log.info("Truncated log file to last 10000 lines")


def run_cleanup() -> None:
    """Run all cleanup tasks."""
    log.info("Starting cleanup...")
    clear_old_signals(days=7)
    cleanup_logs()
    log.info("Cleanup complete")


if __name__ == "__main__":
    run_cleanup()
