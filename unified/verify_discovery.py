#!/usr/bin/env python3
"""Verify AirPlay mDNS and DLNA SSDP discovery from a LAN host."""

from __future__ import annotations

import re
import socket
import struct
import time
import urllib.request


TARGET_IP = "192.168.2.125"


def lan_interface_ip() -> str:
    """Return the local IPv4 address selected by the route to the gateway."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route:
        route.connect((TARGET_IP, 9))
        return route.getsockname()[0]


def dns_name(name: str) -> bytes:
    return b"".join(bytes([len(label)]) + label.encode() for label in name.split(".")) + b"\0"


def receive_until(sock: socket.socket, deadline: float) -> list[tuple[bytes, tuple[str, int]]]:
    responses = []
    while time.monotonic() < deadline:
        sock.settimeout(max(0.05, deadline - time.monotonic()))
        try:
            responses.append(sock.recvfrom(65535))
        except socket.timeout:
            break
    return responses


def verify_airplay() -> None:
    query = struct.pack("!HHHHHH", 0, 0, 1, 0, 0, 0)
    query += dns_name("_raop._tcp.local") + struct.pack("!HH", 12, 0x8001)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("0.0.0.0", 0))
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(lan_interface_ip()))
        sock.sendto(query, ("224.0.0.251", 5353))
        responses = receive_until(sock, time.monotonic() + 3)
    combined = b"\n".join(data for data, _ in responses)
    assert b"Snapcast-AirPlay" in combined, "AirPlay RAOP service was not found"
    assert socket.inet_aton(TARGET_IP) in combined, "AirPlay service did not resolve to .125"
    print("AirPlay mDNS: Snapcast-AirPlay -> 192.168.2.125")


def verify_dlna() -> None:
    request = (
        "M-SEARCH * HTTP/1.1\r\n"
        "HOST: 239.255.255.250:1900\r\n"
        'MAN: "ssdp:discover"\r\n'
        "MX: 1\r\n"
        "ST: urn:schemas-upnp-org:device:MediaRenderer:1\r\n\r\n"
    ).encode()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("0.0.0.0", 0))
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(lan_interface_ip()))
        sock.sendto(request, ("239.255.255.250", 1900))
        responses = receive_until(sock, time.monotonic() + 3)
    for data, source in responses:
        text = data.decode("utf-8", "replace")
        match = re.search(r"(?im)^location:\s*(\S+)", text)
        if source[0] != TARGET_IP or not match:
            continue
        with urllib.request.urlopen(match.group(1), timeout=3) as response:
            description = response.read().decode("utf-8", "replace")
        if "Snapcast-DLNA" in description:
            print(f"DLNA SSDP: Snapcast-DLNA -> {match.group(1)}")
            return
    raise AssertionError("Snapcast-DLNA MediaRenderer was not found")


if __name__ == "__main__":
    verify_airplay()
    verify_dlna()
