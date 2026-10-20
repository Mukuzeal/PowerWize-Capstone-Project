#!/usr/bin/env bash
# PowerWize local dev launcher (Linux) — the counterpart to run.ps1.
# Starts the Postgres container (if down), clears stale app.py processes, runs the app.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$root"

# docker group membership does not apply to an already-open shell, so route
# every docker call through `sg docker` when the current shell lacks it.
if id -nG | tr ' ' '\n' | grep -qx docker && docker info >/dev/null 2>&1; then
    docker() { command docker "$@"; }
else
    docker() { sg docker -c "docker $(printf '%q ' "$@")"; }
fi

# 1. PostgreSQL --------------------------------------------------------------
if [ "$(docker inspect -f '{{.State.Running}}' powerwize-postgres 2>/dev/null || echo false)" = true ]; then
    echo "[pg] already running"
else
    echo "[pg] starting..."
    docker compose up -d
fi

# The container reports ready a moment before it accepts connections; init_db()
# runs at import time, so a race here fails the app's very first query.
for _ in $(seq 1 30); do
    docker exec powerwize-postgres pg_isready -q -U postgres >/dev/null 2>&1 && break
    sleep 1
done

# 2. Kill stale app.py processes ---------------------------------------------
# app.py runs with its cwd already changed to src/, so argv is "python app.py"
# -- not "python src/app.py" -- match the venv path instead of the src/ prefix.
pkill -f "[P]owerWize/\.venv/bin/python app\.py" 2>/dev/null && echo "[app] killed stale process" || true

# 3. Environment overrides ----------------------------------------------------
# .env is shared with the Windows boot and is loaded with load_dotenv() (no
# override=True), so real environment variables win. Anything that differs per
# OS is set here instead of forking .env.
#
# LM Studio exposes this model as "qwen3-vl-4b-instruct" on Linux, while .env
# carries the Windows-side key "qwen/qwen3-vl-4b" — that name 400s here with
# "No models loaded". Check `lms ps` if AI calls start failing.
export LM_STUDIO_MODEL="${LM_STUDIO_MODEL:-qwen3-vl-4b-instruct}"

# 4. Run the app --------------------------------------------------------------
echo "[app] starting on http://127.0.0.1:5000"
cd "$root/src"
exec "$root/.venv/bin/python" app.py
