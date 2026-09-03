"""Persistent disk cache for search results and instant query acceleration."""

import json
import time
from typing import Any, Dict, List, Optional

from music.config import CONFIG_DIR, ensure_config_dir

SEARCH_CACHE_FILE = CONFIG_DIR / "search_cache.json"
CACHE_TTL_SECONDS = 86400  # 24 hours


def _load_cache_data() -> Dict[str, Any]:
    if not SEARCH_CACHE_FILE.exists():
        return {}
    try:
        with open(SEARCH_CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache_data(data: Dict[str, Any]) -> None:
    ensure_config_dir()
    try:
        if len(data) > 200:
            sorted_keys = sorted(data.keys(), key=lambda k: data[k].get("ts", 0), reverse=True)
            data = {k: data[k] for k in sorted_keys[:200]}
        with open(SEARCH_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def get_cached_search(query: str, filter_mode: str) -> Optional[List[Dict[str, Any]]]:
    """Retrieve cached search items for (query, filter_mode) if not expired."""
    key = f"{filter_mode.lower()}:{query.strip().lower()}"
    cache = _load_cache_data()
    entry = cache.get(key)
    if not entry:
        return None

    cached_at = entry.get("ts", 0)
    if time.time() - cached_at > CACHE_TTL_SECONDS:
        return None

    return entry.get("items", [])


def set_cached_search(query: str, filter_mode: str, serialized_items: List[Dict[str, Any]]) -> None:
    """Save search items for (query, filter_mode) into persistent disk cache."""
    key = f"{filter_mode.lower()}:{query.strip().lower()}"
    cache = _load_cache_data()
    cache[key] = {
        "ts": time.time(),
        "items": serialized_items[:25],
    }
    _save_cache_data(cache)
