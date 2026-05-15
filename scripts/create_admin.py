"""
Run once to create the default admin account.
  python create_admin.py
"""
from werkzeug.security import generate_password_hash
from db import get_db, init_db

ADMIN_FNAME    = "Admin"
ADMIN_LNAME    = "EnergyWize"
ADMIN_EMAIL    = "admin@energywize.com"
ADMIN_PASSWORD = "Admin@2026"

def main():
    init_db()
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("SELECT id FROM users WHERE email = %s", (ADMIN_EMAIL,))
    if cur.fetchone():
        print(f"Admin account already exists: {ADMIN_EMAIL}")
    else:
        cur.execute(
            "INSERT INTO users (role, fname, lname, email, password_hash) VALUES (%s,%s,%s,%s,%s)",
            ("admin", ADMIN_FNAME, ADMIN_LNAME, ADMIN_EMAIL,
             generate_password_hash(ADMIN_PASSWORD))
        )
        conn.commit()
        print(f"Admin account created.")
        print(f"  Email   : {ADMIN_EMAIL}")
        print(f"  Password: {ADMIN_PASSWORD}")
    cur.close()
    conn.close()

if __name__ == "__main__":
    main()
