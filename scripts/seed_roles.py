"""Seed one account per role, plus one Trainer per work-area combination, so
the permission matrix can be exercised by logging in rather than by reading
src/permissions.py.

    cd src
    $env:SEED_PASSWORD="..."; ..\\venv\\Scripts\\python.exe ..\\scripts\\seed_roles.py

The password comes from the environment, never from this file: a literal here
is a credential in version control, and the one that used to sit in
seed_users.py ended up published in the repository.

Existing accounts keep their password (re-seeding must not quietly reset one
that has since been rotated) -- pass --reset-passwords to force them all to
SEED_PASSWORD. Trainer work areas are always re-applied, since those are the
state under test rather than a secret.
"""
import os
import sys

# Running a script puts the script's own folder on sys.path, not the working
# directory, so src/ has to be added explicitly for the flat imports below.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from werkzeug.security import generate_password_hash

from db import get_db, init_db, set_user_capability, clear_user_capabilities
from permissions import (ROLE_LABELS, OVERRIDABLE, OVERRIDABLE_ROLES, can,
                         home_url_for)
from _guard import require_local_db

PASSWORD = os.getenv("SEED_PASSWORD", "")
RESET    = "--reset-passwords" in sys.argv

# (email, role, fname, lname, work areas or None for the role default)
#
# `employee` is the stored value for what the UI calls a Trainer. The three
# trainers differ only by work area, which is the point: same role, different
# remit, set per account in user_capabilities.
ACCOUNTS = [
    ("super.user@ewize.com",      "super_user", "Super",   "User",     None),
    ("secretary@ewize.com",       "secretary",  "Sec",     "Retary",   None),
    ("trainer.both@ewize.com",    "employee",   "Trainer", "Both",     ("manage_modules", "review_solar")),
    ("trainer.modules@ewize.com", "employee",   "Trainer", "Modules",  ("manage_modules",)),
    ("trainer.solar@ewize.com",   "employee",   "Trainer", "Solar",    ("review_solar",)),
    # Unpaid, so this one actually sees /payment — the discount code field and
    # the corporate-invoice picker are both unreachable from a paid account.
    ("trainee.unpaid@ewize.com",  "trainee",    "Unpaid",  "Trainee",  None),
]

# An unpaid trainee needs an approved registration behind them, otherwise the
# fee falls back to the TRAINING_FEE env default instead of a real program
# price. CEM Training / Online is PHP 18,000.
UNPAID_REGISTRATION = {
    "id":            "SEEDR01",
    "form_type":     "training",
    "form_label":    "CEM Training",
    "training_type": "Online, 7 days, 56 hours",
}

AREA_LABELS = {"manage_modules": "Training modules", "review_solar": "PV consultations"}


def _ensure_registration(cur, conn, email, fname, lname):
    """Give the seeded trainee an accepted registration so /payment quotes a
    real program price rather than the TRAINING_FEE fallback."""
    r = UNPAID_REGISTRATION
    cur.execute("SELECT id FROM registrations WHERE email = %s", (email,))
    if cur.fetchone():
        return
    cur.execute("""
        INSERT INTO registrations (id, form_type, form_label, submitted_at, full_name,
                                   email, training_type, status, is_qualified)
        VALUES (%s,%s,%s,NOW(),%s,%s,%s,'accepted',1)
        ON CONFLICT (id) DO NOTHING
    """, (r["id"], r["form_type"], r["form_label"], f"{fname} {lname}", email,
          r["training_type"]))
    conn.commit()


def apply_areas(cur_conn, user_id, role, areas):
    """Store only deviations from the role default, exactly like the admin UI."""
    if role not in OVERRIDABLE_ROLES or areas is None:
        clear_user_capabilities(user_id)
        return
    for cap in OVERRIDABLE:
        wanted = cap in areas
        set_user_capability(user_id, cap, None if wanted == can(role, cap) else wanted)


def main():
    if not PASSWORD:
        sys.exit("SEED_PASSWORD is not set. Choose one and re-run, e.g.\n"
                 '  $env:SEED_PASSWORD="something-strong"; '
                 "..\\venv\\Scripts\\python.exe ..\\scripts\\seed_roles.py")

    require_local_db()
    init_db()
    conn = get_db()
    cur  = conn.cursor()

    rows = []
    for email, role, fname, lname, areas in ACCOUNTS:
        cur.execute("SELECT id FROM users WHERE email = %s", (email,))
        found = cur.fetchone()
        if found:
            uid = found[0]
            if RESET:
                cur.execute("UPDATE users SET password_hash=%s, role=%s, archived_at=NULL, "
                            "failed_login_attempts=0, locked_until=NULL WHERE id=%s",
                            (generate_password_hash(PASSWORD), role, uid))
                state = "password reset"
            else:
                cur.execute("UPDATE users SET role=%s, archived_at=NULL WHERE id=%s", (role, uid))
                state = "existing (password unchanged)"
        else:
            # Staff never go through the payment wall, so they start paid; the
            # seeded trainee is deliberately unpaid.
            if role == "trainee":
                cur.execute(
                    "INSERT INTO users (role, fname, lname, email, password_hash, "
                    "company_name, payment_status, training_type) "
                    "VALUES (%s,%s,%s,%s,%s,'ZZ Test Corp','unpaid','training') RETURNING id",
                    (role, fname, lname, email, generate_password_hash(PASSWORD)))
            else:
                cur.execute(
                    "INSERT INTO users (role, fname, lname, email, password_hash, "
                    "company_name, payment_status) "
                    "VALUES (%s,%s,%s,%s,%s,'EnergyWize Solutions','paid') RETURNING id",
                    (role, fname, lname, email, generate_password_hash(PASSWORD)))
            uid = cur.fetchone()[0]
            state = "created"
        conn.commit()

        if role == "trainee":
            _ensure_registration(cur, conn, email, fname, lname)

        apply_areas(conn, uid, role, areas)
        rows.append((email, role, areas, state))

    cur.close()
    conn.close()

    width = max(len(e) for e, _, _, _ in rows)
    print()
    print("ROLE TEST ACCOUNTS  (password: the SEED_PASSWORD you just passed)")
    print("-" * (width + 58))
    for email, role, areas, state in rows:
        areas_txt = ""
        if role in OVERRIDABLE_ROLES:
            areas_txt = "  [" + ", ".join(AREA_LABELS[a] for a in (areas or OVERRIDABLE)) + "]"
        print("  %-*s  %-11s -> %-10s %s%s"
              % (width, email, ROLE_LABELS.get(role, role), home_url_for(role),
                 state, areas_txt))
    print()
    print("Add these to demo_credentials.txt if you want them written down —")
    print("that file is gitignored and is not touched by this script.")


if __name__ == "__main__":
    main()
