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


def expand_offsets(offsets, start_date):
    """A batch's individual run days, before any of them have been nudged for
    a holiday: `start_date` plus each offset."""
    return [start_date + timedelta(days=d) for d in offsets]


def format_dates(dates):
    """Human-readable label for an explicit, ascending list of dates, e.g.
    'January 29, 30, 31 & February 5'. Used for both the offset-computed case
    (new batches) and an admin's individually-edited day list (existing ones)."""
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


def build_batch_dates(offsets, start_date):
    """Human-readable run dates for a batch, e.g. 'January 29, 30, 31 & February 5'."""
    return format_dates(expand_offsets(offsets, start_date))


def build_batch_label(name, offsets, start_date):
    date_str, year = build_batch_dates(offsets, start_date)
    return f"{name} - {date_str}, {year}"


def build_label_from_dates(name, dates):
    """Same label as build_batch_label, but from an explicit list of dates
    (e.g. after an admin has edited individual days) instead of offsets."""
    date_str, year = format_dates(sorted(dates))
    return f"{name} - {date_str}, {year}"


def _session_timezone():
    """The app's local zone, for every DB session.

    Columns are naive TIMESTAMP stamped by NOW(), and code compares them with
    Python's naive datetime.now(). That only holds if both clocks agree: the
    Windows Postgres ran in local time, the Docker one runs in UTC, which made
    every 30-minute grant look 7.5 hours expired the moment it was issued.
    DB_TIMEZONE overrides; otherwise the process's current UTC offset, written
    POSIX-style (sign inverted: UTC+8 is '<+0800>-08:00').
    """
    if os.environ.get("DB_TIMEZONE"):
        return os.environ["DB_TIMEZONE"]
    from datetime import datetime
    minutes = int(datetime.now().astimezone().utcoffset().total_seconds() // 60)
    east = minutes >= 0
    h, m = divmod(abs(minutes), 60)
    return f"<{'+' if east else '-'}{h:02d}{m:02d}>{'-' if east else '+'}{h:02d}:{m:02d}"


def get_db():
    return psycopg2.connect(DATABASE_URL, options=f"-c timezone={_session_timezone()}")


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
            dates      DATE[]       NULL,
            created_at TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("ALTER TABLE batches ADD COLUMN IF NOT EXISTS dates DATE[] NULL")
    # Backfill rows created before `dates` existed by expanding their single
    # start_date through the same TYPE_OFFSETS pattern used everywhere else,
    # so every batch has an explicit per-day list to edit individually.
    cur.execute("""
        UPDATE batches SET dates = CASE type
            WHEN 'training' THEN ARRAY[start_date, start_date+1, start_date+2,
                                        start_date+6, start_date+7, start_date+8, start_date+9]
            WHEN 'renewal' THEN ARRAY[start_date, start_date+1]
            WHEN 'gemp_training' THEN ARRAY[start_date, start_date+1, start_date+2]
            ELSE ARRAY[start_date]
        END
        WHERE dates IS NULL
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
            failed_login_attempts SMALLINT  NOT NULL DEFAULT 0,
            locked_until           TIMESTAMP NULL DEFAULT NULL,
            created_at     TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
            archived_at    TIMESTAMP    NULL DEFAULT NULL
        )
    """)
    # Same drift as payments.anchor_version below — backfill for tables that
    # already existed before these columns were added.
    cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS failed_login_attempts SMALLINT NOT NULL DEFAULT 0")
    cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS locked_until TIMESTAMP NULL DEFAULT NULL")
    # The authoritative link from an application to the account it produced.
    # Previously the two were matched on the email string, which is ambiguous:
    # `registrations.email` is not unique, so someone who applied twice had no
    # single answer, and case differences broke the match outright. Set by
    # redeem_invitation_and_create_account(); left NULL on pre-existing rows
    # rather than guessed, because inferring it from a best-matching email
    # would be exactly the kind of invented history to avoid.
    cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS registration_id VARCHAR(8) NULL")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_users_registration ON users (registration_id)")

    # ── Per-user capability overrides ─────────────────────────────────────
    #
    # Deviations from the role default, one row per (user, capability). No row
    # means "whatever the role says", so an untouched account keeps exactly the
    # access its role grants and this table stays empty until someone is
    # deliberately narrowed or widened.
    #
    # Scoped to the Trainer role in permissions.py: that is where the need is
    # (one trainer runs modules, another handles PV consultations, some do
    # both). See permissions.OVERRIDABLE / OVERRIDABLE_ROLES.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_capabilities (
            id         SERIAL PRIMARY KEY,
            user_id    INT         NOT NULL,
            capability VARCHAR(40) NOT NULL,
            granted    SMALLINT    NOT NULL,
            set_by     INT         NULL,
            set_at     TIMESTAMP   DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_user_capability UNIQUE (user_id, capability),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (set_by)  REFERENCES users(id) ON DELETE SET NULL
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_user_caps_user ON user_capabilities (user_id)")

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

    # At most ONE unused invitation per registration, enforced in the
    # database rather than by hoping two call sites agree.
    #
    # The predicate is `used_at IS NULL` and not "...AND expires_at > NOW()",
    # because NOW() is not immutable and cannot appear in an index predicate.
    # claim_account_invitation() therefore clears any EXPIRED unused token for
    # the registration inside the same transaction before inserting, so
    # re-issuing after an expiry still works.
    #
    # Existing databases may already hold several unused tokens for one
    # registration (two call sites used to be able to mint them), which would
    # make the index creation fail. Keep the newest and retire the rest first
    # — they are superseded invitations, not review outcomes, so nothing is
    # being inferred by dropping them.
    cur.execute("""
        DELETE FROM account_tokens a
         WHERE a.used_at IS NULL
           AND EXISTS (SELECT 1 FROM account_tokens b
                        WHERE b.reg_id = a.reg_id AND b.used_at IS NULL
                          AND (b.created_at, b.token) > (a.created_at, a.token))
    """)
    cur.execute("""CREATE UNIQUE INDEX IF NOT EXISTS uq_account_token_live
                   ON account_tokens (reg_id)
                   WHERE used_at IS NULL""")

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
            final_monthly_savings DECIMAL(10,2) NULL,
            final_roi_years     DECIMAL(5,1) NULL,
            final_system_type   VARCHAR(30)  NULL,
            grid_connection             VARCHAR(10)   NOT NULL DEFAULT 'grid_tie',
            battery_kwh_capacity        DECIMAL(8,2)  NULL,
            estimated_monthly_yield_kwh DECIMAL(10,2) NULL,
            estimated_annual_yield_kwh  DECIMAL(10,2) NULL,
            out_of_scope                SMALLINT      NOT NULL DEFAULT 0,
            out_of_scope_reason         TEXT          NULL,
            created_at          TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
        )
    """)
    # Same drift as payments.anchor_version above — backfill for tables that
    # already existed before these columns were added.
    cur.execute("ALTER TABLE solar_requests ADD COLUMN IF NOT EXISTS grid_connection VARCHAR(10) NOT NULL DEFAULT 'grid_tie'")
    cur.execute("ALTER TABLE solar_requests ADD COLUMN IF NOT EXISTS battery_kwh_capacity DECIMAL(8,2) NULL")
    cur.execute("ALTER TABLE solar_requests ADD COLUMN IF NOT EXISTS estimated_monthly_yield_kwh DECIMAL(10,2) NULL")
    cur.execute("ALTER TABLE solar_requests ADD COLUMN IF NOT EXISTS estimated_annual_yield_kwh DECIMAL(10,2) NULL")
    cur.execute("ALTER TABLE solar_requests ADD COLUMN IF NOT EXISTS final_monthly_savings DECIMAL(10,2) NULL")
    cur.execute("ALTER TABLE solar_requests ADD COLUMN IF NOT EXISTS final_roi_years DECIMAL(5,1) NULL")
    cur.execute("ALTER TABLE solar_requests ADD COLUMN IF NOT EXISTS final_system_type VARCHAR(30) NULL")
    cur.execute("ALTER TABLE solar_requests ADD COLUMN IF NOT EXISTS out_of_scope SMALLINT NOT NULL DEFAULT 0")
    cur.execute("ALTER TABLE solar_requests ADD COLUMN IF NOT EXISTS out_of_scope_reason TEXT NULL")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS lms_modules (
            id            SERIAL PRIMARY KEY,
            title         VARCHAR(200) NOT NULL,
            description   TEXT,
            instructor_id INT          NOT NULL,
            training_type VARCHAR(250) NOT NULL DEFAULT 'training',
            is_published  SMALLINT     NOT NULL DEFAULT 0,
            sort_order    INT          NOT NULL DEFAULT 0,
            is_locked     SMALLINT     NOT NULL DEFAULT 0,
            created_at    TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
            archived_at   TIMESTAMP    NULL DEFAULT NULL,
            FOREIGN KEY (instructor_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    # Same drift as payments.anchor_version above — backfill for tables that
    # already existed before these columns were added.
    cur.execute("ALTER TABLE lms_modules ADD COLUMN IF NOT EXISTS sort_order INT NOT NULL DEFAULT 0")
    cur.execute("ALTER TABLE lms_modules ADD COLUMN IF NOT EXISTS is_locked SMALLINT NOT NULL DEFAULT 0")

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
            is_locked       SMALLINT     NOT NULL DEFAULT 0,
            created_at      TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (module_id) REFERENCES lms_modules(id) ON DELETE CASCADE
        )
    """)
    cur.execute("ALTER TABLE lms_quizzes ADD COLUMN IF NOT EXISTS is_locked SMALLINT NOT NULL DEFAULT 0")

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
            is_locked           SMALLINT     NOT NULL DEFAULT 0,
            created_at          TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (module_id) REFERENCES lms_modules(id) ON DELETE CASCADE
        )
    """)
    cur.execute("ALTER TABLE lms_practical_exams ADD COLUMN IF NOT EXISTS is_locked SMALLINT NOT NULL DEFAULT 0")

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
            material_pct SMALLINT     NOT NULL DEFAULT 0,
            completed    SMALLINT     NOT NULL DEFAULT 0,
            completed_at TIMESTAMP    NULL DEFAULT NULL,
            CONSTRAINT uq_user_module UNIQUE (user_id, module_id),
            FOREIGN KEY (user_id)   REFERENCES users(id)       ON DELETE CASCADE,
            FOREIGN KEY (module_id) REFERENCES lms_modules(id) ON DELETE CASCADE
        )
    """)
    cur.execute("ALTER TABLE lms_progress ADD COLUMN IF NOT EXISTS material_pct SMALLINT NOT NULL DEFAULT 0")

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

    # Commit everything above before the best-effort extension probe below.
    # Without this, the probe's rollback-on-failure discards the whole
    # uncommitted transaction — i.e. every CREATE TABLE in this function — so
    # on a server without pgvector any table declared above this line was
    # silently rolled back on every startup. The tables happened to survive
    # only because they predate the probe; the next one added above it would
    # not have.
    conn.commit()

    # Best-effort — pgvector is painful to install on Windows Postgres, so
    # retrieval defaults to REAL[] + brute-force cosine similarity in Python
    # regardless (fine at this corpus size). This just logs whether the
    # extension happens to be available for a future ANN-backed path; a
    # missing extension must never block startup.
    try:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.commit()
    except Exception:
        conn.rollback()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS rag_chunks (
            id           SERIAL PRIMARY KEY,
            source_type  VARCHAR(30)  NOT NULL,
            source_ref   VARCHAR(255) NOT NULL,
            title        VARCHAR(200) NOT NULL,
            content      TEXT         NOT NULL,
            visibility   VARCHAR(10)  NOT NULL DEFAULT 'public',
            topic        VARCHAR(40)  NULL,
            embedding    REAL[]       NOT NULL,
            embed_model  VARCHAR(100) NOT NULL,
            content_hash VARCHAR(64)  NOT NULL,
            updated_at   TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_rag_chunks_visibility ON rag_chunks (visibility)")

    # ── Registration document retention + company intake ──────────────────
    #
    # Placed AFTER `users` because every table below carries a FK to it.
    # When these lived next to the `registrations` block they referenced a
    # table that did not exist yet, so a FRESH install died on
    # UndefinedTable: relation "users" does not exist. An existing database
    # never showed it, because `users` was already there.

    # ── Document retention ────────────────────────────────────────────────
    #
    # Uploaded IDs, selfies, resumes and DOE certificates are evidence for a
    # decision, not records to keep. They live only until BOTH review gates
    # close — the accept/reject on the registration itself, and the separate
    # selfie verification — and are then hashed and deleted.
    #
    # `selfie_reviewed_at` is the gate that did not previously exist: the
    # pending-selfie queue was driven purely by `selfie_with_id IS NOT NULL`,
    # so an approved selfie never left the queue and nothing recorded that a
    # human had looked at it.
    cur.execute("ALTER TABLE registrations ADD COLUMN IF NOT EXISTS selfie_reviewed_at TIMESTAMP NULL")
    cur.execute("ALTER TABLE registrations ADD COLUMN IF NOT EXISTS selfie_outcome VARCHAR(20) NULL")
    cur.execute("ALTER TABLE registrations ADD COLUMN IF NOT EXISTS documents_purged_at TIMESTAMP NULL")

    # What was reviewed, after the file itself is gone. The SHA-256 lets a
    # later audit confirm a specific document was the one checked without the
    # document being retained; nothing here is personal data on its own.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS registration_document_reviews (
            id          SERIAL PRIMARY KEY,
            reg_id      VARCHAR(8)   NOT NULL,
            field       VARCHAR(30)  NOT NULL,
            sha256      VARCHAR(64)  NULL,
            byte_size   BIGINT       NULL,
            file_ext    VARCHAR(10)  NULL,
            -- Outcome of the review this document supported, copied here so
            -- the evidence row stands alone if the registration is purged.
            outcome     VARCHAR(20)  NULL,
            reviewed_by INT          NULL,
            purged_at   TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
            -- 'deleted' | 'missing' — a file already gone at purge time is
            -- recorded rather than silently skipped.
            note        VARCHAR(40)  NULL,
            CONSTRAINT uq_regdoc_review UNIQUE (reg_id, field),
            FOREIGN KEY (reg_id)      REFERENCES registrations(id) ON DELETE CASCADE,
            FOREIGN KEY (reviewed_by) REFERENCES users(id)         ON DELETE SET NULL
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_regdoc_review_reg ON registration_document_reviews (reg_id)")

    # ── Company intake and roster ─────────────────────────────────────────
    #
    # A company tells us up front who it intends to enrol. That expected list
    # is the only thing that makes "has NOT submitted yet" expressible: a
    # `registrations` row exists only after someone submits, so without a
    # roster there is nothing to compare against.
    #
    # Membership is by explicit slot, never inferred from company_name text
    # or a matching email — both are free-form and collide.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS corporate_intakes (
            id               SERIAL PRIMARY KEY,
            company_name     VARCHAR(200) NOT NULL,
            contact_person   VARCHAR(200) NOT NULL,
            contact_email    VARCHAR(150) NOT NULL,
            contact_number   VARCHAR(30)  NULL,
            -- The program every slot in this intake is for. Matched against
            -- the form the invitee actually fills in.
            form_type        VARCHAR(30)  NOT NULL,
            training_type    VARCHAR(250) NULL,
            -- Coordinator link: SHA-256 only, never the plaintext token.
            coord_token_hash VARCHAR(64)  NULL UNIQUE,
            coord_expires_at TIMESTAMP    NULL,
            coord_revoked_at TIMESTAMP    NULL,
            status           VARCHAR(20)  NOT NULL DEFAULT 'open'
                             CHECK (status IN ('open','ready','closed','cancelled')),
            -- Set when staff dispatch the payment link, so the action cannot
            -- silently fire twice.
            payment_link_sent_at TIMESTAMP NULL,
            created_by       INT          NULL,
            created_at       TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
            closed_at        TIMESTAMP    NULL,
            FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_intake_status ON corporate_intakes (status)")
    # Archiving organises the admin list independently of the business status.
    # It never cancels enrollment, invoices, or class membership.
    cur.execute("ALTER TABLE corporate_intakes ADD COLUMN IF NOT EXISTS archived_at TIMESTAMP NULL")
    cur.execute("ALTER TABLE corporate_intakes ADD COLUMN IF NOT EXISTS archived_by INT NULL REFERENCES users(id) ON DELETE SET NULL")
    # Shared trainee upload entry is separate from the coordinator roster.
    cur.execute("ALTER TABLE corporate_intakes ADD COLUMN IF NOT EXISTS registration_token_hash VARCHAR(64) NULL")
    cur.execute("ALTER TABLE corporate_intakes ADD COLUMN IF NOT EXISTS registration_expires_at TIMESTAMP NULL")
    cur.execute("ALTER TABLE corporate_intakes ADD COLUMN IF NOT EXISTS registration_revoked_at TIMESTAMP NULL")
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_intake_registration_token ON corporate_intakes (registration_token_hash) WHERE registration_token_hash IS NOT NULL")

    # One row per expected trainee, created BEFORE that person submits.
    # `registration_id` is the explicit link; a slot holds at most one
    # registration and a registration belongs to at most one slot.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS corporate_intake_slots (
            id                SERIAL PRIMARY KEY,
            intake_id         INT          NOT NULL,
            full_name         VARCHAR(200) NOT NULL,
            email             VARCHAR(150) NOT NULL,
            -- lower(email). users.email is UNIQUE but CASE-SENSITIVE in
            -- Postgres, and registration.py stores addresses with only
            -- .strip() applied, so 'A@x.com' and 'a@x.com' would otherwise be
            -- two slots for one person. Same trick as discount_codes.code_key.
            email_key         VARCHAR(150) NOT NULL,
            -- Per-employee invitation. SHA-256 only; single-use via used_at.
            invite_token_hash VARCHAR(64)  NULL UNIQUE,
            invite_expires_at TIMESTAMP    NULL,
            invite_used_at    TIMESTAMP    NULL,
            invite_revoked_at TIMESTAMP    NULL,
            registration_id   VARCHAR(8)   NULL,
            created_at        TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_intake_slot_email UNIQUE (intake_id, email_key),
            FOREIGN KEY (intake_id)       REFERENCES corporate_intakes(id) ON DELETE CASCADE,
            FOREIGN KEY (registration_id) REFERENCES registrations(id)     ON DELETE SET NULL
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_intake_slot_intake ON corporate_intake_slots (intake_id)")
    cur.execute("ALTER TABLE corporate_intake_slots ADD COLUMN IF NOT EXISTS entry_challenge_hash VARCHAR(64) NULL")
    cur.execute("ALTER TABLE corporate_intake_slots ADD COLUMN IF NOT EXISTS entry_code_hash VARCHAR(64) NULL")
    cur.execute("ALTER TABLE corporate_intake_slots ADD COLUMN IF NOT EXISTS entry_code_expires_at TIMESTAMP NULL")
    cur.execute("ALTER TABLE corporate_intake_slots ADD COLUMN IF NOT EXISTS entry_code_sent_at TIMESTAMP NULL")
    cur.execute("ALTER TABLE corporate_intake_slots ADD COLUMN IF NOT EXISTS entry_code_attempts INT NOT NULL DEFAULT 0")
    # A registration may be claimed by at most ONE slot, anywhere. Without
    # this the same submission could appear on two companies' rosters.
    cur.execute("""CREATE UNIQUE INDEX IF NOT EXISTS uq_intake_slot_registration
                   ON corporate_intake_slots (registration_id)
                   WHERE registration_id IS NOT NULL""")

    # Every notification we attempt to a company contact. Append-only, so a
    # retry is a new row and the history of what was sent survives. The
    # UNIQUE guard is what stops an accidental duplicate send of the same
    # event for the same subject.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS corporate_notifications (
            id          SERIAL PRIMARY KEY,
            intake_id   INT          NOT NULL,
            -- 'needs_correction' | 'payment_link'
            kind        VARCHAR(40)  NOT NULL,
            -- The thing the notice is about: a slot id for per-trainee
            -- notices, NULL for intake-wide ones.
            slot_id     INT          NULL,
            to_email    VARCHAR(150) NOT NULL,
            subject     VARCHAR(300) NULL,
            -- 'pending' | 'sent' | 'failed'
            status      VARCHAR(20)  NOT NULL DEFAULT 'pending',
            attempts    INT          NOT NULL DEFAULT 0,
            last_error  TEXT         NULL,
            dedupe_key  VARCHAR(120) NOT NULL,
            created_by  INT          NULL,
            created_at  TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
            sent_at     TIMESTAMP    NULL,
            CONSTRAINT uq_corp_notif_dedupe UNIQUE (dedupe_key),
            FOREIGN KEY (intake_id)  REFERENCES corporate_intakes(id)      ON DELETE CASCADE,
            FOREIGN KEY (slot_id)    REFERENCES corporate_intake_slots(id) ON DELETE SET NULL,
            FOREIGN KEY (created_by) REFERENCES users(id)                  ON DELETE SET NULL
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_corp_notif_intake ON corporate_notifications (intake_id, kind)")
    # Delivery ownership. A send is CLAIMED by generating an attempt_id and
    # leasing the row until attempt_expires_at; completion must quote the same
    # attempt_id. Without this, two requests could both believe they owned the
    # send, and a slow first attempt could overwrite a second one's outcome.
    cur.execute("ALTER TABLE corporate_notifications ADD COLUMN IF NOT EXISTS attempt_id VARCHAR(36) NULL")
    cur.execute("ALTER TABLE corporate_notifications ADD COLUMN IF NOT EXISTS attempt_started_at TIMESTAMP NULL")
    cur.execute("ALTER TABLE corporate_notifications ADD COLUMN IF NOT EXISTS attempt_expires_at TIMESTAMP NULL")
    # Which transport actually handled it, so a preview is never mistaken for
    # a real send. Only 'submitted' means an SMTP server accepted the message.
    cur.execute("ALTER TABLE corporate_notifications ADD COLUMN IF NOT EXISTS transport VARCHAR(20) NULL")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_corp_notif_open ON corporate_notifications (status) "
                "WHERE status <> 'submitted'")
    # Which invoice/link generation a notice belongs to. Folded into the
    # dedupe key so that intentionally replacing an invoice is not blocked
    # forever by the notification belonging to the invoice it replaced.
    cur.execute("ALTER TABLE corporate_notifications ADD COLUMN IF NOT EXISTS "
                "corporate_payment_id INT NULL")
    cur.execute("ALTER TABLE corporate_notifications ADD COLUMN IF NOT EXISTS "
                "link_version INT NOT NULL DEFAULT 0")
    # Everything the send needs, captured when the intent is authorised. A
    # RETRY must not depend on a browser still having the payment URL in a
    # form field — the operator retrying may be a different person, hours
    # later, from the unresolved queue.
    #
    # This does mean the payable URL is at rest. It is scoped to one invoice,
    # dies when the link is revoked or the version bumps, and the alternative
    # (re-minting on every retry) would silently break a link the company may
    # already have received.
    cur.execute("ALTER TABLE corporate_notifications ADD COLUMN IF NOT EXISTS "
                "payload TEXT NULL")

    # Requirement corrections the company is allowed to see. Deliberately
    # separate from any private review note: this text is written FOR the
    # applicant, and the company portal renders only this.
    cur.execute("ALTER TABLE registrations ADD COLUMN IF NOT EXISTS correction_note TEXT NULL")
    cur.execute("ALTER TABLE registrations ADD COLUMN IF NOT EXISTS correction_set_at TIMESTAMP NULL")
    # Bumped each time an admin asks for a correction. The notification
    # dedupe key includes it, so asking twice for the SAME correction sends
    # one email, while a genuinely new request after a resubmission sends a
    # new one.
    cur.execute("ALTER TABLE registrations ADD COLUMN IF NOT EXISTS correction_version INT NOT NULL DEFAULT 0")


    # ── Corporate bulk payments ───────────────────────────────────────────
    #
    # A company settles one invoice covering several already-approved
    # trainees. Deliberately its own table rather than a row in `payments`:
    # `payments.user_id` is NOT NULL and one corporate record covers many
    # users, and the per-trainee breakdown has to survive a price override.
    #
    # Account creation stays invitation-only — every trainee listed here got
    # in through the public form -> admin review -> emailed token flow, so
    # this table only ever *pays for* existing unpaid accounts.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS corporate_payments (
            id                  SERIAL PRIMARY KEY,
            reference           VARCHAR(40)   NOT NULL UNIQUE,
            company_name        VARCHAR(200)  NOT NULL,
            contact_person      VARCHAR(200)  NOT NULL,
            contact_email       VARCHAR(150)  NULL,
            contact_number      VARCHAR(30)   NULL,
            -- list_total is the sum of the per-trainee program prices;
            -- custom_total is what staff actually charged. Both are kept so
            -- the discount given is auditable after the fact.
            list_total_php      DECIMAL(12,2) NOT NULL,
            custom_total_php    DECIMAL(12,2) NULL,
            override_note       TEXT          NULL,
            override_by         INT           NULL,
            override_at         TIMESTAMP     NULL,
            -- What PayMongo was actually asked to charge, in integer
            -- centavos, so no float rounding can reach the gateway.
            amount_centavos     BIGINT        NOT NULL,
            status              VARCHAR(20)   NOT NULL DEFAULT 'pending',
            method              VARCHAR(10)   NULL,
            paymongo_id         VARCHAR(120)  NULL,
            expires_at          TIMESTAMP     NOT NULL,
            paid_at             TIMESTAMP     NULL,
            cancelled_at        TIMESTAMP     NULL,
            created_by          INT           NULL,
            created_at          TIMESTAMP     DEFAULT CURRENT_TIMESTAMP,
            receipt_id          VARCHAR(30)   NULL,
            receipt_hash        VARCHAR(66)   NULL,
            tx_hash             VARCHAR(66)   NULL,
            -- see payments.anchor_version
            anchor_version      SMALLINT      DEFAULT 2,
            qr_code_path        VARCHAR(255)  NULL,
            FOREIGN KEY (created_by)  REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY (override_by) REFERENCES users(id) ON DELETE SET NULL
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_corp_pay_status ON corporate_payments (status)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_corp_pay_pmid ON corporate_payments (paymongo_id)")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS corporate_payment_items (
            id                   SERIAL PRIMARY KEY,
            corporate_payment_id INT           NOT NULL,
            user_id              INT           NOT NULL,
            training_type        VARCHAR(250)  NOT NULL,
            form_type            VARCHAR(30)   NULL,
            price_php            DECIMAL(10,2) NOT NULL,
            price_label          VARCHAR(150)  NULL,
            CONSTRAINT uq_corp_item UNIQUE (corporate_payment_id, user_id),
            FOREIGN KEY (corporate_payment_id) REFERENCES corporate_payments(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id)              REFERENCES users(id)              ON DELETE CASCADE
        )
    """)

    # ── Training classes and their join codes ─────────────────────────────
    #
    # A class is a cohort a trainer runs: one company's paid employees, taking
    # one program together, with progress visible per person and in aggregate.
    #
    # The join code is Google-Classroom-style — short, shared, read aloud. It
    # is NOT a credential and NOT an entitlement. Everything it could be
    # mistaken for is checked independently at join time by
    # db/classes.py::join_class(): that the person is an approved trainee, that
    # their fee is paid, and that they are on THIS class's roster. The code
    # only says which class they mean. See the comment block there.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS training_classes (
            id                   SERIAL PRIMARY KEY,
            name                 VARCHAR(200) NOT NULL,
            -- The program. Decides the syllabus, exactly as for an individual
            -- trainee: a class cannot hand someone a different course.
            training_type        VARCHAR(250) NOT NULL,
            -- Where membership is authorised FROM. A class with neither is a
            -- staff-managed class: nobody can self-join it by code.
            intake_id            INT          NULL,
            corporate_payment_id INT          NULL,
            -- Stored in plaintext, deliberately, unlike every token in this
            -- schema. A classroom code is dictated to a room and typed by
            -- many people, so the trainer has to be able to read it back; and
            -- because it authorises nothing on its own, hashing it would cost
            -- that and buy no safety. Contrast corporate_intakes.coord_token_hash,
            -- which IS a credential and is therefore hashed.
            join_code            VARCHAR(12)  NOT NULL UNIQUE,
            join_open            BOOLEAN      NOT NULL DEFAULT TRUE,
            created_by           INT          NULL,
            created_at           TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
            closed_at            TIMESTAMP    NULL,
            FOREIGN KEY (intake_id)            REFERENCES corporate_intakes(id)  ON DELETE SET NULL,
            FOREIGN KEY (corporate_payment_id) REFERENCES corporate_payments(id) ON DELETE SET NULL,
            FOREIGN KEY (created_by)           REFERENCES users(id)              ON DELETE SET NULL
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_class_intake ON training_classes (intake_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_class_payment ON training_classes (corporate_payment_id)")
    cur.execute("ALTER TABLE training_classes ADD COLUMN IF NOT EXISTS instructor_id INT NULL REFERENCES users(id) ON DELETE SET NULL")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_class_instructor ON training_classes (instructor_id)")
    # Bind temporary company submission tokens to their server-side entry
    # authority. Dropping a browser session must not turn a shared-code grant
    # into a legacy invitation that bypasses link/code revocation.
    cur.execute("ALTER TABLE corporate_intake_slots ADD COLUMN IF NOT EXISTS entry_class_id INT NULL REFERENCES training_classes(id) ON DELETE SET NULL")
    cur.execute("ALTER TABLE corporate_intake_slots ADD COLUMN IF NOT EXISTS entry_link_hash VARCHAR(64) NULL")
    cur.execute("ALTER TABLE corporate_intake_slots ADD COLUMN IF NOT EXISTS entry_class_code_hash VARCHAR(64) NULL")
    # The canonical LMS program code (training / cea_training / cem_renewal /
    # …), which is what decides a syllabus. `training_type` above is free text
    # copied from the intake ("Online", "Hybrid, 5 days…") and is a LABEL
    # only: comparing it against a registration's raw training_type matched
    # two pieces of prose, not two programs. normalize_training_type() is the
    # single mapping, shared with onboarding and get_user_training_type().
    cur.execute("ALTER TABLE training_classes ADD COLUMN IF NOT EXISTS program_code VARCHAR(30) NULL")
    # Backfill from the AUTHORITATIVE program field, not from the free-text
    # label. corporate_intakes.form_type and corporate_payment_items.form_type
    # already hold a program code; training_type does not, so an old class
    # labelled "Online" could be CEM or CEA and guessing picks wrong.
    #
    # Rows that cannot be derived are left NULL on purpose. _authorise()
    # refuses a class with no program_code rather than defaulting, so an
    # ambiguous row blocks and gets reported instead of quietly admitting the
    # wrong programme.
    cur.execute("""
        UPDATE training_classes c SET program_code = i.form_type
          FROM corporate_intakes i
         WHERE c.intake_id = i.id
           AND c.program_code IS NULL
           AND i.form_type IS NOT NULL
    """)
    cur.execute("""
        UPDATE training_classes c SET program_code = sub.form_type
          FROM (SELECT it.corporate_payment_id AS pid,
                       MIN(it.form_type) AS form_type,
                       COUNT(DISTINCT it.form_type) AS variants
                  FROM corporate_payment_items it
                 WHERE it.form_type IS NOT NULL
                 GROUP BY it.corporate_payment_id) sub
         WHERE c.corporate_payment_id = sub.pid
           AND c.program_code IS NULL
           -- A mixed-programme invoice is genuinely ambiguous: leave it NULL.
           AND sub.variants = 1
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS training_class_members (
            id         SERIAL PRIMARY KEY,
            class_id   INT         NOT NULL,
            user_id    INT         NOT NULL,
            joined_at  TIMESTAMP   DEFAULT CURRENT_TIMESTAMP,
            -- What actually authorised this membership, recorded so an audit
            -- can tell a self-join from a staff addition. Never 'code': the
            -- code is the trigger, not the authority.
            authorised VARCHAR(20) NOT NULL DEFAULT 'roster'
                       CHECK (authorised IN ('roster','staff')),
            added_by   INT         NULL,
            CONSTRAINT uq_class_member UNIQUE (class_id, user_id),
            FOREIGN KEY (class_id) REFERENCES training_classes(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id)  REFERENCES users(id)            ON DELETE CASCADE,
            FOREIGN KEY (added_by) REFERENCES users(id)            ON DELETE SET NULL
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_class_member_user ON training_class_members (user_id)")

    # ── Hosted-checkout payment attempts ──────────────────────────────────
    #
    # One row per attempt to create a hosted Checkout Session. The row is
    # written BEFORE the remote call, carrying the idempotency key and an
    # immutable snapshot of what was requested. That ordering is the whole
    # point: if the response is lost, replaying the stored key is the only way
    # to discover whether a session exists, and a key generated at call time
    # would be gone with the response.
    #
    # `payment_intent_id` is nullable by design. v2 Checkout Session creation
    # DEFERS intent creation until the customer pays, so there is genuinely no
    # intent id at creation time. It is kept separate from the session id
    # because they are different namespaces and the legacy intent-only poll
    # cannot be used for a v2 session.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS corporate_payment_attempts (
            id                   SERIAL PRIMARY KEY,
            corporate_payment_id INT          NOT NULL,
            -- Our own attempt identity, quoted on every completion.
            attempt_ref          VARCHAR(36)  NOT NULL UNIQUE,
            idempotency_key      VARCHAR(255) NOT NULL UNIQUE,
            -- Immutable request snapshot: exactly what we asked the gateway
            -- for. Never rewritten, so a later dispute can be checked.
            request_amount_centavos BIGINT    NOT NULL,
            request_currency     VARCHAR(3)   NOT NULL DEFAULT 'PHP',
            request_reference    VARCHAR(40)  NOT NULL,
            request_payload      TEXT         NULL,
            environment          VARCHAR(10)  NOT NULL,
            -- creating | active | expired | paid | failed | unknown
            --   unknown = the create call's outcome was never observed; the
            --   recovery path must resolve it before anything else happens.
            status               VARCHAR(20)  NOT NULL DEFAULT 'creating',
            checkout_session_id  VARCHAR(120) NULL,
            checkout_url         TEXT         NULL,
            payment_intent_id    VARCHAR(120) NULL,
            paid_payment_id      VARCHAR(120) NULL,
            last_error           TEXT         NULL,
            created_by           INT          NULL,
            created_at           TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
            remote_created_at    TIMESTAMP    NULL,
            settled_at           TIMESTAMP    NULL,
            expired_at           TIMESTAMP    NULL,
            FOREIGN KEY (corporate_payment_id) REFERENCES corporate_payments(id) ON DELETE CASCADE,
            FOREIGN KEY (created_by)           REFERENCES users(id)             ON DELETE SET NULL
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_corp_attempt_payment "
                "ON corporate_payment_attempts (corporate_payment_id)")
    # Webhook matching key: our own stored session id.
    cur.execute("""CREATE UNIQUE INDEX IF NOT EXISTS uq_corp_attempt_session
                   ON corporate_payment_attempts (checkout_session_id)
                   WHERE checkout_session_id IS NOT NULL""")
    # At most ONE attempt may be open per invoice. A replacement cannot be
    # created while an earlier outcome is still unknown or still payable.
    cur.execute("""CREATE UNIQUE INDEX IF NOT EXISTS uq_corp_attempt_open
                   ON corporate_payment_attempts (corporate_payment_id)
                   WHERE status IN ('creating','active','unknown')""")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_corp_attempt_open_all "
                "ON corporate_payment_attempts (status) "
                "WHERE status IN ('creating','active','unknown')")
    # PayMongo retains an idempotency key for 24 hours. After that the SAME
    # key starts a NEW request, so an automatic replay past this moment would
    # create a second payable session instead of recovering the first. Stored
    # rather than recomputed so the window is explicit in the data.
    cur.execute("ALTER TABLE corporate_payment_attempts ADD COLUMN IF NOT EXISTS "
                "idempotency_expires_at TIMESTAMP NULL")
    cur.execute("UPDATE corporate_payment_attempts "
                "SET idempotency_expires_at = created_at + interval '24 hours' "
                "WHERE idempotency_expires_at IS NULL")
    # Settlement bookkeeping is a separate step from the invoice flip, so a
    # crash between them is recoverable: this records which attempt settled.
    cur.execute("ALTER TABLE corporate_payment_attempts ADD COLUMN IF NOT EXISTS "
                "settlement_confirmed_at TIMESTAMP NULL")
    # Explicit creation ownership. While this is in the future the creating
    # request owns the row, so reconciliation will not replay its idempotency
    # key underneath a call that may still be in flight.
    cur.execute("ALTER TABLE corporate_payment_attempts ADD COLUMN IF NOT EXISTS "
                "creation_lease_until TIMESTAMP NULL")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_corp_attempt_unconfirmed "
                "ON corporate_payment_attempts (status) "
                "WHERE status = 'paid' AND settlement_confirmed_at IS NULL")

    # ── Unresolved gateway events ─────────────────────────────────────────
    #
    # A webhook we could not match to an attempt, or could not validate, is
    # money we may already have received. Acknowledging it with a bare 200 and
    # a log line loses it. Stored verbatim so it can be replayed by hand once
    # the cause is understood — a session created but never persisted, for
    # example.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS unresolved_payment_events (
            id             SERIAL PRIMARY KEY,
            source         VARCHAR(20)  NOT NULL,
            event_type     VARCHAR(60)  NULL,
            checkout_session_id VARCHAR(120) NULL,
            payment_id     VARCHAR(120) NULL,
            reference_hint VARCHAR(60)  NULL,
            amount_centavos BIGINT      NULL,
            currency       VARCHAR(5)   NULL,
            livemode       BOOLEAN      NULL,
            reason         TEXT         NOT NULL,
            raw_event      TEXT         NOT NULL,
            resolved_at    TIMESTAMP    NULL,
            resolved_by    INT          NULL,
            resolution_note TEXT        NULL,
            received_at    TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (resolved_by) REFERENCES users(id) ON DELETE SET NULL
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_unresolved_open "
                "ON unresolved_payment_events (received_at) "
                "WHERE resolved_at IS NULL")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_unresolved_session "
                "ON unresolved_payment_events (checkout_session_id)")

    # The public payment link, and the version that scopes its notifications.
    cur.execute("ALTER TABLE corporate_payments ADD COLUMN IF NOT EXISTS pay_token_hash VARCHAR(64) NULL")
    cur.execute("ALTER TABLE corporate_payments ADD COLUMN IF NOT EXISTS pay_token_issued_at TIMESTAMP NULL")
    cur.execute("ALTER TABLE corporate_payments ADD COLUMN IF NOT EXISTS pay_token_revoked_at TIMESTAMP NULL")
    cur.execute("ALTER TABLE corporate_payments ADD COLUMN IF NOT EXISTS link_version INT NOT NULL DEFAULT 0")
    cur.execute("ALTER TABLE corporate_payments ADD COLUMN IF NOT EXISTS intake_id INT NULL")
    # Money that arrived but could not be matched or reconciled. Deliberately
    # a persistent flag, not a log line: it must stay visible until a human
    # clears it.
    cur.execute("ALTER TABLE corporate_payments ADD COLUMN IF NOT EXISTS needs_attention_at TIMESTAMP NULL")
    cur.execute("ALTER TABLE corporate_payments ADD COLUMN IF NOT EXISTS attention_reason TEXT NULL")
    cur.execute("""CREATE UNIQUE INDEX IF NOT EXISTS uq_corp_pay_token
                   ON corporate_payments (pay_token_hash)
                   WHERE pay_token_hash IS NOT NULL""")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_corp_pay_attention "
                "ON corporate_payments (needs_attention_at) "
                "WHERE needs_attention_at IS NOT NULL")

    # Append-only audit trail shown on the record's detail page. Separate from
    # `audit_logs` because it is surfaced to staff inline per record, not as a
    # global admin feed.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS corporate_payment_events (
            id                   SERIAL PRIMARY KEY,
            corporate_payment_id INT          NOT NULL,
            actor_id             INT          NULL,
            action               VARCHAR(60)  NOT NULL,
            details              TEXT         NULL,
            created_at           TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (corporate_payment_id) REFERENCES corporate_payments(id) ON DELETE CASCADE,
            FOREIGN KEY (actor_id)             REFERENCES users(id)              ON DELETE SET NULL
        )
    """)

    # ── Discount codes (individual trainees only) ─────────────────────────
    #
    # code_key is lower(code) with its own UNIQUE constraint — that is what
    # makes the code case-insensitively unique and lets a lookup be an index
    # hit instead of a sequential scan over lower(code).
    cur.execute("""
        CREATE TABLE IF NOT EXISTS discount_codes (
            id            SERIAL PRIMARY KEY,
            code          VARCHAR(40)  NOT NULL,
            code_key      VARCHAR(40)  NOT NULL UNIQUE,
            percent_off   SMALLINT     NOT NULL,
            expires_on    DATE         NOT NULL,
            max_uses      INT          NOT NULL,
            used          INT          NOT NULL DEFAULT 0,
            -- NULL = valid for every program; otherwise one training_type code
            training_type VARCHAR(250) NULL,
            is_active     SMALLINT     NOT NULL DEFAULT 1,
            created_by    INT          NULL,
            created_at    TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT ck_discount_pct CHECK (percent_off BETWEEN 1 AND 100),
            FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
        )
    """)

    # Which code a trainee's payment was taken at. Recorded when the intent is
    # created so an amount that reached PayMongo can always be explained.
    cur.execute("ALTER TABLE payments ADD COLUMN IF NOT EXISTS discount_code_id INT NULL")
    cur.execute("ALTER TABLE payments ADD COLUMN IF NOT EXISTS discount_percent SMALLINT NULL")
    cur.execute("ALTER TABLE payments ADD COLUMN IF NOT EXISTS discount_amount_php DECIMAL(10,2) NULL")
    cur.execute("""
        ALTER TABLE payments DROP CONSTRAINT IF EXISTS fk_payments_discount_code
    """)
    cur.execute("""
        ALTER TABLE payments ADD CONSTRAINT fk_payments_discount_code
        FOREIGN KEY (discount_code_id) REFERENCES discount_codes(id) ON DELETE SET NULL
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
