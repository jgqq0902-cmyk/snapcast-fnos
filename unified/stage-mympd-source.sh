#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
project=${PROJECT_DIR:-$(dirname "$script_dir")}
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

echo "Source backup: $backup"
grep '^GATEWAY_IP=' "$project/.env"
