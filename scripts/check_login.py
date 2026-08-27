import os, sys
from db import get_db, dict_cur
from werkzeug.security import check_password_hash

conn = get_db()
cur = dict_cur(conn)

PASSWORD = os.getenv("SEED_PASSWORD", "")
if not PASSWORD:
    sys.exit('SEED_PASSWORD is not set - pass the password to check, e.g.\n'
             '  SEED_PASSWORD="..." python check_login.py')

# Emails only; the password to test against comes from the environment.
test_accounts = [
    ("admin@ewize.com",              PASSWORD),
    ("roberto.delacruz@ewize.com",   PASSWORD),
    ("maria.santos@gmail.com",       PASSWORD),
    ("miguel.torres@gmail.com",      PASSWORD),
]

for email, pwd in test_accounts:
    cur.execute(
        "SELECT id, role, fname, lname, password_hash, archived_at, payment_status "
        "FROM users WHERE email = %s", (email,)
    )
    row = cur.fetchone()
    if not row:
        print(f"NOT FOUND: {email}")
        continue
    ok = check_password_hash(row["password_hash"], pwd)
    archived = row["archived_at"] is not None
    print(f"{'OK  ' if ok and not archived else 'FAIL'} | {row['role']:8s} | {email} | pw_ok={ok} | archived={archived} | payment={row['payment_status']}")

cur.close()
conn.close()
