"""Unit and integration tests for offline mode in music-cli."""

import os
import shutil
import sys
import tempfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from music.config import set_config_val
from music.lyrics import fetch_lyrics, parse_lrc
from music.offline import (
    clear_all_offline_data,
    delete_offline_collection,
    delete_offline_track,
    format_bytes,
    get_downloads_dir,
    get_lyrics_dir,
    get_offline_collection,
    get_offline_collection_tracks,
    get_offline_lyrics_path,
    get_offline_stats,
    get_offline_track,
    get_offline_track_path,
    get_tracks_dir,
    init_offline_db,
    is_offline_mode_enabled,
    is_track_offline,
    list_offline_collections,
    list_offline_tracks,
    sanitize_filename,
    save_offline_collection,
    save_offline_track,
)
from music.search import (
    AlbumItem,
    PlaylistItem,
    SongItem,
    get_album_tracks,
    get_playlist_tracks,
    resolve_audio_stream_url,
    search_albums,
    search_music,
    search_playlists,
)


def test_offline_helpers():
    """Verify filename sanitization, byte formatting, and directory generation."""
    assert sanitize_filename("Artist / Track : Name ? *") == "Artist Track Name"
    assert sanitize_filename('AC/DC: "Back in Black"') == "ACDC Back in Black"
    assert format_bytes(512) == "512.0 B"
    assert format_bytes(1024 * 1024 * 3.5) == "3.5 MB"
    assert format_bytes(1024 * 1024 * 1024 * 1.2) == "1.2 GB"

    d_dir = get_downloads_dir()
    t_dir = get_tracks_dir()
    l_dir = get_lyrics_dir()
    assert d_dir.exists()
    assert t_dir.exists()
    assert l_dir.exists()
    print("✓ Offline helpers & path tests passed")


def test_offline_track_and_collection_db():
    """Test full CRUD operations on offline_tracks and offline_collections."""
    init_offline_db()
    clear_all_offline_data(delete_files=False)

    # 1. Create dummy audio file on disk
    dummy_file = get_tracks_dir() / "Test_Artist_-_Test_Track_[off_12345].mp3"
    with open(dummy_file, "wb") as f:
        f.write(b"ID3" + b"\x00" * 2048)  # fake audio header + bytes

    song = SongItem(
        title="Test Track",
        artist="Test Artist",
        album="Test Album",
        duration="03:30",
        duration_seconds=210,
        video_id="off_12345",
        url="https://www.youtube.com/watch?v=off_12345",
    )

    # 2. Save track
    save_offline_track(song, str(dummy_file), os.path.getsize(dummy_file), "mp3")

    assert is_track_offline("off_12345") is True
    assert get_offline_track_path("off_12345") == str(dummy_file.resolve())

    loaded = get_offline_track("off_12345")
    assert loaded is not None
    assert loaded.title == "Test Track"
    assert loaded.artist == "Test Artist"
    assert loaded.video_id == "off_12345"

    # 3. Save Playlist collection
    save_offline_collection(
        collection_id="PL_offline_test",
        collection_type="playlist",
        title="Offline Chill Mix",
        author="Music CLI",
        track_ids=["off_12345"],
    )

    p_cols = list_offline_collections("playlist")
    assert len(p_cols) >= 1
    assert any(p["id"] == "PL_offline_test" for p in p_cols)

    col, col_tracks = get_offline_collection_tracks("PL_offline_test")
    assert col is not None
    assert col["title"] == "Offline Chill Mix"
    assert len(col_tracks) == 1
    assert col_tracks[0].video_id == "off_12345"

    # 4. Save Album collection
    save_offline_collection(
        collection_id="MPREb_album_test",
        collection_type="album",
        title="Offline Masterpiece",
        author="Test Artist",
        track_ids=["off_12345"],
    )

    a_cols = list_offline_collections("album")
    assert len(a_cols) >= 1
    assert any(a["id"] == "MPREb_album_test" for a in a_cols)

    # 5. Verify stats
    stats = get_offline_stats()
    assert stats["total_tracks"] >= 1
    assert stats["total_playlists"] >= 1
    assert stats["total_albums"] >= 1
    assert stats["total_bytes"] > 0

    # 6. Test delete
    ok_del_t = delete_offline_track("off_12345")
    assert ok_del_t is True
    assert is_track_offline("off_12345") is False
    assert not dummy_file.exists()

    ok_del_p = delete_offline_collection("PL_offline_test")
    assert ok_del_p is True
    assert get_offline_collection("PL_offline_test") is None

    ok_del_a = delete_offline_collection("MPREb_album_test")
    assert ok_del_a is True
    assert get_offline_collection("MPREb_album_test") is None

    print("✓ Offline database & collection CRUD tests passed")


def test_offline_playback_resolution():
    """Verify resolve_audio_stream_url immediately returns local file path for downloaded tracks."""
    # Create test track and file
    dummy_file = get_tracks_dir() / "Resolved_Offline_Track_[off_res_99].mp3"
    with open(dummy_file, "wb") as f:
        f.write(b"MPEG" + b"\x00" * 4096)

    song = SongItem(
        title="Instant Offline Song",
        artist="Offline Artist",
        album="Zero Buffering",
        duration="02:45",
        duration_seconds=165,
        video_id="off_res_99",
        url="https://www.youtube.com/watch?v=off_res_99",
    )
    save_offline_track(song, str(dummy_file), os.path.getsize(dummy_file), "mp3")

    # Call resolve_audio_stream_url
    resolved_path = resolve_audio_stream_url(song)
    assert resolved_path == str(dummy_file.resolve()), f"Expected local path, got: {resolved_path}"

    # Also resolve by string video ID or URL
    resolved_by_id = resolve_audio_stream_url("off_res_99")
    assert resolved_by_id == str(dummy_file.resolve())

    # Cleanup
    delete_offline_track("off_res_99")
    print("✓ Offline zero-latency playback resolution tests passed")


def test_offline_lyrics_integration():
    """Verify time-synchronized lyrics load locally from disk when offline."""
    lrc_file = get_lyrics_dir() / "off_lyrics_1.lrc"
    sample_lrc = (
        "[00:05.00]This is line one offline\n"
        "[00:15.50]This is line two offline\n"
        "[00:25.00]Offline karaoke rocks!\n"
    )
    with open(lrc_file, "w", encoding="utf-8") as f:
        f.write(sample_lrc)

    assert get_offline_lyrics_path("off_lyrics_1") == str(lrc_file.resolve())

    # fetch_lyrics should read from disk without network
    lyrics_data = fetch_lyrics(
        title="Offline Song",
        artist="Offline Artist",
        duration_sec=30,
        video_id="off_lyrics_1",
    )
    assert lyrics_data is not None
    assert lyrics_data.is_synced is True
    assert len(lyrics_data.lines) == 3
    assert lyrics_data.lines[0].text == "This is line one offline"
    assert lyrics_data.lines[2].text == "Offline karaoke rocks!"

    if lrc_file.exists():
        lrc_file.unlink()
    print("✓ Offline synchronized lyrics integration tests passed")


def test_offline_search_and_collections():
    """Verify search fallbacks to offline collections when offline mode is set."""
    dummy_file = get_tracks_dir() / "Parachutes_Track_[para_1].mp3"
    with open(dummy_file, "wb") as f:
        f.write(b"AUDIO" + b"\x00" * 1024)

    song = SongItem(
        title="Yellow Offline",
        artist="Coldplay Offline",
        album="Parachutes",
        duration="04:29",
        duration_seconds=269,
        video_id="para_1",
        url="https://www.youtube.com/watch?v=para_1",
    )
    save_offline_track(song, str(dummy_file), os.path.getsize(dummy_file), "mp3")

    save_offline_collection(
        collection_id="coldplay_pl_1",
        collection_type="playlist",
        title="Coldplay Best Of Offline",
        author="Coldplay",
        track_ids=["para_1"],
    )

    save_offline_collection(
        collection_id="coldplay_alb_1",
        collection_type="album",
        title="Parachutes Offline",
        author="Coldplay Offline",
        track_ids=["para_1"],
    )

    # Force offline mode in config
    set_config_val("offline_mode", True)
    assert is_offline_mode_enabled() is True

    # 1. search_music returns offline track
    songs = search_music("Yellow Offline", limit=3)
    assert len(songs) >= 1
    assert any(s.video_id == "para_1" for s in songs)

    # 2. search_playlists returns offline playlist
    playlists = search_playlists("Coldplay Best Of", limit=3)
    assert len(playlists) >= 1
    assert any(p.playlist_id == "coldplay_pl_1" for p in playlists)

    # 3. get_playlist_tracks returns offline tracks
    p_item, p_tracks = get_playlist_tracks("coldplay_pl_1")
    assert p_item is not None
    assert len(p_tracks) == 1
    assert p_tracks[0].video_id == "para_1"

    # 4. search_albums returns offline album
    albums = search_albums("Parachutes Offline", limit=3)
    assert len(albums) >= 1
    assert any(a.browse_id == "coldplay_alb_1" for a in albums)

    # 5. get_album_tracks returns offline album tracks
    a_item, a_tracks = get_album_tracks("coldplay_alb_1")
    assert a_item is not None
    assert len(a_tracks) == 1
    assert a_tracks[0].video_id == "para_1"

    # Reset offline mode config
    set_config_val("offline_mode", False)

    # Cleanup
    delete_offline_track("para_1")
    delete_offline_collection("coldplay_pl_1")
    delete_offline_collection("coldplay_alb_1")

    print("✓ Offline search and collection fallback tests passed")


def test_download_tracker_and_progress_bars():
    """Verify thread-safe DownloadTracker and UI progress bar cards render without errors."""
    from music.offline import get_download_tracker, DownloadTracker
    from music.ui import render_download_progress_card
    from music.home import render_search_download_banner

    tracker = DownloadTracker()
    assert not tracker.is_active()

    # 1. Single track downloading state
    tracker.start_download("song", "Yellow - Coldplay", total_items=1)
    assert tracker.is_active()
    tracker.update_progress(45.5, speed="2.1 MiB/s", eta="00:06")
    snap1 = tracker.get_snapshot()
    assert snap1["state"] == "downloading"
    assert snap1["percent"] == 45.5
    assert snap1["speed"] == "2.1 MiB/s"

    card1 = render_download_progress_card(snap1, width=70)
    assert card1 is not None
    banner1 = render_search_download_banner(snap1, width=70)
    assert banner1 is not None

    # 2. Batch album downloading state
    tracker.start_download("album", "Parachutes", total_items=10)
    tracker.update_track(3, "Yellow", track_percent=50.0, speed="3.4 MiB/s", eta="00:15")
    snap2 = tracker.get_snapshot()
    assert snap2["state"] == "downloading"
    assert snap2["current_index"] == 3
    assert snap2["total_items"] == 10
    # base is 20%, item contribution is 5% -> 25%
    assert 24.0 <= snap2["percent"] <= 26.0

    card2 = render_download_progress_card(snap2, width=70)
    assert card2 is not None
    banner2 = render_search_download_banner(snap2, width=70)
    assert banner2 is not None

    # 3. Finished state (persists for confirmation)
    tracker.finish(True, "✓ Downloaded 10/10 tracks for Parachutes")
    assert tracker.is_active()  # still active within 4 seconds window
    snap3 = tracker.get_snapshot()
    assert snap3["state"] == "finished"
    assert snap3["percent"] == 100.0

    card3 = render_download_progress_card(snap3, width=70)
    assert card3 is not None
    banner3 = render_search_download_banner(snap3, width=70)
    assert banner3 is not None

    # 4. Error state
    tracker.finish(False, "✗ Download timed out")
    snap4 = tracker.get_snapshot()
    assert snap4["state"] == "error"
    card4 = render_download_progress_card(snap4, width=70)
    assert card4 is not None

    print("✓ Persistent download tracker & progress bar rendering tests passed")


if __name__ == "__main__":
    test_offline_helpers()
    test_offline_track_and_collection_db()
    test_offline_playback_resolution()
    test_offline_lyrics_integration()
    test_offline_search_and_collections()
    test_download_tracker_and_progress_bars()
    print("\n🎉 ALL OFFLINE MODE TESTS PASSED!")
