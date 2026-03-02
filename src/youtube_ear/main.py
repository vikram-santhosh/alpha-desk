"""YouTube Ear — finance video intelligence pipeline orchestrator.

Runs the full pipeline: fetch videos from YouTube, analyze transcripts with
Gemini, track mentions and theses, detect view spikes and convergence,
publish signals to the agent bus, and format output for Telegram delivery.
"""

import asyncio
import time
from typing import Any

from src.utils.logger import get_logger

log = get_logger(__name__)

AGENT_NAME = "youtube_ear"


async def run() -> dict[str, Any]:
    """Orchestrate the full YouTube Ear pipeline.

    Steps:
        1. Fetch videos from all configured YouTube channels
        2. Analyze transcripts with Gemini
        3. Track mentions and theses
        4. Publish signals to agent bus
        5. Format output for Telegram

    Returns:
        Dict with keys:
        - formatted: HTML-formatted string for Telegram
        - signals: list of signal dicts published to agent bus
        - stats: dict with pipeline statistics
        - analysis: summary of analysis results
    """
    pipeline_start = time.monotonic()
    stats: dict[str, Any] = {}
    signals: list[dict[str, Any]] = []
    videos: list[dict[str, Any]] = []
    analysis: dict[str, Any] = {
        "tickers": {},
        "theses": [],
        "macro_signals": [],
        "themes": [],
        "market_mood": "unknown",
    }
    view_spikes: list[dict[str, Any]] = []
    convergences: list[dict[str, Any]] = []

    # Step 1: Fetch videos from YouTube
    log.info("Step 1/5: Fetching YouTube videos")
    step_start = time.monotonic()
    try:
        from src.youtube_ear.youtube_fetcher import fetch_videos
        videos = await asyncio.to_thread(fetch_videos)
        stats["videos_fetched"] = len(videos)
        stats["fetch_time_s"] = round(time.monotonic() - step_start, 1)
        log.info("Fetched %d videos in %.1fs", len(videos), stats["fetch_time_s"])
    except Exception as e:
        log.error("Failed to fetch videos: %s", e, exc_info=True)
        stats["videos_fetched"] = 0
        stats["fetch_error"] = str(e)

    # Step 2: Analyze transcripts with Gemini
    log.info("Step 2/5: Analyzing transcripts with Gemini")
    step_start = time.monotonic()
    try:
        if videos:
            from src.youtube_ear.analyzer import analyze_videos
            analysis = await asyncio.to_thread(analyze_videos, videos)
            stats["tickers_found"] = len(analysis.get("tickers", {}))
            stats["theses_found"] = len(analysis.get("theses", []))
            stats["themes_found"] = len(analysis.get("themes", []))
        else:
            log.warning("No videos to analyze — skipping")
            stats["tickers_found"] = 0
            stats["theses_found"] = 0
            stats["themes_found"] = 0
        stats["analysis_time_s"] = round(time.monotonic() - step_start, 1)
        log.info(
            "Analysis complete in %.1fs: %d tickers, %d theses, %d themes",
            stats["analysis_time_s"],
            stats.get("tickers_found", 0),
            stats.get("theses_found", 0),
            stats.get("themes_found", 0),
        )
    except Exception as e:
        log.error("Failed to analyze videos: %s", e, exc_info=True)
        stats["tickers_found"] = 0
        stats["analysis_error"] = str(e)

    # Step 3: Track mentions, theses, and detect anomalies
    log.info("Step 3/5: Tracking mentions and detecting anomalies")
    step_start = time.monotonic()
    try:
        from src.youtube_ear.tracker import (
            detect_multi_channel_convergence,
            detect_view_spikes,
            record_scan,
            record_theses,
        )

        # Record this scan's data
        record_scan(analysis)
        record_theses(analysis)

        # Detect anomalies
        view_spikes = detect_view_spikes(analysis, videos)
        convergences = detect_multi_channel_convergence(analysis)

        stats["view_spikes"] = len(view_spikes)
        stats["convergences"] = len(convergences)
        stats["tracking_time_s"] = round(time.monotonic() - step_start, 1)

        log.info(
            "Tracking complete in %.1fs: %d view spikes, %d convergences",
            stats["tracking_time_s"],
            len(view_spikes), len(convergences),
        )
    except Exception as e:
        log.error("Failed in tracking step: %s", e, exc_info=True)
        stats["tracking_error"] = str(e)

    # Step 4: Publish signals to agent bus
    log.info("Step 4/5: Publishing signals to agent bus")
    step_start = time.monotonic()
    try:
        from src.youtube_ear.tracker import publish_signals

        thesis_signals = publish_signals(analysis)

        # Collect all signals for the return value
        for spike in view_spikes:
            signals.append({"type": "narrative_amplification", **spike})
        for c in convergences:
            signals.append({"type": "expert_analysis", **c})
        for t in thesis_signals:
            signals.append({"type": "expert_analysis", **t})

        stats["signals_published"] = len(signals)
        stats["signal_time_s"] = round(time.monotonic() - step_start, 1)
        log.info("Published %d signals in %.1fs", len(signals), stats["signal_time_s"])
    except Exception as e:
        log.error("Failed to publish signals: %s", e, exc_info=True)
        stats["signal_error"] = str(e)

    # Step 5: Format output for Telegram
    log.info("Step 5/5: Formatting output")
    step_start = time.monotonic()
    formatted = ""
    try:
        from src.youtube_ear.formatter import format_output

        formatted = format_output(
            analysis=analysis,
            view_spikes=view_spikes,
            convergences=convergences,
            videos=videos,
        )
        stats["output_chars"] = len(formatted)
        stats["format_time_s"] = round(time.monotonic() - step_start, 1)
        log.info("Formatted output: %d chars in %.1fs", len(formatted), stats["format_time_s"])
    except Exception as e:
        log.error("Failed to format output: %s", e, exc_info=True)
        formatted = "\U0001f3ac <b>YouTube Ear</b>\n<i>Error formatting output</i>"
        stats["format_error"] = str(e)

    # Summary
    total_time = round(time.monotonic() - pipeline_start, 1)
    stats["total_time_s"] = total_time
    log.info(
        "YouTube Ear pipeline complete in %.1fs — %d videos, %d tickers, %d signals",
        total_time,
        stats.get("videos_fetched", 0),
        stats.get("tickers_found", 0),
        stats.get("signals_published", 0),
    )

    return {
        "formatted": formatted,
        "signals": signals,
        "stats": stats,
        "analysis": {
            "market_mood": analysis.get("market_mood", "unknown"),
            "tickers_found": len(analysis.get("tickers", {})),
            "themes": analysis.get("themes", []),
            "theses_count": len(analysis.get("theses", [])),
            "macro_signals_count": len(analysis.get("macro_signals", [])),
        },
    }
