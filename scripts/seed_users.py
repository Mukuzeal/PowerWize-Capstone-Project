"""
Run once to seed 10 test users.
  python seed_users.py
"""
from werkzeug.security import generate_password_hash
from db import get_db, init_db

TEST_USERS = [
    ("admin",    "System",   "Administrator", "admin@ewize.com",             "Admin@1234", "09171234500", "PowerWize",           None),
    ("trainee",  "Maria",    "Santos",    "maria.santos@gmail.com",      "Test@1234", "09171234501", "MERALCO",             "training"),
    ("trainee",  "Jose",     "Reyes",     "jose.reyes@gmail.com",        "Test@1234", "09171234502", "NAPOCOR",             "cea_training"),
    ("trainee",  "Ana",      "Cruz",      "ana.cruz@yahoo.com",          "Test@1234", "09171234503", "First Gen",           "renewal"),
    ("trainee",  "Carlos",   "Garcia",    "carlos.garcia@gmail.com",     "Test@1234", "09171234504", "PNOC",                "cea_renewal"),
    ("trainee",  "Liza",     "Mendoza",   "liza.mendoza@gmail.com",      "Test@1234", "09171234505", "PSALM",               "cem_renewal"),
    ("employee", "Roberto",  "Dela Cruz", "roberto.delacruz@ewize.com",  "Test@1234", "09171234506", "e-Wize Solutions",    None),
    ("employee", "Patricia", "Villanueva","patricia.v@ewize.com",        "Test@1234", "09171234507", "e-Wize Solutions",    None),
    ("trainee",  "Miguel",   "Torres",    "miguel.torres@gmail.com",     "Test@1234", "09171234508", "Aboitiz Power",       "training"),
    ("trainee",  "Grace",    "Lim",       "grace.lim@gmail.com",         "Test@1234", "09171234509", "San Miguel Energy",   "cea_training"),
    ("trainee",  "Ramon",    "Aquino",    "ramon.aquino@hotmail.com",    "Test@1234", "09171234510", "DOE",                 "renewal"),
]

def main():
    init_db()
    conn = get_db()
    cur  = conn.cursor()
    added = 0
    for role, fname, lname, email, password, contact, company, training_type in TEST_USERS:
        cur.execute("SELECT id FROM users WHERE email = %s", (email,))
        if cur.fetchone():
            print(f"  skip  {email} (already exists)")
            continue
        payment_status = "paid" if role == "employee" else "unpaid"
        cur.execute(
            "INSERT INTO users (role, fname, lname, email, password_hash, contact_number, company_name, payment_status, training_type) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (role, fname, lname, email, generate_password_hash(password), contact, company, payment_status, training_type)
        )
        added += 1
        print(f"  added {role:8s}  {fname} {lname} — {email}")
    conn.commit()
    cur.close()
    conn.close()
    print(f"\nDone. {added} user(s) inserted. Password for all: Test@1234")

if __name__ == "__main__":
    main()
