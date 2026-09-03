"""Interactive playback queue manager for music-cli."""

import shutil
import threading
import time
from typing import List, Optional, Set, Tuple

from rich import box
from rich.align import Align
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from music.adblock import check_and_skip_ads
from music.player import MpvPlayer
from music.search import SongItem, format_duration
from music.ui import KeyReader

PAGE_SIZE = 8


def truncate_str(text: str, max_len: int) -> str:
    """Cleanly truncate text with ellipsis if exceeding max_len."""
    if len(text) > max_len:
        return text[: max_len - 1].rstrip() + "…"
    return text


def render_queue_screen(
    curr_song: SongItem,
    time_progress: str,
    queue: List[SongItem],
    selected_idx: int,
    scroll_offset: int,
    notification_msg: str = "",
    console_width: int = 80,
    console_height: int = 24,
) -> Group:
    """Build the styled Queue Manager screen."""
    panel_width = min(74, max(54, console_width - 6))
    inner_width = panel_width - 6

    # 1. Header with currently playing song
    header = Align.center(
        Text.from_markup(
            f"[bold bright_cyan]🎶  P l a y b a c k   Q u e u e[/bold bright_cyan]  [dim]({len(queue)} upcoming)[/dim]\n"
            f"[bold green]▶  Now Playing:[/bold green] [bold white]{truncate_str(curr_song.title, 26)}[/bold white] "
            f"[dim]by {truncate_str(curr_song.artist, 18)}[/dim]   [cyan]{time_progress}[/cyan]"
        )
    )

    # 2. Queue items table or empty state
    if not queue:
        empty_text = Text(
            "\n  The queue is currently empty.\n\n"
            "  Press '/' in the player to search and add tracks with '+' or 'Enter'!\n",
            style="dim italic",
        )
        body_panel = Panel(
            empty_text,
            title="[dim]Upcoming Tracks[/dim]",
            title_align="left",
            box=box.ROUNDED,
            border_style="bright_blue",
            width=panel_width,
            padding=(1, 2),
        )
    else:
        table = Table(
            box=None,
            expand=True,
            show_header=True,
            header_style="bold cyan",
            padding=(0, 1),
        )
        table.add_column("", width=2, justify="center")
        table.add_column("#", width=3, justify="right", style="dim")
        table.add_column("Title", min_width=24, no_wrap=True)
        table.add_column("Artist", min_width=16, style="yellow", no_wrap=True)
        table.add_column("Duration", width=8, justify="right", style="cyan")

        visible_items = queue[scroll_offset : scroll_offset + PAGE_SIZE]
        for v_idx, song in enumerate(visible_items):
            actual_idx = scroll_offset + v_idx
            is_selected = actual_idx == selected_idx
            prefix = "▶ " if is_selected else "  "
            pos_str = str(actual_idx + 1)
            row_style = "bold bright_white on blue" if is_selected else "white"

            title_str = truncate_str(song.title, max(18, inner_width - 34))
            artist_str = truncate_str(song.artist, 16)
            dur_str = song.duration or "--:--"

            table.add_row(prefix, pos_str, title_str, artist_str, dur_str, style=row_style)

        # Scrolling indicator in title
        start_n = scroll_offset + 1
        end_n = min(len(queue), scroll_offset + PAGE_SIZE)
        title_count = f"[dim]Upcoming ({start_n}-{end_n} of {len(queue)})[/dim]"

        body_panel = Panel(
            table,
            title=title_count,
            title_align="left",
            box=box.ROUNDED,
            border_style="bright_cyan",
            width=panel_width,
            padding=(0, 1),
        )

    # 3. Context-aware Footer Shortcuts
    footer = Align.center(
        Text.from_markup(
            "[bold cyan]↑/↓[/bold cyan] Select   [dim]•[/dim]   "
            "[bold cyan]Shift+↑/↓ (J/K)[/bold cyan] Reorder   [dim]•[/dim]   "
            "[bold red]x / Del[/bold red] Remove   [dim]•[/dim]   "
            "[bold cyan]Enter[/bold cyan] Play Now   [dim]•[/dim]   "
            "[bold white]Esc / Tab[/bold white] Back"
        )
    )

    # 4. Vertical Centering
    content_height = 17
    top_pad = max(1, (console_height - content_height) // 2)

    elements = []
    if top_pad > 1:
        elements.append(Text("\n" * (top_pad - 1)))
    elements.extend([
        header,
        Text(""),
    ])

    if notification_msg:
        elements.append(Align.center(Text.from_markup(notification_msg)))

    elements.extend([
        Align.center(body_panel),
        Text(""),
        footer,
    ])

    return Group(*elements)


def run_queue_view(
    player: MpvPlayer,
    curr_song: SongItem,
    queue: List[SongItem],
    time_progress: str = "",
    ad_blocker: bool = True,
    current_segments: Optional[List[dict]] = None,
    skipped_ranges: Optional[Set] = None,
) -> Optional[Tuple[str, SongItem]]:
    """Interactive loop for viewing, reordering, and deleting tracks from the queue."""
    console = Console()
    selected_idx = 0
    scroll_offset = 0

    notification_msg = ""
    notif_clear_time = 0.0
    active_now_playing_time = time_progress

    with KeyReader() as key_reader:
        with Live(console=console, refresh_per_second=15, transient=True) as live:
            while player.process_is_alive():
                if notification_msg and time.time() > notif_clear_time:
                    notification_msg = ""

                # Live playback update & AdBlock skipping
                p_status = player.get_status()
                pos = p_status.get("time_pos", 0.0)
                dur = p_status.get("duration", 0.0) or curr_song.duration_seconds
                active_now_playing_time = f"{format_duration(pos)} / {format_duration(dur)}"
                if ad_blocker and current_segments and p_status.get("state") == "playing":
                    s_msg = check_and_skip_ads(player, pos, current_segments, skipped_ranges)
                    if s_msg:
                        notification_msg = f"[bold yellow]🛡️ {s_msg}[/bold yellow]"
                        notif_clear_time = time.time() + 2.0

                term_size = shutil.get_terminal_size((80, 24))
                term_w = term_size.columns
                term_h = term_size.lines

                # Keep selection and scroll bounded
                if queue:
                    selected_idx = max(0, min(len(queue) - 1, selected_idx))
                    if selected_idx < scroll_offset:
                        scroll_offset = selected_idx
                    elif selected_idx >= scroll_offset + PAGE_SIZE:
                        scroll_offset = selected_idx - PAGE_SIZE + 1
                else:
                    selected_idx = 0
                    scroll_offset = 0

                screen = render_queue_screen(
                    curr_song=curr_song,
                    time_progress=active_now_playing_time,
                    queue=queue,
                    selected_idx=selected_idx,
                    scroll_offset=scroll_offset,
                    notification_msg=notification_msg,
                    console_width=term_w,
                    console_height=term_h,
                )
                live.update(screen)

                key = key_reader.get_key(timeout=0.06)
                if not key:
                    continue

                if key in ("escape", "tab", "\t", "q", "quit"):
                    return None

                elif key == "up":
                    if queue:
                        selected_idx = max(0, selected_idx - 1)

                elif key == "down":
                    if queue:
                        selected_idx = min(len(queue) - 1, selected_idx + 1)

                # Reorder UP: Shift+Up or 'K' or 'k' or 'u'
                elif key in ("shift_up", "K", "k"):
                    if queue and selected_idx > 0:
                        queue[selected_idx], queue[selected_idx - 1] = queue[selected_idx - 1], queue[selected_idx]
                        selected_idx -= 1
                        notification_msg = f"[bold green]▲ Moved up: {truncate_str(queue[selected_idx].title, 32)}[/bold green]"
                        notif_clear_time = time.time() + 1.5

                # Reorder DOWN: Shift+Down or 'J' or 'j'
                elif key in ("shift_down", "J", "j"):
                    if queue and selected_idx < len(queue) - 1:
                        queue[selected_idx], queue[selected_idx + 1] = queue[selected_idx + 1], queue[selected_idx]
                        selected_idx += 1
                        notification_msg = f"[bold green]▼ Moved down: {truncate_str(queue[selected_idx].title, 32)}[/bold green]"
                        notif_clear_time = time.time() + 1.5

                # Remove from Queue: 'x' or Delete or Backspace or 'd'
                elif key in ("x", "X", "delete", "\x7f", "\x08", "d", "D"):
                    if queue and 0 <= selected_idx < len(queue):
                        removed = queue.pop(selected_idx)
                        if selected_idx >= len(queue):
                            selected_idx = max(0, len(queue) - 1)
                        notification_msg = f"[bold yellow]✗ Removed from queue: {truncate_str(removed.title, 30)}[/bold yellow]"
                        notif_clear_time = time.time() + 1.8

                # Clear entire Queue: 'c' or 'C'
                elif key in ("c", "C"):
                    if queue:
                        queue.clear()
                        selected_idx = 0
                        scroll_offset = 0
                        notification_msg = "[bold red]✓ Queue cleared[/bold red]"
                        notif_clear_time = time.time() + 1.8

                # Play Now: Enter
                elif key in ("\r", "\n", "enter"):
                    if queue and 0 <= selected_idx < len(queue):
                        chosen = queue.pop(selected_idx)
                        return ("play_now", chosen)

    return None
