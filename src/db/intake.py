"""Company intake and roster.

A company declares up front who it intends to enrol. That expected list is
what makes "has NOT submitted yet" answerable at all — a `registrations` row
only exists once someone submits.

Membership is always by explicit slot. `company_name` is free text and
`email` is not unique in `registrations`, so neither can identify who belongs
to which company.

Scope note: nothing here grants payment or creates accounts. A slot's
invitation leads to the ordinary public registration form, whose submission
still goes through the existing admin review.
"""
import hashlib
import secrets
from datetime import datetime, timedelta

import psycopg2.extras

from .core import get_db
from .corporate import _ref

# How long an invitation / coordinator link stays usable unless told otherwise.
DEFAULT_INVITE_DAYS = 14
DEFAULT_COORD_DAYS  = 30

# Derived per-trainee states shown on the roster. `registrations.status` stays
# the source of truth; these are a projection of it, never a second copy.
SLOT_NOT_SUBMITTED    = "not_submitted"
SLOT_PENDING_REVIEW   = "pending_review"
SLOT_NEEDS_CORRECTION = "needs_correction"
SLOT_APPROVED         = "approved"
SLOT_REJECTED         = "rejected"


def hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _new_token():
    return secrets.token_urlsafe(32)


# ── Intake ───────────────────────────────────────────────────────────────────

def create_intake(company_name, contact_person, contact_email, contact_number,
                  form_type, training_type, created_by):
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO corporate_intakes
                (company_name, contact_person, contact_email, contact_number,
                 form_type, training_type, created_by)
            VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id
        """, (company_name, contact_person, contact_email.strip().lower(),
              contact_number or None, form_type, training_type or None, created_by))
        iid = cur.fetchone()[0]
        conn.commit()
        return iid
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close(); conn.close()


def get_intake(intake_id=None, coord_token=None):
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if intake_id is not None:
        cur.execute("SELECT * FROM corporate_intakes WHERE id = %s", (intake_id,))
    else:
        cur.execute("SELECT * FROM corporate_intakes WHERE coord_token_hash = %s",
                    (hash_token(coord_token),))
    row = cur.fetchone()
    cur.close(); conn.close()
    return dict(row) if row else None


def get_intakes(status=None, archived=None):
    """List intakes; archived=None includes both views for the admin filters."""
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    sql = """
        SELECT i.*,
               (SELECT COUNT(*) FROM corporate_intake_slots s
                 WHERE s.intake_id = i.id) AS slot_count,
               (SELECT COUNT(*) FROM corporate_intake_slots s
                 WHERE s.intake_id = i.id AND s.registration_id IS NOT NULL) AS submitted_count
        FROM corporate_intakes i
    """
    params = []
    conditions = []
    if status:
        conditions.append("i.status = %s")
        params.append(status)
    if archived is not None:
        conditions.append("i.archived_at IS " + ("NOT NULL" if archived else "NULL"))
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY i.created_at DESC"
    cur.execute(sql, params)
    rows = [dict(r) for r in cur.fetchall()]
    cur.close(); conn.close()
    return rows


def set_intake_archived(intake_id, archived, actor_id=None):
    """Change archive metadata only. Return the changed row, or None on replay.

    Repeated requests preserve the original archive timestamp and actor.
    Enrollment status, tokens, registrations, invoices and classes stay intact.
    """
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        if archived:
            cur.execute("""UPDATE corporate_intakes
                              SET archived_at = NOW(), archived_by = %s
                            WHERE id = %s AND archived_at IS NULL RETURNING *""",
                        (actor_id, intake_id))
        else:
            cur.execute("""UPDATE corporate_intakes
                              SET archived_at = NULL, archived_by = NULL
                            WHERE id = %s AND archived_at IS NOT NULL RETURNING *""",
                        (intake_id,))
        row = cur.fetchone()
        conn.commit()
        return dict(row) if row else None
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close(); conn.close()


def issue_coordinator_token(intake_id, days=DEFAULT_COORD_DAYS):
    """Mint a fresh coordinator link. Returns the plaintext token ONCE; only
    its hash is stored. Re-issuing replaces the previous link."""
    token = _new_token()
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        UPDATE corporate_intakes
           SET coord_token_hash = %s, coord_expires_at = %s, coord_revoked_at = NULL
         WHERE id = %s AND status IN ('open','ready')
    """, (hash_token(token), datetime.now() + timedelta(days=days), intake_id))
    changed = cur.rowcount
    conn.commit(); cur.close(); conn.close()
    return token if changed == 1 else None


def revoke_coordinator_token(intake_id):
    conn = get_db(); cur = conn.cursor()
    cur.execute("UPDATE corporate_intakes SET coord_revoked_at = NOW() "
                "WHERE id = %s AND coord_revoked_at IS NULL", (intake_id,))
    changed = cur.rowcount
    conn.commit(); cur.close(); conn.close()
    return changed == 1


def coordinator_access(coord_token):
    """(intake, reason) — the intake if this link may be used right now.

    Unknown, expired and revoked all return the same `reason` to the caller's
    eye; distinguishing them to an anonymous visitor would be an oracle.
    """
    if not coord_token:
        return None, "invalid"
    intake = get_intake(coord_token=coord_token)
    if not intake:
        return None, "invalid"
    if intake["coord_revoked_at"] is not None:
        return None, "invalid"
    if intake["coord_expires_at"] and intake["coord_expires_at"] < datetime.now():
        return None, "invalid"
    if intake["status"] == "cancelled":
        return None, "invalid"
    return intake, None


# ── Roster slots ─────────────────────────────────────────────────────────────

def add_slot(intake_id, full_name, email, invite_days=DEFAULT_INVITE_DAYS):
    """Add one expected trainee. Returns (slot_id, invite_token) or
    (None, None) if that email is already on this intake's roster."""
    token = _new_token()
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO corporate_intake_slots
                (intake_id, full_name, email, email_key,
                 invite_token_hash, invite_expires_at)
            VALUES (%s,%s,%s,%s,%s,%s)
            ON CONFLICT (intake_id, email_key) DO NOTHING
            RETURNING id
        """, (intake_id, full_name.strip(), email.strip(), email.strip().lower(),
              hash_token(token), datetime.now() + timedelta(days=invite_days)))
        row = cur.fetchone()
        conn.commit()
        return (row[0], token) if row else (None, None)
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close(); conn.close()


def get_slots(intake_id):
    """Roster rows joined to their registration, with the derived state.

    The company-facing projection lives here so the portal and the admin view
    cannot disagree about what "approved" means.
    """
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT s.*, r.status AS reg_status, r.submitted_at, r.is_qualified,
               r.correction_note, r.correction_set_at, r.form_type,
               r.selfie_with_id, r.selfie_reviewed_at, r.selfie_outcome,
               r.documents_purged_at, r.photo_id, r.resume, r.expired_doe,
               r.valid_id
        FROM corporate_intake_slots s
        LEFT JOIN registrations r ON r.id = s.registration_id
        WHERE s.intake_id = %s
        ORDER BY s.full_name
    """, (intake_id,))
    rows = []
    for r in cur.fetchall():
        d = dict(r)
        d["derived_status"] = _derive_slot_status(d)
        d["readiness"] = _slot_readiness(d)
        rows.append(d)
    cur.close(); conn.close()
    return rows


def _slot_readiness(slot):
    """review_policy.readiness() for a slot's registration, or None.

    Routed through the shared rule so the roster, the admin console, account
    invitation issuance and payment eligibility all answer "is this person
    approved?" identically.
    """
    if not slot.get("registration_id"):
        return None
    from review_policy import readiness
    return readiness({
        "status":              slot.get("reg_status"),
        "form_type":           slot.get("form_type"),
        "selfie_with_id":      slot.get("selfie_with_id"),
        "selfie_reviewed_at":  slot.get("selfie_reviewed_at"),
        "selfie_outcome":      slot.get("selfie_outcome"),
        "documents_purged_at": slot.get("documents_purged_at"),
        "is_qualified":        slot.get("is_qualified", 1),
        "photo_id":            slot.get("photo_id"),
        "resume":              slot.get("resume"),
        "expired_doe":         slot.get("expired_doe"),
        "valid_id":            slot.get("valid_id"),
    })


def _derive_slot_status(slot):
    """Project registration state onto the roster states.

    Derived, never stored: a stored copy drifts from `registrations.status`,
    which is the only thing admin review writes.

    `approved` means the SHARED readiness rule is satisfied — accepted AND
    identity review finished successfully. An accepted registration whose
    selfie is still pending or was rejected is NOT approved here, which is
    what keeps payment eligibility honest.
    """
    if not slot.get("registration_id"):
        return SLOT_NOT_SUBMITTED
    status = (slot.get("reg_status") or "").lower()
    if status == "rejected":
        return SLOT_REJECTED
    if status == "needs_correction":
        return SLOT_NEEDS_CORRECTION
    r = _slot_readiness(slot)
    if r and r["ready"]:
        return SLOT_APPROVED
    return SLOT_PENDING_REVIEW


def get_slot_by_invite(invite_token):
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT s.*, i.form_type, i.training_type, i.company_name, i.status AS intake_status
        FROM corporate_intake_slots s
        JOIN corporate_intakes i ON i.id = s.intake_id
        WHERE s.invite_token_hash = %s
    """, (hash_token(invite_token),))
    row = cur.fetchone()
    cur.close(); conn.close()
    return dict(row) if row else None


def invitation_state(invite_token):
    """(slot, reason) — the slot if this invitation may be redeemed now."""
    if not invite_token:
        return None, "invalid"
    slot = get_slot_by_invite(invite_token)
    if not slot:
        return None, "invalid"
    if slot["invite_revoked_at"] is not None:
        return None, "invalid"
    if slot["invite_used_at"] is not None:
        return None, "used"
    if slot["invite_expires_at"] and slot["invite_expires_at"] < datetime.now():
        return None, "invalid"
    if slot["intake_status"] in ("cancelled", "closed"):
        return None, "invalid"
    if slot["registration_id"]:
        return None, "used"
    return slot, None


def revoke_slot_invite(slot_id):
    conn = get_db(); cur = conn.cursor()
    cur.execute("UPDATE corporate_intake_slots SET invite_revoked_at = NOW() "
                "WHERE id = %s AND invite_revoked_at IS NULL", (slot_id,))
    changed = cur.rowcount
    conn.commit(); cur.close(); conn.close()
    return changed == 1


def replace_slot_invite(slot_id, invite_days=DEFAULT_INVITE_DAYS):
    """Rotate an unsubmitted slot's invitation, locking parent before slot."""
    token = _new_token()
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute("""
            SELECT i.id, i.status
              FROM corporate_intakes i
              JOIN corporate_intake_slots s ON s.intake_id = i.id
             WHERE s.id = %s
             FOR UPDATE OF i
        """, (slot_id,))
        intake = cur.fetchone()
        if not intake or intake["status"] not in ("open", "ready"):
            conn.rollback()
            return None, None
        cur.execute("""
            UPDATE corporate_intake_slots
               SET invite_token_hash = %s, invite_expires_at = %s,
                   invite_revoked_at = NULL
             WHERE id = %s AND invite_used_at IS NULL AND registration_id IS NULL
            RETURNING id, intake_id, full_name, invite_expires_at
        """, (hash_token(token), datetime.now() + timedelta(days=invite_days), slot_id))
        row = cur.fetchone()
        if not row:
            conn.rollback()
            return None, None
        conn.commit()
        return dict(row), token
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close(); conn.close()


def claim_slot_with_registration(invite_token, reg_id, insert_registration_sql, params,
                                 shared_token=None, email_key=None,
                                 registration_class_id=None, registration_code_hash=None):
    """Validate the invitation, insert the registration and attach it to the
    slot — in ONE transaction on ONE connection.

    This is the requirement that cannot be met by calling three helpers in
    sequence: `get_db()` opens a new connection per call and psycopg2 does not
    autocommit, so separate helpers are separate transactions. A crash between
    them would leave a consumed invitation with no registration, or a
    registration attached to nothing.

    Returns (reg_id, None) on success or (None, reason) on refusal.
    """
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        # Lock the parent intake FIRST and re-read its status inside the
        # transaction. Without this, an admin closing or cancelling the intake
        # can interleave with a submission: the earlier check would have
        # passed, the slot would be claimed, and a registration would attach
        # to an intake that is no longer accepting any.
        #
        # Locking the parent before the child also fixes the lock order for
        # every intake operation, so concurrent submissions and admin changes
        # cannot deadlock against each other.
        cur.execute("""
            SELECT i.id, i.status, s.entry_class_id, s.entry_link_hash, s.entry_class_code_hash
              FROM corporate_intakes i
              JOIN corporate_intake_slots s ON s.intake_id = i.id
             WHERE s.invite_token_hash = %s
             FOR UPDATE OF i
        """, (hash_token(invite_token),))
        parent = cur.fetchone()
        if not parent:
            conn.rollback()
            return None, "invalid"
        if parent["status"] in ("closed", "cancelled"):
            conn.rollback()
            return None, "closed"

        # Stored entry bindings remain authoritative even if a client strips
        # the session and submits its temporary token via a legacy form URL.
        entry_link_hash = parent.get('entry_link_hash')
        if shared_token or entry_link_hash:
            cur.execute("""
                SELECT id FROM corporate_intakes WHERE id=%s AND registration_token_hash=%s
                  AND registration_revoked_at IS NULL AND registration_expires_at > NOW()
            """, (parent['id'], entry_link_hash or hash_token(shared_token)))
            if not cur.fetchone():
                conn.rollback()
                return None, "invalid"

        if entry_link_hash:
            registration_class_id = parent['entry_class_id']
            registration_code_hash = parent['entry_class_code_hash']
            if registration_class_id is None:
                conn.rollback()
                return None, "invalid"
        if registration_class_id is not None:
            cur.execute("SELECT join_code FROM training_classes "
                        "WHERE id=%s AND intake_id=%s AND join_open=TRUE FOR SHARE",
                        (registration_class_id, parent['id']))
            cls = cur.fetchone()
            if not cls or not registration_code_hash or not secrets.compare_digest(
                    hash_token(cls['join_code']), registration_code_hash):
                conn.rollback()
                return None, "invalid"

        # Claim the invitation. The guarded UPDATE is the concurrency control
        # between two simultaneous submissions: exactly one matches a row.
        cur.execute("""
            UPDATE corporate_intake_slots
               SET invite_used_at = NOW()
             WHERE invite_token_hash = %s
               AND invite_used_at IS NULL
               AND invite_revoked_at IS NULL
               AND (invite_expires_at IS NULL OR invite_expires_at > NOW())
               AND registration_id IS NULL AND (%s IS NULL OR email_key=%s)
            RETURNING id, intake_id
        """, (hash_token(invite_token), email_key, email_key))
        claimed = cur.fetchone()
        if not claimed:
            conn.rollback()
            return None, "invalid"

        # `registrations.id` is an application-generated VARCHAR(8), so the
        # caller already knows it; nothing is read back.
        cur.execute(insert_registration_sql, params)
        cur.execute(
            "UPDATE corporate_intake_slots SET registration_id = %s WHERE id = %s",
            (reg_id, claimed["id"]))
        conn.commit()
        return reg_id, None
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close(); conn.close()


# ── Eligibility for the company payment link ─────────────────────────────────

def payment_link_eligibility(intake_id):
    """(eligible: bool, reason: str, detail: dict) — recomputed from current
    rows every time it is asked.

    Never cached and never trusted from the client: the admin button is only a
    hint, and the send path calls this again server-side.
    """
    intake = get_intake(intake_id=intake_id)
    if not intake:
        return False, "No such intake.", {}
    slots = get_slots(intake_id)
    if not slots:
        return False, "The roster is empty.", {}

    counts = {}
    for s in slots:
        counts[s["derived_status"]] = counts.get(s["derived_status"], 0) + 1
    detail = {"total": len(slots), "counts": counts,
              "already_sent_at": intake["payment_link_sent_at"]}

    # NOTE: payment_link_sent_at is NOT consulted as a lock here. Send-once is
    # owned by corporate_notifications (uq_corp_notif_dedupe, scoped to the
    # invoice's link_version), so replacing an invoice stays possible. This
    # column is surfaced in `detail` for display only.
    if intake["status"] == "cancelled":
        return False, "This intake is cancelled.", detail

    outstanding = [s for s in slots if s["derived_status"] != SLOT_APPROVED]
    if outstanding:
        # Named so staff can see exactly who is holding it up.
        detail["outstanding"] = [
            {"name": s["full_name"], "state": s["derived_status"],
             "label": s['readiness']['display_label'] if s['readiness'] else 'Not submitted'} for s in outstanding
        ]
        return False, (f"{len(outstanding)} of {len(slots)} expected trainee(s) "
                       f"are not approved yet."), detail
    return True, "All expected trainees are approved.", detail


def set_correction_and_queue_notice(reg_id, note, actor_id):
    """Record the correction AND its notification intent in ONE transaction.

    (result, error). `result` carries the notification id when one was
    created, or None when this correction event had already been queued.

    The two must commit together: a correction without an intent means the
    company is never told, and an intent without a correction means telling
    them about something that is not recorded. `correction_version` is bumped
    here and folded into the dedupe key, so re-asking for the SAME correction
    does not queue a second email while a genuinely new request after a
    resubmission does.

    The slot and intake are looked up from the registration, so a registration
    with no company attachment simply records the correction and queues
    nothing.
    """
    from .notifications import queue_notification

    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute("""
            UPDATE registrations
               SET correction_note = %s,
                   correction_set_at = NOW(),
                   correction_version = correction_version + 1,
                   status = 'needs_correction'
             WHERE id = %s
            RETURNING correction_version, full_name
        """, (note, reg_id))
        reg = cur.fetchone()
        if not reg:
            conn.rollback()
            return None, "No such registration."

        cur.execute("""
            SELECT s.id AS slot_id, s.full_name, i.id AS intake_id,
                   i.contact_email, i.company_name
              FROM corporate_intake_slots s
              JOIN corporate_intakes i ON i.id = s.intake_id
             WHERE s.registration_id = %s
        """, (reg_id,))
        slot = cur.fetchone()
        if not slot:
            conn.commit()
            return {"notification_id": None, "company": None}, None

        notif_id = queue_notification(
            cur, slot["intake_id"], "needs_correction", slot["contact_email"],
            f"Action needed: {slot['full_name']} — {slot['company_name']} training registration",
            dedupe_key=f"correction:{reg_id}:v{reg['correction_version']}",
            slot_id=slot["slot_id"], created_by=actor_id)
        conn.commit()
        return {"notification_id": notif_id, "company": slot["company_name"],
                "to_email": slot["contact_email"], "slot_name": slot["full_name"]}, None
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close(); conn.close()


def authorize_payment_link_send(intake_id, corporate_payment_id, link_version,
                                to_email, subject, actor_id, payload=None):
    """Create the durable send intent for a company payment link.

    (notification_id, error). The notification row — not
    `payment_link_sent_at` — is the lock: it carries the attempt lease, the
    attempt history and the outcome, and `uq_corp_notif_dedupe` is what makes
    a double-click harmless.

    Eligibility is revalidated INSIDE this transaction with the intake row
    locked, so a roster change or a review landing between the admin seeing
    the button and pressing it cannot authorize a send that is no longer
    justified.

    The dedupe key is scoped to (payment, link_version), so deliberately
    replacing an invoice produces a new sendable event instead of being
    blocked forever by the notice belonging to the invoice it replaced.
    """
    from .notifications import queue_notification

    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute("SELECT id, status FROM corporate_intakes WHERE id = %s FOR UPDATE",
                    (intake_id,))
        intake = cur.fetchone()
        if not intake:
            conn.rollback()
            return None, "No such intake."
        if intake["status"] == "cancelled":
            conn.rollback()
            return None, "This intake is cancelled."

        # Re-derive approval from the rows as they stand right now, holding
        # the lock. `payment_link_eligibility` is the read-only view of the
        # same rule used by the UI.
        cur.execute("""
            SELECT s.id, s.registration_id, r.status AS reg_status, r.form_type,
                   r.selfie_with_id, r.selfie_reviewed_at, r.selfie_outcome,
                   r.documents_purged_at, r.is_qualified,
                   r.photo_id, r.resume, r.expired_doe, r.valid_id
              FROM corporate_intake_slots s
              LEFT JOIN registrations r ON r.id = s.registration_id
             WHERE s.intake_id = %s
        """, (intake_id,))
        slots = [dict(r) for r in cur.fetchall()]
        if not slots:
            conn.rollback()
            return None, "The roster is empty."

        from review_policy import readiness
        unapproved = []
        for s in slots:
            if not s["registration_id"]:
                unapproved.append("a trainee who has not submitted")
                continue
            r = readiness({**s, "status": s["reg_status"]})
            if not r["ready"]:
                unapproved.append(s["registration_id"])
        if unapproved:
            conn.rollback()
            return None, (f"{len(unapproved)} of {len(slots)} expected trainee(s) "
                          f"are no longer approved — the roster changed. "
                          f"Re-check before sending.")

        # Approval is not coverage. A trainee added AND approved after the
        # invoice was raised passes the check above while being absent from
        # the invoice — so the company would be asked to pay an amount that
        # does not cover its own roster. Compare account identities directly.
        cur.execute("""
            SELECT u.id
              FROM corporate_intake_slots s
              JOIN users u ON u.registration_id = s.registration_id
                          AND u.archived_at IS NULL
             WHERE s.intake_id = %s
        """, (intake_id,))
        roster_users = {r["id"] for r in cur.fetchall()}
        cur.execute("SELECT user_id FROM corporate_payment_items "
                    "WHERE corporate_payment_id = %s", (corporate_payment_id,))
        invoiced_users = {r["user_id"] for r in cur.fetchall()}

        missing = roster_users - invoiced_users
        extra   = invoiced_users - roster_users
        if missing or extra:
            conn.rollback()
            parts = []
            if missing:
                parts.append(f"{len(missing)} approved trainee(s) are NOT on "
                             f"this invoice")
            if extra:
                parts.append(f"{len(extra)} invoice line(s) are no longer on "
                             f"the roster")
            return None, (" and ".join(parts) + ". Raise a replacement invoice "
                          "covering the current roster, or remove the "
                          "difference, before sending.")

        # Contact edits must not reuse another recipient's delivery record.
        # The intake lock serializes this check with edits and other sends;
        # retain the historical key for the first recipient of a link version.
        cur.execute('SELECT contact_email,status,link_version,pay_token_revoked_at,expires_at > NOW() AS unexpired FROM corporate_payments WHERE id=%s AND intake_id=%s FOR UPDATE',
                    (corporate_payment_id, intake_id))
        invoice = cur.fetchone()
        if (not invoice or invoice['status'] != 'pending' or not invoice['unexpired']
                or invoice['pay_token_revoked_at'] or invoice['link_version'] != link_version
                or (invoice['contact_email'] or '').strip().lower() != (to_email or '').strip().lower()):
            conn.rollback()
            return None, 'The invoice or company email changed. Reload it before sending.'
        cur.execute('SELECT to_email FROM corporate_notifications WHERE corporate_payment_id=%s AND link_version=%s AND kind=%s',
                    (corporate_payment_id, link_version, 'payment_link'))
        previous = cur.fetchall()
        if any(n['to_email'].strip().lower() == to_email.strip().lower() for n in previous):
            conn.rollback()
            return None, 'A payment link notice for this invoice version and recipient already exists. Use Retry on that notice.'
        dedupe_key = f'paylink:{corporate_payment_id}:v{link_version}'
        if previous:
            import hashlib
            dedupe_key += ':to:' + hashlib.sha256(to_email.strip().lower().encode()).hexdigest()
        notif_id = queue_notification(
            cur, intake_id, "payment_link", to_email, subject,
            dedupe_key=dedupe_key,
            created_by=actor_id)
        if notif_id is None:
            conn.rollback()
            return None, ("A payment link notice for this invoice version has "
                          "already been raised. Use Retry on that notice, or "
                          "issue a new invoice link.")
        # The retry payload is written in THIS transaction, not a follow-up
        # call. A crash in between used to leave a queued notification with no
        # retry URL while its dedupe key was already consumed — unsendable and
        # unretryable at the same time.
        #
        # Encrypted at rest: unlike every other secret here it must be read
        # back, so it cannot be hashed. That means the "database holds only
        # hashes" property no longer covers this column, which is why it is
        # encrypted, excluded from logs, and dies when the link is revoked.
        stored = None
        if payload is not None:
            import json
            from secretbox import encrypt
            stored = encrypt(json.dumps(payload))

        cur.execute("""UPDATE corporate_notifications
                          SET corporate_payment_id = %s, link_version = %s,
                              payload = %s
                        WHERE id = %s""",
                    (corporate_payment_id, link_version, stored, notif_id))
        conn.commit()
        return notif_id, None
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close(); conn.close()


def note_payment_link_submitted(intake_id):
    """Refresh the DISPLAY timestamp after a real SMTP submission.

    Deliberately not a lock and not a guard. `corporate_notifications` owns
    send-once; this column exists only so the console can show "last sent"
    without joining. It is updated *after* the transport accepted the message
    and never for a preview or a mock, so a development run cannot make the
    console claim a company was emailed.
    """
    conn = get_db(); cur = conn.cursor()
    cur.execute("UPDATE corporate_intakes SET payment_link_sent_at = NOW() "
                "WHERE id = %s", (intake_id,))
    conn.commit(); cur.close(); conn.close()


def invoiceable_roster(intake_id):
    """Who on this roster can be billed, and who cannot — with the reason.

    A corporate invoice line needs a `users.id`, because that is what
    settlement flips to paid. An approved applicant who has not yet created
    their account therefore cannot be invoiced yet, and saying so plainly
    beats silently dropping them from the total.

    The account is found through `users.registration_id`, the authoritative
    link — not by matching email strings, which are neither unique in
    `registrations` nor case-consistent.
    """
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT s.id AS slot_id, s.full_name, s.email, s.registration_id,
               r.status AS reg_status, r.form_type, r.training_type,
               r.selfie_with_id, r.selfie_reviewed_at, r.selfie_outcome,
               r.documents_purged_at, r.is_qualified,
               r.photo_id, r.resume, r.expired_doe, r.valid_id,
               u.id AS user_id, u.payment_status
          FROM corporate_intake_slots s
          LEFT JOIN registrations r ON r.id = s.registration_id
          LEFT JOIN users u ON u.registration_id = s.registration_id
                           AND u.archived_at IS NULL
         WHERE s.intake_id = %s
         ORDER BY s.full_name
    """, (intake_id,))
    rows = [dict(r) for r in cur.fetchall()]
    cur.close(); conn.close()

    from review_policy import readiness
    billable, blocked = [], []
    for s in rows:
        if not s["registration_id"]:
            blocked.append({**s, "reason": "Has not submitted a registration yet."})
            continue
        r = readiness({**s, "status": s["reg_status"]})
        if not r["ready"]:
            blocked.append({**s, "reason": " ".join(r["blockers"])})
            continue
        if not s["user_id"]:
            blocked.append({**s, "reason": (
                "Approved, but has not created their account yet — an invoice "
                "line needs the account it will mark paid.")})
            continue
        if s["payment_status"] == "paid":
            blocked.append({**s, "reason": "Already paid."})
            continue
        billable.append(s)
    return billable, blocked


def create_invoice_for_intake(intake_id, expiry_at, created_by, price_fn):
    """Validate the roster AND create the invoice in ONE transaction.

    (result, error). `price_fn(form_type, training_type)` returns the fee dict
    or None; pricing stays in `pricing.py` while the locking lives here.

    The same rule the preview shows is enforced here, with the intake row
    locked: if ANYONE on the roster cannot be billed, nothing is created. The
    previous split — preview says "cannot create", POST creates anyway for
    whoever happens to be billable — produced an invoice that silently
    undercharged, and a roster change between the two calls could change the
    answer underneath the operator.
    """
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute("SELECT * FROM corporate_intakes WHERE id = %s FOR UPDATE",
                    (intake_id,))
        intake = cur.fetchone()
        if not intake:
            conn.rollback()
            return None, "No such intake."
        intake = dict(intake)
        if intake["status"] == "cancelled":
            conn.rollback()
            return None, "This intake is cancelled."

        cur.execute("""
            SELECT s.id AS slot_id, s.full_name, s.email, s.registration_id,
                   r.status AS reg_status, r.form_type, r.training_type,
                   r.selfie_with_id, r.selfie_reviewed_at, r.selfie_outcome,
                   r.documents_purged_at, r.is_qualified,
                   r.photo_id, r.resume, r.expired_doe, r.valid_id,
                   u.id AS user_id, u.payment_status
              FROM corporate_intake_slots s
              LEFT JOIN registrations r ON r.id = s.registration_id
              LEFT JOIN users u ON u.registration_id = s.registration_id
                               AND u.archived_at IS NULL
             WHERE s.intake_id = %s
             ORDER BY s.full_name
        """, (intake_id,))
        slots = [dict(r) for r in cur.fetchall()]
        if not slots:
            conn.rollback()
            return None, "The roster is empty."

        from review_policy import readiness
        items, total, blocked = [], 0.0, []
        for s in slots:
            if not s["registration_id"]:
                blocked.append((s["full_name"], "has not submitted a registration"))
                continue
            rd = readiness({**s, "status": s["reg_status"]})
            if not rd["ready"]:
                blocked.append((s["full_name"], " ".join(rd["blockers"])))
                continue
            if not s["user_id"]:
                blocked.append((s["full_name"], "has not created their account yet"))
                continue
            if s["payment_status"] == "paid":
                blocked.append((s["full_name"], "is already paid"))
                continue
            fee = price_fn(s["form_type"], s["training_type"])
            if not fee:
                blocked.append((s["full_name"], "has no published price"))
                continue
            total += fee["total"]
            items.append({"user_id": s["user_id"],
                          "training_type": s["training_type"] or s["form_type"],
                          "form_type": s["form_type"], "price_php": fee["total"],
                          "price_label": fee.get("label", "")})

        if blocked:
            conn.rollback()
            return None, ("Every expected trainee must be billable before an "
                          "invoice can be created. Outstanding: "
                          + "; ".join(f"{n} ({why})" for n, why in blocked))

        reference = _ref()
        amount_centavos = int(round(total * 100))
        cur.execute("""
            INSERT INTO corporate_payments
              (reference, company_name, contact_person, contact_email,
               contact_number, list_total_php, amount_centavos, expires_at,
               created_by, intake_id)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
        """, (reference, intake["company_name"], intake["contact_person"],
              intake["contact_email"], intake["contact_number"],
              round(total, 2), amount_centavos, expiry_at, created_by, intake_id))
        cid = cur.fetchone()["id"]
        for it in items:
            cur.execute("""
                INSERT INTO corporate_payment_items
                  (corporate_payment_id, user_id, training_type, form_type,
                   price_php, price_label)
                VALUES (%s,%s,%s,%s,%s,%s)
            """, (cid, it["user_id"], it["training_type"], it["form_type"],
                  it["price_php"], it["price_label"]))
        # Registration creates the class before accounts and payment exist.
        # Bind that class to this invoice in the same transaction. A closed,
        # unpaid invoice may be replaced; leaving its old foreign key here
        # made a fully paid replacement unusable with the original class code.
        # A class backed by a pending or paid invoice is never reassigned.
        from .lms import normalize_training_type
        cur.execute("""UPDATE training_classes c SET corporate_payment_id=%s
                         WHERE c.intake_id=%s AND c.program_code=%s
                           AND (c.corporate_payment_id IS NULL OR EXISTS (
                               SELECT 1 FROM corporate_payments old
                                WHERE old.id=c.corporate_payment_id
                                  AND old.intake_id=c.intake_id
                                  AND old.status IN ('cancelled','expired')))
                         RETURNING c.id""",
                    (cid, intake_id, normalize_training_type(intake['form_type'], intake['training_type'])))
        bound_classes = [r['id'] for r in cur.fetchall()]
        if bound_classes:
            cur.execute("""INSERT INTO corporate_payment_events (corporate_payment_id,actor_id,action,details)
                           VALUES (%s,%s,'classes_bound',%s)""",
                        (cid, created_by, 'Intake classes bound to this invoice: '+', '.join(map(str,bound_classes))))
        conn.commit()
        return {"id": cid, "reference": reference, "total_php": round(total, 2),
                "trainee_count": len(items)}, None
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close(); conn.close()


def intake_invoices(intake_id):
    """Every corporate invoice raised for one intake, newest first.

    Used when creating a class: the invoice is the roster and payment
    authority, so a class must be bound to one rather than silently falling
    back to intake-only authority because the browser omitted the id.
    """
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""SELECT * FROM corporate_payments
                    WHERE intake_id = %s
                    ORDER BY (status = 'paid') DESC, created_at DESC""",
                (intake_id,))
    rows = [dict(r) for r in cur.fetchall()]
    cur.close(); conn.close()
    return rows
