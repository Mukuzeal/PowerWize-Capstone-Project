#!/usr/bin/env bash
# Sourced by Linux launchers; paths may contain spaces (shared NTFS drive).
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
export TZ="${TZ:-Asia/Manila}"

linux_prepare() {
    [[ -f "$root/.env" ]] || { echo "Missing .env. Run bash setup-linux.sh first." >&2; return 1; }
    if [[ ! -x "$root/.venv/bin/python" ]]; then
        echo "Create the Linux environment first: bash setup-linux.sh" >&2
        return 1
    fi
    command -v docker >/dev/null || { echo "Install Docker and Compose first (LINUX_SETUP.md)." >&2; return 1; }
    if command docker info >/dev/null 2>&1; then
        docker() { command docker "$@"; }
    elif command -v sg >/dev/null && sg docker -c 'docker info' >/dev/null 2>&1; then
        docker() { sg docker -c "docker $(printf '%q ' "$@")"; }
    else
        echo "Docker is unavailable. Start its service and enable access for your user." >&2
        return 1
    fi
    [[ -s "$root/powerwize_dump.sql" ]] || { echo "Missing powerwize_dump.sql; run scripts/export_linux_db.py on Windows." >&2; return 1; }
    docker compose up -d postgres
    for ((attempt=0; attempt<60; attempt++)); do
        # TCP remains unavailable while the entrypoint's temporary server restores SQL.
        if docker compose exec -T postgres pg_isready -q -h 127.0.0.1 -U postgres -d powerwize; then
            return 0
        fi
        sleep 1
    done
    echo "PostgreSQL did not become ready. Inspect: docker compose logs postgres" >&2
    return 1
}
