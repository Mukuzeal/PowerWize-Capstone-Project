from datetime import timedelta
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


def build_batch_dates(offsets, start_date):
    """Human-readable run dates for a batch, e.g. 'January 29, 30, 31 & February 5'."""
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
    return date_str, dates[0].year


def build_batch_label(name, offsets, start_date):
    date_str, year = build_batch_dates(offsets, start_date)
    return f"{name} - {date_str}, {year}"


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
            selfie_with_id   VARCHAR(255),
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
            -- 1 = legacy anchor (hash compared against this same row);
            -- 2 = fingerprint recomputed from the record at verification time.
            anchor_version SMALLINT   DEFAULT 1,
            qr_code_path VARCHAR(255) NULL,
            created_at   TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
            paid_at      TIMESTAMP    NULL DEFAULT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    # anchor_version was added to the CREATE TABLE after this table already
    # existed in deployed databases, so CREATE TABLE IF NOT EXISTS never
    # applied it there. This backfills it on every startup.
    cur.execute("ALTER TABLE payments ADD COLUMN IF NOT EXISTS anchor_version SMALLINT DEFAULT 1")

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
            -- see payments.anchor_version
            anchor_version   SMALLINT     DEFAULT 1,
            FOREIGN KEY (user_id)     REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (approved_by) REFERENCES users(id) ON DELETE SET NULL
        )
    """)
    # Same drift as payments.anchor_version above — backfill for tables that
    # already existed before this column was added.
    cur.execute("ALTER TABLE lms_certificates ADD COLUMN IF NOT EXISTS anchor_version SMALLINT DEFAULT 1")

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
