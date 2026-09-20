#!/bin/sh
set -eu

# This is intentionally a fixed, argument-free helper. Prefer Shairport Sync's
# native D-Bus API; if the image does not expose it, Supervisor will restart the
# receiver after the current process is terminated.
if command -v dbus-send >/dev/null 2>&1 && [ -n "${DBUS_SESSION_BUS_ADDRESS:-}" ]; then
    if dbus-send --session --type=method_call --dest=org.gnome.ShairportSync \
        /org/gnome/ShairportSync org.gnome.ShairportSync.DropSession >/dev/null 2>&1; then
        echo dbus
        exit 0
    fi
fi

pid="$(pgrep -x shairport-sync 2>/dev/null | sed -n '1p' || true)"
if [ -z "$pid" ]; then
    echo no-session
    exit 0
fi

kill -TERM "$pid"
echo supervisor-restart
