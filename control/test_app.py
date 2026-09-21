import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import app as app_module
from app import (
    ControlError, GroupMutationError, Handler, clamp_int, create_group,
    login_allowed, merge_groups, normalized_snapcast_state, parse_mpd,
    record_login_failure, set_client_name, set_group_members, set_group_name,
    set_zone_volume, song_payload, source_descriptor, stop_all_sources,
)


class ControlHelpersTest(unittest.TestCase):
    def test_parse_mpd_and_song_fallbacks(self):
        self.assertEqual(parse_mpd(["Artist: A", "state: play"]), {"Artist": "A", "state": "play"})
        self.assertEqual(song_payload({"file": "Artist/Album/track.flac"})["title"], "track")
        self.assertEqual(song_payload({"file": "track.flac"})["artist"], "未知歌手")

    def test_clamp_int_validates_bounds(self):
        self.assertEqual(clamp_int("25", 0, 100, "volume"), 25)
        with self.assertRaises(ControlError):
            clamp_int(101, 0, 100, "volume")

    def test_source_descriptor_exposes_source_type(self):
        self.assertEqual(source_descriptor({"id": "Airplay"})["sourceType"], "airplay")
        self.assertEqual(source_descriptor({"id": "DLNA"})["sourceType"], "mpd")

    def test_login_rate_limit_is_per_address(self):
        app_module.LOGIN_ATTEMPTS.clear()
        for offset in range(app_module.LOGIN_LIMIT):
            record_login_failure("192.0.2.8", now=100 + offset)
        self.assertFalse(login_allowed("192.0.2.8", now=110)[0])
        self.assertTrue(login_allowed("192.0.2.9", now=110)[0])
        self.assertTrue(login_allowed("192.0.2.8", now=200)[0])

    def test_snapcast_normalization_preserves_groups(self):
        server = {"server": {"streams": [{"id": "DLNA", "status": "playing", "uri": {"query": {}}}], "groups": [
            {"id": "g1", "name": "客厅", "stream_id": "DLNA", "clients": []},
            {"id": "g2", "name": "书房", "stream_id": "DLNA", "clients": []},
        ]}}
        with patch("app.snap_rpc", return_value=server):
            state = normalized_snapcast_state()
        self.assertEqual([group["id"] for group in state["groups"]], ["g1", "g2"])

    def test_zone_volume_scales_connected_clients_proportionally(self):
        zones = {"groups": [{"id": "g1", "clients": [
            {"id": "a", "connected": True, "volume": 80},
            {"id": "b", "connected": True, "volume": 40},
            {"id": "offline", "connected": False, "volume": 60},
        ]}]}
        with patch("app.normalized_snapcast_state", return_value=zones), patch("app.snap_rpc", return_value={}) as rpc:
            set_zone_volume("g1", 50)
        self.assertEqual([call.args[1]["volume"]["percent"] for call in rpc.call_args_list], [50, 25])

    def test_zone_volume_from_silence_sets_requested_level(self):
        zones = {"groups": [{"id": "g1", "clients": [
            {"id": "a", "connected": True, "volume": 0}, {"id": "b", "connected": True, "volume": 0},
        ]}]}
        with patch("app.normalized_snapcast_state", return_value=zones), patch("app.snap_rpc", return_value={}) as rpc:
            set_zone_volume("g1", 30)
        self.assertEqual([call.args[1]["volume"]["percent"] for call in rpc.call_args_list], [30, 30])

    @staticmethod
    def snap_state(groups, streams=None):
        return {"groups": groups, "streams": streams or [{"id": "Default", "status": "idle"}]}

    def test_group_and_client_rename_validate_state(self):
        state = self.snap_state([{"id": "g1", "name": "客厅", "clients": [{"id": "c1"}]}])
        with patch("app.normalized_snapcast_state", return_value=state), patch("app.snap_rpc", return_value={}) as rpc:
            set_group_name("g1", "影音室")
            set_client_name("c1", "左音箱")
        self.assertEqual(rpc.call_args_list[0].args, ("Group.SetName", {"id": "g1", "name": "影音室"}))

    def test_group_members_reject_duplicates_and_unknown_clients(self):
        state = self.snap_state([{"id": "g1", "clients": [{"id": "c1"}]}])
        with patch("app.normalized_snapcast_state", return_value=state):
            with self.assertRaises(ControlError):
                set_group_members("g1", ["c1", "c1"])
            with self.assertRaises(ControlError):
                set_group_members("g1", ["missing"])

    def test_create_group_success(self):
        initial = self.snap_state([
            {"id": "g1", "name": "A", "streamId": "Default", "clients": [{"id": "c1"}, {"id": "c2"}]},
            {"id": "g2", "name": "B", "streamId": "Default", "clients": [{"id": "c3"}]},
        ])
        split = self.snap_state([
            {"id": "g1", "name": "A", "streamId": "Default", "clients": [{"id": "c2"}]},
            {"id": "g3", "name": "播放组", "streamId": "Default", "clients": [{"id": "c1"}]},
            {"id": "g2", "name": "B", "streamId": "Default", "clients": [{"id": "c3"}]},
        ])
        final = self.snap_state([{"id": "g3", "name": "新组", "streamId": "Default", "clients": [{"id": "c1"}, {"id": "c3"}]}])
        with patch("app.normalized_snapcast_state", side_effect=[initial, split, final]), patch("app.snap_rpc", return_value={}) as rpc:
            create_group("新组", ["c1", "c3"], "Default")
        self.assertIn(("Group.SetName", {"id": "g3", "name": "新组"}), [call.args for call in rpc.call_args_list])

    def test_create_group_failure_attempts_rollback_and_reports_partial_state(self):
        initial = self.snap_state([
            {"id": "g1", "name": "A", "streamId": "Default", "clients": [{"id": "c1"}, {"id": "c2"}]},
            {"id": "g2", "name": "B", "streamId": "DLNA", "clients": [{"id": "c3"}]},
        ], [{"id": "Default"}, {"id": "DLNA"}])
        split = self.snap_state([
            {"id": "g1", "name": "A", "streamId": "Default", "clients": [{"id": "c2"}]},
            {"id": "auto", "name": "播放组", "streamId": "Default", "clients": [{"id": "c1"}]},
            {"id": "g2", "name": "B", "streamId": "DLNA", "clients": [{"id": "c3"}]},
        ], initial["streams"])
        states = [initial, split, split, split, initial]
        calls = []
        def rpc(method, params):
            calls.append((method, params))
            if method == "Group.SetClients" and params.get("id") == "auto" and params["clients"] == ["c1", "c3"]:
                raise ControlError("injected")
            return {}
        with patch("app.normalized_snapcast_state", side_effect=states), patch("app.snap_rpc", side_effect=rpc):
            with self.assertRaises(GroupMutationError) as error:
                create_group("新组", ["c1", "c3"], "Default")
        self.assertTrue(any(method == "Group.SetClients" and params["clients"] == ["c1", "c2"] for method, params in calls))
        self.assertIn("创建播放组失败", str(error.exception))

    def test_merge_groups_protects_last_group(self):
        one = self.snap_state([{"id": "g1", "clients": [{"id": "c1"}]}])
        with patch("app.normalized_snapcast_state", return_value=one):
            with self.assertRaises(ControlError):
                merge_groups("g1", "g2")

    def test_stop_all_keeps_queue_and_skips_idle_airplay(self):
        idle = self.snap_state([], [{"id": "Airplay", "status": "idle"}, {"id": "DLNA", "status": "idle"}])
        with patch("app.mpd_command", return_value=[]) as mpd, patch("app.normalized_snapcast_state", return_value=idle), patch("app.subprocess.run") as run:
            result = stop_all_sources()
        mpd.assert_called_once_with("stop")
        run.assert_not_called()
        self.assertTrue(result["mpdStopped"])


class AuthHttpTest(unittest.TestCase):
    def setUp(self):
        app_module.SESSIONS.clear()
        app_module.LOGIN_ATTEMPTS.clear()
        self.settings = patch.multiple(app_module, AUTH_ENABLED=True, CONTROL_USERNAME="admin", CONTROL_PASSWORD="correct-password", SESSION_TTL=3600)
        self.settings.start()
        self.state = patch.object(app_module, "combined_state", return_value={"snapcast": {}, "player": {}, "errors": []})
        self.state_mock = self.state.start()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=2)
        self.state.stop(); self.settings.stop()

    def request(self, path, payload=None, opener=None, headers=None):
        data = None if payload is None else json.dumps(payload).encode()
        request_headers = {"Content-Type": "application/json"} if data else {}
        request_headers.update(headers or {})
        request = urllib.request.Request(self.base + path, data=data, headers=request_headers)
        return opener.open(request, timeout=2) if opener else urllib.request.urlopen(request, timeout=2)

    def test_api_requires_login(self):
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request("/api/state")
        self.assertEqual(error.exception.code, 401)

    def test_login_session_allows_api_and_logout_revokes_it(self):
        response = self.request("/api/login", {"username": "admin", "password": "correct-password"}, self.opener)
        self.assertIn("HttpOnly", response.headers["Set-Cookie"])
        self.assertEqual(self.request("/api/state", opener=self.opener).status, 200)
        self.request("/api/logout", {}, self.opener)
        with self.assertRaises(urllib.error.HTTPError):
            self.request("/api/state", opener=self.opener)

    def test_secure_cookie_option(self):
        with patch.object(app_module, "SECURE_COOKIE", True):
            response = self.request("/api/login", {"username": "admin", "password": "correct-password"})
        self.assertIn("Secure", response.headers["Set-Cookie"])

    def test_real_ip_is_trusted_only_from_loopback_proxy(self):
        handler = object.__new__(Handler)
        handler.client_address = ("127.0.0.1", 1)
        handler.headers = {"X-Real-IP": "192.0.2.8"}
        self.assertEqual(handler.client_ip(), "192.0.2.8")
        handler.client_address = ("192.0.2.9", 1)
        self.assertEqual(handler.client_ip(), "192.0.2.9")
        handler.client_address = ("127.0.0.1", 1)
        handler.headers = {"X-Real-IP": "forged"}
        self.assertEqual(handler.client_ip(), "127.0.0.1")

    def test_health_uses_cached_snapshot(self):
        with patch.object(app_module, "HEALTH_STATE", {"ok": True, "updatedAt": 1, "components": {"mpd": True}}):
            self.assertTrue(json.load(self.request("/api/health"))["ok"])
        self.state_mock.assert_not_called()

    def test_static_security_and_retired_player_api(self):
        response = self.request("/")
        self.assertIn("frame-src 'self'", response.headers["Content-Security-Policy"])
        index = response.read().decode()
        self.assertIn("Snap / Room", index)
        self.assertNotIn("192.168.", index)
        self.request("/api/login", {"username": "admin", "password": "correct-password"}, self.opener)
        with self.assertRaises(urllib.error.HTTPError) as retired:
            self.request("/api/player/bootstrap", opener=self.opener)
        self.assertEqual(retired.exception.code, 404)


class ProductionConfigTest(unittest.TestCase):
    def test_nginx_protects_player_websocket_and_limits_login_by_remote_ip(self):
        config = (Path(__file__).parents[1] / "unified" / "nginx.conf").read_text(encoding="utf-8")
        self.assertIn("limit_req_zone $binary_remote_addr", config)
        self.assertIn("location = /api/login", config)
        self.assertIn("auth_request /_session_check", config)
        self.assertIn("proxy_set_header Upgrade $http_upgrade", config)

    def test_mobile_breakpoint_has_three_columns_and_safe_bottom_space(self):
        styles = (Path(__file__).parent / "static" / "styles" / "responsive.css").read_text(encoding="utf-8")
        self.assertIn("@media (max-width: 900.98px)", styles)
        self.assertIn("grid-template-columns: repeat(3", styles)
        self.assertIn("padding: 0 0 calc(62px + env(safe-area-inset-bottom))", styles)
        self.assertIn("height: 100dvh", styles)
        self.assertNotIn("repeat(5", styles)

    def test_retired_player_backend_symbols_are_absent(self):
        backend = (Path(__file__).parent / "app.py").read_text(encoding="utf-8")
        for symbol in ("LibraryIndex", "library_browse", "playlist_m3u", "parse_lyrics", "run_player_action", "remote_stream_watchdog"):
            self.assertNotIn(symbol, backend)


if __name__ == "__main__":
    unittest.main()
