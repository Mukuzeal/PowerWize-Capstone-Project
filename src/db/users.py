import hashlib
from datetime import datetime, timedelta

import psycopg2.extras

from .core import get_db


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
        SELECT t.*, r.full_name, r.title, r.contact_number, r.company_name,
               r.training_type, r.form_type
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


def get_user_basic_info(user_id):
    """fname/lname/email/payment_status for the trainee portal page."""
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        "SELECT fname, lname, email, payment_status FROM users WHERE id=%s",
        (user_id,)
    )
    row = cur.fetchone()
    cur.close(); conn.close()
    return dict(row) if row else None


# ── Login lockout ─────────────────────────────────────────────────────────────

MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_MINUTES     = 5


def register_failed_login(email):
    """Increments the failed-attempt counter; locks the account once it hits
    MAX_LOGIN_ATTEMPTS. Returns {'failed_login_attempts', 'locked_until'}."""
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        UPDATE users
        SET failed_login_attempts = failed_login_attempts + 1,
            locked_until = CASE WHEN failed_login_attempts + 1 >= %s
                                 THEN NOW() + (%s * INTERVAL '1 minute')
                                 ELSE locked_until END
        WHERE email = %s
        RETURNING failed_login_attempts, locked_until
    """, (MAX_LOGIN_ATTEMPTS, LOCKOUT_MINUTES, email.lower()))
    row = cur.fetchone()
    conn.commit(); cur.close(); conn.close()
    return dict(row)


def reset_login_attempts(email):
    conn = get_db(); cur = conn.cursor()
    cur.execute(
        "UPDATE users SET failed_login_attempts=0, locked_until=NULL WHERE email=%s",
        (email.lower(),)
    )
    conn.commit(); cur.close(); conn.close()


def get_users():
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT id, role, fname, lname, email, contact_number, company_name, training_type, payment_status, created_at, archived_at FROM users ORDER BY id DESC")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [dict(r) for r in rows]


# ── Per-user capability overrides ─────────────────────────────────────────────
#
# Only deviations from the role default are stored, so an untouched account has
# no rows and follows its role exactly. See src/permissions.py for which
# capabilities and roles this applies to.

def get_user_capabilities(user_id):
    """{capability: bool} overrides for one user; empty dict if none."""
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT capability, granted FROM user_capabilities WHERE user_id = %s",
                (user_id,))
    rows = cur.fetchall()
    cur.close(); conn.close()
    return {r["capability"]: bool(r["granted"]) for r in rows}


def get_all_user_capabilities():
    """{user_id: {capability: bool}} for every user that has an override.

    One query for the whole admin users table rather than one per row.
    """
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT user_id, capability, granted FROM user_capabilities")
    rows = cur.fetchall()
    cur.close(); conn.close()
    out = {}
    for r in rows:
        out.setdefault(r["user_id"], {})[r["capability"]] = bool(r["granted"])
    return out


def set_user_capability(user_id, capability, granted, set_by=None):
    """Record an override. `granted=None` clears it, falling back to the role
    default — that keeps the table free of rows that merely restate the role."""
    conn = get_db(); cur = conn.cursor()
    if granted is None:
        cur.execute("DELETE FROM user_capabilities WHERE user_id=%s AND capability=%s",
                    (user_id, capability))
    else:
        cur.execute("""
            INSERT INTO user_capabilities (user_id, capability, granted, set_by)
            VALUES (%s,%s,%s,%s)
            ON CONFLICT (user_id, capability)
            DO UPDATE SET granted=EXCLUDED.granted, set_by=EXCLUDED.set_by, set_at=NOW()
        """, (user_id, capability, 1 if granted else 0, set_by))
    conn.commit(); cur.close(); conn.close()


def clear_user_capabilities(user_id):
    """Drop every override for a user — used when their role changes, so stale
    deviations from an old role cannot linger."""
    conn = get_db(); cur = conn.cursor()
    cur.execute("DELETE FROM user_capabilities WHERE user_id = %s", (user_id,))
    conn.commit(); cur.close(); conn.close()
