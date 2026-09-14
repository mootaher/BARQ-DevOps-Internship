#!/usr/bin/env bash
set -euo pipefail

DB_SERVICE="postgres"
DB_USER="barq_app"
SOURCE_DB="barq_tasks"

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 <backup.dump>" >&2
    exit 2
fi

backup_file="$1"

if [[ ! -f "$backup_file" ]]; then
    echo "FAIL: backup file not found: $backup_file" >&2
    exit 1
fi

if [[ ! -s "$backup_file" ]]; then
    echo "FAIL: backup file is empty: $backup_file" >&2
    exit 1
fi

echo "BARQ PostgreSQL restore verification"
echo "============================================================"

container_id="$(docker compose ps -q "$DB_SERVICE")"

if [[ -z "$container_id" ]]; then
    echo "FAIL: PostgreSQL container is not running" >&2
    exit 1
fi

if ! docker compose exec -T "$DB_SERVICE" \
    pg_isready -U "$DB_USER" -d "$SOURCE_DB" >/dev/null; then
    echo "FAIL: PostgreSQL is not ready" >&2
    exit 1
fi

echo "PASS: PostgreSQL is ready"

if ! docker compose exec -T "$DB_SERVICE" \
    pg_restore -l < "$backup_file" >/dev/null; then
    echo "FAIL: backup archive is invalid" >&2
    exit 1
fi

echo "PASS: backup archive is readable"

verify_db="barq_restore_verify_$(date -u +%Y%m%d%H%M%S)_$$"

cleanup() {
    docker compose exec -T "$DB_SERVICE" \
        dropdb \
        -U "$DB_USER" \
        --if-exists \
        "$verify_db" >/dev/null 2>&1 || true
}

trap cleanup EXIT INT TERM

if ! docker compose exec -T "$DB_SERVICE" \
    createdb \
    -U "$DB_USER" \
    -T template0 \
    "$verify_db"; then
    echo "FAIL: could not create temporary verification database" >&2
    exit 1
fi

echo "PASS: temporary verification database created"

if ! docker compose exec -T "$DB_SERVICE" \
    pg_restore \
    -U "$DB_USER" \
    -d "$verify_db" \
    --no-owner \
    --no-privileges \
    --exit-on-error \
    < "$backup_file"; then
    echo "FAIL: restore failed" >&2
    exit 1
fi

echo "PASS: backup restored successfully"

table_name="$(
    docker compose exec -T "$DB_SERVICE" \
        psql \
        -U "$DB_USER" \
        -d "$verify_db" \
        -Atqc "SELECT to_regclass('public.records');"
)"

if [[ "$table_name" != "records" ]]; then
    echo "FAIL: restored records table is missing" >&2
    exit 1
fi

echo "PASS: restored records table exists"

row_count="$(
    docker compose exec -T "$DB_SERVICE" \
        psql \
        -U "$DB_USER" \
        -d "$verify_db" \
        -Atqc "SELECT count(*) FROM records;"
)"

if ! [[ "$row_count" =~ ^[0-9]+$ ]]; then
    echo "FAIL: could not verify restored row count" >&2
    exit 1
fi

if (( row_count < 1 )); then
    echo "FAIL: restored records table contains no rows" >&2
    exit 1
fi

echo "PASS: restored records contain $row_count row(s)"

echo
echo "Restored record sample:"
docker compose exec -T "$DB_SERVICE" \
    psql \
    -U "$DB_USER" \
    -d "$verify_db" \
    -c "SELECT id, title FROM records ORDER BY id LIMIT 10;"

echo
echo "PASS: PostgreSQL backup restore verified"
echo "INFO: live database '$SOURCE_DB' was not overwritten"
echo "INFO: temporary verification database will now be removed"
