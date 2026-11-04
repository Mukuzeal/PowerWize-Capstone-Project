"""Copy the whole database one direction: local <-> Supabase.

The app reads a single DATABASE_URL (src/db/core.py), so it talks to exactly
one database per process. There is no dual-write: keeping two live copies in
step is done here, deliberately, not on every request.

This is a REPLACE, not a merge. The target's public schema is dropped and
rebuilt from the source. Both sides use the same serial primary keys, so
merging them would collide on every table -- pick a direction and accept that
the target is overwritten.

    python scripts/db_sync.py --to-supabase              # local  -> Supabase
    python scripts/db_sync.py --to-supabase --schema-only
    python scripts/db_sync.py --to-local                 # Supabase -> local

--schema-only ships the 36 tables with no rows, which is how you stand up
Supabase without copying real trainees' names, addresses, birthdates, contact
numbers and password hashes into a cloud service. Seed it afterwards with
scripts/seed_roles.py.
"""
import argparse
import os
import shutil
import subprocess
import sys
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()

LOCAL = os.getenv("LOCAL_DATABASE_URL") or os.getenv("DATABASE_URL", "")
SUPA = os.getenv("SUPABASE_DATABASE_URL", "")


def _tool(name):
    """pg_dump/psql are rarely on PATH on Windows; fall back to the install."""
    found = shutil.which(name)
    if found:
        return found
    import glob
    for pat in (r"C:\Program Files\PostgreSQL\*\bin\%s.exe" % name,
                r"C:\Program Files (x86)\PostgreSQL\*\bin\%s.exe" % name):
        hits = sorted(glob.glob(pat), reverse=True)
        if hits:
            return hits[0]
    sys.exit(f"Could not find {name}. Install the PostgreSQL client tools or add them to PATH.")


def _label(url):
    p = urlparse(url)
    return f"{p.hostname}/{(p.path or '/').lstrip('/')}"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--to-supabase", action="store_true", help="local -> Supabase")
    g.add_argument("--to-local", action="store_true", help="Supabase -> local")
    ap.add_argument("--schema-only", action="store_true",
                    help="structure only, no rows (no personal data leaves the machine)")
    ap.add_argument("--yes", action="store_true", help="skip the typed confirmation")
    args = ap.parse_args()

    if not LOCAL:
        sys.exit("LOCAL_DATABASE_URL (or DATABASE_URL) is not set.")
    if not SUPA:
        sys.exit("SUPABASE_DATABASE_URL is not set. Add it to .env -- see .env.example.")

    src, dst = (LOCAL, SUPA) if args.to_supabase else (SUPA, LOCAL)

    # Same intent as scripts/_guard.py: a remote target is only ever written
    # on purpose. The direction flag alone is not enough -- an opt-in env var
    # keeps this consistent with every other script that can reach production.
    if args.to_supabase and os.getenv("POWERWIZE_ALLOW_REMOTE") != "1":
        sys.exit("Refusing to overwrite the remote database. Set POWERWIZE_ALLOW_REMOTE=1 to override.")

    print(f"  source : {_label(src)}")
    print(f"  target : {_label(dst)}   <-- will be REPLACED")
    print(f"  rows   : {'NO (schema only)' if args.schema_only else 'YES'}")
    if args.to_supabase and not args.schema_only:
        print("\n  WARNING: this copies real names, residences, contact numbers,")
        print("  birthdates and password hashes to a hosted service.")
        print("  Use --schema-only unless you have decided otherwise.")

    if not args.yes:
        if input(f"\nType the target host to confirm [{urlparse(dst).hostname}]: ").strip() != urlparse(dst).hostname:
            sys.exit("Aborted.")

    dump = [_tool("pg_dump"), src,
            # Supabase owns roles and extensions this dump must not touch, so
            # restrict to public and drop ownership/grants.
            "--schema=public", "--no-owner", "--no-privileges",
            "--clean", "--if-exists", "--quote-all-identifiers"]
    if args.schema_only:
        dump.append("--schema-only")

    restore = [_tool("psql"), dst, "-v", "ON_ERROR_STOP=1", "--quiet"]

    print("\nTransferring...")
    p1 = subprocess.Popen(dump, stdout=subprocess.PIPE)
    p2 = subprocess.Popen(restore, stdin=p1.stdout)
    p1.stdout.close()
    rc = p2.wait()
    if p1.wait() != 0 or rc != 0:
        sys.exit("Transfer failed -- the target may be half-written. Re-run before using it.")

    print(f"Done. {_label(dst)} now matches {_label(src)}.")
    if args.schema_only:
        print("Schema only -- seed it:  SEED_PASSWORD='...' POWERWIZE_ALLOW_REMOTE=1 python scripts/seed_roles.py")


if __name__ == "__main__":
    main()
