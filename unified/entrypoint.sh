#!/bin/sh
set -eu

umask 0002

dbus-uuidgen --ensure 2>/dev/null || true
mkdir -p /app/data/dlna/music /app/data/dlna/playlists /app/data/dlna/cache
touch /app/data/dlna/state /app/data/dlna/database
if [ ! -e /app/data/dlna/library ] && [ ! -L /app/data/dlna/library ]; then
    ln -s /media/music /app/data/dlna/library
fi
rm -f /app/data/dlna/mpd.sock \
      /app/data/dlna/mpd.pid \
      /app/data/dlna/upmpdcli.pid \
      /app/data/unified-supervisord.pid

exec /usr/bin/supervisord -c /app/unified/supervisord.conf
