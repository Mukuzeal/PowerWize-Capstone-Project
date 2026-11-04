"""Training classes and their join codes.

A join code is a convenience, not a permission. It identifies *which* class a
person means; it never establishes that they are entitled to be in it. Four
separate facts are re-derived from the database on every join, and all four
must hold:

  1. they are a trainee (role), and their registration was ACCEPTED by staff
  2. their fee is paid
  3. they are on THIS class's roster — the company's invoice items, or a slot
     on the company's intake matching their registration
  4. the class's program matches what they were approved and billed for

That list is the whole point. If the code were treated as authorisation, then
one leaked or overheard code would let anyone enrol: someone with no account
(so no ID check and no selfie review), someone whose registration was
rejected, someone who never paid, or an employee of a different company. Each
of those is a separate failure and each is refused separately below, with a
reason the person can act on.

The code deliberately does NOT:
  * create accounts — see the invitation-only rule in src/auth.py
  * stand in for admin approval of a registration
  * confer payment entitlement, or mark anything paid
"""
import secrets

import psycopg2
import psycopg2.extras

from review_policy import readiness

from .core import get_db
from .lms import get_user_training_type, normalize_training_type

# Human labels for the canonical program codes, so a refusal names the
# programme rather than echoing a database token at the trainee.
PROGRAM_LABELS = {
    "training":     "CEM Training",
    "cea_training": "CEA Training",
    "cem_renewal":  "CEM Renewal",
    "cea_renewal":  "CEA Renewal",
    "renewal":      "Renewal",
    "gemp_lgu":     "GEMP (LGU)",
    "gemp_oge":     "GEMP (OGE)",
}

# No 0/O/1/I/L — these are read aloud and copied off a whiteboard.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_CODE_LENGTH = 7


def _new_code():
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LENGTH))


def normalize_code(raw):
    """What the user typed, as the stored form.

    People type lowercase, paste trailing spaces, and insert hyphens or
    non-breaking spaces copied out of chat. Strip all of that rather than
    telling them their correct code is wrong.
    """
    if not raw:
        return ""
    cleaned = []
    for ch in str(raw).strip().upper():
        if ch.isalnum():
            cleaned.append(ch)
        elif ch in "-_  ‐‑‒–—":
            continue
        else:
            cleaned.append(ch)       # keep, so an invalid char still fails
    return "".join(cleaned)


def create_class(name, training_type, created_by, intake_id=None,
                 corporate_payment_id=None, form_type=None):
    """(class_dict, error). The code is generated here, never supplied.

    `training_type` is the human label; `form_type` is the intake's program
    field. Both are folded through normalize_training_type() to store the
    canonical program_code, which is what eligibility actually compares.
    """
    if not (name or "").strip():
        return None, "A class needs a name."
    if not (training_type or "").strip():
        return None, "A class needs a program."
    program_code = normalize_training_type(form_type, training_type)
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        # UNIQUE(join_code) is the real guard; retry on the rare collision
        # rather than trusting a single draw.
        for _ in range(8):
            code = _new_code()
            try:
                cur.execute("""
                    INSERT INTO training_classes
                        (name, training_type, program_code, intake_id,
                         corporate_payment_id, join_code, created_by)
                    VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *
                """, (name.strip(), training_type.strip(), program_code,
                      intake_id, corporate_payment_id, code, created_by))
                row = cur.fetchone()
                conn.commit()
                return dict(row), None
            except psycopg2.errors.UniqueViolation:
                conn.rollback()
                continue
        return None, "Could not allocate a unique join code. Try again."
    finally:
        cur.close(); conn.close()


def get_class(class_id=None, join_code=None):
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if join_code is not None:
        cur.execute("SELECT * FROM training_classes WHERE join_code = %s",
                    (normalize_code(join_code),))
    else:
        cur.execute("SELECT * FROM training_classes WHERE id = %s", (class_id,))
    row = cur.fetchone()
    cur.close(); conn.close()
    return dict(row) if row else None


def list_classes(intake_id=None):
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    sql = """SELECT c.*, i.company_name, p.reference AS invoice_reference,
                    concat_ws(' ',u.fname,u.lname) AS instructor_name,
                    u.email AS instructor_email,
                    u.archived_at AS instructor_archived_at, u.role AS instructor_role,
                    p.status AS invoice_status,
                    (SELECT COUNT(*) FROM training_class_members m
                      WHERE m.class_id = c.id) AS member_count
               FROM training_classes c
               LEFT JOIN corporate_intakes i ON i.id = c.intake_id
               LEFT JOIN corporate_payments p ON p.id = c.corporate_payment_id
               LEFT JOIN users u ON u.id = c.instructor_id"""
    params = ()
    if intake_id is not None:
        sql += " WHERE c.intake_id = %s"
        params = (intake_id,)
    sql += " ORDER BY c.created_at DESC"
    cur.execute(sql, params)
    rows = [dict(r) for r in cur.fetchall()]
    cur.close(); conn.close()
    return rows


def _instructor_enabled(cur, user_id):
    """Check the real account and its training remit, not a stale session role."""
    from permissions import TRAINER, can
    cur.execute("""SELECT u.id FROM users u
                    LEFT JOIN user_capabilities cap ON cap.user_id=u.id AND cap.capability='manage_modules'
                   WHERE u.id=%s AND u.role=%s AND u.archived_at IS NULL
                     AND COALESCE(cap.granted<>0,%s)""",
                (user_id, TRAINER, can(TRAINER, 'manage_modules')))
    return cur.fetchone() is not None


def class_instructors():
    """Active instructor accounts with permission to run training modules."""
    from permissions import TRAINER, can
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute("""SELECT u.id, concat_ws(' ',u.fname,u.lname) AS name,u.email
                       FROM users u LEFT JOIN user_capabilities cap
                         ON cap.user_id=u.id AND cap.capability='manage_modules'
                      WHERE u.role=%s AND u.archived_at IS NULL
                        AND COALESCE(cap.granted<>0,%s)
                      ORDER BY lower(u.lname),lower(u.fname),u.id""",
                    (TRAINER, can(TRAINER, 'manage_modules')))
        return [dict(r) for r in cur.fetchall()]
    finally:
        cur.close(); conn.close()


def assign_class_instructor(class_id, instructor_id, expected_id, actor_id):
    """One instructor per batch; a trainer may run multiple batches.

    Serialize writes and refuse stale selections. Assignment and its audit
    commit together; trainee rosters, invoices and class codes are unchanged.
    None clears the assignment. No account privileges are granted here.
    """
    import json
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute('SELECT * FROM training_classes WHERE id=%s FOR UPDATE', (class_id,))
        cls = cur.fetchone()
        if not cls:
            conn.rollback()
            return {'error': 'No such batch.'}, 404
        if cls['instructor_id'] != expected_id:
            conn.rollback()
            return {'error': 'The instructor assignment changed. Reload the batch before saving.'}, 409
        if instructor_id is not None:
            cur.execute('SELECT id FROM users WHERE id=%s FOR SHARE', (instructor_id,))
            if not cur.fetchone() or not _instructor_enabled(cur, instructor_id):
                conn.rollback()
                return {'error': 'Choose an active instructor with training-module access.'}, 400
        if cls['instructor_id'] == instructor_id:
            conn.commit()
            return {'ok': True, 'changed': False, 'message': 'Instructor assignment is already up to date.'}, 200
        cur.execute('UPDATE training_classes SET instructor_id=%s WHERE id=%s', (instructor_id,class_id))
        cur.execute("""INSERT INTO audit_logs(user_id,action,entity_type,entity_id,details)
                       VALUES(%s,'class_instructor_assigned','training_class',%s,%s)""",
                    (actor_id,str(class_id),json.dumps({'previous_instructor_id': cls['instructor_id'],
                     'instructor_id': instructor_id,'intake_id':cls['intake_id']})))
        conn.commit()
        return {'ok':True,'changed':True,'message':
                'Instructor assigned to this batch.' if instructor_id is not None else 'Instructor assignment cleared.'}, 200
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close(); conn.close()


def instructor_can_view_class(class_id, user_id):
    conn = get_db(); cur = conn.cursor()
    try:
        if not _instructor_enabled(cur,user_id):
            return False
        cur.execute('SELECT 1 FROM training_classes WHERE id=%s AND instructor_id=%s', (class_id,user_id))
        return cur.fetchone() is not None
    finally:
        cur.close(); conn.close()


def instructor_classes(user_id):
    """Only the requesting instructor's batches, including unjoined counts."""
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        if not _instructor_enabled(cur,user_id):
            return []
        cur.execute("""SELECT c.id,c.name,c.program_code,c.join_code,c.join_open,
                              i.company_name,
                              (SELECT count(*) FROM training_class_members m WHERE m.class_id=c.id) AS member_count
                         FROM training_classes c
                         LEFT JOIN corporate_intakes i ON i.id=c.intake_id
                        WHERE c.instructor_id=%s ORDER BY c.created_at DESC,c.id DESC""", (user_id,))
        return [dict(r) for r in cur.fetchall()]
    finally:
        cur.close(); conn.close()


def repair_replacement_class_invoice(class_id, replacement_id, actor_id=None):
    """Repair an existing closed-invoice binding using a paid replacement.

    Requires the same intake, program, and exact billed account identities.
    Only the class's invoice pointer changes; membership, code, reviews and
    payment outcomes remain their original records. Entitlement still goes
    through _authorise() on every join and LMS access.
    """
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute('SELECT * FROM training_classes WHERE id=%s FOR UPDATE', (class_id,))
        cls = cur.fetchone()
        if not cls or not cls['intake_id'] or not cls['corporate_payment_id']:
            conn.rollback(); return False, 'An invoice-backed company class is required.'
        if cls['corporate_payment_id'] == replacement_id:
            conn.rollback(); return True, None
        cur.execute('SELECT id,reference,status,intake_id FROM corporate_payments WHERE id=ANY(%s) ORDER BY id FOR SHARE',
                    ([cls['corporate_payment_id'], replacement_id],))
        invoices = {r['id']: dict(r) for r in cur.fetchall()}
        old = invoices.get(cls['corporate_payment_id']); replacement = invoices.get(replacement_id)
        if (not old or not replacement or old['intake_id'] != cls['intake_id']
                or replacement['intake_id'] != cls['intake_id']):
            conn.rollback(); return False, 'Both invoices must belong to this class\'s company intake.'
        if old['status'] not in ('cancelled','expired') or replacement['status'] != 'paid':
            conn.rollback(); return False, 'Only a cancelled or expired invoice can be replaced with a paid invoice.'
        cur.execute('SELECT corporate_payment_id,user_id,form_type,training_type FROM corporate_payment_items WHERE corporate_payment_id=ANY(%s) FOR SHARE',
                    ([old['id'], replacement_id],))
        items = [dict(r) for r in cur.fetchall()]
        old_users = {r['user_id'] for r in items if r['corporate_payment_id'] == old['id']}
        new_users = {r['user_id'] for r in items if r['corporate_payment_id'] == replacement_id}
        if not new_users or new_users != old_users:
            conn.rollback(); return False, 'The replacement must cover exactly the same billed trainee accounts.'
        if not cls['program_code'] or any(normalize_training_type(r['form_type'],r['training_type']) != cls['program_code'] for r in items):
            conn.rollback(); return False, 'The class and both invoices must have the same training program.'
        cur.execute('UPDATE training_classes SET corporate_payment_id=%s WHERE id=%s', (replacement_id,class_id))
        detail = f"Class {class_id} moved from {old['reference']} ({old['status']}) to paid replacement {replacement['reference']}; billed accounts and program match."
        cur.execute("INSERT INTO corporate_payment_events(corporate_payment_id,actor_id,action,details) VALUES(%s,%s,'class_invoice_rebound',%s)",
                    (replacement_id,actor_id,detail))
        cur.execute("INSERT INTO audit_logs(user_id,action,entity_type,entity_id,details) VALUES(%s,'class_invoice_rebound','training_class',%s,%s)",
                    (actor_id,str(class_id),detail))
        conn.commit()
        return True, None
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close(); conn.close()


def set_join_open(class_id, is_open):
    """Open or close self-joining. Existing members are unaffected — closing a
    class must not silently remove people who are already in it."""
    conn = get_db(); cur = conn.cursor()
    cur.execute("""UPDATE training_classes
                      SET join_open = %s,
                          closed_at = CASE WHEN %s THEN NULL ELSE NOW() END
                    WHERE id = %s""", (bool(is_open), bool(is_open), class_id))
    ok = cur.rowcount == 1
    conn.commit(); cur.close(); conn.close()
    return ok


def rotate_join_code(class_id):
    """(code, error). Used when a code has been shared too widely.

    Rotation does not evict members: they were authorised by the roster, not
    by the code, so taking the code away cannot retroactively unauthorise
    them. It only stops further self-joins with the old code.
    """
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        for _ in range(8):
            code = _new_code()
            try:
                cur.execute("UPDATE training_classes SET join_code = %s "
                            "WHERE id = %s RETURNING join_code",
                            (code, class_id))
                row = cur.fetchone()
                if not row:
                    conn.rollback()
                    return None, "No such class."
                conn.commit()
                return row["join_code"], None
            except psycopg2.errors.UniqueViolation:
                conn.rollback()
                continue
        return None, "Could not allocate a unique join code. Try again."
    finally:
        cur.close(); conn.close()


# ── Eligibility ──────────────────────────────────────────────────────────────
#
# One function, _authorise(), used by every path. It takes a cursor rather
# than opening its own, so join_class() can lock the class, decide, and insert
# inside a SINGLE transaction. Three separate connections — one to resolve the
# code, one to check eligibility, one to insert — meant a class could be
# closed, rotated, or a roster slot revoked in the gap between the decision
# and the insert, and the stale decision still won.

# Lock order for everything that decides entitlement. Every writer and reader
# below takes these in this order and no other, so two transactions touching
# the same person cannot deadlock:
#
#     training_classes -> registrations -> corporate_payments
#                      -> corporate_payment_items -> corporate_intake_slots
#
# The reads are FOR SHARE, not plain SELECTs. A plain read saw 'accepted' while
# a reviewer's UPDATE to 'rejected' was in flight, and the stale verdict still
# produced an insert. FOR SHARE lets other readers through but makes a writer
# wait until this transaction ends, so a rejection or a roster revocation is
# either fully visible to us or applied after our decision — never half-way
# through it.
LOCK_ORDER = ("training_classes", "registrations", "corporate_payments",
              "corporate_payment_items", "corporate_intake_slots")


def _authorise(cur, cls, user_id, lock=False):
    """(ok, reason) for an already-loaded class row, on a caller's cursor.

    Each refusal is a distinct fact, so the person is told what to actually do.

    `lock=True` takes FOR SHARE on every authoritative row, in LOCK_ORDER.
    Callers that are about to WRITE (join_class, add_member_as_staff) must set
    it; read-only callers that just render a verdict leave it off so a panel
    refresh cannot block a reviewer.
    """
    # registrations is second in LOCK_ORDER; the class row is already locked
    # by the caller. FOR SHARE cannot be used with a LEFT JOIN's outer side,
    # so the registration is read on its own after the user row.
    cur.execute("""
        SELECT id, role, payment_status, registration_id
          FROM users WHERE id = %s
    """, (user_id,))
    row = cur.fetchone()
    if not row:
        return False, "No such account."
    user = dict(row)
    user["reg_id"] = None          # set below only if the row really exists
    if user["registration_id"]:
        cur.execute(
            "SELECT * FROM registrations WHERE id = %s"
            + (" FOR SHARE" if lock else ""), (user["registration_id"],))
        reg = cur.fetchone()
        if reg:
            # r.* so review_policy.readiness() sees EVERY field it reads.
            # Hand-listing them dropped selfie_outcome and
            # documents_purged_at, which made a finished, approved review read
            # back as "still pending".
            user.update(dict(reg))
            user["reg_id"] = reg["id"]

    # 1. A trainee with a registration that passed the SHARED readiness rule.
    #    Not a local re-reading of `status`: review_policy.readiness() is the
    #    one place that knows acceptance and identity review are separate
    #    facts, and that a finished selfie review purges the file (so a
    #    missing selfie is not evidence of a missing review).
    if user["role"] != "trainee":
        return False, ("Only trainee accounts can join a class. Trainers and "
                       "staff see classes through the console.")
    if not user["registration_id"] or not user["reg_id"]:
        return False, ("This account has no registration behind it, so there "
                       "is nothing for staff to have approved.")

    verdict = readiness(user)
    if not verdict["ready"]:
        return False, ("This registration is not cleared for training yet: "
                       + " ".join(verdict["blockers"])
                       + " A join code cannot stand in for that review.")

    # 2. Payment, from the authority that actually allocates it.
    if cls["corporate_payment_id"] is not None:
        # The invoice is the roster AND the payment record. Checking only
        # users.payment_status let someone paid by a DIFFERENT invoice (or
        # flipped by hand) into a cohort whose own invoice was never settled.
        cur.execute(
            "SELECT id, status, reference FROM corporate_payments WHERE id = %s"
            + (" FOR SHARE" if lock else ""), (cls["corporate_payment_id"],))
        inv = cur.fetchone()
        if not inv:
            return False, ("The invoice behind that class no longer exists. "
                           "Staff need to re-point the class at a live one.")
        inv = dict(inv)
        cur.execute(
            "SELECT training_type, form_type FROM corporate_payment_items "
            "WHERE corporate_payment_id = %s AND user_id = %s"
            + (" FOR SHARE" if lock else ""),
            (cls["corporate_payment_id"], user_id))
        item = cur.fetchone()
        if not item:
            return False, ("This account is not on the invoice that paid for "
                           "that class. Ask your coordinator to have you "
                           "added and billed.")
        item = dict(item)
        if inv["status"] != "paid":
            return False, (f"The invoice for that class is "
                           f"'{inv['status']}', not paid. A join code does "
                           f"not grant access to training that has not been "
                           f"paid for.")
        billed = normalize_training_type(item.get("form_type"),
                                         item.get("training_type"))
    elif cls["intake_id"] is not None:
        # No invoice yet, so the intake's live slots are the roster and the
        # account's own payment status is the best available evidence.
        if (user["payment_status"] or "") != "paid":
            return False, ("This account is not marked paid. A join code does "
                           "not grant access to a program that has not been "
                           "paid for.")
        cur.execute("""SELECT id FROM corporate_intake_slots
                        WHERE intake_id = %s AND registration_id = %s
                          AND invite_revoked_at IS NULL"""
                    + (" FOR SHARE" if lock else ""),
                    (cls["intake_id"], user["registration_id"]))
        if cur.fetchone() is None:
            return False, ("This account is not on that class's company "
                           "roster. Ask your coordinator to add you before "
                           "using the code.")
        billed = None                      # nothing billed yet to compare
    else:
        return False, ("This class has no company roster, so nobody can join "
                       "it with a code. Staff add members directly.")

    # 3. The same PROGRAM, as canonical codes, across all THREE records that
    #    carry a programme: the class, the registration, and what was actually
    #    billed. Comparing raw text matched "Online" against "Online" — two
    #    labels, not two programmes; a CEM and a CEA cohort can both read
    #    "Online". And agreeing with the registration is not enough on its
    #    own: an invoice line raised for a different programme means the
    #    company paid for something else.
    want = cls.get("program_code")
    if not want:
        # No fallback. Deriving it from the free-text label guessed, and the
        # guess resolved an old CEA class labelled "Online" to CEM. An
        # un-derivable class is refused and reported, not admitted.
        return False, ("That class has no programme recorded, so entitlement "
                       "cannot be checked. Staff need to set its programme "
                       "before anyone joins.")
    have = normalize_training_type(user["form_type"], user["training_type"])
    if have and want != have:
        return False, (f"That class runs the {PROGRAM_LABELS.get(want, want)} "
                       f"programme, but this registration is for "
                       f"{PROGRAM_LABELS.get(have, have)}.")
    if billed and billed != want:
        return False, (f"That class runs the {PROGRAM_LABELS.get(want, want)} "
                       f"programme, but the invoice billed "
                       f"{PROGRAM_LABELS.get(billed, billed)}. Staff need to "
                       f"correct the billing before this can open.")
    return True, None


def membership_authority(class_id, user_id):
    """(authorised, reason) — may this user be a member of this class?

    Read-only wrapper for callers that just want to display the verdict (the
    admin panel's "who has not joined, and why"). Re-derived every time it is
    asked, so a revoked slot or an unpaid invoice takes effect immediately.
    """
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute("SELECT * FROM training_classes WHERE id = %s", (class_id,))
        cls = cur.fetchone()
        if not cls:
            return False, "No such class."
        return _authorise(cur, dict(cls), user_id)
    finally:
        cur.close(); conn.close()


def join_class(user_id, raw_code):
    """(class_dict, error) — the self-join path a trainee drives.

    Resolve, decide and insert in ONE transaction, with the class row locked
    FOR UPDATE. Without the lock, a code rotation or a close that landed
    between the decision and the insert was simply ignored.
    """
    code = normalize_code(raw_code)
    if not code:
        return None, "Enter the class code your trainer gave you."

    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        # The lock is taken on the code lookup itself, so the row cannot be
        # rotated or closed from under the rest of this transaction.
        cur.execute("SELECT * FROM training_classes WHERE join_code = %s "
                    "FOR UPDATE", (code,))
        row = cur.fetchone()
        if not row:
            conn.rollback()
            # Nothing is revealed about which codes exist, because there is
            # nothing worth revealing: the code alone opens nothing.
            return None, "No class has that code. Check it with your trainer."
        cls = dict(row)
        if not cls["join_open"]:
            conn.rollback()
            return None, ("That class is no longer accepting new members. Ask "
                          "your trainer to add you.")

        ok, reason = _authorise(cur, cls, user_id, lock=True)
        if not ok:
            conn.rollback()
            return None, reason

        # Idempotent: a double submit must not error, and must not look like
        # a second enrolment.
        cur.execute("""INSERT INTO training_class_members
                           (class_id, user_id, authorised)
                       VALUES (%s,%s,'roster')
                       ON CONFLICT (class_id, user_id) DO NOTHING""",
                    (cls["id"], user_id))
        conn.commit()
        return cls, None
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close(); conn.close()


def add_member_as_staff(class_id, user_id, added_by):
    """(ok, error) — staff adding someone directly.

    Holds the SAME roster and payment checks as a self-join. Staff convenience
    is not a reason to let an unpaid or unapproved person into a syllabus; if
    the roster is wrong, the roster is what needs fixing.

    One transaction with the class row locked, for the same reason join_class()
    takes the lock: deciding on one connection and inserting on another let a
    revoked slot or an unpaid invoice slip through the gap.
    """
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute("SELECT * FROM training_classes WHERE id = %s FOR UPDATE",
                    (class_id,))
        row = cur.fetchone()
        if not row:
            conn.rollback()
            return False, "No such class."
        ok, reason = _authorise(cur, dict(row), user_id, lock=True)
        if not ok:
            conn.rollback()
            return False, reason
        cur.execute("""INSERT INTO training_class_members
                           (class_id, user_id, authorised, added_by)
                       VALUES (%s,%s,'staff',%s)
                       ON CONFLICT (class_id, user_id) DO NOTHING""",
                    (class_id, user_id, added_by))
        conn.commit()
        return True, None
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close(); conn.close()


def remove_member(class_id, user_id):
    conn = get_db(); cur = conn.cursor()
    cur.execute("DELETE FROM training_class_members "
                "WHERE class_id = %s AND user_id = %s", (class_id, user_id))
    ok = cur.rowcount == 1
    conn.commit(); cur.close(); conn.close()
    return ok


def class_members(class_id):
    """Members with the identity a trainer needs to recognise them."""
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT m.user_id, m.joined_at, m.authorised,
               u.fname, u.lname, u.email, u.payment_status, u.registration_id,
               r.training_type
          FROM training_class_members m
          JOIN users u ON u.id = m.user_id
          LEFT JOIN registrations r ON r.id = u.registration_id
         WHERE m.class_id = %s
         ORDER BY u.lname, u.fname
    """, (class_id,))
    rows = [dict(r) for r in cur.fetchall()]
    cur.close(); conn.close()
    return rows


def classes_for_user(user_id):
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT c.*, m.joined_at, i.company_name
          FROM training_class_members m
          JOIN training_classes c ON c.id = m.class_id
          LEFT JOIN corporate_intakes i ON i.id = c.intake_id
         WHERE m.user_id = %s
         ORDER BY m.joined_at DESC
    """, (user_id,))
    rows = [dict(r) for r in cur.fetchall()]
    cur.close(); conn.close()
    return rows


def class_roster_candidates(class_id):
    """Everyone this class draws its membership from, joined or not.

    Reads the SAME authority membership_authority() does — the invoice items
    when the class names an invoice, otherwise the intake's live slots.

    Not invoiceable_roster(): that answers "who can still be billed", so once
    the invoice is paid it reports every member as blocked with "Already
    paid". Correct for invoicing, exactly backwards for class membership.
    """
    cls = get_class(class_id=class_id)
    if not cls:
        return []
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        if cls["corporate_payment_id"] is not None:
            # The invoice decides membership, but the intake's own slots are
            # listed too when they differ. Someone the company rostered and
            # never billed is invisible to the invoice, and a trainer reading
            # only the invoice would never learn why that person cannot join.
            # _authorise() still refuses them, naming the invoice.
            cur.execute("""
                SELECT u.id AS user_id, u.fname, u.lname, u.email, NULL AS full_name
                  FROM corporate_payment_items it
                  JOIN users u ON u.id = it.user_id
                 WHERE it.corporate_payment_id = %s
                 UNION
                SELECT u.id AS user_id, u.fname, u.lname, u.email, s.full_name
                  FROM corporate_intake_slots s
                  JOIN users u ON u.registration_id = s.registration_id
                 WHERE s.intake_id = %s
                   AND s.registration_id IS NOT NULL
                   AND s.invite_revoked_at IS NULL
                 ORDER BY 3, 2
            """, (cls["corporate_payment_id"], cls["intake_id"] or -1))
        elif cls["intake_id"] is not None:
            cur.execute("""
                SELECT u.id AS user_id, u.fname, u.lname, u.email,
                       s.full_name
                  FROM corporate_intake_slots s
                  JOIN users u ON u.registration_id = s.registration_id
                 WHERE s.intake_id = %s
                   AND s.registration_id IS NOT NULL
                   AND s.invite_revoked_at IS NULL
                 ORDER BY u.lname, u.fname
            """, (cls["intake_id"],))
        else:
            return []
        rows = []
        for r in cur.fetchall():
            d = dict(r)
            d["name"] = (d.get("full_name")
                         or f"{d.get('fname') or ''} {d.get('lname') or ''}".strip()
                         or d.get("email"))
            rows.append(d)
        return rows
    finally:
        cur.close(); conn.close()


# ── LMS access gate ──────────────────────────────────────────────────────────

def class_gate(user_id, program_code=None):
    """(allowed, reason) — may this trainee open this programme's training?

    This is where a join code finally *does* something: for a trainee whose
    fee was paid through a company invoice, training opens once they are in
    the class their employer booked. That is the "enter the code to access
    training" behaviour.

    Membership is NOT standing authority. A row in training_class_members
    records that entitlement held at join time; it is re-derived here through
    _authorise() on every access, so a registration rejected afterwards, a
    revoked roster slot, a refunded invoice or a corrected programme closes
    access immediately. Accepting the row on its own made the first successful
    join permanent.

    Membership is also scoped to the programme being opened. A trainee in a
    CEM cohort must not have that membership satisfy the gate for CEA
    material, so only classes whose program_code matches count.

    Two boundaries are deliberate, and both are exceptions worth naming:

      * Individual enrolment is untouched. Someone who paid for themselves is
        on no corporate invoice, so there is no class to be in and this
        returns allowed immediately. Gating them would break the ordinary
        trainee path for a feature that is not theirs.

      * DOCUMENTED EXCEPTION to mandatory code entry: a corporate trainee is
        gated only once a class actually EXISTS for their invoice or intake in
        that programme. If staff have not created one, there is no code to
        enter, and locking people out of training they have already paid for
        because of an internal gap would be the wrong failure. Access is open
        in that window; the gate appears the moment the class does. This is a
        real hole in "a corporate trainee must enter a code" and is accepted
        knowingly — the alternative denies service for a staff omission.
    """
    program_code = program_code or get_user_training_type(user_id)
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        # Which company invoices name this person? Deliberately NOT filtered
        # to status='paid'. Filtering here meant cancelling an invoice made
        # its trainees look like individual enrolments and OPENED the gate —
        # the one case where it most needs to close. A cancelled booking is
        # still a corporate booking; whether it entitles anyone is
        # _authorise()'s decision, not this query's.
        cur.execute("""
            SELECT p.id, p.intake_id, p.company_name
              FROM corporate_payment_items it
              JOIN corporate_payments p ON p.id = it.corporate_payment_id
             WHERE it.user_id = %s
        """, (user_id,))
        invoices = [dict(r) for r in cur.fetchall()]

        # Membership alone also makes the gate apply: someone added by staff
        # to an intake-only class is on no invoice at all, and must still be
        # revalidated rather than treated as an individual.
        cur.execute("""
            SELECT c.* FROM training_class_members m
              JOIN training_classes c ON c.id = m.class_id
             WHERE m.user_id = %s AND c.program_code = %s
        """, (user_id, program_code))
        joined_any = [dict(r) for r in cur.fetchall()]

        if not invoices and not joined_any:
            return True, None                      # individual enrolment

        inv_ids = [i["id"] for i in invoices] or [-1]
        intake_ids = [i["intake_id"] for i in invoices if i["intake_id"]] or [-1]

        # Classes that could gate THIS programme. A class with no recorded
        # programme is excluded: it cannot be matched, and _authorise() would
        # refuse it anyway, so it must not create a gate nobody can pass.
        cur.execute("""
            SELECT * FROM training_classes
             WHERE program_code = %s
               AND (corporate_payment_id = ANY(%s)
                    OR (intake_id = ANY(%s) AND corporate_payment_id IS NULL))
        """, (program_code, inv_ids, intake_ids))
        candidates = [dict(r) for r in cur.fetchall()]
        if not candidates and not joined_any:
            # No class for this programme yet — the documented exception.
            return True, None

        cur.execute("""
            SELECT class_id FROM training_class_members WHERE user_id = %s
        """, (user_id,))
        member_of = {r["class_id"] for r in cur.fetchall()}

        joined = [c for c in candidates if c["id"] in member_of]
        # A class they are in that is NOT a candidate (its invoice was
        # re-pointed, say) still counts for revalidation, so losing
        # candidacy cannot quietly become "no gate".
        seen = {c["id"] for c in joined}
        joined += [c for c in joined_any if c["id"] not in seen]
        if not joined:
            company = (invoices[0]["company_name"] if invoices
                       else None) or "your company"
            return False, (f"Your training was booked by {company} as a "
                           f"class. Enter the class code your trainer gave "
                           f"you to open your modules — it is on your portal "
                           f"page.")

        # Re-derive entitlement for each class they are actually in. One still
        # valid is enough; it is the same rule that let them in.
        last = None
        for cls in joined:
            ok, reason = _authorise(cur, cls, user_id)
            if ok:
                return True, None
            last = reason
        return False, (f"Your place in that class is no longer valid: {last}")
    finally:
        cur.close(); conn.close()
