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
    ControlError, Handler, clamp_int, combined_state,
    login_allowed, normalized_snapcast_state,
    mpd_playback_options, mympd_art_url, proxy_mympd_rpc, reconcile_main_group, validate_mympd_params,
    player_event_revision, publish_player_event, record_login_failure, set_client_name,
    set_client_active, source_descriptor, stop_all_sources,
)


class ControlHelpersTest(unittest.TestCase):
    class RpcResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        @staticmethod
        def read(_size):
            return b'{"jsonrpc":"2.0","id":1,"result":{}}'

    def test_clamp_int_validates_bounds(self):
        self.assertEqual(clamp_int("25", 0, 100, "volume"), 25)
        with self.assertRaises(ControlError):
            clamp_int(101, 0, 100, "volume")

    def test_player_event_revision_advances(self):
        before = player_event_revision()
        self.assertEqual(publish_player_event(), before + 1)
        self.assertEqual(player_event_revision(), before + 1)

    def test_mpd_playback_options_extracts_loop_state(self):
        self.assertEqual(
            mpd_playback_options(["volume: 10", "repeat: 1", "random: 0", "single: 1"]),
            {"repeat": "1", "random": "0", "single": "1"},
        )

    def test_player_state_is_enriched_with_mpd_options(self):
        response = self.RpcResponse()
        response.read = lambda _size: b'{"jsonrpc":"2.0","id":1,"result":{"state":"play"}}'
        with patch("app.urllib.request.urlopen", return_value=response), patch(
            "app.mpd_command", return_value=["repeat: 1", "random: 0", "single: 0"]
        ):
            result = proxy_mympd_rpc({"method": "MYMPD_API_PLAYER_STATE", "params": {}})["result"]
        self.assertEqual((result["repeat"], result["random"], result["single"]), ("1", "0", "0"))

    def test_source_descriptor_exposes_source_type(self):
        self.assertEqual(source_descriptor({"id": "Airplay"})["sourceType"], "airplay")
        self.assertEqual(source_descriptor({"id": "DLNA"})["sourceType"], "mpd")

    def test_mympd_rpc_rejects_methods_outside_allowlist(self):
        with self.assertRaisesRegex(ControlError, "允许列表"):
            proxy_mympd_rpc({"method": "MYMPD_API_SCRIPT_EXECUTE", "params": {}})

    def test_mympd_rpc_rejects_oversized_uri_list(self):
        with self.assertRaisesRegex(ControlError, "URI数量"):
            validate_mympd_params("MYMPD_API_QUEUE_REPLACE_URIS", {"uris": ["track.flac"] * 201})
        with self.assertRaisesRegex(ControlError, "协议"):
            validate_mympd_params("MYMPD_API_QUEUE_APPEND_URIS", {"uris": ["file:///etc/passwd"]})

    def test_mympd_rpc_rejects_invalid_playlist_and_id_lists(self):
        with self.assertRaisesRegex(ControlError, "歌单名称"):
            validate_mympd_params("MYMPD_API_PLAYLIST_RENAME", {"plist": "ok", "newName": "x" * 201})
        with self.assertRaisesRegex(ControlError, "songIds"):
            validate_mympd_params("MYMPD_API_QUEUE_RM_IDS", {"songIds": [1, -2]})

    def test_mympd_rpc_rejects_oversized_search_expression(self):
        with self.assertRaisesRegex(ControlError, "搜索表达式"):
            validate_mympd_params("MYMPD_API_DATABASE_SEARCH", {"expression": "x" * 2049})

    def test_mympd_rpc_forwards_unicode_without_escapes(self):
        with patch("app.urllib.request.urlopen", return_value=self.RpcResponse()) as urlopen:
            proxy_mympd_rpc({"method": "MYMPD_API_PLAYLIST_CONTENT_LIST", "params": {"plist": "网络收音机"}})
        body = urlopen.call_args.args[0].data
        self.assertIn("网络收音机".encode(), body)
        self.assertNotIn(b"\\u", body)

    def test_mympd_playback_mode_validation(self):
        self.assertEqual(
            validate_mympd_params("MYMPD_API_PLAYER_OPTIONS_SET", {"repeat": True, "random": False, "single": "1"}),
            {"repeat": True, "random": False, "single": "1"},
        )
        with self.assertRaisesRegex(ControlError, "repeat必须"):
            validate_mympd_params("MYMPD_API_PLAYER_OPTIONS_SET", {"repeat": "yes"})

    def test_mympd_art_proxy_only_accepts_albumart_paths(self):
        self.assertIn("/albumart-large?", mympd_art_url("size=large&uri=music%2Fsong.flac"))
        with self.assertRaisesRegex(ControlError, "不受支持"):
            mympd_art_url("source=%2Fapi%2Fdefault%3Furi%3Dx")

    def test_login_rate_limit_is_per_address(self):
        app_module.LOGIN_ATTEMPTS.clear()
        for offset in range(app_module.LOGIN_LIMIT):
            record_login_failure("192.0.2.8", now=100 + offset)
        self.assertFalse(login_allowed("192.0.2.8", now=110)[0])
        self.assertTrue(login_allowed("192.0.2.9", now=110)[0])
        self.assertTrue(login_allowed("192.0.2.8", now=200)[0])

    def test_snapcast_normalization_exposes_explicit_main_group(self):
        server = {"server": {"streams": [{"id": "DLNA", "status": "playing", "uri": {"query": {}}}], "groups": [
            {"id": "g1", "name": "客厅", "stream_id": "DLNA", "clients": []},
            {"id": "g2", "name": "书房", "stream_id": "DLNA", "clients": []},
        ]}}
        with patch("app.snap_rpc", return_value=server):
            state = normalized_snapcast_state()
        self.assertEqual([group["id"] for group in state["groups"]], ["g1", "g2"])
        self.assertEqual(state["mainGroupId"], "g1")
        self.assertEqual(state["mainGroup"]["id"], "g1")

    def test_client_activation_preserves_volume(self):
        before = self.snap_state([{"id": "g1", "clients": [{"id": "c1", "volume": 37, "muted": True}]}])
        after = self.snap_state([{"id": "g1", "clients": [{"id": "c1", "volume": 37, "muted": False}]}])
        with patch("app.normalized_snapcast_state", side_effect=[before, after]), patch("app.snap_rpc", return_value={}) as rpc:
            set_client_active("c1", True)
        rpc.assert_called_once_with("Client.SetVolume", {"id": "c1", "volume": {"muted": False, "percent": 37}})

    def test_reconcile_main_group_merges_and_selects_default(self):
        initial = {"groups": [
            {"id": "g1", "name": "客厅", "streamId": "DLNA", "clients": [{"id": "a"}, {"id": "b"}]},
            {"id": "g2", "name": "书房", "streamId": "Airplay", "clients": [{"id": "c"}]},
        ], "streams": [], "mainGroupId": "g1"}
        merged = {"groups": [{"id": "g1", "name": "客厅", "streamId": "DLNA", "clients": [{"id": "a"}, {"id": "b"}, {"id": "c"}]}], "streams": [], "mainGroupId": "g1"}
        final = {"groups": [{"id": "g1", "name": "主播放组", "streamId": "Default", "clients": merged["groups"][0]["clients"]}], "streams": [], "mainGroupId": "g1"}
        with patch("app.normalized_snapcast_state", side_effect=[initial, merged, final]), patch("app.snap_rpc", return_value={}) as rpc:
            result = reconcile_main_group()
        calls = [call.args for call in rpc.call_args_list]
        self.assertIn(("Group.SetClients", {"id": "g1", "clients": ["a", "b", "c"]}), calls)
        self.assertIn(("Group.SetStream", {"id": "g1", "stream_id": "Default"}), calls)
        self.assertEqual(result["groups"][0]["name"], "主播放组")

    def test_reconcile_restores_default_without_topology_change(self):
        state = {"groups": [{"id": "g1", "name": app_module.MAIN_GROUP_NAME, "streamId": "Airplay", "clients": [{"id": "a"}]}], "streams": [], "mainGroupId": "g1"}
        with patch("app.normalized_snapcast_state", side_effect=[state, state]), patch("app.snap_rpc", return_value={}) as rpc:
            reconcile_main_group()
        rpc.assert_called_once_with("Group.SetStream", {"id": "g1", "stream_id": "Default"})

    def test_api_state_contains_no_duplicate_player_state(self):
        snapcast = {"streams": [{"id": "Airplay", "status": "playing"}], "groups": [], "mainGroup": None}
        with patch("app.normalized_snapcast_state", return_value=snapcast), patch("app.health_snapshot", return_value={"ok": True}):
            state = combined_state()
        self.assertNotIn("player", state)
        self.assertEqual(state["sources"][0]["id"], "Airplay")

    @staticmethod
    def snap_state(groups, streams=None):
        return {"groups": groups, "streams": streams or [{"id": "Default", "status": "idle"}]}

    def test_client_rename_validates_state(self):
        state = self.snap_state([{"id": "g1", "name": "客厅", "clients": [{"id": "c1"}]}])
        with patch("app.normalized_snapcast_state", return_value=state), patch("app.snap_rpc", return_value={}) as rpc:
            set_client_name("c1", "左音箱")
        self.assertEqual(rpc.call_args.args, ("Client.SetName", {"id": "c1", "name": "左音箱"}))

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
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        asset = self.request("/app.js?v=cache-test")
        self.assertEqual(asset.headers["Cache-Control"], "private, no-cache")
        self.request("/api/login", {"username": "admin", "password": "correct-password"}, self.opener)
        with self.assertRaises(urllib.error.HTTPError) as retired:
            self.request("/api/player/bootstrap", opener=self.opener)
        self.assertEqual(retired.exception.code, 404)
        for path in ("/api/snapcast/stream", "/api/snapcast/all-stream", "/api/snapcast/group-volume", "/api/player/seek", "/api/player/volume"):
            with self.assertRaises(urllib.error.HTTPError) as retired:
                self.request(path, {}, self.opener)
            self.assertEqual(retired.exception.code, 404)


class ProductionConfigTest(unittest.TestCase):
    @staticmethod
    def contrast_ratio(foreground, background):
        def luminance(value):
            channels = [int(value[index:index + 2], 16) / 255 for index in (1, 3, 5)]
            channels = [channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4 for channel in channels]
            return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722
        light, dark = sorted((luminance(foreground), luminance(background)), reverse=True)
        return (light + 0.05) / (dark + 0.05)

    def test_nginx_exposes_no_full_mympd_proxy_and_limits_login_by_remote_ip(self):
        config = (Path(__file__).parents[1] / "unified" / "nginx.conf").read_text(encoding="utf-8")
        self.assertIn("limit_req_zone $binary_remote_addr", config)
        self.assertIn("location = /api/login", config)
        self.assertIn("location = /api/player/events", config)
        self.assertIn("proxy_buffering off", config)
        self.assertIn("access.log snaproom", config)
        self.assertIn("$http_user_agent", config)
        self.assertNotIn("location /player/", config)
        self.assertNotIn("__MYMPD_PORT__", config)
        self.assertNotIn("proxy_set_header Upgrade", config)

    def test_runtime_defaults_and_tls_health_contract(self):
        project = Path(__file__).parents[1]
        env_example = (project / ".env.example").read_text(encoding="utf-8")
        compose = (project / "docker-compose.yml").read_text(encoding="utf-8")
        entrypoint = (project / "unified" / "entrypoint.sh").read_text(encoding="utf-8")
        healthcheck = (project / "unified" / "healthcheck.sh").read_text(encoding="utf-8")
        smoke = (project / "unified" / "smoke-test.sh").read_text(encoding="utf-8")
        workflow = (project / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("PGID=1001", env_example)
        self.assertIn("GATEWAY_MAC_ADDRESS=", env_example)
        self.assertIn("PGID: ${PGID:-1001}", compose)
        self.assertIn("mac_address: ${GATEWAY_MAC_ADDRESS:?", compose)
        self.assertIn("driver: macvlan", compose)
        self.assertIn("pgid=${PGID:-1001}", entrypoint)
        self.assertIn("CONTROL_INTERNAL_PORT", healthcheck)
        self.assertNotIn("$web_port/api/health", healthcheck)
        self.assertIn("https://127.0.0.1:$web_port/api/health", smoke)
        self.assertIn("docker-smoke-http:", workflow)
        self.assertIn("docker-smoke-https:", workflow)

    def test_bundled_radio_playlist_is_well_formed_and_deduplicated(self):
        playlist = Path(__file__).parents[1] / "unified" / "radio-stations.m3u"
        lines = [line.strip() for line in playlist.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(lines[0], "#EXTM3U")
        self.assertGreater(len(lines), 100)
        self.assertEqual((len(lines) - 1) % 2, 0)
        urls = []
        for index in range(1, len(lines), 2):
            self.assertTrue(lines[index].startswith("#EXTINF:-1,"))
            self.assertRegex(lines[index + 1], r"^https?://[^/]+/")
            self.assertNotIn("://lhttp://", lines[index + 1])
            urls.append(lines[index + 1])
        self.assertEqual(len(urls), len(set(urls)))

    def test_native_mympd_radio_importer_is_idempotent(self):
        import importlib.util
        project = Path(__file__).parents[1]
        module_path = project / "unified" / "import-mympd-radios.py"
        spec = importlib.util.spec_from_file_location("import_mympd_radios", module_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        class FakeApi:
            def __init__(self):
                self.saved = []

            def call(self, method, params):
                if method.endswith("_SEARCH"):
                    return {"data": [{"Name": "已有电台", "StreamUri": "https://radio/existing"}]}
                self.saved.append(params)
                return {"message": "saved"}

        api = FakeApi()
        changed, unchanged = module.sync(api, [
            ("已有电台", "https://radio/existing"),
            ("新增电台", "https://radio/new"),
        ])
        self.assertEqual((changed, unchanged), (1, 1))
        self.assertEqual(api.saved[0]["oldName"], "新增电台")
        self.assertEqual(api.saved[0]["streamUri"], "https://radio/new")

        importer_source = module_path.read_text(encoding="utf-8")
        self.assertIn("ensure_ascii=False", importer_source)

        supervisor = (project / "unified" / "supervisord.conf").read_text(encoding="utf-8")
        self.assertIn("[program:radio-import]", supervisor)
        self.assertIn("/api/default", supervisor)
        mympd_program = supervisor.split("[program:mympd]", 1)[1].split("[program:", 1)[0]
        self.assertIn('MPD_HOST="127.0.0.1"', mympd_program)
        self.assertNotIn('MPD_HOST="/app/data/dlna/mpd.sock"', mympd_program)

        mympd_init = (project / "unified" / "mympd-init.sh").read_text(encoding="utf-8")
        self.assertIn('write_config mympd_uri "http://127.0.0.1:$http_port"', mympd_init)
        self.assertNotIn('127.0.0.1:$http_port/"', mympd_init)
        self.assertIn('write_state mpd_host 127.0.0.1', mympd_init)
        self.assertIn('write_state mpd_port 6600', mympd_init)
        self.assertNotIn('$web_port/player/', mympd_init)

    def test_mobile_breakpoint_has_unified_player_without_navigation_rail(self):
        styles = (Path(__file__).parent / "static" / "styles" / "responsive.css").read_text(encoding="utf-8")
        self.assertIn("@media (max-width: 900.98px)", styles)
        self.assertIn(".device-shell { padding: 0; }", styles)
        self.assertIn(".dashboard { grid-template-columns: 1fr; }", styles)

    def test_deployment_backup_covers_persistent_configuration(self):
        project = Path(__file__).parents[1]
        deploy = (project / "unified" / "deploy-console.sh").read_text(encoding="utf-8")
        entrypoint = (project / "unified" / "entrypoint.sh").read_text(encoding="utf-8")
        for path in ("data/mympd/work/config", "data/mympd/work/state", "data/dlna/playlists", "data/.snaproom-schema-version"):
            self.assertIn(path, deploy)
        self.assertIn("persistent-config.tar", deploy)
        self.assertIn("snaproom-persistent-config-$timestamp.tar", deploy)
        self.assertIn("DATA_SCHEMA_VERSION", entrypoint)
        self.assertIn(".snaproom-schema-version", entrypoint)
        self.assertIn("exec /bin/su -p -s /bin/sh snapcast", entrypoint)
        self.assertIn("exec /usr/bin/supervisord", entrypoint)
        supervisor = (project / "unified" / "supervisord.conf").read_text(encoding="utf-8")
        self.assertNotIn("user=root", supervisor)
        self.assertNotIn("/dev/stdout", supervisor)
        self.assertIn("/app/data/service-logs/%(program_name)s.stdout.log", supervisor)

    def test_dual_panel_ui_and_mympd_skin_contract(self):
        project = Path(__file__).parents[1]
        index = (Path(__file__).parent / "static" / "index.html").read_text(encoding="utf-8")
        zones = (Path(__file__).parent / "static" / "js" / "zones.js").read_text(encoding="utf-8")
        mympd_css = (project / "unified" / "mympd-custom.css").read_text(encoding="utf-8")
        self.assertIn('id="playerPanel"', index)
        self.assertIn('id="devicePanelHost"', index)
        self.assertNotIn('data-route="player"', index)
        self.assertNotIn('data-route="devices"', index)
        self.assertNotIn('id="reloadPlayer"', index)
        self.assertNotIn('class="sidebar"', index)
        self.assertNotIn("nowPlayingCard", zones)
        self.assertNotIn("data-main-source", zones)
        self.assertIn("prefers-reduced-motion", mympd_css)
        self.assertNotIn('data-route="settings"', index)
        self.assertNotIn("group-manager.css", index)
        self.assertFalse((Path(__file__).parent / "static" / "js" / "groups.js").exists())

    def test_native_lightfield_player_contract(self):
        static = Path(__file__).parent / "static"
        index = (static / "index.html").read_text(encoding="utf-8")
        adapter = (static / "js" / "mympd-adapter.js").read_text(encoding="utf-8")
        player = (static / "js" / "player.js").read_text(encoding="utf-8")
        styles = (static / "styles" / "player.css").read_text(encoding="utf-8")
        responsive = (static / "styles" / "responsive.css").read_text(encoding="utf-8")
        icons = (static / "icons.svg").read_text(encoding="utf-8")
        self.assertNotIn("<iframe", index)
        view_order = [
            index.index('data-player-view="now"'),
            index.index('data-player-view="queue"'),
            index.index('data-player-view="playlists"'),
            index.index('data-player-view="radio"'),
            index.index('data-player-view="library"'),
        ]
        self.assertEqual(view_order, sorted(view_order))
        self.assertIn('class="active" data-player-view="now"', index)
        self.assertNotIn('data-player-view="lyrics"', index)
        self.assertIn('repeat(5, minmax(0, 1fr))', styles)
        self.assertIn('class="lightfield-player embedded-player active"', index)
        self.assertIn('class="player-actions"', index)
        self.assertIn('id="activeSourceBanner"', index)
        self.assertIn('aria-label="系统状态"', index)
        self.assertIn('maxlength="64"', (static / "js" / "zones.js").read_text(encoding="utf-8"))
        self.assertIn("syncActiveSource", player)
        self.assertIn(".embedded-player .lightfield-toolbar { display: none; }", styles)
        self.assertIn("height: calc(100svh - var(--header-space))", styles)
        self.assertIn('const API_URL = "/api/player/rpc"', adapter)
        self.assertIn('const EVENTS_URL = "/api/player/events"', adapter)
        self.assertIn("new EventSource", adapter)
        self.assertIn("MYMPD_API_WEBRADIO_FAVORITE_SEARCH", adapter)
        self.assertIn("radioNames.get(normalizeUri(uri))", adapter)
        self.assertIn("rememberRadioNames", adapter)
        self.assertIn("MYMPD_API_QUEUE_ADD_RANDOM", adapter)
        self.assertIn('quantity: 50', adapter)
        self.assertIn('play: false', adapter)
        self.assertIn('const playlistFields = ["Pos", "Title", "Artist", "Album", "Duration"]', adapter)
        self.assertIn("MYMPD_API_PLAYER_OPTIONS_SET", adapter)
        self.assertIn('id="playerModeButton"', index)
        self.assertIn("cyclePlaybackMode", player)
        self.assertIn('value === true || value === 1 || value === "1"', adapter)
        self.assertNotIn("播放器已更新", player)
        self.assertIn("installThumbDragRange", player)
        self.assertIn("coverChanged", player)
        self.assertIn('node.getAttribute("href") !== value', player)
        self.assertIn("(max-width: 700px) and (pointer: coarse)", responsive)
        self.assertIn(".thumb-only-range .thumb-drag-range { pointer-events: none", responsive)
        self.assertIn(".thumb-only-handle", responsive)
        self.assertNotIn("touch-range-unlock", responsive)
        for icon in ('"queue"', '"repeat"', '"repeat-one"', '"shuffle"'):
            self.assertIn(icon, player)
        self.assertNotIn('if (!await askConfirm("生成随机播放队列？"', player)
        self.assertIn("queueItemsSignature", player)
        self.assertIn("row.offsetTop - row.offsetHeight * 3", player)
        self.assertIn("MYMPD_API_PLAYLIST_CONTENT_APPEND_URIS", adapter)
        self.assertIn("MYMPD_API_PLAYLIST_RENAME", adapter)
        self.assertIn("MYMPD_API_PLAYLIST_RM", adapter)
        self.assertIn("MYMPD_API_PLAYLIST_CONTENT_RM_POSITIONS", adapter)
        self.assertIn("MYMPD_API_PLAYLIST_CONTENT_MOVE_POSITION", adapter)
        self.assertIn("installSelectionBar", player)
        self.assertIn("askPlaylistName", player)
        self.assertIn("item.uri || item.Name", player)
        self.assertIn("try { await showPlaylist", player)
        self.assertNotIn("renderLyrics", player)
        self.assertIn("extractAccent", player)
        self.assertIn("prefers-reduced-motion", styles)
        self.assertNotIn('viewBox="0 0 1024 1024"', icons)
        self.assertGreaterEqual(icons.count('viewBox="0 0 24 24"'), 20)

    def test_commercial_ui_accessibility_contract(self):
        static = Path(__file__).parent / "static"
        index = (static / "index.html").read_text(encoding="utf-8")
        app = (static / "app.js").read_text(encoding="utf-8")
        zones = (static / "js" / "zones.js").read_text(encoding="utf-8")
        tokens = (static / "styles" / "tokens.css").read_text(encoding="utf-8")
        self.assertGreaterEqual(self.contrast_ratio("#93ead5", "#0b1216"), 4.5)
        self.assertGreaterEqual(self.contrast_ratio("#acbfbd", "#142127"), 4.5)
        self.assertIn('--brand-text: #93ead5', tokens)
        self.assertIn('data-theme="dark"', index)
        self.assertNotIn('data-theme="system"', index)
        self.assertIn('id="systemHealth"', index)
        self.assertIn('id="healthSnapserver"', index)
        self.assertNotIn('aria-label="展开播放器"', index)
        self.assertNotIn('aria-label="折叠播放器"', index)
        self.assertIn('aria-label="退出登录"', index)
        self.assertNotIn('<span>退出登录</span>', index)
        self.assertIn('aria-labelledby="loginTitle"', index)
        self.assertIn('aria-live="polite"', index)
        self.assertIn('app.bundle.js?v=', index)
        self.assertIn('class="speaker-toggle"', zones)
        self.assertIn('class="speaker-settings"', zones)
        self.assertIn('class="edit-device-name"', zones)
        self.assertIn('class="device-name-display"', zones)
        self.assertIn("installMobileGestureGuard", app)
        self.assertIn('/api/snapcast/client-name', zones)
        self.assertNotIn('class="device-tuning"', zones)
        self.assertNotIn('id="themeSelect"', index)
        self.assertNotIn('class="more-menu"', index)
        self.assertIn('clearPrivateState', app)
        self.assertIn('addEventListener("cancel", event => event.preventDefault())', app)
        self.assertIn('Promise.resolve().then(openLogin)', app)
        self.assertNotIn('{ once: true }', app.split('addEventListener("cancel"', 1)[1].split(";", 1)[0])

    def test_frontend_module_graph_uses_one_cache_version(self):
        static = Path(__file__).parent / "static"
        source_version = "20261002-ios2"
        bundle_version = "20261002-ios12dom"
        index = (static / "index.html").read_text(encoding="utf-8")
        app = (static / "app.js").read_text(encoding="utf-8")
        bundle = (static / "app.bundle.js").read_text(encoding="utf-8")
        zones = (static / "js" / "zones.js").read_text(encoding="utf-8")
        player = (static / "js" / "player.js").read_text(encoding="utf-8")
        watchdog = (static / "js" / "bootstrap-watchdog.js").read_text(encoding="utf-8")
        self.assertIn(f'app.bundle.js?v={bundle_version}', index)
        self.assertIn(f'bootstrap-watchdog.js?v={bundle_version}', index)
        self.assertNotIn('type="module"', index)
        for source in (app, zones, player):
            for line in (line for line in source.splitlines() if line.startswith("import ")):
                self.assertIn(f"?v={source_version}", line)
        self.assertIn('dataset.consoleBoot = "ready"', app)
        self.assertIn('dataset.consoleBoot = "ready"', bundle)
        self.assertNotIn("import ", bundle)
        self.assertIn("控制台脚本未能启动", watchdog)
        self.assertIn('report("watchdog-start")', watchdog)
        self.assertIn('__snapProbe("app-start")', app)

    def test_frontend_startup_is_legacy_safari_parseable(self):
        static = Path(__file__).parent / "static"
        sources = "\n".join(path.read_text(encoding="utf-8") for path in (
            static / "app.js", *(static / "js").glob("*.js")
        ))
        for unsupported in ("?.", "??", "replaceAll(", "replaceChildren(", "queueMicrotask("):
            self.assertNotIn(unsupported, sources)
        ui = (static / "js" / "ui.js").read_text(encoding="utf-8")
        self.assertNotIn("showModal", ui)
        self.assertIn("while (node.firstChild) node.removeChild(node.firstChild)", ui)
        self.assertIn('dialog.setAttribute("open", "")', ui)
        index = (static / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("<dialog", index)
        self.assertIn('id="loginDialog" class="modal" role="dialog" aria-modal="true" open', index)

    def test_legacy_safari_dialog_position_and_viewport_fallbacks(self):
        static = Path(__file__).parent / "static"
        components = (static / "styles" / "components.css").read_text(encoding="utf-8")
        responsive = (static / "styles" / "responsive.css").read_text(encoding="utf-8")
        modal_rule = components.split(".modal[open]", 1)[1].split("}", 1)[0]
        for edge in ("top: 0", "right: 0", "bottom: 0", "left: 0"):
            self.assertIn(edge, modal_rule)
        self.assertNotIn("inset:", modal_rule)
        self.assertIn("max-height: calc(100vh - 48px)", components)
        self.assertIn("max-height: calc(100vh - 24px)", responsive)

    def test_frontend_has_complete_device_states_and_user_facing_copy(self):
        static = Path(__file__).parent / "static"
        sources = "\n".join(path.read_text(encoding="utf-8") for path in (
            static / "index.html", static / "app.js", static / "js" / "zones.js"
        ))
        for state_copy in ("暂未发现设备", "网关连接中断", "需要重新登录"):
            self.assertIn(state_copy, sources)
        for engineering_copy in (">SYSTEM<", ">BATCH ACTION<", ">APPEARANCE<", ">ACCOUNT<", ">ZONE<", "UNKNOWN"):
            self.assertNotIn(engineering_copy, sources)

    def test_retired_player_backend_symbols_are_absent(self):
        backend = (Path(__file__).parent / "app.py").read_text(encoding="utf-8")
        for symbol in ("LibraryIndex", "library_browse", "playlist_m3u", "parse_lyrics", "run_player_action", "remote_stream_watchdog"):
            self.assertNotIn(symbol, backend)


if __name__ == "__main__":
    unittest.main()
