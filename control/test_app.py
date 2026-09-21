import unittest
import sys
import json
import threading
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from http.server import ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import app as app_module
from app import (
    ControlError,
    Handler,
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
    read_limited,
    resolve_playlist_uris,
    normalize_library_path,
    normalized_snapcast_state,
    login_allowed,
    record_login_failure,
    run_player_action,
    server_playlist_files,
    should_recover_remote,
    song_payload,
    source_descriptor,
    create_group,
    merge_groups,
    set_client_name,
    set_group_members,
    set_group_name,
    set_zone_volume,
    stop_all_sources,
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

    def test_queue_play_position_does_not_clear_queue(self):
        with patch("app.mpd_command", return_value=[]) as command:
            run_player_action({"action": "play-position", "position": 1})
        command.assert_called_once_with("play 1")

    def test_playlist_position_loads_then_plays_selected_track(self):
        with patch("app.mpd_command", return_value=[]) as command:
            run_player_action({"action": "playlist-play-position", "name": "收藏", "position": 3})
        self.assertEqual(
            [call.args[0] for call in command.call_args_list],
            ["clear", 'load "收藏"', "play 3"],
        )

    def test_source_descriptor_exposes_type_and_capabilities(self):
        airplay = source_descriptor({"id": "Airplay", "status": "playing"})
        local = source_descriptor({"id": "DLNA", "status": "idle"})
        self.assertEqual(airplay["sourceType"], "airplay")
        self.assertFalse(airplay["capabilities"]["seek"])
        self.assertEqual(local["sourceType"], "mpd")
        self.assertTrue(local["capabilities"]["queue"])

    def test_read_limited_rejects_large_files(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "cover.jpg"
            path.write_bytes(b"12345")
            with self.assertRaises(ControlError):
                read_limited(path, 4, "封面文件")

    def test_playlist_scan_uses_cache_until_forced(self):
        with TemporaryDirectory() as directory, patch.object(app_module, "LIBRARY_ROOT", Path(directory)):
            first = Path(directory) / "first.m3u8"
            first.write_text("a.flac", encoding="utf-8")
            app_module.PLAYLIST_SCAN_CACHE = (0.0, [])
            self.assertEqual([item["name"] for item in server_playlist_files()], ["first"])
            first.unlink()
            second = Path(directory) / "second.m3u8"
            second.write_text("b.flac", encoding="utf-8")
            self.assertEqual([item["name"] for item in server_playlist_files()], ["first"])
            self.assertEqual([item["name"] for item in server_playlist_files(True)], ["second"])

    def test_login_rate_limit_expires_after_window(self):
        app_module.LOGIN_ATTEMPTS.clear()
        for offset in range(app_module.LOGIN_LIMIT):
            record_login_failure("192.0.2.8", now=100 + offset)
        self.assertFalse(login_allowed("192.0.2.8", now=110)[0])
        self.assertTrue(login_allowed("192.0.2.8", now=200)[0])

    def test_snapcast_normalization_preserves_two_independent_zones(self):
        server = {
            "server": {
                "streams": [
                    {"id": "Airplay", "status": "idle", "uri": {"query": {}}},
                    {"id": "DLNA", "status": "playing", "uri": {"query": {}}},
                ],
                "groups": [
                    {"id": "g1", "name": "客厅", "stream_id": "Airplay", "clients": []},
                    {"id": "g2", "name": "书房", "stream_id": "DLNA", "clients": []},
                ],
            }
        }
        with patch("app.snap_rpc", return_value=server):
            state = normalized_snapcast_state()
        self.assertEqual([(group["id"], group["streamId"]) for group in state["groups"]], [("g1", "Airplay"), ("g2", "DLNA")])

    def test_snapcast_group_volume_tracks_loudest_connected_client(self):
        server = {"server": {"streams": [], "groups": [{
            "id": "g1", "stream_id": "Default", "clients": [
                {"id": "a", "connected": True, "config": {"volume": {"percent": 80, "muted": False}}},
                {"id": "b", "connected": True, "config": {"volume": {"percent": 40, "muted": False}}},
                {"id": "offline", "connected": False, "config": {"volume": {"percent": 100, "muted": False}}},
            ],
        }]}}
        with patch("app.snap_rpc", return_value=server):
            state = normalized_snapcast_state()
        self.assertEqual(state["groups"][0]["volume"], 80)

    def test_zone_volume_scales_connected_clients_proportionally(self):
        zones = {
            "groups": [
                {"id": "g1", "clients": [
                    {"id": "a", "connected": True, "volume": 80},
                    {"id": "b", "connected": True, "volume": 40},
                    {"id": "offline", "connected": False, "volume": 60},
                ]},
                {"id": "g2", "clients": [{"id": "c", "connected": True, "volume": 90}]},
            ]
        }
        with patch("app.normalized_snapcast_state", return_value=zones), patch("app.snap_rpc", return_value={}) as rpc:
            set_zone_volume("g1", 50)
        self.assertEqual(
            [call.args for call in rpc.call_args_list],
            [
                ("Client.SetVolume", {"id": "a", "volume": {"muted": False, "percent": 50}}),
                ("Client.SetVolume", {"id": "b", "volume": {"muted": False, "percent": 25}}),
            ],
        )

    def test_zone_volume_from_silence_sets_connected_clients_to_requested_level(self):
        zones = {"groups": [{"id": "g1", "clients": [
            {"id": "a", "connected": True, "volume": 0},
            {"id": "b", "connected": True, "volume": 0},
        ]}]}
        with patch("app.normalized_snapcast_state", return_value=zones), patch("app.snap_rpc", return_value={}) as rpc:
            set_zone_volume("g1", 30)
        self.assertEqual([call.args[1]["volume"]["percent"] for call in rpc.call_args_list], [30, 30])

    @staticmethod
    def snap_state(groups, streams=None):
        return {"groups": groups, "streams": streams or [{"id": "Default", "status": "idle"}]}

    def test_group_and_client_rename_validate_current_state(self):
        state = self.snap_state([{"id": "g1", "name": "客厅", "clients": [{"id": "c1"}]}])
        with patch("app.normalized_snapcast_state", return_value=state), patch("app.snap_rpc", return_value={}) as rpc:
            set_group_name("g1", "影音室")
            set_client_name("c1", "左音箱")
        self.assertEqual(rpc.call_args_list[0].args, ("Group.SetName", {"id": "g1", "name": "影音室"}))
        self.assertEqual(rpc.call_args_list[1].args, ("Client.SetName", {"id": "c1", "name": "左音箱"}))

    def test_group_members_reject_duplicates_and_unknown_clients(self):
        state = self.snap_state([{"id": "g1", "clients": [{"id": "c1"}]}])
        with patch("app.normalized_snapcast_state", return_value=state):
            with self.assertRaises(ControlError):
                set_group_members("g1", ["c1", "c1"])
            with self.assertRaises(ControlError):
                set_group_members("g1", ["missing"])

    def test_create_group_splits_anchor_then_moves_selected_clients(self):
        initial = self.snap_state([
            {"id": "g1", "name": "A", "clients": [{"id": "c1"}, {"id": "c2"}]},
            {"id": "g2", "name": "B", "clients": [{"id": "c3"}]},
        ])
        split = self.snap_state([
            {"id": "g1", "name": "A", "clients": [{"id": "c2"}]},
            {"id": "g3", "name": "播放组", "clients": [{"id": "c1"}]},
            {"id": "g2", "name": "B", "clients": [{"id": "c3"}]},
        ])
        final = self.snap_state([{"id": "g3", "name": "新组", "clients": [{"id": "c1"}, {"id": "c3"}]}])
        with patch("app.normalized_snapcast_state", side_effect=[initial, split, final]), patch("app.snap_rpc", return_value={}) as rpc:
            create_group("新组", ["c1", "c3"], "Default")
        calls = [call.args for call in rpc.call_args_list]
        self.assertEqual(calls[0], ("Group.SetClients", {"id": "g1", "clients": ["c2"]}))
        self.assertIn(("Group.SetClients", {"id": "g3", "clients": ["c1", "c3"]}), calls)
        self.assertIn(("Group.SetName", {"id": "g3", "name": "新组"}), calls)
        self.assertIn(("Group.SetStream", {"id": "g3", "stream_id": "Default"}), calls)

    def test_merge_groups_moves_members_and_protects_last_group(self):
        one = self.snap_state([{"id": "g1", "clients": [{"id": "c1"}]}])
        with patch("app.normalized_snapcast_state", return_value=one):
            with self.assertRaises(ControlError):
                merge_groups("g1", "g2")
        two = self.snap_state([
            {"id": "g1", "clients": [{"id": "c1"}]},
            {"id": "g2", "clients": [{"id": "c2"}]},
        ])
        with patch("app.normalized_snapcast_state", return_value=two), patch("app.snap_rpc", return_value={}) as rpc:
            merge_groups("g1", "g2")
        rpc.assert_called_once_with("Group.SetClients", {"id": "g2", "clients": ["c2", "c1"]})

    def test_stop_all_keeps_queue_and_skips_airplay_restart_when_idle(self):
        idle = self.snap_state([], [{"id": "Airplay", "status": "idle"}, {"id": "DLNA", "status": "idle"}])
        with patch("app.mpd_command", return_value=[]) as mpd, patch("app.normalized_snapcast_state", return_value=idle), patch("app.subprocess.run") as run:
            result = stop_all_sources()
        mpd.assert_called_once_with("stop")
        run.assert_not_called()
        self.assertTrue(result["mpdStopped"])
        self.assertTrue(result["airplayDropped"])

    def test_stop_all_reports_airplay_helper_failure_without_masking_mpd(self):
        playing = self.snap_state([], [{"id": "Airplay", "status": "playing"}])
        completed = app_module.subprocess.CompletedProcess([], 1, "", "drop failed")
        with patch("app.mpd_command", return_value=[]), patch("app.normalized_snapcast_state", return_value=playing), patch("app.subprocess.run", return_value=completed):
            result = stop_all_sources()
        self.assertTrue(result["mpdStopped"])
        self.assertFalse(result["airplayDropped"])
        self.assertIn("AirPlay", result["errors"][0])


class AuthHttpTest(unittest.TestCase):
    def setUp(self):
        app_module.SESSIONS.clear()
        app_module.LOGIN_ATTEMPTS.clear()
        self.settings = patch.multiple(
            app_module,
            AUTH_ENABLED=True,
            CONTROL_USERNAME="admin",
            CONTROL_PASSWORD="correct-password",
            SESSION_TTL=3600,
        )
        self.settings.start()
        self.state = patch.object(app_module, "combined_state", return_value={"snapcast": {}, "player": {}, "errors": []})
        self.state.start()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.state.stop()
        self.settings.stop()

    def request(self, path, payload=None, opener=None):
        data = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(
            self.base + path,
            data=data,
            headers={"Content-Type": "application/json"} if data else {},
        )
        return opener.open(request, timeout=2) if opener else urllib.request.urlopen(request, timeout=2)

    def test_api_requires_login_and_rejects_wrong_password(self):
        with self.assertRaises(urllib.error.HTTPError) as state_error:
            self.request("/api/state")
        self.assertEqual(state_error.exception.code, 401)
        with self.assertRaises(urllib.error.HTTPError) as login_error:
            self.request("/api/login", {"username": "admin", "password": "wrong"})
        self.assertEqual(login_error.exception.code, 401)

    def test_api_rejects_unauthenticated_post(self):
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request("/api/player/action", {"action": "stop"})
        self.assertEqual(error.exception.code, 401)

    def test_unconfigured_auth_does_not_allow_login(self):
        with patch.object(app_module, "CONTROL_PASSWORD", ""):
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.request("/api/login", {"username": "admin", "password": ""})
        self.assertEqual(error.exception.code, 503)

    def test_oversized_json_body_is_rejected(self):
        request = urllib.request.Request(
            self.base + "/api/login",
            data=b"{}",
            headers={"Content-Type": "application/json", "Content-Length": "1100001"},
        )
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request, timeout=2)
        self.assertEqual(error.exception.code, 400)

    def test_login_session_allows_api_and_expiry_revokes_it(self):
        response = self.request("/api/login", {"username": "admin", "password": "correct-password"}, self.opener)
        self.assertIn("HttpOnly", response.headers["Set-Cookie"])
        self.assertIn("SameSite=Strict", response.headers["Set-Cookie"])
        self.assertEqual(self.request("/api/state", opener=self.opener).status, 200)
        for token in list(app_module.SESSIONS):
            app_module.SESSIONS[token] = 0
        with self.assertRaises(urllib.error.HTTPError) as expired:
            self.request("/api/state", opener=self.opener)
        self.assertEqual(expired.exception.code, 401)

    def test_lan_mode_allows_api_without_session(self):
        with patch.object(app_module, "AUTH_ENABLED", False):
            self.assertEqual(self.request("/api/state").status, 200)

    def test_zone_stream_targets_only_requested_group(self):
        with patch.object(app_module, "AUTH_ENABLED", False), patch("app.snap_rpc", return_value={}) as rpc:
            response = self.request("/api/snapcast/stream", {"groupId": "living-room", "streamId": "DLNA"})
        self.assertEqual(response.status, 200)
        rpc.assert_called_once_with("Group.SetStream", {"id": "living-room", "stream_id": "DLNA"})

    def test_static_modules_are_served_but_traversal_is_not(self):
        response = self.request("/js/api.js")
        self.assertEqual(response.status, 200)
        self.assertIn("javascript", response.headers["Content-Type"])
        index_response = self.request("/")
        self.assertIn("frame-src http://*:1782", index_response.headers["Content-Security-Policy"])
        index = index_response.read().decode("utf-8")
        self.assertIn("设备", index)
        self.assertIn(":1782/", index)
        self.assertIn('data-page="player"', index)
        self.assertNotIn('data-page="music"', index)
        self.assertNotIn('data-page="queue"', index)
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request("/%2e%2e/app.py")
        self.assertEqual(error.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
