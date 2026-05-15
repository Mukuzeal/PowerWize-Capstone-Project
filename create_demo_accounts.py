#!/usr/bin/env python
"""Create demo accounts for screen recording."""
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, 'src')

from db import get_db
from werkzeug.security import generate_password_hash

def create_demo_accounts():
    conn = get_db()
    cur = conn.cursor()

    try:
        # 1. ADMIN ACCOUNT
        admin_email = "admin@energywize.demo"
        admin_pass = "Admin@123"
        admin_hash = generate_password_hash(admin_pass)

        # Check if admin exists
        cur.execute("SELECT id FROM users WHERE email = %s", (admin_email,))
        if cur.fetchone():
            print(f"[OK] Admin account already exists: {admin_email}")
        else:
            cur.execute("""
                INSERT INTO users (email, password_hash, fname, lname, role)
                VALUES (%s, %s, %s, %s, %s)
            """, (admin_email, admin_hash, "Admin", "Demo", "admin"))
            conn.commit()
            print(f"[OK] Created admin: {admin_email}")

        # 2. APPROVED TRAINEE (CEM) - can log into LMS
        trainee_email = "trainee@energywize.demo"
        trainee_pass = "Trainee@123"
        trainee_hash = generate_password_hash(trainee_pass)

        cur.execute("SELECT id FROM users WHERE email = %s", (trainee_email,))
        trainee = cur.fetchone()

        if trainee:
            print(f"[OK] Approved trainee account already exists: {trainee_email}")
            trainee_id = trainee[0]
        else:
            cur.execute("""
                INSERT INTO users (email, password_hash, fname, lname, role)
                VALUES (%s, %s, %s, %s, %s)
            """, (trainee_email, trainee_hash, "Maria", "Santos", "trainee"))
            conn.commit()

            # Get the inserted user_id
            cur.execute("SELECT id FROM users WHERE email = %s", (trainee_email,))
            trainee_id = cur.fetchone()[0]
            print(f"[OK] Created approved trainee: {trainee_email}")


        print("\n" + "="*60)
        print("DEMO ACCOUNTS READY")
        print("="*60)
        print("\n[ADMIN ACCOUNT]")
        print("  Email: admin@energywize.demo")
        print("  Password: Admin@123")
        print("  Role: Administrator")
        print("  Access: /admin dashboard, approvals, exports")

        print("\n[APPROVED TRAINEE - Can log into LMS]")
        print("  Email: trainee@energywize.demo")
        print("  Password: Trainee@123")
        print("  Role: Trainee (already has access to LMS)")
        print("  Status: Ready to view courses and take quizzes")

        print("\n" + "="*60)
        print("\nUSAGE FOR SCREEN RECORDING:")
        print("1. Demo registration forms by visiting http://localhost:5000/")
        print("2. Fill out a new CEM/CEA registration form to show validation")
        print("3. Admin login (admin@energywize.demo) to approve pending registrations")
        print("4. Trainee login (trainee@energywize.demo) to demo LMS features")
        print("\n" + "="*60)

    except Exception as e:
        print(f"[ERROR] {e}")
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    create_demo_accounts()
