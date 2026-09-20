#!/usr/bin/env python3
"""Verify UPnP SetNextAVTransportURI reaches MPD without losing the queue."""
from __future__ import annotations

import html
import json
import os
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from urllib.parse import urljoin


OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())


def open_url(request: str | urllib.request.Request):
    return OPENER.open(request, timeout=5)


def get_json(url: str) -> dict:
    with open_url(url) as response:
        return json.load(response)


def post_json(url: str, payload: dict) -> dict:
    request = urllib.request.Request(
        url, json.dumps(payload).encode(), {"Content-Type": "application/json"}
    )
    with open_url(request) as response:
        return json.load(response)


def authenticate(api: str) -> None:
    try:
        auth = get_json(f"{api}/api/auth")
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"control API auth probe failed: HTTP {error.code}") from error
    if not auth.get("enabled") or auth.get("authenticated"):
        return
    username = os.environ.get("CONTROL_USERNAME", "admin")
    password = os.environ.get("CONTROL_PASSWORD", "")
    if not auth.get("configured"):
        raise RuntimeError("control API authentication is enabled but CONTROL_PASSWORD is not configured")
    if not password:
        raise RuntimeError("set CONTROL_PASSWORD in the environment for this authenticated regression test")
    post_json(f"{api}/api/login", {"username": username, "password": password})


def control_url(description_url: str) -> str:
    with open_url(description_url) as response:
        root = ET.parse(response).getroot()
    namespace = {"d": "urn:schemas-upnp-org:device-1-0"}
    for service in root.findall(".//d:service", namespace):
        kind = service.findtext("d:serviceType", "", namespace)
        if kind == "urn:schemas-upnp-org:service:AVTransport:1":
            return urljoin(description_url, service.findtext("d:controlURL", "", namespace))
    raise RuntimeError("AVTransport control URL not found")


def soap(url: str, action: str, uri: str) -> None:
    body = (
        '<?xml version="1.0"?>'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
        f'<u:{action} xmlns:u="urn:schemas-upnp-org:service:AVTransport:1">'
        f"<InstanceID>0</InstanceID><CurrentURI>{html.escape(uri)}</CurrentURI>"
        f"<CurrentURIMetaData></CurrentURIMetaData></u:{action}>"
        "</s:Body></s:Envelope>"
    )
    if action == "SetNextAVTransportURI":
        body = body.replace("CurrentURI", "NextURI").replace("CurrentURIMetaData", "NextURIMetaData")
    request = urllib.request.Request(
        url,
        body.encode(),
        {
            "Content-Type": 'text/xml; charset="utf-8"',
            "SOAPAction": f'"urn:schemas-upnp-org:service:AVTransport:1#{action}"',
        },
    )
    with open_url(request) as response:
        response.read()


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: verify_upnp_next.py DESCRIPTION_URL CONTROL_BASE_URL")
    description_url, api = sys.argv[1], sys.argv[2].rstrip("/")
    authenticate(api)
    before = get_json(f"{api}/api/player/bootstrap?limit=1")
    if before["player"]["state"] != "stop":
        raise SystemExit("refusing to modify a playing queue")
    original = [song["file"] for song in before["queue"]]
    current = f"{api}/upnp-regression-current.mp3"
    following = f"{api}/upnp-regression-next.mp3"
    try:
        endpoint = control_url(description_url)
        soap(endpoint, "SetAVTransportURI", current)
        soap(endpoint, "SetNextAVTransportURI", following)
        queue = get_json(f"{api}/api/player/collections")["queue"]
        assert len(queue) == 2, f"expected 2 MPD items, got {len(queue)}"
        assert queue[1]["file"] == following, "next URI did not reach MPD"
        print("PASS: SetNextAVTransportURI created a two-item MPD queue")
    finally:
        post_json(f"{api}/api/player/action", {"action": "clear"})
        for uri in original:
            post_json(f"{api}/api/player/action", {"action": "add", "uri": uri})


if __name__ == "__main__":
    main()
