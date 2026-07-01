"""
seed_demo.py — Seeds two demo accounts for the Research Colloquium demo.

Run from the src/ directory so db.py is importable:
    cd src && python ../scripts/seed_demo.py

Accounts created
----------------
  demo.fail@powerwize.com   / Demo1234!  — trainee, no quiz history
                                            (take quiz live, fail, show AI hints)

  demo.ready@powerwize.com  / Demo1234!  — trainee, all modules completed
                                            (admin issues certificate during demo)

Both passwords: Demo1234!
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

from werkzeug.security import generate_password_hash
from datetime import datetime
import psycopg2
import psycopg2.extras


def get_conn():
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL not set")
    return psycopg2.connect(url)


def upsert_user(cur, role, fname, lname, email, password, contact, company, training_type=None):
    cur.execute("SELECT id FROM users WHERE email = %s", (email,))
    row = cur.fetchone()
    if row:
        print(f"  user already exists: {email} (id={row['id']})")
        return row['id']
    pw_hash = generate_password_hash(password)
    cur.execute(
        """INSERT INTO users
               (role, fname, lname, email, password_hash, contact_number,
                company_name, payment_status, training_type)
           VALUES (%s,%s,%s,%s,%s,%s,%s,'paid',%s)
           RETURNING id""",
        (role, fname, lname, email, pw_hash, contact, company, training_type)
    )
    uid = cur.fetchone()['id']
    print(f"  created user: {email} (id={uid})")
    return uid


def seed():
    conn = get_conn()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    print("\n" + "="*55)
    print("  POWERWIZE COLLOQUIUM DEMO SEED")
    print("="*55)

    # ── 1. Demo accounts ───────────────────────────────────────
    print("\n[1] Creating demo accounts...")

    fail_id = upsert_user(
        cur, "trainee", "Demo", "Trainee",
        "demo.fail@powerwize.com", "Demo1234!",
        "09171234888", "PowerWize Demo", "training"
    )

    ready_id = upsert_user(
        cur, "trainee", "Ready", "Trainee",
        "demo.ready@powerwize.com", "Demo1234!",
        "09171234889", "PowerWize Demo", "training"
    )

    conn.commit()

    # ── 2. Mark "ready" trainee as completed on all published modules ──────────
    print("\n[2] Completing all published modules for demo.ready account...")

    cur.execute("SELECT id, title FROM lms_modules WHERE is_published = 1")
    modules = cur.fetchall()
    print(f"  found {len(modules)} published module(s)")

    for mod in modules:
        mid = mod['id']
        cur.execute(
            """INSERT INTO lms_progress
                   (user_id, module_id, quiz_score, quiz_passed, exam_graded, exam_grade, completed, completed_at)
               VALUES (%s, %s, 85.00, 1, 1, 85, 1, %s)
               ON CONFLICT (user_id, module_id) DO UPDATE SET
                   quiz_score   = 85.00,
                   quiz_passed  = 1,
                   exam_graded  = 1,
                   exam_grade   = 85,
                   completed    = 1,
                   completed_at = %s""",
            (ready_id, mid, datetime.now(), datetime.now())
        )
        print(f"  completed: [{mid}] {mod['title']}")

    conn.commit()

    # ── 3. Verify eligibility ──────────────────────────────────
    print("\n[3] Checking certificate eligibility for demo.ready...")
    cur.execute("""
        SELECT COUNT(p.id) AS completed_count,
               (SELECT COUNT(*) FROM lms_modules WHERE is_published=1) AS total_modules
        FROM   lms_progress p
        WHERE  p.user_id = %s AND p.completed = 1
    """, (ready_id,))
    check = cur.fetchone()
    completed = check['completed_count']
    total     = check['total_modules']
    eligible  = completed >= total
    print(f"  completed={completed}, total_published={total}, eligible={'YES' if eligible else 'NO - WARNING'}")

    if not eligible:
        print("  WARNING: demo.ready is NOT eligible. Check if lms_modules table is populated.")

    # ── 4. Remove any existing cert so admin can issue it fresh ───────────────
    cur.execute("DELETE FROM lms_certificates WHERE user_id = %s", (ready_id,))
    deleted = cur.rowcount
    if deleted:
        print(f"\n[4] Removed existing certificate for demo.ready (fresh demo)")
    conn.commit()

    cur.close()
    conn.close()

    print("\n" + "="*55)
    print("  SEED COMPLETE")
    print("="*55)
    print()
    print("DEMO ACCOUNTS  (password for both: Demo1234!)")
    print("-" * 55)
    print("  Quiz fail + AI hints  :  demo.fail@powerwize.com")
    print("  Cert issuance (admin) :  demo.ready@powerwize.com")
    print()
    print("DEMO FLOW")
    print("-" * 55)
    print("  1. Register a new account (show registration form)")
    print("  2. Log in as demo.fail, go to LMS, take any quiz")
    print("     answer wrong, fail, click 'Generate Hints'")
    print("     AI (Groq) gives personalized study tips")
    print("  3. Log in as admin, go to /lms/certificates/manage")
    print("     issue certificate to 'Ready Trainee'")
    print("     NFT minted on Polygon Amoy in real time")
    print("  4. Show QR code / Polygonscan transaction")
    print()


if __name__ == "__main__":
    seed()
