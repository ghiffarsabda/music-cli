"""Terminal User Interface for music-cli using Rich."""

import os
import select
import sys
import termios
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

from music.auth import get_auth_status
from music.history import add_to_history
from music.player import MpvPlayer
from music.search import SongItem, format_duration

console = Console()


def prompt_song_selection(songs: List[SongItem]) -> Optional[SongItem]:
    """Render search results in a clean table and prompt user to pick."""
    if not songs:
        console.print("[red]No songs found.[/red]")
        return None

    if len(songs) == 1:
        return songs[0]

    table = Table(
        title="[bold cyan]YouTube Music Results[/bold cyan]",
        border_style="bright_blue",
        title_justify="left",
        show_lines=False,
    )
    table.add_column("#", style="bold yellow", width=4, justify="right")
    table.add_column("Title", style="bold white", min_width=25)
    table.add_column("Artist", style="cyan", min_width=18)
    table.add_column("Album", style="dim", min_width=15)
    table.add_column("Duration", style="green", justify="right", width=10)

    for idx, song in enumerate(songs, 1):
        table.add_row(
            str(idx),
            song.title,
            song.artist,
            song.album or "-",
            song.duration or "--:--",
        )

    console.print()
    console.print(table)
    console.print()

    auth = get_auth_status()
    auth_desc = f"[green]● {auth['description']}[/green]" if auth["mode"] != "none" else "[yellow]● Standard Mode (No login)[/yellow]"
    console.print(f"Status: {auth_desc}")
    console.print("[dim]Press Enter to play #1, type 1-N to select, or 'q' to cancel:[/dim]")

    try:
        choice = input("> ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        console.print("\n[yellow]Cancelled.[/yellow]")
        return None

    if choice in ("q", "quit", "exit"):
        return None
    if choice == "":
        return songs[0]

    try:
        idx = int(choice)
        if 1 <= idx <= len(songs):
            return songs[idx - 1]
    except ValueError:
        pass

    console.print("[yellow]Invalid selection. Playing top result by default.[/yellow]")
    return songs[0]


class KeyReader:
    """Non-blocking keyboard character reader using termios and tty."""

    def __init__(self):
        self.fd = sys.stdin.fileno() if sys.stdin.isatty() else None
        self.old_settings = None

    def __enter__(self):
        if self.fd is not None:
            try:
                self.old_settings = termios.tcgetattr(self.fd)
                tty.setcbreak(self.fd)
            except Exception:
                self.old_settings = None
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.fd is not None and self.old_settings is not None:
            try:
                termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old_settings)
            except Exception:
                pass

    def get_key(self, timeout: float = 0.05) -> Optional[str]:
        """Read a single key or escape sequence within timeout seconds."""
        if self.fd is None:
            time.sleep(timeout)
            return None

        rlist, _, _ = select.select([self.fd], [], [], timeout)
        if not rlist:
            return None

        try:
            ch1 = os.read(self.fd, 1).decode("utf-8", errors="ignore")
            if ch1 == "\x1b":  # Escape sequence
                rlist, _, _ = select.select([self.fd], [], [], 0.05)
                if not rlist:
                    return "escape"
                ch2 = os.read(self.fd, 1).decode("utf-8", errors="ignore")
                if ch2 == "[":
                    ch3 = os.read(self.fd, 1).decode("utf-8", errors="ignore")
                    if ch3 == "A":
                        return "up"
                    elif ch3 == "B":
                        return "down"
                    elif ch3 == "C":
                        return "right"
                    elif ch3 == "D":
                        return "left"
                return "escape"
            elif ch1 in ("\x03", "\x04"):  # Ctrl+C or Ctrl+D
                return "quit"
            return ch1
        except Exception:
            return None


def render_player_panel(song: SongItem, status: dict, auth_info: dict, message: str = "") -> Panel:
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

    # Header line
    header_text = Text.from_markup(f"  {state_badge}    [dim]•[/dim]    {auth_badge}")

    # Song details
    song_info = Table.grid(padding=(0, 2))
    song_info.add_column(style="bold cyan", justify="right")
    song_info.add_column(style="white")

    song_info.add_row("Track:", f"[bold white]{song.title}[/bold white]")
    song_info.add_row("Artist:", f"[bold yellow]{song.artist}[/bold yellow]")
    if song.album:
        song_info.add_row("Album:", f"[dim]{song.album}[/dim]")
    song_info.add_row("Source:", f"[dim underline]{song.url}[/dim underline]")

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
        r"[bold white][←/→][/bold white] ±5s   "
        r"[bold white][\[/\]][/bold white] ±30s   "
        r"[bold white][↑/↓][/bold white] Vol   "
        r"[bold white][m][/bold white] Mute   "
        r"[bold white][r][/bold white] Replay   "
        r"[bold white][q][/bold white] Quit"
    )

    elements = [
        header_text,
        Text(),
        song_info,
        Text(),
        Group(
            Align.center(prog_bar),
            Align.center(time_text),
        ),
        Text(),
        Align.center(vol_text),
        Text(),
        Align.center(controls),
    ]

    if message:
        elements.append(Text())
        elements.append(Align.center(Text.from_markup(f"[bold green]{message}[/bold green]")))

    return Panel(
        Group(*elements),
        title="[bold bright_blue]🎵 Music CLI - YouTube Music[/bold bright_blue]",
        border_style="bright_blue",
        padding=(1, 2),
    )


def run_player_loop(song: SongItem, player: MpvPlayer) -> None:
    """Main interactive loop for song playback and keyboard control."""
    auth_info = get_auth_status()
    add_to_history(song)

    try:
        player.start()
    except Exception as e:
        console.print(f"[bold red]Failed to start player backend:[/bold red] {e}")
        return

    player.play(song.url)

    message = ""
    msg_clear_time = 0.0

    with KeyReader() as key_reader:
        with Live(console=console, refresh_per_second=10, transient=False) as live:
            while player.process_is_alive():
                # Clear temporary notification message
                if message and time.time() > msg_clear_time:
                    message = ""

                # Handle keyboard inputs
                key = key_reader.get_key(timeout=0.08)
                if key:
                    if key in ("q", "quit"):
                        break
                    elif key == " ":
                        player.toggle_pause()
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

                # Refresh display
                status = player.get_status()
                if status["state"] == "finished":
                    live.update(render_player_panel(song, status, auth_info, message="[Playback Finished]"))
                    time.sleep(1.0)
                    break

                panel = render_player_panel(song, status, auth_info, message)
                live.update(panel)

    player.stop()
    console.print("\n[dim]Playback stopped.[/dim]\n")
