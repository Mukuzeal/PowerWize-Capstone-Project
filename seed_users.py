"""
Run once to seed 10 test users.
  python seed_users.py
"""
from werkzeug.security import generate_password_hash
from db import get_db, init_db

TEST_USERS = [
    ("trainee",  "Maria",    "Santos",    "maria.santos@gmail.com",      "Test@1234", "09171234501", "MERALCO"),
    ("trainee",  "Jose",     "Reyes",     "jose.reyes@gmail.com",        "Test@1234", "09171234502", "NAPOCOR"),
    ("trainee",  "Ana",      "Cruz",      "ana.cruz@yahoo.com",          "Test@1234", "09171234503", "First Gen"),
    ("trainee",  "Carlos",   "Garcia",    "carlos.garcia@gmail.com",     "Test@1234", "09171234504", "PNOC"),
    ("trainee",  "Liza",     "Mendoza",   "liza.mendoza@gmail.com",      "Test@1234", "09171234505", "PSALM"),
    ("employee", "Roberto",  "Dela Cruz", "roberto.delacruz@ewize.com",  "Test@1234", "09171234506", "e-Wize Solutions"),
    ("employee", "Patricia", "Villanueva","patricia.v@ewize.com",        "Test@1234", "09171234507", "e-Wize Solutions"),
    ("trainee",  "Miguel",   "Torres",    "miguel.torres@gmail.com",     "Test@1234", "09171234508", "Aboitiz Power"),
    ("trainee",  "Grace",    "Lim",       "grace.lim@gmail.com",         "Test@1234", "09171234509", "San Miguel Energy"),
    ("trainee",  "Ramon",    "Aquino",    "ramon.aquino@hotmail.com",    "Test@1234", "09171234510", "DOE"),
]

def main():
    init_db()
    conn = get_db()
    cur  = conn.cursor()
    added = 0
    for role, fname, lname, email, password, contact, company in TEST_USERS:
        cur.execute("SELECT id FROM users WHERE email = %s", (email,))
        if cur.fetchone():
            print(f"  skip  {email} (already exists)")
            continue
        cur.execute(
            "INSERT INTO users (role, fname, lname, email, password_hash, contact_number, company_name) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (role, fname, lname, email, generate_password_hash(password), contact, company)
        )
        added += 1
        print(f"  added {role:8s}  {fname} {lname} — {email}")
    conn.commit()
    cur.close()
    conn.close()
    print(f"\nDone. {added} user(s) inserted. Password for all: Test@1234")

if __name__ == "__main__":
    main()
