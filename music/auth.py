"""Authentication and cookie manager for YouTube Music streaming."""

import os
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Tuple

from music.config import COOKIES_FILE, get_config_val, load_config, set_config_val


SUPPORTED_BROWSERS = [
    "chrome",
    "firefox",
    "brave",
    "edge",
    "chromium",
    "opera",
    "vivaldi",
]


def get_ytdl_auth_args() -> List[str]:
    """Return command line arguments for yt-dlp based on current authentication mode."""
    cfg = load_config()
    mode = cfg.get("auth_mode", "none")

    if mode == "browser":
        browser = cfg.get("browser", "chrome")
        return ["--cookies-from-browser", browser]
    elif mode == "cookies_file":
        cfile = cfg.get("cookies_file", str(COOKIES_FILE))
        if os.path.isfile(cfile):
            return ["--cookies", cfile]
    return []


def get_mpv_auth_args() -> List[str]:
    """Return command line arguments for mpv based on current authentication mode."""
    cfg = load_config()
    mode = cfg.get("auth_mode", "none")

    if mode == "browser":
        browser = cfg.get("browser", "chrome")
        return [f"--ytdl-raw-options-append=cookies-from-browser={browser}"]
    elif mode == "cookies_file":
        cfile = cfg.get("cookies_file", str(COOKIES_FILE))
        if os.path.isfile(cfile):
            return [f"--ytdl-raw-options-append=cookies={cfile}"]
    return []


def test_auth_options(auth_args: List[str]) -> Tuple[bool, str]:
    """Test whether authentication options work with YouTube."""
    yt_dlp = get_config_val("yt_dlp_path", "yt-dlp")
    cmd = [
        yt_dlp,
        *auth_args,
        "--simulate",
        "--no-warnings",
        "--print",
        "title",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    ]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if proc.returncode == 0:
            return True, "Authentication verified successfully!"
        err = proc.stderr.strip()
        if "could not find" in err.lower() or "database is locked" in err.lower():
            return False, f"Could not read browser cookies: {err}"
        return False, f"Verification failed: {err}"
    except subprocess.TimeoutExpired:
        return False, "Verification timed out connecting to YouTube."
    except Exception as e:
        return False, f"Error running verification: {e}"


def login_browser(browser_name: str) -> Tuple[bool, str]:
    """Set authentication via browser cookie extraction."""
    b_clean = browser_name.lower().strip()
    if b_clean not in SUPPORTED_BROWSERS:
        return (
            False,
            f"Unsupported browser '{browser_name}'. Supported: {', '.join(SUPPORTED_BROWSERS)}",
        )

    auth_args = ["--cookies-from-browser", b_clean]
    ok, msg = test_auth_options(auth_args)
    if not ok:
        # Check if browser is running or cookies locked
        return False, (
            f"Failed to extract cookies from {b_clean}.\n"
            f"Details: {msg}\n"
            f"Tip: If {b_clean} is currently open, try closing it or use an exported cookies.txt file."
        )

    set_config_val("auth_mode", "browser")
    set_config_val("browser", b_clean)
    return True, f"Successfully authenticated with {b_clean} cookies! YouTube Premium ads will be skipped."


def login_cookies_file(cookies_path: str) -> Tuple[bool, str]:
    """Set authentication via Netscape cookies.txt file."""
    src = Path(cookies_path).expanduser().resolve()
    if not src.is_file():
        return False, f"Cookies file not found at: {src}"

    try:
        # Copy to config dir
        dest = COOKIES_FILE
        shutil.copyfile(src, dest)
        dest.chmod(0o600)  # Secure permission
    except Exception as e:
        return False, f"Failed to copy cookies file: {e}"

    auth_args = ["--cookies", str(dest)]
    ok, msg = test_auth_options(auth_args)
    if not ok:
        return False, f"Cookies file verification failed: {msg}"

    set_config_val("auth_mode", "cookies_file")
    set_config_val("cookies_file", str(dest))
    return True, "Successfully loaded cookies.txt! YouTube Premium ads will be skipped."


def logout() -> Tuple[bool, str]:
    """Log out and revert to standard guest mode."""
    set_config_val("auth_mode", "none")
    if COOKIES_FILE.exists():
        try:
            COOKIES_FILE.unlink()
        except OSError:
            pass
    return True, "Logged out. music-cli is now running in standard guest mode."


def get_auth_status() -> Dict[str, str]:
    """Return dictionary with human-readable auth status."""
    cfg = load_config()
    mode = cfg.get("auth_mode", "none")

    if mode == "browser":
        browser = cfg.get("browser", "chrome")
        return {
            "mode": "browser",
            "browser": browser,
            "description": f"Authenticated via {browser.capitalize()} browser cookies",
            "ad_free": "Yes (Premium active if your account is subscribed)",
        }
    elif mode == "cookies_file":
        cfile = cfg.get("cookies_file", str(COOKIES_FILE))
        return {
            "mode": "cookies_file",
            "file": cfile,
            "description": f"Authenticated via cookies file ({cfile})",
            "ad_free": "Yes (Premium active if your account is subscribed)",
        }
    else:
        return {
            "mode": "none",
            "description": "Guest / Standard mode (no account logged in)",
            "ad_free": "No (Standard public playback)",
        }
