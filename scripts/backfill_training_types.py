"""
backfill_training_types.py — One-time fix for existing trainee accounts whose
users.training_type was set to raw registration free text (e.g. "Hybrid, 5
days online + 2 days face to face...") or left NULL, instead of one of the
normalized LMS program codes. See db.lms.normalize_training_type() for the
same normalization now applied going forward at account-creation time.

Run from the src/ directory so db.py is importable:
    cd src && python ../scripts/backfill_training_types.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from _guard import require_local_db
require_local_db()

from db import get_db, dict_cur, normalize_training_type

VALID_CODES = {'training', 'cea_training', 'renewal', 'cea_renewal',
               'cem_renewal', 'gemp_lgu', 'gemp_oge'}

conn = get_db()
cur = dict_cur(conn)
cur.execute("SELECT id, email, training_type FROM users WHERE role = 'trainee'")
trainees = cur.fetchall()

updated = 0
for t in trainees:
    if t['training_type'] in VALID_CODES:
        continue
    cur.execute(
        "SELECT form_type, training_type FROM registrations "
        "WHERE email = %s ORDER BY submitted_at DESC LIMIT 1",
        (t['email'],)
    )
    reg = cur.fetchone()
    normalized = normalize_training_type(
        reg['form_type'] if reg else None,
        reg['training_type'] if reg else None,
    )
    cur.execute("UPDATE users SET training_type = %s WHERE id = %s", (normalized, t['id']))
    print(f"  #{t['id']:<4} {t['email']:<40} {t['training_type']!r:<50} -> {normalized}")
    updated += 1

conn.commit()
cur.close()
conn.close()
print(f"\nUpdated {updated} of {len(trainees)} trainee accounts.")
