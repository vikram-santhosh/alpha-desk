#!/bin/bash
# AlphaDesk Telegram Bot launcher
# Runs the bot which:
#   1. Polls for Telegram commands (/advisor, /holdings, /macro, etc.)
#   2. Sends the full advisor brief daily at 7:00 AM

cd /Users/Sakshi.Agarwal/alphadesk

# Source environment
set -a
source .env 2>/dev/null
set +a

PYTHON="/Users/Sakshi.Agarwal/sdmain/polaris/.buildenv/bin/python"
exec "$PYTHON" -m src.shared.telegram_bot
