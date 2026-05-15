from db import get_db
from werkzeug.security import check_password_hash

conn = get_db()
cur = conn.cursor(dictionary=True)

test_accounts = [
    ("admin@ewize.com",              "Admin@1234"),
    ("roberto.delacruz@ewize.com",   "Test@1234"),
    ("maria.santos@gmail.com",       "Test@1234"),
    ("miguel.torres@gmail.com",      "Test@1234"),
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
