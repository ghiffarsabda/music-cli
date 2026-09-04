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
from music.home import run_home_view
from music.player import MpvPlayer
from music.search import (
    extract_album_id,
    extract_playlist_id,
    get_album_tracks,
    get_playlist_tracks,
    is_album_url,
    is_playlist_url,
    is_youtube_url,
    resolve_direct_item,
    search_albums,
    search_music,
    search_playlists,
)
from music.ui import (
    prompt_album_selection,
    prompt_playlist_selection,
    prompt_song_selection,
    run_player_loop,
)

console = Console()


def handle_playlist_query(
    query: str,
    select_track: bool = False,
    shuffle: bool = False,
    autoplay: Optional[bool] = None,
    ad_blocker: Optional[bool] = None,
    show_lyrics: Optional[bool] = None,
    offline: bool = False,
) -> None:
    """Search for or load a playlist, prompt track selection if requested, and stream."""
    import random

    clean_q = query.strip()
    p_item = None
    tracks = []

    if offline:
        from music.offline import get_offline_collection_tracks, list_offline_collections
        col, tracks = get_offline_collection_tracks(clean_q)
        if not tracks:
            for p in list_offline_collections("playlist"):
                if clean_q.lower() in p["title"].lower():
                    col, tracks = get_offline_collection_tracks(p["id"])
                    break
        if not tracks:
            console.print(f"[red]No offline playlist found matching '{clean_q}'.[/red]")
            return
        p_title = col.get("title", "Offline Playlist") if col else "Offline Playlist"
        p_item = PlaylistItem(
            title=p_title,
            playlist_id=col.get("id", ""),
            author=col.get("author", "Offline Collection"),
            track_count=len(tracks),
            url="",
        )
    elif is_playlist_url(clean_q):
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

    vol = get_config_val("volume", 100)
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


def handle_album_query(
    query: str,
    select_track: bool = False,
    shuffle: bool = False,
    autoplay: Optional[bool] = None,
    ad_blocker: Optional[bool] = None,
    show_lyrics: Optional[bool] = None,
    offline: bool = False,
) -> None:
    """Search for or load an album, prompt track selection if requested, and stream."""
    clean = query.strip()
    album_id = extract_album_id(clean)
    album_item = None
    tracks: List[SongItem] = []

    if offline:
        from music.offline import get_offline_collection_tracks, list_offline_collections
        col, tracks = get_offline_collection_tracks(clean)
        if not tracks:
            for a in list_offline_collections("album"):
                if clean.lower() in a["title"].lower():
                    col, tracks = get_offline_collection_tracks(a["id"])
                    break
        if not tracks:
            console.print(f"[red]No offline album found matching '{clean}'.[/red]")
            return
        album_title = col.get("title", "Offline Album") if col else "Offline Album"
        album_item = AlbumItem(
            title=album_title,
            browse_id=col.get("id", ""),
            artist=col.get("author", "Offline Collection"),
            track_count=len(tracks),
        )
    elif album_id or clean.startswith("MPREb_"):
        with console.status(f"[bold cyan]Fetching album {clean}...[/bold cyan]"):
            album_item, tracks = get_album_tracks(album_id or clean)
    else:
        with console.status(f"[bold cyan]Searching albums for: {clean}...[/bold cyan]"):
            albums = search_albums(clean, limit=8)

        if not albums:
            console.print(f"[red]No albums found matching '{clean}'.[/red]")
            return

        if select_track and len(albums) > 1:
            album_item = prompt_album_selection(albums)
            if not album_item:
                return
        else:
            album_item = albums[0]

        with console.status(f"[bold cyan]Loading album tracks for '{album_item.title}'...[/bold cyan]"):
            _, tracks = get_album_tracks(album_item.browse_id)

    if not tracks:
        console.print(f"[red]No tracks found in album '{album_item.title if album_item else clean}'.[/red]")
        return

    if shuffle:
        import random
        random.shuffle(tracks)

    start_idx = 0
    if select_track and len(tracks) > 1:
        chosen_song = prompt_song_selection(tracks)
        if not chosen_song:
            return
        for i, t in enumerate(tracks):
            if t.video_id == chosen_song.video_id:
                start_idx = i
                break

    start_song = tracks[start_idx]
    initial_queue = tracks[start_idx + 1 :]
    vol = get_config_val("volume", 100)
    player = MpvPlayer(initial_volume=vol)
    album_title = album_item.title if album_item else "Album"

    run_player_loop(
        start_song,
        player,
        enable_autoplay=autoplay,
        enable_adblock=ad_blocker,
        enable_lyrics=show_lyrics,
        initial_queue=initial_queue,
        playlist_name=f"Album: {album_title}",
        playlist_pos=(start_idx + 1, len(tracks)),
    )


def handle_play_query(
    query: str,
    select_menu: bool = False,
    autoplay: Optional[bool] = None,
    ad_blocker: Optional[bool] = None,
    show_lyrics: Optional[bool] = None,
    offline: bool = False,
) -> None:
    """Search for query and start playback."""
    if offline:
        from music.offline import list_offline_tracks
        results = list_offline_tracks(query)
        if not results:
            console.print(f"[red]No offline downloaded tracks found matching '{query}'.[/red]")
            console.print("[dim]Tip: Use 'music download <song>' to download songs for offline playback.[/dim]")
            return
        if select_menu and len(results) > 1:
            selected_song = prompt_song_selection(results)
            if not selected_song:
                return
        else:
            selected_song = results[0]
        vol = get_config_val("volume", 100)
        player = MpvPlayer(initial_volume=vol)
        run_player_loop(
            selected_song,
            player,
            autoplay=autoplay,
            ad_blocker=ad_blocker,
            show_lyrics=show_lyrics,
        )
        return

    if is_playlist_url(query):
        handle_playlist_query(
            query,
            select_track=select_menu,
            autoplay=autoplay,
            ad_blocker=ad_blocker,
            show_lyrics=show_lyrics,
            offline=offline,
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

    vol = get_config_val("volume", 100)
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
            vol = get_config_val("volume", 100)
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


def handle_stop_playback() -> None:
    """Find and terminate any active music-cli mpv playback instances."""
    import glob
    import os
    import signal
    import subprocess

    killed_count = 0
    # 1. Terminate any mpv process referencing music_cli
    try:
        proc = subprocess.run(["pgrep", "-f", "mpv.*music_cli"], capture_output=True, text=True)
        if proc.returncode == 0:
            for pid_str in proc.stdout.split():
                if pid_str.isdigit():
                    try:
                        os.kill(int(pid_str), signal.SIGTERM)
                        killed_count += 1
                    except OSError:
                        pass
    except Exception:
        pass

    # 2. Clean up any leftover IPC sockets in /tmp
    for sock in glob.glob("/tmp/music_cli_*.sock"):
        try:
            os.remove(sock)
        except OSError:
            pass

    if killed_count > 0:
        console.print(f"[bold green]✓ Stopped {killed_count} active playback process(es).[/bold green]")
    else:
        console.print("[yellow]No active background music playback found.[/yellow]")


def handle_download(args: argparse.Namespace) -> None:
    """Download songs, playlists, or albums to local storage for 100% offline playback."""
    from music.offline import (
        download_album_by_query,
        download_playlist_by_query,
        download_song,
        is_track_offline,
    )

    query_parts = list(args.query) if getattr(args, "query", None) else []
    if not query_parts:
        console.print("[red]Please specify a song, playlist, or album to download.[/red]")
        return

    first = query_parts[0].lower()
    is_pl = getattr(args, "playlist", False)
    is_alb = getattr(args, "album", False)
    select_menu = getattr(args, "select", False)

    if first in ("playlist", "pl") and len(query_parts) > 1:
        is_pl = True
        query_parts = query_parts[1:]
    elif first in ("album", "alb") and len(query_parts) > 1:
        is_alb = True
        query_parts = query_parts[1:]
    elif first in ("song", "track") and len(query_parts) > 1:
        query_parts = query_parts[1:]

    raw_query = " ".join(query_parts).strip()

    if is_pl or is_playlist_url(raw_query):
        download_playlist_by_query(raw_query, console=console)
        return

    if is_alb or is_album_url(raw_query):
        download_album_by_query(raw_query, console=console)
        return

    if is_youtube_url(raw_query):
        console.print("[cyan]Resolving direct track URL...[/cyan]")
        song = resolve_direct_item(raw_query)
        if not song:
            console.print("[red]Could not resolve track URL.[/red]")
            return
    else:
        console.print(f"[cyan]Searching for:[/cyan] [bold white]{raw_query}[/bold white]...")
        results = search_music(raw_query, limit=5)
        if not results:
            console.print(f"[red]No tracks found matching '{raw_query}'.[/red]")
            return

        if select_menu:
            song = prompt_song_selection(results)
            if not song:
                return
        else:
            song = results[0]

    if is_track_offline(song.video_id):
        console.print(f"[yellow]Track is already downloaded locally:[/yellow] [bold white]{song.title}[/bold white]")
        return

    with console.status(f"[bold cyan]Downloading '{song.title}' for offline playback...[/bold cyan]"):
        ok, msg, fpath = download_song(song, console=console, show_status=False)

    if ok:
        console.print(f"[bold green]{msg}[/bold green]")
        console.print(f"[dim]Saved to: {fpath}[/dim]")
    else:
        console.print(f"[bold red]{msg}[/bold red]")


def handle_offline(args: argparse.Namespace) -> None:
    """Manage, list, and play offline downloaded songs and collections."""
    from rich import box
    from music.offline import (
        clear_all_offline_data,
        delete_offline_collection,
        delete_offline_track,
        get_offline_collection_tracks,
        get_offline_stats,
        list_offline_collections,
        list_offline_tracks,
    )

    action = getattr(args, "action", "list") or "list"
    target_words = getattr(args, "target", [])
    target = " ".join(target_words).strip() if target_words else ""

    if action == "status":
        stats = get_offline_stats()
        table = Table(title="[bold cyan]Offline Music Storage Status[/bold cyan]", border_style="cyan")
        table.add_column("Property", style="bold yellow")
        table.add_column("Value", style="white")
        table.add_row("Total Downloaded Tracks", str(stats["total_tracks"]))
        table.add_row("Total Playlists", str(stats["total_playlists"]))
        table.add_row("Total Albums", str(stats["total_albums"]))
        table.add_row("Storage Used", stats["total_size_str"])
        table.add_row("Downloads Directory", stats["downloads_dir"])
        console.print(table)
        return

    if action == "clear":
        try:
            confirm = input("Are you sure you want to delete ALL offline downloaded songs? (y/N): ").strip().lower()
            if confirm in ("y", "yes"):
                cnt = clear_all_offline_data(delete_files=True)
                console.print(f"[bold green]✓ Cleared {cnt} offline tracks and collections.[/bold green]")
            else:
                console.print("[yellow]Canceled.[/yellow]")
        except (KeyboardInterrupt, EOFError):
            pass
        return

    if action == "remove":
        if not target:
            console.print("[red]Please specify a track title, video ID, or collection to remove.[/red]")
            return
        if delete_offline_track(target):
            console.print(f"[bold green]✓ Removed offline track '{target}'.[/bold green]")
            return
        if delete_offline_collection(target, delete_tracks=False):
            console.print(f"[bold green]✓ Removed offline collection '{target}'.[/bold green]")
            return
        tracks = list_offline_tracks(target)
        if tracks:
            delete_offline_track(tracks[0].video_id)
            console.print(f"[bold green]✓ Removed offline track: {tracks[0].title}[/bold green]")
            return
        console.print(f"[red]No offline track or collection found matching '{target}'.[/red]")
        return

    if action in ("play", "search"):
        tracks = list_offline_tracks(target) if target else list_offline_tracks()
        if not tracks:
            console.print("[yellow]No matching offline tracks downloaded yet.[/yellow]")
            console.print("[dim]Use 'music download <song>' to download songs for offline playback.[/dim]")
            return

        if action == "search":
            table = Table(title=f"[bold cyan]Offline Tracks Matching '{target}'[/bold cyan]", border_style="cyan")
            table.add_column("#", style="dim", justify="right", width=3)
            table.add_column("Title", style="bold white")
            table.add_column("Artist", style="yellow")
            table.add_column("Duration", style="green", justify="right")
            for i, t in enumerate(tracks, 1):
                table.add_row(str(i), t.title, t.artist, t.duration)
            console.print(table)
            return

        if len(tracks) > 1 and getattr(args, "select", False):
            chosen = prompt_song_selection(tracks)
            if not chosen:
                return
            start_song = chosen
            idx = tracks.index(chosen)
            queue = tracks[idx + 1:]
        else:
            start_song = tracks[0]
            queue = tracks[1:]

        if getattr(args, "shuffle", False):
            import random
            random.shuffle(queue)

        vol = get_config_val("volume", 100)
        player = MpvPlayer(initial_volume=vol)
        run_player_loop(
            start_song,
            player,
            initial_queue=queue,
            playlist_name="Offline Library",
        )
        return

    if action == "playlist":
        if not target:
            playlists = list_offline_collections("playlist")
            if not playlists:
                console.print("[yellow]No offline playlists downloaded.[/yellow]")
                return
            table = Table(title="[bold cyan]Offline Playlists[/bold cyan]", border_style="cyan")
            table.add_column("#", style="dim", width=3)
            table.add_column("Title", style="bold white")
            table.add_column("Author", style="yellow")
            table.add_column("Tracks", style="cyan", justify="right")
            for i, p in enumerate(playlists, 1):
                table.add_row(str(i), p["title"], p.get("author", ""), str(p.get("track_count", 0)))
            console.print(table)
            return

        col, tracks = get_offline_collection_tracks(target)
        if not tracks:
            for p in list_offline_collections("playlist"):
                if target.lower() in p["title"].lower():
                    col, tracks = get_offline_collection_tracks(p["id"])
                    break
        if not tracks:
            console.print(f"[red]No offline playlist found matching '{target}'.[/red]")
            return

        if getattr(args, "shuffle", False):
            import random
            random.shuffle(tracks)

        start_song = tracks[0]
        queue = tracks[1:]
        vol = get_config_val("volume", 100)
        player = MpvPlayer(initial_volume=vol)
        run_player_loop(
            start_song,
            player,
            initial_queue=queue,
            playlist_name=f"Offline: {col.get('title', 'Playlist') if col else 'Playlist'}",
        )
        return

    if action == "album":
        if not target:
            albums = list_offline_collections("album")
            if not albums:
                console.print("[yellow]No offline albums downloaded.[/yellow]")
                return
            table = Table(title="[bold cyan]Offline Albums[/bold cyan]", border_style="cyan")
            table.add_column("#", style="dim", width=3)
            table.add_column("Title", style="bold white")
            table.add_column("Artist", style="yellow")
            table.add_column("Tracks", style="cyan", justify="right")
            for i, a in enumerate(albums, 1):
                table.add_row(str(i), a["title"], a.get("author", ""), str(a.get("track_count", 0)))
            console.print(table)
            return

        col, tracks = get_offline_collection_tracks(target)
        if not tracks:
            for a in list_offline_collections("album"):
                if target.lower() in a["title"].lower():
                    col, tracks = get_offline_collection_tracks(a["id"])
                    break
        if not tracks:
            console.print(f"[red]No offline album found matching '{target}'.[/red]")
            return

        if getattr(args, "shuffle", False):
            import random
            random.shuffle(tracks)

        start_song = tracks[0]
        queue = tracks[1:]
        vol = get_config_val("volume", 100)
        player = MpvPlayer(initial_volume=vol)
        run_player_loop(
            start_song,
            player,
            initial_queue=queue,
            playlist_name=f"Offline Album: {col.get('title', 'Album') if col else 'Album'}",
        )
        return

    # Default action: list
    tracks = list_offline_tracks()
    playlists = list_offline_collections("playlist")
    albums = list_offline_collections("album")
    stats = get_offline_stats()

    if not tracks and not playlists and not albums:
        console.print("[yellow]No songs downloaded for offline mode yet.[/yellow]")
        console.print("\n[bold cyan]How to download music for offline play:[/bold cyan]")
        console.print("  • Download a song:     [bold white]music download \"Song Title\"[/bold white]")
        console.print("  • Download a playlist: [bold white]music download playlist \"Playlist Name\"[/bold white]")
        console.print("  • Download an album:   [bold white]music download album \"Album Name\"[/bold white]")
        console.print("  • Press [bold white]'D'[/bold white] in the player while listening to save the current song!")
        return

    table = Table(
        title=f"[bold bright_green]💾 Offline Library ({stats['total_tracks']} tracks • {stats['total_size_str']})[/bold bright_green]",
        border_style="bright_green",
        box=box.ROUNDED,
    )
    table.add_column("#", style="dim", justify="right", width=3)
    table.add_column("Title", style="bold white", min_width=24)
    table.add_column("Artist", style="yellow", min_width=18)
    table.add_column("Album", style="dim")
    table.add_column("Duration", style="cyan", justify="right", width=8)

    for i, t in enumerate(tracks[:30], 1):
        table.add_row(str(i), t.title, t.artist, t.album or "--", t.duration)

    console.print(table)
    if len(tracks) > 30:
        console.print(f"[dim]... and {len(tracks) - 30} more tracks.[/dim]")

    if playlists:
        p_table = Table(title="[bold cyan]Offline Playlists[/bold cyan]", border_style="cyan", box=box.ROUNDED)
        p_table.add_column("#", style="dim", width=3)
        p_table.add_column("Playlist", style="bold white")
        p_table.add_column("Tracks", style="cyan", justify="right")
        for i, p in enumerate(playlists, 1):
            p_table.add_row(str(i), p["title"], str(p.get("track_count", 0)))
        console.print(p_table)

    if albums:
        a_table = Table(title="[bold cyan]Offline Albums[/bold cyan]", border_style="cyan", box=box.ROUNDED)
        a_table.add_column("#", style="dim", width=3)
        a_table.add_column("Album", style="bold white")
        a_table.add_column("Artist", style="yellow")
        a_table.add_column("Tracks", style="cyan", justify="right")
        for i, a in enumerate(albums, 1):
            a_table.add_row(str(i), a["title"], a.get("author", ""), str(a.get("track_count", 0)))
        console.print(a_table)

    console.print(
        "\n[dim]Commands: [bold white]music offline play [name][/bold white] to play • "
        "[bold white]music offline playlist [name][/bold white] • "
        "[bold white]music offline remove [name][/bold white][/dim]"
    )


def launch_home_session() -> None:
    """Run interactive OpenCode-styled home search session loop."""
    staged_queue: List[Any] = []
    while True:
        action = run_home_view(now_playing_queue=staged_queue)
        if not action:
            break
        act_type, target = action[:2]
        if act_type in ("track", "play_now"):
            vol = get_config_val("volume", 100)
            player = MpvPlayer(initial_volume=vol)
            rem = action[2] if len(action) > 2 and action[2] is not None else (staged_queue if staged_queue else None)
            pl_name = action[3] if len(action) > 3 else None
            pl_pos = action[4] if len(action) > 4 else None
            hist_stack = action[5] if len(action) > 5 else None
            staged_queue = []
            run_player_loop(
                target,
                player,
                initial_queue=rem,
                playlist_name=pl_name,
                playlist_pos=pl_pos,
                history_stack=hist_stack,
            )
        elif act_type in ("container_track", "playlist_track"):
            vol = get_config_val("volume", 100)
            player = MpvPlayer(initial_volume=vol)
            p_type = getattr(target, "parent_type", "playlist").capitalize()
            p_title = getattr(target, "parent_title", getattr(target, "playlist", None).title if hasattr(target, "playlist") else "Collection")
            full_t = getattr(target, "full_tracks", getattr(target, "full_playlist_tracks", []))
            initial_queue = full_t[target.track_index + 1 :]
            played_history = full_t[:target.track_index]
            run_player_loop(
                target.song,
                player,
                initial_queue=initial_queue,
                history_stack=played_history,
                playlist_name=f"{p_type}: {p_title}",
                playlist_pos=(target.track_index + 1, len(full_t)),
            )
        elif act_type == "album":
            handle_album_query(target.browse_id)
        elif act_type in ("album_url", "search_album"):
            handle_album_query(target)
        elif act_type == "playlist":
            handle_playlist_query(target.url or target.playlist_id)
        elif act_type in ("playlist_url", "search_playlist"):
            handle_playlist_query(target)
        elif act_type == "query":
            handle_play_query(target)


def main() -> None:
    """Main CLI entrypoint."""
    raw_args = sys.argv[1:]

    # OpenCode-styled interactive home view when typing 'music' with no arguments:
    if not raw_args:
        launch_home_session()
        return

    # Direct query convenience:
    # If the first argument is not a flag or recognized subcommand,
    # treat all non-flag arguments as a search query!
    subcommands = {"login", "logout", "config", "history", "search", "play", "url", "playlist", "album", "home", "help", "stop", "kill", "download", "offline"}

    if raw_args and not raw_args[0].startswith("-") and raw_args[0] not in subcommands:
        # Separate optional flags like -s / --select, --offline, --no-autoplay, --autoplay, --no-adblock, --adblock, --no-lyrics, --lyrics, --shuffle
        select_menu = False
        autoplay = None
        ad_blocker = None
        show_lyrics = None
        shuffle = False
        offline = False
        words = []
        for a in raw_args:
            if a in ("-s", "--select"):
                select_menu = True
            elif a in ("--offline", "-o"):
                offline = True
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
                    offline=offline,
                )
            else:
                handle_play_query(
                    query,
                    select_menu=select_menu,
                    autoplay=autoplay,
                    ad_blocker=ad_blocker,
                    show_lyrics=show_lyrics,
                    offline=offline,
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
    p_play.add_argument("--offline", "-o", action="store_true", help="Play only from downloaded offline tracks")
    p_play.add_argument("--no-autoplay", action="store_true", help="Disable autoplay for this session")
    p_play.add_argument("--autoplay", action="store_true", help="Force enable autoplay for this session")
    p_play.add_argument("--no-adblock", action="store_true", help="Disable ad & sponsor blocking")
    p_play.add_argument("--adblock", action="store_true", help="Force enable ad & sponsor blocking")
    p_play.add_argument("--no-lyrics", action="store_true", help="Disable synced lyrics display")
    p_play.add_argument("--lyrics", action="store_true", help="Force enable synced lyrics display")

    p_search = subparsers.add_parser("search", help="Search YouTube Music and select from list")
    p_search.add_argument("query", nargs="+", help="Song or playlist query to search")
    p_search.add_argument("-p", "--playlist", action="store_true", help="Search for playlists instead of individual tracks")
    p_search.add_argument("--offline", "-o", action="store_true", help="Search only downloaded offline tracks")
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
    p_plist.add_argument("--offline", "-o", action="store_true", help="Stream from local offline playlists")
    p_plist.add_argument("--no-autoplay", action="store_true", help="Stop playback when playlist ends")
    p_plist.add_argument("--autoplay", action="store_true", help="Continue radio after playlist ends")
    p_plist.add_argument("--no-adblock", action="store_true", help="Disable ad & sponsor blocking")
    p_plist.add_argument("--adblock", action="store_true", help="Force enable ad & sponsor blocking")
    p_plist.add_argument("--no-lyrics", action="store_true", help="Disable synced lyrics display")
    p_plist.add_argument("--lyrics", action="store_true", help="Force enable synced lyrics display")

    # album subcommand
    p_alb = subparsers.add_parser("album", help="Search or stream an entire album")
    p_alb.add_argument("query", nargs="+", help="Album name, artist, or YouTube Music album browse URL")
    p_alb.add_argument("-s", "--select", action="store_true", help="Select starting track from album table")
    p_alb.add_argument("--shuffle", action="store_true", help="Shuffle album tracks")
    p_alb.add_argument("--offline", "-o", action="store_true", help="Stream from local offline albums")
    p_alb.add_argument("--no-autoplay", action="store_true", help="Stop playback when album ends")
    p_alb.add_argument("--autoplay", action="store_true", help="Continue radio after album ends")
    p_alb.add_argument("--no-adblock", action="store_true", help="Disable ad & sponsor blocking")
    p_alb.add_argument("--adblock", action="store_true", help="Force enable ad & sponsor blocking")
    p_alb.add_argument("--no-lyrics", action="store_true", help="Disable synced lyrics display")
    p_alb.add_argument("--lyrics", action="store_true", help="Force enable synced lyrics display")

    p_url = subparsers.add_parser("url", help="Stream direct YouTube / YouTube Music URL")
    p_url.add_argument("url", help="Direct YouTube or YouTube Music song/playlist URL")
    p_url.add_argument("--no-autoplay", action="store_true", help="Disable autoplay for this session")
    p_url.add_argument("--autoplay", action="store_true", help="Force enable autoplay for this session")
    p_url.add_argument("--no-adblock", action="store_true", help="Disable ad & sponsor blocking")
    p_url.add_argument("--adblock", action="store_true", help="Force enable ad & sponsor blocking")
    p_url.add_argument("--no-lyrics", action="store_true", help="Disable synced lyrics display")
    p_url.add_argument("--lyrics", action="store_true", help="Force enable synced lyrics display")

    # download subcommand
    p_dl = subparsers.add_parser("download", help="Download songs, playlists, or albums for offline playback")
    p_dl.add_argument("query", nargs="+", help="Song title, playlist, album, or direct URL to download")
    p_dl.add_argument("-p", "--playlist", action="store_true", help="Download as playlist")
    p_dl.add_argument("-a", "--album", action="store_true", help="Download as album")
    p_dl.add_argument("-s", "--select", action="store_true", help="Select from search results before downloading")

    # offline subcommand
    p_off = subparsers.add_parser("offline", help="Manage and play offline downloaded media")
    p_off.add_argument(
        "action",
        nargs="?",
        choices=["list", "play", "playlist", "album", "search", "remove", "clear", "status"],
        default="list",
        help="Action: list (default), play, playlist, album, search, remove, clear, status",
    )
    p_off.add_argument("target", nargs="*", help="Query, title, video ID, or collection name")
    p_off.add_argument("-s", "--select", action="store_true", help="Select starting track from list")
    p_off.add_argument("--shuffle", action="store_true", help="Shuffle offline playback")

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

    # home subcommand
    subparsers.add_parser("home", help="Open interactive OpenCode-styled home search view")

    # stop / kill subcommand
    subparsers.add_parser("stop", help="Stop and terminate all background music playback")
    subparsers.add_parser("kill", help="Alias for stop")

    args = parser.parse_args(raw_args)

    if args.command in ("stop", "kill"):
        handle_stop_playback()
    elif args.command == "home":
        launch_home_session()
    elif args.command == "download":
        handle_download(args)
    elif args.command == "offline":
        handle_offline(args)
    elif args.command == "playlist":
        query = " ".join(args.query).strip()
        select_track = getattr(args, "select", False)
        shuf = getattr(args, "shuffle", False)
        off = getattr(args, "offline", False)
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
            offline=off,
        )
    elif args.command == "album":
        query = " ".join(args.query).strip()
        select_track = getattr(args, "select", False)
        shuf = getattr(args, "shuffle", False)
        off = getattr(args, "offline", False)
        ap = False if getattr(args, "no_autoplay", False) else (True if getattr(args, "autoplay", False) else None)
        adb = False if getattr(args, "no_adblock", False) else (True if getattr(args, "adblock", False) else None)
        lyr = False if getattr(args, "no_lyrics", False) else (True if getattr(args, "lyrics", False) else None)
        handle_album_query(
            query,
            select_track=select_track,
            shuffle=shuf,
            autoplay=ap,
            ad_blocker=adb,
            show_lyrics=lyr,
            offline=off,
        )
    elif args.command in ("play", "search"):
        query = " ".join(args.query).strip()
        select_menu = getattr(args, "select", False) or args.command == "search"
        off = getattr(args, "offline", False)
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
                offline=off,
            )
        else:
            handle_play_query(
                query,
                select_menu=select_menu,
                autoplay=ap,
                ad_blocker=adb,
                show_lyrics=lyr,
                offline=off,
            )
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
