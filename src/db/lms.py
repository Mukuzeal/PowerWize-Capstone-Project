import psycopg2.extras

from .core import get_db


def lms_create_module(instructor_id, title, description, training_type="training"):
    conn = get_db(); cur = conn.cursor()
    cur.execute(
        "INSERT INTO lms_modules (instructor_id,title,description,training_type) VALUES (%s,%s,%s,%s) RETURNING id",
        (instructor_id, title, description, training_type)
    )
    conn.commit(); mid = cur.fetchone()[0]; cur.close(); conn.close()
    return mid


def lms_get_modules(instructor_id=None, published_only=False):
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if instructor_id:
        cur.execute("""SELECT m.*,u.fname,u.lname FROM lms_modules m
                       JOIN users u ON m.instructor_id=u.id
                       WHERE m.instructor_id=%s AND m.archived_at IS NULL
                       ORDER BY m.created_at DESC""", (instructor_id,))
    elif published_only:
        cur.execute("""SELECT m.*,u.fname,u.lname FROM lms_modules m
                       JOIN users u ON m.instructor_id=u.id
                       WHERE m.is_published=1 AND m.archived_at IS NULL
                       ORDER BY m.created_at DESC""")
    else:
        cur.execute("""SELECT m.*,u.fname,u.lname FROM lms_modules m
                       JOIN users u ON m.instructor_id=u.id
                       WHERE m.archived_at IS NULL ORDER BY m.created_at DESC""")
    rows = cur.fetchall(); cur.close(); conn.close()
    return [dict(r) for r in rows]


def lms_get_modules_with_counts(archived=False):
    """Modules (active or archived) with quiz/exam counts, for the admin dashboard."""
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(f"""
        SELECT m.*, u.fname, u.lname,
               COUNT(DISTINCT q.id) as quiz_count,
               COUNT(DISTINCT e.id) as exam_count
        FROM lms_modules m
        LEFT JOIN users u ON m.instructor_id = u.id
        LEFT JOIN lms_quizzes q ON m.id = q.module_id
        LEFT JOIN lms_practical_exams e ON m.id = e.module_id
        WHERE m.archived_at IS {'NOT NULL' if archived else 'NULL'}
        GROUP BY m.id, u.id, u.fname, u.lname
        ORDER BY m.{'archived_at' if archived else 'created_at'} DESC
    """)
    rows = cur.fetchall(); cur.close(); conn.close()
    return [dict(r) for r in rows]


def lms_get_module(module_id):
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""SELECT m.*,u.fname,u.lname FROM lms_modules m
                   JOIN users u ON m.instructor_id=u.id WHERE m.id=%s""", (module_id,))
    row = cur.fetchone(); cur.close(); conn.close()
    return dict(row) if row else None


def get_user_training_type(user_id):
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        "SELECT form_type, training_type FROM registrations "
        "WHERE email=(SELECT email FROM users WHERE id=%s) ORDER BY submitted_at DESC LIMIT 1",
        (user_id,)
    )
    row = cur.fetchone(); cur.close(); conn.close()
    if not row:
        return 'training'

    form_type = row.get('form_type', '') or ''
    if form_type == 'gemp_lgu':
        return 'gemp_lgu'
    if form_type == 'gemp_oge':
        return 'gemp_oge'

    reg_type = (row.get('training_type') or '').lower()
    if 'cea' in reg_type and 'renewal' in reg_type:
        return 'cea_renewal'
    elif 'cem' in reg_type and 'renewal' in reg_type:
        return 'cem_renewal'
    elif 'cea' in reg_type:
        return 'cea_training'
    elif 'renewal' in reg_type:
        return 'renewal'
    else:
        return 'training'


def lms_get_modules_for_trainee(user_id, published_only=True):
    training_type = get_user_training_type(user_id)
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if published_only:
        cur.execute("""SELECT m.*,u.fname,u.lname FROM lms_modules m
                       JOIN users u ON m.instructor_id=u.id
                       WHERE m.is_published=1 AND m.training_type=%s ORDER BY m.created_at DESC""", (training_type,))
    else:
        cur.execute("""SELECT m.*,u.fname,u.lname FROM lms_modules m
                       JOIN users u ON m.instructor_id=u.id
                       WHERE m.training_type=%s ORDER BY m.created_at DESC""", (training_type,))
    rows = cur.fetchall(); cur.close(); conn.close()
    return [dict(r) for r in rows]


def lms_update_module(module_id, title, description, training_type=None):
    conn = get_db(); cur = conn.cursor()
    if training_type:
        cur.execute("UPDATE lms_modules SET title=%s,description=%s,training_type=%s WHERE id=%s",
                    (title, description, training_type, module_id))
    else:
        cur.execute("UPDATE lms_modules SET title=%s,description=%s WHERE id=%s",
                    (title, description, module_id))
    conn.commit(); cur.close(); conn.close()


def lms_toggle_publish(module_id, published):
    conn = get_db(); cur = conn.cursor()
    cur.execute("UPDATE lms_modules SET is_published=%s WHERE id=%s", (1 if published else 0, module_id))
    conn.commit(); cur.close(); conn.close()


def lms_add_file(module_id, filename, original_name, file_type, file_size):
    conn = get_db(); cur = conn.cursor()
    cur.execute(
        "INSERT INTO lms_module_files (module_id,filename,original_name,file_type,file_size) VALUES (%s,%s,%s,%s,%s) RETURNING id",
        (module_id, filename, original_name, file_type, file_size)
    )
    conn.commit(); fid = cur.fetchone()[0]; cur.close(); conn.close()
    return fid


def lms_get_files(module_id):
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM lms_module_files WHERE module_id=%s ORDER BY uploaded_at", (module_id,))
    rows = cur.fetchall(); cur.close(); conn.close()
    return [dict(r) for r in rows]


def lms_get_file(file_id):
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM lms_module_files WHERE id=%s", (file_id,))
    row = cur.fetchone(); cur.close(); conn.close()
    return dict(row) if row else None


def lms_delete_file(file_id):
    conn = get_db(); cur = conn.cursor()
    cur.execute("DELETE FROM lms_module_files WHERE id=%s", (file_id,))
    conn.commit(); cur.close(); conn.close()


def lms_save_quiz(module_id, title, description, time_limit, passing_score, is_ai_generated=False):
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        INSERT INTO lms_quizzes (module_id,title,description,time_limit_mins,passing_score,is_ai_generated)
        VALUES (%s,%s,%s,%s,%s,%s)
        ON CONFLICT (module_id) DO UPDATE SET
            title=EXCLUDED.title,
            description=EXCLUDED.description,
            time_limit_mins=EXCLUDED.time_limit_mins,
            passing_score=EXCLUDED.passing_score
        RETURNING id
    """, (module_id, title, description, time_limit, passing_score, 1 if is_ai_generated else 0))
    conn.commit()
    qid = cur.fetchone()[0]; cur.close(); conn.close()
    return qid


def lms_get_quiz(module_id=None, quiz_id=None):
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if module_id:
        cur.execute("SELECT * FROM lms_quizzes WHERE module_id=%s", (module_id,))
    else:
        cur.execute("SELECT * FROM lms_quizzes WHERE id=%s", (quiz_id,))
    row = cur.fetchone(); cur.close(); conn.close()
    return dict(row) if row else None


def lms_save_questions(quiz_id, questions):
    lms_save_quiz_questions(quiz_id, questions)


def lms_get_questions(quiz_id):
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM lms_quiz_questions WHERE quiz_id=%s ORDER BY order_num", (quiz_id,))
    questions = [dict(q) for q in cur.fetchall()]
    for q in questions:
        cur.execute("SELECT * FROM lms_quiz_choices WHERE question_id=%s", (q["id"],))
        q["choices"] = [dict(c) for c in cur.fetchall()]
    cur.close(); conn.close()
    return questions


def lms_publish_quiz(quiz_id, published):
    conn = get_db(); cur = conn.cursor()
    cur.execute("UPDATE lms_quizzes SET is_published=%s WHERE id=%s", (1 if published else 0, quiz_id))
    conn.commit(); cur.close(); conn.close()


def lms_save_exam(module_id, title, instructions, criteria, requires_camera=False):
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        INSERT INTO lms_practical_exams (module_id,title,instructions,evaluation_criteria,requires_camera)
        VALUES (%s,%s,%s,%s,%s)
        ON CONFLICT (module_id) DO UPDATE SET
            title=EXCLUDED.title,
            instructions=EXCLUDED.instructions,
            evaluation_criteria=EXCLUDED.evaluation_criteria,
            requires_camera=EXCLUDED.requires_camera
    """, (module_id, title, instructions, criteria, 1 if requires_camera else 0))
    conn.commit(); cur.close(); conn.close()


def lms_get_exam(module_id=None, exam_id=None):
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if module_id:
        cur.execute("SELECT * FROM lms_practical_exams WHERE module_id=%s", (module_id,))
    else:
        cur.execute("SELECT * FROM lms_practical_exams WHERE id=%s", (exam_id,))
    row = cur.fetchone(); cur.close(); conn.close()
    return dict(row) if row else None


def lms_start_attempt(user_id, quiz_id):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT id FROM lms_quiz_attempts WHERE user_id=%s AND quiz_id=%s AND completed=0",
                (user_id, quiz_id))
    existing = cur.fetchone()
    if existing:
        cur.close(); conn.close()
        return existing[0]
    cur.execute("INSERT INTO lms_quiz_attempts (user_id,quiz_id) VALUES (%s,%s) RETURNING id", (user_id, quiz_id))
    conn.commit(); aid = cur.fetchone()[0]; cur.close(); conn.close()
    return aid


def lms_record_tab_switch(attempt_id):
    conn = get_db(); cur = conn.cursor()
    cur.execute("UPDATE lms_quiz_attempts SET tab_switches=tab_switches+1 WHERE id=%s", (attempt_id,))
    conn.commit(); cur.close(); conn.close()


def lms_get_attempt(attempt_id):
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM lms_quiz_attempts WHERE id=%s", (attempt_id,))
    row = cur.fetchone(); cur.close(); conn.close()
    return dict(row) if row else None


def lms_get_user_attempt(user_id, quiz_id):
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""SELECT * FROM lms_quiz_attempts
                   WHERE user_id=%s AND quiz_id=%s AND completed=1
                   ORDER BY submitted_at DESC LIMIT 1""", (user_id, quiz_id))
    row = cur.fetchone(); cur.close(); conn.close()
    return dict(row) if row else None


def lms_submit_exam(user_id, exam_id, file_path):
    conn = get_db(); cur = conn.cursor()
    cur.execute(
        "INSERT INTO lms_exam_submissions (user_id,exam_id,file_path) VALUES (%s,%s,%s) RETURNING id",
        (user_id, exam_id, file_path)
    )
    conn.commit(); sid = cur.fetchone()[0]; cur.close(); conn.close()
    return sid


def lms_get_exam_submissions(exam_id):
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""SELECT s.*,u.fname,u.lname,u.email
                   FROM lms_exam_submissions s JOIN users u ON s.user_id=u.id
                   WHERE s.exam_id=%s ORDER BY s.submitted_at DESC""", (exam_id,))
    rows = cur.fetchall(); cur.close(); conn.close()
    return [dict(r) for r in rows]


def lms_get_user_exam_submission(user_id, exam_id):
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""SELECT * FROM lms_exam_submissions
                   WHERE user_id=%s AND exam_id=%s ORDER BY submitted_at DESC LIMIT 1""", (user_id, exam_id))
    row = cur.fetchone(); cur.close(); conn.close()
    return dict(row) if row else None


def lms_grade_submission(submission_id, grade, feedback, graded_by):
    conn = get_db(); cur = conn.cursor()
    cur.execute("UPDATE lms_exam_submissions SET grade=%s,feedback=%s,graded_at=NOW(),graded_by=%s WHERE id=%s",
                (grade, feedback, graded_by, submission_id))
    conn.commit(); cur.close(); conn.close()


def lms_get_submission_user_module(sub_id):
    """user_id + module_id for the exam a submission belongs to (for progress updates)."""
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""SELECT s.user_id, e.module_id FROM lms_exam_submissions s
                   JOIN lms_practical_exams e ON s.exam_id=e.id WHERE s.id=%s""", (sub_id,))
    row = cur.fetchone(); cur.close(); conn.close()
    return dict(row) if row else None


def lms_get_all_submissions(instructor_id=None):
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if instructor_id:
        cur.execute("""SELECT s.*,u.fname,u.lname,e.title AS exam_title,m.title AS module_title
                       FROM lms_exam_submissions s
                       JOIN users u ON s.user_id=u.id
                       JOIN lms_practical_exams e ON s.exam_id=e.id
                       JOIN lms_modules m ON e.module_id=m.id
                       WHERE m.instructor_id=%s ORDER BY s.submitted_at DESC""", (instructor_id,))
    else:
        cur.execute("""SELECT s.*,u.fname,u.lname,e.title AS exam_title,m.title AS module_title
                       FROM lms_exam_submissions s
                       JOIN users u ON s.user_id=u.id
                       JOIN lms_practical_exams e ON s.exam_id=e.id
                       JOIN lms_modules m ON e.module_id=m.id
                       ORDER BY s.submitted_at DESC""")
    rows = cur.fetchall(); cur.close(); conn.close()
    return [dict(r) for r in rows]


def lms_update_progress(user_id, module_id, **fields):
    conn = get_db(); cur = conn.cursor()
    cur.execute("""INSERT INTO lms_progress (user_id,module_id) VALUES (%s,%s)
                   ON CONFLICT (user_id,module_id) DO NOTHING""", (user_id, module_id))
    allowed = {"quiz_score","quiz_passed","exam_graded","exam_grade","completed","completed_at"}
    safe = {k: v for k, v in fields.items() if k in allowed}
    if safe:
        # Convert booleans to integers for Postgres SMALLINT columns
        safe_values = []
        for k, v in safe.items():
            if isinstance(v, bool):
                safe_values.append(1 if v else 0)
            else:
                safe_values.append(v)
        clauses = ", ".join(f"{k}=%s" for k in safe)
        cur.execute(f"UPDATE lms_progress SET {clauses} WHERE user_id=%s AND module_id=%s",
                    (*safe_values, user_id, module_id))
    conn.commit(); cur.close(); conn.close()


def lms_get_progress(user_id, module_id=None):
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if module_id:
        cur.execute("SELECT * FROM lms_progress WHERE user_id=%s AND module_id=%s", (user_id, module_id))
        row = cur.fetchone(); cur.close(); conn.close()
        return dict(row) if row else None
    cur.execute("SELECT * FROM lms_progress WHERE user_id=%s", (user_id,))
    rows = cur.fetchall(); cur.close(); conn.close()
    return [dict(r) for r in rows]


def lms_issue_certificate(user_id, approved_by):
    import secrets
    from datetime import date
    cert_id = secrets.token_hex(16)
    issued  = date.today()
    expires = date(issued.year + 3, issued.month, issued.day)
    conn = get_db(); cur = conn.cursor()
    cur.execute(
        "INSERT INTO lms_certificates (user_id,cert_id,approved_by,issued_at,expires_at) VALUES (%s,%s,%s,%s,%s) RETURNING id",
        (user_id, cert_id, approved_by, issued, expires)
    )
    conn.commit(); cid = cur.fetchone()[0]; cur.close(); conn.close()
    return cid, cert_id


def lms_update_cert_blockchain(cert_id, tx_hash, blockchain_token, anchor_version=1):
    conn = get_db(); cur = conn.cursor()
    cur.execute("UPDATE lms_certificates SET tx_hash=%s,blockchain_token=%s,anchor_version=%s "
                "WHERE cert_id=%s",
                (tx_hash, blockchain_token, anchor_version, cert_id))
    conn.commit(); cur.close(); conn.close()


def lms_get_certificate(user_id=None, cert_id=None):
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if cert_id:
        cur.execute("""SELECT c.*,u.fname,u.lname,u.email,
                              a.fname AS approver_fname, a.lname AS approver_lname
                       FROM lms_certificates c JOIN users u ON c.user_id=u.id
                       LEFT JOIN users a ON c.approved_by=a.id
                       WHERE c.cert_id=%s""", (cert_id,))
    else:
        cur.execute("""SELECT c.*,u.fname,u.lname,u.email,
                              a.fname AS approver_fname, a.lname AS approver_lname
                       FROM lms_certificates c JOIN users u ON c.user_id=u.id
                       LEFT JOIN users a ON c.approved_by=a.id
                       WHERE c.user_id=%s""", (user_id,))
    row = cur.fetchone(); cur.close(); conn.close()
    return dict(row) if row else None


def lms_get_certificates():
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""SELECT c.*,u.fname,u.lname,u.email,
                          a.fname AS approver_fname, a.lname AS approver_lname
                   FROM lms_certificates c JOIN users u ON c.user_id=u.id
                   LEFT JOIN users a ON c.approved_by=a.id
                   ORDER BY c.issued_at DESC""")
    rows = cur.fetchall(); cur.close(); conn.close()
    return [dict(r) for r in rows]


def lms_get_wrong_questions(attempt_id):
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT qq.question_text,
               qc_given.choice_text    AS given_answer,
               qc_correct.choice_text  AS correct_answer
        FROM lms_quiz_answers qa
        JOIN  lms_quiz_questions qq
              ON qa.question_id = qq.id AND qq.question_type = 'multiple_choice'
        LEFT JOIN lms_quiz_choices qc_given
              ON qa.selected_choice_id = qc_given.id
        LEFT JOIN lms_quiz_choices qc_correct
              ON qc_correct.question_id = qq.id AND qc_correct.is_correct = 1
        WHERE qa.attempt_id = %s
          AND (qa.selected_choice_id IS NULL OR qc_given.is_correct = 0)
    """, (attempt_id,))
    rows = cur.fetchall(); cur.close(); conn.close()
    return [dict(r) for r in rows]


def lms_get_eligible_for_cert():
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT u.id, u.fname, u.lname, u.email, COUNT(p.id) AS completed_count,
               (SELECT COUNT(*) FROM lms_modules WHERE is_published=1) AS total_modules
        FROM users u
        JOIN lms_progress p ON u.id=p.user_id AND p.completed=1
        WHERE u.role='trainee'
          AND u.id NOT IN (SELECT user_id FROM lms_certificates)
        GROUP BY u.id, u.fname, u.lname, u.email
        HAVING COUNT(p.id) >= (SELECT COUNT(*) FROM lms_modules WHERE is_published=1)
           AND (SELECT COUNT(*) FROM lms_modules WHERE is_published=1) > 0
    """)
    rows = cur.fetchall(); cur.close(); conn.close()
    return [dict(r) for r in rows]


# ── LMS Quiz Question Types Helpers ───────────────────────────────────────────

def lms_save_quiz_questions(quiz_id, questions):
    conn = get_db(); cur = conn.cursor()
    cur.execute("DELETE FROM lms_quiz_questions WHERE quiz_id=%s", (quiz_id,))
    for i, q in enumerate(questions):
        q_type = q.get("type", "multiple_choice")
        correct_answer = q.get("correct_answer") if q_type != "multiple_choice" else None
        cur.execute("""
            INSERT INTO lms_quiz_questions (quiz_id, question_text, question_type, correct_answer, order_num, points)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (quiz_id, q.get("text"), q_type, correct_answer, i, q.get("points", 1)))
        q_id = cur.fetchone()[0]
        if q_type == "multiple_choice":
            for choice in q.get("choices", []):
                cur.execute("""
                    INSERT INTO lms_quiz_choices (question_id, choice_text, is_correct)
                    VALUES (%s, %s, %s)
                """, (q_id, choice.get("text"), 1 if choice.get("is_correct") else 0))
    conn.commit(); cur.close(); conn.close()


def _auto_grade_answer(question_type, correct_answer, submitted_text):
    if not submitted_text or not correct_answer:
        return False, 0
    if question_type == "identification":
        is_correct = submitted_text.strip().lower() == correct_answer.strip().lower()
        return is_correct, (1 if is_correct else 0)
    if question_type == "enumeration":
        correct_set  = {x.strip().lower() for x in correct_answer.split(",")}
        submitted_set = {x.strip().lower() for x in submitted_text.split(",")}
        is_correct = submitted_set >= correct_set
        return is_correct, (1 if is_correct else 0)
    return False, 0


def lms_submit_quiz(attempt_id, answers_dict):
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT quiz_id FROM lms_quiz_attempts WHERE id=%s", (attempt_id,))
    quiz_row = cur.fetchone()
    if not quiz_row:
        cur.close(); conn.close()
        return None
    quiz_id = quiz_row["quiz_id"]
    cur.execute("SELECT id, question_type, points, correct_answer FROM lms_quiz_questions WHERE quiz_id=%s ORDER BY order_num", (quiz_id,))
    questions = [dict(q) for q in cur.fetchall()]
    total_points = sum(q["points"] for q in questions)
    earned = 0.0
    cur2 = conn.cursor()
    for q in questions:
        q_id   = q["id"]
        answer = answers_dict.get(str(q_id), "")
        is_correct = False
        if q["question_type"] == "multiple_choice":
            if answer:
                try:
                    choice_id = int(answer)
                    cur.execute("SELECT is_correct FROM lms_quiz_choices WHERE id=%s", (choice_id,))
                    choice = cur.fetchone()
                    is_correct = choice and choice["is_correct"]
                    cur2.execute("""
                        INSERT INTO lms_quiz_answers (attempt_id, question_id, selected_choice_id)
                        VALUES (%s, %s, %s)
                    """, (attempt_id, q_id, choice_id if choice else None))
                except ValueError:
                    pass
        else:
            is_correct, _ = _auto_grade_answer(q["question_type"], q["correct_answer"], answer)
            cur2.execute("""
                INSERT INTO lms_quiz_answers (attempt_id, question_id, answer_text)
                VALUES (%s, %s, %s)
            """, (attempt_id, q_id, answer))
        if is_correct:
            earned += q["points"]
    score = round((earned / total_points * 100) if total_points > 0 else 0, 2)
    cur2.execute("UPDATE lms_quiz_attempts SET score=%s, completed=1, submitted_at=NOW() WHERE id=%s", (score, attempt_id))
    conn.commit(); cur.close(); cur2.close(); conn.close()
    return score


# ── LMS Practical Exam Question Helpers ───────────────────────────────────────

def lms_get_exam_questions(exam_id):
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM lms_exam_questions WHERE exam_id=%s ORDER BY order_num", (exam_id,))
    rows = cur.fetchall(); cur.close(); conn.close()
    return [dict(r) for r in rows]


def lms_save_exam_questions(exam_id, questions):
    conn = get_db(); cur = conn.cursor()
    cur.execute("DELETE FROM lms_exam_questions WHERE exam_id=%s", (exam_id,))
    for i, q in enumerate(questions):
        cur.execute("""
            INSERT INTO lms_exam_questions (exam_id, question_text, question_type, correct_answer, order_num, points)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (exam_id, q.get("text"), q.get("type", "essay"), q.get("correct_answer"), i, q.get("points", 1)))
    conn.commit(); cur.close(); conn.close()


def lms_submit_exam_answers(submission_id, answers_dict):
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT exam_id FROM lms_exam_submissions WHERE id=%s", (submission_id,))
    sub = cur.fetchone()
    if not sub:
        cur.close(); conn.close()
        return
    exam_id  = sub["exam_id"]
    questions = lms_get_exam_questions(exam_id)
    has_essay  = False
    auto_score = 0.0
    cur2 = conn.cursor()
    for q in questions:
        answer = answers_dict.get(str(q["id"]), "")
        cur2.execute("""
            INSERT INTO lms_exam_answers (submission_id, question_id, answer_text)
            VALUES (%s, %s, %s)
        """, (submission_id, q["id"], answer))
        if q["question_type"] == "essay":
            has_essay = True
        else:
            is_correct, pts = _auto_grade_answer(q["question_type"], q["correct_answer"], answer)
            if is_correct:
                auto_score += q["points"]
    conn.commit()
    cur2.execute("UPDATE lms_exam_submissions SET auto_score=%s, needs_review=%s WHERE id=%s",
                 (auto_score, 1 if has_essay else 0, submission_id))
    conn.commit(); cur.close(); cur2.close(); conn.close()


def lms_get_exam_submission_detail(sub_id):
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT s.*, u.fname, u.lname, u.email, m.title AS module_title, e.title AS exam_title
        FROM lms_exam_submissions s
        JOIN users u ON s.user_id=u.id
        JOIN lms_practical_exams e ON s.exam_id=e.id
        JOIN lms_modules m ON e.module_id=m.id
        WHERE s.id=%s
    """, (sub_id,))
    submission = cur.fetchone()
    if not submission:
        cur.close(); conn.close()
        return None
    submission = dict(submission)
    cur.execute("""
        SELECT q.id, q.question_text, q.question_type, q.correct_answer, q.points,
               a.answer_text
        FROM lms_exam_questions q
        LEFT JOIN lms_exam_answers a ON q.id=a.question_id AND a.submission_id=%s
        WHERE q.exam_id=%s
        ORDER BY q.order_num
    """, (sub_id, submission["exam_id"]))
    submission["questions"] = [dict(q) for q in cur.fetchall()]
    cur.close(); conn.close()
    return submission


def lms_archive_module(module_id):
    conn = get_db(); cur = conn.cursor()
    cur.execute("UPDATE lms_modules SET archived_at = NOW() WHERE id = %s", (module_id,))
    conn.commit(); cur.close(); conn.close()


def lms_restore_module(module_id):
    conn = get_db(); cur = conn.cursor()
    cur.execute("UPDATE lms_modules SET archived_at = NULL WHERE id = %s", (module_id,))
    conn.commit(); cur.close(); conn.close()


def lms_get_archived_modules(instructor_id=None):
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if instructor_id:
        cur.execute("""SELECT m.*,u.fname,u.lname FROM lms_modules m
                       JOIN users u ON m.instructor_id=u.id
                       WHERE m.archived_at IS NOT NULL AND m.instructor_id=%s
                       ORDER BY m.archived_at DESC""", (instructor_id,))
    else:
        cur.execute("""SELECT m.*,u.fname,u.lname FROM lms_modules m
                       JOIN users u ON m.instructor_id=u.id
                       WHERE m.archived_at IS NOT NULL ORDER BY m.archived_at DESC""")
    rows = cur.fetchall(); cur.close(); conn.close()
    return [dict(r) for r in rows]


def lms_delete_module(module_id):
    conn = get_db(); cur = conn.cursor()
    cur.execute("DELETE FROM lms_modules WHERE id = %s AND archived_at IS NOT NULL", (module_id,))
    conn.commit(); cur.close(); conn.close()


def lms_get_module_requirements(module_ids):
    """Which of these modules actually have a quiz / practical exam, in one query.

    The trainee progress bars use this so they only count work that exists — a
    module with no exam should not sit at 50% forever waiting for one. Any quiz
    or exam row counts as required, matching _check_completion().
    """
    if not module_ids:
        return {}
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT m.id AS module_id,
               EXISTS(SELECT 1 FROM lms_quizzes q         WHERE q.module_id = m.id) AS has_quiz,
               EXISTS(SELECT 1 FROM lms_practical_exams e WHERE e.module_id = m.id) AS has_exam
        FROM lms_modules m
        WHERE m.id = ANY(%s)
    """, (list(module_ids),))
    rows = cur.fetchall(); cur.close(); conn.close()
    return {r["module_id"]: {"has_quiz": bool(r["has_quiz"]),
                             "has_exam": bool(r["has_exam"])} for r in rows}
