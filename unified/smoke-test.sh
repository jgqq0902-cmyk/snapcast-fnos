#!/bin/sh
set -eu

fail() {
    echo "FAIL: $*" >&2
    exit 1
}

assert_process_user() {
    process=$1
    pids=$(pgrep -x "$process" || true)
    [ -n "$pids" ] || fail "$process is not running"
    for pid in $pids; do
        user=$(awk '/^Uid:/ { print $2 }' "/proc/$pid/status")
        [ "$user" = "$(id -u snapcast)" ] || fail "$process pid $pid runs as uid $user"
    done
}

assert_listener() {
    port=$1
    expected=$2
    hex_port=$(printf '%04X' "$port")
    awk -v port=":$hex_port" -v address="$expected" '
        NR > 1 && $2 ~ port "$" && $4 == "0A" { split($2, local, ":"); if (local[1] == address) found=1 }
        END { exit found ? 0 : 1 }
    ' /proc/net/tcp /proc/net/tcp6 || fail "TCP $port is not listening on $expected"
}

assert_matching_process_user() {
    label=$1
    pattern=$2
    pids=$(pgrep -f "$pattern" || true)
    [ -n "$pids" ] || fail "$label is not running"
    for pid in $pids; do
        user=$(awk '/^Uid:/ { print $2 }' "/proc/$pid/status")
        [ "$user" = "$(id -u snapcast)" ] || fail "$label pid $pid runs as uid $user"
    done
}

for process in snapserver dbus-daemon avahi-daemon shairport-sync mpd mympd upmpdcli; do
    assert_process_user "$process"
done
assert_matching_process_user control '/app/control/app.py'

# /proc/net/tcp stores IPv4 addresses as little-endian hex.
assert_listener 1704 00000000
assert_listener 1705 0100007F
assert_listener 1780 0100007F
assert_listener 1781 00000000
assert_listener 1782 00000000

wget -qO- http://127.0.0.1:1781/api/health >/dev/null || fail "control API health check failed"
wget -qO- http://127.0.0.1:1782/ >/dev/null || fail "myMPD web check failed"
printf 'ping\nclose\n' | nc -w 2 127.0.0.1 6600 | grep -q '^OK' || fail "MPD command socket failed"

echo "PASS: processes, privileges, listeners, control API and MPD are healthy"
