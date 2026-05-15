"""
Seed comprehensive data into PowerWize database.
Run: python seed_all_data.py
"""
import random
from datetime import datetime, timedelta
from db import get_db, init_db

def seed_all():
    init_db()
    conn = get_db()
    cur = conn.cursor()

    print("\n" + "="*60)
    print("SEEDING POWERWIZE DATABASE")
    print("="*60)

    # Get all existing data first
    cur.execute("SELECT id FROM users WHERE role = 'employee'")
    employee_ids = [row[0] for row in cur.fetchall()]

    cur.execute("SELECT id FROM users WHERE role = 'trainee'")
    trainee_ids = [row[0] for row in cur.fetchall()]

    # ──────────────────────────────────────────────────────────────
    # 1. SEED LMS MODULES
    # ──────────────────────────────────────────────────────────────
    print("\n[LMS MODULES] Seeding modules...")

    modules = [
        ("Introduction to Solar Energy Systems", "Learn the basics of solar PV technology, components, and how they work.", "training", True),
        ("Solar System Design & Sizing", "Master the calculations and design considerations for residential and commercial systems.", "training", True),
        ("Electrical Safety in Solar Installation", "Critical safety protocols for working with solar electrical systems.", "training", True),
        ("Grid-Tie vs Off-Grid Systems", "Understand the differences between connected and standalone solar systems.", "training", True),
        ("Battery Storage & Backup Systems", "Explore battery technologies, sizing, and hybrid configurations.", "cea_training", True),
        ("Advanced Solar Economics & ROI", "Deep dive into cost analysis, financing, and return on investment calculations.", "cea_training", False),
        ("CEM Professional Certification Prep", "Comprehensive review for Certified Energy Manager certification exam.", "renewal", True),
        ("CEA Renewal: Latest Standards 2026", "Updated standards and regulations for Certified Energy Auditors.", "cea_renewal", True),
    ]

    module_ids = {}
    for i, (title, desc, training_type, is_published) in enumerate(modules):
        instructor_id = random.choice(employee_ids)
        cur.execute(
            "INSERT IGNORE INTO lms_modules (title, description, instructor_id, is_published, training_type) "
            "VALUES (%s, %s, %s, %s, %s)",
            (title, desc, instructor_id, is_published, training_type)
        )
        # Get the ID whether it was inserted or already existed
        cur.execute("SELECT id FROM lms_modules WHERE title = %s LIMIT 1", (title,))
        module_ids[i] = cur.fetchone()[0]
        print(f"  [OK] Module {i+1}: {title}")

    conn.commit()

    # ──────────────────────────────────────────────────────────────
    # 2. SEED LMS QUIZZES
    # ──────────────────────────────────────────────────────────────
    print("\n[QUIZZES] Seeding quizzes...")

    quizzes = [
        (module_ids[0], "Solar Basics Quiz", "Test your understanding of solar fundamentals", True),
        (module_ids[1], "System Design Challenge", "Apply design principles to real scenarios", True),
        (module_ids[2], "Safety Protocols Quiz", "Verify knowledge of electrical safety", True),
        (module_ids[3], "Grid vs Off-Grid Comparison", "Identify system advantages and trade-offs", True),
        (module_ids[4], "Battery Technology Quiz", "Understand battery specs and applications", False),
    ]

    quiz_ids = {}
    for i, (module_id, title, desc, published) in enumerate(quizzes):
        cur.execute(
            "INSERT IGNORE INTO lms_quizzes (module_id, title, description, is_published) "
            "VALUES (%s, %s, %s, %s)",
            (module_id, title, desc, published)
        )
        cur.execute("SELECT id FROM lms_quizzes WHERE module_id = %s LIMIT 1", (module_id,))
        quiz_ids[i] = cur.fetchone()[0]
        print(f"  [OK] Quiz {i+1}: {title}")

    conn.commit()

    # ──────────────────────────────────────────────────────────────
    # 3. SEED LMS QUIZ QUESTIONS
    # ──────────────────────────────────────────────────────────────
    print("\n[QUESTIONS] Seeding quiz questions...")

    questions_data = {
        0: [
            ("What does PV stand for?", "multiple_choice", "Photovoltaic"),
            ("Solar panels convert sunlight into:", "multiple_choice", "Electricity"),
            ("Name two main types of solar systems", "enumeration", "Grid-tie, Off-grid"),
        ],
        1: [
            ("What is the typical lifespan of a solar panel?", "multiple_choice", "25-30 years"),
            ("List three factors affecting system sizing", "enumeration", "Daily usage, climate, roof space"),
        ],
    }

    for quiz_idx, questions in questions_data.items():
        if quiz_idx not in quiz_ids:
            continue
        quiz_id = quiz_ids[quiz_idx]

        for q_idx, (text, qtype, correct) in enumerate(questions):
            cur.execute(
                "INSERT IGNORE INTO lms_quiz_questions (quiz_id, question_text, question_type, correct_answer) "
                "VALUES (%s, %s, %s, %s)",
                (quiz_id, text, qtype, correct)
            )
            print(f"  [OK] Q{quiz_idx+1}.{q_idx+1}: {text[:50]}...")

    conn.commit()

    # ──────────────────────────────────────────────────────────────
    # 4. SEED PRACTICAL EXAMS
    # ──────────────────────────────────────────────────────────────
    print("\n[EXAMS] Seeding practical exams...")

    exams = [
        (module_ids[0], "Solar Basics Practical Exam", "Design a simple 5kW residential system"),
        (module_ids[2], "Safety Compliance Exam", "Demonstrate proper safety procedures"),
        (module_ids[4], "Battery Design Exam", "Size a hybrid system with battery storage"),
    ]

    exam_ids = {}
    for i, (module_id, title, instructions) in enumerate(exams):
        cur.execute(
            "INSERT IGNORE INTO lms_practical_exams (module_id, title, instructions) "
            "VALUES (%s, %s, %s)",
            (module_id, title, instructions)
        )
        cur.execute("SELECT id FROM lms_practical_exams WHERE module_id = %s LIMIT 1", (module_id,))
        exam_ids[i] = cur.fetchone()[0]
        print(f"  [OK] Exam {i+1}: {title}")

    conn.commit()

    # ──────────────────────────────────────────────────────────────
    # 5. SEED QUIZ ATTEMPTS
    # ──────────────────────────────────────────────────────────────
    print("\n[ATTEMPTS] Seeding quiz attempts...")

    attempts_added = 0
    for quiz_idx in range(min(2, len(quiz_ids))):
        if quiz_idx not in quiz_ids:
            continue
        quiz_id = quiz_ids[quiz_idx]

        for trainee_id in random.sample(trainee_ids, min(3, len(trainee_ids))):
            attempt_date = datetime.now() - timedelta(days=random.randint(1, 30))
            score = random.randint(60, 100)
            cur.execute(
                "INSERT INTO lms_quiz_attempts (quiz_id, user_id, score, submitted_at, completed) "
                "VALUES (%s, %s, %s, %s, %s)",
                (quiz_id, trainee_id, score, attempt_date, 1)
            )
            attempts_added += 1

    conn.commit()
    print(f"  [OK] Added {attempts_added} quiz attempts")

    # ──────────────────────────────────────────────────────────────
    # 6. SEED SOLAR REQUESTS
    # ──────────────────────────────────────────────────────────────
    print("\n[SOLAR] Seeding solar requests...")

    statuses = ["submitted", "ai_processed", "pending_review", "reviewed"]
    feasibilities = ["feasible", "limited", "unfeasible", "unknown"]
    system_types = ["Grid-tie", "Hybrid", "Off-grid"]

    solar_added = 0
    for i in range(8):
        user_id = random.choice(trainee_ids)
        monthly_bill = random.randint(3000, 15000)
        kwh = monthly_bill / random.randint(10, 14)
        roof_sqm = random.randint(20, 100)
        system_kw = roof_sqm / 2.5

        cur.execute(
            "INSERT INTO solar_requests "
            "(user_id, name, address, email, contact, establishment_type, ownership, "
            "electrical_phase, monthly_bill_php, kwh_monthly, roof_sqm, system_size_kw, "
            "system_type, battery_recommended, feasibility, status) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (user_id, f"Client {i+1}", f"{i+1} Solar St, Manila", f"client{i+1}@email.com",
            f"09{random.randint(100000000, 999999999)}", random.choice(["residential", "commercial", "industrial"]),
            random.choice(["owned", "rented"]), random.choice(["single", "three"]),
            monthly_bill, kwh, roof_sqm, system_kw, random.choice(system_types), random.choice([0, 1]),
            random.choice(feasibilities), random.choice(statuses))
        )
        solar_added += 1

    conn.commit()
    print(f"  [OK] Added {solar_added} solar requests")

    # ──────────────────────────────────────────────────────────────
    # SUMMARY
    # ──────────────────────────────────────────────────────────────
    cur.close()
    conn.close()

    print("\n" + "="*60)
    print("[SUCCESS] DATABASE SEEDING COMPLETE!")
    print("="*60)
    print("\nData Seeded:")
    print(f"  - {len(modules)} LMS Modules")
    print(f"  - {len(quizzes)} Quizzes")
    print(f"  - 5 Quiz Questions (auto-gradable)")
    print(f"  - {len(exams)} Practical Exams")
    print(f"  - {attempts_added} Quiz Attempts")
    print(f"  - {solar_added} Solar Requests")
    print("\nLogin Credentials (from seed_users.py):")
    print("  Trainee: maria.santos@gmail.com / Test@1234")
    print("  Employee: roberto.delacruz@ewize.com / Test@1234")
    print("\n[COMPLETE] System ready to explore!\n")

if __name__ == "__main__":
    seed_all()
