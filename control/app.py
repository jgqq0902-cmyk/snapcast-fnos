#!/usr/bin/env python3
"""Snap / Room authenticated device console and minimal MPD bridge."""
from __future__ import annotations

import hmac
import ipaddress
import itertools
import json
import math
import mimetypes
import os
import secrets
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict, deque
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

CONTROL_HOST = os.environ.get("CONTROL_HOST", "127.0.0.1")
CONTROL_PORT = int(os.environ.get("CONTROL_PORT", "1783"))
SNAPSERVER_RPC_URL = os.environ.get("SNAPSERVER_RPC_URL", "http://127.0.0.1:1780/jsonrpc")
SNAPSERVER_RPC_PORT = int(os.environ.get("SNAPSERVER_RPC_PORT", "1705"))
MPD_SOCKET = os.environ.get("MPD_SOCKET", "/app/data/dlna/mpd.sock")
MYMPD_INTERNAL_PORT = int(os.environ.get("MYMPD_INTERNAL_PORT", "1782"))
MYMPD_RPC_URL = f"http://127.0.0.1:{MYMPD_INTERNAL_PORT}/api/default"
AIRPLAY_STOP_HELPER = os.environ.get("AIRPLAY_STOP_HELPER", "/app/unified/drop-airplay-session.sh")
STATIC_DIR = Path(__file__).with_name("static")

AUTH_ENABLED = os.environ.get("CONTROL_AUTH_ENABLED", "true").strip().casefold() not in {"0", "false", "no", "off"}
CONTROL_USERNAME = os.environ.get("CONTROL_USERNAME", "admin")
CONTROL_PASSWORD = os.environ.get("CONTROL_PASSWORD", "")
SESSION_TTL = max(300, int(os.environ.get("CONTROL_SESSION_TTL", "43200")))
SESSION_COOKIE = "snaproom_session"
SECURE_COOKIE = os.environ.get("CONTROL_SECURE_COOKIE", "false").strip().casefold() in {"1", "true", "yes", "on"}
LOGIN_WINDOW = 60
LOGIN_LIMIT = 5
HEALTH_INTERVAL = max(2, int(os.environ.get("HEALTH_INTERVAL", "5")))

RPC_IDS = itertools.count(1)
SNAP_RPC_TARGET = urlparse(SNAPSERVER_RPC_URL)
SNAP_RPC_LOCK = threading.Lock()
SNAP_RPC_SOCKET: socket.socket | None = None
SNAP_RPC_BUFFER = bytearray()
GROUP_MUTATION_LOCK = threading.Lock()
AUTH_LOCK = threading.Lock()
SESSIONS: dict[str, float] = {}
LOGIN_ATTEMPTS: dict[str, deque[float]] = defaultdict(deque)
HEALTH_LOCK = threading.Lock()
HEALTH_STATE: dict[str, Any] = {"ok": False, "updatedAt": 0, "components": {}}
MAIN_GROUP_NAME = os.environ.get("SNAPCAST_MAIN_GROUP_NAME", "主播放组").strip() or "主播放组"
MYMPD_ALLOWED_METHODS = frozenset({
    "MYMPD_API_PLAYER_STATE", "MYMPD_API_PLAYER_CURRENT_SONG", "MYMPD_API_PLAYER_PLAY",
    "MYMPD_API_PLAYER_PAUSE", "MYMPD_API_PLAYER_STOP", "MYMPD_API_PLAYER_NEXT",
    "MYMPD_API_PLAYER_PREV", "MYMPD_API_PLAYER_SEEK_CURRENT", "MYMPD_API_PLAYER_VOLUME_SET",
    "MYMPD_API_PLAYER_PLAY_SONG", "MYMPD_API_DATABASE_ALBUM_LIST", "MYMPD_API_DATABASE_SEARCH",
    "MYMPD_API_DATABASE_ALBUM_DETAIL", "MYMPD_API_QUEUE_SEARCH", "MYMPD_API_QUEUE_REPLACE_URIS",
    "MYMPD_API_QUEUE_APPEND_URIS", "MYMPD_API_QUEUE_REPLACE_PLAYLISTS", "MYMPD_API_QUEUE_RM_IDS",
    "MYMPD_API_QUEUE_CLEAR", "MYMPD_API_QUEUE_ADD_RANDOM", "MYMPD_API_PLAYLIST_LIST",
    "MYMPD_API_PLAYLIST_CONTENT_LIST", "MYMPD_API_PLAYLIST_CONTENT_APPEND_URIS",
    "MYMPD_API_PLAYLIST_RENAME", "MYMPD_API_PLAYLIST_RM", "MYMPD_API_PLAYLIST_CONTENT_RM_POSITIONS",
    "MYMPD_API_PLAYLIST_CONTENT_MOVE_POSITION", "MYMPD_API_WEBRADIO_FAVORITE_SEARCH",
})


class ControlError(RuntimeError):
    pass


def auth_configured() -> bool:
    return not AUTH_ENABLED or bool(CONTROL_USERNAME and CONTROL_PASSWORD)


def login_allowed(address: str, now: float | None = None) -> tuple[bool, int]:
    current = time.time() if now is None else now
    with AUTH_LOCK:
        attempts = LOGIN_ATTEMPTS[address]
        while attempts and current - attempts[0] >= LOGIN_WINDOW:
            attempts.popleft()
        if len(attempts) >= LOGIN_LIMIT:
            return False, max(1, int(LOGIN_WINDOW - (current - attempts[0])))
        return True, 0


def record_login_failure(address: str, now: float | None = None) -> None:
    with AUTH_LOCK:
        LOGIN_ATTEMPTS[address].append(time.time() if now is None else now)


def verify_credentials(username: Any, password: Any) -> bool:
    return auth_configured() and hmac.compare_digest(str(username), CONTROL_USERNAME) and hmac.compare_digest(str(password), CONTROL_PASSWORD)


def create_session(address: str, now: float | None = None) -> str:
    current = time.time() if now is None else now
    token = secrets.token_urlsafe(32)
    with AUTH_LOCK:
        SESSIONS[token] = current + SESSION_TTL
        LOGIN_ATTEMPTS.pop(address, None)
        for value in [value for value, expiry in SESSIONS.items() if expiry <= current]:
            SESSIONS.pop(value, None)
    return token


def session_token(cookie_header: str, now: float | None = None) -> str:
    if not AUTH_ENABLED:
        return "lan-mode"
    try:
        cookie = SimpleCookie()
        cookie.load(cookie_header or "")
        token = cookie[SESSION_COOKIE].value
    except (KeyError, AttributeError):
        return ""
    current = time.time() if now is None else now
    with AUTH_LOCK:
        if SESSIONS.get(token, 0) <= current:
            SESSIONS.pop(token, None)
            return ""
    return token


def revoke_session(cookie_header: str) -> None:
    token = session_token(cookie_header)
    if token and token != "lan-mode":
        with AUTH_LOCK:
            SESSIONS.pop(token, None)


def clamp_int(value: Any, minimum: int, maximum: int, field: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ControlError(f"{field} 必须是整数") from exc
    if not minimum <= parsed <= maximum:
        raise ControlError(f"{field} 必须在 {minimum} 到 {maximum} 之间")
    return parsed


def snap_rpc(method: str, params: dict[str, Any] | None = None) -> Any:
    global SNAP_RPC_SOCKET, SNAP_RPC_BUFFER
    rpc_id = next(RPC_IDS)
    payload = json.dumps({"id": rpc_id, "jsonrpc": "2.0", "method": method, "params": params or {}}).encode()
    with SNAP_RPC_LOCK:
        for attempt in range(2):
            try:
                if SNAP_RPC_SOCKET is None:
                    SNAP_RPC_SOCKET = socket.create_connection((SNAP_RPC_TARGET.hostname or "127.0.0.1", SNAPSERVER_RPC_PORT), timeout=3)
                    SNAP_RPC_SOCKET.settimeout(3)
                    SNAP_RPC_BUFFER.clear()
                SNAP_RPC_SOCKET.sendall(payload + b"\r\n")
                while True:
                    newline = SNAP_RPC_BUFFER.find(b"\n")
                    if newline < 0:
                        part = SNAP_RPC_SOCKET.recv(65536)
                        if not part:
                            raise ConnectionError("连接已关闭")
                        SNAP_RPC_BUFFER.extend(part)
                        continue
                    raw = bytes(SNAP_RPC_BUFFER[:newline]).strip()
                    del SNAP_RPC_BUFFER[: newline + 1]
                    if not raw:
                        continue
                    message = json.loads(raw)
                    if message.get("id") == rpc_id:
                        result = message
                        break
                break
            except (OSError, json.JSONDecodeError) as exc:
                if SNAP_RPC_SOCKET:
                    SNAP_RPC_SOCKET.close()
                SNAP_RPC_SOCKET = None
                SNAP_RPC_BUFFER.clear()
                if attempt:
                    raise ControlError(f"Snapserver 暂不可用：{exc}") from exc
    if "error" in result:
        raise ControlError(result["error"].get("message", "Snapserver 请求失败"))
    return result.get("result")


def _read_mpd_response(connection: socket.socket) -> list[str]:
    chunks = bytearray()
    while True:
        part = connection.recv(65536)
        if not part:
            raise ControlError("MPD 提前关闭了连接")
        chunks.extend(part)
        lines = chunks.decode("utf-8", "replace").splitlines()
        if lines and (lines[-1] == "OK" or lines[-1].startswith("ACK ")):
            if lines[-1].startswith("ACK "):
                raise ControlError(lines[-1])
            return lines[:-1]


def mpd_command(command: str, timeout: float = 3) -> list[str]:
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(timeout)
            connection.connect(MPD_SOCKET)
            if not connection.recv(128).decode("utf-8", "replace").startswith("OK MPD"):
                raise ControlError("MPD 握手失败")
            connection.sendall((command + "\n").encode())
            return _read_mpd_response(connection)
    except (AttributeError, FileNotFoundError, ConnectionRefusedError, socket.timeout, OSError) as exc:
        raise ControlError(f"播放器暂不可用：{exc}") from exc


def parse_mpd(lines: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for line in lines:
        key, separator, value = line.partition(": ")
        if separator:
            result[key] = value
    return result


def song_payload(song: dict[str, Any]) -> dict[str, Any]:
    uri = str(song.get("file", ""))
    title = str(song.get("Title") or Path(uri).stem or "等待播放")
    return {
        "file": uri,
        "title": title,
        "artist": str(song.get("Artist") or "未知歌手"),
        "album": str(song.get("Album") or ""),
        "duration": float(song.get("duration", 0) or 0),
    }


def player_state() -> dict[str, Any]:
    status = parse_mpd(mpd_command("status"))
    song = song_payload(parse_mpd(mpd_command("currentsong")))
    duration = float(status.get("duration", song["duration"]) or 0)
    uri = song["file"].strip()
    scheme = urlparse(uri).scheme.casefold()
    playing = status.get("state", "stop") in {"play", "pause"}
    if scheme in {"http", "https"}:
        origin = "radio" if duration <= 0 else "dlna"
    elif uri:
        origin = "local"
    else:
        origin = "unknown"
    return {
        "state": status.get("state", "stop"),
        "elapsed": float(status.get("elapsed", 0) or 0),
        "duration": duration,
        "song": song,
        "audio": status.get("audio", ""),
        "volume": min(100, max(0, int(status.get("volume", 0) or 0))),
        "sourceType": "mpd",
        "origin": origin,
        "live": playing and origin == "radio",
        "seekable": playing and duration > 0 and origin in {"local", "dlna"},
    }


def seek_player(position: Any) -> dict[str, Any]:
    try:
        target = float(position)
    except (TypeError, ValueError) as exc:
        raise ControlError("播放位置必须是秒数") from exc
    if not math.isfinite(target):
        raise ControlError("播放位置无效")
    current = player_state()
    if not current["seekable"]:
        raise ControlError("当前音源不支持跳转")
    target = max(0.0, min(target, current["duration"]))
    mpd_command(f"seekcur {target:.3f}")
    return player_state()


def set_player_volume(percent: Any) -> dict[str, Any]:
    value = clamp_int(percent, 0, 100, "音源音量")
    mpd_command(f"setvol {value}")
    return player_state()


def source_type(stream_id: Any) -> str:
    return {"airplay": "airplay", "dlna": "mpd", "default": "auto"}.get(str(stream_id).strip().casefold(), "unknown")


def source_descriptor(stream: dict[str, Any], active_kind: str = "") -> dict[str, Any]:
    kind = source_type(stream.get("id", ""))
    effective = active_kind if kind == "auto" and active_kind else kind
    return {
        "id": stream.get("id", ""),
        "name": stream.get("id", ""),
        "status": stream.get("status", "idle"),
        "format": stream.get("uri", {}).get("query", {}).get("sampleformat", ""),
        "sourceType": kind,
        "effectiveSourceType": effective,
    }


def normalized_snapcast_state() -> dict[str, Any]:
    server = snap_rpc("Server.GetStatus")["server"]
    raw_streams = server.get("streams", [])
    playing_kinds = {source_type(item.get("id")) for item in raw_streams if item.get("status") == "playing"}
    active_kind = "airplay" if "airplay" in playing_kinds else "mpd"
    streams = [source_descriptor(stream, active_kind) for stream in raw_streams]
    streams_by_id = {stream["id"]: stream for stream in streams}
    groups = []
    for group in server.get("groups", []):
        clients = []
        for client in group.get("clients", []):
            config = client.get("config", {})
            volume = config.get("volume", {})
            clients.append({
                "id": client["id"],
                "name": config.get("name") or client.get("host", {}).get("name") or client["id"],
                "connected": bool(client.get("connected")),
                "latency": int(config.get("latency", 0)),
                "volume": int(volume.get("percent", 0)),
                "muted": bool(volume.get("muted", False)),
                "active": not bool(volume.get("muted", False)),
                "participating": not bool(volume.get("muted", False)),
                "ip": client.get("host", {}).get("ip", "").replace("::ffff:", ""),
                "version": client.get("snapclient", {}).get("version", ""),
            })
        stream_id = group.get("stream_id", "")
        connected = [client for client in clients if client["connected"]]
        source = streams_by_id.get(stream_id, source_descriptor({"id": stream_id}, active_kind))
        source_playing = source.get("status") == "playing"
        for client in clients:
            client["audible"] = bool(client["connected"] and client["active"] and source_playing and not group.get("muted", False))
        groups.append({
            "id": group["id"], "name": group.get("name") or "播放组", "streamId": stream_id,
            "sourceType": source["effectiveSourceType"], "source": source,
            "muted": bool(group.get("muted", False)),
            "volume": max((client["volume"] for client in connected if client["active"]), default=0),
            "connectedCount": len(connected), "clients": clients,
        })
    main_group = max(groups, key=lambda item: len(item["clients"]), default=None)
    return {"streams": streams, "groups": groups, "mainGroupId": main_group["id"] if main_group else "", "mainGroup": main_group}


def set_zone_volume(group_id: Any, percent: Any, muted: bool = False) -> list[Any]:
    identifier = str(group_id)
    value = clamp_int(percent, 0, 100, "音量")
    group = next((item for item in normalized_snapcast_state()["groups"] if item["id"] == identifier), None)
    if group is None:
        raise ControlError("播放区域不存在")
    connected = [client for client in group["clients"] if client["connected"] and client.get("active", not client.get("muted", False))]
    if not connected:
        raise ControlError("没有已激活的在线设备")
    peak = max((client["volume"] for client in connected), default=0)
    return [snap_rpc("Client.SetVolume", {"id": client["id"], "volume": {"muted": muted, "percent": value if peak == 0 else min(100, int(client["volume"] * value / peak + 0.5))}}) for client in connected]


def set_client_active(client_id: Any, active: Any) -> dict[str, Any]:
    identifier = str(client_id or "")
    if not isinstance(active, bool):
        raise ControlError("激活状态必须为布尔值")
    with GROUP_MUTATION_LOCK:
        state = normalized_snapcast_state()
        _, clients = snapcast_indexes(state)
        client = clients.get(identifier)
        if client is None:
            raise ControlError("设备不存在")
        snap_rpc("Client.SetVolume", {"id": identifier, "volume": {"muted": not active, "percent": client["volume"]}})
        return normalized_snapcast_state()


def reconcile_main_group() -> dict[str, Any]:
    """Idempotently collapse all registered clients into one Default group."""
    with GROUP_MUTATION_LOCK:
        state = normalized_snapcast_state()
        groups = [group for group in state["groups"] if group["clients"]]
        if not groups:
            return state
        target = max(groups, key=lambda item: (len(item["clients"]), item["id"] == state.get("mainGroupId")))
        client_ids = list(dict.fromkeys(
            client["id"] for group in [target, *[item for item in groups if item["id"] != target["id"]]] for client in group["clients"]
        ))
        target_ids = [client["id"] for client in target["clients"]]
        topology_changed = len(groups) > 1 or target_ids != client_ids
        first_reconciliation = target.get("name") != MAIN_GROUP_NAME
        if topology_changed:
            snap_rpc("Group.SetClients", {"id": target["id"], "clients": client_ids})
            state = normalized_snapcast_state()
            target = next((group for group in state["groups"] if client_ids[0] in {client["id"] for client in group["clients"]}), target)
        if target.get("name") != MAIN_GROUP_NAME:
            snap_rpc("Group.SetName", {"id": target["id"], "name": MAIN_GROUP_NAME})
        if (topology_changed or first_reconciliation) and target.get("streamId") != "Default":
            snap_rpc("Group.SetStream", {"id": target["id"], "stream_id": "Default"})
        return normalized_snapcast_state()


def snap_name(value: Any, label: str) -> str:
    name = str(value or "").strip()
    if not name or len(name) > 64 or any(ord(char) < 32 for char in name):
        raise ControlError(f"{label}必须为 1 到 64 个有效字符")
    return name


def snapcast_indexes(state: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    groups = {group["id"]: group for group in state["groups"]}
    clients = {client["id"]: client for group in state["groups"] for client in group["clients"]}
    return groups, clients


def set_client_name(client_id: Any, name: Any) -> dict[str, Any]:
    with GROUP_MUTATION_LOCK:
        _, clients = snapcast_indexes(normalized_snapcast_state())
        identifier = str(client_id or "")
        if identifier not in clients:
            raise ControlError("设备不存在")
        snap_rpc("Client.SetName", {"id": identifier, "name": snap_name(name, "设备名")})
        return normalized_snapcast_state()


def stop_all_sources() -> dict[str, Any]:
    errors: list[str] = []
    mpd_stopped = airplay_dropped = False
    try:
        mpd_command("stop")
        mpd_stopped = True
    except ControlError as exc:
        errors.append(f"MPD：{exc}")
    try:
        before = normalized_snapcast_state()
        airplay = next((stream for stream in before["streams"] if stream["id"].casefold() == "airplay"), None)
        if airplay is None or airplay.get("status") != "playing":
            airplay_dropped = True
        else:
            completed = subprocess.run([AIRPLAY_STOP_HELPER], capture_output=True, text=True, timeout=8, check=False)
            if completed.returncode != 0:
                raise ControlError((completed.stderr or completed.stdout or "辅助脚本执行失败").strip())
            airplay_dropped = True
    except (ControlError, OSError, subprocess.TimeoutExpired) as exc:
        errors.append(f"AirPlay：{exc}")
    streams: list[dict[str, Any]] = []
    for _ in range(6):
        try:
            streams = normalized_snapcast_state()["streams"]
            if all(stream.get("status") != "playing" for stream in streams):
                break
        except ControlError as exc:
            errors.append(f"状态刷新：{exc}")
            break
        time.sleep(0.25)
    playing = [stream.get("id", "未知音源") for stream in streams if stream.get("status") == "playing"]
    if playing:
        errors.append(f"状态确认：{', '.join(playing)} 仍显示播放中")
    return {"mpdStopped": mpd_stopped, "airplayDropped": airplay_dropped, "streams": streams, "errors": errors}


def combined_state() -> dict[str, Any]:
    errors: list[str] = []
    snapcast, player = {"available": False, "streams": [], "groups": []}, {"available": False, "state": "stop", "song": {}}
    try:
        snapcast = {"available": True, **normalized_snapcast_state()}
    except ControlError as exc:
        errors.append(str(exc))
    try:
        player = {"available": True, **player_state()}
    except ControlError as exc:
        errors.append(str(exc))
    health = health_snapshot()
    return {"snapcast": snapcast, "mainGroup": snapcast.get("mainGroup"), "zones": snapcast.get("groups", []), "sources": snapcast.get("streams", []), "player": player, "system": {"hostname": socket.gethostname(), **health}, "errors": errors}


def refresh_health() -> dict[str, Any]:
    components: dict[str, bool] = {}
    try:
        snap_rpc("Server.GetStatus")
        components["snapserver"] = True
    except ControlError:
        components["snapserver"] = False
    try:
        mpd_command("ping", 2)
        components["mpd"] = True
    except ControlError:
        components["mpd"] = False
    try:
        with socket.create_connection(("127.0.0.1", MYMPD_INTERNAL_PORT), timeout=2):
            components["mympd"] = True
    except OSError:
        components["mympd"] = False
    snapshot = {"ok": all(components.values()), "updatedAt": int(time.time()), "components": components}
    with HEALTH_LOCK:
        HEALTH_STATE.clear()
        HEALTH_STATE.update(snapshot)
    return snapshot


def health_snapshot() -> dict[str, Any]:
    with HEALTH_LOCK:
        return dict(HEALTH_STATE)


def proxy_mympd_rpc(payload: dict[str, Any]) -> dict[str, Any]:
    method = payload.get("method")
    if method not in MYMPD_ALLOWED_METHODS:
        raise ControlError("播放器方法不在允许列表中")
    params = payload.get("params", {})
    if not isinstance(params, (dict, list)):
        raise ControlError("播放器参数格式无效")
    request_body = json.dumps({"jsonrpc": "2.0", "id": payload.get("id", 1), "method": method, "params": params}, separators=(",", ":")).encode()
    request = urllib.request.Request(MYMPD_RPC_URL, data=request_body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
    except (OSError, urllib.error.URLError) as exc:
        raise ControlError("播放器服务暂不可用") from exc
    if len(raw) > 2 * 1024 * 1024:
        raise ControlError("播放器响应过大")
    try:
        return json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ControlError("播放器返回了无效响应") from exc


def mympd_art_url(query: str) -> str:
    values = urllib.parse.parse_qs(query, keep_blank_values=False)
    source = values.get("source", [""])[0]
    if source:
        parsed = urllib.parse.urlsplit(source)
        if parsed.path not in {"/albumart", "/albumart-large"}:
            raise ControlError("封面路径不受支持")
        uri = urllib.parse.parse_qs(parsed.query).get("uri", [""])[0]
        size = "large" if parsed.path.endswith("-large") else "small"
    else:
        uri = values.get("uri", [""])[0]
        size = values.get("size", ["small"])[0]
    if not uri or len(uri) > 4096 or size not in {"small", "large"}:
        raise ControlError("封面参数无效")
    path = "/albumart-large" if size == "large" else "/albumart"
    return f"http://127.0.0.1:{MYMPD_INTERNAL_PORT}{path}?offset=0&uri={urllib.parse.quote(uri, safe='')}"


def health_monitor() -> None:
    while True:
        refresh_health()
        time.sleep(HEALTH_INTERVAL)


def topology_monitor() -> None:
    while True:
        try:
            reconcile_main_group()
        except ControlError as exc:
            print(f"Main group reconciliation deferred: {exc}", flush=True)
        time.sleep(max(10, HEALTH_INTERVAL * 2))


class Handler(BaseHTTPRequestHandler):
    server_version = "SnapRoom/4.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        request = str(args[0]) if args else ""
        if not request.startswith(("GET /api/state ", "GET /api/health ")):
            print(f"{self.address_string()} - {fmt % args}", flush=True)

    def _headers(self, status: int, content_type: str, length: int, cache: str = "no-store", extra: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-src 'self'")
        for name, value in (extra or {}).items():
            self.send_header(name, value)
        self.end_headers()

    def json_response(self, payload: Any, status: int = HTTPStatus.OK, headers: dict[str, str] | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        self._headers(status, "application/json; charset=utf-8", len(body), extra=headers)
        self.wfile.write(body)

    def read_json(self) -> dict[str, Any]:
        if self.headers.get_content_type() != "application/json":
            raise ControlError("请求必须使用 application/json")
        length = clamp_int(self.headers.get("Content-Length", 0), 0, 65536, "Content-Length")
        try:
            value = json.loads(self.rfile.read(length))
        except json.JSONDecodeError as exc:
            raise ControlError("JSON 格式错误") from exc
        if not isinstance(value, dict):
            raise ControlError("请求体必须是对象")
        return value

    def authenticated(self) -> bool:
        return bool(session_token(self.headers.get("Cookie", "")))

    def client_ip(self) -> str:
        peer = ipaddress.ip_address(self.client_address[0])
        forwarded = self.headers.get("X-Real-IP", "").strip()
        if peer.is_loopback and forwarded:
            try:
                return str(ipaddress.ip_address(forwarded))
            except ValueError:
                pass
        return str(peer)

    def require_auth(self, path: str) -> bool:
        if not path.startswith("/api/") or path in {"/api/health", "/api/auth", "/api/login"} or self.authenticated():
            return True
        self.json_response({"ok": False, "error": "需要登录"}, HTTPStatus.UNAUTHORIZED)
        return False

    def do_GET(self) -> None:  # noqa: N802
        parsed_path = urlparse(self.path)
        path = parsed_path.path
        if not self.require_auth(path):
            return
        if path == "/api/auth":
            self.json_response({"ok": True, "enabled": AUTH_ENABLED, "configured": auth_configured(), "authenticated": self.authenticated(), "username": CONTROL_USERNAME if AUTH_ENABLED else ""}); return
        if path == "/api/state":
            self.json_response(combined_state()); return
        if path == "/api/health":
            self.json_response(health_snapshot()); return
        if path == "/api/player/events":
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            try:
                for sequence in range(60):
                    self.wfile.write(f"event: update\ndata: {{\"sequence\":{sequence}}}\n\n".encode())
                    self.wfile.flush()
                    time.sleep(2)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        if path == "/api/player/art":
            try:
                request = urllib.request.Request(mympd_art_url(parsed_path.query), headers={"Accept": "image/*"})
                with urllib.request.urlopen(request, timeout=8) as response:
                    body = response.read(12 * 1024 * 1024 + 1)
                    content_type = response.headers.get_content_type()
                if len(body) > 12 * 1024 * 1024 or not content_type.startswith("image/"):
                    raise ControlError("封面响应无效")
                self._headers(HTTPStatus.OK, content_type, len(body), cache="private, max-age=300")
                self.wfile.write(body)
            except ControlError as exc:
                self.json_response({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
            except (OSError, urllib.error.URLError):
                self.send_error(HTTPStatus.BAD_GATEWAY)
            return
        route = "/index.html" if path in ("/", "/index.html") else path
        requested = (STATIC_DIR / route.lstrip("/")).resolve()
        if STATIC_DIR.resolve() not in requested.parents or not requested.is_file():
            self.send_error(HTTPStatus.NOT_FOUND); return
        body = requested.read_bytes()
        content_type = mimetypes.guess_type(requested.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type == "application/javascript":
            content_type += "; charset=utf-8"
        # Revalidate UI assets on every page load so a container upgrade cannot
        # leave an authenticated browser running stale control logic.
        self._headers(HTTPStatus.OK, content_type, len(body), cache="no-store" if route == "/index.html" else "private, no-cache")
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/login":
            try:
                body = self.read_json()
                if not AUTH_ENABLED:
                    self.json_response({"ok": True, "enabled": False}); return
                if not auth_configured():
                    self.json_response({"ok": False, "error": "控制台认证尚未配置"}, HTTPStatus.SERVICE_UNAVAILABLE); return
                address = self.client_ip()
                allowed, retry_after = login_allowed(address)
                if not allowed:
                    self.json_response({"ok": False, "error": "登录尝试过于频繁"}, HTTPStatus.TOO_MANY_REQUESTS, {"Retry-After": str(retry_after)}); return
                if not verify_credentials(body.get("username"), body.get("password")):
                    record_login_failure(address)
                    self.json_response({"ok": False, "error": "用户名或密码错误"}, HTTPStatus.UNAUTHORIZED); return
                token = create_session(address)
                secure = "; Secure" if SECURE_COOKIE else ""
                cookie = f"{SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={SESSION_TTL}{secure}"
                self.json_response({"ok": True, "username": CONTROL_USERNAME}, headers={"Set-Cookie": cookie}); return
            except ControlError as exc:
                self.json_response({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST); return
        if not self.require_auth(path):
            return
        if path == "/api/logout":
            revoke_session(self.headers.get("Cookie", ""))
            secure = "; Secure" if SECURE_COOKIE else ""
            self.json_response({"ok": True}, headers={"Set-Cookie": f"{SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0{secure}"}); return
        try:
            body = self.read_json()
            if path == "/api/player/rpc":
                self.json_response(proxy_mympd_rpc(body)); return
            if path == "/api/snapcast/volume":
                result = snap_rpc("Client.SetVolume", {"id": str(body.get("clientId", "")), "volume": {"muted": bool(body.get("muted", False)), "percent": clamp_int(body.get("percent"), 0, 100, "音量")}})
            elif path == "/api/snapcast/latency":
                result = snap_rpc("Client.SetLatency", {"id": str(body.get("clientId", "")), "latency": clamp_int(body.get("latency"), -1000, 5000, "延迟")})
            elif path == "/api/snapcast/group-volume":
                result = set_zone_volume(body.get("groupId", ""), body.get("percent"), bool(body.get("muted", False)))
            elif path == "/api/snapcast/client-active":
                result = set_client_active(body.get("clientId"), body.get("active"))
            elif path == "/api/snapcast/stream":
                result = snap_rpc("Group.SetStream", {"id": str(body.get("groupId", "")), "stream_id": str(body.get("streamId", ""))})
            elif path == "/api/snapcast/all-stream":
                stream_id = str(body.get("streamId", ""))
                result = [snap_rpc("Group.SetStream", {"id": group["id"], "stream_id": stream_id}) for group in normalized_snapcast_state()["groups"]]
            elif path == "/api/snapcast/client-name":
                result = set_client_name(body.get("clientId"), body.get("name"))
            elif path == "/api/sources/stop-all":
                result = stop_all_sources()
            elif path == "/api/player/seek":
                result = seek_player(body.get("position"))
            elif path == "/api/player/volume":
                result = set_player_volume(body.get("percent"))
            else:
                self.send_error(HTTPStatus.NOT_FOUND); return
            self.json_response({"ok": True, "result": result})
        except ControlError as exc:
            self.json_response({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            print(f"Unhandled request error: {exc!r}", flush=True)
            self.json_response({"ok": False, "error": "控制服务内部错误"}, HTTPStatus.INTERNAL_SERVER_ERROR)


def main() -> None:
    threading.Thread(target=health_monitor, name="health-monitor", daemon=True).start()
    threading.Thread(target=topology_monitor, name="topology-monitor", daemon=True).start()
    server = ThreadingHTTPServer((CONTROL_HOST, CONTROL_PORT), Handler)
    server.daemon_threads = True
    print(f"Snap / Room listening on {CONTROL_HOST}:{CONTROL_PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
