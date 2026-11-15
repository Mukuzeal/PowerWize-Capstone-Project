#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/scripts/linux-common.sh"
command -v ngrok >/dev/null || { echo "Install ngrok and configure its authtoken first." >&2; exit 1; }
linux_prepare
mkdir -p "$root/logs"
(cd "$root/src" && exec "$root/.venv/bin/python" -m flask --app app run --no-reload) > "$root/logs/linux-app.log" 2>&1 &
app_pid=$!
cleanup() { kill "$app_pid" 2>/dev/null || true; wait "$app_pid" 2>/dev/null || true; }
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
ready=false
for ((attempt=0; attempt<60; attempt++)); do
    if ! kill -0 "$app_pid" 2>/dev/null; then
        tail -n 30 "$root/logs/linux-app.log"
        exit 1
    fi
    if "$root/.venv/bin/python" -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:5000/", timeout=1)' >/dev/null 2>&1; then
        ready=true
        break
    fi
    sleep 1
done
[[ "$ready" == true ]] || { echo "App did not become ready. See logs/linux-app.log" >&2; exit 1; }
ngrok http 5000
