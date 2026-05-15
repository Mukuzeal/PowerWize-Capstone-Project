"""
seed_demo.py — Full demo data seed for PowerWize screenshot walkthrough.

Run:  python seed_demo.py

Covers:
  - Users (trainee, employee, admin) via seed_users
  - Registrations (30 fake records) via seed_registrations
  - LMS: module + published quiz with 5 MC questions + choices
  - Failed quiz attempt (Maria Santos, score=40) with tracked wrong answers  ← AI Hints
  - Passed quiz attempt (Miguel Torres, score=80) → module completed
  - Certificate issued to Miguel Torres
  - Payments for trainees
  - Module feedback (star ratings)
  - Audit log entries
  - Solar requests
"""
import secrets
from datetime import datetime, date, timedelta
from werkzeug.security import generate_password_hash
from db import get_db, init_db

# ── helpers ────────────────────────────────────────────────────────────────────

def _get_user(cur, email):
    cur.execute("SELECT id, fname, lname FROM users WHERE email=%s", (email,))
    return cur.fetchone()


def _ensure_user(cur, conn, role, fname, lname, email, password="Test@1234",
                 contact="09171234599", company="PowerWize", training_type=None):
    row = _get_user(cur, email)
    if row:
        return row[0]
    cur.execute(
        "INSERT INTO users (role,fname,lname,email,password_hash,contact_number,company_name,"
        "payment_status,training_type) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (role, fname, lname, email, generate_password_hash(password),
         contact, company, "paid" if role != "trainee" else "paid", training_type)
    )
    conn.commit()
    return cur.lastrowid


def _ensure_module(cur, conn, title, desc, instructor_id, training_type="training"):
    cur.execute("SELECT id FROM lms_modules WHERE title=%s LIMIT 1", (title,))
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute(
        "INSERT INTO lms_modules (title,description,instructor_id,is_published,training_type) "
        "VALUES (%s,%s,%s,1,%s)",
        (title, desc, instructor_id, training_type)
    )
    conn.commit()
    return cur.lastrowid


def _ensure_quiz(cur, conn, module_id, title):
    cur.execute("SELECT id FROM lms_quizzes WHERE module_id=%s LIMIT 1", (module_id,))
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute(
        "INSERT INTO lms_quizzes (module_id,title,description,passing_score,is_published) "
        "VALUES (%s,%s,%s,70,1)",
        (module_id, title, "Test your solar PV knowledge.")
    )
    conn.commit()
    return cur.lastrowid


def _add_mc_question(cur, conn, quiz_id, text, choices, correct_idx, order_num=0):
    """Insert one MC question with choices. correct_idx is 0-based."""
    cur.execute("SELECT id FROM lms_quiz_questions WHERE quiz_id=%s AND question_text=%s LIMIT 1",
                (quiz_id, text))
    row = cur.fetchone()
    if row:
        return row[0], []
    cur.execute(
        "INSERT INTO lms_quiz_questions (quiz_id,question_text,question_type,order_num,points) "
        "VALUES (%s,%s,'multiple_choice',%s,1)",
        (quiz_id, text, order_num)
    )
    conn.commit()
    q_id = cur.lastrowid
    choice_ids = []
    for i, c_text in enumerate(choices):
        cur.execute(
            "INSERT INTO lms_quiz_choices (question_id,choice_text,is_correct) VALUES (%s,%s,%s)",
            (q_id, c_text, 1 if i == correct_idx else 0)
        )
        conn.commit()
        choice_ids.append(cur.lastrowid)
    return q_id, choice_ids


def _wrong_choice_id(cur, question_id):
    """Return the id of one wrong choice for a question."""
    cur.execute(
        "SELECT id FROM lms_quiz_choices WHERE question_id=%s AND is_correct=0 LIMIT 1",
        (question_id,)
    )
    row = cur.fetchone()
    return row[0] if row else None


def _correct_choice_id(cur, question_id):
    cur.execute(
        "SELECT id FROM lms_quiz_choices WHERE question_id=%s AND is_correct=1 LIMIT 1",
        (question_id,)
    )
    row = cur.fetchone()
    return row[0] if row else None


def seed_demo():
    init_db()
    conn = get_db()
    cur  = conn.cursor()

    print("\n" + "="*60)
    print(" POWERWIZE DEMO SEED")
    print("="*60)

    # ── 1. Users ───────────────────────────────────────────────────────────────
    print("\n[1] Users...")
    import seed_users
    seed_users.main()

    # Ensure key demo users exist and grab their IDs
    admin_id    = _ensure_user(cur, conn, "admin",    "System", "Administrator", "admin@ewize.com")
    employee_id = _ensure_user(cur, conn, "employee", "Roberto", "Dela Cruz", "roberto.delacruz@ewize.com")
    maria_id    = _ensure_user(cur, conn, "trainee",  "Maria",   "Santos",    "maria.santos@gmail.com",  training_type="training")
    miguel_id   = _ensure_user(cur, conn, "trainee",  "Miguel",  "Torres",    "miguel.torres@gmail.com", training_type="training")
    grace_id    = _ensure_user(cur, conn, "trainee",  "Grace",   "Lim",       "grace.lim@gmail.com",     training_type="cea_training")
    print(f"  admin={admin_id}  employee={employee_id}  maria={maria_id}  miguel={miguel_id}  grace={grace_id}")

    # ── 2. Registrations ──────────────────────────────────────────────────────
    print("\n[2] Registrations...")
    import seed_registrations
    seed_registrations.seed(30)

    # ── 3. LMS Module ─────────────────────────────────────────────────────────
    print("\n[3] LMS Module...")
    mod_id = _ensure_module(
        cur, conn,
        "Introduction to Solar Energy Systems",
        "Learn the basics of solar PV technology, components, and how they work together in a complete system.",
        instructor_id=employee_id,
        training_type="training"
    )
    print(f"  module_id={mod_id}")

    # ── 4. Quiz + 5 MC Questions ──────────────────────────────────────────────
    print("\n[4] Quiz + Questions...")
    quiz_id = _ensure_quiz(cur, conn, mod_id, "Solar Basics Quiz")
    print(f"  quiz_id={quiz_id}")

    questions = [
        ("What does 'PV' stand for in solar PV systems?",
         ["Pressure Voltage", "Photovoltaic", "Power Variation", "Phase Voltage"], 1),
        ("Which component converts DC electricity from solar panels to AC for home use?",
         ["Charge controller", "Battery bank", "Inverter", "Junction box"], 2),
        ("What is the typical lifespan of a quality solar panel?",
         ["5–10 years", "10–15 years", "15–20 years", "25–30 years"], 3),
        ("Which type of solar system remains connected to the utility grid?",
         ["Off-grid system", "Grid-tie system", "Standalone system", "Hybrid island system"], 1),
        ("What unit is used to measure the capacity of a solar panel?",
         ["Kilowatt-hour (kWh)", "Ampere (A)", "Watt-peak (Wp)", "Volt (V)"], 2),
    ]

    q_ids = []
    for i, (text, choices, correct_idx) in enumerate(questions):
        q_id, _ = _add_mc_question(cur, conn, quiz_id, text, choices, correct_idx, order_num=i)
        q_ids.append(q_id)
        print(f"  Q{i+1}: {text[:55]}... (correct idx={correct_idx})")

    # ── 5. Failed attempt — Maria Santos (score 40, AI hints target) ──────────
    print("\n[5] Failed attempt (Maria, score=40)...")
    cur.execute("SELECT id FROM lms_quiz_attempts WHERE user_id=%s AND quiz_id=%s LIMIT 1",
                (maria_id, quiz_id))
    if cur.fetchone():
        print("  already exists, skipping")
    else:
        cur.execute(
            "INSERT INTO lms_quiz_attempts (user_id,quiz_id,started_at,submitted_at,score,completed) "
            "VALUES (%s,%s,%s,%s,40.00,1)",
            (maria_id, quiz_id,
             datetime.now() - timedelta(hours=2),
             datetime.now() - timedelta(hours=1))
        )
        conn.commit()
        attempt_id = cur.lastrowid
        print(f"  attempt_id={attempt_id}")

        # Record answers: get 2 right, get 3 wrong (score 40%)
        for i, q_id in enumerate(q_ids):
            if i < 2:  # first 2 correct
                choice_id = _correct_choice_id(cur, q_id)
            else:      # last 3 wrong
                choice_id = _wrong_choice_id(cur, q_id)
            if choice_id:
                cur.execute(
                    "INSERT INTO lms_quiz_answers (attempt_id,question_id,selected_choice_id) "
                    "VALUES (%s,%s,%s)",
                    (attempt_id, q_id, choice_id)
                )
        conn.commit()
        print(f"  {len(q_ids)} answers recorded (2 correct, 3 wrong)")

    # Progress row for Maria (failed)
    cur.execute(
        "INSERT INTO lms_progress (user_id,module_id,quiz_score,quiz_passed,completed) "
        "VALUES (%s,%s,40.00,0,0) ON DUPLICATE KEY UPDATE quiz_score=40.00, quiz_passed=0, completed=0",
        (maria_id, mod_id)
    )
    conn.commit()

    # ── 6. Passed attempt — Miguel Torres (score 80, completed) ──────────────
    print("\n[6] Passed attempt (Miguel, score=80)...")
    cur.execute("SELECT id FROM lms_quiz_attempts WHERE user_id=%s AND quiz_id=%s LIMIT 1",
                (miguel_id, quiz_id))
    if cur.fetchone():
        print("  already exists, skipping")
    else:
        cur.execute(
            "INSERT INTO lms_quiz_attempts (user_id,quiz_id,started_at,submitted_at,score,completed) "
            "VALUES (%s,%s,%s,%s,80.00,1)",
            (miguel_id, quiz_id,
             datetime.now() - timedelta(days=5, hours=2),
             datetime.now() - timedelta(days=5, hours=1))
        )
        conn.commit()
        attempt_id_m = cur.lastrowid
        for q_id in q_ids:
            choice_id = _correct_choice_id(cur, q_id)
            if choice_id:
                cur.execute(
                    "INSERT INTO lms_quiz_answers (attempt_id,question_id,selected_choice_id) "
                    "VALUES (%s,%s,%s)",
                    (attempt_id_m, q_id, choice_id)
                )
        conn.commit()
        print(f"  attempt_id={attempt_id_m}, all correct")

    completed_at = datetime.now() - timedelta(days=5)
    cur.execute(
        "INSERT INTO lms_progress (user_id,module_id,quiz_score,quiz_passed,completed,completed_at) "
        "VALUES (%s,%s,80.00,1,1,%s) ON DUPLICATE KEY UPDATE "
        "quiz_score=80.00, quiz_passed=1, completed=1, completed_at=%s",
        (miguel_id, mod_id, completed_at, completed_at)
    )
    conn.commit()
    print("  progress: completed")

    # ── 7. Certificate for Miguel ─────────────────────────────────────────────
    print("\n[7] Certificate (Miguel)...")
    cur.execute("SELECT id FROM lms_certificates WHERE user_id=%s LIMIT 1", (miguel_id,))
    if cur.fetchone():
        print("  already exists, skipping")
    else:
        cert_id   = secrets.token_hex(16)
        issued    = date.today() - timedelta(days=5)
        expires   = date(issued.year + 3, issued.month, issued.day)
        tx_hash   = "0x" + secrets.token_hex(32)
        cur.execute(
            "INSERT INTO lms_certificates (user_id,cert_id,approved_by,issued_at,expires_at,tx_hash) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            (miguel_id, cert_id, employee_id, issued, expires, tx_hash)
        )
        conn.commit()
        print(f"  cert_id={cert_id}")
        print(f"  expires={expires}, tx_hash={tx_hash[:20]}…")

    # ── 8. Payments ───────────────────────────────────────────────────────────
    print("\n[8] Payments...")
    import random
    payment_users = [
        (maria_id,  12000.00, "qrph"),
        (miguel_id, 12000.00, "card"),
        (grace_id,  18000.00, "qrph"),
    ]
    for uid, amount, method in payment_users:
        cur.execute("SELECT id FROM payments WHERE user_id=%s LIMIT 1", (uid,))
        if cur.fetchone():
            print(f"  user {uid} payment already exists, skip")
            continue
        paid_at = datetime.now() - timedelta(days=random.randint(10, 30))
        cur.execute(
            "INSERT INTO payments (user_id,amount_php,method,paymongo_id,status,paid_at) "
            "VALUES (%s,%s,%s,%s,'paid',%s)",
            (uid, amount, method, "pm_" + secrets.token_hex(8), paid_at)
        )
    # Add some extra historical payments with different months for chart
    from datetime import date as ddate
    extra_payments = [
        (maria_id,  8500.00, "card",  90),
        (grace_id,  18000.00, "qrph", 60),
        (miguel_id, 12000.00, "qrph", 45),
        (maria_id,  12000.00, "card", 30),
        (grace_id,  8500.00,  "card", 20),
        (miguel_id, 18000.00, "qrph", 15),
    ]
    for uid, amount, method, days_ago in extra_payments:
        paid_at = datetime.now() - timedelta(days=days_ago)
        cur.execute(
            "INSERT INTO payments (user_id,amount_php,method,paymongo_id,status,paid_at) "
            "VALUES (%s,%s,%s,%s,'paid',%s)",
            (uid, amount, method, "pm_" + secrets.token_hex(8), paid_at)
        )
    conn.commit()
    print("  payments seeded")

    # ── 9. Module Feedback ────────────────────────────────────────────────────
    print("\n[9] Feedback...")
    feedbacks = [
        (miguel_id, mod_id, 5, "Excellent module! The content was clear and well-structured."),
        (grace_id,  mod_id, 4, "Very informative. Would love more practical examples."),
        (maria_id,  mod_id, 3, "Good content but the quiz was challenging."),
    ]
    for uid, mid, rating, comment in feedbacks:
        cur.execute(
            "INSERT INTO feedback (user_id,module_id,rating,comment) VALUES (%s,%s,%s,%s) "
            "ON DUPLICATE KEY UPDATE rating=%s, comment=%s",
            (uid, mid, rating, comment, rating, comment)
        )
    conn.commit()
    print("  feedback seeded")

    # ── 10. Audit Logs ────────────────────────────────────────────────────────
    print("\n[10] Audit logs...")
    logs = [
        (admin_id,    "issue_certificate",  "certificate", miguel_id,  "Certificate issued to Miguel Torres"),
        (admin_id,    "update_status",      "registration", None,      "Registration status changed to accepted"),
        (employee_id, "export_report",      "report",       None,      "Exported registrations report (Excel)"),
        (admin_id,    "archive_user",       "user",         grace_id,  "Archived user grace.lim@gmail.com"),
        (admin_id,    "unarchive_user",     "user",         grace_id,  "Restored user grace.lim@gmail.com"),
        (employee_id, "export_report",      "report",       None,      "Exported payments report (Excel)"),
        (admin_id,    "update_status",      "registration", None,      "Registration status changed to rejected"),
    ]
    for uid, action, entity_type, entity_id, details in logs:
        ts = datetime.now() - timedelta(minutes=random.randint(5, 1440))
        cur.execute(
            "INSERT INTO audit_logs (user_id,action,entity_type,entity_id,details,created_at) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            (uid, action, entity_type, entity_id, details, ts)
        )
    conn.commit()
    print("  audit logs seeded")

    # ── 11. Solar Requests ────────────────────────────────────────────────────
    print("\n[11] Solar requests...")
    solar_data = [
        (maria_id, "Maria Santos",   "123 Malate St, Manila",        "residential", "feasible",   "ai_processed",
         8500, 680, 35, 14.0, "Grid-tie", 0),
        (miguel_id, "Miguel Torres", "456 BGC Ave, Taguig",          "commercial",  "limited",    "reviewed",
         25000, 2000, 80, 32.0, "Hybrid", 1),
        (grace_id, "Grace Lim",      "789 Ortigas Center, Pasig",    "commercial",  "feasible",   "pending_review",
         18000, 1440, 60, 24.0, "Grid-tie", 0),
        (None, "Carlos Bautista",    "321 Quezon Ave, QC",           "residential", "unfeasible", "submitted",
         3500, 280, 15, 6.0, "Off-grid", 0),
        (None, "Ana Reyes",          "654 Pasay Rd, Pasay",          "industrial",  "feasible",   "quotation_sent",
         50000, 4000, 200, 80.0, "Grid-tie", 0),
    ]
    for row in solar_data:
        uid, name, addr, etype, feas, status, bill, kwh, roof, kw, stype, batt = row
        cur.execute(
            "INSERT INTO solar_requests "
            "(user_id,name,address,email,contact,establishment_type,ownership,electrical_phase,"
            "monthly_bill_php,kwh_monthly,roof_sqm,system_size_kw,system_type,battery_recommended,"
            "feasibility,status,target_savings) "
            "VALUES (%s,%s,%s,%s,%s,%s,'owned','single',%s,%s,%s,%s,%s,%s,%s,%s,'100')",
            (uid, name, addr, f"{name.split()[0].lower()}@demo.com", "09171234999",
             etype, bill, kwh, roof, kw, stype, batt, feas, status)
        )
    conn.commit()
    print("  solar requests seeded")

    cur.close()
    conn.close()

    print("\n" + "="*60)
    print(" DEMO SEED COMPLETE!")
    print("="*60)
    print("\nLOGIN CREDENTIALS (all passwords: Test@1234)")
    print("-" * 45)
    print("  Admin    :  admin@ewize.com")
    print("  Employee :  roberto.delacruz@ewize.com")
    print("  Trainee  :  maria.santos@gmail.com   <- failed quiz (AI hints demo)")
    print("  Trainee  :  miguel.torres@gmail.com  <- passed + has certificate")
    print("  Trainee  :  grace.lim@gmail.com      <- has solar request")
    print("\nSCREENSHOT FLOW")
    print("-" * 45)
    print("  1. maria.santos  -> /lms/learn -> Solar module -> Generate Hints")
    print("  2. miguel.torres -> /lms/certificates -> cert with QR")
    print("  3. admin         -> /admin -> Analytics, Exports, Feedback, Audit Log")
    print("  4. maria.santos  -> /solar -> solar consultation")


if __name__ == "__main__":
    seed_demo()
