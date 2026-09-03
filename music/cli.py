"""Main CLI entrypoint for music-cli."""

import argparse
import sys
from typing import List, Optional

from rich.console import Console
from rich.table import Table

from music.auth import (
    GOOGLE_LOGIN_URL,
    SUPPORTED_BROWSERS,
    get_auth_status,
    login_cookies_file,
    logout,
    open_login_hyperlink,
    run_interactive_login,
    set_browser_login,
)
from music.config import get_config_val, load_config, set_config_val
from music.history import clear_history, get_history
from music.player import MpvPlayer
from music.search import (
    is_playlist_url,
    is_youtube_url,
    get_playlist_tracks,
    resolve_direct_item,
    search_music,
    search_playlists,
)
from music.ui import prompt_playlist_selection, prompt_song_selection, run_player_loop

console = Console()


def handle_playlist_query(
    query: str,
    select_track: bool = False,
    shuffle: bool = False,
    autoplay: Optional[bool] = None,
    ad_blocker: Optional[bool] = None,
    show_lyrics: Optional[bool] = None,
) -> None:
    """Search for or load a playlist, prompt track selection if requested, and stream."""
    import random

    clean_q = query.strip()
    p_item = None
    tracks = []

    if is_playlist_url(clean_q):
        console.print("[cyan]Loading playlist from URL...[/cyan]")
        p_item, tracks = get_playlist_tracks(clean_q)
    else:
        console.print(f"[cyan]Searching YouTube Music for playlists:[/cyan] [bold white]{clean_q}[/bold white]...")
        results = search_playlists(clean_q, limit=6)
        if not results:
            console.print("[red]No playlists found matching your query.[/red]")
            return

        selected_playlist = prompt_playlist_selection(results)
        if not selected_playlist:
            return

        console.print(f"[cyan]Fetching tracks for:[/cyan] [bold white]{selected_playlist.title}[/bold white]...")
        p_item, tracks = get_playlist_tracks(selected_playlist.playlist_id)

    if not tracks:
        console.print("[red]No playable tracks found in playlist.[/red]")
        return

    p_title = p_item.title if p_item else "Playlist"
    console.print(f"[green]✓ Loaded playlist:[/green] [bold white]{p_title}[/bold white] ([cyan]{len(tracks)} tracks[/cyan])")

    if shuffle:
        console.print("[dim]🔀 Shuffling tracks...[/dim]")
        random.shuffle(tracks)

    if select_track:
        start_song = prompt_song_selection(tracks)
        if not start_song:
            return
        idx = tracks.index(start_song)
        initial_queue = tracks[idx + 1:]
    else:
        start_song = tracks[0]
        initial_queue = tracks[1:]

    vol = get_config_val("volume", 80)
    player = MpvPlayer(initial_volume=vol)
    run_player_loop(
        start_song,
        player,
        autoplay=autoplay,
        ad_blocker=ad_blocker,
        show_lyrics=show_lyrics,
        initial_queue=initial_queue,
        playlist_name=p_title,
    )


def handle_play_query(
    query: str,
    select_menu: bool = False,
    autoplay: Optional[bool] = None,
    ad_blocker: Optional[bool] = None,
    show_lyrics: Optional[bool] = None,
) -> None:
    """Search for query and start playback."""
    if is_playlist_url(query):
        handle_playlist_query(
            query,
            select_track=select_menu,
            autoplay=autoplay,
            ad_blocker=ad_blocker,
            show_lyrics=show_lyrics,
        )
        return

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
    run_player_loop(
        selected_song,
        player,
        autoplay=autoplay,
        ad_blocker=ad_blocker,
        show_lyrics=show_lyrics,
    )


def handle_login(args: argparse.Namespace) -> None:
    """Handle login and authentication configuration."""
    if args.status:
        status = get_auth_status()
        table = Table(title="[bold cyan]Authentication Status[/bold cyan]", border_style="cyan")
        table.add_column("Property", style="bold yellow")
        table.add_column("Value", style="white")

        table.add_row("Mode", status["mode"].capitalize())
        table.add_row("Status", status["description"])
        table.add_row("Account", status.get("email", "(None)"))
        table.add_row("Ad-Free Playback", status["ad_free"])
        if "browser" in status:
            table.add_row("Browser", status["browser"].capitalize())
        if "profile" in status and status["profile"]:
            table.add_row("Profile", status["profile"])
        if "file" in status:
            table.add_row("Cookies File", status["file"])
        console.print(table)
        return

    if args.logout:
        _, msg = logout()
        console.print(f"[yellow]{msg}[/yellow]")
        return

    if getattr(args, "open", False):
        console.print("[cyan]Opening Google Account Chooser in browser...[/cyan]")
        open_login_hyperlink()
        return

    if args.cookies:
        console.print(f"[cyan]Importing cookies from {args.cookies}...[/cyan]")
        ok, msg = login_cookies_file(args.cookies)
        if ok:
            console.print(f"[bold green]✓ {msg}[/bold green]")
        else:
            console.print(f"[bold red]✗ {msg}[/bold red]")
        return

    # Run interactive login with hyperlink and account chooser
    run_interactive_login()


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
    subcommands = {"login", "logout", "config", "history", "search", "play", "url", "playlist", "help"}

    if raw_args and not raw_args[0].startswith("-") and raw_args[0] not in subcommands:
        # Separate optional flags like -s / --select, --no-autoplay, --autoplay, --no-adblock, --adblock, --no-lyrics, --lyrics, --shuffle
        select_menu = False
        autoplay = None
        ad_blocker = None
        show_lyrics = None
        shuffle = False
        words = []
        for a in raw_args:
            if a in ("-s", "--select"):
                select_menu = True
            elif a == "--no-autoplay":
                autoplay = False
            elif a == "--autoplay":
                autoplay = True
            elif a == "--no-adblock":
                ad_blocker = False
            elif a == "--adblock":
                ad_blocker = True
            elif a == "--no-lyrics":
                show_lyrics = False
            elif a == "--lyrics":
                show_lyrics = True
            elif a in ("--shuffle",):
                shuffle = True
            else:
                words.append(a)
        query = " ".join(words).strip()
        if query:
            if is_playlist_url(query):
                handle_playlist_query(
                    query,
                    select_track=select_menu,
                    shuffle=shuffle,
                    autoplay=autoplay,
                    ad_blocker=ad_blocker,
                    show_lyrics=show_lyrics,
                )
            else:
                handle_play_query(
                    query,
                    select_menu=select_menu,
                    autoplay=autoplay,
                    ad_blocker=ad_blocker,
                    show_lyrics=show_lyrics,
                )
            return

    parser = argparse.ArgumentParser(
        prog="music",
        description="Stream music directly from YouTube Music in your terminal.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  music "Never Gonna Give You Up"          # Play top match with synced lyrics & autoplay
  music "Bohemian Rhapsody" -s             # Show search results list to pick from
  music playlist "Lofi Hip Hop"            # Search and play a selected playlist
  music playlist "Synthwave" --shuffle     # Play a playlist shuffled
  music url "https://music.youtube.com/..." # Stream direct song or playlist URL
  music login                              # Interactive login (hyperlink & account selector)
  music history                            # View and replay recently played songs
        """,
    )

    subparsers = parser.add_subparsers(dest="command")

    # play / search subcommand
    p_play = subparsers.add_parser("play", help="Search and stream a track")
    p_play.add_argument("query", nargs="+", help="Song title or query to search")
    p_play.add_argument("-s", "--select", action="store_true", help="Show interactive search picker")
    p_play.add_argument("--no-autoplay", action="store_true", help="Disable autoplay for this session")
    p_play.add_argument("--autoplay", action="store_true", help="Force enable autoplay for this session")
    p_play.add_argument("--no-adblock", action="store_true", help="Disable ad & sponsor blocking")
    p_play.add_argument("--adblock", action="store_true", help="Force enable ad & sponsor blocking")
    p_play.add_argument("--no-lyrics", action="store_true", help="Disable synced lyrics display")
    p_play.add_argument("--lyrics", action="store_true", help="Force enable synced lyrics display")

    p_search = subparsers.add_parser("search", help="Search YouTube Music and select from list")
    p_search.add_argument("query", nargs="+", help="Song or playlist query to search")
    p_search.add_argument("-p", "--playlist", action="store_true", help="Search for playlists instead of individual tracks")
    p_search.add_argument("--no-autoplay", action="store_true", help="Disable autoplay for this session")
    p_search.add_argument("--autoplay", action="store_true", help="Force enable autoplay for this session")
    p_search.add_argument("--no-adblock", action="store_true", help="Disable ad & sponsor blocking")
    p_search.add_argument("--adblock", action="store_true", help="Force enable ad & sponsor blocking")
    p_search.add_argument("--no-lyrics", action="store_true", help="Disable synced lyrics display")
    p_search.add_argument("--lyrics", action="store_true", help="Force enable synced lyrics display")

    # playlist subcommand
    p_plist = subparsers.add_parser("playlist", help="Search or stream a selected playlist")
    p_plist.add_argument("query", nargs="+", help="Playlist name or direct playlist URL")
    p_plist.add_argument("-s", "--select", action="store_true", help="Select starting track from playlist table")
    p_plist.add_argument("--shuffle", action="store_true", help="Shuffle playlist tracks")
    p_plist.add_argument("--no-autoplay", action="store_true", help="Stop playback when playlist ends")
    p_plist.add_argument("--autoplay", action="store_true", help="Continue radio after playlist ends")
    p_plist.add_argument("--no-adblock", action="store_true", help="Disable ad & sponsor blocking")
    p_plist.add_argument("--adblock", action="store_true", help="Force enable ad & sponsor blocking")
    p_plist.add_argument("--no-lyrics", action="store_true", help="Disable synced lyrics display")
    p_plist.add_argument("--lyrics", action="store_true", help="Force enable synced lyrics display")

    p_url = subparsers.add_parser("url", help="Stream direct YouTube / YouTube Music URL")
    p_url.add_argument("url", help="Direct YouTube or YouTube Music song/playlist URL")
    p_url.add_argument("--no-autoplay", action="store_true", help="Disable autoplay for this session")
    p_url.add_argument("--autoplay", action="store_true", help="Force enable autoplay for this session")
    p_url.add_argument("--no-adblock", action="store_true", help="Disable ad & sponsor blocking")
    p_url.add_argument("--adblock", action="store_true", help="Force enable ad & sponsor blocking")
    p_url.add_argument("--no-lyrics", action="store_true", help="Disable synced lyrics display")
    p_url.add_argument("--lyrics", action="store_true", help="Force enable synced lyrics display")

    # login subcommand
    p_login = subparsers.add_parser("login", help="Configure YouTube authentication (skip ads)")
    p_login.add_argument("--open", action="store_true", help="Open Google login link directly in browser")
    p_login.add_argument("--browser", choices=SUPPORTED_BROWSERS, help="Extract cookies from browser")
    p_login.add_argument("--cookies", help="Path to Netscape cookies.txt file")
    p_login.add_argument("--status", action="store_true", help="Show current authentication status")
    p_login.add_argument("--logout", action="store_true", help="Log out and return to guest mode")

    # logout subcommand (convenience shortcut for music login --logout)
    subparsers.add_parser("logout", help="Log out and return to standard guest mode")

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

    if args.command == "playlist":
        query = " ".join(args.query).strip()
        select_track = getattr(args, "select", False)
        shuf = getattr(args, "shuffle", False)
        ap = False if getattr(args, "no_autoplay", False) else (True if getattr(args, "autoplay", False) else None)
        adb = False if getattr(args, "no_adblock", False) else (True if getattr(args, "adblock", False) else None)
        lyr = False if getattr(args, "no_lyrics", False) else (True if getattr(args, "lyrics", False) else None)
        handle_playlist_query(
            query,
            select_track=select_track,
            shuffle=shuf,
            autoplay=ap,
            ad_blocker=adb,
            show_lyrics=lyr,
        )
    elif args.command in ("play", "search"):
        query = " ".join(args.query).strip()
        select_menu = getattr(args, "select", False) or args.command == "search"
        ap = False if getattr(args, "no_autoplay", False) else (True if getattr(args, "autoplay", False) else None)
        adb = False if getattr(args, "no_adblock", False) else (True if getattr(args, "adblock", False) else None)
        lyr = False if getattr(args, "no_lyrics", False) else (True if getattr(args, "lyrics", False) else None)
        if getattr(args, "playlist", False) or is_playlist_url(query):
            handle_playlist_query(
                query,
                select_track=select_menu,
                autoplay=ap,
                ad_blocker=adb,
                show_lyrics=lyr,
            )
        else:
            handle_play_query(query, select_menu=select_menu, autoplay=ap, ad_blocker=adb, show_lyrics=lyr)
    elif args.command == "url":
        ap = False if getattr(args, "no_autoplay", False) else (True if getattr(args, "autoplay", False) else None)
        adb = False if getattr(args, "no_adblock", False) else (True if getattr(args, "adblock", False) else None)
        lyr = False if getattr(args, "no_lyrics", False) else (True if getattr(args, "lyrics", False) else None)
        if is_playlist_url(args.url):
            handle_playlist_query(args.url, select_track=False, autoplay=ap, ad_blocker=adb, show_lyrics=lyr)
        else:
            handle_play_query(args.url, select_menu=False, autoplay=ap, ad_blocker=adb, show_lyrics=lyr)
    elif args.command == "login":
        handle_login(args)
    elif args.command == "logout":
        _, msg = logout()
        console.print(f"[yellow]{msg}[/yellow]")
    elif args.command == "history":
        handle_history(args)
    elif args.command == "config":
        handle_config(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
