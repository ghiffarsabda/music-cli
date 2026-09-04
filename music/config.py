"""Configuration manager for music-cli."""

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

CONFIG_DIR = Path.home() / ".config" / "music-cli"
CONFIG_FILE = CONFIG_DIR / "config.json"
COOKIES_FILE = CONFIG_DIR / "cookies.txt"
HISTORY_FILE = CONFIG_DIR / "history.json"
LIBRARY_DB = CONFIG_DIR / "library.db"


def _is_executable(path: str) -> bool:
    """Check if file exists and is executable."""
    if not path or not os.path.isfile(path):
        return False
    if sys.platform == "win32":
        return True
    return os.access(path, os.X_OK)


def detect_executable(name: str, fallback_paths: Optional[List[str]] = None) -> str:
    """Find the best available executable path."""
    found = shutil.which(name)
    if found:
        return found

    # Check same directory as sys.executable (e.g. active virtualenv bin/ or Scripts/)
    exe_dir = os.path.dirname(sys.executable)
    bin_names = [f"{name}.exe", name] if sys.platform == "win32" else [name]
    for n in bin_names:
        cand = os.path.join(exe_dir, n)
        if _is_executable(cand):
            return cand

    if fallback_paths:
        for p in fallback_paths:
            expanded = str(Path(p).expanduser())
            if _is_executable(expanded):
                return expanded
    return name


def find_ytdl_bin() -> str:
    """Find the best available yt-dlp executable path.

    Checks in priority order:
    1. User configured path in config.json (if it exists and is runnable)
    2. System PATH (shutil.which)
    3. Active Python environment's directory (virtualenv bin/ or Scripts/)
    4. Standard user install locations across OSes
    """
    cfg_val = get_config_val("yt_dlp_path", "")
    if cfg_val and cfg_val != "yt-dlp":
        if _is_executable(cfg_val):
            return cfg_val
        found = shutil.which(cfg_val)
        if found:
            return found

    # Check system PATH
    found = shutil.which("yt-dlp")
    if found:
        return found

    # Check active virtualenv / python Scripts directory
    exe_dir = os.path.dirname(sys.executable)
    names = ["yt-dlp.exe", "yt-dlp"] if sys.platform == "win32" else ["yt-dlp"]
    for n in names:
        cand = os.path.join(exe_dir, n)
        if _is_executable(cand):
            return cand

    # Check common system & user paths across OSes
    home = str(Path.home())
    candidates = [
        # Linux / macOS isolated venv
        os.path.join(home, ".local", "share", "music-cli", "venv", "bin", "yt-dlp"),
        os.path.join(home, ".local", "bin", "yt-dlp"),
        "/opt/homebrew/bin/yt-dlp",
        "/usr/local/bin/yt-dlp",
        "/usr/bin/yt-dlp",
        # Windows isolated venv and user paths
        os.path.expandvars(r"%LOCALAPPDATA%\music-cli\venv\Scripts\yt-dlp.exe"),
        os.path.expandvars(r"%USERPROFILE%\.local\bin\yt-dlp.exe"),
    ]
    for c in candidates:
        if _is_executable(c):
            return c

    return "yt-dlp"


def get_ytdl_cmd_prefix() -> List[str]:
    """Return command prefix to run yt-dlp.

    Returns:
        [path_to_yt_dlp] if a valid binary was found,
        otherwise [sys.executable, "-m", "yt_dlp"].
    """
    ytdl_bin = find_ytdl_bin()
    if ytdl_bin and ytdl_bin != "yt-dlp" and (_is_executable(ytdl_bin) or shutil.which(ytdl_bin)):
        return [ytdl_bin]
    if shutil.which("yt-dlp"):
        return ["yt-dlp"]
    return [sys.executable, "-m", "yt_dlp"]


def find_node_bin() -> str:
    """Find the best available node executable path."""
    cfg_val = get_config_val("node_path", "")
    if cfg_val and cfg_val != "node":
        if _is_executable(cfg_val):
            return cfg_val
        found = shutil.which(cfg_val)
        if found:
            return found

    found = shutil.which("node")
    if found:
        return found

    home = str(Path.home())
    candidates = [
        os.path.join(home, ".local", "bin", "node"),
        "/opt/homebrew/bin/node",
        "/usr/local/bin/node",
        "/usr/bin/node",
        os.path.expandvars(r"%ProgramFiles%\nodejs\node.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\node\node.exe"),
    ]
    for c in candidates:
        if _is_executable(c):
            return c

    return ""


DEFAULT_CONFIG: Dict[str, Any] = {
    "auth_mode": "none",  # 'none', 'browser', 'cookies_file'
    "browser": "chrome",  # 'chrome', 'firefox', 'brave', 'edge', etc.
    "profile": "",  # profile key e.g. 'Default', 'Profile 1'
    "account_email": "",
    "cookies_file": str(COOKIES_FILE),
    "volume": 100,
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
