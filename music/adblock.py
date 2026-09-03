"""Built-in Ad Blocker for music-cli.

Integrates:
1. In-stream ad, sponsor, and non-music segment skipping (via SponsorBlock API).
2. Domain-level blocking for ad networks, doubleclick, and telemetry trackers.
"""

import json
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Set, Tuple

# Human-readable labels for skipped categories
CATEGORY_LABELS = {
    "sponsor": "Sponsor segment",
    "music_offtopic": "Non-music intro/skit",
    "intro": "Intro animation",
    "outro": "Outro/Credits",
    "selfpromo": "Self-promotion",
    "interaction": "Subscribe/Like reminder",
    "preview": "Recap/Preview",
}

# Domain blocklist inspired by uBlock Origin / EasyList for YouTube ad servers & telemetry
AD_BLOCKLIST = {
    "googleads.g.doubleclick.net",
    "pagead2.googlesyndication.com",
    "ad.doubleclick.net",
    "static.doubleclick.net",
    "securepubads.g.doubleclick.net",
    "pubads.g.doubleclick.net",
    "adservice.google.com",
    "stats.g.doubleclick.net",
    "www.google-analytics.com",
    "adclick.g.doubleclick.net",
    "youtube.com/api/stats/ads",
    "youtube.com/pagead/",
    "play.google.com/log",
}

# In-memory segment cache {video_id: [segments]}
_SEGMENT_CACHE: Dict[str, List[Dict[str, Any]]] = {}


def is_ad_domain(url_or_host: str) -> bool:
    """Check whether a URL or hostname matches the ad/telemetry blocklist."""
    clean = url_or_host.lower().strip()
    if clean.startswith("http://") or clean.startswith("https://"):
        try:
            parsed = urllib.parse.urlparse(clean)
            clean = parsed.netloc or parsed.path
        except Exception:
            pass

    for blocked in AD_BLOCKLIST:
        if blocked in clean:
            return True
    return False


def fetch_skip_segments(video_id: str, timeout: float = 2.5) -> List[Dict[str, Any]]:
    """Fetch ad, sponsor, and non-music segments from SponsorBlock API for a video."""
    if not video_id:
        return []

    if video_id in _SEGMENT_CACHE:
        return _SEGMENT_CACHE[video_id]

    categories = ["sponsor", "music_offtopic", "intro", "outro", "selfpromo", "interaction", "preview"]
    cats_json = json.dumps(categories)
    api_url = f"https://sponsor.ajay.app/api/skipSegments?videoID={video_id}&categories={urllib.parse.quote(cats_json)}"

    try:
        req = urllib.request.Request(
            api_url,
            headers={
                "User-Agent": "music-cli/0.1.0 (uBlock/SponsorBlock adblocker)",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        segments = []
        for item in data:
            cat = item.get("category", "sponsor")
            seg = item.get("segment", [])
            if len(seg) >= 2:
                start, end = float(seg[0]), float(seg[1])
                segments.append({
                    "category": cat,
                    "label": CATEGORY_LABELS.get(cat, "Ad/Sponsor"),
                    "start": start,
                    "end": end,
                    "duration": end - start,
                })

        _SEGMENT_CACHE[video_id] = segments
        return segments
    except Exception:
        # 404 means no sponsored segments exist for this track
        _SEGMENT_CACHE[video_id] = []
        return []


def check_and_skip_ads(
    player: Any,
    current_time: float,
    segments: List[Dict[str, Any]],
    skipped_ranges: Set[Tuple[float, float]],
) -> Optional[str]:
    """Check if current playback position is inside an ad/sponsor segment and skip it."""
    if not segments or current_time <= 0:
        return None

    for seg in segments:
        start = seg["start"]
        end = seg["end"]
        seg_key = (round(start, 1), round(end, 1))

        if seg_key in skipped_ranges:
            continue

        # If currently inside the segment
        if start <= current_time < (end - 0.2):
            skipped_ranges.add(seg_key)
            skip_target = end + 0.1
            player.seek_to(skip_target)
            dur = max(1, round(end - start))
            return f"🛡️ AdBlock: Skipped {seg['label']} (+{dur}s)"

    return None
