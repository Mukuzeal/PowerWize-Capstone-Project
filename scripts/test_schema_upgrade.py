"""Upgrade from a representative OLDER schema.

Re-running init_db() on an already-current database proves only idempotence.
This builds a database that looks like a genuinely older PowerWize — the
pre-Phase-0, pre-intake shape, with real rows in it — then runs init_db() over
the top and checks that the upgrade lands without losing data.

Deliberately includes the two conditions that broke upgrades before:
  * tables carrying FKs to `users` must be created after it
  * `uq_account_token_live` cannot be built while a registration holds more
    than one unused invitation, so the migration must retire the extras first

    cd src; ..\\venv\\Scripts\\python.exe ..\\scripts\\test_schema_upgrade.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from _testdb import use_test_db, assert_isolated, TEST_DB_NAME   # noqa: E402

use_test_db(recreate=True)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import hashlib                                   # noqa: E402
from datetime import datetime, timedelta         # noqa: E402

from db.core import get_db, init_db              # noqa: E402

results = []


def check(name, passed, detail=""):
    results.append((name, passed, detail))
    print(f"  [{'PASS' if passed else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


# ── A representative older schema ────────────────────────────────────────────
# Only the columns that existed before this work: no selfie_reviewed_at, no
# documents_purged_at, no correction_note, no users.registration_id, and no
# intake / notification / document-review tables at all.
OLD_SCHEMA = """
CREATE TABLE batches (
    id SERIAL PRIMARY KEY, name VARCHAR(100) NOT NULL, type VARCHAR(30) NOT NULL,
    start_date DATE NOT NULL, dates DATE[] NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);

CREATE TABLE registrations (
    id VARCHAR(8) PRIMARY KEY, form_type VARCHAR(30) NOT NULL,
    form_label VARCHAR(50) NOT NULL, submitted_at TIMESTAMP NOT NULL,
    title VARCHAR(20), full_name VARCHAR(200), middle_name VARCHAR(100),
    residence VARCHAR(300), company_name VARCHAR(200), designation VARCHAR(150),
    company_address VARCHAR(300), contact_number VARCHAR(30), email VARCHAR(150),
    birthdate VARCHAR(20), age VARCHAR(5), doe_expiry VARCHAR(20),
    training_type VARCHAR(250), batch_id INT NULL,
    photo_id VARCHAR(255), resume VARCHAR(255), expired_doe VARCHAR(255),
    valid_id VARCHAR(255), selfie_with_id VARCHAR(255),
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    is_qualified SMALLINT NOT NULL DEFAULT 1, gemp_designation VARCHAR(200) NULL,
    FOREIGN KEY (batch_id) REFERENCES batches(id) ON DELETE SET NULL);

CREATE TABLE users (
    id SERIAL PRIMARY KEY, role VARCHAR(20) NOT NULL, fname VARCHAR(100) NOT NULL,
    lname VARCHAR(100) NOT NULL, email VARCHAR(150) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL, contact_number VARCHAR(20),
    company_name VARCHAR(150), payment_status VARCHAR(10) NOT NULL DEFAULT 'unpaid',
    training_type VARCHAR(250) NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    archived_at TIMESTAMP NULL DEFAULT NULL);

CREATE TABLE account_tokens (
    token VARCHAR(64) PRIMARY KEY, reg_id VARCHAR(8) NOT NULL,
    email VARCHAR(150) NOT NULL, is_qualified SMALLINT NOT NULL DEFAULT 1,
    expires_at TIMESTAMP NOT NULL, used_at TIMESTAMP NULL DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (reg_id) REFERENCES registrations(id) ON DELETE CASCADE);
"""


def _h(s):
    return hashlib.sha256(s.encode()).hexdigest()


print(f"\nisolated database: {assert_isolated()}")

print("\n1. Build the older schema and populate it")
conn = get_db(); cur = conn.cursor()
cur.execute(OLD_SCHEMA)
cur.execute("INSERT INTO batches (name, type, start_date) VALUES ('B1','training','2026-01-05') RETURNING id")
bid = cur.fetchone()[0]
cur.execute("""INSERT INTO registrations (id, form_type, form_label, submitted_at,
               full_name, email, status, is_qualified, photo_id, valid_id, selfie_with_id, batch_id)
               VALUES ('OLD00001','training','Training',NOW(),'Legacy Person',
                       'legacy@old.test','accepted',0,'p.png','v.png','s.png',%s)""", (bid,))
cur.execute("""INSERT INTO users (role, fname, lname, email, password_hash)
               VALUES ('admin','A','B','olduser@old.test','x')""")
# TWO unused invitations for one registration — the exact state the new
# partial unique index cannot tolerate.
for i, age in enumerate([3, 1]):
    cur.execute("""INSERT INTO account_tokens (token, reg_id, email, is_qualified,
                   expires_at, created_at) VALUES (%s,'OLD00001','legacy@old.test',0,%s,%s)""",
                (_h(f"tok{i}"), datetime.now() + timedelta(days=7),
                 datetime.now() - timedelta(days=age)))
conn.commit()
cur.execute("SELECT COUNT(*) FROM account_tokens WHERE reg_id='OLD00001'")
check("older schema seeded with 2 duplicate invitations", cur.fetchone()[0] == 2)
cur.close(); conn.close()

print("\n2. Run init_db() over the older schema")
try:
    init_db()
    check("upgrade completed without error", True)
except Exception as e:
    check("upgrade completed without error", False, f"{type(e).__name__}: {e}")
    print("\nABORTING — upgrade failed.")
    sys.exit(1)

print("\n3. Existing data survived")
conn = get_db(); cur = conn.cursor()
cur.execute("SELECT full_name, status, is_qualified FROM registrations WHERE id='OLD00001'")
row = cur.fetchone()
check("registration row intact", row == ("Legacy Person", "accepted", 0), str(row))
check("is_qualified=0 preserved (no invented policy)", row[2] == 0)
cur.execute("SELECT COUNT(*) FROM users WHERE email='olduser@old.test'")
check("existing user intact", cur.fetchone()[0] == 1)

print("\n4. New columns added, not guessed")
cur.execute("""SELECT column_name FROM information_schema.columns
                WHERE table_name='registrations'
                  AND column_name IN ('selfie_reviewed_at','selfie_outcome',
                                      'documents_purged_at','correction_note')
                ORDER BY column_name""")
cols = [r[0] for r in cur.fetchall()]
check("registration retention/correction columns added", len(cols) == 4, str(cols))
cur.execute("SELECT selfie_reviewed_at, documents_purged_at FROM registrations WHERE id='OLD00001'")
r = cur.fetchone()
check("historical review outcome NOT inferred (both NULL)", r == (None, None), str(r))
cur.execute("""SELECT column_name FROM information_schema.columns
                WHERE table_name='users' AND column_name='registration_id'""")
check("users.registration_id added", cur.fetchone() is not None)
cur.execute("SELECT registration_id FROM users WHERE email='olduser@old.test'")
check("existing account link left NULL, not matched by email",
      cur.fetchone()[0] is None)

print("\n5. Duplicate invitations retired so the index could be built")
cur.execute("SELECT COUNT(*) FROM account_tokens WHERE reg_id='OLD00001' AND used_at IS NULL")
check("exactly one unused invitation remains", cur.fetchone()[0] == 1)
cur.execute("""SELECT indexname FROM pg_indexes
                WHERE tablename='account_tokens' AND indexname='uq_account_token_live'""")
check("uq_account_token_live created", cur.fetchone() is not None)

print("\n6. New tables present")
cur.execute("""SELECT table_name FROM information_schema.tables
                WHERE table_name IN ('corporate_intakes','corporate_intake_slots',
                                     'corporate_notifications',
                                     'registration_document_reviews')
                ORDER BY table_name""")
tables = [r[0] for r in cur.fetchall()]
check("all four new tables created", len(tables) == 4, str(tables))
cur.close(); conn.close()

print("\n7. program_code is backfilled from authoritative sources only")
# An existing class carries a free-text label like "Online", which is shared
# by CEM and CEA. Deriving the programme from that label guessed, and the
# guess resolved an old CEA class to CEM. The backfill reads
# corporate_intakes.form_type / corporate_payment_items.form_type instead, and
# leaves genuinely ambiguous rows NULL so they block rather than mis-resolve.
conn = get_db(); cur = conn.cursor()
cur.execute("""INSERT INTO users (role, fname, lname, email, password_hash,
               payment_status) VALUES ('admin','S','U','schema@up.test','x','unpaid')
               ON CONFLICT (email) DO UPDATE SET role='admin' RETURNING id""")
UP_ADMIN = cur.fetchone()[0]
cur.execute("""INSERT INTO corporate_intakes
               (company_name, contact_person, contact_email, form_type,
                training_type, created_by)
               VALUES ('CEA Legacy Co','L','l@up.test','cea_training',
                       'Online', %s) RETURNING id""", (UP_ADMIN,))
UP_INTAKE = cur.fetchone()[0]
# Pre-upgrade shape: a class with the label only and NO program_code.
cur.execute("""INSERT INTO training_classes
               (name, training_type, intake_id, join_code, created_by)
               VALUES ('Legacy CEA batch','Online',%s,'LEGACY1',%s)
               RETURNING id""", (UP_INTAKE, UP_ADMIN))
LEGACY = cur.fetchone()[0]
# And one with no derivable source at all.
cur.execute("""INSERT INTO training_classes
               (name, training_type, join_code, created_by)
               VALUES ('Orphan batch','Online','LEGACY2',%s) RETURNING id""",
            (UP_ADMIN,))
ORPHAN = cur.fetchone()[0]
cur.execute("UPDATE training_classes SET program_code=NULL WHERE id IN (%s,%s)",
            (LEGACY, ORPHAN))
conn.commit(); cur.close(); conn.close()

init_db()

conn = get_db(); cur = conn.cursor()
cur.execute("SELECT program_code FROM training_classes WHERE id=%s", (LEGACY,))
got = cur.fetchone()[0]
check("an old CEA class resolves to cea_training, not CEM",
      got == "cea_training", f"got {got!r}")
cur.execute("SELECT program_code FROM training_classes WHERE id=%s", (ORPHAN,))
orphan_code = cur.fetchone()[0]
check("an un-derivable class is left NULL, not guessed",
      orphan_code is None, f"got {orphan_code!r}")
cur.close(); conn.close()

from db import membership_authority                   # noqa: E402
ok, why = membership_authority(ORPHAN, UP_ADMIN)
check("and a NULL programme blocks rather than defaulting",
      not ok and ("no programme recorded" in (why or "")
                  or "trainee accounts" in (why or "")), (why or "")[:70])


print("\n8. Upgrade is idempotent")
try:
    init_db(); init_db()
    check("init_db re-runs cleanly after upgrade", True)
except Exception as e:
    check("init_db re-runs cleanly after upgrade", False, f"{type(e).__name__}: {e}")
conn = get_db(); cur = conn.cursor()
cur.execute("SELECT program_code FROM training_classes WHERE id=%s", (LEGACY,))
check("the backfill does not churn on re-run", cur.fetchone()[0] == "cea_training")
cur.close(); conn.close()

failed = [x for x in results if not x[1]]
print(f"\n{'='*64}\n{len(results) - len(failed)}/{len(results)} passed")
for n, _, d in failed:
    print(f"  FAILED: {n} {d}")
sys.exit(1 if failed else 0)
