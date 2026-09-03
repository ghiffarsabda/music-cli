"""Interactive OpenCode-styled Home View for music-cli.

Provides a vertically and horizontally centered, minimalist search bar with live animated
loading dropdown suggestions for tracks, playlists, and history. Supports asynchronous
infinite scrolling to browse more results indefinitely.
"""

import shutil
import threading
import time
from dataclasses import dataclass
from typing import Any, List, Optional, Set, Tuple

from rich import box
from rich.align import Align
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from music.config import get_config_val
from music.history import get_history
from music.player import MpvPlayer
from music.search import (
    PlaylistItem,
    SongItem,
    is_playlist_url,
    search_music,
    search_playlists,
)
from music.ui import KeyReader, run_player_loop

SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
PAGE_SIZE = 7


@dataclass
class DropdownItem:
    kind: str  # "track", "playlist", "history", "preset"
    title: str
    subtitle: str
    extra: str
    data: Any


def truncate_str(text: str, max_len: int) -> str:
    """Cleanly truncate text with ellipsis if exceeding max_len."""
    if len(text) > max_len:
        return text[: max_len - 1].rstrip() + "…"
    return text


def get_default_items() -> List[DropdownItem]:
    """Return default quick-pick items: recent history + popular genres/presets."""
    items: List[DropdownItem] = []

    # 1. Recent History
    recent_songs = get_history(limit=4)
    for s in recent_songs:
        items.append(
            DropdownItem(
                kind="history",
                title=s.title,
                subtitle=s.artist,
                extra=s.duration or "--:--",
                data=s,
            )
        )

    # 2. Curated Presets to ensure rich home screen
    presets = [
        ("Lo-Fi Study Beats", "Curated Radio", "Relaxing", "lofi hip hop study beats"),
        ("Today's Top Hits", "YouTube Music", "Trending", "top hits 2026"),
        ("Synthwave Chill", "Retro Wave", "Focus", "synthwave chill"),
        ("Acoustic Coffeehouse", "Acoustic Pop", "Chill", "acoustic coffeehouse pop"),
    ]

    for title, subtitle, extra, query in presets:
        if len(items) >= 7:
            break
        items.append(
            DropdownItem(
                kind="preset",
                title=title,
                subtitle=subtitle,
                extra=extra,
                data=query,
            )
        )

    return items


def fetch_dropdown_results(
    query: str,
    filter_mode: str,
    limit: int = 15,
    seen_ids: Optional[Set[str]] = None,
) -> List[DropdownItem]:
    """Fetch search results formatted for the dropdown according to filter_mode.
    
    If seen_ids is provided, deduplicates against already loaded items for infinite scrolling.
    """
    clean_q = query.strip()
    if not clean_q:
        return get_default_items()

    if seen_ids is None:
        seen_ids = set()

    items: List[DropdownItem] = []

    if filter_mode in ("All", "Tracks"):
        limit_tracks = limit if filter_mode == "Tracks" else max(8, int(limit * 0.65))
        try:
            songs = search_music(clean_q, limit=limit_tracks)
            for s in songs:
                if s.video_id and s.video_id not in seen_ids:
                    seen_ids.add(s.video_id)
                    items.append(
                        DropdownItem(
                            kind="track",
                            title=s.title,
                            subtitle=s.artist,
                            extra=s.duration or "--:--",
                            data=s,
                        )
                    )
        except Exception:
            pass

    if filter_mode in ("All", "Playlists"):
        limit_pl = limit if filter_mode == "Playlists" else max(4, int(limit * 0.35))
        try:
            playlists = search_playlists(clean_q, limit=limit_pl)
            for p in playlists:
                if p.playlist_id and p.playlist_id not in seen_ids:
                    seen_ids.add(p.playlist_id)
                    cnt_str = f"{p.track_count} tracks" if p.track_count > 0 else "Playlist"
                    items.append(
                        DropdownItem(
                            kind="playlist",
                            title=p.title,
                            subtitle=p.author,
                            extra=cnt_str,
                            data=p,
                        )
                    )
        except Exception:
            pass

    return items


def render_home_screen(
    query: str,
    cursor_on: bool,
    filter_mode: str,
    items: List[DropdownItem],
    selected_idx: int,
    scroll_offset: int,
    is_searching: bool,
    is_loading_more: bool = False,
    console_width: int = 80,
    console_height: int = 24,
) -> Group:
    """Build the OpenCode-styled home layout with vertical/horizontal centering and viewport scrolling."""
    panel_width = min(72, max(52, console_width - 6))
    inner_width = panel_width - 6

    # 1. Minimalist OpenCode Brand Header
    header = Align.center(
        Text.from_markup(
            "[bold bright_cyan]♫  m u s i c  -  c l i[/bold bright_cyan]  [dim]v0.1.0[/dim]\n"
            "[green]● Online[/green]  [dim]•[/dim]  [cyan]YouTube Music[/cyan]  [dim]•[/dim]  [magenta]Karaoke Ready[/magenta]  [dim]•[/dim]  [green]🛡️ AdBlock[/green]"
        )
    )

    # 2. Centered Search Bar
    cursor_char = "│" if cursor_on else " "
    search_text = Text()
    search_text.append(" 🔍  ", style="bright_cyan")
    if query:
        search_text.append(query, style="bold white")
    else:
        search_text.append("Search songs, artists, or playlists...", style="dim white")
    search_text.append(cursor_char, style="bold bright_yellow")

    # Filter Badge pill on the right
    content_display_len = len(query) if query else len("Search songs, artists, or playlists...")
    available_space = panel_width - 4 - 6 - content_display_len - len(filter_mode) - 4
    if available_space > 1:
        search_text.append(" " * available_space)
        search_text.append(f"[{filter_mode}]", style="bold cyan")

    search_border = "bright_cyan" if selected_idx == -1 else "blue"
    search_panel = Panel(
        search_text,
        title="[dim]Search[/dim]",
        title_align="left",
        box=box.ROUNDED,
        border_style=search_border,
        width=panel_width,
        padding=(0, 1),
    )

    # 3. Dynamic Dropdown List / Animated Loading State
    if is_searching and query.strip():
        spinner = SPINNER_FRAMES[int(time.time() * 10) % len(SPINNER_FRAMES)]
        loading_table = Table.grid(padding=(0, 1))
        loading_table.add_column(width=3, justify="center")
        loading_table.add_column(width=inner_width - 3, no_wrap=True)

        loading_table.add_row(
            f"[bold bright_cyan]{spinner}[/bold bright_cyan]",
            f"[bold white]Searching YouTube Music for:[/bold white] [bold bright_cyan]\"{truncate_str(query, 30)}\"[/bold bright_cyan]...",
        )
        loading_table.add_row(
            " ",
            "[dim]Querying matching songs and community playlists...[/dim]",
        )
        loading_table.add_row(
            " ",
            "[dim cyan]╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌[/dim cyan]",
        )
        loading_table.add_row(
            "[bold cyan]⚡[/bold cyan]",
            "[dim]Pre-caching audio streams & time-synced lyrics...[/dim]",
        )

        dropdown_panel = Panel(
            loading_table,
            title=f"[dim]Results  [bold bright_cyan]{spinner} Loading...[/bold bright_cyan][/dim]",
            title_align="left",
            box=box.ROUNDED,
            border_style="bright_cyan",
            width=panel_width,
            padding=(1, 2),
        )
    else:
        # Windowed Viewport: show PAGE_SIZE items starting at scroll_offset
        visible_items = items[scroll_offset : scroll_offset + PAGE_SIZE]

        col_cursor = 2
        col_kind = 12
        col_extra = 11
        rem_width = max(24, inner_width - col_cursor - col_kind - col_extra)
        col_title = int(rem_width * 0.60)
        col_sub = rem_width - col_title

        items_table = Table.grid(padding=(0, 1))
        items_table.add_column(width=col_cursor, justify="center")
        items_table.add_column(width=col_kind)
        items_table.add_column(width=col_title, no_wrap=True)
        items_table.add_column(width=col_sub, no_wrap=True)
        items_table.add_column(width=col_extra, justify="right", no_wrap=True)

        if visible_items:
            for i, itm in enumerate(visible_items):
                actual_idx = scroll_offset + i
                is_active = actual_idx == selected_idx

                if itm.kind == "track":
                    kind_badge = "🎵 Track"
                    kind_style = "bold magenta" if is_active else "dim magenta"
                elif itm.kind == "playlist":
                    kind_badge = "📋 Playlist"
                    kind_style = "bold cyan" if is_active else "dim cyan"
                elif itm.kind == "history":
                    kind_badge = "🕒 History"
                    kind_style = "bold yellow" if is_active else "dim yellow"
                else:
                    kind_badge = "✨ Featured"
                    kind_style = "bold green" if is_active else "dim green"

                trunc_title = truncate_str(itm.title, col_title)
                trunc_sub = truncate_str(itm.subtitle, col_sub)
                trunc_extra = truncate_str(itm.extra, col_extra)

                if is_active:
                    items_table.add_row(
                        "[bold cyan]▶[/bold cyan]",
                        f"[{kind_style}]{kind_badge}[/{kind_style}]",
                        f"[bold bright_white]{trunc_title}[/bold bright_white]",
                        f"[bold bright_yellow]{trunc_sub}[/bold bright_yellow]",
                        f"[bold cyan]{trunc_extra}[/bold cyan]",
                    )
                else:
                    items_table.add_row(
                        " ",
                        f"[{kind_style}]{kind_badge}[/{kind_style}]",
                        f"[white]{trunc_title}[/white]",
                        f"[dim yellow]{trunc_sub}[/dim yellow]",
                        f"[dim cyan]{trunc_extra}[/dim cyan]",
                    )
            
            # Fill empty rows if visible_items < PAGE_SIZE to keep box height strictly constant
            for _ in range(PAGE_SIZE - len(visible_items)):
                items_table.add_row(" ", "", "", "", "")
        else:
            items_table.add_row(
                " ",
                "",
                "[dim]No matching results found[/dim]",
                "",
                "",
            )
            for _ in range(PAGE_SIZE - 1):
                items_table.add_row(" ", "", "", "", "")

        # Dropdown Title with position and pagination status
        spinner = SPINNER_FRAMES[int(time.time() * 10) % len(SPINNER_FRAMES)]
        if is_loading_more:
            res_title = f"[dim]Results ({selected_idx + 1}/{len(items)})  [bold bright_cyan]{spinner} Loading more...[/bold bright_cyan][/dim]"
        elif query:
            scroll_hint = ""
            if scroll_offset + PAGE_SIZE < len(items):
                scroll_hint = " [cyan]▼ Scroll for more[/cyan]"
            res_title = f"[dim]Results ({selected_idx + 1}/{len(items)}){scroll_hint}[/dim]"
        else:
            res_title = "[dim]Quick Picks & Recent History[/dim]"

        dropdown_panel = Panel(
            items_table,
            title=res_title,
            title_align="left",
            box=box.ROUNDED,
            border_style="blue",
            width=panel_width,
            padding=(0, 1),
        )

    # 4. Minimalist Footer Shortcuts & Scroll Range
    footer = Align.center(
        Text.from_markup(
            "[dim white]Scroll [bold cyan]↑/↓[/bold cyan]   [dim]•[/dim]   Play [bold cyan]Enter[/bold cyan]   [dim]•[/dim]   Filter [bold cyan]Tab[/bold cyan]   [dim]•[/dim]   Exit [bold cyan]Esc[/bold cyan][/dim white]"
        )
    )

    # 5. Vertical Centering Calculation
    content_height = 17
    top_pad = max(1, (console_height - content_height) // 2)

    elements = []
    if top_pad > 1:
        elements.append(Text("\n" * (top_pad - 1)))
    elements.extend([
        header,
        Text(""),
        Align.center(search_panel),
        Align.center(dropdown_panel),
        Text(""),
        footer,
    ])

    return Group(*elements)


def run_home_view() -> Optional[Tuple[str, Any]]:
    """Interactive loop for the OpenCode-styled home view with indefinite async scrolling."""
    console = Console()

    query = ""
    filter_modes = ["All", "Tracks", "Playlists"]
    filter_idx = 0
    selected_idx = 0
    scroll_offset = 0

    items: List[DropdownItem] = get_default_items()
    seen_ids: Set[str] = set()
    current_limit = 15
    is_searching = False
    is_loading_more = False
    has_more = True

    last_key_time = 0.0
    last_searched_query = ""
    last_searched_mode = "All"
    lock = threading.Lock()
    running = True

    # Background initial search debounced worker
    def initial_search_worker():
        nonlocal items, is_searching, last_searched_query, last_searched_mode, seen_ids, current_limit, has_more, scroll_offset, selected_idx
        while running:
            time.sleep(0.04)
            current_q = query.strip()
            current_mode = filter_modes[filter_idx]

            # If user cleared the query, restore default items immediately
            if not current_q:
                if last_searched_query != "":
                    with lock:
                        items = get_default_items()
                        seen_ids.clear()
                        current_limit = 15
                        has_more = True
                        last_searched_query = ""
                        last_searched_mode = current_mode
                        is_searching = False
                        scroll_offset = 0
                        selected_idx = 0
                continue

            # Check if query or filter mode changed and debounce elapsed (220ms)
            if (current_q != last_searched_query or current_mode != last_searched_mode) and (time.time() - last_key_time > 0.22):
                new_seen = set()
                new_items = fetch_dropdown_results(current_q, current_mode, limit=15, seen_ids=new_seen)
                with lock:
                    items = new_items
                    seen_ids = new_seen
                    current_limit = 15
                    has_more = len(new_items) > 0
                    last_searched_query = current_q
                    last_searched_mode = current_mode
                    is_searching = False
                    scroll_offset = 0
                    selected_idx = 0

    # Background async pagination load-more worker
    def load_more_worker(target_q: str, target_mode: str):
        nonlocal items, is_loading_more, has_more, current_limit
        with lock:
            if is_loading_more or not has_more:
                return
            is_loading_more = True

        next_limit = current_limit + 20
        new_items = fetch_dropdown_results(target_q, target_mode, limit=next_limit, seen_ids=seen_ids)
        with lock:
            if new_items:
                items.extend(new_items)
                current_limit = next_limit
            else:
                has_more = False
            is_loading_more = False

    search_thread = threading.Thread(target=initial_search_worker, daemon=True)
    search_thread.start()

    console.clear()

    with KeyReader() as key_reader:
        with Live(console=console, refresh_per_second=15, transient=True) as live:
            while True:
                cursor_on = (int(time.time() * 2) % 2) == 0
                term_size = shutil.get_terminal_size((80, 24))
                term_w = term_size.columns
                term_h = term_size.lines

                with lock:
                    curr_items = list(items)
                    searching = is_searching
                    loading_more = is_loading_more

                # Adjust viewport scroll window
                if selected_idx < scroll_offset:
                    scroll_offset = selected_idx
                elif selected_idx >= scroll_offset + PAGE_SIZE:
                    scroll_offset = selected_idx - PAGE_SIZE + 1

                screen = render_home_screen(
                    query=query,
                    cursor_on=cursor_on,
                    filter_mode=filter_modes[filter_idx],
                    items=curr_items,
                    selected_idx=selected_idx,
                    scroll_offset=scroll_offset,
                    is_searching=searching,
                    is_loading_more=loading_more,
                    console_width=term_w,
                    console_height=term_h,
                )
                live.update(screen)

                key = key_reader.get_key(timeout=0.06)
                if not key:
                    continue

                if key in ("escape", "quit"):
                    running = False
                    return None

                elif key == "up":
                    if curr_items:
                        selected_idx = max(0, selected_idx - 1)

                elif key == "down":
                    if curr_items:
                        selected_idx = min(len(curr_items) - 1, selected_idx + 1)
                        # Asynchronous Infinite Scroll Trigger:
                        # When scrolling down within 3 items of the end, fetch next batch in background!
                        if (
                            query.strip()
                            and selected_idx >= len(curr_items) - 4
                            and has_more
                            and not loading_more
                            and not searching
                        ):
                            threading.Thread(
                                target=load_more_worker,
                                args=(query.strip(), filter_modes[filter_idx]),
                                daemon=True,
                            ).start()

                elif key in ("tab", "\t"):
                    filter_idx = (filter_idx + 1) % len(filter_modes)
                    with lock:
                        if query.strip():
                            is_searching = True
                    last_key_time = time.time()
                    selected_idx = 0
                    scroll_offset = 0

                elif key in ("\r", "\n", "enter"):
                    running = False
                    # If an item in dropdown is active and not searching
                    if not searching and 0 <= selected_idx < len(curr_items):
                        chosen = curr_items[selected_idx]
                        if chosen.kind in ("track", "history"):
                            return ("track", chosen.data)
                        elif chosen.kind == "playlist":
                            return ("playlist", chosen.data)
                        elif chosen.kind == "preset":
                            return ("query", chosen.data)
                    # If raw query entered
                    if query.strip():
                        if is_playlist_url(query):
                            return ("playlist_url", query.strip())
                        if filter_modes[filter_idx] == "Playlists":
                            return ("search_playlist", query.strip())
                        return ("query", query.strip())
                    return None

                elif key in ("\x7f", "\x08", "backspace"):
                    if query:
                        query = query[:-1]
                        with lock:
                            if query.strip():
                                is_searching = True
                            else:
                                is_searching = False
                                items = get_default_items()
                        last_key_time = time.time()
                        selected_idx = 0
                        scroll_offset = 0

                elif key in ("ctrl_u", "\x15"):
                    query = ""
                    with lock:
                        is_searching = False
                        items = get_default_items()
                    last_key_time = time.time()
                    selected_idx = 0
                    scroll_offset = 0

                elif len(key) == 1 and key.isprintable():
                    query += key
                    with lock:
                        is_searching = True
                    last_key_time = time.time()
                    selected_idx = 0
                    scroll_offset = 0
