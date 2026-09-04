"""Offline Mode and Local Download Engine for music-cli.

Provides complete offline music capabilities:
- Download individual songs, full playlists, and full albums to local disk.
- Fast, metadata-tagged audio extraction via yt-dlp (with MP3/M4A/native fallback).
- Automatic offline time-synchronized lyrics (.lrc) downloading and storage.
- Local SQLite catalog of downloaded tracks, playlists, and albums.
- Instant, zero-latency, 100% offline playback with zero internet connection required.
"""

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from rich import box
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
)
from rich.table import Table

from music.config import (
    CONFIG_DIR,
    LIBRARY_DB,
    get_config_val,
    get_ytdl_cmd_prefix,
    set_config_val,
)
from music.library import get_db, get_db_connection, init_library_db
from music.lyrics import fetch_lyrics, parse_lrc
from music.search import (
    AlbumItem,
    PlaylistItem,
    SongItem,
    extract_album_id,
    extract_playlist_id,
    format_duration,
    get_album_tracks,
    get_playlist_tracks,
    is_album_url,
    is_playlist_url,
    is_youtube_url,
    resolve_direct_item,
    search_albums,
    search_music,
    search_playlists,
)

DEFAULT_DOWNLOADS_DIR = Path.home() / ".local" / "share" / "music-cli" / "downloads"

OFFLINE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS offline_tracks (
    video_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    artist TEXT NOT NULL,
    album TEXT NOT NULL DEFAULT '',
    duration TEXT NOT NULL DEFAULT '00:00',
    duration_seconds INTEGER NOT NULL DEFAULT 0,
    url TEXT NOT NULL DEFAULT '',
    thumbnail TEXT NOT NULL DEFAULT '',
    file_path TEXT NOT NULL,
    file_size INTEGER DEFAULT 0,
    audio_format TEXT NOT NULL DEFAULT 'mp3',
    downloaded_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_offline_tracks_downloaded_at ON offline_tracks(downloaded_at DESC);

CREATE TABLE IF NOT EXISTS offline_collections (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    author TEXT NOT NULL DEFAULT '',
    track_count INTEGER NOT NULL DEFAULT 0,
    track_ids TEXT NOT NULL,
    thumbnail TEXT NOT NULL DEFAULT '',
    downloaded_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_offline_collections_type ON offline_collections(type);
"""


def get_downloads_dir() -> Path:
    """Return root directory where offline songs and collections are stored."""
    cfg_dir = get_config_val("download_dir", "")
    if cfg_dir:
        p = Path(cfg_dir).expanduser()
    else:
        p = DEFAULT_DOWNLOADS_DIR
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_tracks_dir() -> Path:
    """Return directory for offline audio files."""
    p = get_downloads_dir() / "tracks"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_lyrics_dir() -> Path:
    """Return directory for offline .lrc lyrics files."""
    p = get_downloads_dir() / "lyrics"
    p.mkdir(parents=True, exist_ok=True)
    return p


def sanitize_filename(name: str, max_len: int = 100) -> str:
    """Sanitize string for cross-platform safe filesystem filenames."""
    # Remove control characters and illegal filename symbols
    cleaned = re.sub(r'[\\/*?:"<>|\x00-\x1f]', "", name)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(". ")
    if not cleaned:
        cleaned = "track"
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].rstrip(". ")
    return cleaned


def format_bytes(size_bytes: int | float) -> str:
    """Format byte size into human readable string (KB, MB, GB)."""
    if size_bytes <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    size = float(size_bytes)
    while size >= 1024.0 and i < len(units) - 1:
        size /= 1024.0
        i += 1
    return f"{size:.1f} {units[i]}"


def reconcile_offline_tracks_from_disk(conn: Optional[Any] = None) -> int:
    """Scan downloads/tracks folder and automatically register missing tracks and albums.

    Guarantees that previously downloaded audio files are never lost even if the
    SQLite database was reinitialized, wiped, or moved across machines.
    """
    tracks_dir = get_tracks_dir()
    if not tracks_dir.exists():
        return 0

    def _do_sync(c: Any) -> int:
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        try:
            existing_rows = c.execute("SELECT video_id, file_path FROM offline_tracks").fetchall()
            existing_vids = {r["video_id"] for r in existing_rows}
        except Exception:
            return 0

        # Clean up entries whose files were deleted from disk
        for r in existing_rows:
            f_path = r["file_path"]
            if not os.path.exists(f_path) or os.path.getsize(f_path) == 0:
                c.execute("DELETE FROM offline_tracks WHERE video_id = ?", (r["video_id"],))
                existing_vids.discard(r["video_id"])

        synced_count = 0
        albums_map: Dict[Tuple[str, str], Dict[str, Any]] = {}

        for cand in tracks_dir.glob("*"):
            if not cand.is_file() or cand.stat().st_size == 0:
                continue
            if cand.suffix.lower() not in (".mp3", ".m4a", ".opus", ".webm", ".ogg", ".wav", ".flac"):
                continue
            if cand.name.endswith((".part", ".ytdl", ".temp")):
                continue

            m = re.search(r"\[([a-zA-Z0-9_-]{11})\]", cand.name)
            if not m:
                continue
            vid = m.group(1)

            base = cand.stem.rsplit(" [", 1)[0]
            if " - " in base:
                artist, title = base.split(" - ", 1)
            else:
                artist = "Unknown Artist"
                title = base

            album = ""
            dur_sec = 0
            try:
                from mutagen.easyid3 import EasyID3
                tags = EasyID3(cand)
                if "title" in tags and tags["title"]:
                    title = tags["title"][0]
                if "artist" in tags and tags["artist"]:
                    artist = tags["artist"][0]
                if "album" in tags and tags["album"]:
                    album = tags["album"][0]
            except Exception:
                pass

            try:
                from mutagen.mp3 import MP3
                mp3 = MP3(cand)
                dur_sec = int(mp3.info.length)
            except Exception:
                pass

            dur_str = format_duration(dur_sec) if dur_sec > 0 else "--:--"
            file_size = cand.stat().st_size
            audio_fmt = cand.suffix.lstrip(".").lower() or "mp3"

            if album:
                key = (album.strip().lower(), artist.strip().lower())
                if key not in albums_map:
                    albums_map[key] = {
                        "title": album.strip(),
                        "author": artist.strip(),
                        "track_ids": [],
                    }
                albums_map[key]["track_ids"].append(vid)

            if vid not in existing_vids:
                c.execute(
                    """
                    INSERT OR REPLACE INTO offline_tracks (
                        video_id, title, artist, album, duration, duration_seconds,
                        url, thumbnail, file_path, file_size, audio_format, downloaded_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        vid,
                        title,
                        artist,
                        album,
                        dur_str,
                        dur_sec,
                        f"https://www.youtube.com/watch?v={vid}",
                        "",
                        str(cand.resolve()),
                        file_size,
                        audio_fmt,
                        now_iso,
                    ),
                )
                existing_vids.add(vid)
                synced_count += 1

        # Reconcile albums
        for (alb_low, art_low), a_info in albums_map.items():
            col_id = f"offline_album_{alb_low.replace(' ', '_')}"
            row = c.execute(
                "SELECT id, track_ids FROM offline_collections WHERE id = ? OR LOWER(title) = ?",
                (col_id, alb_low),
            ).fetchone()
            if not row:
                c.execute(
                    """
                    INSERT OR REPLACE INTO offline_collections (
                        id, type, title, author, track_count, track_ids, thumbnail, downloaded_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        col_id,
                        "album",
                        a_info["title"],
                        a_info["author"],
                        len(a_info["track_ids"]),
                        json.dumps(a_info["track_ids"]),
                        "",
                        now_iso,
                    ),
                )
            else:
                try:
                    cur_tids = json.loads(row["track_ids"])
                except Exception:
                    cur_tids = []
                merged = list(dict.fromkeys(cur_tids + a_info["track_ids"]))
                if len(merged) != len(cur_tids):
                    c.execute(
                        "UPDATE offline_collections SET track_count = ?, track_ids = ? WHERE id = ?",
                        (len(merged), json.dumps(merged), row["id"]),
                    )

        c.commit()
        return synced_count

    if conn is not None:
        return _do_sync(conn)
    with get_db() as c:
        return _do_sync(c)


def init_offline_db(conn: Optional[Any] = None) -> None:
    """Ensure offline tables, library tables, and indices are created in library database."""
    if conn is not None:
        init_library_db(conn)
        conn.executescript(OFFLINE_SCHEMA_SQL)
        reconcile_offline_tracks_from_disk(conn)
        return

    with get_db() as c:
        init_library_db(c)
        c.executescript(OFFLINE_SCHEMA_SQL)
        reconcile_offline_tracks_from_disk(c)


def is_track_offline(video_id: str) -> bool:
    """Check if a track is downloaded and exists on local disk."""
    if not video_id:
        return False

    path = get_offline_track_path(video_id)
    return bool(path and os.path.exists(path) and os.path.getsize(path) > 0)


def get_offline_track_path(video_id: str) -> Optional[str]:
    """Return local audio file path for video_id if available."""
    if not video_id:
        return None

    init_offline_db()
    try:
        with get_db() as conn:
            cursor = conn.execute(
                "SELECT file_path FROM offline_tracks WHERE video_id = ?", (video_id,)
            )
            row = cursor.fetchone()
            if row and row["file_path"]:
                fpath = row["file_path"]
                if os.path.exists(fpath) and os.path.getsize(fpath) > 0:
                    return fpath
                else:
                    # Clean up missing file entry
                    conn.execute("DELETE FROM offline_tracks WHERE video_id = ?", (video_id,))
                    conn.commit()
    except Exception:
        pass

    # Disk scan fallback (e.g. if DB was reinitialized or moved)
    tracks_dir = get_tracks_dir()
    for cand in tracks_dir.glob(f"*{video_id}*"):
        if cand.is_file() and cand.stat().st_size > 0 and not cand.name.endswith((".part", ".ytdl")):
            return str(cand.resolve())

    return None


def get_offline_lyrics_path(video_id: str) -> Optional[str]:
    """Return local .lrc lyrics file path for video_id if available."""
    if not video_id:
        return None
    lrc_file = get_lyrics_dir() / f"{video_id}.lrc"
    if lrc_file.exists() and lrc_file.stat().st_size > 0:
        return str(lrc_file.resolve())
    return None


def get_offline_track(video_id: str) -> Optional[SongItem]:
    """Retrieve SongItem metadata for an offline track."""
    if not video_id:
        return None

    init_offline_db()
    try:
        with get_db() as conn:
            row = conn.execute(
                "SELECT * FROM offline_tracks WHERE video_id = ?", (video_id,)
            ).fetchone()
            if row:
                fpath = row["file_path"]
                if os.path.exists(fpath) and os.path.getsize(fpath) > 0:
                    return SongItem(
                        title=row["title"],
                        artist=row["artist"],
                        album=row["album"],
                        duration=row["duration"],
                        duration_seconds=row["duration_seconds"],
                        video_id=row["video_id"],
                        url=row["url"],
                        thumbnail=row["thumbnail"],
                    )
    except Exception:
        pass
    return None


def save_offline_track(
    song: SongItem,
    file_path: str,
    file_size: int,
    audio_format: str = "mp3",
) -> None:
    """Save or update offline track record in database."""
    init_offline_db()
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with get_db() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO offline_tracks (
                video_id, title, artist, album, duration, duration_seconds,
                url, thumbnail, file_path, file_size, audio_format, downloaded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                song.video_id,
                song.title,
                song.artist,
                song.album or "",
                song.duration or "00:00",
                int(song.duration_seconds or 0),
                song.url or f"https://www.youtube.com/watch?v={song.video_id}",
                song.thumbnail or "",
                str(Path(file_path).resolve()),
                int(file_size),
                audio_format,
                now_iso,
            ),
        )
        # Also ensure it is present in tracks and tracks_fts for instant local search
        conn.execute(
            """
            INSERT INTO tracks (
                video_id, title, artist, album, duration, duration_seconds,
                url, thumbnail, played_at, play_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(video_id) DO UPDATE SET
                title=excluded.title,
                artist=excluded.artist,
                album=excluded.album
            """,
            (
                song.video_id,
                song.title,
                song.artist,
                song.album or "",
                song.duration or "00:00",
                int(song.duration_seconds or 0),
                song.url or f"https://www.youtube.com/watch?v={song.video_id}",
                song.thumbnail or "",
                now_iso,
            ),
        )
        conn.commit()


def save_offline_collection(
    collection_id: str,
    collection_type: str,
    title: str,
    author: str = "",
    track_ids: Optional[List[str]] = None,
    thumbnail: str = "",
    **kwargs: Any,
) -> None:
    """Save or update offline playlist or album collection record."""
    init_offline_db()
    if not author and "artist" in kwargs:
        author = str(kwargs["artist"])
    if track_ids is None:
        track_ids = kwargs.get("tracks") or []
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with get_db() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO offline_collections (
                id, type, title, author, track_count, track_ids, thumbnail, downloaded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                collection_id,
                collection_type.lower(),
                title,
                author,
                len(track_ids),
                json.dumps(track_ids),
                thumbnail,
                now_iso,
            ),
        )
        conn.commit()


def list_offline_tracks(query: Optional[str] = None) -> List[SongItem]:
    """List all downloaded tracks, optionally filtered by search query with multi-term token matching."""
    init_offline_db()
    items: List[SongItem] = []
    try:
        with get_db() as conn:
            if query and query.strip():
                tokens = [t.strip().lower() for t in query.strip().split() if t.strip()]
                conditions = []
                params = []
                for tok in tokens:
                    conditions.append("LOWER(title || ' ' || artist || ' ' || album) LIKE ?")
                    params.append(f"%{tok}%")
                where_clause = " AND ".join(conditions)
                rows = conn.execute(
                    f"SELECT * FROM offline_tracks WHERE {where_clause} ORDER BY downloaded_at DESC",
                    params,
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM offline_tracks ORDER BY downloaded_at DESC"
                ).fetchall()

            for r in rows:
                fpath = r["file_path"]
                if os.path.exists(fpath) and os.path.getsize(fpath) > 0:
                    items.append(
                        SongItem(
                            title=r["title"],
                            artist=r["artist"],
                            album=r["album"],
                            duration=r["duration"],
                            duration_seconds=r["duration_seconds"],
                            video_id=r["video_id"],
                            url=r["url"],
                            thumbnail=r["thumbnail"],
                        )
                    )
    except Exception:
        pass
    return items


def list_offline_collections(
    collection_type: Optional[str] = None,
    query: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """List all offline playlists or albums, optionally filtered by search query."""
    init_offline_db()
    collections: List[Dict[str, Any]] = []
    try:
        with get_db() as conn:
            if collection_type:
                rows = conn.execute(
                    "SELECT * FROM offline_collections WHERE LOWER(type) = ? ORDER BY downloaded_at DESC",
                    (collection_type.lower(),),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM offline_collections ORDER BY downloaded_at DESC"
                ).fetchall()

            q_tokens = [t.strip().lower() for t in query.strip().split() if t.strip()] if query else []

            for r in rows:
                if q_tokens:
                    haystack = f"{r['title']} {r['author']}".lower()
                    if not all(tok in haystack for tok in q_tokens):
                        continue

                try:
                    t_ids = json.loads(r["track_ids"])
                except Exception:
                    t_ids = []
                collections.append({
                    "id": r["id"],
                    "type": r["type"],
                    "title": r["title"],
                    "author": r["author"],
                    "track_count": r["track_count"],
                    "track_ids": t_ids,
                    "thumbnail": r["thumbnail"],
                    "downloaded_at": r["downloaded_at"],
                })
    except Exception:
        pass
    return collections


def get_offline_collection(collection_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve collection details by ID or title match."""
    init_offline_db()
    clean_id = collection_id.strip()
    try:
        with get_db() as conn:
            row = conn.execute(
                """
                SELECT * FROM offline_collections
                WHERE id = ? OR LOWER(title) = ? OR id = ? OR LOWER(id) LIKE ?
                LIMIT 1
                """,
                (clean_id, clean_id.lower(), f"offline_album_{clean_id.lower().replace(' ', '_')}", f"%{clean_id.lower()}%"),
            ).fetchone()
            if row:
                try:
                    t_ids = json.loads(row["track_ids"])
                except Exception:
                    t_ids = []
                return {
                    "id": row["id"],
                    "type": row["type"],
                    "title": row["title"],
                    "author": row["author"],
                    "track_count": row["track_count"],
                    "track_ids": t_ids,
                    "thumbnail": row["thumbnail"],
                    "downloaded_at": row["downloaded_at"],
                }
    except Exception:
        pass
    return None


def get_offline_collection_tracks(collection_id: str) -> Tuple[Optional[Dict[str, Any]], List[SongItem]]:
    """Retrieve an offline collection and all its downloaded tracks."""
    col = get_offline_collection(collection_id)
    if not col:
        return None, []

    tracks: List[SongItem] = []
    for vid in col.get("track_ids", []):
        t = get_offline_track(vid)
        if t:
            tracks.append(t)
    return col, tracks


def delete_offline_track(video_id: str) -> bool:
    """Delete downloaded track file, lyrics, and database entry."""
    init_offline_db()
    deleted = False
    try:
        with get_db() as conn:
            row = conn.execute(
                "SELECT file_path FROM offline_tracks WHERE video_id = ?", (video_id,)
            ).fetchone()
            if row and row["file_path"]:
                fpath = Path(row["file_path"])
                if fpath.exists():
                    try:
                        fpath.unlink()
                        deleted = True
                    except OSError:
                        pass
            # Delete associated lyrics file if exists
            lrc_file = get_lyrics_dir() / f"{video_id}.lrc"
            if lrc_file.exists():
                try:
                    lrc_file.unlink()
                except OSError:
                    pass

            conn.execute("DELETE FROM offline_tracks WHERE video_id = ?", (video_id,))
            conn.commit()
            deleted = True
    except Exception:
        pass

    # Disk cleanup fallback
    for cand in get_tracks_dir().glob(f"*{video_id}*"):
        try:
            cand.unlink()
            deleted = True
        except OSError:
            pass

    return deleted


def delete_offline_collection(collection_id: str, delete_tracks: bool = False) -> bool:
    """Delete an offline playlist or album collection record."""
    init_offline_db()
    col = get_offline_collection(collection_id)
    if not col:
        return False

    if delete_tracks:
        for vid in col.get("track_ids", []):
            delete_offline_track(vid)

    with get_db() as conn:
        conn.execute("DELETE FROM offline_collections WHERE id = ?", (col["id"],))
        conn.commit()
    return True


def clear_all_offline_data(delete_files: bool = True) -> int:
    """Remove all offline downloaded tracks and collections."""
    init_offline_db()
    count = 0
    with get_db() as conn:
        rows = conn.execute("SELECT video_id, file_path FROM offline_tracks").fetchall()
        count = len(rows)
        if delete_files:
            for r in rows:
                fpath = Path(r["file_path"])
                if fpath.exists():
                    try:
                        fpath.unlink()
                    except OSError:
                        pass
            # Clear tracks and lyrics directories
            for f in get_tracks_dir().glob("*"):
                try:
                    f.unlink()
                except OSError:
                    pass
            for f in get_lyrics_dir().glob("*"):
                try:
                    f.unlink()
                except OSError:
                    pass

        conn.execute("DELETE FROM offline_tracks")
        conn.execute("DELETE FROM offline_collections")
        conn.commit()
    return count


def get_offline_stats() -> Dict[str, Any]:
    """Return storage and item statistics for offline mode."""
    init_offline_db()
    total_tracks = 0
    total_bytes = 0
    playlists_count = 0
    albums_count = 0

    try:
        with get_db() as conn:
            r = conn.execute("SELECT COUNT(*), COALESCE(SUM(file_size), 0) FROM offline_tracks").fetchone()
            if r:
                total_tracks = r[0]
                total_bytes = r[1]

            r_p = conn.execute("SELECT COUNT(*) FROM offline_collections WHERE type = 'playlist'").fetchone()
            if r_p:
                playlists_count = r_p[0]

            r_a = conn.execute("SELECT COUNT(*) FROM offline_collections WHERE type = 'album'").fetchone()
            if r_a:
                albums_count = r_a[0]
    except Exception:
        pass

    # If DB byte sum is 0, verify from disk
    if total_bytes == 0:
        for f in get_tracks_dir().glob("*"):
            if f.is_file():
                total_bytes += f.stat().st_size

    return {
        "total_tracks": total_tracks,
        "total_playlists": playlists_count,
        "total_albums": albums_count,
        "total_bytes": total_bytes,
        "total_size_str": format_bytes(total_bytes),
        "downloads_dir": str(get_downloads_dir()),
        "tracks_dir": str(get_tracks_dir()),
        "lyrics_dir": str(get_lyrics_dir()),
    }


def is_offline_mode_enabled() -> bool:
    """Check if offline-only mode is toggled via config or environment."""
    if os.environ.get("MUSIC_OFFLINE", "").strip() in ("1", "true", "yes", "on"):
        return True
    return bool(get_config_val("offline_mode", False))


def check_internet_connectivity(host: str = "1.1.1.1", port: int = 53, timeout: float = 1.2) -> bool:
    """Check if internet is reachable."""
    if is_offline_mode_enabled():
        return False
    try:
        socket.setdefaulttimeout(timeout)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((host, port))
        return True
    except (socket.timeout, socket.error, OSError):
        try:
            # Fallback check to Google DNS
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect(("8.8.8.8", 53))
            return True
        except Exception:
            return False


# --- Downloading Logic ---


def _download_lyrics_offline(song: SongItem) -> None:
    """Fetch and persist synced lyrics to disk alongside track."""
    try:
        lyrics = fetch_lyrics(
            title=song.title,
            artist=song.artist,
            duration_sec=song.duration_seconds,
            video_id=song.video_id,
            timeout=3.0,
        )
        if lyrics and lyrics.lines:
            lrc_file = get_lyrics_dir() / f"{song.video_id}.lrc"
            lines_content = []
            for l in lyrics.lines:
                m = int(l.timestamp // 60)
                s = l.timestamp % 60
                lines_content.append(f"[{m:02d}:{s:05.2f}]{l.text}")
            with open(lrc_file, "w", encoding="utf-8") as f:
                f.write("\n".join(lines_content) + "\n")
    except Exception:
        pass


class DownloadTracker:
    """Thread-safe persistent download progress tracker for single songs and collections."""

    def __init__(self):
        self._lock = threading.RLock()
        self.state = "idle"  # "idle", "downloading", "finished", "error"
        self.item_type = ""  # "song", "playlist", "album", "batch"
        self.collection_title = ""
        self.current_title = ""
        self.current_index = 0
        self.total_items = 0
        self.percent = 0.0
        self.speed = ""
        self.eta = ""
        self.message = ""
        self.error = ""
        self.finished_at = 0.0

    def start_download(self, item_type: str, collection_title: str, total_items: int = 1):
        with self._lock:
            self.state = "downloading"
            self.item_type = item_type
            self.collection_title = collection_title
            self.current_title = collection_title if total_items == 1 else ""
            self.current_index = 1
            self.total_items = max(1, total_items)
            self.percent = 0.0
            self.speed = ""
            self.eta = ""
            self.message = f"Starting download of {collection_title}..."
            self.error = ""
            self.finished_at = 0.0

    def update_track(self, current_index: int, current_title: str, track_percent: float = 0.0, speed: str = "", eta: str = ""):
        with self._lock:
            self.current_index = current_index
            self.current_title = current_title
            base_percent = ((current_index - 1) / max(1, self.total_items)) * 100.0
            item_contribution = (track_percent / max(1, self.total_items))
            self.percent = min(100.0, max(0.0, base_percent + item_contribution))
            if speed:
                self.speed = speed
            if eta:
                self.eta = eta
            self.message = f"[{current_index}/{self.total_items}] {current_title}"

    def update_progress(self, percent: float, speed: str = "", eta: str = ""):
        with self._lock:
            if self.total_items <= 1:
                self.percent = min(100.0, max(0.0, percent))
            else:
                base_percent = ((self.current_index - 1) / max(1, self.total_items)) * 100.0
                item_contribution = (percent / max(1, self.total_items))
                self.percent = min(100.0, max(0.0, base_percent + item_contribution))
            if speed:
                self.speed = speed
            if eta:
                self.eta = eta

    def finish(self, success: bool = True, message: str = ""):
        with self._lock:
            self.state = "finished" if success else "error"
            self.percent = 100.0 if success else self.percent
            self.message = message or ("✓ Download complete" if success else "✗ Download failed")
            self.finished_at = time.time()

    def is_active(self) -> bool:
        with self._lock:
            if self.state == "downloading":
                return True
            if self.state in ("finished", "error"):
                return (time.time() - self.finished_at) < 4.0
            return False

    def get_snapshot(self) -> dict:
        with self._lock:
            return {
                "state": self.state,
                "item_type": self.item_type,
                "collection_title": self.collection_title,
                "current_title": self.current_title,
                "current_index": self.current_index,
                "total_items": self.total_items,
                "percent": self.percent,
                "speed": self.speed,
                "eta": self.eta,
                "message": self.message,
                "error": self.error,
                "is_active": self.is_active(),
            }


_GLOBAL_DOWNLOAD_TRACKER = DownloadTracker()


def get_download_tracker() -> DownloadTracker:
    """Return the global download progress tracker instance."""
    return _GLOBAL_DOWNLOAD_TRACKER


def download_song(
    song: SongItem,
    console: Optional[Console] = None,
    show_status: bool = True,
    timeout: int = 180,
) -> Tuple[bool, str, Optional[str]]:
    """Download a single song to local storage using yt-dlp.

    Returns:
        (success: bool, message: str, file_path: Optional[str])
    """
    tracker = get_download_tracker()
    is_standalone = not tracker.is_active() or tracker.item_type == "song"
    if is_standalone:
        tracker.start_download("song", song.title, total_items=1)
        tracker.update_track(1, song.title, 0.0)

    if is_track_offline(song.video_id):
        existing_path = get_offline_track_path(song.video_id)
        if is_standalone:
            tracker.finish(True, f"✓ Already offline: {song.title}")
        return True, f"Already downloaded: {song.title}", existing_path

    tracks_dir = get_tracks_dir()
    clean_artist = sanitize_filename(song.artist or "Unknown Artist", max_len=40)
    clean_title = sanitize_filename(song.title or "Unknown Title", max_len=60)
    out_prefix = f"{clean_artist} - {clean_title} [{song.video_id}]"
    out_tmpl = str(tracks_dir / f"{out_prefix}.%(ext)s")

    base_cmd = get_ytdl_cmd_prefix()
    target_url = f"https://www.youtube.com/watch?v={song.video_id}"

    has_ffmpeg = bool(shutil.which("ffmpeg"))
    audio_fmt = "mp3" if has_ffmpeg else "m4a"

    # Progress hook for yt-dlp
    def _progress_hook(d):
        status = d.get("status")
        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes", 0)
            pct = (downloaded / total * 100.0) if total else 0.0
            spd = d.get("_speed_str") or (f"{format_bytes(d.get('speed', 0))}/s" if d.get("speed") else "")
            eta = d.get("_eta_str") or (f"{d.get('eta')}s" if d.get("eta") else "")
            tracker.update_progress(pct, speed=spd, eta=eta)
        elif status == "finished":
            tracker.update_progress(100.0, speed="", eta="")

    # Try yt_dlp python module first for real-time progress callbacks
    ytdl_success = False
    try:
        import yt_dlp
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": out_tmpl,
            "quiet": True,
            "no_warnings": True,
            "progress_hooks": [_progress_hook],
        }
        if has_ffmpeg:
            ydl_opts["postprocessors"] = [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "0",
                },
                {
                    "key": "FFmpegMetadata",
                },
            ]
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([target_url])
        ytdl_success = True
    except Exception:
        ytdl_success = False

    # Fallback to subprocess if python API failed
    if not ytdl_success:
        cmd = [
            *base_cmd,
            "--no-playlist",
            "--no-warnings",
            "-f", "bestaudio/best",
            "-o", out_tmpl,
        ]
        if has_ffmpeg:
            cmd.extend([
                "-x",
                "--audio-format", "mp3",
                "--audio-quality", "0",
                "--add-metadata",
            ])
        cmd.append(target_url)

        try:
            tracker.update_progress(20.0)
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            if proc.returncode != 0 and has_ffmpeg:
                tracker.update_progress(40.0)
                cmd_fallback = [
                    *base_cmd,
                    "--no-playlist",
                    "--no-warnings",
                    "-f", "ba/b",
                    "-o", out_tmpl,
                    target_url,
                ]
                proc = subprocess.run(cmd_fallback, capture_output=True, text=True, timeout=timeout)
            tracker.update_progress(90.0)
        except Exception as e:
            if is_standalone:
                tracker.finish(False, f"✗ Download failed: {e}")
            return False, f"Failed downloading {song.title}: {e}", None

    # Locate downloaded file on disk
    found_file: Optional[Path] = None
    for cand in tracks_dir.glob(f"*{song.video_id}*"):
        if cand.is_file() and not cand.name.endswith((".part", ".ytdl", ".temp")):
            found_file = cand
            break

    if not found_file or not found_file.exists() or found_file.stat().st_size == 0:
        if is_standalone:
            tracker.finish(False, "✗ No audio file generated")
        return False, f"Download failed for '{song.title}' (no audio file generated)", None

    file_size = found_file.stat().st_size
    ext = found_file.suffix.lstrip(".").lower() or audio_fmt
    actual_path = str(found_file.resolve())

    # Save to database
    save_offline_track(
        song=song,
        file_path=actual_path,
        file_size=file_size,
        audio_format=ext,
    )

    # Download lyrics in background
    threading.Thread(target=_download_lyrics_offline, args=(song,), daemon=True).start()

    tracker.update_progress(100.0)
    if is_standalone:
        tracker.finish(True, f"✓ Downloaded: {song.title} ({format_bytes(file_size)})")

    return True, f"✓ Downloaded: {song.title} ({format_bytes(file_size)})", actual_path


def download_songs_batch(
    songs: List[SongItem],
    collection_title: str = "Batch",
    collection_type: str = "batch",
    collection_id: str = "",
    author: str = "",
    console: Optional[Console] = None,
    show_cli_progress: bool = True,
) -> Tuple[int, int, List[SongItem]]:
    """Download multiple tracks with persistent DownloadTracker and live Rich progress bar.

    Returns:
        (downloaded_count, failed_count, successful_songs)
    """
    tracker = get_download_tracker()
    tracker.start_download(collection_type, collection_title, total_items=len(songs))

    if not songs:
        tracker.finish(False, "No tracks provided")
        return 0, 0, []

    success_count = 0
    fail_count = 0
    successful_tracks: List[SongItem] = []

    # If running from CLI command (console provided or interactive stdout), show Rich progress bar
    if show_cli_progress and console:
        con = console
        con.print(
            f"\n[bold cyan]⬇ Downloading {len(songs)} tracks for {collection_type.capitalize()}:[/bold cyan] "
            f"[bold white]{collection_title}[/bold white]"
        )
        progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold cyan]{task.fields[status]}[/bold cyan]"),
            BarColumn(bar_width=35, complete_style="bright_cyan", finished_style="green"),
            TaskProgressColumn(),
            MofNCompleteColumn(),
            TimeRemainingColumn(),
            console=con,
        )
        with progress:
            task_id = progress.add_task("downloading", total=len(songs), status="Starting download...")
            for idx, song in enumerate(songs, 1):
                short_title = song.title[:30] + "…" if len(song.title) > 30 else song.title
                progress.update(task_id, status=f"[{idx}/{len(songs)}] {short_title}")
                tracker.update_track(idx, song.title, 0.0)
                ok, msg, fpath = download_song(song, console=con, show_status=False)
                if ok:
                    success_count += 1
                    successful_tracks.append(song)
                else:
                    fail_count += 1
                tracker.update_track(idx, song.title, 100.0)
                progress.advance(task_id)
    else:
        # Background / TUI mode: purely update DownloadTracker
        for idx, song in enumerate(songs, 1):
            tracker.update_track(idx, song.title, 0.0)
            ok, msg, fpath = download_song(song, show_status=False)
            if ok:
                success_count += 1
                successful_tracks.append(song)
            else:
                fail_count += 1
            tracker.update_track(idx, song.title, 100.0)

    # Save collection record if an ID was provided
    if collection_id and successful_tracks:
        save_offline_collection(
            collection_id=collection_id,
            collection_type=collection_type,
            title=collection_title,
            author=author,
            track_ids=[t.video_id for t in successful_tracks],
        )

    tracker.finish(
        success_count > 0,
        f"✓ Downloaded {success_count}/{len(songs)} tracks for {collection_title}",
    )

    if show_cli_progress and console:
        console.print(
            f"[bold green]✓ Finished downloading {collection_title}:[/bold green] "
            f"[cyan]{success_count} succeeded[/cyan]" +
            (f", [red]{fail_count} failed[/red]" if fail_count > 0 else "") +
            f" ([dim]{format_bytes(sum(os.path.getsize(get_offline_track_path(t.video_id) or '') for t in successful_tracks if is_track_offline(t.video_id)))} saved locally[/dim])"
        )

    return success_count, fail_count, successful_tracks


def download_playlist_by_query(
    query: str,
    console: Optional[Console] = None,
) -> Tuple[bool, str, Optional[PlaylistItem], List[SongItem]]:
    """Search for or load a playlist, then download all its tracks for offline playback."""
    con = console or Console()
    clean_q = query.strip()
    p_item: Optional[PlaylistItem] = None
    tracks: List[SongItem] = []

    if is_playlist_url(clean_q):
        con.print("[cyan]Resolving playlist from URL...[/cyan]")
        p_item, tracks = get_playlist_tracks(clean_q)
    else:
        con.print(f"[cyan]Searching YouTube Music for playlist:[/cyan] [bold white]{clean_q}[/bold white]...")
        results = search_playlists(clean_q, limit=5)
        if not results:
            return False, f"No playlists found matching '{clean_q}'", None, []

        from music.ui import prompt_playlist_selection
        p_item = prompt_playlist_selection(results)
        if not p_item:
            return False, "Playlist selection canceled", None, []

        con.print(f"[cyan]Fetching tracks for:[/cyan] [bold white]{p_item.title}[/bold white]...")
        _, tracks = get_playlist_tracks(p_item.playlist_id)

    if not tracks:
        return False, "No downloadable tracks found in playlist", p_item, []

    p_title = p_item.title if p_item else clean_q
    p_id = p_item.playlist_id if p_item else clean_q
    p_author = p_item.author if p_item else ""

    succ, fail, downloaded = download_songs_batch(
        songs=tracks,
        collection_title=p_title,
        collection_type="playlist",
        collection_id=p_id,
        author=p_author,
        console=con,
    )

    return True, f"Playlist '{p_title}' downloaded ({succ} tracks)", p_item, downloaded


def download_album_by_query(
    query: str,
    console: Optional[Console] = None,
) -> Tuple[bool, str, Optional[AlbumItem], List[SongItem]]:
    """Search for or load an album, then download all its tracks for offline playback."""
    con = console or Console()
    clean_q = query.strip()
    alb_item: Optional[AlbumItem] = None
    tracks: List[SongItem] = []

    album_id = extract_album_id(clean_q)
    if album_id or clean_q.startswith("MPREb_"):
        con.print(f"[cyan]Fetching album details for {clean_q}...[/cyan]")
        alb_item, tracks = get_album_tracks(album_id or clean_q)
    else:
        con.print(f"[cyan]Searching YouTube Music for album:[/cyan] [bold white]{clean_q}[/bold white]...")
        results = search_albums(clean_q, limit=6)
        if not results:
            return False, f"No albums found matching '{clean_q}'", None, []

        from music.ui import prompt_album_selection
        alb_item = prompt_album_selection(results)
        if not alb_item:
            return False, "Album selection canceled", None, []

        con.print(f"[cyan]Fetching tracks for album:[/cyan] [bold white]{alb_item.title}[/bold white]...")
        _, tracks = get_album_tracks(alb_item.browse_id)

    if not tracks:
        return False, "No downloadable tracks found in album", alb_item, []

    alb_title = alb_item.title if alb_item else clean_q
    alb_id = alb_item.browse_id if alb_item else clean_q
    alb_artist = alb_item.artist if alb_item else ""

    succ, fail, downloaded = download_songs_batch(
        songs=tracks,
        collection_title=alb_title,
        collection_type="album",
        collection_id=alb_id,
        author=alb_artist,
        console=con,
    )

    return True, f"Album '{alb_title}' downloaded ({succ} tracks)", alb_item, downloaded
