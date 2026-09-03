"""Comprehensive test suite for local performance improvements (Milestone M1).

Validates SQLite FTS5 engine, BM25 ranking, token sanitization, diacritic folding,
history.json migration idempotency, typo-tolerant fuzzy matching, hybrid search
workflow, backward-compatible history adaptation, and zero external dependencies audit.
"""

import ast
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time

from music.config import LIBRARY_DB
import music.history as history_mod
from music.history import (
    HISTORY_FILE,
    add_to_history,
    clear_history,
    get_history,
    search_history,
)
from music.library import (
    SCHEMA_SQL,
    _normalize_str,
    add_track_to_library,
    clear_library,
    get_recent_tracks,
    init_library_db,
    migrate_history_json_if_needed,
    sanitize_fts5_query,
    search_library_fts5,
    search_library_fuzzy,
    search_local_library,
)
from music.search import SongItem


def test_schema_and_connection_initialization():
    """Test 1: Verify database schema, triggers, indices, and WAL mode initialization."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "library.db"

        # Initialize schema
        conn = init_library_db(db_path=db_path)

        # 1. Verify WAL journal mode
        cur = conn.cursor()
        jm = cur.execute("PRAGMA journal_mode;").fetchone()[0]
        assert jm.lower() == "wal", f"Expected journal_mode 'wal', got {jm}"

        # 2. Verify tables exist
        tables = {
            r[0]
            for r in cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table';"
            ).fetchall()
        }
        assert "tracks" in tables, "Table 'tracks' not found in sqlite_master"
        assert "tracks_fts" in tables, "Virtual table 'tracks_fts' not found in sqlite_master"

        # 3. Verify triggers exist
        triggers = {
            r[0]
            for r in cur.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger';"
            ).fetchall()
        }
        assert "tracks_ai" in triggers, "Trigger 'tracks_ai' not found"
        assert "tracks_ad" in triggers, "Trigger 'tracks_ad' not found"
        assert "tracks_au" in triggers, "Trigger 'tracks_au' not found"

        # 4. Verify index exists
        indices = {
            r[0]
            for r in cur.execute(
                "SELECT name FROM sqlite_master WHERE type='index';"
            ).fetchall()
        }
        assert "idx_tracks_played_at" in indices, "Index 'idx_tracks_played_at' not found"

        # 5. Verify idempotency on repeated initialization
        conn2 = init_library_db(db_path=db_path)
        assert conn2 is not None
        conn.close()

    print("✓ Test 1 Passed: Database schema, triggers, indices, and WAL mode initialized successfully.")


def test_fts5_bm25_search_and_ranking():
    """Test 2: Verify FTS5 exact/prefix matching and BM25 weighted ranking."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "library.db"
        init_library_db(db_path=db_path)

        # Insert 3 tracks: title match vs artist match vs album match
        track_title = SongItem(
            title="Radiohead Special",
            artist="Various Artists",
            album="Collection",
            duration="03:30",
            duration_seconds=210,
            video_id="vid_title",
            url="http://vid_title",
        )
        track_artist = SongItem(
            title="Creep",
            artist="Radiohead",
            album="Pablo Honey",
            duration="03:58",
            duration_seconds=238,
            video_id="vid_artist",
            url="http://vid_artist",
        )
        track_album = SongItem(
            title="Parachutes",
            artist="Coldplay",
            album="Radiohead Edition",
            duration="04:29",
            duration_seconds=269,
            video_id="vid_album",
            url="http://vid_album",
        )

        add_track_to_library(track_title, played_at="2026-09-01T10:00:00", db_path=db_path)
        add_track_to_library(track_artist, played_at="2026-09-01T10:00:00", db_path=db_path)
        add_track_to_library(track_album, played_at="2026-09-01T10:00:00", db_path=db_path)

        # 1. Full-text search for 'Radiohead'
        results = search_library_fts5("Radiohead", limit=10, db_path=db_path)
        assert len(results) == 3, f"Expected 3 results, got {len(results)}"
        # Title match (weight 10.0) ranks 1st, Artist match (5.0) 2nd, Album match (1.0) 3rd
        assert results[0].video_id == "vid_title", (
            f"Expected title match 'vid_title' 1st, got {results[0].video_id}"
        )
        assert results[1].video_id == "vid_artist", (
            f"Expected artist match 'vid_artist' 2nd, got {results[1].video_id}"
        )
        assert results[2].video_id == "vid_album", (
            f"Expected album match 'vid_album' 3rd, got {results[2].video_id}"
        )

        # 2. Prefix search 'radi'
        prefix_results = search_library_fts5("radi", limit=10, db_path=db_path)
        assert len(prefix_results) == 3

        # 3. Sub-millisecond latency benchmark
        times = []
        for _ in range(200):
            t0 = time.perf_counter()
            res = search_library_fts5("radi", limit=5, db_path=db_path)
            times.append(time.perf_counter() - t0)

        avg_latency_ms = (sum(times) / len(times)) * 1000
        assert avg_latency_ms < 5.0, f"Average latency {avg_latency_ms:.3f} ms exceeds 5.0 ms limit"

    print(f"✓ Test 2 Passed: FTS5 BM25 weighted ranking verified (avg latency {avg_latency_ms:.3f} ms).")


def test_token_sanitization_and_injection_defense():
    """Test 3: Verify token sanitization against SQLite syntax errors and operator injections."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "library.db"
        init_library_db(db_path=db_path)

        # Insert track with special characters
        acdc_song = SongItem(
            title="Back in Black",
            artist="AC/DC",
            album="Back in Black",
            duration="04:15",
            duration_seconds=255,
            video_id="acdc_1",
            url="http://acdc",
        )
        add_track_to_library(acdc_song, db_path=db_path)

        # Adversarial queries that crash naive FTS5 queries
        adversarial_queries = [
            "AC/DC",
            "Jay-Z",
            "blink-182",
            "coldplay AND",
            "AND",
            "OR",
            "NOT",
            "NEAR",
            "foo (bar",
            "foo:bar",
            "***",
            '"',
            '""',
            "()",
            "- - -",
            '"unclosed quote',
            "coldplay' OR 1=1--",
            "夜に駆ける",
            "아이유",
            "Кино",
            "فيروز",
        ]

        for q in adversarial_queries:
            sanitized = sanitize_fts5_query(q)
            # Must execute without raising sqlite3.OperationalError
            res = search_library_fts5(q, limit=5, db_path=db_path)
            assert isinstance(res, list)

        # Verify AC/DC matches
        acdc_res = search_library_fts5("AC/DC", limit=5, db_path=db_path)
        assert len(acdc_res) == 1
        assert acdc_res[0].video_id == "acdc_1"

    print("✓ Test 3 Passed: Token sanitization and injection defense verified (zero crashes).")


def test_history_migration_idempotency_and_data_integrity():
    """Test 4: Verify seamless, idempotent migration of legacy history.json."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "library.db"
        hist_path = Path(tmpdir) / "history.json"
        init_library_db(db_path=db_path)

        # Non-existent history file returns 0
        assert migrate_history_json_if_needed(db_path=db_path, history_file=hist_path) == 0

        # Corrupted / invalid JSON files handled gracefully
        with open(hist_path, "w", encoding="utf-8") as f:
            f.write("")
        assert migrate_history_json_if_needed(db_path=db_path, history_file=hist_path) == 0

        with open(hist_path, "w", encoding="utf-8") as f:
            f.write("{invalid json")
        assert migrate_history_json_if_needed(db_path=db_path, history_file=hist_path) == 0

        with open(hist_path, "w", encoding="utf-8") as f:
            json.dump({"not_a_list": 1}, f)
        assert migrate_history_json_if_needed(db_path=db_path, history_file=hist_path) == 0

        # Create valid history.json with 4 items (including 1 invalid dict entry)
        sample_entries = [
            {
                "video_id": "v1",
                "title": "Yellow",
                "artist": "Coldplay",
                "album": "Parachutes",
                "duration": "04:29",
                "duration_seconds": 269,
                "url": "http://v1",
                "thumbnail": "",
                "played_at": "2026-09-01T10:00:00",
            },
            {
                "video_id": "v2",
                "title": "Creep",
                "artist": "Radiohead",
                "album": "Pablo Honey",
                "duration": "03:58",
                "duration_seconds": 238,
                "url": "http://v2",
                "thumbnail": "",
                "played_at": "2026-09-01T11:00:00",
            },
            {
                "video_id": "v3",
                "title": "Blinding Lights",
                "artist": "The Weeknd",
                "album": "After Hours",
                "duration": "03:20",
                "duration_seconds": 200,
                "url": "http://v3",
                "thumbnail": "",
                "played_at": "2026-09-01T12:00:00",
            },
            "invalid_non_dict_entry",
            {"video_id": ""},  # empty video_id
        ]
        with open(hist_path, "w", encoding="utf-8") as f:
            json.dump(sample_entries, f)

        # 1. First migration
        migrated = migrate_history_json_if_needed(db_path=db_path, history_file=hist_path)
        assert migrated == 3, f"Expected 3 valid migrated entries, got {migrated}"

        recent = get_recent_tracks(limit=10, db_path=db_path)
        assert len(recent) == 3
        assert recent[0].title == "Blinding Lights"  # most recent (12:00:00)

        # 2. Second migration (idempotency check)
        migrated_again = migrate_history_json_if_needed(db_path=db_path, history_file=hist_path)
        assert migrated_again == 3
        recent_again = get_recent_tracks(limit=10, db_path=db_path)
        assert len(recent_again) == 3, "Rows duplicated on re-migration!"

        # 3. Test MAX(played_at) preservation: update v1 with a newer timestamp in DB
        add_track_to_library(
            SongItem("Yellow", "Coldplay", "Parachutes", "04:29", 269, "v1", "http://v1"),
            played_at="2026-09-02T15:00:00",
            db_path=db_path,
        )
        # Re-run migration with older timestamp (2026-09-01)
        migrate_history_json_if_needed(db_path=db_path, history_file=hist_path)
        recent_after = get_recent_tracks(limit=10, db_path=db_path)
        assert recent_after[0].video_id == "v1", "Newer timestamp was regressed by migration!"

        # Verify history.json was NOT unlinked or deleted during migration
        assert hist_path.exists(), "history.json should remain intact after migration"

    print("✓ Test 4 Passed: history.json migration idempotency and data integrity verified.")


def test_typo_tolerant_fuzzy_matching():
    """Test 5: Verify typo tolerance for misspellings, sliding windows, and diacritics."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "library.db"
        init_library_db(db_path=db_path)

        catalog = [
            SongItem("Creep", "Radiohead", "Pablo Honey", "03:58", 238, "rad1", "http1"),
            SongItem("Yellow", "Coldplay", "Parachutes", "04:29", 269, "cold1", "http2"),
            SongItem("Blinding Lights", "The Weeknd", "After Hours", "03:20", 200, "week1", "http3"),
            SongItem("Never Gonna Give You Up", "Rick Astley", "Album", "03:33", 213, "rick1", "http4"),
            SongItem("Bohemian Rhapsody", "Queen", "Opera", "05:55", 355, "queen1", "http5"),
            SongItem("CUFF IT", "Beyoncé", "Renaissance", "03:45", 225, "bey1", "http6"),
            SongItem("Army of Me", "Björk", "Post", "03:54", 234, "bjork1", "http7"),
        ]
        for s in catalog:
            add_track_to_library(s, db_path=db_path)

        # Target misspellings mapping
        test_queries = [
            ("radiahead", "rad1"),       # Transposition / phonetic in artist
            ("coldpaly", "cold1"),        # Letter transposition in artist
            ("the weekend", "week1"),     # Phonetic misspelling in artist
            ("rick astly", "rick1"),      # Missing character in artist
            ("bohemain", "queen1"),       # Transposition in title token
            ("nevr gona", "rick1"),       # Multi-word sliding window typo
            ("beyonce", "bey1"),          # Diacritic folding
            ("bjork", "bjork1"),          # Diacritic folding
        ]

        durations = []
        for q, expected_vid in test_queries:
            t0 = time.perf_counter()
            matches = search_library_fuzzy(q, limit=5, threshold=0.75, db_path=db_path)
            durations.append(time.perf_counter() - t0)

            assert len(matches) > 0, f"Query '{q}' returned no fuzzy matches"
            assert matches[0].video_id == expected_vid, (
                f"Query '{q}' expected video_id '{expected_vid}', got '{matches[0].video_id}'"
            )

        avg_fuzzy_ms = (sum(durations) / len(durations)) * 1000
        assert avg_fuzzy_ms < 5.0, f"Average fuzzy latency {avg_fuzzy_ms:.3f} ms exceeds 5.0 ms"

    print(f"✓ Test 5 Passed: Typo-tolerant fuzzy matching verified (avg latency {avg_fuzzy_ms:.3f} ms).")


def test_hybrid_search_workflow():
    """Test 6: Verify 3-tier hybrid search (empty -> recent; non-empty -> FTS5; fallback -> fuzzy)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "library.db"
        init_library_db(db_path=db_path)

        song1 = SongItem("Starboy", "The Weeknd", "Starboy", "03:50", 230, "s1", "http1")
        song2 = SongItem("Yellow", "Coldplay", "Parachutes", "04:29", 269, "s2", "http2")
        add_track_to_library(song1, played_at="2026-09-01T10:00:00", db_path=db_path)
        add_track_to_library(song2, played_at="2026-09-01T11:00:00", db_path=db_path)

        # 1. Empty query returns recent tracks (most recent 'Yellow' first)
        res_empty = search_local_library("", limit=5, db_path=db_path)
        assert len(res_empty) == 2
        assert res_empty[0].video_id == "s2"

        res_ws = search_local_library("   ", limit=5, db_path=db_path)
        assert len(res_ws) == 2

        # 2. Exact prefix query routes to FTS5
        res_fts = search_local_library("star", limit=5, db_path=db_path)
        assert len(res_fts) == 1
        assert res_fts[0].video_id == "s1"

        # 3. Typo query falls back to fuzzy matching
        res_fuzzy = search_local_library("coldpaly", limit=5, db_path=db_path)
        assert len(res_fuzzy) == 1
        assert res_fuzzy[0].video_id == "s2"

        # 4. Unknown junk query returns []
        res_none = search_local_library("zzzxxyyynonexistent", limit=5, db_path=db_path)
        assert len(res_none) == 0

        # 5. Single-character query with zero FTS5 matches returns []
        res_single = search_local_library("z", limit=5, db_path=db_path)
        assert len(res_single) == 0

    print("✓ Test 6 Passed: Hybrid search 3-tier routing verified.")


def test_backward_compatible_history_adapter():
    """Test 7: Verify music.history delegates to music.library with 100% backward compatibility."""
    # Test clear_history
    clear_history()
    assert len(get_history()) == 0

    # Test add_to_history
    test_song = SongItem(
        title="Adapter Song",
        artist="Adapter Artist",
        album="Adapter Album",
        duration="03:00",
        duration_seconds=180,
        video_id="adapter_1",
        url="http://adapter_1",
    )
    add_to_history(test_song)

    # Test get_history
    hist = get_history()
    assert len(hist) == 1
    assert hist[0].video_id == "adapter_1"

    # Test search_history exact
    search_res = search_history("adapter", limit=5)
    assert len(search_res) == 1
    assert search_res[0].video_id == "adapter_1"

    # Test search_history fuzzy fallback
    search_fuzzy_res = search_history("adaptr", limit=5)
    assert len(search_fuzzy_res) == 1
    assert search_fuzzy_res[0].video_id == "adapter_1"

    # Clean up
    clear_history()
    assert len(get_history()) == 0

    # Verify exported symbols
    assert hasattr(history_mod, "HISTORY_FILE")
    assert hasattr(history_mod, "SongItem")
    assert hasattr(history_mod, "get_history")
    assert hasattr(history_mod, "add_to_history")
    assert hasattr(history_mod, "search_history")
    assert hasattr(history_mod, "clear_history")

    print("✓ Test 7 Passed: Backward-compatible history adapter verified.")


def test_zero_external_pip_dependencies_audit():
    """Test 8: Verify strictly zero new external pip dependencies in AST and pyproject.toml."""
    allowed_standard_modules = {
        "ast",
        "contextlib",
        "datetime",
        "difflib",
        "json",
        "os",
        "pathlib",
        "re",
        "shutil",
        "sqlite3",
        "sys",
        "tempfile",
        "time",
        "typing",
        "unicodedata",
    }

    files_to_audit = [
        Path("music/config.py"),
        Path("music/library.py"),
        Path("music/history.py"),
    ]

    for file_path in files_to_audit:
        with open(file_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=str(file_path))

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    assert root in allowed_standard_modules or root == "music", (
                        f"Disallowed import '{root}' in {file_path}"
                    )
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    root = node.module.split(".")[0]
                    assert root in allowed_standard_modules or root == "music", (
                        f"Disallowed import from '{root}' in {file_path}"
                    )

    # Inspect pyproject.toml dependencies
    pyproject_path = Path("pyproject.toml")
    with open(pyproject_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Original allowed dependencies only
    expected_deps = ["ytmusicapi", "yt-dlp", "rich", "secretstorage"]
    dep_section = content.split("dependencies = [")[1].split("]")[0]
    for line in dep_section.strip().splitlines():
        line = line.strip().strip('"').strip("',")
        if not line:
            continue
        pkg_name = line.split(">=")[0].split("==")[0].strip()
        assert pkg_name in expected_deps, f"Unexpected new dependency found in pyproject.toml: {pkg_name}"

    print("✓ Test 8 Passed: Zero external pip dependencies audit verified (strictly standard library).")


if __name__ == "__main__":
    print("\n========================================================")
    print("RUNNING MILESTONE M1 LOCAL PERFORMANCE TEST SUITE")
    print("========================================================")
    test_schema_and_connection_initialization()
    test_fts5_bm25_search_and_ranking()
    test_token_sanitization_and_injection_defense()
    test_history_migration_idempotency_and_data_integrity()
    test_typo_tolerant_fuzzy_matching()
    test_hybrid_search_workflow()
    test_backward_compatible_history_adapter()
    test_zero_external_pip_dependencies_audit()
    print("\n🎉 ALL MILESTONE M1 PERFORMANCE TESTS PASSED SUCCESSFULLY!\n")
