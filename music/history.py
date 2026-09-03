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

    # Keep maximum 500 entries for rich offline caching and search
    entries = entries[:500]

    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2)
    except Exception:
        pass


def search_history(query: str, limit: int = 5) -> List[SongItem]:
    """Search previously played tracks locally without internet connection (0ms latency)."""
    clean = query.strip().lower()
    if not clean:
        return get_history(limit=limit)

    all_songs = get_history(limit=500)
    scored_matches: List[tuple] = []

    for s in all_songs:
        t_low = s.title.lower()
        a_low = s.artist.lower()
        alb_low = s.album.lower() if s.album else ""

        score = 0
        if t_low.startswith(clean):
            score += 25
        elif f" {clean}" in t_low or f"({clean}" in t_low or f"[{clean}" in t_low:
            score += 18
        elif clean in t_low:
            score += 10

        if a_low.startswith(clean):
            score += 15
        elif f" {clean}" in a_low:
            score += 12
        elif clean in a_low:
            score += 8

        if clean in alb_low:
            score += 5

        if score > 0:
            scored_matches.append((score, s))

    scored_matches.sort(key=lambda x: x[0], reverse=True)
    return [item[1] for item in scored_matches[:limit]]


def clear_history() -> None:
    """Clear playback history."""
    if HISTORY_FILE.exists():
        try:
            HISTORY_FILE.unlink()
        except OSError:
            pass
