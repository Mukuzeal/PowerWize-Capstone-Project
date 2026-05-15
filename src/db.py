from datetime import datetime, timedelta
import hashlib
import os

from dotenv import load_dotenv
load_dotenv()

import psycopg2
import psycopg2.extras

DATABASE_URL = os.environ.get("DATABASE_URL", "")

MONTHS_PY = ["January","February","March","April","May","June",
             "July","August","September","October","November","December"]

TYPE_OFFSETS = {
    "training":      [0, 1, 2, 6, 7, 8, 9],
    "selfpaced":     [0, 1, 2],
    "renewal":       [0, 1],
    "gemp_training": [0, 1, 2],
}


def build_batch_label(name, offsets, start_date):
    dates = [start_date + timedelta(days=d) for d in offsets]
    parts = []
    current_month = None
    for d in dates:
        if d.month != current_month:
            parts.append(f"{MONTHS_PY[d.month - 1]} {d.day}")
            current_month = d.month
        else:
            parts.append(str(d.day))
    date_str = (", ".join(parts[:-1]) + " & " + parts[-1]) if len(parts) > 1 else parts[0]
    return f"{name} - {date_str}, {dates[0].year}"


def get_db():
    return psycopg2.connect(DATABASE_URL)


def dict_cur(conn):
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS batches (
            id         SERIAL PRIMARY KEY,
            name       VARCHAR(100) NOT NULL,
            type       VARCHAR(30)  NOT NULL,
            start_date DATE         NOT NULL,
            created_at TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS registrations (
            id               VARCHAR(8)   PRIMARY KEY,
            form_type        VARCHAR(30)  NOT NULL,
            form_label       VARCHAR(50)  NOT NULL,
            submitted_at     TIMESTAMP    NOT NULL,
            title            VARCHAR(20),
            full_name        VARCHAR(200),
            middle_name      VARCHAR(100),
            residence        VARCHAR(300),
            company_name     VARCHAR(200),
            designation      VARCHAR(150),
            company_address  VARCHAR(300),
            contact_number   VARCHAR(30),
            email            VARCHAR(150),
            birthdate        VARCHAR(20),
            age              VARCHAR(5),
            doe_expiry       VARCHAR(20),
            training_type    VARCHAR(250),
            batch_id         INT NULL,
            photo_id         VARCHAR(255),
            resume           VARCHAR(255),
            expired_doe      VARCHAR(255),
            valid_id         VARCHAR(255),
            status           VARCHAR(20)  NOT NULL DEFAULT 'pending',
            is_qualified     SMALLINT     NOT NULL DEFAULT 1,
            gemp_designation VARCHAR(200) NULL,
            FOREIGN KEY (batch_id) REFERENCES batches(id) ON DELETE SET NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id             SERIAL PRIMARY KEY,
            role           VARCHAR(20)  NOT NULL,
            fname          VARCHAR(100) NOT NULL,
            lname          VARCHAR(100) NOT NULL,
            email          VARCHAR(150) NOT NULL UNIQUE,
            password_hash  VARCHAR(255) NOT NULL,
            contact_number VARCHAR(20),
            company_name   VARCHAR(150),
            payment_status VARCHAR(10)  NOT NULL DEFAULT 'unpaid',
            training_type  VARCHAR(250) NULL,
            created_at     TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
            archived_at    TIMESTAMP    NULL DEFAULT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id           SERIAL PRIMARY KEY,
            user_id      INT          NOT NULL,
            amount_php   DECIMAL(10,2) NOT NULL,
            method       VARCHAR(10)  NOT NULL,
            paymongo_id  VARCHAR(120) NOT NULL,
            status       VARCHAR(10)  NOT NULL DEFAULT 'pending',
            receipt_id   VARCHAR(30)  NULL,
            receipt_hash VARCHAR(66)  NULL,
            tx_hash      VARCHAR(66)  NULL,
            qr_code_path VARCHAR(255) NULL,
            created_at   TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
            paid_at      TIMESTAMP    NULL DEFAULT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS account_tokens (
            token        VARCHAR(64)  PRIMARY KEY,
            reg_id       VARCHAR(8)   NOT NULL,
            email        VARCHAR(150) NOT NULL,
            is_qualified SMALLINT     NOT NULL DEFAULT 1,
            expires_at   TIMESTAMP    NOT NULL,
            used_at      TIMESTAMP    NULL DEFAULT NULL,
            created_at   TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (reg_id) REFERENCES registrations(id) ON DELETE CASCADE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS solar_requests (
            id                  SERIAL PRIMARY KEY,
            user_id             INT NULL,
            name                VARCHAR(200) NOT NULL,
            address             TEXT         NOT NULL,
            email               VARCHAR(150) NOT NULL,
            contact             VARCHAR(30)  NOT NULL,
            establishment_type  VARCHAR(20)  NOT NULL,
            ownership           VARCHAR(10)  NOT NULL,
            electrical_phase    VARCHAR(10)  NOT NULL,
            monthly_bill_php    DECIMAL(10,2) NULL,
            kwh_monthly         DECIMAL(10,2) NULL,
            time_of_use_night_pct INT         NULL,
            target_savings      VARCHAR(5)   NOT NULL DEFAULT '100',
            roof_sqm            DECIMAL(8,2) NULL,
            notes               TEXT         NULL,
            bill_path           VARCHAR(255) NULL,
            ocr_kwh             DECIMAL(10,2) NULL,
            ocr_bill_amount     DECIMAL(10,2) NULL,
            system_size_kw      DECIMAL(6,2) NULL,
            panel_count         INT          NULL,
            cost_min            DECIMAL(12,2) NULL,
            cost_max            DECIMAL(12,2) NULL,
            monthly_savings     DECIMAL(10,2) NULL,
            roi_years           DECIMAL(5,1) NULL,
            feasibility         VARCHAR(20)  NULL,
            system_type         VARCHAR(30)  NULL,
            battery_recommended SMALLINT     NULL,
            ai_explanation      TEXT         NULL,
            status              VARCHAR(30)  NOT NULL DEFAULT 'submitted',
            reviewer_notes      TEXT         NULL,
            reviewed_at         TIMESTAMP    NULL,
            final_system_kw     DECIMAL(6,2) NULL,
            final_panel_count   INT          NULL,
            final_cost          DECIMAL(12,2) NULL,
            created_at          TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS lms_modules (
            id            SERIAL PRIMARY KEY,
            title         VARCHAR(200) NOT NULL,
            description   TEXT,
            instructor_id INT          NOT NULL,
            training_type VARCHAR(250) NOT NULL DEFAULT 'training',
            is_published  SMALLINT     NOT NULL DEFAULT 0,
            created_at    TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
            archived_at   TIMESTAMP    NULL DEFAULT NULL,
            FOREIGN KEY (instructor_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS lms_module_files (
            id            SERIAL PRIMARY KEY,
            module_id     INT          NOT NULL,
            filename      VARCHAR(255) NOT NULL,
            original_name VARCHAR(255) NOT NULL,
            file_type     VARCHAR(50),
            file_size     INT,
            uploaded_at   TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (module_id) REFERENCES lms_modules(id) ON DELETE CASCADE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS lms_quizzes (
            id              SERIAL PRIMARY KEY,
            module_id       INT          NOT NULL UNIQUE,
            title           VARCHAR(200) NOT NULL,
            description     TEXT,
            time_limit_mins INT          NOT NULL DEFAULT 30,
            passing_score   INT          NOT NULL DEFAULT 70,
            is_ai_generated SMALLINT     NOT NULL DEFAULT 0,
            is_published    SMALLINT     NOT NULL DEFAULT 0,
            created_at      TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (module_id) REFERENCES lms_modules(id) ON DELETE CASCADE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS lms_quiz_questions (
            id             SERIAL PRIMARY KEY,
            quiz_id        INT  NOT NULL,
            question_text  TEXT NOT NULL,
            question_type  VARCHAR(20) NOT NULL DEFAULT 'multiple_choice',
            correct_answer TEXT NULL,
            order_num      INT  NOT NULL DEFAULT 0,
            points         INT  NOT NULL DEFAULT 1,
            FOREIGN KEY (quiz_id) REFERENCES lms_quizzes(id) ON DELETE CASCADE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS lms_quiz_choices (
            id          SERIAL PRIMARY KEY,
            question_id INT      NOT NULL,
            choice_text TEXT     NOT NULL,
            is_correct  SMALLINT NOT NULL DEFAULT 0,
            FOREIGN KEY (question_id) REFERENCES lms_quiz_questions(id) ON DELETE CASCADE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS lms_practical_exams (
            id                  SERIAL PRIMARY KEY,
            module_id           INT      NOT NULL UNIQUE,
            title               VARCHAR(200) NOT NULL,
            instructions        TEXT         NOT NULL,
            evaluation_criteria TEXT,
            requires_camera     SMALLINT     NOT NULL DEFAULT 0,
            created_at          TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (module_id) REFERENCES lms_modules(id) ON DELETE CASCADE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS lms_quiz_attempts (
            id           SERIAL PRIMARY KEY,
            user_id      INT      NOT NULL,
            quiz_id      INT      NOT NULL,
            started_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            submitted_at TIMESTAMP NULL DEFAULT NULL,
            score        DECIMAL(5,2) NULL,
            tab_switches INT      NOT NULL DEFAULT 0,
            completed    SMALLINT NOT NULL DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (quiz_id) REFERENCES lms_quizzes(id) ON DELETE CASCADE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS lms_quiz_answers (
            id                 SERIAL PRIMARY KEY,
            attempt_id         INT  NOT NULL,
            question_id        INT  NOT NULL,
            selected_choice_id INT  NULL,
            answer_text        TEXT NULL,
            FOREIGN KEY (attempt_id)         REFERENCES lms_quiz_attempts(id)  ON DELETE CASCADE,
            FOREIGN KEY (question_id)        REFERENCES lms_quiz_questions(id) ON DELETE CASCADE,
            FOREIGN KEY (selected_choice_id) REFERENCES lms_quiz_choices(id)   ON DELETE SET NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS lms_exam_submissions (
            id           SERIAL PRIMARY KEY,
            user_id      INT      NOT NULL,
            exam_id      INT      NOT NULL,
            file_path    VARCHAR(255),
            submitted_at TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
            grade        INT          NULL,
            feedback     TEXT         NULL,
            graded_at    TIMESTAMP    NULL DEFAULT NULL,
            graded_by    INT          NULL,
            auto_score   DECIMAL(5,2) NULL,
            needs_review SMALLINT     NOT NULL DEFAULT 0,
            FOREIGN KEY (user_id)   REFERENCES users(id)               ON DELETE CASCADE,
            FOREIGN KEY (exam_id)   REFERENCES lms_practical_exams(id) ON DELETE CASCADE,
            FOREIGN KEY (graded_by) REFERENCES users(id)               ON DELETE SET NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS lms_progress (
            id           SERIAL PRIMARY KEY,
            user_id      INT          NOT NULL,
            module_id    INT          NOT NULL,
            quiz_score   DECIMAL(5,2) NULL,
            quiz_passed  SMALLINT     NOT NULL DEFAULT 0,
            exam_graded  SMALLINT     NOT NULL DEFAULT 0,
            exam_grade   INT          NULL,
            completed    SMALLINT     NOT NULL DEFAULT 0,
            completed_at TIMESTAMP    NULL DEFAULT NULL,
            CONSTRAINT uq_user_module UNIQUE (user_id, module_id),
            FOREIGN KEY (user_id)   REFERENCES users(id)       ON DELETE CASCADE,
            FOREIGN KEY (module_id) REFERENCES lms_modules(id) ON DELETE CASCADE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS lms_certificates (
            id               SERIAL PRIMARY KEY,
            user_id          INT          NOT NULL,
            cert_id          VARCHAR(32)  NOT NULL UNIQUE,
            issued_at        TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
            expires_at       DATE         NULL,
            approved_by      INT          NULL,
            tx_hash          VARCHAR(66)  NULL,
            blockchain_token VARCHAR(255) NULL,
            FOREIGN KEY (user_id)     REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (approved_by) REFERENCES users(id) ON DELETE SET NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS lms_exam_questions (
            id            SERIAL PRIMARY KEY,
            exam_id       INT         NOT NULL,
            question_text TEXT        NOT NULL,
            question_type VARCHAR(20) NOT NULL DEFAULT 'essay',
            correct_answer TEXT       NULL,
            order_num     INT         NOT NULL DEFAULT 0,
            points        INT         NOT NULL DEFAULT 1,
            FOREIGN KEY (exam_id) REFERENCES lms_practical_exams(id) ON DELETE CASCADE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS lms_exam_answers (
            id            SERIAL PRIMARY KEY,
            submission_id INT  NOT NULL,
            question_id   INT  NOT NULL,
            answer_text   TEXT NULL,
            FOREIGN KEY (submission_id) REFERENCES lms_exam_submissions(id) ON DELETE CASCADE,
            FOREIGN KEY (question_id)   REFERENCES lms_exam_questions(id)   ON DELETE CASCADE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS feedback (
            id         SERIAL PRIMARY KEY,
            user_id    INT      NOT NULL,
            module_id  INT      NOT NULL,
            rating     SMALLINT NOT NULL,
            comment    TEXT     NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_fb_user_module UNIQUE (user_id, module_id),
            FOREIGN KEY (user_id)   REFERENCES users(id)       ON DELETE CASCADE,
            FOREIGN KEY (module_id) REFERENCES lms_modules(id) ON DELETE CASCADE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id          SERIAL PRIMARY KEY,
            user_id     INT          NULL,
            action      VARCHAR(150) NOT NULL,
            entity_type VARCHAR(50)  NULL,
            entity_id   VARCHAR(50)  NULL,
            details     TEXT         NULL,
            created_at  TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            token      VARCHAR(64)  PRIMARY KEY,
            email      VARCHAR(150) NOT NULL,
            expires_at TIMESTAMP    NOT NULL,
            used_at    TIMESTAMP    NULL DEFAULT NULL,
            created_at TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Seed GEMP 2026 batches (only once)
    cur.execute("SELECT COUNT(*) FROM batches WHERE type='gemp_training'")
    if cur.fetchone()[0] == 0:
        from datetime import date as _date
        gemp_batches = [
            ("GEMP Training", _date(2026, 1, 8)),
            ("GEMP Training", _date(2026, 3, 12)),
            ("GEMP Training", _date(2026, 4, 23)),
            ("GEMP Training", _date(2026, 6, 18)),
            ("GEMP Training", _date(2026, 7, 23)),
            ("GEMP Training", _date(2026, 9, 24)),
            ("GEMP Training", _date(2026, 11, 5)),
        ]
        for bname, bdate in gemp_batches:
            cur.execute(
                "INSERT INTO batches (name, type, start_date) VALUES (%s, 'gemp_training', %s)",
                (bname, bdate)
            )

    conn.commit()
    cur.close()
    conn.close()


# ── Solar PV request helpers ──────────────────────────────────────────────────

def save_solar_request(data: dict) -> int:
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("""
        INSERT INTO solar_requests (
            user_id, name, address, email, contact,
            establishment_type, ownership, electrical_phase,
            monthly_bill_php, kwh_monthly, time_of_use_night_pct,
            target_savings, roof_sqm, notes, bill_path,
            ocr_kwh, ocr_bill_amount
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        RETURNING id
    """, (
        data.get("user_id"), data.get("name"), data.get("address"),
        data.get("email"), data.get("contact"),
        data.get("establishment_type"), data.get("ownership"),
        data.get("electrical_phase"),
        data.get("monthly_bill_php"), data.get("kwh_monthly"),
        data.get("time_of_use_night_pct"), data.get("target_savings"),
        data.get("roof_sqm"), data.get("notes"), data.get("bill_path"),
        data.get("ocr_kwh"), data.get("ocr_bill_amount"),
    ))
    conn.commit()
    req_id = cur.fetchone()[0]
    cur.close(); conn.close()
    return req_id


def update_solar_request(req_id: int, **fields):
    if not fields:
        return
    allowed = {
        "system_size_kw", "panel_count", "cost_min", "cost_max",
        "monthly_savings", "roi_years", "feasibility", "system_type",
        "battery_recommended", "ai_explanation", "status",
        "reviewer_notes", "reviewed_at",
        "final_system_kw", "final_panel_count", "final_cost",
    }
    safe = {k: v for k, v in fields.items() if k in allowed}
    if not safe:
        return
    clauses = ", ".join(f"{k}=%s" for k in safe)
    conn = get_db()
    cur  = conn.cursor()
    cur.execute(f"UPDATE solar_requests SET {clauses} WHERE id=%s",
                (*safe.values(), req_id))
    conn.commit()
    cur.close(); conn.close()


def get_solar_request(req_id: int) -> dict | None:
    conn = get_db()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM solar_requests WHERE id=%s", (req_id,))
    row = cur.fetchone()
    cur.close(); conn.close()
    return dict(row) if row else None


def get_solar_requests() -> list:
    conn = get_db()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM solar_requests ORDER BY created_at DESC")
    rows = cur.fetchall()
    cur.close(); conn.close()
    return [dict(r) for r in rows]


def get_solar_requests_by_user(user_id: int) -> list:
    conn = get_db()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM solar_requests WHERE user_id=%s ORDER BY created_at DESC", (user_id,))
    rows = cur.fetchall()
    cur.close(); conn.close()
    return [dict(r) for r in rows]


def get_schedules():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, name, type, start_date FROM batches ORDER BY start_date, id")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    result = {
        "online": [], "face_to_face": [],
        "selfpaced_online": [], "selfpaced_f2f": [],
        "renewal_online": [], "renewal_f2f": [],
        "gemp_online": [], "gemp_f2f": [],
    }
    for bid, name, btype, start_date in rows:
        if btype == "training":
            t = {"id": bid, "label": build_batch_label(name, TYPE_OFFSETS["training"],  start_date)}
            s = {"id": bid, "label": build_batch_label(name, TYPE_OFFSETS["selfpaced"], start_date)}
            result["online"].append(t)
            result["face_to_face"].append(t)
            result["selfpaced_online"].append(s)
            result["selfpaced_f2f"].append(s)
        elif btype == "renewal":
            r = {"id": bid, "label": build_batch_label(name, TYPE_OFFSETS["renewal"], start_date)}
            result["renewal_online"].append(r)
            result["renewal_f2f"].append(r)
        elif btype == "gemp_training":
            g = {"id": bid, "label": build_batch_label(name, TYPE_OFFSETS["gemp_training"], start_date)}
            result["gemp_online"].append(g)
            result["gemp_f2f"].append(g)
    return result


def get_batches_full():
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT id, name, type, start_date, created_at FROM batches ORDER BY start_date")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [dict(r) for r in rows]


def insert_registration(entry):
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("""
        INSERT INTO registrations (
            id, form_type, form_label, submitted_at,
            title, full_name, middle_name, residence,
            company_name, designation, company_address,
            contact_number, email, birthdate, age, doe_expiry,
            training_type, batch_id,
            photo_id, resume, expired_doe, valid_id,
            gemp_designation
        ) VALUES (%s,%s,%s,%s, %s,%s,%s,%s, %s,%s,%s, %s,%s,%s,%s,%s, %s,%s, %s,%s,%s,%s, %s)
    """, (
        entry.get("id"),           entry.get("form_type"),   entry.get("form_label"), entry.get("submitted_at"),
        entry.get("title"),        entry.get("full_name"),   entry.get("middle_name"), entry.get("residence"),
        entry.get("company_name"), entry.get("designation"), entry.get("company_address"),
        entry.get("contact_number"), entry.get("email"), entry.get("birthdate"), entry.get("age"), entry.get("doe_expiry"),
        entry.get("training_type"), entry.get("batch_id") or None,
        entry.get("photo_id"), entry.get("resume"), entry.get("expired_doe"), entry.get("valid_id"),
        entry.get("gemp_designation"),
    ))
    conn.commit()
    cur.close()
    conn.close()


def get_registrations():
    conn = get_db()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT r.*, b.name AS batch_name, b.start_date AS batch_start
        FROM registrations r
        LEFT JOIN batches b ON r.batch_id = b.id
        ORDER BY r.submitted_at DESC
    """)
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    for row in rows:
        if row.get("submitted_at"):
            row["submitted_at"] = row["submitted_at"].strftime("%Y-%m-%d %H:%M")
    return rows


def set_registration_status(reg_id, status, is_qualified=None):
    conn = get_db()
    cur  = conn.cursor()
    if is_qualified is not None:
        cur.execute(
            "UPDATE registrations SET status = %s, is_qualified = %s WHERE id = %s",
            (status, int(is_qualified), reg_id)
        )
    else:
        cur.execute("UPDATE registrations SET status = %s WHERE id = %s", (status, reg_id))
    conn.commit()
    cur.close()
    conn.close()


def _hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


def create_account_token(reg_id, email, is_qualified):
    import secrets
    token = secrets.token_urlsafe(32)
    token_hash = _hash_token(token)
    expires = datetime.now() + timedelta(days=7)
    conn = get_db()
    cur  = conn.cursor()
    cur.execute(
        "INSERT INTO account_tokens (token, reg_id, email, is_qualified, expires_at) VALUES (%s,%s,%s,%s,%s)",
        (token_hash, reg_id, email, int(is_qualified), expires)
    )
    conn.commit()
    cur.close()
    conn.close()
    return token


def get_account_token(token):
    conn = get_db()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT t.*, r.full_name, r.title, r.contact_number, r.company_name, r.training_type
        FROM account_tokens t
        JOIN registrations r ON t.reg_id = r.id
        WHERE t.token = %s
    """, (_hash_token(token),))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return dict(row) if row else None


def mark_token_used(token):
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("UPDATE account_tokens SET used_at = NOW() WHERE token = %s", (_hash_token(token),))
    conn.commit()
    cur.close()
    conn.close()


# ── Password reset helpers ────────────────────────────────────────────────────

def create_reset_token(email):
    import secrets
    token = secrets.token_urlsafe(32)
    token_hash = _hash_token(token)
    expires = datetime.now() + timedelta(hours=1)
    conn = get_db(); cur = conn.cursor()
    cur.execute(
        "INSERT INTO password_reset_tokens (token, email, expires_at) VALUES (%s,%s,%s)",
        (token_hash, email.lower(), expires)
    )
    conn.commit(); cur.close(); conn.close()
    return token


def get_reset_token(token):
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        "SELECT * FROM password_reset_tokens WHERE token=%s",
        (_hash_token(token),)
    )
    row = cur.fetchone(); cur.close(); conn.close()
    return dict(row) if row else None


def mark_reset_token_used(token):
    conn = get_db(); cur = conn.cursor()
    cur.execute(
        "UPDATE password_reset_tokens SET used_at=NOW() WHERE token=%s",
        (_hash_token(token),)
    )
    conn.commit(); cur.close(); conn.close()


def reset_user_password(email, new_password_hash):
    conn = get_db(); cur = conn.cursor()
    cur.execute("UPDATE users SET password_hash=%s WHERE email=%s", (new_password_hash, email.lower()))
    conn.commit(); cur.close(); conn.close()


def get_user_by_email(email):
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT id, fname, lname, email FROM users WHERE email=%s AND archived_at IS NULL", (email.lower(),))
    row = cur.fetchone(); cur.close(); conn.close()
    return dict(row) if row else None


def get_users():
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT id, role, fname, lname, email, contact_number, company_name, created_at, archived_at FROM users ORDER BY id DESC")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [dict(r) for r in rows]


def get_registration_by_email(email):
    conn = get_db()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        "SELECT form_type, form_label, training_type, status, submitted_at FROM registrations WHERE email=%s ORDER BY submitted_at DESC LIMIT 1",
        (email,)
    )
    row = cur.fetchone()
    cur.close(); conn.close()
    return dict(row) if row else None


# ── Payment helpers ───────────────────────────────────────────────────────────

def log_payment(user_id, amount_php, method, paymongo_id):
    conn = get_db()
    cur  = conn.cursor()
    cur.execute(
        "INSERT INTO payments (user_id, amount_php, method, paymongo_id, status) VALUES (%s,%s,%s,%s,'pending') RETURNING id",
        (user_id, amount_php, method, paymongo_id),
    )
    conn.commit()
    row_id = cur.fetchone()[0]
    cur.close(); conn.close()
    return row_id


def mark_payment_paid(paymongo_id):
    conn = get_db()
    cur  = conn.cursor()
    cur.execute(
        "UPDATE payments SET status='paid', paid_at=NOW() WHERE paymongo_id=%s AND status='pending'",
        (paymongo_id,),
    )
    conn.commit()
    cur.close(); conn.close()


def mark_payment_failed(paymongo_id):
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("UPDATE payments SET status='failed' WHERE paymongo_id=%s AND status='pending'", (paymongo_id,))
    conn.commit()
    cur.close(); conn.close()


def mark_user_paid(user_id):
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("UPDATE users SET payment_status='paid' WHERE id=%s", (user_id,))
    conn.commit()
    cur.close(); conn.close()


def get_user_payment_status(user_id):
    conn = get_db()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT payment_status FROM users WHERE id=%s", (user_id,))
    row = cur.fetchone()
    cur.close(); conn.close()
    return row["payment_status"] if row else None


def save_blockchain_receipt(paymongo_id, receipt_id, receipt_hash, tx_hash, qr_code_path):
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("""
        UPDATE payments
        SET receipt_id=%s, receipt_hash=%s, tx_hash=%s, qr_code_path=%s
        WHERE paymongo_id=%s
    """, (receipt_id, receipt_hash, tx_hash, qr_code_path, paymongo_id))
    conn.commit()
    cur.close(); conn.close()


def get_receipt_by_id(receipt_id):
    conn = get_db()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT p.*, u.fname, u.lname, u.email
        FROM payments p
        JOIN users u ON p.user_id = u.id
        WHERE p.receipt_id = %s
    """, (receipt_id,))
    row = cur.fetchone()
    cur.close(); conn.close()
    return dict(row) if row else None


def get_receipt_by_user(user_id):
    conn = get_db()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT * FROM payments
        WHERE user_id = %s AND status = 'paid'
        ORDER BY paid_at DESC LIMIT 1
    """, (user_id,))
    row = cur.fetchone()
    cur.close(); conn.close()
    return dict(row) if row else None


# ── LMS helpers ───────────────────────────────────────────────────────────────

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


def lms_update_cert_blockchain(cert_id, tx_hash, blockchain_token):
    conn = get_db(); cur = conn.cursor()
    cur.execute("UPDATE lms_certificates SET tx_hash=%s,blockchain_token=%s WHERE cert_id=%s",
                (tx_hash, blockchain_token, cert_id))
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


# ── Feedback helpers ──────────────────────────────────────────────────────────

def save_feedback(user_id, module_id, rating, comment):
    conn = get_db(); cur = conn.cursor()
    cur.execute(
        "INSERT INTO feedback (user_id, module_id, rating, comment) VALUES (%s,%s,%s,%s) "
        "ON CONFLICT (user_id, module_id) DO UPDATE SET rating=EXCLUDED.rating, comment=EXCLUDED.comment, created_at=NOW()",
        (user_id, module_id, rating, comment)
    )
    conn.commit(); cur.close(); conn.close()


def get_feedback(module_id=None):
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if module_id:
        cur.execute("""
            SELECT f.*, u.fname, u.lname, m.title AS module_title
            FROM feedback f
            JOIN users u ON f.user_id = u.id
            JOIN lms_modules m ON f.module_id = m.id
            WHERE f.module_id = %s ORDER BY f.created_at DESC
        """, (module_id,))
    else:
        cur.execute("""
            SELECT f.*, u.fname, u.lname, m.title AS module_title
            FROM feedback f
            JOIN users u ON f.user_id = u.id
            JOIN lms_modules m ON f.module_id = m.id
            ORDER BY f.created_at DESC
        """)
    rows = cur.fetchall(); cur.close(); conn.close()
    return [dict(r) for r in rows]


def get_feedback_summary():
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT m.title, COUNT(*) AS count, ROUND(AVG(f.rating), 1) AS avg_rating
        FROM feedback f JOIN lms_modules m ON f.module_id = m.id
        GROUP BY f.module_id, m.title ORDER BY avg_rating DESC
    """)
    rows = cur.fetchall(); cur.close(); conn.close()
    return [dict(r) for r in rows]


def get_user_feedback(user_id, module_id):
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM feedback WHERE user_id=%s AND module_id=%s", (user_id, module_id))
    row = cur.fetchone(); cur.close(); conn.close()
    return dict(row) if row else None


# ── Audit log helpers ─────────────────────────────────────────────────────────

def audit_log(user_id, action, entity_type=None, entity_id=None, details=None):
    try:
        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "INSERT INTO audit_logs (user_id, action, entity_type, entity_id, details) "
            "VALUES (%s,%s,%s,%s,%s)",
            (user_id, action, entity_type, str(entity_id) if entity_id is not None else None, details)
        )
        conn.commit(); cur.close(); conn.close()
    except Exception:
        pass


def get_audit_logs(limit=300):
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT a.*, u.fname, u.lname, u.role
        FROM audit_logs a
        LEFT JOIN users u ON a.user_id = u.id
        ORDER BY a.created_at DESC LIMIT %s
    """, (limit,))
    rows = cur.fetchall(); cur.close(); conn.close()
    return [dict(r) for r in rows]


# ── Admin analytics ───────────────────────────────────────────────────────────

def get_analytics_data():
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("""
        SELECT TO_CHAR(paid_at, 'YYYY-MM') AS month, SUM(amount_php) AS revenue,
               COUNT(*) AS count
        FROM payments WHERE status='paid' AND paid_at IS NOT NULL
        GROUP BY month ORDER BY month ASC LIMIT 12
    """)
    revenue_monthly = [dict(r) for r in cur.fetchall()]

    cur.execute("SELECT COALESCE(SUM(amount_php),0) AS total FROM payments WHERE status='paid'")
    total_revenue = float(cur.fetchone()["total"])

    cur.execute("SELECT form_type, COUNT(*) AS count FROM registrations GROUP BY form_type ORDER BY count DESC")
    reg_by_type = [dict(r) for r in cur.fetchall()]

    cur.execute("SELECT status, COUNT(*) AS count FROM registrations GROUP BY status")
    reg_by_status = [dict(r) for r in cur.fetchall()]

    cur.execute("""
        SELECT m.title, COUNT(*) AS completions
        FROM lms_progress p JOIN lms_modules m ON p.module_id = m.id
        WHERE p.completed = 1
        GROUP BY m.id, m.title ORDER BY completions DESC LIMIT 10
    """)
    lms_completions = [dict(r) for r in cur.fetchall()]

    cur.execute("SELECT status, COUNT(*) AS count FROM solar_requests GROUP BY status ORDER BY count DESC")
    solar_by_status = [dict(r) for r in cur.fetchall()]

    cur.execute("""
        SELECT payment_status, COUNT(*) AS count FROM users
        WHERE role='trainee' AND archived_at IS NULL GROUP BY payment_status
    """)
    payment_split = [dict(r) for r in cur.fetchall()]

    cur.close(); conn.close()
    return {
        "revenue_monthly":  revenue_monthly,
        "total_revenue":    total_revenue,
        "reg_by_type":      reg_by_type,
        "reg_by_status":    reg_by_status,
        "lms_completions":  lms_completions,
        "solar_by_status":  solar_by_status,
        "payment_split":    payment_split,
    }
