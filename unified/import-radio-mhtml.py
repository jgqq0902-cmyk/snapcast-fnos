#!/usr/bin/env python3
"""Extract and normalize the first M3U playlist embedded in a saved forum MHTML."""

from __future__ import annotations

import argparse
from email import policy
from email.parser import BytesParser
from html import unescape
from pathlib import Path
import re
from urllib.parse import urlsplit, urlunsplit


def html_text(source: Path) -> str:
    message = BytesParser(policy=policy.default).parsebytes(source.read_bytes())
    part = next((item for item in message.walk() if item.get_content_type() == "text/html"), None)
    if part is None:
        raise ValueError("MHTML 中没有 HTML 正文")
    payload = part.get_payload(decode=True)
    if payload is None:
        raise ValueError("无法解码 MHTML 正文")
    charset = part.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="replace")


def normalize_url(value: str) -> str:
    value = value.strip()
    # The source post contains one duplicated protocol/host typo.
    value = value.replace("https://lhttp://qingting.fm/", "https://lhttp.qingting.fm/")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"无效电台地址：{value}")
    return urlunsplit(parsed)


def extract(source: Path) -> list[tuple[str, str]]:
    body = html_text(source)
    marker = body.find("#EXTM3U")
    if marker < 0:
        raise ValueError("网页中未找到 #EXTM3U")
    fragment = body[marker:]
    fragment = re.sub(r"(?i)<br\s*/?>|</li>|</p>|</div>", "\n", fragment)
    fragment = unescape(re.sub(r"<[^>]+>", "", fragment))
    lines = [line.strip() for line in fragment.splitlines() if line.strip()]

    stations: list[tuple[str, str]] = []
    seen: set[str] = set()
    for index, line in enumerate(lines):
        if not line.startswith("#EXTINF:") or "," not in line:
            continue
        name = line.split(",", 1)[1].strip()
        url = next((candidate for candidate in lines[index + 1:index + 5]
                    if candidate.startswith(("http://", "https://"))), "")
        if not name or not url:
            continue
        url = normalize_url(url)
        if url not in seen:
            seen.add(url)
            stations.append((name, url))
    if not stations:
        raise ValueError("网页中没有可导入的电台")
    return stations


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    stations = extract(args.source)
    content = "#EXTM3U\n" + "".join(f"#EXTINF:-1,{name}\n{url}\n" for name, url in stations)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(content, encoding="utf-8", newline="\n")
    print(f"已导入 {len(stations)} 个不重复电台：{args.output}")


if __name__ == "__main__":
    main()
