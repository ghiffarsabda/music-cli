"""YouTube Music search and URL resolution engine."""

import json
import re
import subprocess
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

from music.config import get_config_val


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
    yt_dlp = get_config_val("yt_dlp_path", "yt-dlp")
    vid = extract_video_id_from_url(url_or_id)
    url = f"https://www.youtube.com/watch?v={vid}"

    cmd = [
        yt_dlp,
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

    # Attempt search via ytmusicapi first (best for accurate songs/artists)
    try:
        from ytmusicapi import YTMusic

        yt = YTMusic()
        # Search songs
        results = yt.search(query, filter="songs")
        if not results:
            # Fallback to general search
            results = yt.search(query)

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
    return search_ytdlp_fallback(query, limit)


def search_ytdlp_fallback(query: str, limit: int = 5) -> List[SongItem]:
    """Fallback search using yt-dlp flat playlist extraction."""
    yt_dlp = get_config_val("yt_dlp_path", "yt-dlp")
    cmd = [
        yt_dlp,
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


def resolve_audio_stream_url(song_item_or_url: Any) -> str:
    """Resolve direct audio stream URL (googlevideo.com) using yt-dlp for instant playback."""
    if isinstance(song_item_or_url, SongItem):
        vid = song_item_or_url.video_id
        fallback_url = song_item_or_url.url
    else:
        vid = extract_video_id_from_url(str(song_item_or_url))
        fallback_url = f"https://www.youtube.com/watch?v={vid}"

    yt_dlp = get_config_val("yt_dlp_path", "yt-dlp")
    target_url = f"https://www.youtube.com/watch?v={vid}"

    # Fast direct extraction (clean stream avoids GVS PO token delay and starts in seconds)
    cmd = [
        yt_dlp,
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
                return lines[-1]
    except Exception:
        pass

    # If fast extraction failed (e.g. member-only or private track), try with cookies
    from music.auth import get_ytdl_auth_args

    auth_args = get_ytdl_auth_args()
    if auth_args:
        node_bin = get_config_val("node_path", "")
        cmd_auth = [
            yt_dlp,
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
                    return lines[-1]
        except Exception:
            pass

    return fallback_url
