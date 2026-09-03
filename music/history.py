"""Playback history management."""

import json
from datetime import datetime
from typing import Any, Dict, List

from music.config import HISTORY_FILE, ensure_config_dir
from music.search import SongItem


def get_history(limit: int = 20) -> List[SongItem]:
    """Retrieve playback history."""
    if not HISTORY_FILE.exists():
        return []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        items: List[SongItem] = []
        for d in data[:limit]:
            items.append(
                SongItem(
                    title=d.get("title", "Unknown"),
                    artist=d.get("artist", "Unknown"),
                    album=d.get("album", ""),
                    duration=d.get("duration", "00:00"),
                    duration_seconds=d.get("duration_seconds", 0),
                    video_id=d.get("video_id", ""),
                    url=d.get("url", ""),
                    thumbnail=d.get("thumbnail", ""),
                )
            )
        return items
    except Exception:
        return []


def add_to_history(song: SongItem) -> None:
    """Add a played song to history, deduplicating and keeping the most recent."""
    ensure_config_dir()
    entries: List[Dict[str, Any]] = []
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                entries = json.load(f)
        except Exception:
            entries = []

    # Remove existing instance of the same video_id
    entries = [e for e in entries if e.get("video_id") != song.video_id]

    entry = song.to_dict()
    entry["played_at"] = datetime.now().isoformat()
    entries.insert(0, entry)

    # Keep maximum 50 entries
    entries = entries[:50]

    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2)
    except Exception:
        pass


def clear_history() -> None:
    """Clear playback history."""
    if HISTORY_FILE.exists():
        try:
            HISTORY_FILE.unlink()
        except OSError:
            pass
