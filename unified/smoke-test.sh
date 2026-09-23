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

for process in snapserver dbus-daemon avahi-daemon shairport-sync mpd mympd upmpdcli nginx; do
    assert_process_user "$process"
done
pgrep -f '/app/unified/dlna_relay.py' >/dev/null || fail "dlna-relay is not running"
assert_matching_process_user control '/app/control/app.py'

# /proc/net/tcp stores IPv4 addresses as little-endian hex.
assert_listener 1704 00000000
assert_listener 1705 0100007F
assert_listener 1780 0100007F
web_port=${WEB_PORT:-1781}
control_port=${CONTROL_INTERNAL_PORT:-1783}
mympd_port=${MYMPD_INTERNAL_PORT:-1782}
assert_listener "$web_port" 00000000
assert_listener "$control_port" 0100007F
assert_listener "$mympd_port" 0100007F
assert_listener 1790 0100007F
assert_listener 6601 0100007F

wget -qO- "http://127.0.0.1:$web_port/api/health" >/dev/null || fail "public health check failed"
wget -qO- "http://127.0.0.1:$mympd_port/" >/dev/null || fail "internal myMPD web check failed"
printf 'ping\nclose\n' | nc -w 2 127.0.0.1 6600 | grep -q '^OK' || fail "MPD command socket failed"
/app/unified/gateway-integration-test.py || fail "authenticated myMPD gateway integration failed"

echo "PASS: processes, privileges, loopback boundaries, authenticated myMPD gateway and MPD are healthy"
