"""YouTube Music search and URL resolution engine."""

import json
import os
import re
import subprocess
import threading
import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Tuple

from music.config import (
    find_node_bin,
    find_ytdl_bin,
    get_config_val,
    get_ytdl_cmd_prefix,
)


@dataclass
class SongItem:
    title: str
    artist: str
    album: str
    duration: str
    duration_seconds: int
    video_id: str
    url: str
    thumbnail: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PlaylistItem:
    title: str
    playlist_id: str
    author: str
    track_count: int
    url: str
    description: str = ""
    thumbnail: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AlbumItem:
    title: str
    browse_id: str
    artist: str
    year: str = ""
    track_count: int = 0
    url: str = ""
    description: str = ""
    thumbnail: str = ""
    audio_playlist_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def format_duration(seconds: int | float | None) -> str:
    """Format seconds into MM:SS or HH:MM:SS."""
    if not seconds or seconds < 0:
        return "00:00"
    s = int(seconds)
    hours = s // 3600
    minutes = (s % 3600) // 60
    secs = s % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def parse_duration_str(dur_str: str) -> int:
    """Parse 'MM:SS' or 'HH:MM:SS' into seconds."""
    if not dur_str:
        return 0
    parts = dur_str.strip().split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        elif len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        elif len(parts) == 1:
            return int(parts[0])
    except ValueError:
        pass
    return 0


def is_playlist_url(query: str) -> bool:
    """Check if query is a YouTube / YouTube Music playlist URL or playlist ID."""
    clean = query.strip()
    if re.search(r"[?&]list=[A-Za-z0-9_-]+", clean):
        return True
    if clean.startswith(("VLPL", "PL", "RDCLAK", "OLAK5uy_")) and len(clean) >= 12:
        return True
    return False


def extract_playlist_id(url_or_id: str) -> Optional[str]:
    """Extract playlist ID from URL or return the clean ID."""
    clean = url_or_id.strip()
    match = re.search(r"[?&]list=([A-Za-z0-9_-]+)", clean)
    if match:
        return match.group(1)
    if clean.startswith(("VLPL", "PL", "RD", "OLAK")) and len(clean) >= 12:
        return clean
    return None


def is_album_url(query: str) -> bool:
    """Check if query is a YouTube Music album URL or browseId."""
    clean = query.strip()
    if "browse/MPREb_" in clean or "channel/MPREb_" in clean:
        return True
    if clean.startswith("MPREb_") and len(clean) >= 10:
        return True
    return False


def extract_album_id(url_or_id: str) -> Optional[str]:
    """Extract album browseId from URL or return the clean ID."""
    clean = url_or_id.strip()
    match = re.search(r"(MPREb_[A-Za-z0-9_-]+)", clean)
    if match:
        return match.group(1)
    if clean.startswith("MPREb_") and len(clean) >= 10:
        return clean
    return None


_YTMUSIC_CLIENT = None


def get_ytmusic_client() -> Any:
    """Return reusable singleton YTMusic client to reuse internal HTTP connection pool."""
    global _YTMUSIC_CLIENT
    if _YTMUSIC_CLIENT is None:
        from ytmusicapi import YTMusic

        _YTMUSIC_CLIENT = YTMusic()
    return _YTMUSIC_CLIENT


def is_youtube_url(query: str) -> bool:
    """Check if query is a direct YouTube or YouTube Music URL or ID."""
    clean = query.strip()
    if re.match(r"^https?://(music\.)?(youtube\.com|youtu\.be)/", clean):
        return True
    if len(clean) == 11 and re.match(r"^[A-Za-z0-9_-]{11}$", clean):
        return True
    return False


def extract_video_id_from_url(url_or_id: str) -> str:
    """Extract YouTube 11-char video ID from URL or return ID itself."""
    clean = url_or_id.strip()
    if len(clean) == 11 and re.match(r"^[A-Za-z0-9_-]{11}$", clean):
        return clean

    match = re.search(r"(?:v=|\/|youtu\.be\/)([a-zA-Z0-9_-]{11})", clean)
    if match:
        return match.group(1)
    return clean


def resolve_direct_item(url_or_id: str) -> Optional[SongItem]:
    """Resolve metadata for a direct YouTube URL or video ID using yt-dlp."""
    base_cmd = get_ytdl_cmd_prefix()
    vid = extract_video_id_from_url(url_or_id)
    url = f"https://www.youtube.com/watch?v={vid}"

    cmd = [
        *base_cmd,
        "--dump-single-json",
        "--skip-download",
        "--no-warnings",
        url,
    ]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=12)
        if proc.returncode == 0:
            data = json.loads(proc.stdout)
            title = data.get("title", "Unknown Title")
            artist = data.get("artist") or data.get("uploader") or data.get("channel", "Unknown Artist")
            album = data.get("album", "")
            duration_sec = data.get("duration", 0)
            thumbnail = data.get("thumbnail", "")

            return SongItem(
                title=title,
                artist=artist,
                album=album,
                duration=format_duration(duration_sec),
                duration_seconds=int(duration_sec or 0),
                video_id=vid,
                url=url,
                thumbnail=thumbnail,
            )
    except Exception:
        pass

    # Fallback basic item
    return SongItem(
        title=f"Track ({vid})",
        artist="YouTube",
        album="",
        duration="--:--",
        duration_seconds=0,
        video_id=vid,
        url=url,
    )


def search_music(query: str, limit: int = 5) -> List[SongItem]:
    """Search YouTube Music for tracks matching the query."""
    if is_youtube_url(query):
        item = resolve_direct_item(query)
        return [item] if item else []

    # If offline mode is enabled, prioritize local downloaded tracks
    try:
        from music.offline import is_offline_mode_enabled, list_offline_tracks
        if is_offline_mode_enabled():
            local = list_offline_tracks(query)
            if local:
                return local[:limit]
    except Exception:
        pass

    # Attempt search via ytmusicapi first (best for accurate songs/artists)
    try:
        yt = get_ytmusic_client()
        # Search songs
        results = yt.search(query, filter="songs", limit=limit)
        if not results:
            # Fallback to general search
            results = yt.search(query, limit=limit)

        items: List[SongItem] = []
        for r in results:
            vid = r.get("videoId")
            if not vid:
                continue

            title = r.get("title", "Unknown Title")
            artists = r.get("artists")
            if isinstance(artists, list):
                artist_names = [a.get("name", "") for a in artists if isinstance(a, dict)]
                artist = ", ".join(filter(None, artist_names)) or "Unknown Artist"
            else:
                artist = str(artists or "Unknown Artist")

            album_data = r.get("album")
            album = album_data.get("name", "") if isinstance(album_data, dict) else ""

            dur_str = r.get("duration", "")
            duration_sec = r.get("duration_seconds")
            if not duration_sec and dur_str:
                duration_sec = parse_duration_str(dur_str)

            thumbnails = r.get("thumbnails", [])
            thumb_url = thumbnails[-1].get("url", "") if thumbnails else ""

            items.append(
                SongItem(
                    title=title,
                    artist=artist,
                    album=album,
                    duration=dur_str or format_duration(duration_sec),
                    duration_seconds=int(duration_sec or 0),
                    video_id=vid,
                    url=f"https://www.youtube.com/watch?v={vid}",
                    thumbnail=thumb_url,
                )
            )
            if len(items) >= limit:
                break

        if items:
            return items
    except Exception:
        # Proceed to yt-dlp fallback
        pass

    # Fallback to yt-dlp search
    res = search_ytdlp_fallback(query, limit)
    if res:
        return res

    # Offline fallback if network searches failed or unreachable
    try:
        from music.offline import list_offline_tracks
        return list_offline_tracks(query)[:limit]
    except Exception:
        return []


def search_playlists(query: str, limit: int = 5) -> List[PlaylistItem]:
    """Search YouTube Music for playlists matching the query."""
    if is_playlist_url(query):
        pid = extract_playlist_id(query)
        if pid:
            item, _ = get_playlist_tracks(pid, limit=1)
            return [item] if item else []

    # If offline mode is enabled, prioritize local offline collections
    try:
        from music.offline import is_offline_mode_enabled, list_offline_collections
        if is_offline_mode_enabled():
            cols = list_offline_collections("playlist", query=query)
            matched = []
            for c in cols:
                matched.append(
                    PlaylistItem(
                        title=c["title"],
                        playlist_id=c["id"],
                        author=c.get("author", "Offline Collection"),
                        track_count=c.get("track_count", 0),
                        url="",
                    )
                )
            if matched:
                return matched[:limit]
    except Exception:
        pass

    try:
        yt = get_ytmusic_client()
        results = yt.search(query, filter="playlists", limit=limit)
        items: List[PlaylistItem] = []

        for p in results:
            pid = p.get("browseId") or ""
            clean_pid = pid[2:] if pid.startswith("VL") else pid
            title = p.get("title", "Untitled Playlist")
            author_val = p.get("author")
            if isinstance(author_val, list):
                author = ", ".join(a.get("name", "") for a in author_val if isinstance(a, dict))
            else:
                author = str(author_val or "YouTube Music")

            count_val = p.get("itemCount")
            try:
                count = int(count_val) if count_val else 0
            except (ValueError, TypeError):
                count = 0

            thumbs = p.get("thumbnails", [])
            thumb_url = thumbs[-1].get("url", "") if isinstance(thumbs, list) and thumbs else ""

            items.append(
                PlaylistItem(
                    title=title,
                    playlist_id=clean_pid or pid,
                    author=author or "YouTube Music",
                    track_count=count,
                    url=f"https://music.youtube.com/playlist?list={clean_pid or pid}",
                    thumbnail=thumb_url,
                )
            )

            if len(items) >= limit:
                break

        if items:
            return items
    except Exception:
        pass

    # Attempt offline search if online search yielded no results or in offline mode
    try:
        from music.offline import list_offline_collections
        cols = list_offline_collections("playlist")
        matched = []
        for c in cols:
            if query.lower() in c["title"].lower() or query.lower() in c.get("author", "").lower():
                matched.append(
                    PlaylistItem(
                        title=c["title"],
                        playlist_id=c["id"],
                        author=c.get("author", "Offline Collection"),
                        track_count=c.get("track_count", 0),
                        url=f"https://music.youtube.com/playlist?list={c['id']}",
                        thumbnail=c.get("thumbnail", ""),
                    )
                )
        if matched:
            return matched[:limit]
    except Exception:
        pass

    return []


def get_playlist_tracks(
    playlist_id_or_url: str,
    limit: int = 100,
) -> Tuple[Optional[PlaylistItem], List[SongItem]]:
    """Retrieve full track list and metadata for a playlist."""
    pid = extract_playlist_id(playlist_id_or_url) or playlist_id_or_url.strip()

    # Prioritize offline collection
    try:
        from music.offline import get_offline_collection_tracks
        col, local_tracks = get_offline_collection_tracks(pid)
        if col and local_tracks:
            p_item = PlaylistItem(
                title=col["title"],
                playlist_id=col["id"],
                author=col.get("author", "Offline Collection"),
                track_count=len(local_tracks),
                url=f"https://music.youtube.com/playlist?list={col['id']}",
                thumbnail=col.get("thumbnail", ""),
            )
            return p_item, local_tracks
    except Exception:
        pass

    # Attempt 1: ytmusicapi
    try:
        yt = get_ytmusic_client()
        p_data = yt.get_playlist(pid, limit=limit)
        title = p_data.get("title", "YouTube Playlist")
        author_data = p_data.get("author", {})
        if isinstance(author_data, dict):
            author = author_data.get("name", "YouTube Music")
        else:
            author = str(author_data or "YouTube Music")

        track_count = int(p_data.get("trackCount") or len(p_data.get("tracks", [])))
        desc = p_data.get("description") or ""
        thumbs = p_data.get("thumbnails", [])
        thumb_url = thumbs[-1].get("url", "") if isinstance(thumbs, list) and thumbs else ""

        p_item = PlaylistItem(
            title=title,
            playlist_id=pid,
            author=author,
            track_count=track_count,
            url=f"https://music.youtube.com/playlist?list={pid}",
            description=desc,
            thumbnail=thumb_url,
        )

        tracks: List[SongItem] = []
        for t in p_data.get("tracks", []):
            vid = t.get("videoId")
            if not vid:
                continue

            t_title = t.get("title", "Unknown Title")
            artists = t.get("artists", [])
            if isinstance(artists, list):
                artist = ", ".join(a.get("name", "") for a in artists if isinstance(a, dict)) or author
            else:
                artist = str(artists or author)

            album_data = t.get("album")
            album = album_data.get("name", "") if isinstance(album_data, dict) else (str(album_data) if album_data else "")
            dur_str = t.get("duration", "")
            dur_sec = t.get("duration_seconds") or parse_duration_str(dur_str)

            t_thumbs = t.get("thumbnails", [])
            t_thumb = t_thumbs[-1].get("url", "") if isinstance(t_thumbs, list) and t_thumbs else ""

            tracks.append(
                SongItem(
                    title=t_title,
                    artist=artist,
                    album=album,
                    duration=dur_str or format_duration(dur_sec),
                    duration_seconds=int(dur_sec or 0),
                    video_id=vid,
                    url=f"https://www.youtube.com/watch?v={vid}",
                    thumbnail=t_thumb,
                )
            )

        if tracks:
            return p_item, tracks
    except Exception:
        pass

    # Attempt 2: Fallback to yt-dlp
    try:
        base_cmd = get_ytdl_cmd_prefix()
        playlist_url = f"https://www.youtube.com/playlist?list={pid}"
        cmd = [*base_cmd, "--flat-playlist", "-J", "--skip-download", playlist_url]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if proc.returncode == 0:
            data = json.loads(proc.stdout)
            title = data.get("title", "YouTube Playlist")
            author = data.get("uploader") or data.get("channel", "YouTube")
            entries = data.get("entries", [])

            p_item = PlaylistItem(
                title=title,
                playlist_id=pid,
                author=author,
                track_count=len(entries),
                url=playlist_url,
            )

            tracks = []
            for e in entries:
                vid = e.get("id")
                if not vid:
                    continue
                e_title = e.get("title", "Unknown Title")
                e_artist = e.get("uploader") or e.get("channel", author)
                dur_sec = int(e.get("duration") or 0)
                tracks.append(
                    SongItem(
                        title=e_title,
                        artist=e_artist,
                        album="",
                        duration=format_duration(dur_sec),
                        duration_seconds=dur_sec,
                        video_id=vid,
                        url=f"https://www.youtube.com/watch?v={vid}",
                    )
                )

            if tracks:
                return p_item, tracks
    except Exception:
        pass

    # Attempt 3: Offline downloaded collection fallback
    try:
        from music.offline import get_offline_collection_tracks
        col, local_tracks = get_offline_collection_tracks(pid)
        if col and local_tracks:
            p_item = PlaylistItem(
                title=col["title"],
                playlist_id=col["id"],
                author=col.get("author", "Offline Collection"),
                track_count=len(local_tracks),
                url=f"https://music.youtube.com/playlist?list={col['id']}",
                thumbnail=col.get("thumbnail", ""),
            )
            return p_item, local_tracks
    except Exception:
        pass

    return None, []


def search_albums(query: str, limit: int = 5) -> List[AlbumItem]:
    """Search YouTube Music for albums matching the query."""
    clean = query.strip()
    if not clean:
        return []

    # If offline mode is enabled, prioritize local offline collections
    try:
        from music.offline import is_offline_mode_enabled, list_offline_collections
        if is_offline_mode_enabled():
            cols = list_offline_collections("album", query=clean)
            matched = []
            for c in cols:
                matched.append(
                    AlbumItem(
                        title=c["title"],
                        browse_id=c["id"],
                        artist=c.get("author", "Offline Collection"),
                        year="",
                        track_count=c.get("track_count", 0),
                    )
                )
            if matched:
                return matched[:limit]
    except Exception:
        pass

    try:
        yt = get_ytmusic_client()
        results = yt.search(clean, filter="albums", limit=limit)
        items: List[AlbumItem] = []

        for a in results:
            bid = a.get("browseId") or ""
            title = a.get("title", "Untitled Album")
            artists_val = a.get("artists")
            if isinstance(artists_val, list):
                artist = ", ".join(art.get("name", "") for art in artists_val if isinstance(art, dict))
            else:
                artist = str(artists_val or "Unknown Artist")
            year = str(a.get("year", ""))
            thumbs = a.get("thumbnails", [])
            thumb_url = thumbs[-1].get("url", "") if isinstance(thumbs, list) and thumbs else ""
            url = f"https://music.youtube.com/browse/{bid}" if bid else ""

            items.append(
                AlbumItem(
                    title=title,
                    browse_id=bid,
                    artist=artist or "Unknown Artist",
                    year=year,
                    thumbnail=thumb_url,
                    url=url,
                )
            )

            if len(items) >= limit:
                break

        if items:
            return items
    except Exception:
        pass

    # Attempt offline search if online search yielded no results
    try:
        from music.offline import list_offline_collections
        cols = list_offline_collections("album")
        matched = []
        for c in cols:
            if clean.lower() in c["title"].lower() or clean.lower() in c.get("author", "").lower():
                matched.append(
                    AlbumItem(
                        title=c["title"],
                        browse_id=c["id"],
                        artist=c.get("author", "Offline Collection"),
                        year="",
                        thumbnail=c.get("thumbnail", ""),
                        url=f"https://music.youtube.com/browse/{c['id']}",
                    )
                )
        if matched:
            return matched[:limit]
    except Exception:
        pass

    return []


def get_album_tracks(browse_id: str, limit: int = 100) -> Tuple[Optional[AlbumItem], List[SongItem]]:
    """Retrieve album metadata and tracks for a given browseId."""
    clean_bid = extract_album_id(browse_id) or browse_id.strip()
    if not clean_bid:
        return None, []

    # Prioritize offline collection
    try:
        from music.offline import get_offline_collection_tracks
        col, local_tracks = get_offline_collection_tracks(clean_bid)
        if col and local_tracks:
            album_item = AlbumItem(
                title=col["title"],
                browse_id=col["id"],
                artist=col.get("author", "Offline Collection"),
                year="",
                track_count=len(local_tracks),
                thumbnail=col.get("thumbnail", ""),
                url=f"https://music.youtube.com/browse/{col['id']}",
            )
            return album_item, local_tracks
    except Exception:
        pass

    try:
        yt = get_ytmusic_client()
        details = yt.get_album(clean_bid)
        if not details:
            return None, []

        title = details.get("title", "Untitled Album")
        artists_val = details.get("artists")
        if isinstance(artists_val, list):
            artist = ", ".join(art.get("name", "") for art in artists_val if isinstance(art, dict))
        else:
            artist = str(artists_val or "Unknown Artist")
        year = str(details.get("year", ""))
        track_cnt = int(details.get("trackCount") or 0)
        audio_pl_id = details.get("audioPlaylistId", "")
        thumbs = details.get("thumbnails", [])
        thumb_url = thumbs[-1].get("url", "") if isinstance(thumbs, list) and thumbs else ""

        album_item = AlbumItem(
            title=title,
            browse_id=clean_bid,
            artist=artist,
            year=year,
            track_count=track_cnt,
            thumbnail=thumb_url,
            url=f"https://music.youtube.com/browse/{clean_bid}",
            audio_playlist_id=audio_pl_id,
        )

        tracks: List[SongItem] = []
        for t in details.get("tracks", []):
            vid = t.get("videoId")
            if not vid:
                continue
            t_title = t.get("title", "Unknown Track")
            t_artists = t.get("artists")
            if isinstance(t_artists, list):
                t_artist = ", ".join(art.get("name", "") for art in t_artists if isinstance(art, dict)) or artist
            else:
                t_artist = artist
            dur_sec = int(t.get("duration_seconds") or 0)
            dur_str = t.get("duration") or format_duration(dur_sec)
            tracks.append(
                SongItem(
                    title=t_title,
                    artist=t_artist,
                    album=title,
                    duration=dur_str,
                    duration_seconds=dur_sec,
                    video_id=vid,
                    url=f"https://music.youtube.com/watch?v={vid}",
                )
            )
            if len(tracks) >= limit:
                break

        return album_item, tracks
    except Exception:
        pass

    # Attempt 2: Offline collection fallback
    try:
        from music.offline import get_offline_collection_tracks
        col, local_tracks = get_offline_collection_tracks(clean_bid)
        if col and local_tracks:
            album_item = AlbumItem(
                title=col["title"],
                browse_id=col["id"],
                artist=col.get("author", "Offline Collection"),
                year="",
                track_count=len(local_tracks),
                thumbnail=col.get("thumbnail", ""),
                url=f"https://music.youtube.com/browse/{col['id']}",
            )
            return album_item, local_tracks
    except Exception:
        pass

    return None, []


def search_ytdlp_fallback(query: str, limit: int = 5) -> List[SongItem]:
    """Fallback search using yt-dlp flat playlist extraction."""
    base_cmd = get_ytdl_cmd_prefix()
    cmd = [
        *base_cmd,
        f"ytsearch{limit}:{query}",
        "--dump-single-json",
        "--flat-playlist",
        "--skip-download",
        "--no-warnings",
    ]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=12)
        if proc.returncode != 0:
            return []

        data = json.loads(proc.stdout)
        entries = data.get("entries", [])
        items: List[SongItem] = []

        for e in entries:
            vid = e.get("id")
            if not vid:
                continue
            title = e.get("title", "Unknown Title")
            uploader = e.get("uploader") or e.get("channel", "YouTube")
            dur = e.get("duration") or 0

            items.append(
                SongItem(
                    title=title,
                    artist=uploader,
                    album="",
                    duration=format_duration(dur),
                    duration_seconds=int(dur),
                    video_id=vid,
                    url=f"https://www.youtube.com/watch?v={vid}",
                )
            )
        return items
    except Exception:
        return []


_STREAM_URL_CACHE: Dict[str, str] = {}
_STREAM_TTL_CACHE: Dict[str, Tuple[str, float]] = {}
_STREAM_LOCK = threading.Lock()


def get_cached_stream_url(video_id: str) -> Optional[str]:
    """Return cached direct audio stream URL if within 5-minute TTL."""
    clean_vid = extract_video_id_from_url(video_id)
    with _STREAM_LOCK:
        if clean_vid in _STREAM_TTL_CACHE:
            url, expiry = _STREAM_TTL_CACHE[clean_vid]
            if time.time() < expiry:
                return url
            del _STREAM_TTL_CACHE[clean_vid]
        return _STREAM_URL_CACHE.get(clean_vid)


def set_cached_stream_url(video_id: str, url: str, ttl: float = 300.0) -> None:
    """Store direct audio stream URL with 5-minute TTL."""
    clean_vid = extract_video_id_from_url(video_id)
    with _STREAM_LOCK:
        _STREAM_URL_CACHE[clean_vid] = url
        _STREAM_TTL_CACHE[clean_vid] = (url, time.time() + ttl)


class StreamPrewarmer:
    """Background daemon pre-resolving audio stream URLs for high-confidence tracks."""

    def __init__(self):
        self._lock = threading.Lock()
        self._active_proc: Optional[subprocess.Popen] = None
        self._active_vid: Optional[str] = None
        self._thread: Optional[threading.Thread] = None

    def prewarm(self, video_id: str) -> None:
        """Pre-warm audio stream URL in background if not already cached."""
        clean_vid = extract_video_id_from_url(video_id)
        if not clean_vid or get_cached_stream_url(clean_vid):
            return

        with self._lock:
            if self._active_vid == clean_vid:
                return
            self._cancel_locked()
            self._active_vid = clean_vid

        def _worker(vid: str):
            try:
                base_cmd = get_ytdl_cmd_prefix()
                cmd = [*base_cmd, "-f", "ba/b", "-g", "--no-warnings", f"https://www.youtube.com/watch?v={vid}"]
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                with self._lock:
                    if self._active_vid != vid:
                        try:
                            proc.terminate()
                        except Exception:
                            pass
                        return
                    self._active_proc = proc
                out, _ = proc.communicate(timeout=10)
                if proc.returncode == 0:
                    lines = [l.strip() for l in out.splitlines() if l.strip().startswith("http")]
                    if lines:
                        set_cached_stream_url(vid, lines[-1])
            except Exception:
                pass
            finally:
                with self._lock:
                    if self._active_vid == vid:
                        self._active_vid = None
                        self._active_proc = None

        t = threading.Thread(target=_worker, args=(clean_vid,), daemon=True)
        with self._lock:
            self._thread = t
        t.start()

    def _cancel_locked(self) -> None:
        if self._active_proc:
            try:
                self._active_proc.terminate()
            except Exception:
                pass
            self._active_proc = None
        self._active_vid = None

    def cancel(self) -> None:
        """Immediately cancel in-flight stream extraction."""
        with self._lock:
            self._cancel_locked()


def resolve_audio_stream_url(song_item_or_url: Any) -> str:
    """Resolve direct audio stream URL (googlevideo.com) using yt-dlp for instant playback."""
    if isinstance(song_item_or_url, SongItem):
        vid = song_item_or_url.video_id
        fallback_url = song_item_or_url.url
    else:
        vid = extract_video_id_from_url(str(song_item_or_url))
        fallback_url = f"https://www.youtube.com/watch?v={vid}"

    # Instant offline playback: check if audio file exists on local disk
    try:
        from music.offline import get_offline_track_path
        local_path = get_offline_track_path(vid)
        if local_path and os.path.exists(local_path):
            return local_path
    except Exception:
        pass

    cached_url = get_cached_stream_url(vid)
    if cached_url:
        return cached_url

    base_cmd = get_ytdl_cmd_prefix()
    target_url = f"https://www.youtube.com/watch?v={vid}"

    # 1. Fast direct extraction (clean stream avoids GVS PO token delay and starts in seconds)
    cmd = [
        *base_cmd,
        "-f", "ba/b",
        "-g",
        "--no-warnings",
        target_url,
    ]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=12)
        if proc.returncode == 0:
            lines = [l.strip() for l in proc.stdout.splitlines() if l.strip().startswith("http")]
            if lines:
                set_cached_stream_url(vid, lines[-1])
                return lines[-1]
    except Exception:
        pass

    # 2. Resilient fallback using mobile/web extractor client (bypasses PO-token challenges)
    cmd_alt = [
        *base_cmd,
        "--extractor-args", "youtube:player_client=android,web",
        "-f", "ba/b",
        "-g",
        "--no-warnings",
        target_url,
    ]
    try:
        proc = subprocess.run(cmd_alt, capture_output=True, text=True, timeout=12)
        if proc.returncode == 0:
            lines = [l.strip() for l in proc.stdout.splitlines() if l.strip().startswith("http")]
            if lines:
                set_cached_stream_url(vid, lines[-1])
                return lines[-1]
    except Exception:
        pass

    # 3. If fast extraction failed (e.g. member-only or private track), try with cookies
    from music.auth import get_ytdl_auth_args

    auth_args = get_ytdl_auth_args()
    if auth_args:
        node_bin = find_node_bin()
        cmd_auth = [
            *base_cmd,
            *auth_args,
            "-f", "ba/b",
            "-g",
            "--no-warnings",
            target_url,
        ]
        if node_bin:
            cmd_auth.extend(["--js-runtimes", f"node:{node_bin}"])
            cmd_auth.extend(["--remote-components", "ejs:github"])
        try:
            proc = subprocess.run(cmd_auth, capture_output=True, text=True, timeout=15)
            if proc.returncode == 0:
                lines = [l.strip() for l in proc.stdout.splitlines() if l.strip().startswith("http")]
                if lines:
                    set_cached_stream_url(vid, lines[-1])
                    return lines[-1]
        except Exception:
            pass

    return fallback_url


def get_related_tracks(video_id: str, limit: int = 20) -> List[SongItem]:
    """Fetch related / up-next radio tracks for autoplay using YouTube Music watch playlist."""
    clean_vid = extract_video_id_from_url(video_id)

    try:
        yt = get_ytmusic_client()
        watch_data = yt.get_watch_playlist(videoId=clean_vid, limit=limit + 5)
        tracks = watch_data.get("tracks", [])

        items: List[SongItem] = []
        for t in tracks:
            vid = t.get("videoId")
            if not vid or vid == clean_vid:
                continue

            title = t.get("title", "Unknown Title")
            artists = t.get("artists", [])
            if isinstance(artists, list):
                artist = ", ".join(a.get("name", "") for a in artists if isinstance(a, dict)) or "Unknown Artist"
            else:
                artist = str(artists or "Unknown Artist")

            album_data = t.get("album", {})
            album = album_data.get("name", "") if isinstance(album_data, dict) else ""
            dur_str = t.get("length", "")
            dur_sec = parse_duration_str(dur_str)

            thumbs = t.get("thumbnail", [])
            thumb_url = thumbs[-1].get("url", "") if isinstance(thumbs, list) and thumbs else ""

            items.append(
                SongItem(
                    title=title,
                    artist=artist,
                    album=album,
                    duration=dur_str or format_duration(dur_sec),
                    duration_seconds=dur_sec,
                    video_id=vid,
                    url=f"https://www.youtube.com/watch?v={vid}",
                    thumbnail=thumb_url,
                )
            )

            if len(items) >= limit:
                break

        if items:
            return items
    except Exception:
        pass

    return []
