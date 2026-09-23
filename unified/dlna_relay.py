#!/usr/bin/env python3
"""Loopback-only resilient HTTP relay and MPD command proxy for DLNA URLs."""

from __future__ import annotations

import hashlib
import http.client
import os
import re
import socket
import socketserver
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


RELAY_HOST = "127.0.0.1"
RELAY_HTTP_PORT = int(os.environ.get("DLNA_RELAY_HTTP_PORT", "1790"))
RELAY_MPD_PORT = int(os.environ.get("DLNA_RELAY_MPD_PORT", "6601"))
MPD_HOST = "127.0.0.1"
MPD_PORT = int(os.environ.get("DLNA_RELAY_UPSTREAM_MPD_PORT", "6600"))
MAX_RETRIES = int(os.environ.get("DLNA_RELAY_MAX_RETRIES", "10"))
READ_TIMEOUT = int(os.environ.get("DLNA_RELAY_READ_TIMEOUT", "20"))
CHUNK_SIZE = 128 * 1024
URL_COMMAND = re.compile(rb'^(add|addid)\s+"((?:\\.|[^"\\])*)"(.*?)(\r?\n)$')


def mpd_unescape(value: bytes) -> str:
    text = value.decode("utf-8", "strict")
    return re.sub(r"\\([\\\"])", r"\1", text)


def mpd_escape(value: str) -> bytes:
    return value.replace("\\", "\\\\").replace('"', '\\"').encode()


class RelayRegistry:
    def __init__(self, limit: int = 256):
        self.limit = limit
        self._urls: OrderedDict[str, str] = OrderedDict()
        self._lock = threading.Lock()

    def register(self, url: str) -> str:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return url
        token = hashlib.sha256(url.encode()).hexdigest()[:32]
        with self._lock:
            self._urls[token] = url
            self._urls.move_to_end(token)
            while len(self._urls) > self.limit:
                self._urls.popitem(last=False)
        return f"http://{RELAY_HOST}:{RELAY_HTTP_PORT}/stream/{token}"

    def get(self, token: str) -> str | None:
        with self._lock:
            url = self._urls.get(token)
            if url:
                self._urls.move_to_end(token)
            return url


REGISTRY = RelayRegistry()


def rewrite_command(line: bytes, registry: RelayRegistry = REGISTRY) -> bytes:
    match = URL_COMMAND.match(line)
    if not match:
        return line
    try:
        source = mpd_unescape(match.group(2))
    except UnicodeError:
        return line
    local = registry.register(source)
    if local == source:
        return line
    return match.group(1) + b' "' + mpd_escape(local) + b'"' + match.group(3) + match.group(4)


def content_range_total(value: str | None) -> int | None:
    if not value or "/" not in value:
        return None
    total = value.rsplit("/", 1)[1]
    return int(total) if total.isdigit() else None


def parse_range(value: str | None) -> int:
    if not value:
        return 0
    match = re.fullmatch(r"bytes=(\d+)-", value.strip())
    if not match:
        raise ValueError("only an open-ended byte range is supported")
    return int(match.group(1))


def open_upstream(url: str, offset: int):
    headers = {
        "Accept-Encoding": "identity",
        "Connection": "close",
        "User-Agent": "Music Player Daemon",
    }
    if offset:
        headers["Range"] = f"bytes={offset}-"
    request = urllib.request.Request(url, headers=headers)
    return urllib.request.urlopen(request, timeout=READ_TIMEOUT)


class RelayHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "SnapRoomRelay/1"

    def log_message(self, fmt, *args):
        print(f"dlna-relay http: {fmt % args}", flush=True)

    def do_HEAD(self):
        self._serve(False)

    def do_GET(self):
        self._serve(True)

    def _serve(self, send_body: bool):
        parsed = urllib.parse.urlsplit(self.path)
        token = parsed.path.removeprefix("/stream/")
        source = REGISTRY.get(token) if re.fullmatch(r"[0-9a-f]{32}", token) else None
        if not source:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            requested_offset = parse_range(self.headers.get("Range"))
            upstream = open_upstream(source, requested_offset)
        except ValueError as exc:
            self.send_error(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE, str(exc))
            return
        except urllib.error.HTTPError as exc:
            self.send_error(exc.code, "upstream rejected the request")
            return
        except Exception as exc:
            print(f"dlna-relay open failed: {type(exc).__name__}: {exc}", flush=True)
            self.send_error(HTTPStatus.BAD_GATEWAY)
            return

        status = upstream.status
        length_header = upstream.headers.get("Content-Length")
        response_length = int(length_header) if length_header and length_header.isdigit() else None
        total = content_range_total(upstream.headers.get("Content-Range"))
        if total is None and response_length is not None:
            total = response_length if requested_offset and status == HTTPStatus.OK else requested_offset + response_length
        if requested_offset and status == HTTPStatus.OK:
            # Some small HTTP servers advertise no byte-range support. Seek by
            # discarding their prefix before exposing a standards-compliant 206.
            remaining = requested_offset
            while remaining:
                skipped = upstream.read(min(CHUNK_SIZE, remaining))
                if not skipped:
                    upstream.close()
                    self.send_error(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                    return
                remaining -= len(skipped)
        response_status = HTTPStatus.PARTIAL_CONTENT if requested_offset else HTTPStatus.OK
        self.send_response(response_status)
        self.send_header("Content-Type", upstream.headers.get("Content-Type", "application/octet-stream"))
        self.send_header("Accept-Ranges", "bytes")
        if total is not None:
            self.send_header("Content-Length", str(max(0, total - requested_offset)))
            if requested_offset:
                self.send_header("Content-Range", f"bytes {requested_offset}-{total - 1}/{total}")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if not send_body:
            upstream.close()
            return

        position = requested_offset
        retries = 0
        current = upstream
        while True:
            try:
                chunk = current.read(CHUNK_SIZE)
                if chunk:
                    self.wfile.write(chunk)
                    position += len(chunk)
                    retries = 0
                    continue
                if total is None or position >= total:
                    return
                raise http.client.IncompleteRead(b"", total - position)
            except (BrokenPipeError, ConnectionResetError):
                return
            except (OSError, EOFError, http.client.HTTPException) as exc:
                current.close()
                if retries >= MAX_RETRIES:
                    print(f"dlna-relay exhausted retries at byte {position}: {type(exc).__name__}", flush=True)
                    return
                retries += 1
                delay = min(0.5 * (2 ** (retries - 1)), 5)
                print(f"dlna-relay reconnect {retries}/{MAX_RETRIES} at byte {position} after {type(exc).__name__}", flush=True)
                time.sleep(delay)
                try:
                    current = open_upstream(source, position)
                    if position and current.status == HTTPStatus.OK:
                        # The source ignored Range. Discard up to the resume point,
                        # preserving correctness for small non-range HTTP servers.
                        remaining = position
                        while remaining:
                            skipped = current.read(min(CHUNK_SIZE, remaining))
                            if not skipped:
                                raise EOFError("upstream ended while seeking resume point")
                            remaining -= len(skipped)
                except Exception as retry_error:
                    exc = retry_error
                    continue


class ThreadingTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = True


class MpdProxyHandler(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            upstream = socket.create_connection((MPD_HOST, MPD_PORT), timeout=5)
        except OSError as exc:
            print(f"dlna-relay MPD connect failed: {exc}", flush=True)
            return
        upstream.settimeout(None)
        self.request.settimeout(None)

        def server_to_client():
            try:
                while data := upstream.recv(65536):
                    self.request.sendall(data)
            except OSError:
                pass
            finally:
                try:
                    self.request.shutdown(socket.SHUT_WR)
                except OSError:
                    pass

        thread = threading.Thread(target=server_to_client, daemon=True)
        thread.start()
        pending = b""
        try:
            while data := self.request.recv(65536):
                pending += data
                while b"\n" in pending:
                    line, pending = pending.split(b"\n", 1)
                    upstream.sendall(rewrite_command(line + b"\n"))
            if pending:
                upstream.sendall(rewrite_command(pending))
        except OSError:
            pass
        finally:
            try:
                upstream.shutdown(socket.SHUT_WR)
            except OSError:
                pass
            thread.join(timeout=2)
            upstream.close()


def main():
    httpd = ThreadingHTTPServer((RELAY_HOST, RELAY_HTTP_PORT), RelayHandler)
    mpd_proxy = ThreadingTCPServer((RELAY_HOST, RELAY_MPD_PORT), MpdProxyHandler)
    threading.Thread(target=httpd.serve_forever, name="dlna-http-relay", daemon=True).start()
    print(f"dlna-relay listening on HTTP {RELAY_HTTP_PORT}, MPD proxy {RELAY_MPD_PORT}", flush=True)
    try:
        mpd_proxy.serve_forever()
    finally:
        httpd.shutdown()
        httpd.server_close()
        mpd_proxy.server_close()


if __name__ == "__main__":
    main()
