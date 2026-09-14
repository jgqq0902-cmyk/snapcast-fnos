#!/bin/sh
set -eu

# upmpdcli initializes its renderer only after it can open MPD.  Supervisord
# starts both processes together, so wait for MPD's TCP listener explicitly.
while ! /usr/bin/python3 -c 'import socket; s=socket.create_connection(("127.0.0.1", 6600), 1); s.close()' 2>/dev/null; do
    sleep 1
done

exec /usr/bin/upmpdcli -c /etc/upmpdcli.conf
