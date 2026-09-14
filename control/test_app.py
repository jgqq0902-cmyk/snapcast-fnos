import unittest
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import (
    ControlError,
    LibraryIndex,
    LIBRARY_INDEX,
    clamp_int,
    decode_opaque_id,
    library_browse,
    library_detail,
    mpd_escape,
    opaque_id,
    parse_mpd,
    parse_mpd_records,
    parse_lyrics,
    parse_playlist_import,
    playlist_name,
    resolve_playlist_uris,
    normalize_library_path,
    should_recover_remote,
    song_payload,
)


class ControlHelpersTest(unittest.TestCase):
    def test_parse_mpd_preserves_repeated_keys(self):
        self.assertEqual(
            parse_mpd(["Artist: A", "Artist: B", "state: play"]),
            {"Artist": ["A", "B"], "state": "play"},
        )

    def test_clamp_int_validates_bounds(self):
        self.assertEqual(clamp_int("25", 0, 100, "volume"), 25)
        with self.assertRaises(ControlError):
            clamp_int(101, 0, 100, "volume")

    def test_mpd_escape_blocks_command_injection(self):
        self.assertEqual(mpd_escape('A "song"\\x'), '"A \\"song\\"\\\\x"')
        with self.assertRaises(ControlError):
            mpd_escape("song\nstop")

    def test_parse_mpd_records_groups_songs(self):
        self.assertEqual(
            parse_mpd_records(
                ["file: a.flac", "Title: A", "Artist: One", "file: b.mp3", "Title: B"],
                "file",
            ),
            [
                {"file": "a.flac", "Title": "A", "Artist": "One"},
                {"file": "b.mp3", "Title": "B"},
            ],
        )

    def test_remote_recovery_requires_network_error(self):
        song = {"file": "https://cdn.example/song.mp4"}
        self.assertTrue(should_recover_remote({"state": "stop", "error": "partial file", "songid": "7"}, song))
        self.assertFalse(should_recover_remote({"state": "stop", "songid": "7"}, song))
        self.assertFalse(should_recover_remote({"state": "stop", "error": "decode", "songid": "7"}, {"file": "local.flac"}))

    def test_library_path_is_confined_to_mounted_root(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "music").mkdir()
            self.assertEqual(normalize_library_path("music", root)[0], "music")
            self.assertEqual(normalize_library_path("/vol1/1000/music", root)[0], "music")
            with self.assertRaises(ControlError):
                normalize_library_path("../outside", root)

    def test_song_payload_has_stable_fallbacks(self):
        self.assertEqual(
            song_payload({"file": "Artist/Album/track.flac"})["title"],
            "track",
        )
        self.assertEqual(
            song_payload({"file": "track.flac"})["artist"],
            "未知歌手",
        )

    def test_opaque_library_id_round_trips_and_rejects_wrong_kind(self):
        item_id = opaque_id("album", "Artist", "Album", "2026")
        self.assertEqual(decode_opaque_id(item_id, "album"), ["Artist", "Album", "2026"])
        with self.assertRaises(ControlError):
            decode_opaque_id(item_id, "artist")

    def test_album_view_distinguishes_same_title_by_artist(self):
        songs = [
            {**song_payload({"file": "a.flac", "Artist": "甲", "Album": "同名"}), "date": ""},
            {**song_payload({"file": "b.flac", "Artist": "乙", "Album": "同名"}), "date": ""},
        ]
        with patch.object(LIBRARY_INDEX, "refresh", return_value=songs):
            page = library_browse("albums")
            detail = library_detail("album", page["items"][0]["id"])
        self.assertEqual(page["total"], 2)
        self.assertEqual(len({item["id"] for item in page["items"]}), 2)
        self.assertEqual(len(detail["tracks"]), 1)

    def test_lrc_parser_supports_multiple_timestamps(self):
        parsed = parse_lyrics("[00:01.50][00:03.25]一句\n[ar:歌手]")
        self.assertEqual(parsed["kind"], "synced")
        self.assertEqual([line["time"] for line in parsed["lines"]], [1.5, 3.25])

    def test_library_page_searches_and_paginates(self):
        index = LibraryIndex()
        songs = [
            {"title": "Alpha", "artist": "One", "album": "First", "file": "a.flac"},
            {"title": "Beta", "artist": "Two", "album": "Second", "file": "b.flac"},
        ]
        with patch.object(index, "refresh", return_value=songs):
            page = index.page("two", 0, 1)
        self.assertEqual(page["total"], 1)
        self.assertEqual(page["items"][0]["title"], "Beta")
        self.assertFalse(page["hasMore"])

    def test_imports_m3u_and_pls_in_order(self):
        self.assertEqual(
            parse_playlist_import("#EXTM3U\n#EXTINF:1,A\na.flac\nb.mp3"),
            ["a.flac", "b.mp3"],
        )
        self.assertEqual(
            parse_playlist_import("[playlist]\nFile2=b.mp3\nFile1=a.flac"),
            ["a.flac", "b.mp3"],
        )

    def test_playlist_name_rejects_paths(self):
        self.assertEqual(playlist_name("收藏"), "收藏")
        with self.assertRaises(ControlError):
            playlist_name("../escape")

    def test_playlist_paths_map_to_mpd_library(self):
        library = [
            {"file": "自然卷/C'est La Vie/10 How Much.flac"},
            {"file": "阿杜/坚持到底/阿杜 - 坚持到底.flac"},
        ]
        resolved, skipped = resolve_playlist_uris(
            [
                "/music/自然卷/C'est La Vie/10 How Much.flac",
                r"D:\\Music\\lxmusic\\阿杜 - 坚持到底.flac",
                "/music/missing.flac",
            ],
            library,
        )
        self.assertEqual(resolved, [library[0]["file"], library[1]["file"]])
        self.assertEqual(skipped, ["/music/missing.flac"])

    def test_playlist_does_not_guess_duplicate_basenames(self):
        library = [{"file": "A/song.flac"}, {"file": "B/song.flac"}]
        resolved, skipped = resolve_playlist_uris(["C:/old/song.flac"], library)
        self.assertEqual(resolved, [])
        self.assertEqual(skipped, ["C:/old/song.flac"])


if __name__ == "__main__":
    unittest.main()
