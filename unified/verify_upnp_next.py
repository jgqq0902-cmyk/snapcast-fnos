#!/usr/bin/env python3
"""Verify UPnP SetNextAVTransportURI reaches MPD without losing the queue."""
from __future__ import annotations

import html
import json
import sys
import urllib.request
import xml.etree.ElementTree as ET
from urllib.parse import urljoin


def get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=5) as response:
        return json.load(response)


def post_json(url: str, payload: dict) -> dict:
    request = urllib.request.Request(
        url, json.dumps(payload).encode(), {"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.load(response)


def control_url(description_url: str) -> str:
    with urllib.request.urlopen(description_url, timeout=5) as response:
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
    with urllib.request.urlopen(request, timeout=5) as response:
        response.read()


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: verify_upnp_next.py DESCRIPTION_URL CONTROL_BASE_URL")
    description_url, api = sys.argv[1], sys.argv[2].rstrip("/")
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
