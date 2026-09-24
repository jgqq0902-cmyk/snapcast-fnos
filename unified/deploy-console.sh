#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
project_dir=${PROJECT_DIR:-$(dirname "$script_dir")}
timestamp=$(date +%Y%m%d-%H%M%S)
backup_dir="$project_dir/backups/$timestamp-audit-remediation"
image_name=$(sed -n 's/^SNAPCAST_IMAGE=//p' "$project_dir/.env" 2>/dev/null | tail -n 1)
container_name=$(sed -n 's/^CONTAINER_NAME=//p' "$project_dir/.env" 2>/dev/null | tail -n 1)
image_name=${image_name:-snapcast-all-in-one:local}
container_name=${container_name:-snapcast}
backup_image="${image_name%:*}:backup-$timestamp"
state_archive="$backup_dir/persistent-config.tar"
container_state_archive="/tmp/snaproom-persistent-config-$timestamp.tar"

cd "$project_dir"
[ -f .env ] || { echo "Missing .env; copy .env.example and configure it first." >&2; exit 1; }
password=$(sed -n 's/^CONTROL_PASSWORD=//p' .env | tail -n 1)
auth_enabled=$(sed -n 's/^CONTROL_AUTH_ENABLED=//p' .env | tail -n 1)
case "$auth_enabled" in
    false|False|FALSE|0|no|off) ;;
    *)
        [ -n "$password" ] || { echo "CONTROL_PASSWORD must not be empty when authentication is enabled." >&2; exit 1; }
        [ "$password" != "replace-with-a-long-random-password" ] || { echo "Replace the example CONTROL_PASSWORD before deployment." >&2; exit 1; }
        ;;
esac

mkdir -p "$backup_dir"
cp docker-compose.yml snapserver.conf "$backup_dir/"
[ ! -f config/snapserver.conf ] || cp config/snapserver.conf "$backup_dir/snapserver.runtime.conf"
docker cp "$container_name:/app/control" "$backup_dir/control-running" 2>/dev/null || true
docker exec "$container_name" sh -eu -c '
    rm -rf /tmp/snaproom-upgrade-state
    mkdir -p /tmp/snaproom-upgrade-state/data/mympd/work /tmp/snaproom-upgrade-state/data/dlna
    for path in data/mympd/work/config data/mympd/work/state data/dlna/playlists data/.snaproom-schema-version; do
        [ ! -e "/app/$path" ] || cp -a "/app/$path" "/tmp/snaproom-upgrade-state/$(dirname "$path")/"
    done
    tar -C /tmp/snaproom-upgrade-state -cpf "$1" .
' _ "$container_state_archive"
docker cp "$container_name:$container_state_archive" "$state_archive"

old_image=$(docker inspect --format '{{.Image}}' "$container_name")
docker image tag "$old_image" "$backup_image"

docker compose config -q
docker compose build
mkdir -p config
cp snapserver.conf config/snapserver.conf

if docker compose up -d --remove-orphans --wait --wait-timeout 180 \
    && docker exec "$container_name" /app/unified/smoke-test.sh; then
    echo "Deployment is healthy. Backup: $backup_dir; image: $backup_image"
    exit 0
fi

echo "Deployment failed; restoring the previous runtime config and image." >&2
if [ -f "$backup_dir/snapserver.runtime.conf" ]; then
    cp "$backup_dir/snapserver.runtime.conf" config/snapserver.conf
fi
docker image tag "$backup_image" "$image_name"
docker compose up -d --remove-orphans --wait --wait-timeout 180
docker cp "$state_archive" "$container_name:$container_state_archive"
docker exec "$container_name" sh -eu -c '
    rm -rf /app/data/mympd/work/config /app/data/mympd/work/state /app/data/dlna/playlists
    rm -f /app/data/.snaproom-schema-version
    tar -C /app -xpf "$1"
    chown -R snapcast:snapcast /app/data/mympd/work /app/data/dlna/playlists /app/data/.snaproom-schema-version 2>/dev/null || true
' _ "$container_state_archive"
docker restart "$container_name" >/dev/null
docker compose up -d --wait --wait-timeout 180
exit 1
