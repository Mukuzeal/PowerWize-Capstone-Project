"""
reseed_lms_modules.py — Wipes all existing LMS modules and recreates exactly
5 placeholder modules for each of the 7 training programs, all pointing at
the existing uploads/lms/3455dc5db88cd3b8a70761aa25723e5b.pdf file.

Confirmed destructive action, approved by the project owner: deletes every
lms_modules row (cascades to lms_module_files/lms_quizzes/
lms_practical_exams/lms_progress via existing foreign keys).

Run from the src/ directory so db.py is importable:
    cd src && python ../scripts/reseed_lms_modules.py
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from _guard import require_local_db
require_local_db()

from db import get_db, dict_cur, lms_create_module, lms_add_file, lms_toggle_publish

PROGRAMS = [
    ('training',     'CEM Training'),
    ('cea_training',  'CEA Training'),
    ('renewal',       'CEM Renewal'),
    ('cea_renewal',   'CEA Renewal'),
    ('cem_renewal',   'CEM Renewal (Professional)'),
    ('gemp_lgu',      'GEMP Training – LGU'),
    ('gemp_oge',      "GEMP Training – Gov't Entity"),
]
MODULES_PER_PROGRAM = 5
INSTRUCTOR_ID = 1  # System Administrator

PLACEHOLDER_FILENAME = '3455dc5db88cd3b8a70761aa25723e5b.pdf'
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLACEHOLDER_PATH = os.path.join(_PROJECT_ROOT, 'uploads', 'lms', PLACEHOLDER_FILENAME)

if not os.path.exists(PLACEHOLDER_PATH):
    sys.exit(f"Placeholder PDF not found at {PLACEHOLDER_PATH}")

placeholder_size = os.path.getsize(PLACEHOLDER_PATH)

conn = get_db()
cur = dict_cur(conn)
cur.execute("SELECT COUNT(*) AS n FROM lms_modules")
existing = cur.fetchone()['n']
cur.execute("DELETE FROM lms_modules")
conn.commit()
cur.close()
conn.close()
print(f"Deleted {existing} existing module(s).")

created = 0
for code, label in PROGRAMS:
    for i in range(1, MODULES_PER_PROGRAM + 1):
        mid = lms_create_module(
            INSTRUCTOR_ID,
            title=f"{label} — Module {i}",
            description=f"Placeholder module {i} of {MODULES_PER_PROGRAM} for the {label} program.",
            training_type=code,
            sort_order=i,
        )
        lms_add_file(mid, PLACEHOLDER_FILENAME, 'Module Material.pdf', 'pdf', placeholder_size)
        lms_toggle_publish(mid, True)  # published so the sequential-unlock flow is testable immediately
        created += 1

print(f"Created {created} module(s) across {len(PROGRAMS)} programs "
      f"({MODULES_PER_PROGRAM} each), all referencing {PLACEHOLDER_FILENAME}.")
