import psycopg2.extras

from .core import get_db


def log_payment(user_id, amount_php, method, paymongo_id,
                discount_code_id=None, discount_percent=None, discount_amount_php=None):
    """Record the intent before the gateway is called. The discount columns
    capture what the charge was actually computed from, so an amount that
    reached PayMongo can always be explained afterwards."""
    conn = get_db()
    cur  = conn.cursor()
    from .workflow import lms_registration_id
    reg_id=lms_registration_id(user_id,cur)
    cur.execute(
        "INSERT INTO payments (user_id, amount_php, method, paymongo_id, status, "
        "discount_code_id, discount_percent, discount_amount_php, registration_id) "
        "VALUES (%s,%s,%s,%s,'pending',%s,%s,%s,%s) RETURNING id",
        (user_id, amount_php, method, paymongo_id,
         discount_code_id, discount_percent, discount_amount_php,reg_id),
    )
    conn.commit()
    row_id = cur.fetchone()[0]
    cur.close(); conn.close()
    return row_id


def mark_payment_paid(paymongo_id):
    """True only for the call that actually moved the row pending -> paid.

    Card attach, the QRPH poll and the webhook can all report the same
    payment; the guarded UPDATE means exactly one of them sees True, which is
    what makes redeeming a discount code exactly-once.
    """
    conn = get_db()
    cur  = conn.cursor()
    cur.execute(
        "UPDATE payments SET status='paid', paid_at=NOW() WHERE paymongo_id=%s AND status='pending'",
        (paymongo_id,),
    )
    transitioned = cur.rowcount == 1
    conn.commit()
    cur.close(); conn.close()
    return transitioned


def get_payment_discount(paymongo_id):
    """(discount_code_id, discount_percent) for a payment, or (None, None)."""
    conn = get_db()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        "SELECT discount_code_id, discount_percent FROM payments WHERE paymongo_id=%s LIMIT 1",
        (paymongo_id,),
    )
    row = cur.fetchone()
    cur.close(); conn.close()
    if not row:
        return None, None
    return row["discount_code_id"], row["discount_percent"]


def mark_payment_failed(paymongo_id):
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("UPDATE payments SET status='failed' WHERE paymongo_id=%s AND status='pending'", (paymongo_id,))
    conn.commit()
    cur.close(); conn.close()


def mark_user_paid(user_id, registration_id=None):
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("UPDATE users SET payment_status='paid' WHERE id=%s AND (%s IS NULL OR registration_id=%s)",
                (user_id,registration_id,registration_id))
    conn.commit()
    cur.close(); conn.close()


def get_user_payment_status(user_id):
    from .workflow import sponsored_enrolment
    sponsor = sponsored_enrolment(user_id)
    if sponsor:
        return 'paid' if sponsor['paid'] else 'unpaid'
    conn = get_db()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    from .workflow import lms_registration_id
    reg_id=lms_registration_id(user_id,cur)
    cur.execute("""SELECT CASE WHEN registration_id IS NOT DISTINCT FROM %s THEN payment_status
        WHEN EXISTS(SELECT 1 FROM payments p WHERE p.user_id=users.id AND p.registration_id=%s AND p.status='paid')
        THEN 'paid' ELSE 'unpaid' END AS payment_status FROM users WHERE id=%s""", (reg_id,reg_id,user_id))
    row = cur.fetchone()
    cur.close(); conn.close()
    return row["payment_status"] if row else None


def get_payment_by_paymongo_id(paymongo_id):
    """The stored payment row, used to build its blockchain anchor."""
    conn = get_db()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM payments WHERE paymongo_id = %s", (paymongo_id,))
    row = cur.fetchone()
    cur.close(); conn.close()
    return dict(row) if row else None


def save_blockchain_receipt(paymongo_id, receipt_id, receipt_hash, tx_hash, qr_code_path,
                            anchor_version=1):
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("""
        UPDATE payments
        SET receipt_id=%s, receipt_hash=%s, tx_hash=%s, qr_code_path=%s, anchor_version=%s
        WHERE paymongo_id=%s
    """, (receipt_id, receipt_hash, tx_hash, qr_code_path, anchor_version, paymongo_id))
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
    from .workflow import lms_registration_id
    reg_id=lms_registration_id(user_id,cur)
    cur.execute("""
        SELECT * FROM payments
        WHERE user_id = %s AND status = 'paid' AND registration_id IS NOT DISTINCT FROM %s
        ORDER BY paid_at DESC LIMIT 1
    """, (user_id,reg_id))
    row = cur.fetchone()
    cur.close(); conn.close()
    return dict(row) if row else None


def get_user_id_for_paymongo(paymongo_id):
    """Look up the owning user_id for a PayMongo payment_intent/source id."""
    conn = get_db()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT user_id FROM payments WHERE paymongo_id=%s LIMIT 1", (paymongo_id,))
    row = cur.fetchone()
    cur.close(); conn.close()
    return row["user_id"] if row else None
