"""YouTube video fetcher for YouTube Ear.

Fetches recent finance video metadata via YouTube Data API v3 and transcripts
via youtube-transcript-api. Returns videos in a schema compatible with the
Reddit post format used downstream.
"""
from __future__ import annotations

import os
import time
from typing import Any

from src.shared.config_loader import load_config
from src.utils.logger import get_logger

log = get_logger(__name__)


def _get_api_key(config: dict[str, Any]) -> str | None:
    """Read YouTube API key from environment.

    Args:
        config: Loaded youtube_channels config dict.

    Returns:
        API key string, or None if not set.
    """
    settings = config.get("settings", {})
    env_var = settings.get("youtube_api_key_env", "YOUTUBE_API_KEY")
    key = os.getenv(env_var)
    if not key:
        log.warning(
            "YouTube API key not set (env var: %s). "
            "Set it to enable YouTube video fetching.",
            env_var,
        )
    return key


def _build_youtube_service(api_key: str):
    """Build YouTube Data API v3 service client.

    Args:
        api_key: YouTube Data API key.

    Returns:
        Google API discovery service resource, or None on import error.
    """
    try:
        from googleapiclient.discovery import build
    except ImportError:
        log.error(
            "google-api-python-client not installed. "
            "Run: pip install google-api-python-client"
        )
        return None

    return build("youtube", "v3", developerKey=api_key)


def _get_transcript(video_id: str, max_chars: int) -> str | None:
    """Fetch transcript text for a YouTube video.

    Args:
        video_id: YouTube video ID.
        max_chars: Maximum character count to return.

    Returns:
        Transcript text capped at max_chars, or None if unavailable.
    """
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        log.error(
            "youtube-transcript-api not installed. "
            "Run: pip install youtube-transcript-api"
        )
        return None

    try:
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
        text = " ".join(segment["text"] for segment in transcript_list)
        if len(text) > max_chars:
            text = text[:max_chars]
        return text
    except Exception as e:
        log.warning("Transcript unavailable for %s: %s", video_id, e)
        return None


def _parse_duration(duration_str: str) -> int:
    """Parse ISO 8601 duration string to seconds.

    Handles formats like PT1H2M3S, PT5M30S, PT45S.

    Args:
        duration_str: ISO 8601 duration (e.g., 'PT15M33S').

    Returns:
        Duration in seconds.
    """
    import re

    match = re.match(
        r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration_str or ""
    )
    if not match:
        return 0

    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    return hours * 3600 + minutes * 60 + seconds


def _fetch_channel_videos(
    youtube,
    channel_id: str,
    channel_name: str,
    max_videos: int,
    max_age_hours: int,
    min_view_count: int,
    max_transcript_chars: int,
) -> list[dict[str, Any]]:
    """Fetch recent videos from a single channel.

    Args:
        youtube: YouTube API service resource.
        channel_id: YouTube channel ID.
        channel_name: Display name for the channel.
        max_videos: Maximum videos to return per channel.
        max_age_hours: Skip videos older than this.
        min_view_count: Skip videos with fewer views.
        max_transcript_chars: Cap transcript text at this length.

    Returns:
        List of video dicts in the standard post schema.
    """
    cutoff_time = time.time() - (max_age_hours * 3600)

    # Search for recent videos on the channel
    try:
        search_response = youtube.search().list(
            channelId=channel_id,
            part="id,snippet",
            order="date",
            maxResults=max_videos * 2,  # fetch extra to account for filtering
            type="video",
        ).execute()
    except Exception as e:
        log.error("YouTube API search error for %s: %s", channel_name, e)
        return []

    video_ids = []
    snippet_map: dict[str, dict[str, Any]] = {}

    for item in search_response.get("items", []):
        video_id = item["id"].get("videoId")
        if not video_id:
            continue

        snippet = item.get("snippet", {})
        published_at = snippet.get("publishedAt", "")

        # Parse ISO 8601 timestamp
        try:
            from datetime import datetime, timezone

            dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
            created_utc = dt.timestamp()
        except (ValueError, AttributeError):
            created_utc = time.time()

        # Skip old videos
        if created_utc < cutoff_time:
            continue

        video_ids.append(video_id)
        snippet_map[video_id] = {
            "title": snippet.get("title", ""),
            "created_utc": created_utc,
        }

    if not video_ids:
        log.info("No recent videos found for %s", channel_name)
        return []

    # Fetch video statistics and content details
    try:
        videos_response = youtube.videos().list(
            id=",".join(video_ids),
            part="statistics,contentDetails",
        ).execute()
    except Exception as e:
        log.error("YouTube API videos.list error for %s: %s", channel_name, e)
        return []

    stats_map: dict[str, dict[str, Any]] = {}
    for item in videos_response.get("items", []):
        vid = item["id"]
        statistics = item.get("statistics", {})
        content_details = item.get("contentDetails", {})
        stats_map[vid] = {
            "view_count": int(statistics.get("viewCount", 0)),
            "comment_count": int(statistics.get("commentCount", 0)),
            "duration_seconds": _parse_duration(
                content_details.get("duration", "")
            ),
        }

    # Build final video list with transcripts
    videos: list[dict[str, Any]] = []
    for video_id in video_ids:
        if len(videos) >= max_videos:
            break

        stats = stats_map.get(video_id, {})
        view_count = stats.get("view_count", 0)

        # Skip low-view videos
        if view_count < min_view_count:
            log.debug(
                "Skipping %s (views=%d < min=%d)",
                video_id, view_count, min_view_count,
            )
            continue

        snippet_data = snippet_map.get(video_id, {})

        # Fetch transcript
        transcript = _get_transcript(video_id, max_transcript_chars)
        if transcript is None:
            log.info("Skipping %s — no transcript available", video_id)
            continue

        video = {
            "title": snippet_data.get("title", ""),
            "selftext": transcript,
            "score": view_count,
            "num_comments": stats.get("comment_count", 0),
            "subreddit": channel_name,
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "created_utc": snippet_data.get("created_utc", time.time()),
            "author": channel_name,
            "source_platform": "youtube",
            "duration_seconds": stats.get("duration_seconds", 0),
        }
        videos.append(video)

    log.info(
        "Fetched %d videos from %s (channel_id=%s)",
        len(videos), channel_name, channel_id,
    )
    return videos


def fetch_videos() -> list[dict[str, Any]]:
    """Fetch recent finance videos from all configured YouTube channels.

    Loads channel config from config/youtube_channels.yaml, fetches metadata
    via YouTube Data API v3, retrieves transcripts, and returns videos in
    the standard post schema.

    Returns:
        List of video dicts matching the Reddit post schema:
        - title, selftext (transcript), score (views), num_comments,
          subreddit (channel name), url, created_utc, author,
          source_platform, duration_seconds
    """
    config = load_config("youtube_channels")
    channels_config = config.get("channels", {})
    settings = config.get("settings", {})

    max_age_hours = settings.get("max_video_age_hours", 48)
    max_transcript_chars = settings.get("max_transcript_chars", 6000)
    max_videos_per_channel = settings.get("max_videos_per_channel", 3)
    min_view_count = settings.get("min_view_count", 1000)

    # Check API key
    api_key = _get_api_key(config)
    if not api_key:
        log.warning("No YouTube API key — returning empty video list")
        return []

    # Build API client
    youtube = _build_youtube_service(api_key)
    if youtube is None:
        return []

    # Flatten all channel categories
    all_channels: list[dict[str, str]] = []
    for _category, channels in channels_config.items():
        if isinstance(channels, list):
            all_channels.extend(channels)

    log.info("Fetching videos from %d channels", len(all_channels))

    all_videos: list[dict[str, Any]] = []
    for channel in all_channels:
        name = channel.get("name", "Unknown")
        channel_id = channel.get("channel_id", "")
        if not channel_id:
            log.warning("Skipping channel with no channel_id: %s", name)
            continue

        videos = _fetch_channel_videos(
            youtube=youtube,
            channel_id=channel_id,
            channel_name=name,
            max_videos=max_videos_per_channel,
            max_age_hours=max_age_hours,
            min_view_count=min_view_count,
            max_transcript_chars=max_transcript_chars,
        )
        all_videos.extend(videos)

    log.info("Total videos fetched: %d", len(all_videos))
    return all_videos
