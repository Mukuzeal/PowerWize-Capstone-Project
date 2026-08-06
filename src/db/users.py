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


def get_users():
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT id, role, fname, lname, email, contact_number, company_name, created_at, archived_at FROM users ORDER BY id DESC")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [dict(r) for r in rows]
