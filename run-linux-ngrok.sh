#!/usr/bin/env bash
# PowerWize + ngrok launcher (Linux) — counterpart to PowerWize-Ngrok.bat.
#
# One-time setup this script does NOT do for you (same as the .bat, which
# also assumes ngrok is already signed in): run this once first —
#   ngrok config add-authtoken <your-authtoken>   # from https://dashboard.ngrok.com
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$root"

command -v ngrok >/dev/null 2>&1 || {
    echo "[ngrok] not found on PATH. Install it (see LINUX_SETUP.md) and run:"
    echo "         ngrok config add-authtoken <your-authtoken>"
    exit 1
}

echo "============================================"
echo "  Starting PowerWize (with ngrok tunnel)"
echo "============================================"
echo

# docker group membership does not apply to an already-open shell, so route
# every docker call through `sg docker` when the current shell lacks it.
if id -nG | tr ' ' '\n' | grep -qx docker && docker info >/dev/null 2>&1; then
    docker() { command docker "$@"; }
else
    docker() { sg docker -c "docker $(printf '%q ' "$@")"; }
fi

# 1. PostgreSQL ----------------------------------------------------------
if [ "$(docker inspect -f '{{.State.Running}}' powerwize-postgres 2>/dev/null || echo false)" = true ]; then
    echo "[database] already running"
else
    echo "[database] starting..."
    docker compose up -d
fi
for _ in $(seq 1 30); do
    docker exec powerwize-postgres pg_isready -q -U postgres >/dev/null 2>&1 && break
    sleep 1
done

# 2. Free port 5000 from any leftover app run -----------------------------
# app.py runs with its cwd already changed to src/, so argv is "python app.py"
# -- not "python src/app.py" -- match the venv path instead of the src/ prefix.
pkill -f "[P]owerWize/\.venv/bin/python app\.py" 2>/dev/null && echo "[app] stopped old instance" || true
sleep 1

# 3. Same LM Studio model-name override as run-linux.sh -------------------
export LM_STUDIO_MODEL="${LM_STUDIO_MODEL:-qwen3-vl-4b-instruct}"

# 4. Start Flask in the background, logged to a file ----------------------
echo "[app] starting on http://127.0.0.1:5000 (log: /tmp/powerwize-app.log)"
(cd "$root/src" && exec "$root/.venv/bin/python" app.py) > /tmp/powerwize-app.log 2>&1 &
app_pid=$!

# Stop the Flask process when this script exits (e.g. Ctrl+C on ngrok below)
# — matches the .bat's "close both windows to stop" intent, minus the manual step.
cleanup() { kill "$app_pid" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

# 5. Give Flask a moment to bind the port, then start the ngrok tunnel ----
sleep 3
if ! kill -0 "$app_pid" 2>/dev/null; then
    echo "[app] FAILED to start — see /tmp/powerwize-app.log"
    tail -n 30 /tmp/powerwize-app.log
    exit 1
fi

echo "[ngrok] starting tunnel to port 5000..."
echo "Inspector: http://127.0.0.1:4040   (Ctrl+C here stops both the tunnel and the app)"
echo
ngrok http 5000
