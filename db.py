from datetime import datetime, timedelta
import hashlib
import mysql.connector

DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "",
    "database": "EwizeDB",
}

MONTHS_PY = ["January","February","March","April","May","June",
             "July","August","September","October","November","December"]

TYPE_OFFSETS = {
    "training":  [0, 1, 2, 6, 7, 8, 9],
    "selfpaced": [0, 1, 2],
    "renewal":   [0, 1],
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
    return mysql.connector.connect(**DB_CONFIG)


def init_db():
    base = mysql.connector.connect(
        host=DB_CONFIG["host"], user=DB_CONFIG["user"], password=DB_CONFIG["password"]
    )
    cur = base.cursor()
    cur.execute(f"CREATE DATABASE IF NOT EXISTS `{DB_CONFIG['database']}`")
    cur.close()
    base.close()

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS batches (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            type ENUM('training','renewal') NOT NULL,
            start_date DATE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS registrations (
            id           VARCHAR(8)   PRIMARY KEY,
            form_type    VARCHAR(30)  NOT NULL,
            form_label   VARCHAR(50)  NOT NULL,
            submitted_at DATETIME     NOT NULL,
            title        VARCHAR(20),
            full_name    VARCHAR(200),
            middle_name  VARCHAR(100),
            residence    VARCHAR(300),
            company_name    VARCHAR(200),
            designation     VARCHAR(150),
            company_address VARCHAR(300),
            contact_number  VARCHAR(30),
            email           VARCHAR(150),
            birthdate    VARCHAR(20),
            age          VARCHAR(5),
            doe_expiry   VARCHAR(20),
            training_type VARCHAR(250),
            batch_id      INT NULL,
            photo_id     VARCHAR(255),
            resume       VARCHAR(255),
            expired_doe  VARCHAR(255),
            valid_id     VARCHAR(255),
            status       ENUM('pending','accepted','rejected') NOT NULL DEFAULT 'pending',
            FOREIGN KEY (batch_id) REFERENCES batches(id) ON DELETE SET NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INT AUTO_INCREMENT PRIMARY KEY,
            role ENUM('admin','employee','trainee') NOT NULL,
            fname VARCHAR(100) NOT NULL,
            lname VARCHAR(100) NOT NULL,
            email VARCHAR(150) NOT NULL UNIQUE,
            password_hash VARCHAR(255) NOT NULL,
            contact_number VARCHAR(20),
            company_name VARCHAR(150),
            payment_status ENUM('unpaid','paid') NOT NULL DEFAULT 'unpaid',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            archived_at TIMESTAMP NULL DEFAULT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id           INT AUTO_INCREMENT PRIMARY KEY,
            user_id      INT NOT NULL,
            amount_php   DECIMAL(10,2) NOT NULL,
            method       ENUM('card','qrph') NOT NULL,
            paymongo_id  VARCHAR(120) NOT NULL,
            status       ENUM('pending','paid','failed') NOT NULL DEFAULT 'pending',
            receipt_id   VARCHAR(30)  NULL,
            receipt_hash VARCHAR(66)  NULL,
            tx_hash      VARCHAR(66)  NULL,
            qr_code_path VARCHAR(255) NULL,
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            paid_at      TIMESTAMP NULL DEFAULT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS account_tokens (
            token      VARCHAR(64)  PRIMARY KEY,
            reg_id     VARCHAR(8)   NOT NULL,
            email      VARCHAR(150) NOT NULL,
            is_qualified TINYINT(1) NOT NULL DEFAULT 1,
            expires_at DATETIME     NOT NULL,
            used_at    DATETIME     NULL DEFAULT NULL,
            created_at TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (reg_id) REFERENCES registrations(id) ON DELETE CASCADE
        )
    """)
    # Add is_qualified column to registrations if missing
    cur.execute("""
        SELECT COUNT(*) FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'registrations' AND COLUMN_NAME = 'is_qualified'
    """, (DB_CONFIG["database"],))
    if cur.fetchone()[0] == 0:
        cur.execute("ALTER TABLE registrations ADD COLUMN is_qualified TINYINT(1) NOT NULL DEFAULT 1 AFTER status")

    # Add payment_status column to users if missing
    cur.execute("""
        SELECT COUNT(*) FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'users' AND COLUMN_NAME = 'payment_status'
    """, (DB_CONFIG["database"],))
    if cur.fetchone()[0] == 0:
        cur.execute("ALTER TABLE users ADD COLUMN payment_status ENUM('unpaid','paid') NOT NULL DEFAULT 'paid' AFTER company_name")

    # Add batch_id column if the table already existed without it
    cur.execute("""
        SELECT COUNT(*) FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'registrations' AND COLUMN_NAME = 'batch_id'
    """, (DB_CONFIG["database"],))
    if cur.fetchone()[0] == 0:
        cur.execute("ALTER TABLE registrations ADD COLUMN batch_id INT NULL")
        cur.execute("ALTER TABLE registrations ADD FOREIGN KEY (batch_id) REFERENCES batches(id) ON DELETE SET NULL")

    # Migrate status ENUM from 'declined' to 'rejected'
    cur.execute("""
        SELECT COLUMN_TYPE FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'registrations' AND COLUMN_NAME = 'status'
    """, (DB_CONFIG["database"],))
    row = cur.fetchone()
    if row and "declined" in row[0]:
        cur.execute("UPDATE registrations SET status = 'rejected' WHERE status = 'declined'")
        cur.execute("ALTER TABLE registrations MODIFY COLUMN status ENUM('pending','accepted','rejected') NOT NULL DEFAULT 'pending'")

    # Add email column if missing
    cur.execute("""
        SELECT COUNT(*) FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'registrations' AND COLUMN_NAME = 'email'
    """, (DB_CONFIG["database"],))
    if cur.fetchone()[0] == 0:
        cur.execute("ALTER TABLE registrations ADD COLUMN email VARCHAR(150) AFTER contact_number")

    # Drop legacy schedule column if it exists
    cur.execute("""
        SELECT COUNT(*) FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'registrations' AND COLUMN_NAME = 'schedule'
    """, (DB_CONFIG["database"],))
    if cur.fetchone()[0] > 0:
        cur.execute("ALTER TABLE registrations DROP COLUMN schedule")

    for col, definition in [
        ("receipt_id",   "VARCHAR(30)  NULL"),
        ("receipt_hash", "VARCHAR(66)  NULL"),
        ("tx_hash",      "VARCHAR(66)  NULL"),
        ("qr_code_path", "VARCHAR(255) NULL"),
    ]:
        cur.execute("""
            SELECT COUNT(*) FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'payments' AND COLUMN_NAME = %s
        """, (DB_CONFIG["database"], col))
        if cur.fetchone()[0] == 0:
            cur.execute(f"ALTER TABLE payments ADD COLUMN {col} {definition}")

    conn.commit()
    cur.close()
    conn.close()


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
    return result


def get_batches_full():
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id, name, type, start_date, created_at FROM batches ORDER BY start_date")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


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
            photo_id, resume, expired_doe, valid_id
        ) VALUES (%s,%s,%s,%s, %s,%s,%s,%s, %s,%s,%s, %s,%s,%s,%s,%s, %s,%s, %s,%s,%s,%s)
    """, (
        entry.get("id"),           entry.get("form_type"),   entry.get("form_label"), entry.get("submitted_at"),
        entry.get("title"),        entry.get("full_name"),   entry.get("middle_name"), entry.get("residence"),
        entry.get("company_name"), entry.get("designation"), entry.get("company_address"),
        entry.get("contact_number"), entry.get("email"), entry.get("birthdate"), entry.get("age"), entry.get("doe_expiry"),
        entry.get("training_type"), entry.get("batch_id") or None,
        entry.get("photo_id"), entry.get("resume"), entry.get("expired_doe"), entry.get("valid_id"),
    ))
    conn.commit()
    cur.close()
    conn.close()


def get_registrations():
    conn = get_db()
    cur  = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT r.*, b.name AS batch_name, b.start_date AS batch_start
        FROM registrations r
        LEFT JOIN batches b ON r.batch_id = b.id
        ORDER BY r.submitted_at DESC
    """)
    rows = cur.fetchall()
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
    return token  # raw token goes in the email link, hash stays in DB


def get_account_token(token):
    conn = get_db()
    cur  = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT t.*, r.full_name, r.title, r.contact_number, r.company_name
        FROM account_tokens t
        JOIN registrations r ON t.reg_id = r.id
        WHERE t.token = %s
    """, (_hash_token(token),))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row


def mark_token_used(token):
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("UPDATE account_tokens SET used_at = NOW() WHERE token = %s", (_hash_token(token),))
    conn.commit()
    cur.close()
    conn.close()


def get_users():
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id, role, fname, lname, email, contact_number, company_name, created_at, archived_at FROM users ORDER BY id DESC")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def get_registration_by_email(email):
    conn = get_db()
    cur  = conn.cursor(dictionary=True)
    cur.execute(
        "SELECT form_type, form_label, training_type, status, submitted_at FROM registrations WHERE email=%s ORDER BY submitted_at DESC LIMIT 1",
        (email,)
    )
    row = cur.fetchone()
    cur.close(); conn.close()
    return row


# ── Payment helpers ───────────────────────────────────────────────────────────

def log_payment(user_id, amount_php, method, paymongo_id):
    conn = get_db()
    cur  = conn.cursor()
    cur.execute(
        "INSERT INTO payments (user_id, amount_php, method, paymongo_id, status) VALUES (%s,%s,%s,%s,'pending')",
        (user_id, amount_php, method, paymongo_id),
    )
    conn.commit()
    row_id = cur.lastrowid
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
    cur  = conn.cursor(dictionary=True)
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
    cur  = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT p.*, u.fname, u.lname, u.email
        FROM payments p
        JOIN users u ON p.user_id = u.id
        WHERE p.receipt_id = %s
    """, (receipt_id,))
    row = cur.fetchone()
    cur.close(); conn.close()
    return row


def get_receipt_by_user(user_id):
    conn = get_db()
    cur  = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT * FROM payments
        WHERE user_id = %s AND status = 'paid'
        ORDER BY paid_at DESC LIMIT 1
    """, (user_id,))
    row = cur.fetchone()
    cur.close(); conn.close()
    return row


