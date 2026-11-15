"""Export the configured local database as portable SQL, preserving the last dump.

Run with the project's Python: python scripts/export_linux_db.py
Set PG_BIN to the PostgreSQL bin directory if pg_dump is not on PATH.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from datetime import datetime

from dotenv import load_dotenv
from psycopg2.extensions import parse_dsn

ROOT = Path(__file__).resolve().parents[1]


def pg_tool(name):
    suffix = '.exe' if os.name == 'nt' else ''
    if os.getenv('PG_BIN'):
        candidate = Path(os.environ['PG_BIN']) / (name + suffix)
        if candidate.is_file():
            return str(candidate)
        raise SystemExit(f'{name} not found in PG_BIN')
    found = shutil.which(name)
    if found:
        return found
    if os.name == 'nt':
        for base, pattern in ((Path('C:/Program Files/PostgreSQL'), f'*/bin/{name}.exe'),
                              (Path('C:/laragon/bin/postgresql'), f'*/bin/{name}.exe')):
            hits = sorted(base.glob(pattern), reverse=True)
            if hits:
                return str(hits[0])
    raise SystemExit(f'Install PostgreSQL client tools or set PG_BIN to find {name}.')


def connection_env(url):
    env = dict(os.environ)
    for key, value in parse_dsn(url).items():
        env['PG' + ('DATABASE' if key == 'dbname' else key.upper())] = value
    env['PGCONNECT_TIMEOUT'] = '10'
    return env


def main():
    load_dotenv(ROOT / '.env')
    url = os.getenv('LOCAL_DATABASE_URL') or os.getenv('DATABASE_URL')
    if not url:
        raise SystemExit('Set LOCAL_DATABASE_URL or DATABASE_URL first.')
    if parse_dsn(url).get('host') not in ('localhost', '127.0.0.1', '::1', None):
        raise SystemExit('This export expects a local database. Set LOCAL_DATABASE_URL.')
    target = ROOT / 'powerwize_dump.sql'
    fd, name = tempfile.mkstemp(prefix='powerwize_dump.', suffix='.tmp', dir=ROOT)
    os.close(fd)
    temporary = Path(name)
    try:
        subprocess.run([pg_tool('pg_dump'), '--no-password', '--format=plain',
                        '--no-owner', '--no-privileges', '--encoding=UTF8',
                        '--file', str(temporary)], env=connection_env(url), check=True)
        if target.exists():
            backup = ROOT / 'backups' / ('linux-export-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
            backup.mkdir(parents=True)
            shutil.copy2(target, backup / target.name)
        temporary.replace(target)
        print(f'Exported {target.name}: {target.stat().st_size:,} bytes (UTF-8).')
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
