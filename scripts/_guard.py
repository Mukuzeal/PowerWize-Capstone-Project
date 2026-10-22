"""Safety guard for one-off maintenance/seed scripts.

These scripts write directly to whatever DATABASE_URL resolves to, with no
distinction between dev and production. Call require_local_db() before any
destructive operation so a misconfigured/production DATABASE_URL doesn't get
silently seeded or mutated by a one-off script.
"""
import os
import sys
from urllib.parse import urlparse


def require_local_db():
    host = urlparse(os.environ.get("DATABASE_URL", "")).hostname
    if host not in ("localhost", "127.0.0.1", None) and os.environ.get("POWERWIZE_ALLOW_REMOTE") != "1":
        sys.exit(
            f"Refusing to run against non-local DATABASE_URL host '{host}'. "
            f"Set POWERWIZE_ALLOW_REMOTE=1 to override."
        )
