"""Time-synchronized lyrics (LRC) engine for music-cli.

Queries LRCLIB (open-source lyrics API) with fallback to ytmusicapi.
Parses LRC timestamps and generates real-time teleprompter window lines.
"""

import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class LyricLine:
    timestamp: float  # Seconds
    text: str


@dataclass
class LyricsData:
    is_synced: bool
    lines: List[LyricLine] = field(default_factory=list)
    plain_text: str = ""


# In-memory lyrics cache {video_id or cache_key: LyricsData}
_LYRICS_CACHE: Dict[str, Optional[LyricsData]] = {}

_LRC_REGEX = re.compile(r"\[(\d{1,2}):(\d{2}(?:\.\d+)?)\](.*)")


def clean_title_for_search(title: str) -> str:
    """Clean video/track title removing video suffixes, remasters, and feat tags."""
    t = title
    # Remove parentheses with official video, music video, audio, etc.
    t = re.sub(r"\(.*?(?:official|music|video|audio|lyrics|remastered|version|live|hd|4k).*?\)", "", t, flags=re.I)
    t = re.sub(r"\[.*?(?:official|music|video|audio|lyrics|remastered|version|live|hd|4k).*?\]", "", t, flags=re.I)
    # Remove 'ft.' or 'feat.' from title
    t = re.sub(r"\s+(?:feat|ft)\.?\s+.*$", "", t, flags=re.I)
    # Remove double quotes / special characters
    t = t.replace('"', "").replace("'", "")
    return t.strip()


def parse_lrc(lrc_content: str) -> List[LyricLine]:
    """Parse standard LRC file format with [mm:ss.xx] timestamps into LyricLine items."""
    lines: List[LyricLine] = []
    for raw_line in lrc_content.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = _LRC_REGEX.match(line)
        if match:
            minutes = int(match.group(1))
            seconds = float(match.group(2))
            total_sec = minutes * 60.0 + seconds
            text = match.group(3).strip()
            if text:
                lines.append(LyricLine(timestamp=total_sec, text=text))

    lines.sort(key=lambda x: x.timestamp)
    return lines


def fetch_lyrics(
    title: str,
    artist: str,
    duration_sec: int = 0,
    video_id: str = "",
    timeout: float = 3.0,
) -> Optional[LyricsData]:
    """Fetch time-synchronized lyrics from LRCLIB with fallback to YouTube Music."""
    cache_key = video_id or f"{title.lower()}::{artist.lower()}"
    if cache_key in _LYRICS_CACHE:
        return _LYRICS_CACHE[cache_key]

    clean_title = clean_title_for_search(title)
    clean_artist = artist.split(",")[0].strip() if artist else ""

    # Attempt 1: Direct exact match from LRCLIB
    try:
        query_params = {
            "track_name": clean_title,
            "artist_name": clean_artist,
        }
        if duration_sec > 0:
            query_params["duration"] = str(duration_sec)

        url = f"https://lrclib.net/api/get?{urllib.parse.urlencode(query_params)}"
        req = urllib.request.Request(url, headers={"User-Agent": "music-cli/0.1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        synced = data.get("syncedLyrics")
        plain = data.get("plainLyrics") or ""
        if synced:
            parsed = parse_lrc(synced)
            if parsed:
                result = LyricsData(is_synced=True, lines=parsed, plain_text=plain)
                _LYRICS_CACHE[cache_key] = result
                return result

        if plain:
            result = LyricsData(is_synced=False, lines=[], plain_text=plain)
            _LYRICS_CACHE[cache_key] = result
            return result
    except Exception:
        pass

    # Attempt 2: Search LRCLIB with general query
    try:
        search_query = f"{clean_title} {clean_artist}".strip()
        url = f"https://lrclib.net/api/search?q={urllib.parse.quote(search_query)}"
        req = urllib.request.Request(url, headers={"User-Agent": "music-cli/0.1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            results = json.loads(resp.read().decode("utf-8"))

        if isinstance(results, list) and results:
            for item in results:
                synced = item.get("syncedLyrics")
                if synced:
                    parsed = parse_lrc(synced)
                    if parsed:
                        result = LyricsData(
                            is_synced=True,
                            lines=parsed,
                            plain_text=item.get("plainLyrics") or "",
                        )
                        _LYRICS_CACHE[cache_key] = result
                        return result

            # If no synced, use first plain lyrics
            first_plain = results[0].get("plainLyrics")
            if first_plain:
                result = LyricsData(is_synced=False, lines=[], plain_text=first_plain)
                _LYRICS_CACHE[cache_key] = result
                return result
    except Exception:
        pass

    # Attempt 3: YouTube Music static lyrics fallback
    if video_id:
        try:
            from ytmusicapi import YTMusic

            yt = YTMusic()
            watch = yt.get_watch_playlist(videoId=video_id)
            lyrics_id = watch.get("lyrics")
            if lyrics_id:
                yt_data = yt.get_lyrics(browseId=lyrics_id)
                lyrics_text = yt_data.get("lyrics")
                if lyrics_text:
                    result = LyricsData(is_synced=False, lines=[], plain_text=lyrics_text)
                    _LYRICS_CACHE[cache_key] = result
                    return result
        except Exception:
            pass

    _LYRICS_CACHE[cache_key] = None
    return None


def get_lyrics_display_window(
    lyrics: Optional[LyricsData],
    time_pos: float,
) -> Tuple[List[Tuple[str, str]], str]:
    """Calculate 3-line teleprompter display window based on current playback timestamp.

    Returns a list of (text, style) tuples.
    """
    if not lyrics:
        return [("♪ (Instrumental or lyrics unavailable) ♪", "dim italic")], "none"

    if not lyrics.is_synced or not lyrics.lines:
        # Static lyrics: show snippet
        plain_lines = [l.strip() for l in lyrics.plain_text.splitlines() if l.strip()]
        if not plain_lines:
            return [("♪ (Instrumental) ♪", "dim italic")], "static"
        sample = plain_lines[:3]
        return [(l, "dim") for l in sample], "static"

    lines = lyrics.lines

    # Before first line is sung
    if time_pos < lines[0].timestamp:
        first_text = lines[0].text
        return [
            ("♪ (Instrumental Intro) ♪", "dim italic"),
            (f"Upcoming: {first_text}", "dim"),
        ], "intro"

    # Find the current line index
    active_idx = 0
    for i, line in enumerate(lines):
        if line.timestamp <= time_pos:
            active_idx = i
        else:
            break

    window: List[Tuple[str, str]] = []

    # Previous line (faded)
    if active_idx > 0:
        window.append((lines[active_idx - 1].text, "dim"))
    else:
        window.append(("", ""))

    # Currently sung line (highlighted bright yellow with indicator)
    window.append((f"▶ {lines[active_idx].text}", "bold bright_yellow"))

    # Next line (readable preview)
    if active_idx + 1 < len(lines):
        window.append((lines[active_idx + 1].text, "dim white"))
    else:
        window.append(("♪ (Outro) ♪", "dim italic"))

    return window, "synced"
