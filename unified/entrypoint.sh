#!/bin/sh
set -eu

umask 0002

puid=${PUID:-1000}
pgid=${PGID:-1001}
case "$puid:$pgid" in
    *[!0-9:]*|:*|*:) echo "PUID and PGID must be numeric" >&2; exit 1 ;;
esac
sed -i -E "s#^(snapcast:x:)[0-9]+:[0-9]+:#\\1${puid}:${pgid}:#" /etc/passwd
sed -i -E "s#^(snapcast:x:)[0-9]+:#\\1${pgid}:#" /etc/group

dbus-uuidgen --ensure 2>/dev/null || true
mkdir -p /app/data/dlna/music /app/data/dlna/playlists /app/data/dlna/cache \
         /app/data/mympd/work /app/data/mympd/cache
if [ ! -e /app/data/dlna/library ] && [ ! -L /app/data/dlna/library ]; then
    ln -s /media/music /app/data/dlna/library
fi
rm -f /app/data/dlna/mpd.sock \
      /app/data/dlna/mpd.pid \
      /app/data/dlna/upmpdcli.pid \
      /app/data/unified-supervisord.pid
chown -R snapcast:snapcast /app/data

exec /usr/bin/supervisord -c /app/unified/supervisord.conf
