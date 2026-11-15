#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/scripts/linux-common.sh"
linux_prepare
echo "[app] starting on http://127.0.0.1:5000"
exec "$root/.venv/bin/python" "$root/src/app.py"
