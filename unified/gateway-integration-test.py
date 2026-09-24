#!/usr/bin/env python3
"""Exercise the authenticated allowlisted player gateway."""
import http.cookiejar
import json
import os
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
    request("/api/player/rpc", {"jsonrpc": "2.0", "id": 1, "method": "MYMPD_API_PLAYER_STATE", "params": {}})
    raise AssertionError("unauthenticated player RPC unexpectedly succeeded")
except urllib.error.HTTPError as exc:
    assert exc.code in {401, 403}, exc.code

login = request("/api/login", {"username": username, "password": password}, True)
assert login.status == 200
rpc = request("/api/player/rpc", {"jsonrpc": "2.0", "id": 1, "method": "MYMPD_API_PLAYER_STATE", "params": {}}, True)
assert rpc.status == 200 and "result" in json.load(rpc)
try:
    request("/api/player/rpc", {"jsonrpc": "2.0", "id": 2, "method": "MYMPD_API_SCRIPT_EXECUTE", "params": {}}, True)
    raise AssertionError("non-allowlisted player RPC unexpectedly succeeded")
except urllib.error.HTTPError as exc:
    assert exc.code == 400, exc.code

events = request("/api/player/events", authenticated=True)
assert events.status == 200 and events.headers.get_content_type() == "text/event-stream"
assert events.readline().startswith(b"event: update")
events.close()

request("/api/logout", {}, True)
try:
    request("/api/player/rpc", {"jsonrpc": "2.0", "id": 3, "method": "MYMPD_API_PLAYER_STATE", "params": {}}, True)
    raise AssertionError("logged-out cookie still accesses player RPC")
except urllib.error.HTTPError as exc:
    assert exc.code in {401, 403}, exc.code

print("PASS: unauthenticated denial, login, allowlisted RPC, rejected RPC, SSE and logout")
