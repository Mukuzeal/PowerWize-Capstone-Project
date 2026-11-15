r"""Add an isolated paid company training demo locally, without sending mail.

Run from the repository root: venv\Scripts\python scripts/seed_company_tracking.py
Existing demo batches are preserved on subsequent runs. SEED_PASSWORD optionally
sets the initial trainee password; otherwise accounts get random passwords.
Paid invoices and learning results are synthetic presentation data.
"""
import os
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from werkzeug.security import generate_password_hash
from db import get_db
from db.classes import class_instructors
from pricing import calculate_fee
from _guard import require_local_db

DELIVERY = 'Online, 7 days, 56 hours'


def main():
    require_local_db()
    instructors = class_instructors()
    if not instructors:
        raise RuntimeError('An active training instructor is required.')
    trainer = instructors[0]['id']
    fee = calculate_fee('training', DELIVERY)['total']
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE role='admin' AND archived_at IS NULL ORDER BY id LIMIT 1")
            admin = cur.fetchone()[0]
            cur.execute("SELECT id FROM lms_modules WHERE training_type='training' AND is_published=1 AND archived_at IS NULL ORDER BY sort_order,id")
            modules = [r[0] for r in cur.fetchall()]
            if not modules:
                raise RuntimeError('Published CEM modules are required.')
            for tag, company, statuses in [
                ('training', 'DEMO - Solara Industries (Training Progress)',
                 ['accepted'] * 4),
            ]:
                cur.execute('SELECT id FROM corporate_intakes WHERE company_name=%s', (company,))
                existing = cur.fetchone()
                if existing:
                    print(f'Preserved existing batch: {company}, intake #{existing[0]}')
                    continue
                cur.execute("""INSERT INTO corporate_intakes(company_name,contact_person,contact_email,
                    form_type,training_type,created_by) VALUES(%s,'Demo Coordinator',%s,'training',%s,%s)
                    RETURNING id""", (company, f'coordinator.{tag}@solara-demo.test', DELIVERY, admin))
                intake = cur.fetchone()[0]
                cur.execute("""INSERT INTO training_classes(name,training_type,program_code,intake_id,
                    join_code,instructor_id,created_by) VALUES(%s,%s,'training',%s,%s,%s,%s) RETURNING id""",
                    (company, DELIVERY, intake, secrets.token_hex(4).upper(), trainer, admin))
                cls = cur.fetchone()[0]
                people = []
                for i, status in enumerate(statuses):
                    first = ['Ana', 'Ben', 'Carla', 'Diego', 'Elena'][i]
                    name = first + ' Demo'
                    email = f'{first.lower()}.{tag}@solara-demo.test'
                    reg = None
                    uid = None
                    if status:
                        reg = secrets.token_hex(4).upper()
                        approved = status == 'accepted'
                        cur.execute("""INSERT INTO registrations(id,form_type,form_label,submitted_at,
                            full_name,email,company_name,training_type,status,is_qualified,
                            selfie_reviewed_at,selfie_outcome,documents_purged_at,correction_note)
                            VALUES(%s,'training','CEM Training',NOW(),%s,%s,%s,%s,%s,1,
                            CASE WHEN %s THEN NOW() ELSE NULL END,%s,CASE WHEN %s THEN NOW() ELSE NULL END,%s)""",
                            (reg, name, email, company, DELIVERY, status, approved,
                             'approved' if approved else None, approved,
                             'Demo: Please submit a clearer copy of your valid ID.' if status == 'needs_correction' else None))
                        # The review demo includes one approved account still awaiting activation.
                        if approved and (tag == 'training' or i == 4):
                            cur.execute("""INSERT INTO users(role,fname,lname,email,password_hash,
                                company_name,payment_status,training_type,registration_id)
                                VALUES('trainee',%s,'Demo',%s,%s,%s,%s,'training',%s) RETURNING id""",
                                (first, email, generate_password_hash(os.getenv('SEED_PASSWORD') or secrets.token_urlsafe(32)),
                                 company, 'paid' if tag == 'training' else 'unpaid', reg))
                            uid = cur.fetchone()[0]
                            cur.execute('INSERT INTO trainee_enrolments(registration_id,user_id) VALUES(%s,%s)', (reg, uid))
                    cur.execute("""INSERT INTO corporate_intake_slots(intake_id,full_name,email,email_key,
                        registration_id) VALUES(%s,%s,%s,%s,%s)""", (intake, name, email, email, reg))
                    people.append((uid, reg, name))
                if tag == 'training':
                    total = fee * len(people)
                    reference = 'DEMO-TRACK-' + secrets.token_hex(4).upper()
                    cur.execute("""INSERT INTO corporate_payments(reference,company_name,contact_person,
                        contact_email,list_total_php,amount_centavos,status,expires_at,paid_at,created_by,intake_id)
                        VALUES(%s,%s,'Demo Coordinator',%s,%s,%s,'paid',NOW()+INTERVAL '30 days',NOW(),%s,%s)
                        RETURNING id""", (reference, company, f'coordinator.{tag}@solara-demo.test',
                                             total, int(total * 100), admin, intake))
                    invoice = cur.fetchone()[0]
                    cur.execute('UPDATE training_classes SET corporate_payment_id=%s WHERE id=%s', (invoice, cls))
                    for i, (uid, reg, name) in enumerate(people):
                        cur.execute("""INSERT INTO corporate_payment_items(corporate_payment_id,user_id,
                            training_type,form_type,price_php,price_label,registration_id,trainee_name,trainee_email)
                            SELECT %s,id,%s,'training',%s,'Demo CEM online',%s,%s,email FROM users WHERE id=%s""",
                            (invoice, DELIVERY, fee, reg, name, uid))
                        # Fourth trainee has paid but has not joined yet.
                        if i == 3:
                            continue
                        cur.execute('INSERT INTO training_class_members(class_id,user_id) VALUES(%s,%s)', (cls, uid))
                        completed = [len(modules), max(1, len(modules) // 2), 0][i]
                        for j, module in enumerate(modules):
                            done = int(j < completed)
                            cur.execute("""INSERT INTO lms_progress(user_id,module_id,registration_id,
                                quiz_score,quiz_passed,exam_graded,exam_grade,material_pct,completed,completed_at)
                                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,CASE WHEN %s=1 THEN NOW() ELSE NULL END)""",
                                (uid,module,reg,90 if done else None,done,done,90 if done else None,
                                 100 if done else 0,done,done))
                print(f'Created {company}: intake #{intake}, class #{cls}, {len(people)} expected trainees')
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    print(f'Assigned instructor ID: {trainer}. No emails sent or real payments processed.')


if __name__ == '__main__':
    main()
