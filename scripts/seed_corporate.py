"""Seed one company's approved-but-unpaid employees, so the Corporate
Payments screen has a realistic batch to invoice.

    cd src
    $env:SEED_PASSWORD="..."; ..\\venv\\Scripts\\python.exe ..\\scripts\\seed_corporate.py

Defaults to the worked example from the spec: 5 employees on CEA Training and
5 on CEM Training, both Online, which lists at PHP 18,000 each -> PHP 180,000
before any override.

These are ordinary trainees created the way the corporate flow expects to find
them: an accepted registration plus an unpaid account. Nothing here bypasses
the invitation-only rule -- the Corporate Payments screen only ever *pays for*
accounts that already exist, and this just manufactures that starting state.

The password comes from the environment, never from this file. Existing
accounts are left alone -- re-running will not flip someone who has since paid
back to unpaid. Pass --reset-passwords to set every one of this company's
accounts to SEED_PASSWORD, which is the one thing a re-run will change.
"""
import os
import sys

# Running a script puts the script's own folder on sys.path, not the working
# directory, so src/ has to be added explicitly for the flat imports below.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from werkzeug.security import generate_password_hash

from db import get_db, init_db
from pricing import calculate_fee
from _guard import require_local_db

PASSWORD = os.getenv("SEED_PASSWORD", "")
COMPANY  = os.getenv("SEED_COMPANY", "VXE")
RESET    = "--reset-passwords" in sys.argv

# Online delivery is what the PHP 18,000 price keys off; see src/pricing.py.
DELIVERY = "Online, 7 days, 56 hours"

# (program code, form label, how many employees)
COHORTS = [
    ("cea_training", "CEA Training", 5),
    ("training",     "CEM Training", 5),
]

FIRST = ["Alon", "Bea", "Caleb", "Dina", "Elias", "Farah", "Gavin", "Hana",
         "Ivan", "Jules", "Kira", "Luis"]
LAST  = ["Abad", "Bacani", "Cordero", "Duran", "Espino", "Fajardo", "Gatchalian",
         "Herrera", "Ilagan", "Jimenez", "Kalaw", "Lazaro"]


def slug(company):
    return "".join(ch for ch in company.lower() if ch.isalnum()) or "corp"


def main():
    if not PASSWORD:
        sys.exit("SEED_PASSWORD is not set. Choose one and re-run, e.g.\n"
                 '  $env:SEED_PASSWORD="something-strong"; '
                 "..\\venv\\Scripts\\python.exe ..\\scripts\\seed_corporate.py")

    require_local_db()
    init_db()
    conn = get_db()
    cur  = conn.cursor()

    tag = slug(COMPANY)
    rows, created, n = [], 0, 0
    for code, label, count in COHORTS:
        fee = calculate_fee(code, DELIVERY)
        if not fee:
            sys.exit("No published price for %s / %s" % (code, DELIVERY))
        for _ in range(count):
            n += 1
            fname = FIRST[(n - 1) % len(FIRST)]
            lname = LAST[(n - 1) % len(LAST)]
            email = "%s.employee%02d@%s.test" % (tag, n, tag)
            reg_id = ("%s%03d" % (tag.upper()[:4], n))[:8]

            cur.execute("SELECT id, payment_status FROM users WHERE email = %s", (email,))
            found = cur.fetchone()
            if found:
                state = "existing (%s)" % found[1]
                if RESET:
                    cur.execute("UPDATE users SET password_hash=%s, archived_at=NULL, "
                                "failed_login_attempts=0, locked_until=NULL WHERE id=%s",
                                (generate_password_hash(PASSWORD), found[0]))
                    state = "password reset (%s)" % found[1]
                rows.append((email, label, fee["total"], state))
                continue

            # The registration has to be there first: the corporate screen
            # prices each trainee from it, and without one the fee falls back
            # to the TRAINING_FEE env default.
            cur.execute("SELECT id FROM registrations WHERE email = %s", (email,))
            if not cur.fetchone():
                cur.execute("""
                    INSERT INTO registrations (id, form_type, form_label, submitted_at,
                                               full_name, email, company_name,
                                               training_type, status, is_qualified)
                    VALUES (%s,%s,%s,NOW(),%s,%s,%s,%s,'accepted',1)
                    ON CONFLICT (id) DO NOTHING
                """, (reg_id, code, label, "%s %s" % (fname, lname), email, COMPANY,
                      DELIVERY))

            cur.execute("""
                INSERT INTO users (role, fname, lname, email, password_hash,
                                   company_name, payment_status, training_type)
                VALUES ('trainee',%s,%s,%s,%s,%s,'unpaid',%s)
            """, (fname, lname, email, generate_password_hash(PASSWORD), COMPANY, code))
            created += 1
            rows.append((email, label, fee["total"], "created"))

    conn.commit()
    cur.close()
    conn.close()

    width = max(len(e) for e, _, _, _ in rows)
    total = sum(r[2] for r in rows)
    print()
    print("%s — unpaid employees for the Corporate Payments screen" % COMPANY)
    print("-" * (width + 46))
    for email, label, price, state in rows:
        print("  %-*s  %-14s %10s  %s"
              % (width, email, label, "{:,.2f}".format(price), state))
    print("-" * (width + 46))
    print("  %-*s  %-14s %10s" % (width, "list total", "", "{:,.2f}".format(total)))
    print()
    print("  %d created, %d already existed." % (created, len(rows) - created))
    print("  Invoice them at /admin#corporate — override the total to see the")
    print("  price-override path (a note is required).")


if __name__ == "__main__":
    main()
