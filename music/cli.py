"""Main CLI entrypoint for music-cli."""

import argparse
import sys
from typing import List, Optional

from rich.console import Console
from rich.table import Table

from music.auth import (
    SUPPORTED_BROWSERS,
    get_auth_status,
    login_browser,
    login_cookies_file,
    logout,
)
from music.config import get_config_val, load_config, set_config_val
from music.history import clear_history, get_history
from music.player import MpvPlayer
from music.search import is_youtube_url, resolve_direct_item, search_music
from music.ui import prompt_song_selection, run_player_loop

console = Console()


def handle_play_query(query: str, select_menu: bool = False) -> None:
    """Search for query and start playback."""
    if is_youtube_url(query):
        console.print(f"[cyan]Resolving direct YouTube link...[/cyan]")
        item = resolve_direct_item(query)
        if not item:
            console.print("[red]Could not load track from specified URL.[/red]")
            return
        selected_song = item
    else:
        console.print(f"[cyan]Searching YouTube Music for:[/cyan] [bold white]{query}[/bold white]...")
        results = search_music(query, limit=5)
        if not results:
            console.print("[red]No tracks found matching your query.[/red]")
            return

        if select_menu:
            selected_song = prompt_song_selection(results)
            if not selected_song:
                return
        else:
            selected_song = results[0]

    vol = get_config_val("volume", 80)
    player = MpvPlayer(initial_volume=vol)
    run_player_loop(selected_song, player)


def handle_login(args: argparse.Namespace) -> None:
    """Handle login and authentication configuration."""
    if args.status:
        status = get_auth_status()
        table = Table(title="[bold cyan]Authentication Status[/bold cyan]", border_style="cyan")
        table.add_column("Property", style="bold yellow")
        table.add_column("Value", style="white")

        table.add_row("Mode", status["mode"].capitalize())
        table.add_row("Status", status["description"])
        table.add_row("Ad-Free Playback", status["ad_free"])
        if "browser" in status:
            table.add_row("Browser", status["browser"].capitalize())
        if "file" in status:
            table.add_row("Cookies File", status["file"])
        console.print(table)
        return

    if args.logout:
        _, msg = logout()
        console.print(f"[yellow]{msg}[/yellow]")
        return

    if args.browser:
        console.print(f"[cyan]Extracting session cookies from {args.browser}...[/cyan]")
        ok, msg = login_browser(args.browser)
        if ok:
            console.print(f"[bold green]✓ {msg}[/bold green]")
        else:
            console.print(f"[bold red]✗ {msg}[/bold red]")
        return

    if args.cookies:
        console.print(f"[cyan]Importing cookies from {args.cookies}...[/cyan]")
        ok, msg = login_cookies_file(args.cookies)
        if ok:
            console.print(f"[bold green]✓ {msg}[/bold green]")
        else:
            console.print(f"[bold red]✗ {msg}[/bold red]")
        return

    # If no flags passed to login, show interactive guide
    console.print("[bold cyan]YouTube Music Account Login[/bold cyan]")
    console.print(
        "Logging in allows you to use your YouTube Music / Premium account to skip ads and access full library."
    )
    console.print()
    console.print("Options:")
    console.print(f"  [bold green]1.[/bold green] Extract cookies from browser:")
    console.print(f"     [dim]music login --browser chrome[/dim]  (Supported: {', '.join(SUPPORTED_BROWSERS)})")
    console.print("  [bold green]2.[/bold green] Use an exported cookies.txt file:")
    console.print("     [dim]music login --cookies ~/Downloads/cookies.txt[/dim]")
    console.print("  [bold green]3.[/bold green] Check current status:")
    console.print("     [dim]music login --status[/dim]")
    console.print("  [bold green]4.[/bold green] Log out (guest mode):")
    console.print("     [dim]music login --logout[/dim]")


def handle_history(args: argparse.Namespace) -> None:
    """Show and replay from history."""
    if args.clear:
        clear_history()
        console.print("[green]Playback history cleared.[/green]")
        return

    history = get_history(limit=args.limit)
    if not history:
        console.print("[yellow]No recently played songs.[/yellow]")
        return

    table = Table(title="[bold cyan]Recently Played[/bold cyan]", border_style="cyan")
    table.add_column("#", style="bold yellow", width=4, justify="right")
    table.add_column("Title", style="bold white")
    table.add_column("Artist", style="cyan")
    table.add_column("Duration", style="green", justify="right")

    for idx, song in enumerate(history, 1):
        table.add_row(str(idx), song.title, song.artist, song.duration)

    console.print(table)
    console.print("[dim]Enter number to replay, or press Enter to exit:[/dim]")

    try:
        choice = input("> ").strip()
        if not choice:
            return
        idx = int(choice)
        if 1 <= idx <= len(history):
            vol = get_config_val("volume", 80)
            player = MpvPlayer(initial_volume=vol)
            run_player_loop(history[idx - 1], player)
    except (ValueError, KeyboardInterrupt, EOFError):
        pass


def handle_config(args: argparse.Namespace) -> None:
    """View or update configuration."""
    if args.action == "set" and args.key and args.val is not None:
        val = args.val
        if val.lower() in ("true", "yes", "1"):
            val = True
        elif val.lower() in ("false", "no", "0"):
            val = False
        elif val.isdigit():
            val = int(val)
        set_config_val(args.key, val)
        console.print(f"[green]Config updated:[/green] {args.key} = {val}")
        return

    cfg = load_config()
    table = Table(title="[bold cyan]Music CLI Configuration[/bold cyan]", border_style="cyan")
    table.add_column("Setting", style="bold yellow")
    table.add_column("Value", style="white")

    for k, v in cfg.items():
        table.add_row(k, str(v))

    console.print(table)


def main() -> None:
    """Main CLI entrypoint."""
    raw_args = sys.argv[1:]

    # Direct query convenience:
    # If the first argument is not a flag or recognized subcommand,
    # treat all non-flag arguments as a search query!
    subcommands = {"login", "config", "history", "search", "play", "url", "help"}

    if raw_args and not raw_args[0].startswith("-") and raw_args[0] not in subcommands:
        # Separate optional flags like -s / --select
        select_menu = False
        words = []
        for a in raw_args:
            if a in ("-s", "--select"):
                select_menu = True
            else:
                words.append(a)
        query = " ".join(words).strip()
        if query:
            handle_play_query(query, select_menu=select_menu)
            return

    parser = argparse.ArgumentParser(
        prog="music",
        description="Stream music directly from YouTube Music in your terminal.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  music "Never Gonna Give You Up"          # Play top match directly
  music "Bohemian Rhapsody" -s             # Show search results list to pick from
  music search "Daft Punk"                 # Interactive search menu
  music url "https://music.youtube.com/..." # Stream direct URL
  music login --browser chrome             # Authenticate with Chrome for YouTube Premium (no ads)
  music login --cookies cookies.txt        # Authenticate with cookies.txt
  music login --status                     # Check current login status
  music history                            # View and replay recently played songs
        """,
    )

    subparsers = parser.add_subparsers(dest="command")

    # play / search subcommand
    p_play = subparsers.add_parser("play", help="Search and stream a track")
    p_play.add_argument("query", nargs="+", help="Song title or query to search")
    p_play.add_argument("-s", "--select", action="store_true", help="Show interactive search picker")

    p_search = subparsers.add_parser("search", help="Search YouTube Music and select from list")
    p_search.add_argument("query", nargs="+", help="Song title or query to search")

    p_url = subparsers.add_parser("url", help="Stream direct YouTube / YouTube Music URL")
    p_url.add_argument("url", help="Direct YouTube or YouTube Music URL")

    # login subcommand
    p_login = subparsers.add_parser("login", help="Configure YouTube authentication (skip ads)")
    p_login.add_argument("--browser", choices=SUPPORTED_BROWSERS, help="Extract cookies from browser")
    p_login.add_argument("--cookies", help="Path to Netscape cookies.txt file")
    p_login.add_argument("--status", action="store_true", help="Show current authentication status")
    p_login.add_argument("--logout", action="store_true", help="Log out and return to guest mode")

    # history subcommand
    p_hist = subparsers.add_parser("history", help="Show recently played songs")
    p_hist.add_argument("-n", "--limit", type=int, default=15, help="Number of items to show")
    p_hist.add_argument("--clear", action="store_true", help="Clear playback history")

    # config subcommand
    p_cfg = subparsers.add_parser("config", help="View or update settings")
    p_cfg.add_argument("action", nargs="?", choices=["get", "set"], default="get")
    p_cfg.add_argument("key", nargs="?", help="Setting name")
    p_cfg.add_argument("val", nargs="?", help="Setting value")

    args = parser.parse_args(raw_args)

    if args.command in ("play", "search"):
        query = " ".join(args.query).strip()
        select_menu = getattr(args, "select", False) or args.command == "search"
        handle_play_query(query, select_menu=select_menu)
    elif args.command == "url":
        handle_play_query(args.url, select_menu=False)
    elif args.command == "login":
        handle_login(args)
    elif args.command == "history":
        handle_history(args)
    elif args.command == "config":
        handle_config(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
