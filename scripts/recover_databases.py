#!/usr/bin/env python3
import subprocess
import time
import os
import sys
from pathlib import Path

MYSQLD = r"C:\laragon\bin\mysql\mysql-8.4.3-winx64\bin\mysqld.exe"
MYSQLDUMP = r"C:\laragon\bin\mysql\mysql-8.4.3-winx64\bin\mysqldump.exe"
MYSQL = r"C:\laragon\bin\mysql\mysql-8.4.3-winx64\bin\mysql.exe"
ISOLATED_BASE = r"C:\laragon\data\mysql-8.4-isolated"
OUTPUT_DIR = r"e:\CAPSTONE PROJECT\PowerWize\db_backups"

# Create output directory
Path(OUTPUT_DIR).mkdir(exist_ok=True)

databases = [
    ('harayahomesdb', 3307),
    ('testharaya', 3308),
    ('student_db', 3309),
]

def create_config(datadir, port, db_name):
    """Create my.ini for isolated database"""
    config = f"""[mysqld]
port={port}
datadir={datadir}
socket={datadir}\\mysql.sock
skip-grant-tables
innodb-force-recovery=6
log-error={datadir}\\error.log
pid-file={datadir}\\mysql.pid
"""
    config_path = os.path.join(datadir, 'my.ini')
    with open(config_path, 'w') as f:
        f.write(config)
    return config_path

def start_mysqld(datadir, port, db_name):
    """Start isolated mysqld instance"""
    config = create_config(datadir, port, db_name)
    print(f"  Starting mysqld on port {port} (config: {config})...")

    try:
        proc = subprocess.Popen(
            [MYSQLD, f"--defaults-file={config}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        time.sleep(4)
        return proc
    except Exception as e:
        print(f"    ERROR: {e}")
        return None

def test_connection(port):
    """Test MySQL connection"""
    try:
        result = subprocess.run(
            [MYSQL, '-u', 'root', f'--port={port}', '-e', 'SELECT 1;'],
            capture_output=True,
            timeout=5
        )
        return result.returncode == 0
    except:
        return False

def dump_database(port, db_name, output_file):
    """Dump database to SQL file"""
    print(f"  Dumping {db_name} to {output_file}...")
    try:
        with open(output_file, 'w') as f:
            subprocess.run(
                [MYSQLDUMP, '-u', 'root', f'--port={port}', '--single-transaction', db_name],
                stdout=f,
                stderr=subprocess.PIPE,
                timeout=30
            )
        size_kb = os.path.getsize(output_file) / 1024
        print(f"    Dumped: {size_kb:.1f} KB")
        return True
    except Exception as e:
        print(f"    ERROR: {e}")
        return False

def stop_mysqld(proc):
    """Kill mysqld process"""
    if proc:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except:
            proc.kill()
        time.sleep(2)

# Recover each database
print("=" * 60)
print(" DATABASE RECOVERY - Isolated Method")
print("=" * 60)

for db_name, port in databases:
    datadir = os.path.join(ISOLATED_BASE, db_name)
    output_file = os.path.join(OUTPUT_DIR, f"{db_name}.sql")

    print(f"\n{db_name}:")

    # Start mysqld
    proc = start_mysqld(datadir, port, db_name)
    if not proc:
        print(f"  SKIPPED: Failed to start mysqld")
        continue

    # Test connection
    for attempt in range(10):
        if test_connection(port):
            print(f"  Connected on port {port}")
            break
        time.sleep(1)
    else:
        print(f"  FAILED: Could not connect to port {port}")
        stop_mysqld(proc)
        continue

    # Dump database
    if dump_database(port, db_name, output_file):
        print(f"  Dump saved to: {output_file}")

    # Stop mysqld
    stop_mysqld(proc)
    print(f"  Stopped mysqld")

print("\n" + "=" * 60)
print(" Recovery complete!")
print("=" * 60)
print(f"\nBackup files in: {OUTPUT_DIR}")
for db_name, _ in databases:
    sql_file = os.path.join(OUTPUT_DIR, f"{db_name}.sql")
    if os.path.exists(sql_file):
        size_kb = os.path.getsize(sql_file) / 1024
        print(f"  ✓ {db_name}.sql ({size_kb:.1f} KB)")
    else:
        print(f"  ✗ {db_name}.sql (NOT FOUND)")
