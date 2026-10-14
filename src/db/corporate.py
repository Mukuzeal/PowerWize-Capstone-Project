"""Corporate bulk payments: one invoice covering several approved trainees.

The trainees themselves are created the usual invitation-only way (public
form -> admin review -> emailed token -> /create-account/<token>); this module
only ever settles the fee for accounts that already exist and are still
unpaid, so nobody skips ID upload, selfie liveness or verification.
"""
import secrets
from datetime import datetime

import psycopg2.extras

from .core import get_db


def _ref():
    """Short, unguessable, URL- and PayMongo-metadata-safe reference. This is
    what ties a gateway callback back to the record."""
    return "CORP-" + secrets.token_hex(6).upper()


def get_unpaid_trainees():
    """Every unpaid trainee, with the registration fields the price is derived
    from. Ordered by company so staff building an invoice for one employer can
    find their people together.

    `pending_corp_id` flags anyone already sitting on another unsettled
    invoice, so the same trainee is not billed twice in parallel.
    """
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT u.id, u.fname, u.lname, u.email, u.company_name, u.training_type,
               r.form_type, r.training_type AS reg_training_type, r.form_label,
               c.corporate_payment_id AS pending_corp_id
        FROM users u
        LEFT JOIN LATERAL (
            SELECT form_type, training_type, form_label
            FROM registrations
            WHERE email = u.email
            ORDER BY submitted_at DESC LIMIT 1
        ) r ON TRUE
        LEFT JOIN LATERAL (
            SELECT i.corporate_payment_id
            FROM corporate_payment_items i
            JOIN corporate_payments p ON p.id = i.corporate_payment_id
            WHERE i.user_id = u.id AND p.status = 'pending'
            LIMIT 1
        ) c ON TRUE
        WHERE u.role = 'trainee' AND u.archived_at IS NULL AND u.payment_status = 'unpaid'
        ORDER BY COALESCE(u.company_name, ''), u.lname, u.fname
    """)
    rows = [dict(r) for r in cur.fetchall()]
    cur.close(); conn.close()
    return rows


def create_corporate_payment(company_name, contact_person, contact_email, contact_number,
                             items, list_total, custom_total, override_note,
                             amount_centavos, expires_at, created_by):
    """Insert the record and its per-trainee lines in one transaction.

    `items` is a list of dicts: user_id, training_type, form_type, price_php,
    price_label. Returns (id, reference).
    """
    conn = get_db(); cur = conn.cursor()
    try:
        reference = _ref()
        overridden = custom_total is not None
        cur.execute("""
            INSERT INTO corporate_payments
              (reference, company_name, contact_person, contact_email, contact_number,
               list_total_php, custom_total_php, override_note, override_by, override_at,
               amount_centavos, expires_at, created_by)
            VALUES (%s,%s,%s,%s,%s, %s,%s,%s,%s,%s, %s,%s,%s)
            RETURNING id
        """, (reference, company_name, contact_person, contact_email or None,
              contact_number or None, list_total, custom_total, override_note or None,
              created_by if overridden else None, datetime.now() if overridden else None,
              amount_centavos, expires_at, created_by))
        cid = cur.fetchone()[0]
        for it in items:
            cur.execute("""
                INSERT INTO corporate_payment_items
                  (corporate_payment_id, user_id, training_type, form_type, price_php, price_label)
                VALUES (%s,%s,%s,%s,%s,%s)
            """, (cid, it["user_id"], it["training_type"], it.get("form_type"),
                  it["price_php"], it.get("price_label")))
        conn.commit()
        return cid, reference
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close(); conn.close()


def expire_stale_corporate_payments():
    """Flip pending records past their expiry. Called before any list/detail
    read, so a stale row never shows as payable."""
    conn = get_db(); cur = conn.cursor()
    cur.execute(
        "UPDATE corporate_payments SET status='expired' "
        "WHERE status='pending' AND expires_at < NOW() RETURNING id"
    )
    expired = [r[0] for r in cur.fetchall()]
    for cid in expired:
        cur.execute(
            "INSERT INTO corporate_payment_events (corporate_payment_id, action, details) "
            "VALUES (%s, 'expired', 'Payment window closed before the invoice was settled.')",
            (cid,),
        )
    conn.commit(); cur.close(); conn.close()
    return expired


def get_corporate_payments(status=None, q=None):
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    sql = """
        SELECT p.*, u.fname AS creator_fname, u.lname AS creator_lname,
               (SELECT COUNT(*) FROM corporate_payment_items i
                 WHERE i.corporate_payment_id = p.id) AS trainee_count
        FROM corporate_payments p
        LEFT JOIN users u ON p.created_by = u.id
        WHERE 1=1
    """
    params = []
    if status:
        sql += " AND p.status = %s"
        params.append(status)
    if q:
        sql += " AND (p.company_name ILIKE %s OR p.contact_person ILIKE %s OR p.reference ILIKE %s)"
        like = "%" + q + "%"
        params += [like, like, like]
    sql += " ORDER BY p.created_at DESC"
    cur.execute(sql, params)
    rows = [dict(r) for r in cur.fetchall()]
    cur.close(); conn.close()
    return rows


def get_corporate_payment(cid=None, reference=None, paymongo_id=None):
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if cid is not None:
        cur.execute("SELECT * FROM corporate_payments WHERE id=%s", (cid,))
    elif reference is not None:
        cur.execute("SELECT * FROM corporate_payments WHERE reference=%s", (reference,))
    else:
        cur.execute("SELECT * FROM corporate_payments WHERE paymongo_id=%s", (paymongo_id,))
    row = cur.fetchone()
    cur.close(); conn.close()
    return dict(row) if row else None


def get_corporate_items(cid):
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT i.*, u.fname, u.lname, u.email, u.payment_status
        FROM corporate_payment_items i
        JOIN users u ON i.user_id = u.id
        WHERE i.corporate_payment_id = %s
        ORDER BY u.lname, u.fname
    """, (cid,))
    rows = [dict(r) for r in cur.fetchall()]
    cur.close(); conn.close()
    return rows


def add_corporate_event(cid, actor_id, action, details=None):
    conn = get_db(); cur = conn.cursor()
    cur.execute(
        "INSERT INTO corporate_payment_events (corporate_payment_id, actor_id, action, details) "
        "VALUES (%s,%s,%s,%s)",
        (cid, actor_id, action, details),
    )
    conn.commit(); cur.close(); conn.close()


def get_corporate_events(cid):
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT e.*, u.fname, u.lname, u.role
        FROM corporate_payment_events e
        LEFT JOIN users u ON e.actor_id = u.id
        WHERE e.corporate_payment_id = %s
        ORDER BY e.created_at ASC, e.id ASC
    """, (cid,))
    rows = [dict(r) for r in cur.fetchall()]
    cur.close(); conn.close()
    return rows


def set_corporate_intent(cid, method, paymongo_id):
    """Record which gateway intent is currently outstanding for this invoice.

    Only touches a still-pending row, so a late retry cannot re-open a record
    that has already been paid or cancelled.
    """
    conn = get_db(); cur = conn.cursor()
    cur.execute(
        "UPDATE corporate_payments SET method=%s, paymongo_id=%s "
        "WHERE id=%s AND status='pending'",
        (method, paymongo_id, cid),
    )
    changed = cur.rowcount
    conn.commit(); cur.close(); conn.close()
    return changed == 1


def mark_corporate_paid(reference=None, paymongo_id=None, cid=None):
    """Settle the invoice: flip the record to paid and mark every listed
    trainee paid, in one transaction.

    Returns the record dict if this call is the one that settled it, None if
    it was already settled (or cancelled/expired). That makes every caller —
    webhook, QRPH poll, card return — idempotent: a duplicate delivery matches
    zero rows on the guarded UPDATE and does nothing.
    """
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        if reference is not None:
            where, param = "reference=%s", reference
        elif paymongo_id is not None:
            where, param = "paymongo_id=%s", paymongo_id
        else:
            where, param = "id=%s", cid
        cur.execute(
            "UPDATE corporate_payments SET status='paid', paid_at=NOW() "
            "WHERE " + where + " AND status='pending' RETURNING *",
            (param,),
        )
        row = cur.fetchone()
        if not row:
            conn.rollback()
            return None
        cur.execute("""
            UPDATE users SET payment_status='paid'
            WHERE id IN (SELECT user_id FROM corporate_payment_items
                          WHERE corporate_payment_id = %s)
        """, (row["id"],))
        unlocked = cur.rowcount
        cur.execute(
            "INSERT INTO corporate_payment_events (corporate_payment_id, action, details) "
            "VALUES (%s, 'paid', %s)",
            (row["id"], "Payment confirmed. " + str(unlocked) + " trainee account(s) unlocked."),
        )
        conn.commit()
        return dict(row)
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close(); conn.close()


def cancel_corporate_payment(cid):
    conn = get_db(); cur = conn.cursor()
    cur.execute(
        "UPDATE corporate_payments SET status='cancelled', cancelled_at=NOW() "
        "WHERE id=%s AND status='pending'",
        (cid,),
    )
    changed = cur.rowcount
    conn.commit(); cur.close(); conn.close()
    return changed == 1


def save_corporate_receipt(cid, receipt_id, receipt_hash, tx_hash, qr_code_path,
                           anchor_version=2):
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        UPDATE corporate_payments
        SET receipt_id=%s, receipt_hash=%s, tx_hash=%s, qr_code_path=%s, anchor_version=%s
        WHERE id=%s
    """, (receipt_id, receipt_hash, tx_hash, qr_code_path, anchor_version, cid))
    conn.commit(); cur.close(); conn.close()
