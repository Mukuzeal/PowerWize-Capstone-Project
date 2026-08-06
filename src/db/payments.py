import psycopg2.extras

from .core import get_db


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


def get_user_id_for_paymongo(paymongo_id):
    """Look up the owning user_id for a PayMongo payment_intent/source id."""
    conn = get_db()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT user_id FROM payments WHERE paymongo_id=%s LIMIT 1", (paymongo_id,))
    row = cur.fetchone()
    cur.close(); conn.close()
    return row["user_id"] if row else None
