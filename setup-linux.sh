#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$root"
python_bin="${PYTHON_BIN:-python3.12}"
command -v "$python_bin" >/dev/null || { echo "Install Python 3.12 and its venv package, or set PYTHON_BIN to a compatible Python." >&2; exit 1; }
if [[ -e .venv && ! -x .venv/bin/python ]]; then
    echo ".venv belongs to another OS or is incomplete. Move it aside before setup." >&2
    exit 1
fi
"$python_bin" -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
if [[ ! -f .env ]]; then
    cp .env.example .env
    echo "Created .env. Set SECRET_KEY and your service credentials before running."
fi
echo "Ready: bash run-linux.sh"
