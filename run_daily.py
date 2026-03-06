"""Entry point for Cloud Run Job — runs the daily advisor pipeline.

GCS FUSE + SQLite is slow (random writes hit rate limits), so we:
  1. Copy DBs from /app/data (GCS mount) → /tmp/data (local SSD)
  2. Run the pipeline against /tmp/data
  3. Copy updated DBs back to /app/data (GCS)
"""

import asyncio
import glob
import os
import shutil
import sys

from src.utils.logger import get_logger

log = get_logger(__name__)

GCS_DATA = "/app/data"
LOCAL_DATA = "/tmp/data"


def _sync_down():
    """Copy DBs from GCS mount to local disk."""
    os.makedirs(LOCAL_DATA, exist_ok=True)
    if not os.path.isdir(GCS_DATA):
        log.info("No GCS data dir found — starting fresh")
        return
    for f in glob.glob(os.path.join(GCS_DATA, "*.db")):
        dst = os.path.join(LOCAL_DATA, os.path.basename(f))
        shutil.copy2(f, dst)
        log.info("Synced down: %s (%.1f KB)", os.path.basename(f), os.path.getsize(f) / 1024)


def _sync_up():
    """Copy updated DBs back to GCS mount."""
    if not os.path.isdir(GCS_DATA):
        log.warning("GCS data dir missing — skipping sync-up")
        return
    for f in glob.glob(os.path.join(LOCAL_DATA, "*.db")):
        dst = os.path.join(GCS_DATA, os.path.basename(f))
        shutil.copy2(f, dst)
        log.info("Synced up: %s (%.1f KB)", os.path.basename(f), os.path.getsize(f) / 1024)


def main():
    log.info("Starting AlphaDesk daily run")

    # Use local disk for SQLite during the run
    _sync_down()
    os.environ.setdefault("ALPHADESK_DATA_DIR", LOCAL_DATA)

    try:
        from src.advisor.main import run
        result = asyncio.run(run())

        stats = result.get("stats", {})
        log.info(
            "Daily run complete — %.1fs, $%.2f, %d holdings, %d signals",
            stats.get("total_time_s", 0),
            stats.get("daily_cost", 0),
            stats.get("holdings_count", 0),
            stats.get("actions_count", 0),
        )
    except Exception:
        log.exception("Daily run failed")
        _sync_up()  # Still save progress on failure
        sys.exit(1)

    _sync_up()
    log.info("Data synced to GCS — done")


if __name__ == "__main__":
    main()
