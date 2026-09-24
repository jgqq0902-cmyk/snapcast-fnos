#!/usr/bin/env python3
"""Read-only myMPD adapter contract check for deployed containers."""

import json
import sys
import urllib.request


API = "http://127.0.0.1:1782/api/default"
CASES = (
    ("MYMPD_API_PLAYER_STATE", {}),
    ("MYMPD_API_PLAYER_CURRENT_SONG", {}),
    ("MYMPD_API_DATABASE_ALBUM_LIST", {"offset": 0, "limit": 3, "expression": "", "sort": "Album", "sortdesc": False, "fields": ["Album", "AlbumArtist"]}),
    ("MYMPD_API_QUEUE_SEARCH", {"offset": 0, "limit": 3, "expression": "", "sort": "Priority", "sortdesc": False, "fields": ["Title", "Artist"]}),
    ("MYMPD_API_PLAYLIST_LIST", {"offset": 0, "limit": 3, "searchstr": "", "type": 0, "sort": "Name", "sortdesc": False, "fields": ["Name"]}),
    ("MYMPD_API_WEBRADIO_FAVORITE_SEARCH", {"offset": 0, "limit": 3, "expression": "", "sort": "Name", "sortdesc": False}),
)


def call(method, params):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    request = urllib.request.Request(API, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.load(response)


def main():
    failed = False
    for method, params in CASES:
        payload = call(method, params)
        if payload.get("error"):
            failed = True
            print(f"FAIL {method}: {payload['error']}")
        else:
            result = payload.get("result", {})
            count = len(result.get("data", [])) if isinstance(result, dict) else 0
            first = result.get("data", [{}])[0] if count else {}
            fields = sorted(first) if first else sorted(result) if isinstance(result, dict) else []
            print(f"PASS {method}: data={count}, fields={','.join(fields)}")
    return int(failed)


if __name__ == "__main__":
    sys.exit(main())
