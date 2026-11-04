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


def claim_account_invitation(reg_id, email, is_qualified):
    """(token, created) — mint ONE invitation per registration.

    The partial unique index below makes this repeat-safe at the database
    level: a second call while a live, unused invitation exists inserts
    nothing and returns created=False. That is what prevents a double submit,
    or a retry after a failed email, from producing two valid tokens.

    A token that was already USED is not blocking — the account exists, so
    there is nothing left to invite.
    """
    import secrets
    token = secrets.token_urlsafe(32)
    conn = get_db(); cur = conn.cursor()
    try:
        # Clear a lapsed, unused invitation so the partial unique index does
        # not block a legitimate re-issue. Only expired ones: a live token is
        # what makes this call a no-op, and a used one is history.
        cur.execute("DELETE FROM account_tokens WHERE reg_id = %s "
                    "AND used_at IS NULL AND expires_at <= NOW()", (reg_id,))
        cur.execute("""
            INSERT INTO account_tokens (token, reg_id, email, is_qualified, expires_at)
            SELECT %s, %s, %s, %s, %s
             WHERE NOT EXISTS (
                   SELECT 1 FROM account_tokens
                    WHERE reg_id = %s AND used_at IS NULL)
            RETURNING token
        """, (_hash_token(token), reg_id, email, int(is_qualified),
              datetime.now() + timedelta(days=7), reg_id))
        created = cur.fetchone() is not None
        conn.commit()
        return (token if created else None), created
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close(); conn.close()


def rotate_account_invitation(reg_id, email, is_qualified):
    """Replace an unused invitation with a fresh one. (token, rotated).

    This is how a resend works, and it ISSUES A NEW LINK rather than resending
    the old one. Only `sha256(token)` is ever stored, so the previous
    plaintext is genuinely unrecoverable — any claim that the same link can be
    sent again would be false. Rotating also means a link that may have leaked
    while bouncing around a mail system stops working.

    Refuses once the invitation has been used: at that point the account
    exists and there is nothing left to invite.
    """
    import secrets
    token = secrets.token_urlsafe(32)
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("SELECT 1 FROM account_tokens WHERE reg_id = %s AND used_at IS NOT NULL",
                    (reg_id,))
        if cur.fetchone():
            conn.rollback()
            return None, False
        cur.execute("DELETE FROM account_tokens WHERE reg_id = %s AND used_at IS NULL",
                    (reg_id,))
        cur.execute(
            "INSERT INTO account_tokens (token, reg_id, email, is_qualified, expires_at) "
            "VALUES (%s,%s,%s,%s,%s)",
            (_hash_token(token), reg_id, email, int(is_qualified),
             datetime.now() + timedelta(days=7)))
        conn.commit()
        return token, True
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close(); conn.close()


def account_exists_for_email(email):
    """True if a user account already exists for this address.

    Guards against inviting someone who has already signed up — the token
    would be dead weight and the email confusing. Compared case-insensitively
    because `users.email` is UNIQUE but case-SENSITIVE in Postgres while the
    registration forms store the address with only .strip() applied.
    """
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT 1 FROM users WHERE lower(email) = lower(%s) "
                "AND archived_at IS NULL", ((email or "").strip(),))
    found = cur.fetchone() is not None
    cur.close(); conn.close()
    return found


def invitation_status(reg_id):
    """What an admin needs to see about a registration's invitation."""
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT email, expires_at, used_at, created_at
          FROM account_tokens WHERE reg_id = %s
         ORDER BY created_at DESC LIMIT 1
    """, (reg_id,))
    row = cur.fetchone()
    cur.close(); conn.close()
    if not row:
        return {"state": "none"}
    if row["used_at"]:
        return {"state": "used", "at": row["used_at"], "email": row["email"]}
    if row["expires_at"] and row["expires_at"] < datetime.now():
        return {"state": "expired", "at": row["expires_at"], "email": row["email"]}
    return {"state": "active", "at": row["expires_at"], "email": row["email"]}


def redeem_invitation_and_create_account(token, password_hash, fname, lname,
                                         contact_number, company_name,
                                         training_type):
    """Claim the token AND create the account in ONE transaction.

    (user_id, error). Previously this spanned three connections — read the
    token, insert the user, mark the token used — and psycopg2 does not
    autocommit, so they were three transactions. A crash between them left a
    committed account with a still-valid token, or a spent token with no
    account. Two simultaneous posts of the same link raced the same way, with
    only `users.email UNIQUE` turning it into an unhandled IntegrityError.

    The guarded UPDATE is the concurrency control: exactly one caller claims
    the token, and the account insert shares its fate.
    """
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute("""
            UPDATE account_tokens SET used_at = NOW()
             WHERE token = %s AND used_at IS NULL AND expires_at > NOW()
            RETURNING reg_id, email, is_qualified
        """, (_hash_token(token),))
        tok = cur.fetchone()
        if not tok:
            conn.rollback()
            return None, "This link is invalid, expired, or already used."

        cur.execute("SELECT id FROM users WHERE lower(email) = lower(%s)", (tok["email"],))
        if cur.fetchone():
            conn.rollback()
            return None, "An account already exists for this email. Please log in."

        # `registration_id` is the authoritative link. Matching on the email
        # string was ambiguous: `registrations.email` is not unique, so a
        # person who registered twice had no single answer.
        cur.execute("""
            INSERT INTO users (role, fname, lname, email, password_hash,
                               contact_number, company_name, payment_status,
                               training_type, registration_id)
            VALUES ('trainee',%s,%s,%s,%s,%s,%s,'unpaid',%s,%s)
            RETURNING id
        """, (fname, lname, tok["email"], password_hash, contact_number or "",
              company_name or "", training_type, tok["reg_id"]))
        uid = cur.fetchone()["id"]
        conn.commit()
        return uid, None
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close(); conn.close()


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
