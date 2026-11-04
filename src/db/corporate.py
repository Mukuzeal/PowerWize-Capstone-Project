"""Corporate bulk payments: one invoice covering several approved trainees.

The trainees themselves are created the usual invitation-only way (public
form -> admin review -> emailed token -> /create-account/<token>); this module
only ever settles the fee for accounts that already exist and are still
unpaid, so nobody skips ID upload, selfie liveness or verification.
"""
import secrets
from datetime import datetime
from decimal import Decimal, InvalidOperation
import re

import psycopg2.extras

from .core import get_db
from .registrations import ACCOUNT_REGISTRATION_JOIN_SQL


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
        """ + ACCOUNT_REGISTRATION_JOIN_SQL + """
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


def corporate_price_edit_state(cid):
    """UI hint only; the write repeats these checks under the invoice lock."""
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute("""SELECT status, expires_at > NOW() AS unexpired, paymongo_id, pay_token_hash,
                          EXISTS (SELECT 1 FROM corporate_payment_attempts a
                                   WHERE a.corporate_payment_id=p.id) AS has_attempt
                         FROM corporate_payments p WHERE id=%s""", (cid,))
        row = cur.fetchone()
        if not row:
            return False, 'Invoice not found.'
        if row['status'] != 'pending' or not row['unexpired']:
            return False, 'Only a pending invoice that has not expired can change price.'
        if row['has_attempt'] or row['paymongo_id'] or row['pay_token_hash']:
            return False, ('A payment link or checkout attempt already exists for this invoice. '
                           'Its amount is fixed; use a replacement invoice for a different price.')
        return True, None
    finally:
        cur.close(); conn.close()


def update_corporate_price(cid, raw_total, note, actor_id, expected_centavos):
    """Edit before the first checkout attempt; preserve item/list prices.

    The invoice lock is shared with reserve_attempt(). An attempt cannot be
    inserted between the safety check and the amount update. Events and audit
    history commit with the price, not after it.
    """
    raw_total = (raw_total or '').strip()
    note = (note or '').strip()
    if not note:
        return None, 'A reason is required for changing the invoice price.', 400
    if len(note) > 2000:
        return None, 'Keep the override reason within 2,000 characters.', 400
    custom = None
    if raw_total:
        if not re.fullmatch(r'(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]{1,2})?', raw_total):
            return None, 'Enter a valid PHP total with no more than two decimal places.', 400
        try:
            custom = Decimal(raw_total.replace(',', ''))
        except InvalidOperation:
            return None, 'Enter a valid PHP total.', 400
        if custom <= 0 or custom > Decimal('9999999999.99'):
            return None, 'The custom total must be greater than zero and within the supported amount range.', 400
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute('SELECT *, expires_at > NOW() AS unexpired FROM corporate_payments WHERE id=%s FOR UPDATE', (cid,))
        row = cur.fetchone()
        if not row:
            conn.rollback(); return None, 'Invoice not found.', 404
        if row['status'] != 'pending' or not row['unexpired']:
            conn.rollback(); return None, 'Only a pending invoice that has not expired can change price.', 409
        cur.execute('SELECT 1 FROM corporate_payment_attempts WHERE corporate_payment_id=%s LIMIT 1', (cid,))
        if cur.fetchone() or row['paymongo_id'] or row['pay_token_hash']:
            conn.rollback(); return None, 'A payment link or checkout attempt already exists. Its amount is fixed; use a replacement invoice for a different price.', 409
        if row['amount_centavos'] != expected_centavos:
            conn.rollback(); return None, 'The invoice price changed since this panel opened. Reload it before saving.', 409
        charged = custom if custom is not None else row['list_total_php']
        centavos = int(charged * 100)
        if centavos <= 0:
            conn.rollback(); return None, 'The charged total must be greater than zero.', 400
        if row['custom_total_php'] == custom and row['amount_centavos'] == centavos and (row['override_note'] or '') == note:
            conn.rollback(); return dict(row), None, 200
        previous = row['amount_centavos']
        cur.execute("""UPDATE corporate_payments SET custom_total_php=%s, amount_centavos=%s,
                          override_note=%s, override_by=%s, override_at=NOW()
                        WHERE id=%s RETURNING *""", (custom, centavos, note, actor_id, cid))
        updated = dict(cur.fetchone())
        details = (f"Charged total changed from PHP {Decimal(previous)/100:,.2f} to PHP {charged:,.2f}. "
                   f"{'Restored published total' if custom is None else 'Custom price override'}. Reason: {note}")
        cur.execute("""INSERT INTO corporate_payment_events (corporate_payment_id,actor_id,action,details)
                       VALUES (%s,%s,'price_override',%s)""", (cid, actor_id, details))
        cur.execute("""INSERT INTO audit_logs (user_id,action,entity_type,entity_id,details)
                       VALUES (%s,'corporate_price_overridden','corporate_payment',%s,%s)""",
                    (actor_id, str(cid), details))
        conn.commit()
        return updated, None, 200
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close(); conn.close()


def update_corporate_email(cid, email, expected_email, actor_id):
    """Update this invoice and its intake, preserving prior delivery history.

    Lock order matches payment-send authorization: intake, invoice, notices.
    Lock notices too so an attempt claimed during this edit cannot use a
    stale recipient; the sender re-reads the contact after claiming its row.
    """
    email = (email or '').strip().lower()
    local, sep, domain = email.rpartition('@')
    label = r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?'
    if (len(email) > 254 or not sep or len(local) > 64
            or not re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+", local)
            or local.startswith('.') or local.endswith('.') or '..' in local
            or not re.fullmatch(label + r'(?:\.' + label + r')+', domain)):
        return None, 'Enter a valid company email address.', 400
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute('SELECT intake_id FROM corporate_payments WHERE id=%s', (cid,))
        initial = cur.fetchone()
        if not initial:
            conn.rollback(); return None, 'Invoice not found.', 404
        intake_id = initial['intake_id']
        intake = None
        if intake_id:
            cur.execute('SELECT id,contact_email FROM corporate_intakes WHERE id=%s FOR UPDATE', (intake_id,))
            intake = cur.fetchone()
        cur.execute('SELECT *, expires_at > NOW() AS unexpired FROM corporate_payments WHERE id=%s FOR UPDATE', (cid,))
        row = cur.fetchone()
        if not row or row['intake_id'] != intake_id:
            conn.rollback(); return None, 'The invoice changed. Reload it before saving.', 409
        if row['status'] != 'pending' or not row['unexpired']:
            conn.rollback(); return None, 'Only an unexpired pending invoice can change its company email.', 409
        if (row['contact_email'] or '').strip().lower() != (expected_email or '').strip().lower():
            conn.rollback(); return None, 'The company email changed since this panel opened. Reload it before saving.', 409
        cur.execute('SELECT id,status FROM corporate_notifications WHERE corporate_payment_id=%s OR intake_id=%s FOR UPDATE',
                    (cid, intake_id))
        if any(n['status'] == 'in_flight' for n in cur.fetchall()):
            conn.rollback(); return None, 'An email is currently being sent. Wait for its outcome before changing the address.', 409
        if row['contact_email'] == email and (not intake or intake['contact_email'] == email):
            conn.rollback(); return dict(row), None, 200
        cur.execute('UPDATE corporate_payments SET contact_email=%s WHERE id=%s RETURNING *', (email, cid))
        updated = dict(cur.fetchone())
        if intake:
            cur.execute('UPDATE corporate_intakes SET contact_email=%s WHERE id=%s', (email, intake_id))
        details = f"Company email changed from {row['contact_email'] or '(none)'} to {email}."
        if intake:
            details += ' Linked Company Intake contact updated; other invoices and delivery history retained.'
        cur.execute("""INSERT INTO corporate_payment_events (corporate_payment_id,actor_id,action,details)
                       VALUES (%s,%s,'contact_email_changed',%s)""", (cid, actor_id, details))
        cur.execute("""INSERT INTO audit_logs (user_id,action,entity_type,entity_id,details)
                       VALUES (%s,'corporate_email_changed','corporate_payment',%s,%s)""", (actor_id, str(cid), details))
        conn.commit()
        return updated, None, 200
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


def mark_corporate_paid(reference=None, paymongo_id=None, cid=None,
                        confirmed_payment_id=None, method=None):
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
            "UPDATE corporate_payments SET status='paid', paid_at=NOW(), "
            "paymongo_id=COALESCE(%s,paymongo_id), method=COALESCE(%s,method) "
            "WHERE " + where + " AND status='pending' RETURNING *",
            (confirmed_payment_id, method, param),
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


def get_corporate_receipt_by_id(receipt_id):
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute("SELECT * FROM corporate_payments WHERE receipt_id=%s AND status='paid'", (receipt_id,))
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        cur.close(); conn.close()


def save_corporate_receipt(cid, receipt_id, receipt_hash, tx_hash, qr_code_path,
                           anchor_version=2):
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        UPDATE corporate_payments
        SET receipt_id=%s, receipt_hash=%s, tx_hash=%s, qr_code_path=%s, anchor_version=%s
        WHERE id=%s
    """, (receipt_id, receipt_hash, tx_hash, qr_code_path, anchor_version, cid))
    conn.commit(); cur.close(); conn.close()


def pending_remote_closures():
    """Invoices closed locally whose gateway session may still be payable.

    `expire_stale_corporate_payments()` and `cancel_corporate_payment()` both
    change local status only. Sessions never expire on their own, so without
    this the link stays live behind a closed invoice. Reconciliation consumes
    this list and closes them remotely.
    """
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT a.*, p.status AS invoice_status, p.reference
          FROM corporate_payment_attempts a
          JOIN corporate_payments p ON p.id = a.corporate_payment_id
         WHERE p.status IN ('cancelled', 'expired')
           AND a.status IN ('creating', 'active', 'unknown')
         ORDER BY a.created_at
    """)
    rows = [dict(r) for r in cur.fetchall()]
    cur.close(); conn.close()
    return rows
