#!/bin/sh
set -eu

while ! /usr/bin/python3 -c 'import socket; s=socket.create_connection(("127.0.0.1", 6600), 1); s.close()' 2>/dev/null; do
    sleep 1
done

exec /usr/bin/upmpdcli -c /app/unified/upmpdcli.conf
