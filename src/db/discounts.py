"""Discount codes for individual trainee payments.

Codes never apply to corporate bulk payments — those carry a staff-set custom
total instead, and mixing the two would double-discount the same invoice.
"""
from datetime import date

import psycopg2.errors
import psycopg2.extras

from .core import get_db


def _key(code):
    return (code or "").strip().lower()


def create_discount_code(code, percent_off, expires_on, max_uses,
                         training_type=None, created_by=None):
    """Returns the new id, or None if the code is already taken. Uniqueness is
    case-insensitive: it is enforced on code_key, not on the display text."""
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute(
            """INSERT INTO discount_codes
                 (code, code_key, percent_off, expires_on, max_uses, training_type, created_by)
               VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (code.strip(), _key(code), int(percent_off), expires_on, int(max_uses),
             training_type or None, created_by),
        )
        new_id = cur.fetchone()[0]
        conn.commit()
        return new_id
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        return None
    finally:
        cur.close(); conn.close()


def update_discount_code(code_id, code, percent_off, expires_on, max_uses, training_type=None):
    """Returns True on success, False if the new code collides with another row."""
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute(
            """UPDATE discount_codes
               SET code=%s, code_key=%s, percent_off=%s, expires_on=%s,
                   max_uses=%s, training_type=%s
               WHERE id=%s""",
            (code.strip(), _key(code), int(percent_off), expires_on, int(max_uses),
             training_type or None, code_id),
        )
        conn.commit()
        return True
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        return False
    finally:
        cur.close(); conn.close()


def set_discount_active(code_id, active):
    conn = get_db(); cur = conn.cursor()
    cur.execute("UPDATE discount_codes SET is_active=%s WHERE id=%s", (1 if active else 0, code_id))
    conn.commit(); cur.close(); conn.close()


def delete_discount_code(code_id):
    conn = get_db(); cur = conn.cursor()
    cur.execute("DELETE FROM discount_codes WHERE id=%s", (code_id,))
    conn.commit(); cur.close(); conn.close()


def get_discount_codes():
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT d.*, u.fname, u.lname
        FROM discount_codes d
        LEFT JOIN users u ON d.created_by = u.id
        ORDER BY d.created_at DESC
    """)
    rows = [dict(r) for r in cur.fetchall()]
    cur.close(); conn.close()
    for r in rows:
        r["status"] = discount_status(r)
    return rows


def get_discount_code(code_id):
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM discount_codes WHERE id=%s", (code_id,))
    row = cur.fetchone()
    cur.close(); conn.close()
    return dict(row) if row else None


def get_discount_by_code(code):
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM discount_codes WHERE code_key=%s", (_key(code),))
    row = cur.fetchone()
    cur.close(); conn.close()
    return dict(row) if row else None


def discount_status(row):
    """active | inactive | expired | exhausted — what the management screen shows."""
    if not row.get("is_active"):
        return "inactive"
    if row.get("expires_on") and row["expires_on"] < date.today():
        return "expired"
    if (row.get("used") or 0) >= row["max_uses"]:
        return "exhausted"
    return "active"


def validate_discount(code, training_type):
    """(row, error) for a trainee trying `code` against their own program.

    The caller must recompute the charge from the returned row — never from
    anything the browser sent.
    """
    if not (code or "").strip():
        return None, "Enter a discount code."
    row = get_discount_by_code(code)
    if not row:
        return None, "That discount code does not exist."
    status = discount_status(row)
    if status == "inactive":
        return None, "That discount code is no longer active."
    if status == "expired":
        return None, "That discount code has expired."
    if status == "exhausted":
        return None, "That discount code has reached its redemption limit."
    if row.get("training_type") and row["training_type"] != training_type:
        return None, "That discount code does not apply to your program."
    return row, None


def redeem_discount(code_id):
    """Atomically burn one redemption. False if the code is already at its cap.

    `used < max_uses` inside the UPDATE is what makes this safe under
    concurrent payments — two webhooks racing on the last slot cannot both
    win, because the second one matches zero rows.
    """
    conn = get_db(); cur = conn.cursor()
    cur.execute(
        "UPDATE discount_codes SET used = used + 1 WHERE id=%s AND used < max_uses RETURNING used",
        (code_id,),
    )
    row = cur.fetchone()
    conn.commit(); cur.close(); conn.close()
    return row is not None
