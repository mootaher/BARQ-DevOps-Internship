#!/usr/bin/env bash
set -euo pipefail

DB_SERVICE="postgres"
DB_USER="barq_app"
DB_NAME="barq_tasks"
BACKUP_DIR="backups"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_file="${BACKUP_DIR}/${DB_NAME}-${timestamp}.dump"
tmp_file="${backup_file}.tmp"

mkdir -p "$BACKUP_DIR"

echo "BARQ PostgreSQL backup"
echo "============================================================"

container_id="$(docker compose ps -q "$DB_SERVICE")"

if [[ -z "$container_id" ]]; then
    echo "FAIL: PostgreSQL container is not running" >&2
    exit 1
fi

if ! docker compose exec -T "$DB_SERVICE" \
    pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null; then
    echo "FAIL: PostgreSQL is not ready" >&2
    exit 1
fi

echo "PASS: PostgreSQL is ready"

rm -f "$tmp_file"

if ! docker compose exec -T "$DB_SERVICE" \
    pg_dump \
    -U "$DB_USER" \
    -d "$DB_NAME" \
    -Fc > "$tmp_file"; then
    rm -f "$tmp_file"
    echo "FAIL: pg_dump failed" >&2
    exit 1
fi

if [[ ! -s "$tmp_file" ]]; then
    rm -f "$tmp_file"
    echo "FAIL: backup file is empty" >&2
    exit 1
fi

if ! docker compose exec -T "$DB_SERVICE" \
    pg_restore -l < "$tmp_file" >/dev/null; then
    rm -f "$tmp_file"
    echo "FAIL: generated backup archive is invalid" >&2
    exit 1
fi

mv "$tmp_file" "$backup_file"

echo "PASS: PostgreSQL backup created"
echo "PASS: backup archive validated"
echo "Backup: $backup_file"
echo "Bytes: $(wc -c < "$backup_file")"
