"""Configuration manager for music-cli."""

import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict

CONFIG_DIR = Path.home() / ".config" / "music-cli"
CONFIG_FILE = CONFIG_DIR / "config.json"
COOKIES_FILE = CONFIG_DIR / "cookies.txt"
HISTORY_FILE = CONFIG_DIR / "history.json"
LIBRARY_DB = CONFIG_DIR / "library.db"


def detect_executable(name: str, fallback_paths: list[str] | None = None) -> str:
    """Find the best available executable path."""
    found = shutil.which(name)
    if found:
        return found
    if fallback_paths:
        for p in fallback_paths:
            expanded = str(Path(p).expanduser())
            if os.path.isfile(expanded) and os.access(expanded, os.X_OK):
                return expanded
    return name


DEFAULT_CONFIG: Dict[str, Any] = {
    "auth_mode": "none",  # 'none', 'browser', 'cookies_file'
    "browser": "chrome",  # 'chrome', 'firefox', 'brave', 'edge', etc.
    "profile": "",  # profile key e.g. 'Default', 'Profile 1'
    "account_email": "",
    "cookies_file": str(COOKIES_FILE),
    "volume": 80,
    "audio_quality": "best",  # 'best', 'high', 'medium'
    "auto_play_top": True,
    "autoplay": True,  # Autoplay next track when song finishes
    "ad_blocker": True,  # Built-in ad & sponsor segment blocker (uBlock/SponsorBlock)
    "show_lyrics": True,  # Time-synchronized lyrics (Karaoke display)
    "yt_dlp_path": detect_executable("yt-dlp", ["~/.local/bin/yt-dlp", "/usr/bin/yt-dlp"]),
    "node_path": detect_executable("node", ["~/.local/bin/node", "/usr/bin/node"]),
}


def ensure_config_dir() -> None:
    """Ensure configuration directory exists."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> Dict[str, Any]:
    """Load configuration from disk, creating default if not existing."""
    ensure_config_dir()
    if not CONFIG_FILE.exists():
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()

    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Merge with defaults in case new keys were added
        merged = DEFAULT_CONFIG.copy()
        merged.update(data)
        return merged
    except Exception:
        return DEFAULT_CONFIG.copy()


def save_config(config: Dict[str, Any]) -> None:
    """Save configuration to disk."""
    ensure_config_dir()
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)


def get_config_val(key: str, default: Any = None) -> Any:
    """Get a single configuration value."""
    cfg = load_config()
    return cfg.get(key, default)


def set_config_val(key: str, val: Any) -> None:
    """Set a single configuration value and persist to disk."""
    cfg = load_config()
    cfg[key] = val
    save_config(cfg)
