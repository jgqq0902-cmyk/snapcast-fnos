#!/usr/bin/env python3
"""Idempotently import the bundled M3U as native myMPD webradio favorites."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def read_m3u(path: Path) -> list[tuple[str, str]]:
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines or lines[0] != "#EXTM3U":
        raise ValueError("电台文件不是扩展 M3U")
    stations: list[tuple[str, str]] = []
    for index in range(1, len(lines), 2):
        if index + 1 >= len(lines) or not lines[index].startswith("#EXTINF:"):
            raise ValueError(f"电台文件第 {index + 1} 行结构错误")
        name = lines[index].split(",", 1)[1].strip()
        uri = lines[index + 1]
        if not name or not uri.startswith(("http://", "https://")):
            raise ValueError(f"电台文件第 {index + 1} 行内容错误")
        stations.append((name, uri))
    return stations


class MyMpdApi:
    def __init__(self, endpoint: str, timeout: float = 10) -> None:
        self.endpoint = endpoint
        self.timeout = timeout
        self.request_id = 0

    def call(self, method: str, params: dict) -> dict:
        self.request_id += 1
        # myMPD deliberately rejects JSON unicode/hex escapes. Send literal
        # UTF-8 so Chinese station names pass its strict request parser.
        payload = json.dumps({
            "jsonrpc": "2.0", "id": self.request_id, "method": method, "params": params
        }, ensure_ascii=False).encode("utf-8")
        request = Request(self.endpoint, data=payload, headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=self.timeout) as response:
            result = json.load(response)
        if "error" in result:
            raise RuntimeError(f"myMPD {method} 失败：{result['error']}")
        return result.get("result", {})


def wait_for_api(api: MyMpdApi, seconds: int) -> None:
    deadline = time.monotonic() + seconds
    while True:
        try:
            api.call("MYMPD_API_WEBRADIO_FAVORITE_SEARCH", {
                "offset": 0, "limit": 1, "expression": "", "sort": "Name", "sortdesc": False
            })
            return
        except (HTTPError, URLError, ConnectionError, TimeoutError, RuntimeError):
            if time.monotonic() >= deadline:
                raise TimeoutError("等待 myMPD API 超时")
            time.sleep(1)


def list_favorites(api: MyMpdApi) -> dict[str, str]:
    result = api.call("MYMPD_API_WEBRADIO_FAVORITE_SEARCH", {
        "offset": 0, "limit": 1000, "expression": "", "sort": "Name", "sortdesc": False
    })
    return {item.get("Name", ""): item.get("StreamUri", "") for item in result.get("data", [])}


def save_favorite(api: MyMpdApi, name: str, uri: str) -> None:
    api.call("MYMPD_API_WEBRADIO_FAVORITE_SAVE", {
        "name": name,
        "oldName": name,
        "streamUri": uri,
        "genres": ["网络电台"],
        "image": "",
        "homepage": "",
        "country": "",
        "region": "",
        "languages": ["中文"],
        "codec": "",
        "bitrate": 0,
        "description": "由 Snapcast FNOS 内置电台表导入",
    })


def sync(api: MyMpdApi, stations: list[tuple[str, str]]) -> tuple[int, int]:
    existing = list_favorites(api)
    changed = 0
    for name, uri in stations:
        if existing.get(name) == uri:
            continue
        save_favorite(api, name, uri)
        existing[name] = uri
        changed += 1
    return changed, len(stations) - changed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path("/app/unified/radio-stations.m3u"))
    parser.add_argument("--endpoint", default="http://127.0.0.1:1782/api/default")
    parser.add_argument("--wait", type=int, default=60)
    args = parser.parse_args()
    api = MyMpdApi(args.endpoint)
    wait_for_api(api, args.wait)
    changed, unchanged = sync(api, read_m3u(args.source))
    print(f"myMPD native radio favorites: changed={changed} unchanged={unchanged}", flush=True)


if __name__ == "__main__":
    main()
