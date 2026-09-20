#!/usr/bin/env python3
"""LAN-only Snapcast console and persistent MPD player API."""
from __future__ import annotations

import base64, binascii, hashlib, hmac, itertools, json, mimetypes, os, secrets, socket, threading, time
import re
from collections import defaultdict, deque
from http.cookies import SimpleCookie
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

try:
    import mutagen
except ImportError:  # Optional in local tests; installed in the unified image.
    mutagen = None

CONTROL_PORT = int(os.environ.get("CONTROL_PORT", "8080"))
SNAPSERVER_RPC_URL = os.environ.get("SNAPSERVER_RPC_URL", "http://127.0.0.1:1780/jsonrpc")
MPD_SOCKET = os.environ.get("MPD_SOCKET", "/data/dlna/mpd.sock")
STATIC_DIR = Path(__file__).with_name("static")
LIBRARY_ROOT = Path(os.environ.get("LIBRARY_ROOT", "/media"))
LIBRARY_LINK = Path(os.environ.get("LIBRARY_LINK", "/app/data/dlna/library"))
LIBRARY_CONFIG = Path(os.environ.get("LIBRARY_CONFIG", "/app/data/dlna/library.json"))
RPC_IDS = itertools.count(1)
SNAP_RPC_LOCK = threading.Lock()
SNAP_RPC_TARGET = urlparse(SNAPSERVER_RPC_URL)
SNAP_RPC_SOCKET: socket.socket | None = None
SNAP_RPC_BUFFER = bytearray()
AUTH_ENABLED = os.environ.get("CONTROL_AUTH_ENABLED", "true").strip().casefold() not in {"0", "false", "no", "off"}
CONTROL_USERNAME = os.environ.get("CONTROL_USERNAME", "admin")
CONTROL_PASSWORD = os.environ.get("CONTROL_PASSWORD", "")
SESSION_TTL = max(300, int(os.environ.get("CONTROL_SESSION_TTL", "43200")))
SESSION_COOKIE = "snaproom_session"
AUTH_LOCK = threading.Lock()
SESSIONS: dict[str, float] = {}
LOGIN_ATTEMPTS: dict[str, deque[float]] = defaultdict(deque)
LOGIN_WINDOW = 60
LOGIN_LIMIT = 5
MAX_ART_BYTES = 20 * 1024 * 1024
MAX_LYRICS_BYTES = 3 * 1024 * 1024
MAX_PLAYLIST_BYTES = 1024 * 1024
PLAYLIST_SCAN_TTL = 60
PLAYLIST_SCAN_LOCK = threading.Lock()
PLAYLIST_SCAN_CACHE: tuple[float, list[dict[str, Any]]] = (0.0, [])


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


def verify_credentials(username: Any, password: Any) -> bool:
    username_matches = hmac.compare_digest(str(username), CONTROL_USERNAME)
    password_matches = hmac.compare_digest(str(password), CONTROL_PASSWORD)
    return auth_configured() and username_matches and password_matches


def record_login_failure(address: str, now: float | None = None) -> None:
    with AUTH_LOCK:
        LOGIN_ATTEMPTS[address].append(time.time() if now is None else now)


def create_session(address: str, now: float | None = None) -> str:
    current = time.time() if now is None else now
    token = secrets.token_urlsafe(32)
    with AUTH_LOCK:
        SESSIONS[token] = current + SESSION_TTL
        LOGIN_ATTEMPTS.pop(address, None)
        expired = [value for value, expiry in SESSIONS.items() if expiry <= current]
        for value in expired:
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
        expiry = SESSIONS.get(token, 0)
        if expiry <= current:
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
                    SNAP_RPC_SOCKET = socket.create_connection((SNAP_RPC_TARGET.hostname or "127.0.0.1", 1705), timeout=3)
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
        if not separator:
            continue
        if key in result:
            current = result[key]
            result[key] = current + [value] if isinstance(current, list) else [current, value]
        else:
            result[key] = value
    return result


def parse_mpd_records(lines: list[str], first_key: str) -> list[dict[str, str]]:
    records, current = [], None
    for line in lines:
        key, separator, value = line.partition(": ")
        if not separator:
            continue
        if key == first_key:
            if current:
                records.append(current)
            current = {}
        if current is not None and key not in current:
            current[key] = value
    if current:
        records.append(current)
    return records


def mpd_escape(value: Any, field: str = "参数") -> str:
    text = str(value)
    if not text or any(char in text for char in ("\n", "\r", "\0")):
        raise ControlError(f"{field} 无效")
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def playlist_name(value: Any) -> str:
    name = str(value).strip()
    if not name or len(name) > 80 or any(char in name for char in ("/", "\\", "\n", "\r", "\0")):
        raise ControlError("歌单名称必须为 1 到 80 个字符且不能包含路径符号")
    return name


def parse_playlist_import(content: Any) -> list[str]:
    text = str(content).lstrip("\ufeff")
    if len(text.encode("utf-8")) > 1024 * 1024:
        raise ControlError("歌单文件不能超过 1 MB")
    lines = [line.strip() for line in text.splitlines()]
    pls = []
    for line in lines:
        match = re.match(r"(?i)^File(\d+)=(.+)$", line)
        if match:
            pls.append((int(match.group(1)), match.group(2).strip()))
    uris = [uri for _, uri in sorted(pls)] if pls else [line for line in lines if line and not line.startswith("#") and line.lower() != "[playlist]" and "=" not in line]
    uris = [uri for uri in uris if uri and not any(char in uri for char in ("\n", "\r", "\0"))]
    if not uris:
        raise ControlError("歌单中没有可导入的曲目")
    if len(uris) > 5000:
        raise ControlError("单个歌单最多导入 5000 首")
    return uris


def resolve_playlist_uris(uris: list[str], library: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """Map host/PC absolute playlist entries to canonical MPD database paths."""
    canonical = [str(song["file"]).replace("\\", "/") for song in library]
    known = {path.casefold(): path for path in canonical}
    suffixes: dict[str, str | None] = {}
    for path in canonical:
        parts = path.split("/")
        for index in range(len(parts)):
            suffix = "/".join(parts[index:]).casefold()
            if suffix not in suffixes:
                suffixes[suffix] = path
            elif suffixes[suffix] != path:
                suffixes[suffix] = None
    library_path = current_library_path().strip("/")
    resolved, skipped = [], []
    for original in uris:
        value = unquote(str(original).strip()).replace("\\", "/")
        if value.startswith(("http://", "https://")):
            resolved.append(value)
            continue
        if value.lower().startswith("file://"):
            value = value[7:]
        value = value.split("?", 1)[0].lstrip("/")
        prefixes = (
            f"vol1/1000/{library_path}/",
            f"media/{library_path}/",
            "app/data/dlna/library/",
            f"{library_path}/",
        )
        lowered = value.casefold()
        for prefix in prefixes:
            position = lowered.find(prefix.casefold())
            if position >= 0:
                value = value[position + len(prefix) :]
                break
        parts = [part for part in value.split("/") if part not in ("", ".")]
        match = None
        for index in range(len(parts)):
            key = "/".join(parts[index:]).casefold()
            match = known.get(key) or suffixes.get(key)
            if match:
                break
        if match:
            resolved.append(match)
        else:
            skipped.append(original)
    return resolved, skipped


def import_playlist(name_value: Any, content: Any, overwrite: bool = True) -> dict[str, Any]:
    name_text = playlist_name(name_value)
    uris, skipped = resolve_playlist_uris(parse_playlist_import(content), LIBRARY_INDEX.refresh())
    if not uris:
        raise ControlError("歌单中的曲目均无法匹配当前曲库")
    name = mpd_escape(name_text, "歌单名称")
    if overwrite:
        try:
            mpd_command(f"rm {name}")
        except ControlError:
            pass
    commands = ["command_list_begin"]
    commands.extend(f"playlistadd {name} {mpd_escape(uri, '曲目地址')}" for uri in uris)
    commands.append("command_list_end")
    try:
        mpd_command("\n".join(commands), 30)
    except ControlError:
        try:
            mpd_command(f"rm {name}")
        except ControlError:
            pass
        raise
    return {"name": name_text, "count": len(uris), "skipped": len(skipped), "skippedExamples": skipped[:5]}


def read_limited(path: Path, limit: int, label: str) -> bytes:
    try:
        if path.stat().st_size > limit:
            raise ControlError(f"{label}不能超过 {limit // (1024 * 1024)} MB")
        with path.open("rb") as source:
            data = source.read(limit + 1)
    except ControlError:
        raise
    except OSError as exc:
        raise ControlError(f"无法读取{label}：{exc}") from exc
    if len(data) > limit:
        raise ControlError(f"{label}不能超过 {limit // (1024 * 1024)} MB")
    return data


def decode_playlist_file(path: Path) -> str:
    raw = read_limited(path, MAX_PLAYLIST_BYTES, "歌单文件")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("gb18030")


def server_playlist_files(force: bool = False) -> list[dict[str, Any]]:
    global PLAYLIST_SCAN_CACHE
    now = time.monotonic()
    with PLAYLIST_SCAN_LOCK:
        cached_at, cached = PLAYLIST_SCAN_CACHE
        if not force and cached_at and now - cached_at < PLAYLIST_SCAN_TTL:
            return [dict(item) for item in cached]
    root = LIBRARY_ROOT.resolve()
    result = []
    try:
        candidates = root.rglob("*")
        for path in candidates:
            if not path.is_file() or path.suffix.casefold() not in {".m3u", ".m3u8", ".pls"}:
                continue
            relative = path.resolve().relative_to(root).as_posix()
            if any(part.startswith(".") for part in Path(relative).parts):
                continue
            if relative.startswith("tools/snapcast/data/dlna/playlists/"):
                continue
            result.append({"path": relative, "hostPath": f"/vol1/1000/{relative}", "name": path.stem, "size": path.stat().st_size})
            if len(result) >= 500:
                break
    except OSError as exc:
        raise ControlError(f"无法扫描 FNOS 歌单：{exc}") from exc
    result = sorted(result, key=lambda item: item["hostPath"].casefold())
    with PLAYLIST_SCAN_LOCK:
        PLAYLIST_SCAN_CACHE = (now, [dict(item) for item in result])
    return result


def import_server_playlist(path_value: Any, name_value: Any = "") -> dict[str, Any]:
    relative = str(path_value).strip().replace("\\", "/").lstrip("/")
    if relative.startswith("vol1/1000/"):
        relative = relative[len("vol1/1000/") :]
    root = LIBRARY_ROOT.resolve()
    candidate = (root / relative).resolve()
    if root not in candidate.parents or not candidate.is_file() or candidate.suffix.casefold() not in {".m3u", ".m3u8", ".pls"}:
        raise ControlError("只能导入 /vol1/1000 下现有的 M3U、M3U8 或 PLS 文件")
    return import_playlist(name_value or candidate.stem, decode_playlist_file(candidate), True)


def song_payload(song: dict[str, str]) -> dict[str, Any]:
    file = song.get("file", "")
    return {
        "file": file,
        "title": song.get("Title") or song.get("Name") or Path(file).stem,
        "artist": song.get("Artist") or song.get("AlbumArtist") or "未知歌手",
        "albumArtist": song.get("AlbumArtist") or song.get("Artist") or "未知歌手",
        "album": song.get("Album") or "未知专辑",
        "genre": song.get("Genre") or "",
        "date": song.get("Date") or "",
        "track": song.get("Track") or "",
        "disc": song.get("Disc") or "",
        "duration": float(song.get("duration", song.get("Time", 0)) or 0),
        "pos": int(song["Pos"]) if song.get("Pos", "").isdigit() else None,
        "id": int(song["Id"]) if song.get("Id", "").isdigit() else None,
    }


def normalize_library_path(value: Any, root: Path = LIBRARY_ROOT) -> tuple[str, Path]:
    text = str(value).strip().replace("\\", "/")
    if text.startswith("/vol1/1000/"):
        text = text[len("/vol1/1000/") :]
    text = text.strip("/")
    if not text:
        raise ControlError("曲库目录不能为空")
    root_resolved, candidate = root.resolve(), (root.resolve() / text).resolve()
    if root_resolved not in candidate.parents or not candidate.is_dir():
        raise ControlError("曲库目录必须位于 /vol1/1000 内且已经存在")
    return candidate.relative_to(root_resolved).as_posix(), candidate


def current_library_path() -> str:
    try:
        return normalize_library_path(json.loads(LIBRARY_CONFIG.read_text(encoding="utf-8")).get("path", ""))[0]
    except (OSError, ValueError, AttributeError, ControlError):
        try:
            return LIBRARY_LINK.resolve().relative_to(LIBRARY_ROOT.resolve()).as_posix()
        except (OSError, ValueError):
            return "music"


def library_config_state() -> dict[str, Any]:
    try:
        directories = sorted(item.name for item in LIBRARY_ROOT.iterdir() if item.is_dir() and not item.name.startswith("."))
    except OSError as exc:
        raise ControlError(f"无法读取曲库根目录：{exc}") from exc
    return {"path": current_library_path(), "hostRoot": "/vol1/1000", "directories": directories}


class LibraryIndex:
    """A thread-safe, paginated view of MPD's persistent database."""
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.songs: list[dict[str, Any]] = []
        self.loaded_at = 0.0
        self.updating = ""

    def invalidate(self) -> None:
        with self.lock:
            self.loaded_at = 0

    def refresh(self, force: bool = False) -> list[dict[str, Any]]:
        updating = str(parse_mpd(mpd_command("status")).get("updating_db", ""))
        with self.lock:
            stale = force or not self.songs or not self.loaded_at or updating != self.updating
            if not stale:
                return list(self.songs)
        songs = [song_payload(item) for item in parse_mpd_records(mpd_command("listallinfo", 30), "file")]
        songs.sort(key=lambda item: (item["artist"].casefold(), item["album"].casefold(), item["title"].casefold()))
        with self.lock:
            self.songs, self.loaded_at, self.updating = songs, time.time(), updating
            return list(self.songs)

    def page(self, query: str = "", offset: int = 0, limit: int = 60) -> dict[str, Any]:
        songs, needle = self.refresh(), query.strip().casefold()
        if needle:
            songs = [item for item in songs if needle in " ".join((item["title"], item["artist"], item["album"], item["file"])).casefold()]
        total = len(songs)
        return {"items": songs[offset : offset + limit], "total": total, "offset": offset, "limit": limit, "hasMore": offset + limit < total}


LIBRARY_INDEX = LibraryIndex()


def opaque_id(kind: str, *parts: str) -> str:
    payload = json.dumps([kind, *parts], ensure_ascii=False, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def decode_opaque_id(value: Any, expected: str) -> list[str]:
    try:
        text = str(value)
        decoded = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
        payload = json.loads(decoded)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError, binascii.Error) as exc:
        raise ControlError("曲库项目标识无效") from exc
    if not isinstance(payload, list) or not payload or payload[0] != expected or not all(isinstance(item, str) for item in payload):
        raise ControlError("曲库项目标识无效")
    return payload[1:]


def paginate(items: list[dict[str, Any]], offset: int, limit: int) -> dict[str, Any]:
    total = len(items)
    return {"items": items[offset : offset + limit], "total": total, "offset": offset, "limit": limit, "hasMore": offset + limit < total}


def library_browse(view: str, query: str = "", offset: int = 0, limit: int = 60, parent: str = "") -> dict[str, Any]:
    songs, needle = LIBRARY_INDEX.refresh(), query.strip().casefold()
    if view == "tracks":
        if needle:
            songs = [item for item in songs if needle in " ".join((item["title"], item["artist"], item["album"], item["file"])).casefold()]
        return {"view": view, **paginate(songs, offset, limit)}
    if view == "albums":
        grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        for song in songs:
            key = (song["albumArtist"], song["album"], song["date"])
            grouped.setdefault(key, []).append(song)
        items = [{
            "id": opaque_id("album", *key), "kind": "album", "title": key[1], "artist": key[0], "date": key[2],
            "count": len(tracks), "duration": sum(track["duration"] for track in tracks), "artUri": tracks[0]["file"],
        } for key, tracks in grouped.items()]
        items.sort(key=lambda item: (item["artist"].casefold(), item["title"].casefold(), item["date"]))
    elif view == "artists":
        grouped_artist: dict[str, list[dict[str, Any]]] = {}
        for song in songs:
            grouped_artist.setdefault(song["albumArtist"] or song["artist"], []).append(song)
        items = []
        for artist, tracks in grouped_artist.items():
            albums = {(track["album"], track["date"]) for track in tracks}
            items.append({
                "id": opaque_id("artist", artist), "kind": "artist", "title": artist,
                "count": len(tracks), "albumCount": len(albums), "artUris": [track["file"] for track in tracks[:4]],
            })
        items.sort(key=lambda item: item["title"].casefold())
    elif view == "folders":
        normalized_parent = str(parent).replace("\\", "/").strip("/")
        if any(part in (".", "..") for part in normalized_parent.split("/") if part):
            raise ControlError("文件夹路径无效")
        prefix = normalized_parent + "/" if normalized_parent else ""
        folders: dict[str, dict[str, Any]] = {}
        direct_tracks: list[dict[str, Any]] = []
        for song in songs:
            path = song["file"]
            if prefix and not path.casefold().startswith(prefix.casefold()):
                continue
            remainder = path[len(prefix) :]
            if "/" in remainder:
                name = remainder.split("/", 1)[0]
                child = prefix + name
                folders.setdefault(child.casefold(), {"id": opaque_id("folder", child), "kind": "folder", "title": name, "path": child})
            elif remainder:
                direct_tracks.append({**song, "kind": "track"})
        items = sorted(folders.values(), key=lambda item: item["title"].casefold()) + sorted(direct_tracks, key=lambda item: item["title"].casefold())
    else:
        raise ControlError("不支持的曲库视图")
    if needle:
        items = [item for item in items if needle in " ".join(str(item.get(key, "")) for key in ("title", "artist", "date", "path")).casefold()]
    return {"view": view, **paginate(items, offset, limit)}


def library_detail(kind: str, item_id: Any) -> dict[str, Any]:
    songs = LIBRARY_INDEX.refresh()
    if kind == "album":
        artist, album, date = decode_opaque_id(item_id, "album")
        tracks = [song for song in songs if (song["albumArtist"], song["album"], song["date"]) == (artist, album, date)]
        tracks.sort(key=lambda item: (str(item["disc"]), str(item["track"]), item["title"].casefold()))
        if not tracks:
            raise ControlError("专辑不存在")
        return {"kind": kind, "id": str(item_id), "title": album, "artist": artist, "date": date, "artUri": tracks[0]["file"], "tracks": tracks}
    if kind == "artist":
        (artist,) = decode_opaque_id(item_id, "artist")
        tracks = [song for song in songs if (song["albumArtist"] or song["artist"]) == artist]
        if not tracks:
            raise ControlError("歌手不存在")
        albums: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for track in tracks:
            albums.setdefault((track["album"], track["date"]), []).append(track)
        groups = []
        for (album, date), album_tracks in sorted(albums.items(), key=lambda item: (item[0][1], item[0][0].casefold())):
            album_tracks.sort(key=lambda item: (str(item["disc"]), str(item["track"]), item["title"].casefold()))
            groups.append({"id": opaque_id("album", artist, album, date), "title": album, "date": date, "artUri": album_tracks[0]["file"], "tracks": album_tracks})
        return {"kind": kind, "id": str(item_id), "title": artist, "albums": groups, "tracks": tracks}
    if kind == "folder":
        (folder,) = decode_opaque_id(item_id, "folder")
        return {"kind": kind, "id": str(item_id), "title": Path(folder).name, "path": folder, **library_browse("folders", parent=folder, limit=200)}
    raise ControlError("不支持的曲库详情")


def local_media_path(uri: Any) -> Path:
    value = unquote(str(uri)).replace("\\", "/").lstrip("/")
    if not value or value.startswith(("http://", "https://")) or "\0" in value:
        raise ControlError("只能读取本地曲库文件")
    base = LIBRARY_LINK.resolve()
    candidate = (base / value).resolve()
    if base not in candidate.parents or not candidate.is_file():
        raise ControlError("媒体文件不存在或超出当前曲库")
    return candidate


def embedded_art(path: Path) -> tuple[bytes, str] | None:
    if mutagen is None:
        return None
    try:
        audio = mutagen.File(path)
        pictures = getattr(audio, "pictures", None)
        if pictures:
            return bytes(pictures[0].data), pictures[0].mime or "image/jpeg"
        tags = getattr(audio, "tags", None)
        if tags:
            for value in tags.values():
                if value.__class__.__name__.startswith("APIC") and getattr(value, "data", None):
                    return bytes(value.data), getattr(value, "mime", "image/jpeg") or "image/jpeg"
            covers = tags.get("covr") if hasattr(tags, "get") else None
            if covers:
                data = bytes(covers[0])
                return data, "image/png" if data.startswith(b"\x89PNG") else "image/jpeg"
    except Exception:
        return None
    return None


def media_art(uri: Any) -> tuple[bytes, str, str] | None:
    path = local_media_path(uri)
    candidates = {item.name.casefold(): item for item in path.parent.iterdir() if item.is_file()}
    for stem in ("cover", "folder", "front"):
        for suffix in (".jpg", ".jpeg", ".png", ".webp"):
            candidate = candidates.get(stem + suffix)
            if candidate:
                data = read_limited(candidate, MAX_ART_BYTES, "封面文件")
                return data, mimetypes.guess_type(candidate.name)[0] or "image/jpeg", hashlib.sha1(data).hexdigest()
    result = embedded_art(path)
    if result:
        data, mime = result
        if len(data) > MAX_ART_BYTES:
            raise ControlError("内嵌封面不能超过 20 MB")
        return data, mime, hashlib.sha1(data).hexdigest()
    return None


LRC_TIME = re.compile(r"\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]")


def parse_lyrics(text: str) -> dict[str, Any]:
    synced: list[dict[str, Any]] = []
    plain: list[str] = []
    for raw in text.lstrip("\ufeff").splitlines():
        matches = list(LRC_TIME.finditer(raw))
        lyric = LRC_TIME.sub("", raw).strip()
        if matches:
            for match in matches:
                fraction = match.group(3) or "0"
                milliseconds = int((fraction + "00")[:3])
                synced.append({"time": int(match.group(1)) * 60 + int(match.group(2)) + milliseconds / 1000, "text": lyric})
        elif raw.strip() and not re.match(r"^\[[a-z]+:.*\]$", raw.strip(), re.I):
            plain.append(raw.strip())
    if synced:
        synced.sort(key=lambda item: item["time"])
        return {"kind": "synced", "lines": synced, "text": "\n".join(item["text"] for item in synced)}
    return {"kind": "plain" if plain else "none", "lines": [], "text": "\n".join(plain)}


def embedded_lyrics(path: Path) -> str:
    if mutagen is None:
        return ""
    try:
        audio = mutagen.File(path)
        tags = getattr(audio, "tags", None)
        if not tags:
            return ""
        for key in ("syncedlyrics", "lyrics", "unsyncedlyrics", "LYRICS", "UNSYNCEDLYRICS"):
            value = tags.get(key) if hasattr(tags, "get") else None
            if value:
                if isinstance(value, (list, tuple)):
                    value = value[0]
                return str(getattr(value, "text", value))
        for value in tags.values():
            if value.__class__.__name__.startswith("USLT") and getattr(value, "text", None):
                return str(value.text)
    except Exception:
        return ""
    return ""


def media_lyrics(uri: Any) -> dict[str, Any]:
    path = local_media_path(uri)
    candidates = (path.with_suffix(".lrc"), path.with_suffix(".txt"), path.parent / "lyrics" / (path.stem + ".lrc"))
    for candidate in candidates:
        if candidate.is_file():
            raw = read_limited(candidate, MAX_LYRICS_BYTES, "歌词文件")
            for encoding in ("utf-8-sig", "gb18030"):
                try:
                    return {"source": candidate.name, **parse_lyrics(raw.decode(encoding))}
                except UnicodeDecodeError:
                    continue
    text = embedded_lyrics(path)
    if len(text.encode("utf-8")) > MAX_LYRICS_BYTES:
        raise ControlError("内嵌歌词不能超过 3 MB")
    return {"source": "embedded" if text else "", **parse_lyrics(text)}


def playlist_detail(name_value: Any) -> dict[str, Any]:
    name_text = playlist_name(name_value)
    tracks = [song_payload(item) for item in parse_mpd_records(mpd_command(f"listplaylistinfo {mpd_escape(name_text, '歌单名称')}", 15), "file")]
    for position, track in enumerate(tracks):
        track["playlistPos"] = position
    return {"name": name_text, "tracks": tracks, "count": len(tracks), "duration": sum(track["duration"] for track in tracks)}


def playlist_m3u(name_value: Any) -> bytes:
    detail = playlist_detail(name_value)
    root = current_library_path().strip("/")
    lines = ["#EXTM3U"]
    for track in detail["tracks"]:
        lines.append(f"#EXTINF:{int(track['duration'])},{track['artist']} - {track['title']}")
        file = track["file"]
        lines.append(file if file.startswith(("http://", "https://")) else f"/vol1/1000/{root}/{file}")
    return ("\ufeff" + "\n".join(lines) + "\n").encode("utf-8")


def save_library_path(value: Any) -> dict[str, Any]:
    relative, target = normalize_library_path(value)
    LIBRARY_LINK.parent.mkdir(parents=True, exist_ok=True)
    if LIBRARY_LINK.exists() and not LIBRARY_LINK.is_symlink():
        raise ControlError("曲库链接位置已被普通文件或目录占用")
    suffix = f".{os.getpid()}.{threading.get_ident()}.tmp"
    temp_link = LIBRARY_LINK.with_name(LIBRARY_LINK.name + suffix)
    temp_config = LIBRARY_CONFIG.with_name(LIBRARY_CONFIG.name + suffix)
    try:
        temp_link.symlink_to(target, target_is_directory=True)
        os.replace(temp_link, LIBRARY_LINK)
        temp_config.write_text(json.dumps({"path": relative}, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(temp_config, LIBRARY_CONFIG)
    finally:
        temp_link.unlink(missing_ok=True)
        temp_config.unlink(missing_ok=True)
    mpd_command("update")
    LIBRARY_INDEX.invalidate()
    return library_config_state()


def player_state() -> dict[str, Any]:
    status = parse_mpd(mpd_command("status"))
    song = song_payload(parse_mpd(mpd_command("currentsong")))
    return {
        "state": status.get("state", "stop"), "volume": int(status.get("volume", -1)),
        "elapsed": float(status.get("elapsed", 0)), "duration": float(status.get("duration", song["duration"]) or 0),
        "song": song, "queueLength": int(status.get("playlistlength", 0)), "queueVersion": int(status.get("playlist", 0)),
        "audio": status.get("audio", ""), "repeat": status.get("repeat") == "1", "random": status.get("random") == "1",
        "single": status.get("single") == "1", "consume": status.get("consume") == "1",
        "updating": bool(status.get("updating_db")), "error": status.get("error", ""),
        "sourceType": "mpd", "capabilities": source_capabilities("mpd"),
    }


def player_collections() -> dict[str, Any]:
    queue = [song_payload(item) for item in parse_mpd_records(mpd_command("playlistinfo", 15), "file")]
    playlists = [item["playlist"] for item in parse_mpd_records(mpd_command("listplaylists", 10), "playlist")]
    return {"queue": queue, "playlists": playlists}


def player_bootstrap(query: str = "", offset: int = 0, limit: int = 60) -> dict[str, Any]:
    return {"player": player_state(), "library": LIBRARY_INDEX.page(query, offset, limit), "libraryConfig": library_config_state(), **player_collections()}


def should_recover_remote(status: dict[str, Any], song: dict[str, Any]) -> bool:
    return status.get("state") == "stop" and bool(status.get("error")) and str(song.get("file", "")).startswith(("http://", "https://")) and str(status.get("songid", "")).isdigit()


def remote_stream_watchdog() -> None:
    if not hasattr(socket, "AF_UNIX"):
        return
    attempts: dict[str, int] = {}
    while True:
        time.sleep(2)
        try:
            status, song = parse_mpd(mpd_command("status")), parse_mpd(mpd_command("currentsong"))
            song_id = str(status.get("songid", ""))
            if status.get("state") == "play" and song_id:
                attempts.pop(song_id, None)
                continue
            count = attempts.get(song_id, 0)
            if not should_recover_remote(status, song) or count >= 3:
                continue
            attempts[song_id] = count + 1
            elapsed = max(0, int(float(status.get("elapsed", 0) or 0)) - 2)
            time.sleep((2, 5, 10)[count])
            mpd_command("clearerror")
            mpd_command(f"playid {song_id}")
            if elapsed > 5:
                time.sleep(1)
                mpd_command(f"seekid {song_id} {elapsed}")
        except ControlError as exc:
            print(f"MPD watchdog: {exc}", flush=True)


def source_type(stream_id: Any) -> str:
    return {"airplay": "airplay", "dlna": "mpd", "default": "auto"}.get(str(stream_id).strip().casefold(), "unknown")


def source_capabilities(kind: str) -> dict[str, bool]:
    controllable = kind == "mpd"
    return {
        "playPause": controllable,
        "previous": controllable,
        "next": controllable,
        "seek": controllable,
        "queue": controllable,
    }


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
        "capabilities": source_capabilities(effective),
    }


def normalized_snapcast_state() -> dict[str, Any]:
    server = snap_rpc("Server.GetStatus")["server"]
    raw_streams = server.get("streams", [])
    active_kind = next((source_type(item.get("id")) for item in raw_streams if item.get("status") == "playing" and source_type(item.get("id")) != "auto"), "mpd")
    streams = [source_descriptor(stream, active_kind) for stream in raw_streams]
    streams_by_id = {stream["id"]: stream for stream in streams}
    groups = []
    for group in server.get("groups", []):
        clients = []
        for client in group.get("clients", []):
            config, volume = client.get("config", {}), client.get("config", {}).get("volume", {})
            clients.append({
                "id": client["id"], "name": config.get("name") or client.get("host", {}).get("name") or client["id"],
                "connected": bool(client.get("connected")), "latency": int(config.get("latency", 0)),
                "volume": int(volume.get("percent", 0)), "muted": bool(volume.get("muted", False)),
                "ip": client.get("host", {}).get("ip", "").replace("::ffff:", ""), "version": client.get("snapclient", {}).get("version", ""),
            })
        stream_id = group.get("stream_id", "")
        connected = [client for client in clients if client["connected"]]
        source = streams_by_id.get(stream_id, source_descriptor({"id": stream_id}, active_kind))
        groups.append({
            "id": group["id"], "name": group.get("name") or "播放组", "streamId": stream_id,
            "sourceType": source["effectiveSourceType"], "source": source,
            "muted": bool(group.get("muted", False)),
            "volume": round(sum(client["volume"] for client in connected) / len(connected)) if connected else 0,
            "connectedCount": len(connected), "clients": clients,
        })
    return {"streams": streams, "groups": groups}


def set_zone_volume(group_id: Any, percent: Any, muted: bool = False) -> list[Any]:
    identifier = str(group_id)
    value = clamp_int(percent, 0, 100, "音量")
    group = next((item for item in normalized_snapcast_state()["groups"] if item["id"] == identifier), None)
    if group is None:
        raise ControlError("播放区域不存在")
    return [
        snap_rpc("Client.SetVolume", {"id": client["id"], "volume": {"muted": muted, "percent": value}})
        for client in group["clients"]
        if client["connected"]
    ]


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
    return {"snapcast": snapcast, "zones": snapcast.get("groups", []), "sources": snapcast.get("streams", []), "player": player, "dlna": player, "system": {"hostname": socket.gethostname()}, "errors": errors}


def run_player_action(body: dict[str, Any]) -> Any:
    action = str(body.get("action", ""))
    simple = {"play": "play", "pause": "pause 1", "resume": "pause 0", "stop": "stop", "next": "next", "previous": "previous", "clear": "clear"}
    if action in simple:
        return mpd_command(simple[action])
    if action in {"repeat", "random", "single", "consume"}:
        return mpd_command(f"{action} {1 if bool(body.get('enabled')) else 0}")
    if action == "volume":
        return mpd_command(f"setvol {clamp_int(body.get('value'), 0, 100, '音量')}")
    if action == "seek":
        return mpd_command(f"seekcur {clamp_int(body.get('seconds'), 0, 604800, '播放位置')}")
    if action in {"add", "play-now", "add-next"}:
        uri = mpd_escape(body.get("uri", ""), "曲目路径")
        if action == "play-now":
            mpd_command("clear")
        added = parse_mpd(mpd_command(f"addid {uri}"))
        song_id = added.get("Id")
        if action == "add-next":
            destination = int(parse_mpd(mpd_command("status")).get("song", -1)) + 1
            mpd_command(f"moveid {song_id} {max(0, destination)}")
        if action == "play-now":
            mpd_command(f"playid {song_id}")
        return added
    if action in {"add-many", "play-many"}:
        values = body.get("uris", [])
        if not isinstance(values, list) or not values or len(values) > 5000:
            raise ControlError("曲目列表必须包含 1 到 5000 首")
        uris = [mpd_escape(value, "曲目路径") for value in values]
        if action == "play-many":
            mpd_command("clear")
        mpd_command("\n".join(["command_list_begin", *(f"add {uri}" for uri in uris), "command_list_end"]), 30)
        if action == "play-many":
            mpd_command("play")
        return {"count": len(uris)}
    if action == "play-position":
        return mpd_command(f"play {clamp_int(body.get('position'), 0, 100000, '队列位置')}")
    if action == "remove":
        return mpd_command(f"deleteid {clamp_int(body.get('id'), 0, 2147483647, '曲目 ID')}")
    if action == "move":
        return mpd_command(f"moveid {clamp_int(body.get('id'), 0, 2147483647, '曲目 ID')} {clamp_int(body.get('position'), 0, 100000, '队列位置')}")
    if action in {"playlist-save", "playlist-load", "playlist-delete"}:
        name = mpd_escape(playlist_name(body.get("name", "")), "歌单名称")
        if action == "playlist-save":
            if bool(body.get("overwrite")):
                try:
                    mpd_command(f"rm {name}")
                except ControlError:
                    pass
            return mpd_command(f"save {name}")
        if action == "playlist-load":
            if not bool(body.get("append", False)):
                mpd_command("clear")
            result = mpd_command(f"load {name}")
            if bool(body.get("play", True)):
                mpd_command("play")
            return result
        return mpd_command(f"rm {name}")
    if action == "playlist-play-position":
        name = mpd_escape(playlist_name(body.get("name", "")), "歌单名称")
        position = clamp_int(body.get("position"), 0, 100000, "歌单位置")
        mpd_command("clear")
        mpd_command(f"load {name}")
        return mpd_command(f"play {position}")
    if action == "playlist-rename":
        old = mpd_escape(playlist_name(body.get("name", "")), "歌单名称")
        new = mpd_escape(playlist_name(body.get("newName", "")), "新歌单名称")
        return mpd_command(f"rename {old} {new}")
    if action == "playlist-add":
        name = mpd_escape(playlist_name(body.get("name", "")), "歌单名称")
        uri = mpd_escape(body.get("uri", ""), "曲目路径")
        return mpd_command(f"playlistadd {name} {uri}")
    if action == "playlist-remove":
        name = mpd_escape(playlist_name(body.get("name", "")), "歌单名称")
        position = clamp_int(body.get("position"), 0, 100000, "歌单位置")
        return mpd_command(f"playlistdelete {name} {position}")
    if action == "playlist-move":
        name = mpd_escape(playlist_name(body.get("name", "")), "歌单名称")
        source = clamp_int(body.get("from"), 0, 100000, "原位置")
        target = clamp_int(body.get("to"), 0, 100000, "新位置")
        return mpd_command(f"playlistmove {name} {source} {target}")
    if action == "playlist-import":
        return import_playlist(body.get("name", ""), body.get("content", ""), bool(body.get("overwrite", True)))
    if action == "playlist-import-server":
        return import_server_playlist(body.get("path", ""), body.get("name", ""))
    if action == "update-library":
        LIBRARY_INDEX.invalidate()
        return mpd_command("update")
    raise ControlError("不支持的播放器操作")


class Handler(BaseHTTPRequestHandler):
    server_version = "SnapRoom/3.0"
    def log_message(self, fmt: str, *args: Any) -> None:
        request = str(args[0]) if args else ""
        if not request.startswith(("GET /api/state ", "GET /api/health ")):
            print(f"{self.address_string()} - {fmt % args}", flush=True)

    def _headers(self, status: int, content_type: str, length: int, cache: str = "no-store", disposition: str = "", extra: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", cache)
        if disposition:
            self.send_header("Content-Disposition", disposition)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:")
        for name, value in (extra or {}).items():
            self.send_header(name, value)
        self.end_headers()

    def json_response(self, payload: Any, status: int = HTTPStatus.OK, headers: dict[str, str] | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        self._headers(status, "application/json; charset=utf-8", len(body), extra=headers)
        self.wfile.write(body)

    def binary_response(self, body: bytes, content_type: str, cache: str = "private, max-age=3600", disposition: str = "") -> None:
        self._headers(HTTPStatus.OK, content_type, len(body), cache, disposition)
        self.wfile.write(body)

    def read_json(self) -> dict[str, Any]:
        if self.headers.get_content_type() != "application/json":
            raise ControlError("请求必须使用 application/json")
        length = clamp_int(self.headers.get("Content-Length", 0), 0, 1100000, "Content-Length")
        try:
            value = json.loads(self.rfile.read(length))
        except json.JSONDecodeError as exc:
            raise ControlError("JSON 格式错误") from exc
        if not isinstance(value, dict):
            raise ControlError("请求体必须是对象")
        return value

    def query_page(self) -> tuple[str, int, int]:
        params = parse_qs(urlparse(self.path).query)
        return (
            unquote(params.get("q", [""])[0])[:200],
            clamp_int(params.get("offset", [0])[0], 0, 1000000, "offset"),
            clamp_int(params.get("limit", [60])[0], 1, 200, "limit"),
        )

    def authenticated(self) -> bool:
        return bool(session_token(self.headers.get("Cookie", "")))

    def require_auth(self, path: str) -> bool:
        if not path.startswith("/api/") or path in {"/api/health", "/api/auth", "/api/login"} or self.authenticated():
            return True
        self.json_response({"ok": False, "error": "需要登录"}, HTTPStatus.UNAUTHORIZED)
        return False

    def do_GET(self) -> None:  # noqa: N802
        parsed_url = urlparse(self.path)
        path, params = parsed_url.path, parse_qs(parsed_url.query)
        if not self.require_auth(path):
            return
        try:
            if path == "/api/auth":
                self.json_response({"ok": True, "enabled": AUTH_ENABLED, "configured": auth_configured(), "authenticated": self.authenticated(), "username": CONTROL_USERNAME if AUTH_ENABLED else ""}); return
            if path == "/api/state":
                self.json_response(combined_state()); return
            if path == "/api/health":
                state = combined_state(); self.json_response({"ok": not state["errors"], "errors": state["errors"]}); return
            if path == "/api/player/bootstrap":
                self.json_response({"ok": True, **player_bootstrap(*self.query_page())}); return
            if path == "/api/player/library":
                query, offset, limit = self.query_page()
                view = params.get("view", ["tracks"])[0]
                parent = unquote(params.get("parent", [""])[0])[:1000]
                self.json_response({"ok": True, **library_browse(view, query, offset, limit, parent)}); return
            if path == "/api/player/library-detail":
                kind = params.get("kind", [""])[0]
                self.json_response({"ok": True, **library_detail(kind, params.get("id", [""])[0])}); return
            if path == "/api/player/art":
                art = media_art(params.get("uri", [""])[0])
                if not art:
                    self.send_error(HTTPStatus.NOT_FOUND); return
                body, mime, _etag = art
                self.binary_response(body, mime, "private, max-age=86400, immutable")
                return
            if path == "/api/player/lyrics":
                self.json_response({"ok": True, **media_lyrics(params.get("uri", [""])[0])}); return
            if path == "/api/player/playlist":
                self.json_response({"ok": True, **playlist_detail(params.get("name", [""])[0])}); return
            if path == "/api/player/playlist-export":
                name = playlist_name(params.get("name", [""])[0])
                body = playlist_m3u(name)
                safe_name = re.sub(r'[^A-Za-z0-9_.-]+', "_", name).strip("_") or "playlist"
                encoded_name = quote(name + ".m3u8", safe="")
                disposition = f'attachment; filename="{safe_name}.m3u8"; filename*=UTF-8\'\'{encoded_name}'
                self.binary_response(body, "audio/x-mpegurl; charset=utf-8", "no-store", disposition)
                return
            if path == "/api/player/collections":
                self.json_response({"ok": True, **player_collections()}); return
            if path == "/api/player/playlist-files":
                force = params.get("refresh", ["0"])[0] in {"1", "true"}
                self.json_response({"ok": True, "items": server_playlist_files(force)}); return
            if path == "/api/mpd/library-config":
                self.json_response({"ok": True, **library_config_state()}); return
        except ControlError as exc:
            self.json_response({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST); return
        route = "/index.html" if path in ("/", "/index.html") else path
        requested = (STATIC_DIR / route.lstrip("/")).resolve()
        if STATIC_DIR.resolve() not in requested.parents or not requested.is_file():
            self.send_error(HTTPStatus.NOT_FOUND); return
        body = requested.read_bytes()
        content_type = mimetypes.guess_type(requested.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type == "application/javascript":
            content_type += "; charset=utf-8"
        self._headers(HTTPStatus.OK, content_type, len(body))
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
                allowed, retry_after = login_allowed(self.client_address[0])
                if not allowed:
                    self.json_response({"ok": False, "error": "登录尝试过于频繁"}, HTTPStatus.TOO_MANY_REQUESTS, {"Retry-After": str(retry_after)}); return
                if not verify_credentials(body.get("username"), body.get("password")):
                    record_login_failure(self.client_address[0])
                    self.json_response({"ok": False, "error": "用户名或密码错误"}, HTTPStatus.UNAUTHORIZED); return
                token = create_session(self.client_address[0])
                cookie = f"{SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={SESSION_TTL}"
                self.json_response({"ok": True, "username": CONTROL_USERNAME}, headers={"Set-Cookie": cookie}); return
            except ControlError as exc:
                self.json_response({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST); return
        if not self.require_auth(path):
            return
        if path == "/api/logout":
            revoke_session(self.headers.get("Cookie", ""))
            self.json_response({"ok": True}, headers={"Set-Cookie": f"{SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0"}); return
        try:
            body = self.read_json()
            if path == "/api/player/action":
                result = run_player_action(body)
            elif path == "/api/player/library-config":
                result = save_library_path(body.get("path", ""))
            elif path == "/api/snapcast/volume":
                result = snap_rpc("Client.SetVolume", {"id": str(body.get("clientId", "")), "volume": {"muted": bool(body.get("muted", False)), "percent": clamp_int(body.get("percent"), 0, 100, "音量")}})
            elif path == "/api/snapcast/latency":
                result = snap_rpc("Client.SetLatency", {"id": str(body.get("clientId", "")), "latency": clamp_int(body.get("latency"), -1000, 5000, "延迟")})
            elif path == "/api/snapcast/group-volume":
                result = set_zone_volume(body.get("groupId", ""), body.get("percent"), bool(body.get("muted", False)))
            elif path == "/api/snapcast/stream":
                result = snap_rpc("Group.SetStream", {"id": str(body.get("groupId", "")), "stream_id": str(body.get("streamId", ""))})
            elif path == "/api/snapcast/all-stream":
                stream_id = str(body.get("streamId", ""))
                result = [snap_rpc("Group.SetStream", {"id": group["id"], "stream_id": stream_id}) for group in normalized_snapcast_state()["groups"]]
            else:
                self.send_error(HTTPStatus.NOT_FOUND); return
            self.json_response({"ok": True, "result": result})
        except ControlError as exc:
            self.json_response({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            print(f"Unhandled request error: {exc!r}", flush=True)
            self.json_response({"ok": False, "error": "控制服务内部错误"}, HTTPStatus.INTERNAL_SERVER_ERROR)


def main() -> None:
    threading.Thread(target=remote_stream_watchdog, name="mpd-watchdog", daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", CONTROL_PORT), Handler)
    server.daemon_threads = True
    print(f"Snap/Room 3 listening on 0.0.0.0:{CONTROL_PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
