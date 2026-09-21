#!/usr/bin/env python3
"""Exercise the production nginx auth_request, myMPD HTTP and WebSocket path."""
import base64
import gzip
import http.cookiejar
import json
import os
import re
import socket
import ssl
import sys
import urllib.error
import urllib.request

port = int(os.environ.get("WEB_PORT", "1781"))
tls = os.environ.get("WEB_TLS_ENABLED", "false").lower() in {"1", "true", "yes", "on"}
scheme = "https" if tls else "http"
base = f"{scheme}://127.0.0.1:{port}"
username = os.environ.get("CONTROL_USERNAME", "admin")
password = os.environ.get("CONTROL_PASSWORD", "")
if os.environ.get("CONTROL_AUTH_ENABLED", "true").lower() in {"0", "false", "no", "off"}:
    print("SKIP: gateway session integration requires authentication")
    raise SystemExit(0)
if not password:
    raise SystemExit("CONTROL_PASSWORD is required for gateway integration test")

context = ssl._create_unverified_context() if tls else None
jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar), urllib.request.HTTPSHandler(context=context))

def request(path, payload=None, authenticated=False):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(base + path, data=data, headers={"Content-Type": "application/json"} if data else {})
    return opener.open(req, timeout=5) if authenticated else urllib.request.urlopen(req, timeout=5, context=context)

try:
    request("/player/")
    raise AssertionError("unauthenticated /player/ unexpectedly succeeded")
except urllib.error.HTTPError as exc:
    assert exc.code in {401, 403}, exc.code

login = request("/api/login", {"username": username, "password": password}, True)
assert login.status == 200
player = request("/player/", authenticated=True)
raw_html = player.read()
if raw_html.startswith(b"\x1f\x8b"):
    raw_html = gzip.decompress(raw_html)
html = raw_html.decode("utf-8", "replace")
assert player.status == 200 and len(html) > 256 and "<html" in html.casefold()

asset = next((value for value in re.findall(r'(?:src|href)=["\']([^"\']+)', html) if value and not value.startswith(("data:", "http", "#"))), "")
if asset:
    asset_path = asset if asset.startswith("/player/") else "/player/" + asset.lstrip("/")
    assert request(asset_path, authenticated=True).status == 200

cookie = "; ".join(f"{item.name}={item.value}" for item in jar)
key = base64.b64encode(os.urandom(16)).decode()
raw = socket.create_connection(("127.0.0.1", port), timeout=5)
if tls:
    raw = ssl._create_unverified_context().wrap_socket(raw, server_hostname="localhost")
upgrade = (
    f"GET /player/ws/default HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
    f"Cookie: {cookie}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
    f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
)
raw.sendall(upgrade.encode())
response = raw.recv(2048).decode("latin1", "replace")
raw.close()
assert response.startswith("HTTP/1.1 101"), response.splitlines()[0] if response else "empty response"

request("/api/logout", {}, True)
try:
    request("/player/", authenticated=True)
    raise AssertionError("logged-out cookie still accesses /player/")
except urllib.error.HTTPError as exc:
    assert exc.code in {401, 403}, exc.code

print("PASS: unauthenticated denial, login, myMPD asset, WebSocket and logout")
