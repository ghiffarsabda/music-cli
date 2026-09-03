"""Playback history management (delegating to music.library SQLite engine).

Maintains 100% backward-compatible function signatures and re-exports with zero
external dependencies.
"""

from pathlib import Path
from typing import List

from music.config import HISTORY_FILE
from music.library import (
    add_track_to_library,
    clear_library,
    get_recent_tracks,
    search_local_library,
)
from music.search import SongItem

__all__ = [
    "get_history",
    "add_to_history",
    "search_history",
    "clear_history",
    "HISTORY_FILE",
    "SongItem",
]


def get_history(limit: int = 20) -> List[SongItem]:
    """Retrieve playback history ordered by recency.

    Delegates to music.library.get_recent_tracks.
    """
    return get_recent_tracks(limit=limit)


def add_to_history(song: SongItem) -> None:
    """Add a played song to history, deduplicating and updating playback timestamp.

    Delegates to music.library.add_track_to_library.
    """
    add_track_to_library(song)


def search_history(query: str, limit: int = 5) -> List[SongItem]:
    """Search previously played tracks locally without internet connection (< 1ms latency).

    Delegates to music.library.search_local_library (FTS5 BM25 with fuzzy fallback).
    """
    return search_local_library(query=query, limit=limit)


def clear_history() -> None:
    """Clear playback history from both SQLite library database and legacy JSON file."""
    clear_library()
    if HISTORY_FILE.exists():
        try:
            HISTORY_FILE.unlink()
        except OSError:
            pass
