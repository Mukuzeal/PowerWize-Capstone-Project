#!/usr/bin/env bash
# Explicitly replace an existing Linux database; back it up before any writes.
set -euo pipefail
if [[ "${1:-}" != --replace ]]; then
    echo "Stop PowerWize, then run: bash scripts/restore-linux-db.sh --replace"
    echo "This replaces the Linux powerwize public schema with powerwize_dump.sql."
    exit 1
fi
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/linux-common.sh"
linux_prepare
backup="$root/backups/linux-before-restore-$(date +%Y%m%d-%H%M%S)-$$.sql"
mkdir -p "$root/backups"
docker compose exec -T postgres pg_dump -U postgres -d powerwize --no-owner --no-privileges > "$backup"
[[ -s "$backup" ]] || { echo "Backup is empty; refusing restore." >&2; exit 1; }
# One transaction: any SQL failure rolls the replacement back.
{
    printf 'DROP SCHEMA public CASCADE;\nCREATE SCHEMA public;\n'
    cat "$root/powerwize_dump.sql"
} | docker compose exec -T postgres psql -X -U postgres -d powerwize -v ON_ERROR_STOP=1 --single-transaction --quiet
echo "Restored. Previous Linux data: $backup"
