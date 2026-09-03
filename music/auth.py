"""Authentication and cookie manager for YouTube Music streaming."""

import json
import os
import shutil
import subprocess
import webbrowser
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from music.config import COOKIES_FILE, get_config_val, load_config, set_config_val

console = Console()

GOOGLE_LOGIN_URL = "https://accounts.google.com/AccountChooser?continue=https://music.youtube.com"

SUPPORTED_BROWSERS = [
    "chrome",
    "firefox",
    "brave",
    "edge",
    "chromium",
    "opera",
    "vivaldi",
]


def detect_browser_profiles() -> List[Dict[str, str]]:
    """Detect available Google/browser accounts across installed browsers."""
    browser_dirs = {
        "chrome": Path.home() / ".config" / "google-chrome",
        "chromium": Path.home() / ".config" / "chromium",
        "brave": Path.home() / ".config" / "BraveSoftware" / "Brave-Browser",
        "edge": Path.home() / ".config" / "microsoft-edge",
    }

    profiles: List[Dict[str, str]] = []

    for b_name, b_dir in browser_dirs.items():
        local_state = b_dir / "Local State"
        if local_state.exists():
            try:
                with open(local_state, "r", encoding="utf-8") as f:
                    data = json.load(f)
                info = data.get("profile", {}).get("info_cache", {})
                for key, val in info.items():
                    name = val.get("name", "Profile")
                    email = val.get("user_name", "")
                    profiles.append(
                        {
                            "browser": b_name,
                            "profile_key": key,
                            "name": name,
                            "email": email or "(No email specified)",
                        }
                    )
            except Exception:
                pass

    return profiles


def get_browser_specifier() -> str:
    """Return browser:profile string for yt-dlp/mpv."""
    cfg = load_config()
    browser = cfg.get("browser", "chrome")
    profile = cfg.get("profile", "")
    if profile:
        return f"{browser}:{profile}"
    return browser


def get_ytdl_auth_args() -> List[str]:
    """Return command line arguments for yt-dlp based on current authentication mode."""
    cfg = load_config()
    mode = cfg.get("auth_mode", "none")

    if mode in ("browser", "cookies_file"):
        cfile = cfg.get("cookies_file", str(COOKIES_FILE))
        if os.path.isfile(cfile) and os.path.getsize(cfile) > 0:
            return ["--cookies", cfile]
        if mode == "browser":
            spec = get_browser_specifier()
            return ["--cookies-from-browser", spec]
    return []


def get_mpv_auth_args() -> List[str]:
    """Return command line arguments for mpv based on current authentication mode."""
    cfg = load_config()
    mode = cfg.get("auth_mode", "none")

    if mode in ("browser", "cookies_file"):
        cfile = cfg.get("cookies_file", str(COOKIES_FILE))
        if os.path.isfile(cfile) and os.path.getsize(cfile) > 0:
            return [f"--ytdl-raw-options-append=cookies={cfile}"]
        if mode == "browser":
            spec = get_browser_specifier()
            return [f"--ytdl-raw-options-append=cookies-from-browser={spec}"]
    return []


def export_browser_cookies(browser_name: str, profile_key: str = "") -> bool:
    """Export browser cookies once into cookies.txt for fast, lock-free streaming."""
    yt_dlp = get_config_val("yt_dlp_path", "yt-dlp")
    node_bin = get_config_val("node_path", "node")
    spec = f"{browser_name}:{profile_key}" if profile_key else browser_name

    cmd = [
        yt_dlp,
        "--js-runtimes",
        f"node:{node_bin}",
        "--remote-components",
        "ejs:github",
        "--cookies-from-browser",
        spec,
        "--cookies",
        str(COOKIES_FILE),
        "--simulate",
        "--no-warnings",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=25)
        return proc.returncode == 0 and COOKIES_FILE.exists() and COOKIES_FILE.stat().st_size > 0
    except Exception:
        return False


def set_browser_login(browser_name: str, profile_key: str = "", email: str = "") -> Tuple[bool, str]:
    """Set authentication via browser and optional profile, exporting cookies for speed."""
    b_clean = browser_name.lower().strip()
    if b_clean not in SUPPORTED_BROWSERS:
        return (
            False,
            f"Unsupported browser '{browser_name}'. Supported: {', '.join(SUPPORTED_BROWSERS)}",
        )

    # Export cookies once to eliminate SQLite lock delays and SecretStorage hangs during playback
    console.print(f"[cyan]Exporting session cookies from {b_clean} for fast playback...[/cyan]")
    export_browser_cookies(b_clean, profile_key)

    set_config_val("auth_mode", "browser")
    set_config_val("browser", b_clean)
    set_config_val("profile", profile_key)
    set_config_val("account_email", email)
    set_config_val("cookies_file", str(COOKIES_FILE))

    display_acc = f" ({email})" if email else ""
    display_prof = f" [{profile_key}]" if profile_key else ""
    return True, f"Successfully connected to {b_clean.capitalize()}{display_prof}{display_acc}!"


def login_cookies_file(cookies_path: str) -> Tuple[bool, str]:
    """Set authentication via Netscape cookies.txt file."""
    src = Path(cookies_path).expanduser().resolve()
    if not src.is_file():
        return False, f"Cookies file not found at: {src}"

    try:
        dest = COOKIES_FILE
        shutil.copyfile(src, dest)
        dest.chmod(0o600)
    except Exception as e:
        return False, f"Failed to copy cookies file: {e}"

    set_config_val("auth_mode", "cookies_file")
    set_config_val("cookies_file", str(dest))
    set_config_val("account_email", "cookies.txt session")
    return True, "Successfully loaded cookies.txt! YouTube Premium ads will be skipped."


def logout() -> Tuple[bool, str]:
    """Log out and revert to standard guest mode."""
    set_config_val("auth_mode", "none")
    set_config_val("profile", "")
    set_config_val("account_email", "")
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
        profile = cfg.get("profile", "")
        email = cfg.get("account_email", "")
        desc = f"Authenticated via {browser.capitalize()}"
        if profile:
            desc += f" (Profile: {profile})"
        if email:
            desc += f" - {email}"

        return {
            "mode": "browser",
            "browser": browser,
            "profile": profile or "Default",
            "email": email or "(Not recorded)",
            "description": desc,
            "ad_free": "Yes (Ad-Free / YouTube Premium active if account subscribed)",
        }
    elif mode == "cookies_file":
        cfile = cfg.get("cookies_file", str(COOKIES_FILE))
        return {
            "mode": "cookies_file",
            "file": cfile,
            "email": "cookies.txt",
            "description": f"Authenticated via cookies file ({cfile})",
            "ad_free": "Yes (Ad-Free / YouTube Premium active if account subscribed)",
        }
    else:
        return {
            "mode": "none",
            "email": "(None)",
            "description": "Guest / Standard mode (no account logged in)",
            "ad_free": "No (Standard public playback)",
        }


def open_login_hyperlink() -> bool:
    """Open the Google Account Chooser link in default web browser."""
    try:
        webbrowser.open(GOOGLE_LOGIN_URL)
        return True
    except Exception:
        return False


def run_interactive_login() -> None:
    """Interactive login workflow featuring hyperlink and multi-account selection."""
    profiles = detect_browser_profiles()

    table = Table(
        title="[bold cyan]Detected Google Accounts (from installed browsers)[/bold cyan]",
        border_style="cyan",
        show_lines=False,
    )
    table.add_column("#", style="bold yellow", width=4, justify="right")
    table.add_column("Account / Email", style="bold white", min_width=28)
    table.add_column("Profile Name", style="cyan", min_width=18)
    table.add_column("Browser", style="dim", min_width=10)

    for idx, p in enumerate(profiles, 1):
        table.add_row(
            str(idx),
            p["email"],
            p["name"],
            f"{p['browser'].capitalize()} ({p['profile_key']})",
        )

    link_markup = f"[link={GOOGLE_LOGIN_URL}][bold underline bright_blue]{GOOGLE_LOGIN_URL}[/bold underline bright_blue][/link]"

    login_panel = Panel(
        f"[bold white]1. Click the login link below (or press [bold green]'o'[/bold green] to open it in your browser):[/bold white]\n"
        f"   🔗 {link_markup}\n\n"
        f"[dim]Google will present your Google accounts. Sign in or pick the account that has YouTube Music / Premium.[/dim]\n\n"
        f"[bold white]2. Then select which Google account below to use for Music CLI:[/bold white]",
        title="[bold bright_green]YouTube Music Login[/bold bright_green]",
        border_style="bright_blue",
    )

    console.print()
    console.print(login_panel)
    console.print()

    if profiles:
        console.print(table)
        console.print()

    console.print("[bold cyan]Commands:[/bold cyan]")
    if profiles:
        console.print(f"  [bold yellow]1-{len(profiles)}[/bold yellow] : Select an account from the list above")
    console.print("  [bold green]o[/bold green]   : Open the Google Account Chooser link in your web browser")
    console.print("  [bold green]c[/bold green]   : Import cookies from a cookies.txt file")
    console.print("  [bold green]s[/bold green]   : View current authentication status")
    console.print("  [bold red]q[/bold red]   : Cancel / Exit")
    console.print()

    while True:
        try:
            choice = input("Enter choice: ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[yellow]Login cancelled.[/yellow]")
            return

        if not choice or choice in ("q", "quit", "exit"):
            console.print("[yellow]Login cancelled.[/yellow]")
            return

        if choice in ("o", "open"):
            console.print("[cyan]Opening Google Account Chooser in your browser...[/cyan]")
            open_login_hyperlink()
            console.print(f"[dim]Link opened: {GOOGLE_LOGIN_URL}[/dim]")
            console.print("[dim]After signing in or selecting your account, choose its number from the list above:[/dim]")
            continue

        if choice in ("s", "status"):
            st = get_auth_status()
            console.print(f"[green]Current status:[/green] {st['description']}")
            continue

        if choice in ("c", "cookies"):
            path = input("Enter path to cookies.txt: ").strip()
            if path:
                ok, msg = login_cookies_file(path)
                if ok:
                    console.print(f"[bold green]✓ {msg}[/bold green]")
                else:
                    console.print(f"[bold red]✗ {msg}[/bold red]")
                return

        # Check numeric selection
        try:
            idx = int(choice)
            if 1 <= idx <= len(profiles):
                selected = profiles[idx - 1]
                ok, msg = set_browser_login(
                    browser_name=selected["browser"],
                    profile_key=selected["profile_key"],
                    email=selected["email"],
                )
                if ok:
                    console.print(f"\n[bold green]✓ {msg}[/bold green]")
                    console.print("[dim]YouTube Music will now stream using this account session.[/dim]\n")
                else:
                    console.print(f"\n[bold red]✗ {msg}[/bold red]\n")
                return
        except ValueError:
            pass

        console.print("[yellow]Invalid choice. Please choose an account number, 'o' to open browser, or 'q' to quit.[/yellow]")
