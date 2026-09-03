"""Embedded SQLite full-text search (FTS5) and local library engine.

Provides sub-millisecond local search, BM25 relevance scoring, typo-tolerant
fuzzy matching, and automated history.json migration strictly using the
Python standard library.
"""

from contextlib import contextmanager
from datetime import datetime
import difflib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Dict, Generator, List, Optional, Set, Tuple, Union
import unicodedata

from music.config import HISTORY_FILE, LIBRARY_DB
from music.search import SongItem

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;
PRAGMA busy_timeout=5000;
PRAGMA cache_size=-2000;

CREATE TABLE IF NOT EXISTS tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    artist TEXT NOT NULL,
    album TEXT NOT NULL DEFAULT '',
    duration TEXT NOT NULL DEFAULT '00:00',
    duration_seconds INTEGER NOT NULL DEFAULT 0,
    url TEXT NOT NULL DEFAULT '',
    thumbnail TEXT NOT NULL DEFAULT '',
    played_at TEXT NOT NULL,
    play_count INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_tracks_played_at ON tracks(played_at DESC);

CREATE VIRTUAL TABLE IF NOT EXISTS tracks_fts USING fts5(
    title,
    artist,
    album,
    content='tracks',
    content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS tracks_ai AFTER INSERT ON tracks BEGIN
  INSERT INTO tracks_fts(rowid, title, artist, album)
  VALUES (new.id, new.title, new.artist, new.album);
END;

CREATE TRIGGER IF NOT EXISTS tracks_ad AFTER DELETE ON tracks BEGIN
  INSERT INTO tracks_fts(tracks_fts, rowid, title, artist, album)
  VALUES ('delete', old.id, old.title, old.artist, old.album);
END;

CREATE TRIGGER IF NOT EXISTS tracks_au AFTER UPDATE ON tracks BEGIN
  INSERT INTO tracks_fts(tracks_fts, rowid, title, artist, album)
  VALUES ('delete', old.id, old.title, old.artist, old.album);
  INSERT INTO tracks_fts(rowid, title, artist, album)
  VALUES (new.id, new.title, new.artist, new.album);
END;
"""


def get_default_db_path() -> Path:
    """Return the default library database path."""
    return LIBRARY_DB


def get_db_connection(
    db_path: Optional[Union[Path, str, sqlite3.Connection]] = None,
) -> sqlite3.Connection:
    """Create or return an SQLite connection configured with WAL and performance PRAGMAs."""
    if isinstance(db_path, sqlite3.Connection):
        return db_path

    if db_path is None:
        target = get_default_db_path()
    else:
        target = Path(db_path)

    if str(target) != ":memory:":
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
        except (PermissionError, OSError):
            pass

    try:
        conn = sqlite3.connect(str(target), check_same_thread=False, timeout=5.0)
    except sqlite3.OperationalError:
        if Path(target).exists():
            try:
                conn = sqlite3.connect(
                    f"file:{target}?mode=ro", uri=True, check_same_thread=False, timeout=5.0
                )
            except sqlite3.Error:
                conn = sqlite3.connect(":memory:", check_same_thread=False)
        else:
            conn = sqlite3.connect(":memory:", check_same_thread=False)

    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.execute("PRAGMA busy_timeout=5000;")
        conn.execute("PRAGMA cache_size=-2000;")
    except sqlite3.Error:
        pass

    return conn


@contextmanager
def get_db(
    db_path: Optional[Union[Path, str, sqlite3.Connection]] = None,
) -> Generator[sqlite3.Connection, None, None]:
    """Context manager for scoped database connections."""
    if isinstance(db_path, sqlite3.Connection):
        yield db_path
    else:
        conn = get_db_connection(db_path)
        try:
            yield conn
        finally:
            conn.close()


def init_library_db(
    db_path: Optional[Union[Path, str, sqlite3.Connection]] = None,
) -> sqlite3.Connection:
    """Initialize database schema, tables, triggers, and indices idempotently."""
    conn = get_db_connection(db_path)
    with conn:
        conn.executescript(SCHEMA_SQL)
    if db_path is None:
        migrate_history_json_if_needed(db_path=conn, history_file=HISTORY_FILE)
    return conn


def sanitize_fts5_query(query: str) -> str:
    """Extract alphanumeric Unicode tokens and quote each with prefix wildcard.

    Guarantees zero SQLite syntax errors from punctuation, operators, or quotes.
    Example: 'AC/DC - Back' -> '"AC"* "DC"* "Back"*'
    """
    if not query:
        return ""
    tokens = re.findall(r"\w+", query)
    if not tokens:
        return ""
    return " ".join(f'"{t}"*' for t in tokens)


def search_library_fts5(
    query: str,
    limit: int = 15,
    db_path: Optional[Union[Path, str, sqlite3.Connection]] = None,
) -> List[SongItem]:
    """Search local tracks using SQLite FTS5 and BM25 relevance scoring.

    Returns results ordered by BM25 relevance, tie-broken by recent playback.
    """
    clean_q = sanitize_fts5_query(query)
    if not clean_q:
        return []

    search_sql = """
    SELECT t.video_id, t.title, t.artist, t.album, t.duration,
           t.duration_seconds, t.url, t.thumbnail, t.played_at, t.play_count,
           bm25(tracks_fts, 10.0, 5.0, 1.0) AS score
    FROM tracks_fts
    JOIN tracks t ON t.id = tracks_fts.rowid
    WHERE tracks_fts MATCH :match_query
    ORDER BY score ASC, t.played_at DESC
    LIMIT :limit;
    """
    try:
        with get_db(db_path) as conn:
            cursor = conn.execute(search_sql, {"match_query": clean_q, "limit": limit})
            rows = cursor.fetchall()
            return [
                SongItem(
                    title=r["title"],
                    artist=r["artist"],
                    album=r["album"] or "",
                    duration=r["duration"] or "00:00",
                    duration_seconds=int(r["duration_seconds"] or 0),
                    video_id=r["video_id"],
                    url=r["url"] or f"https://music.youtube.com/watch?v={r['video_id']}",
                    thumbnail=r["thumbnail"] or "",
                )
                for r in rows
            ]
    except sqlite3.Error:
        return []


def migrate_history_json_if_needed(
    db_path: Optional[Union[Path, str, sqlite3.Connection]] = None,
    history_file: Optional[Path] = None,
) -> int:
    """Migrate entries from legacy history.json into SQLite tracks table idempotently.

    Preserves newer playback timestamps and leaves history.json intact.
    """
    target_hist = history_file or HISTORY_FILE
    if not target_hist.exists():
        return 0

    try:
        with open(target_hist, "r", encoding="utf-8") as f:
            entries = json.load(f)
        if not isinstance(entries, list) or not entries:
            return 0
    except (json.JSONDecodeError, OSError, UnicodeDecodeError, Exception):
        return 0

    migrated_count = 0
    now_iso = datetime.now().isoformat()

    upsert_sql = """
    INSERT INTO tracks (
        video_id, title, artist, album,
        duration, duration_seconds, url, thumbnail,
        played_at, play_count
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
    ON CONFLICT(video_id) DO UPDATE SET
        title = CASE WHEN tracks.title = 'Unknown' AND excluded.title != 'Unknown' THEN excluded.title ELSE tracks.title END,
        artist = CASE WHEN tracks.artist = 'Unknown' AND excluded.artist != 'Unknown' THEN excluded.artist ELSE tracks.artist END,
        album = CASE WHEN tracks.album = '' AND excluded.album != '' THEN excluded.album ELSE tracks.album END,
        duration = CASE WHEN tracks.duration = '00:00' AND excluded.duration != '00:00' THEN excluded.duration ELSE tracks.duration END,
        duration_seconds = CASE WHEN tracks.duration_seconds = 0 AND excluded.duration_seconds > 0 THEN excluded.duration_seconds ELSE tracks.duration_seconds END,
        url = CASE WHEN tracks.url = '' AND excluded.url != '' THEN excluded.url ELSE tracks.url END,
        thumbnail = CASE WHEN tracks.thumbnail = '' AND excluded.thumbnail != '' THEN excluded.thumbnail ELSE tracks.thumbnail END,
        played_at = MAX(tracks.played_at, excluded.played_at),
        play_count = tracks.play_count;
    """

    try:
        with get_db(db_path) as conn:
            with conn:
                conn.executescript(SCHEMA_SQL)
                for e in entries:
                    if not isinstance(e, dict):
                        continue

                    vid = str(e.get("video_id") or "").strip()
                    if not vid:
                        continue

                    title = str(e.get("title") or "Unknown").strip()
                    artist = str(e.get("artist") or "Unknown").strip()
                    album = str(e.get("album") or "").strip()
                    duration = str(e.get("duration") or "00:00").strip()

                    try:
                        duration_seconds = int(e.get("duration_seconds") or 0)
                    except (ValueError, TypeError):
                        duration_seconds = 0

                    url = str(e.get("url") or f"https://music.youtube.com/watch?v={vid}").strip()
                    thumbnail = str(e.get("thumbnail") or "").strip()
                    played_at = str(e.get("played_at") or now_iso).strip()

                    conn.execute(
                        upsert_sql,
                        (
                            vid,
                            title,
                            artist,
                            album,
                            duration,
                            duration_seconds,
                            url,
                            thumbnail,
                            played_at,
                        ),
                    )
                    migrated_count += 1
    except (sqlite3.OperationalError, PermissionError, OSError):
        return 0

    return migrated_count


def _normalize_str(text: str) -> str:
    """Normalize string to lowercase ASCII by stripping Unicode diacritics."""
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if unicodedata.category(c) != "Mn").lower().strip()


def search_library_fuzzy(
    query: str,
    limit: int = 15,
    threshold: float = 0.75,
    db_path: Optional[Union[Path, str, sqlite3.Connection]] = None,
) -> List[SongItem]:
    """Perform typo-tolerant fuzzy matching across catalog artists and titles.

    Uses Python standard library difflib and mathematical length candidate pruning.
    """
    clean_q = _normalize_str(query)
    if len(clean_q) < 2:
        return []

    target_db = db_path or get_default_db_path()
    if (
        not isinstance(db_path, sqlite3.Connection)
        and str(target_db) != ":memory:"
        and not Path(target_db).exists()
    ):
        return []

    try:
        with get_db(db_path) as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT title, artist, album, duration, duration_seconds,
                       video_id, url, thumbnail, played_at
                FROM tracks
                ORDER BY played_at DESC
                """
            )
            rows = cur.fetchall()
            if not rows:
                return []

            artist_map: Dict[str, List[sqlite3.Row]] = {}
            title_map: Dict[str, List[sqlite3.Row]] = {}
            window_map: Dict[str, List[sqlite3.Row]] = {}

            q_words = clean_q.split()
            k_words = len(q_words)
            window_lengths = {1, k_words}

            for r in rows:
                t_raw, a_raw = r["title"], r["artist"]
                t_norm = _normalize_str(t_raw)
                a_norm = _normalize_str(a_raw)

                if a_norm:
                    artist_map.setdefault(a_norm, []).append(r)
                if t_norm:
                    title_map.setdefault(t_norm, []).append(r)

                t_tokens = t_norm.split()
                for w_len in window_lengths:
                    if len(t_tokens) >= w_len:
                        for i in range(len(t_tokens) - w_len + 1):
                            win = " ".join(t_tokens[i : i + w_len]).strip("(),.-'\"[]")
                            if len(win) >= 2:
                                window_map.setdefault(win, []).append(r)

            # Mathematical length bounding filter for threshold
            min_len = int(len(clean_q) * 0.6)
            max_len = int(len(clean_q) * 1.67) + 1

            cand_artists = [k for k in artist_map.keys() if min_len <= len(k) <= max_len]
            cand_titles = [k for k in title_map.keys() if min_len <= len(k) <= max_len]
            cand_windows = [k for k in window_map.keys() if min_len <= len(k) <= max_len]

            matched_artist_keys = difflib.get_close_matches(
                clean_q, cand_artists, n=limit, cutoff=threshold
            )
            matched_title_keys = difflib.get_close_matches(
                clean_q, cand_titles, n=limit, cutoff=threshold
            )
            matched_window_keys: List[str] = []
            if len(matched_title_keys) < limit:
                matched_window_keys = difflib.get_close_matches(
                    clean_q, cand_windows, n=limit, cutoff=threshold
                )

            seen_vids: Set[str] = set()
            results: List[SongItem] = []

            def _add_rows(matching_keys: List[str], mapping: Dict[str, List[sqlite3.Row]]) -> None:
                for k in matching_keys:
                    for r in mapping.get(k, []):
                        vid = r["video_id"]
                        if vid not in seen_vids:
                            seen_vids.add(vid)
                            results.append(
                                SongItem(
                                    title=r["title"],
                                    artist=r["artist"],
                                    album=r["album"] or "",
                                    duration=r["duration"] or "00:00",
                                    duration_seconds=int(r["duration_seconds"] or 0),
                                    video_id=vid,
                                    url=r["url"] or f"https://music.youtube.com/watch?v={vid}",
                                    thumbnail=r["thumbnail"] or "",
                                )
                            )
                            if len(results) >= limit:
                                return

            _add_rows(matched_artist_keys, artist_map)
            if len(results) < limit:
                _add_rows(matched_title_keys, title_map)
            if len(results) < limit:
                _add_rows(matched_window_keys, window_map)

            return results[:limit]
    except Exception:
        return []


def search_local_library(
    query: str,
    limit: int = 15,
    db_path: Optional[Union[Path, str, sqlite3.Connection]] = None,
) -> List[SongItem]:
    """Hybrid search across local library:

    1. If query is empty -> returns recent tracks.
    2. If query is non-empty -> attempts FTS5 BM25 search.
    3. If FTS5 returns 0 matches -> falls back to typo-tolerant fuzzy matching.
    """
    clean_q = query.strip() if query else ""
    if not clean_q:
        return get_recent_tracks(limit=limit, db_path=db_path)

    fts_results = search_library_fts5(clean_q, limit=limit, db_path=db_path)
    if fts_results:
        return fts_results

    if len(clean_q) < 2:
        return []

    return search_library_fuzzy(clean_q, limit=limit, threshold=0.75, db_path=db_path)


def add_track_to_library(
    song: SongItem,
    played_at: Optional[str] = None,
    db_path: Optional[Union[Path, str, sqlite3.Connection]] = None,
) -> None:
    """Insert or upsert a played track, incrementing play count and updating timestamp."""
    ts = played_at or datetime.now().isoformat()
    upsert_sql = """
    INSERT INTO tracks (
        video_id, title, artist, album, duration,
        duration_seconds, url, thumbnail, played_at, play_count
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
    ON CONFLICT(video_id) DO UPDATE SET
        title = excluded.title,
        artist = excluded.artist,
        album = CASE WHEN excluded.album != '' THEN excluded.album ELSE tracks.album END,
        duration = excluded.duration,
        duration_seconds = excluded.duration_seconds,
        url = excluded.url,
        thumbnail = CASE WHEN excluded.thumbnail != '' THEN excluded.thumbnail ELSE tracks.thumbnail END,
        played_at = excluded.played_at,
        play_count = tracks.play_count + 1;
    """
    try:
        with get_db(db_path) as conn:
            with conn:
                conn.executescript(SCHEMA_SQL)
                conn.execute(
                    upsert_sql,
                    (
                        song.video_id,
                        song.title,
                        song.artist,
                        song.album or "",
                        song.duration or "00:00",
                        song.duration_seconds or 0,
                        song.url or "",
                        song.thumbnail or "",
                        ts,
                    ),
                )
    except Exception:
        pass


def get_recent_tracks(
    limit: int = 20,
    db_path: Optional[Union[Path, str, sqlite3.Connection]] = None,
) -> List[SongItem]:
    """Retrieve recently played tracks ordered by played_at DESC using index."""
    target_db = db_path or get_default_db_path()
    if (
        not isinstance(db_path, sqlite3.Connection)
        and str(target_db) != ":memory:"
        and not Path(target_db).exists()
    ):
        if db_path is None:
            init_library_db()
        else:
            return []

    query_sql = """
    SELECT video_id, title, artist, album, duration, duration_seconds, url, thumbnail, played_at
    FROM tracks
    ORDER BY played_at DESC
    LIMIT ?;
    """
    try:
        with get_db(db_path) as conn:
            cursor = conn.execute(query_sql, (limit,))
            return [
                SongItem(
                    title=r["title"],
                    artist=r["artist"],
                    album=r["album"] or "",
                    duration=r["duration"] or "00:00",
                    duration_seconds=int(r["duration_seconds"] or 0),
                    video_id=r["video_id"],
                    url=r["url"] or f"https://music.youtube.com/watch?v={r['video_id']}",
                    thumbnail=r["thumbnail"] or "",
                )
                for r in cursor.fetchall()
            ]
    except Exception:
        return []


def clear_library(
    db_path: Optional[Union[Path, str, sqlite3.Connection]] = None,
) -> None:
    """Clear all tracks from the library; triggers automatically clear tracks_fts."""
    target_db = db_path or get_default_db_path()
    if (
        not isinstance(db_path, sqlite3.Connection)
        and str(target_db) != ":memory:"
        and not Path(target_db).exists()
    ):
        return

    try:
        with get_db(db_path) as conn:
            with conn:
                conn.execute("DELETE FROM tracks;")
    except Exception:
        pass
