#!/bin/sh
set -eu

project_dir=/vol1/1000/tools/snapcast
backup_compose="$project_dir/backups/20260910-unified-predeploy/docker-compose.yml"
candidate_compose="$project_dir/docker-compose.unified.yml"
active_compose="$project_dir/docker-compose.yml"

cd "$project_dir"
test -f "$backup_compose"
test -f "$candidate_compose"

docker compose config -q
docker compose down --remove-orphans
cp "$candidate_compose" "$active_compose"

if docker compose up -d --remove-orphans --wait --wait-timeout 150; then
    echo "Unified Snapcast stack is healthy."
    exit 0
fi

echo "Unified stack failed health checks; restoring the four-service stack." >&2
docker compose -f "$candidate_compose" down --remove-orphans || true
cp "$backup_compose" "$active_compose"
docker compose up -d --remove-orphans --wait --wait-timeout 150
exit 1
