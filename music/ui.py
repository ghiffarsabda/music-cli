"""Terminal User Interface for music-cli using Rich."""

import os
import select
import sys
import termios
import threading
import time
import tty
from typing import List, Optional

from rich.align import Align
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.progress_bar import ProgressBar
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text

from music.adblock import check_and_skip_ads, fetch_skip_segments
from music.auth import get_auth_status
from music.config import get_config_val
from music.history import add_to_history
from music.lyrics import LyricsData, fetch_lyrics, get_lyrics_display_window
from music.player import MpvPlayer
from music.search import (
    SongItem,
    format_duration,
    get_related_tracks,
    resolve_audio_stream_url,
)

console = Console()


def prompt_song_selection(songs: List[SongItem]) -> Optional[SongItem]:
    """Render interactive numbered table of search results and prompt user selection."""
    table = Table(
        title="[bold bright_blue]Search Results[/bold bright_blue]",
        box=box.ROUNDED,
        border_style="bright_blue",
        header_style="bold cyan",
        show_lines=True,
    )
    table.add_column("#", style="bold white", width=3, justify="center")
    table.add_column("Title", style="white", min_width=30)
    table.add_column("Artist", style="yellow", min_width=20)
    table.add_column("Album", style="dim", min_width=18)
    table.add_column("Duration", style="cyan", width=8, justify="right")

    for i, s in enumerate(songs, start=1):
        table.add_row(str(i), s.title, s.artist, s.album or "-", s.duration or "--:--")

    console.print(table)

    while True:
        try:
            choice = Prompt.ask(
                "[bold cyan]Select track #[/bold cyan] (1-" + str(len(songs)) + ", or 'q' to cancel)",
                default="1",
            )
            if choice.lower() in ("q", "quit", "exit"):
                return None
            idx = int(choice) - 1
            if 0 <= idx < len(songs):
                return songs[idx]
            console.print(f"[red]Please enter a number between 1 and {len(songs)}.[/red]")
        except ValueError:
            console.print("[red]Invalid input. Enter a valid number or 'q'.[/red]")
        except (KeyboardInterrupt, EOFError):
            return None


class KeyReader:
    """Non-blocking keyboard reader with support for arrows, space, and escape keys on Linux."""

    def __init__(self):
        self.old_settings = None

    def __enter__(self):
        if sys.stdin.isatty():
            try:
                self.old_settings = termios.tcgetattr(sys.stdin)
                tty.setcbreak(sys.stdin.fileno())
            except Exception:
                self.old_settings = None
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.old_settings:
            try:
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self.old_settings)
            except Exception:
                pass

    def get_key(self, timeout: float = 0.05) -> Optional[str]:
        """Read a single keypress or key escape sequence within timeout."""
        if not sys.stdin.isatty():
            time.sleep(timeout)
            return None

        rlist, _, _ = select.select([sys.stdin], [], [], timeout)
        if not rlist:
            return None

        try:
            ch1 = sys.stdin.read(1)
            if ch1 == "\x1b":  # Escape sequence
                rlist, _, _ = select.select([sys.stdin], [], [], 0.02)
                if not rlist:
                    return "escape"
                ch2 = sys.stdin.read(1)
                if ch2 == "[":
                    rlist, _, _ = select.select([sys.stdin], [], [], 0.02)
                    if not rlist:
                        return "escape"
                    ch3 = sys.stdin.read(1)
                    if ch3 == "A":
                        return "up"
                    elif ch3 == "B":
                        return "down"
                    elif ch3 == "C":
                        return "right"
                    elif ch3 == "D":
                        return "left"
            elif ch1 == "\x03":  # Ctrl-C
                return "quit"
            return ch1
        except Exception:
            return None


def render_player_panel(
    song: SongItem,
    status: dict,
    auth_info: dict,
    message: str = "",
    autoplay: bool = True,
    next_song: Optional[SongItem] = None,
    is_buffered: bool = False,
    ad_blocker: bool = True,
    show_lyrics: bool = True,
    lyrics_window: Optional[List[Tuple[str, str]]] = None,
) -> Panel:
    """Build the Rich UI Panel for current playback state."""
    state = status.get("state", "loading")
    time_pos = status.get("time_pos", 0.0)
    duration = status.get("duration", 0.0) or float(song.duration_seconds or 1.0)
    paused = status.get("paused", False)
    volume = status.get("volume", 80)
    muted = status.get("muted", False)

    # State badge
    if state == "playing":
        state_badge = "[bold green]▶ PLAYING[/bold green]"
    elif state == "paused":
        state_badge = "[bold yellow]⏸ PAUSED[/bold yellow]"
    elif state == "loading":
        state_badge = "[bold cyan]⌛ BUFFERING AUDIO[/bold cyan]"
    elif state == "finished":
        state_badge = "[bold white]⏹ FINISHED[/bold white]"
    else:
        state_badge = f"[bold dim]{state.upper()}[/bold dim]"

    # Auth badge
    if auth_info.get("mode") != "none":
        auth_badge = "[bold green]✓ Subscribed/Ad-Free[/bold green]"
    else:
        auth_badge = "[yellow]Standard (Public / Ads)[/yellow]"

    # Autoplay badge
    autoplay_badge = "[bold green]∞ Autoplay ON[/bold green]" if autoplay else "[dim]∞ Autoplay OFF[/dim]"

    # AdBlock badge
    adblock_badge = "[bold green]🛡️ AdBlock ON[/bold green]" if ad_blocker else "[dim]🛡️ AdBlock OFF[/dim]"

    # Lyrics badge
    lyrics_badge = "[bold magenta]🎤 Lyrics ON[/bold magenta]" if show_lyrics else "[dim]🎤 Lyrics OFF[/dim]"

    # Header line
    header_text = Text.from_markup(f"  {state_badge}    [dim]•[/dim]    {auth_badge}    [dim]•[/dim]    {autoplay_badge}    [dim]•[/dim]    {adblock_badge}    [dim]•[/dim]    {lyrics_badge}")

    # Song details
    song_info = Table.grid(padding=(0, 2))
    song_info.add_column(style="bold cyan", justify="right")
    song_info.add_column(style="white")

    song_info.add_row("Track:", f"[bold white]{song.title}[/bold white]")
    song_info.add_row("Artist:", f"[bold yellow]{song.artist}[/bold yellow]")
    if song.album:
        song_info.add_row("Album:", f"[dim]{song.album}[/dim]")
    if next_song:
        buff_status = "[bold green](⚡ Pre-buffered)[/bold green]" if is_buffered else "[dim cyan](⌛ Pre-buffering...)[/dim cyan]"
        song_info.add_row("Up Next:", f"[bold cyan]{next_song.title}[/bold cyan] [dim]by {next_song.artist}[/dim]  {buff_status}")
    song_info.add_row("Source:", f"[dim underline]{song.url}[/dim underline]")

    # Synced lyrics section
    lyrics_elements = []
    if show_lyrics and lyrics_window:
        for l_text, l_style in lyrics_window:
            if l_text:
                lyrics_elements.append(Align.center(Text(l_text, style=l_style)))
            else:
                lyrics_elements.append(Align.center(Text(" ")))

    # Progress bar calculation
    completed = min(time_pos, duration) if duration > 0 else 0
    total = max(duration, 1.0)
    curr_str = format_duration(time_pos)
    dur_str = format_duration(duration) if duration > 0 else song.duration or "--:--"

    prog_bar = ProgressBar(
        total=total,
        completed=completed,
        width=50,
        complete_style="bright_cyan",
        finished_style="green",
    )

    time_text = Text.from_markup(f"[cyan]{curr_str}[/cyan] / [dim]{dur_str}[/dim]")

    # Volume & status line
    vol_icon = "🔇" if muted or volume == 0 else ("🔉" if volume < 50 else "🔊")
    vol_status = f"{vol_icon} [bold]{volume}%[/bold]" if not muted else "🔇 [bold red]MUTED[/bold red]"
    vol_text = Text.from_markup(f"Volume: {vol_status}")

    # Keybinds footer
    controls = Text.from_markup(
        r"[bold white][Space][/bold white] Play/Pause   "
        r"[bold white][n][/bold white] Next   "
        r"[bold white][←/→][/bold white] ±5s   "
        r"[bold white][↑/↓][/bold white] Vol   "
        r"[bold white][m][/bold white] Mute   "
        r"[bold white][a][/bold white] Autoplay   "
        r"[bold white][b][/bold white] AdBlock   "
        r"[bold white][l][/bold white] Lyrics   "
        r"[bold white][q][/bold white] Quit"
    )

    elements = [
        header_text,
        Text(),
        song_info,
    ]

    if lyrics_elements:
        elements.append(Text())
        elements.append(Group(*lyrics_elements))

    elements.extend([
        Text(),
        Group(
            Align.center(prog_bar),
            Align.center(time_text),
        ),
        Text(),
        Align.center(vol_text),
        Text(),
        Align.center(controls),
    ])

    if message:
        elements.append(Text())
        elements.append(Align.center(Text.from_markup(f"[bold green]{message}[/bold green]")))

    return Panel(
        Group(*elements),
        title="[bold bright_blue]🎵 Music CLI - YouTube Music[/bold bright_blue]",
        border_style="bright_blue",
        padding=(1, 2),
    )


def run_player_loop(
    song: SongItem,
    player: MpvPlayer,
    autoplay: Optional[bool] = None,
    ad_blocker: Optional[bool] = None,
    show_lyrics: Optional[bool] = None,
) -> None:
    """Main interactive loop for playback, prebuffering, ad-blocking, synced lyrics, and keyboard control."""
    auth_info = get_auth_status()
    if autoplay is None:
        autoplay = get_config_val("autoplay", True)
    if ad_blocker is None:
        ad_blocker = get_config_val("ad_blocker", True)
    if show_lyrics is None:
        show_lyrics = get_config_val("show_lyrics", True)

    curr_song = song
    add_to_history(curr_song)

    queue: List[SongItem] = []
    seen_ids = {curr_song.video_id}
    buffered_vids = set()
    prebuffering_vid: Optional[str] = None
    lock = threading.Lock()
    is_fetching = False

    # AdBlock segments for current track
    current_segments: List[dict] = []
    skipped_ranges = set()

    # Synced lyrics data
    current_lyrics: Optional[LyricsData] = None

    def fetch_segments(vid: str):
        nonlocal current_segments, skipped_ranges
        skipped_ranges = set()
        current_segments = fetch_skip_segments(vid)

    def fetch_lyrics_task(target_song: SongItem):
        nonlocal current_lyrics
        current_lyrics = fetch_lyrics(
            target_song.title,
            target_song.artist,
            target_song.duration_seconds,
            target_song.video_id,
        )

    def fetch_queue(vid: str):
        nonlocal is_fetching
        is_fetching = True
        try:
            tracks = get_related_tracks(vid, limit=15)
            for t in tracks:
                if t.video_id not in seen_ids:
                    seen_ids.add(t.video_id)
                    queue.append(t)
        except Exception:
            pass
        finally:
            is_fetching = False

    def prebuffer_worker(target_song: SongItem):
        nonlocal prebuffering_vid
        try:
            url = resolve_audio_stream_url(target_song)
            with lock:
                if player.process_is_alive() and target_song.video_id not in buffered_vids:
                    player.append_track(url)
                    buffered_vids.add(target_song.video_id)
        except Exception:
            pass
        finally:
            with lock:
                if prebuffering_vid == target_song.video_id:
                    prebuffering_vid = None

    # Start background queue, ad-block segments, and lyrics fetching
    threading.Thread(target=fetch_queue, args=(curr_song.video_id,), daemon=True).start()
    threading.Thread(target=fetch_segments, args=(curr_song.video_id,), daemon=True).start()
    threading.Thread(target=fetch_lyrics_task, args=(curr_song,), daemon=True).start()

    console.print(f"[cyan]⌛ Preparing audio stream for:[/cyan] [bold white]{curr_song.title}[/bold white]...")
    stream_url = resolve_audio_stream_url(curr_song)

    try:
        player.start()
    except Exception as e:
        console.print(f"[bold red]Failed to start player backend:[/bold red] {e}")
        return

    player.play(stream_url)

    message = ""
    msg_clear_time = 0.0

    with KeyReader() as key_reader:
        with Live(console=console, refresh_per_second=10, transient=False) as live:
            while player.process_is_alive():
                # Clear temporary notification message
                if message and time.time() > msg_clear_time:
                    message = ""

                # Asynchronous prebuffering: prebuffer upcoming track in background
                if autoplay and queue:
                    candidate = queue[0]
                    with lock:
                        if candidate.video_id not in buffered_vids and prebuffering_vid != candidate.video_id:
                            prebuffering_vid = candidate.video_id
                            threading.Thread(target=prebuffer_worker, args=(candidate,), daemon=True).start()

                # Handle keyboard inputs
                key = key_reader.get_key(timeout=0.08)
                if key:
                    if key in ("q", "quit"):
                        break
                    elif key == " ":
                        player.toggle_pause()
                    elif key in ("n", "N", ">"):
                        if queue:
                            next_track = queue[0]
                            with lock:
                                is_buf = next_track.video_id in buffered_vids
                            if is_buf:
                                # Instant switch to pre-buffered track!
                                player.next_track()
                                player._send_command(["playlist-remove", 0])
                                curr_song = queue.pop(0)
                                add_to_history(curr_song)
                                threading.Thread(target=fetch_segments, args=(curr_song.video_id,), daemon=True).start()
                                threading.Thread(target=fetch_lyrics_task, args=(curr_song,), daemon=True).start()
                                message = f"⚡ Instant Next: {curr_song.title}"
                                msg_clear_time = time.time() + 2.0
                            else:
                                curr_song = queue.pop(0)
                                add_to_history(curr_song)
                                threading.Thread(target=fetch_segments, args=(curr_song.video_id,), daemon=True).start()
                                threading.Thread(target=fetch_lyrics_task, args=(curr_song,), daemon=True).start()
                                stream_url = resolve_audio_stream_url(curr_song)
                                player.play(stream_url)
                                message = f"Skipping to: {curr_song.title}"
                                msg_clear_time = time.time() + 2.0

                            if len(queue) < 4 and not is_fetching:
                                threading.Thread(target=fetch_queue, args=(curr_song.video_id,), daemon=True).start()
                        else:
                            message = "Queue is empty"
                            msg_clear_time = time.time() + 1.5
                    elif key in ("a", "A"):
                        autoplay = not autoplay
                        message = f"Autoplay {'ON' if autoplay else 'OFF'}"
                        msg_clear_time = time.time() + 1.5
                    elif key in ("b", "B"):
                        ad_blocker = not ad_blocker
                        message = f"🛡️ AdBlock {'ON' if ad_blocker else 'OFF'}"
                        msg_clear_time = time.time() + 1.5
                    elif key in ("l", "L"):
                        show_lyrics = not show_lyrics
                        message = f"🎤 Lyrics {'ON' if show_lyrics else 'OFF'}"
                        msg_clear_time = time.time() + 1.5
                    elif key == "right":
                        player.seek(5)
                        message = "Seek +5s"
                        msg_clear_time = time.time() + 1.2
                    elif key == "left":
                        player.seek(-5)
                        message = "Seek -5s"
                        msg_clear_time = time.time() + 1.2
                    elif key == "]":
                        player.seek(30)
                        message = "Seek +30s"
                        msg_clear_time = time.time() + 1.2
                    elif key == "[":
                        player.seek(-30)
                        message = "Seek -30s"
                        msg_clear_time = time.time() + 1.2
                    elif key == "up":
                        new_vol = player.adjust_volume(5)
                        message = f"Volume: {new_vol}%"
                        msg_clear_time = time.time() + 1.2
                    elif key == "down":
                        new_vol = player.adjust_volume(-5)
                        message = f"Volume: {new_vol}%"
                        msg_clear_time = time.time() + 1.2
                    elif key in ("m", "M"):
                        player.toggle_mute()
                        message = "Mute toggled"
                        msg_clear_time = time.time() + 1.2
                    elif key in ("r", "R"):
                        player.restart()
                        message = "Replaying track"
                        msg_clear_time = time.time() + 1.2

                # Check for automatic gapless transition from MPV
                playlist_pos = player.get_playlist_pos()
                if playlist_pos > 0 and queue:
                    # mpv automatically advanced to pre-buffered track!
                    player._send_command(["playlist-remove", 0])
                    curr_song = queue.pop(0)
                    add_to_history(curr_song)
                    threading.Thread(target=fetch_segments, args=(curr_song.video_id,), daemon=True).start()
                    threading.Thread(target=fetch_lyrics_task, args=(curr_song,), daemon=True).start()
                    message = f"⚡ Instant Next: {curr_song.title}"
                    msg_clear_time = time.time() + 2.5
                    if len(queue) < 4 and not is_fetching:
                        threading.Thread(target=fetch_queue, args=(curr_song.video_id,), daemon=True).start()
                    continue

                # Refresh display & run real-time AdBlock skipping
                status = player.get_status()
                if ad_blocker and current_segments and status.get("state") == "playing":
                    skip_msg = check_and_skip_ads(player, status.get("time_pos", 0.0), current_segments, skipped_ranges)
                    if skip_msg:
                        message = skip_msg
                        msg_clear_time = time.time() + 2.5

                next_track = queue[0] if queue else None
                with lock:
                    is_ready = bool(next_track and next_track.video_id in buffered_vids)

                # Calculate lyrics display window
                lyrics_win = None
                if show_lyrics:
                    lyrics_win, _ = get_lyrics_display_window(current_lyrics, status.get("time_pos", 0.0))

                if status["state"] == "error":
                    live.update(
                        render_player_panel(
                            curr_song,
                            status,
                            auth_info,
                            message="[Playback Error - Could not load stream]",
                            autoplay=autoplay,
                            next_song=next_track,
                            is_buffered=is_ready,
                            ad_blocker=ad_blocker,
                            show_lyrics=show_lyrics,
                            lyrics_window=lyrics_win,
                        )
                    )
                    time.sleep(2.0)
                    break
                elif status["state"] == "finished":
                    if autoplay and queue:
                        if is_ready:
                            player.next_track()
                            player._send_command(["playlist-remove", 0])
                            curr_song = queue.pop(0)
                            add_to_history(curr_song)
                            threading.Thread(target=fetch_segments, args=(curr_song.video_id,), daemon=True).start()
                            threading.Thread(target=fetch_lyrics_task, args=(curr_song,), daemon=True).start()
                            message = f"⚡ Instant Next: {curr_song.title}"
                            msg_clear_time = time.time() + 2.5
                        else:
                            curr_song = queue.pop(0)
                            add_to_history(curr_song)
                            threading.Thread(target=fetch_segments, args=(curr_song.video_id,), daemon=True).start()
                            threading.Thread(target=fetch_lyrics_task, args=(curr_song,), daemon=True).start()
                            stream_url = resolve_audio_stream_url(curr_song)
                            player.play(stream_url)
                            message = f"Autoplaying: {curr_song.title}"
                            msg_clear_time = time.time() + 2.5

                        if len(queue) < 4 and not is_fetching:
                            threading.Thread(target=fetch_queue, args=(curr_song.video_id,), daemon=True).start()
                        continue
                    else:
                        live.update(
                            render_player_panel(
                                curr_song,
                                status,
                                auth_info,
                                message="[Playback Finished]",
                                autoplay=autoplay,
                                next_song=next_track,
                                is_buffered=is_ready,
                                ad_blocker=ad_blocker,
                                show_lyrics=show_lyrics,
                                lyrics_window=lyrics_win,
                            )
                        )
                        time.sleep(1.0)
                        break

                panel = render_player_panel(
                    curr_song,
                    status,
                    auth_info,
                    message=message,
                    autoplay=autoplay,
                    next_song=next_track,
                    is_buffered=is_ready,
                    ad_blocker=ad_blocker,
                    show_lyrics=show_lyrics,
                    lyrics_window=lyrics_win,
                )
                live.update(panel)

    player.stop()
    console.print("\n[dim]Playback stopped.[/dim]\n")
