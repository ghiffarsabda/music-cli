"""Unit and integration tests for music-cli."""

import time
from music.config import load_config, set_config_val
from music.search import search_music, format_duration, parse_duration_str, SongItem
from music.history import add_to_history, get_history, clear_history
from music.player import MpvPlayer
from music.auth import get_auth_status, logout


def test_duration_helpers():
    assert format_duration(65) == "01:05"
    assert format_duration(3665) == "01:01:05"
    assert format_duration(0) == "00:00"
    assert parse_duration_str("03:45") == 225
    assert parse_duration_str("01:02:03") == 3723
    print("✓ Duration helper tests passed")


def test_history():
    clear_history()
    assert len(get_history()) == 0

    item = SongItem(
        title="Test Song",
        artist="Test Artist",
        album="Test Album",
        duration="03:00",
        duration_seconds=180,
        video_id="test1234567",
        url="https://music.youtube.com/watch?v=test1234567",
    )
    add_to_history(item)
    hist = get_history()
    assert len(hist) == 1
    assert hist[0].title == "Test Song"
    clear_history()
    print("✓ History management tests passed")


def test_auth_status():
    logout()
    status = get_auth_status()
    assert status["mode"] == "none"
    print("✓ Auth status tests passed")


def test_search():
    results = search_music("Rick Astley Never Gonna Give You Up", limit=3)
    assert len(results) > 0, "No search results returned"
    first = results[0]
    assert first.title, "Empty title in search result"
    assert first.video_id, "Empty videoId in search result"
    assert "youtube.com" in first.url
    print(f"✓ Search test passed: Found '{first.title}' by '{first.artist}' (ID: {first.video_id})")


def test_player_ipc():
    player = MpvPlayer(initial_volume=70)
    try:
        player.start()
        assert player.process_is_alive()

        # Check initial volume
        vol = player.get_volume()
        assert vol == 70

        # Change volume
        new_vol = player.adjust_volume(10)
        assert new_vol == 80
        assert player.get_volume() == 80

        # Mute toggle
        player.toggle_mute()
        time.sleep(0.1)
        st = player.get_status()
        assert st["muted"] is True

        player.toggle_mute()
        time.sleep(0.1)
        st = player.get_status()
        assert st["muted"] is False

        print("✓ Player IPC socket tests passed")
    finally:
        player.stop()
        assert not player.process_is_alive()


def test_related_tracks():
    from music.search import get_related_tracks
    tracks = get_related_tracks("lYBUbBu4W08", limit=3)
    assert len(tracks) > 0, "No related tracks returned for autoplay"
    assert tracks[0].video_id != "lYBUbBu4W08", "Current track should not be in related queue"
    assert tracks[0].title, "Related track should have title"
    print(f"✓ Autoplay related tracks test passed: Next up is '{tracks[0].title}' by '{tracks[0].artist}'")


def test_adblock():
    from music.adblock import is_ad_domain, fetch_skip_segments, check_and_skip_ads
    assert is_ad_domain("https://googleads.g.doubleclick.net/pagead/id")
    assert is_ad_domain("https://pagead2.googlesyndication.com/ad")
    assert not is_ad_domain("https://rr4---sn-2uuxa3vh.googlevideo.com/videoplayback")

    # Test segment skipping logic on mock player
    class MockPlayer:
        def __init__(self):
            self.sought = None
        def seek_to(self, target):
            self.sought = target

    p = MockPlayer()
    segments = [{"category": "sponsor", "label": "Sponsor segment", "start": 30.0, "end": 45.0, "duration": 15.0}]
    skipped = set()

    # Time before segment: no skip
    msg = check_and_skip_ads(p, 25.0, segments, skipped)
    assert msg is None
    assert p.sought is None

    # Time inside segment: skips to end!
    msg = check_and_skip_ads(p, 32.5, segments, skipped)
    assert msg is not None
    assert "Sponsor segment" in msg
    assert p.sought == 45.1
    print("✓ Built-in adblocker and SponsorBlock test passed")


def test_lyrics():
    from music.lyrics import parse_lrc, get_lyrics_display_window, LyricsData, LyricLine
    sample_lrc = """[00:05.50] Hello world
[00:10.00] Line two
[00:15.25] Line three"""
    parsed = parse_lrc(sample_lrc)
    assert len(parsed) == 3
    assert parsed[0].timestamp == 5.5
    assert parsed[0].text == "Hello world"
    assert parsed[1].timestamp == 10.0
    assert parsed[2].timestamp == 15.25

    # Test window at 12.0 seconds (Line two is active)
    data = LyricsData(is_synced=True, lines=parsed)
    win, mode = get_lyrics_display_window(data, 12.0)
    assert mode == "synced"
    # Current active line should have yellow indicator
    assert any("▶ Line two" in text for text, _ in win)

    # Test window before song starts (Intro)
    win, mode = get_lyrics_display_window(data, 2.0)
    assert mode == "intro"
    assert any("Instrumental Intro" in text for text, _ in win)

    print("✓ Time-synchronized lyrics engine tests passed")


def test_playlist():
    from music.search import is_playlist_url, extract_playlist_id, search_playlists, get_playlist_tracks
    url = "https://music.youtube.com/playlist?list=PLOzDu-MXXLljymo0oXEkTSLKf5TqxY-JN"
    assert is_playlist_url(url)
    assert extract_playlist_id(url) == "PLOzDu-MXXLljymo0oXEkTSLKf5TqxY-JN"

    p_item, tracks = get_playlist_tracks("PLOzDu-MXXLljymo0oXEkTSLKf5TqxY-JN", limit=5)
    assert p_item is not None
    assert p_item.title
    assert len(tracks) > 0
    assert tracks[0].video_id
    print(f"✓ Playlist loading tests passed: '{p_item.title}' ({len(tracks)} tracks loaded)")


def test_home_view():
    from music.home import get_default_items, render_home_screen, fetch_dropdown_results
    items = get_default_items()
    assert len(items) >= 4
    for itm in items:
        assert itm.kind in ("history", "preset")
        assert itm.title

    screen = render_home_screen(
        query="lofi",
        cursor_on=True,
        filter_mode="All",
        items=items,
        selected_idx=0,
        scroll_offset=0,
        is_searching=False,
        is_loading_more=False,
        console_width=80,
        console_height=24,
    )
    assert screen is not None

    results = fetch_dropdown_results("lofi", "Tracks")
    assert len(results) > 0
    assert any(r.kind == "track" for r in results)

    # Test Accordion logic
    from music.home import collapse_playlist_accordion, DropdownItem, PlaylistTrackData
    from music.search import SongItem, PlaylistItem

    pl = PlaylistItem("Test PL", "PL001", "Author", 2, "url")
    s1 = SongItem("Track 1", "Artist", "", "03:00", 180, "v1", "u1")
    s2 = SongItem("Track 2", "Artist", "", "03:30", 210, "v2", "u2")
    sample_items = [
        DropdownItem("playlist", pl.title, pl.author, "2 tracks", pl),
        DropdownItem("playlist_track", s1.title, s1.artist, s1.duration, PlaylistTrackData(s1, pl, [s1, s2], 0), parent_playlist_id="PL001", tree_prefix="├─"),
        DropdownItem("playlist_track", s2.title, s2.artist, s2.duration, PlaylistTrackData(s2, pl, [s1, s2], 1), parent_playlist_id="PL001", tree_prefix="└─"),
    ]
    assert len(sample_items) == 3
    collapsed = collapse_playlist_accordion(sample_items, "PL001")
    assert len(collapsed) == 1
    assert collapsed[0].kind == "playlist"

    # Test rendering screen with expanded accordion
    screen_acc = render_home_screen(
        query="lofi",
        cursor_on=True,
        filter_mode="All",
        items=sample_items,
        selected_idx=1,
        scroll_offset=0,
        is_searching=False,
        is_loading_more=False,
        expanded_playlist_id="PL001",
        console_width=80,
        console_height=24,
    )
    assert screen_acc is not None
    print(f"✓ OpenCode-styled home view & accordion tests passed ({len(results)} search results rendered)")


if __name__ == "__main__":
    test_duration_helpers()
    test_history()
    test_auth_status()
    test_search()
    test_player_ipc()
    test_related_tracks()
    test_adblock()
    test_lyrics()
    test_playlist()
    test_home_view()
    print("\n🎉 ALL TESTS PASSED!")
