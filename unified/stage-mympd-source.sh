#!/bin/sh
set -eu

project=/vol1/1000/tools/snapcast
archive=${1:-/tmp/snapcast-mympd-integration.tar.gz}

[ "$(realpath "$project")" = "$project" ]
[ -f "$archive" ]
[ -f "$project/.env" ]

stage=$(mktemp -d /tmp/snapcast-mympd.XXXXXX)
trap 'rm -rf "$stage"' EXIT HUP INT TERM
tar -xzf "$archive" -C "$stage"

timestamp=$(date +%Y%m%d-%H%M%S)
backup="$project/backups/$timestamp-pre-mympd-source"
mkdir -p "$backup"
mv "$project/control" "$backup/control"
mv "$project/unified" "$backup/unified"
cp -a "$stage/control" "$project/control"
cp -a "$stage/unified" "$project/unified"
cp "$stage/README.md" "$stage/.env.example" "$stage/docker-compose.yml" \
   "$stage/snapserver.conf" "$project/"

sed -i 's/^GATEWAY_IP=.*/GATEWAY_IP=192.168.2.126/' "$project/.env"

# Remove the retired test definition, but intentionally keep its persistent data.
rm -f /vol1/1000/tools/music-assistant/docker-compose.yml \
      /vol1/1000/tools/music-assistant/.env.example \
      /vol1/1000/tools/music-assistant/README.md

echo "Source backup: $backup"
grep '^GATEWAY_IP=' "$project/.env"
[ ! -d /vol1/1000/tools/music-assistant/data ] || echo "Music Assistant data preserved"
