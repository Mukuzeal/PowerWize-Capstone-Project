import psycopg2.extras

from .core import get_db, build_label_from_dates, format_dates

# Batch type in `batches` -> the offset key used to expand its run dates.
PUBLIC_BATCH_TYPES = {
    "training": "training",
    "renewal": "renewal",
    "gemp_training": "gemp_training",
}


def get_public_schedule():
    """Upcoming batches for the public site, grouped by batch type.

    Returns {batch_type: [{"name", "dates", "year", "days", "start"}]}. Rows are
    read from the same `batches` table the registration forms use, so the
    published calendar and the form dropdowns can never drift apart. `dates`
    is read straight from the stored per-day list, so a holiday-adjusted day
    shows up here without recomputing anything from a single start_date.
    """
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT name, type, start_date, dates FROM batches "
        "WHERE type = ANY(%s) ORDER BY start_date, id",
        (list(PUBLIC_BATCH_TYPES),),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    out = {t: [] for t in PUBLIC_BATCH_TYPES}
    for name, btype, start_date, dates in rows:
        dates = sorted(dates) if dates else [start_date]
        date_str, year = format_dates(dates)
        out[btype].append({
            "name": name,
            "dates": date_str,
            "year": year,
            "days": len(dates),
            "start": start_date,
        })
    return out


def get_schedules():
    """Batch-picker options for the registration forms, keyed by
    delivery mode. Reads each batch's explicit `dates` list (falling back to
    just start_date for any pre-migration row that never got backfilled) so
    an admin's individual holiday-day edits are reflected here too."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, name, type, start_date, dates FROM batches ORDER BY start_date, id")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    result = {
        "online": [], "face_to_face": [],
        "selfpaced_online": [], "selfpaced_f2f": [],
        "renewal_online": [], "renewal_f2f": [],
        "gemp_online": [], "gemp_f2f": [],
    }
    for bid, name, btype, start_date, dates in rows:
        dates = sorted(dates) if dates else [start_date]
        if btype == "training":
            # Self-paced is always the first 3 calendar days of the full run.
            t = {"id": bid, "label": build_label_from_dates(name, dates)}
            s = {"id": bid, "label": build_label_from_dates(name, dates[:3])}
            result["online"].append(t)
            result["face_to_face"].append(t)
            result["selfpaced_online"].append(s)
            result["selfpaced_f2f"].append(s)
        elif btype == "renewal":
            r = {"id": bid, "label": build_label_from_dates(name, dates)}
            result["renewal_online"].append(r)
            result["renewal_f2f"].append(r)
        elif btype == "gemp_training":
            g = {"id": bid, "label": build_label_from_dates(name, dates)}
            result["gemp_online"].append(g)
            result["gemp_f2f"].append(g)
    return result


def get_batches_full():
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT id, name, type, start_date, dates, created_at FROM batches ORDER BY start_date")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    out = []
    for r in rows:
        r = dict(r)
        r["dates"] = sorted(r["dates"]) if r["dates"] else [r["start_date"]]
        out.append(r)
    return out


# The insert is published as SQL + params so a caller that needs it to share
# a transaction with other statements (claim_slot_with_registration, where the
# invitation claim and the insert must commit together or not at all) runs the
# exact same statement rather than a second, drifting copy of it.
REGISTRATION_INSERT_SQL = """
        INSERT INTO registrations (
            id, form_type, form_label, submitted_at,
            title, full_name, middle_name, residence,
            company_name, designation, company_address,
            contact_number, email, birthdate, age, doe_expiry,
            training_type, batch_id,
            photo_id, resume, expired_doe, valid_id, selfie_with_id,
            gemp_designation
        ) VALUES (%s,%s,%s,%s, %s,%s,%s,%s, %s,%s,%s, %s,%s,%s,%s,%s, %s,%s, %s,%s,%s,%s,%s, %s)
"""


def registration_insert_params(entry):
    return (
        entry.get("id"),           entry.get("form_type"),   entry.get("form_label"), entry.get("submitted_at"),
        entry.get("title"),        entry.get("full_name"),   entry.get("middle_name"), entry.get("residence"),
        entry.get("company_name"), entry.get("designation"), entry.get("company_address"),
        entry.get("contact_number"), entry.get("email"), entry.get("birthdate"), entry.get("age"), entry.get("doe_expiry"),
        entry.get("training_type"), entry.get("batch_id") or None,
        entry.get("photo_id"), entry.get("resume"), entry.get("expired_doe"), entry.get("valid_id"), entry.get("selfie_with_id"),
        entry.get("gemp_designation"),
    )


def insert_registration(entry):
    conn = get_db()
    cur  = conn.cursor()
    cur.execute(REGISTRATION_INSERT_SQL, registration_insert_params(entry))
    conn.commit()
    cur.close()
    conn.close()


def get_registrations():
    conn = get_db()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT r.*, b.name AS batch_name, b.start_date AS batch_start
        FROM registrations r
        LEFT JOIN batches b ON r.batch_id = b.id
        ORDER BY r.submitted_at DESC
    """)
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    # Attach the SHARED readiness verdict so the console shows the same
    # answer the company portal and payment eligibility use. Without this the
    # pane rendered raw `status`, so an accepted registration whose identity
    # review was still pending displayed a plain "Accepted" badge while every
    # other surface correctly called it not-ready.
    from review_policy import readiness
    for row in rows:
        if row.get("submitted_at"):
            row["submitted_at"] = row["submitted_at"].strftime("%Y-%m-%d %H:%M")
        row["readiness"] = readiness(row)
    return rows


def set_registration_status(reg_id, status, is_qualified=None):
    conn = get_db()
    cur  = conn.cursor()
    if is_qualified is not None:
        cur.execute(
            "UPDATE registrations SET status = %s, is_qualified = %s WHERE id = %s",
            (status, int(is_qualified), reg_id)
        )
    else:
        cur.execute("UPDATE registrations SET status = %s WHERE id = %s", (status, reg_id))
    conn.commit()
    cur.close()
    conn.close()


# Shared by account pricing and the staff trainee picker. A linked account
# always wins over email history. Older accounts may use a single unambiguous
# email match, without writing an inferred registration_id back to the account.
ACCOUNT_REGISTRATION_JOIN_SQL = """
    LEFT JOIN registrations r ON r.id = u.registration_id OR (
        u.registration_id IS NULL AND lower(r.email) = lower(u.email)
        AND NOT EXISTS (
            SELECT 1 FROM registrations other
             WHERE lower(other.email) = lower(u.email) AND other.id <> r.id
        )
    )
"""


def get_registration_for_user(user_id):
    """Account-bound registration facts; None when identity is unresolved."""
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute("""SELECT r.id,r.form_type,r.form_label,r.training_type,
                              r.status,r.submitted_at
                         FROM users u """ + ACCOUNT_REGISTRATION_JOIN_SQL +
                    " WHERE u.id=%s AND r.id IS NOT NULL", (user_id,))
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        cur.close(); conn.close()


def get_registration_by_email(email):
    conn = get_db()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        "SELECT form_type, form_label, training_type, status, submitted_at FROM registrations WHERE email=%s ORDER BY submitted_at DESC LIMIT 1",
        (email,)
    )
    row = cur.fetchone()
    cur.close(); conn.close()
    return dict(row) if row else None


def get_registration_full(reg_id):
    """The whole row, for review_policy.readiness()."""
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM registrations WHERE id = %s", (reg_id,))
    row = cur.fetchone()
    cur.close(); conn.close()
    return dict(row) if row else None


def set_correction_note(reg_id, note):
    """The one piece of review text the company portal renders. Cleared when
    the applicant is later accepted or rejected, so a stale instruction does
    not linger on a resolved row."""
    conn = get_db(); cur = conn.cursor()
    cur.execute("UPDATE registrations SET correction_note = %s, "
                "correction_set_at = NOW() WHERE id = %s", (note, reg_id))
    conn.commit(); cur.close(); conn.close()


def clear_correction_note(reg_id):
    conn = get_db(); cur = conn.cursor()
    cur.execute("UPDATE registrations SET correction_note = NULL, "
                "correction_set_at = NULL WHERE id = %s", (reg_id,))
    conn.commit(); cur.close(); conn.close()


def get_pending_selfies():
    """Registrations whose selfie still needs a human decision.

    `selfie_reviewed_at IS NULL` is the filter that makes this a queue. Before
    it existed the list was driven only by the filename being present, so an
    approved selfie was never removed and staff saw it again every visit.
    """
    conn = get_db()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT id, full_name, email, submitted_at, form_label, selfie_with_id
        FROM registrations
        WHERE selfie_with_id IS NOT NULL AND selfie_with_id != ''
          AND selfie_reviewed_at IS NULL
        ORDER BY submitted_at DESC
    """)
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


# ── Document retention ───────────────────────────────────────────────────────
#
# Uploads exist to support two decisions and are deleted once both are made.
# What survives is the outcome plus a SHA-256 of each file, so an audit can
# confirm which document was reviewed without the document being kept.

DOC_FIELDS = ("photo_id", "resume", "expired_doe", "valid_id", "selfie_with_id")


def record_selfie_review(reg_id, outcome, reviewed_by=None):
    """Close the selfie gate. Idempotent: only the first decision sticks."""
    conn = get_db(); cur = conn.cursor()
    cur.execute(
        "UPDATE registrations SET selfie_reviewed_at = NOW(), selfie_outcome = %s "
        "WHERE id = %s AND selfie_reviewed_at IS NULL",
        (outcome, reg_id),
    )
    changed = cur.rowcount
    conn.commit(); cur.close(); conn.close()
    return changed == 1


def registration_review_state(reg_id):
    """(status, selfie_reviewed, has_selfie, already_purged) for one row."""
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT status, selfie_reviewed_at, selfie_with_id, documents_purged_at
        FROM registrations WHERE id = %s
    """, (reg_id,))
    row = cur.fetchone()
    cur.close(); conn.close()
    if not row:
        return None
    return {
        "status":          row["status"],
        "selfie_reviewed": row["selfie_reviewed_at"] is not None,
        "has_selfie":      bool((row["selfie_with_id"] or "").strip()),
        "purged":          row["documents_purged_at"] is not None,
    }


def get_registration_documents(reg_id):
    """{field: filename} for the documents still recorded against a row."""
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT " + ", ".join(DOC_FIELDS) +
                " FROM registrations WHERE id = %s", (reg_id,))
    row = cur.fetchone()
    cur.close(); conn.close()
    if not row:
        return {}
    return {f: (row[f] or "").strip() for f in DOC_FIELDS if (row[f] or "").strip()}


def record_document_purge(reg_id, entries, outcome, reviewed_by=None):
    """Write the evidence rows, clear the pointers that are actually gone,
    and stamp the registration only if nothing was left behind.

    One transaction. Two rules make a partial failure recoverable:

      * a field is cleared only if its file is confirmed gone ('deleted' or
        already 'missing'). Clearing a pointer to a file that is still on
        disk would orphan it with nothing referencing it.
      * `documents_purged_at` is set only when every entry succeeded. If one
        deletion failed, the stamp stays NULL so the next gate action — or a
        sweep — retries it instead of believing the job is done.

    Returns True if the registration is now fully purged.
    """
    gone = [e for e in entries if e.get("note") in ("deleted", "missing")]
    complete = len(gone) == len(entries)

    conn = get_db(); cur = conn.cursor()
    try:
        for e in entries:
            cur.execute("""
                INSERT INTO registration_document_reviews
                    (reg_id, field, sha256, byte_size, file_ext, outcome, reviewed_by, note)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (reg_id, field) DO UPDATE
                   SET sha256 = COALESCE(EXCLUDED.sha256, registration_document_reviews.sha256),
                       note   = EXCLUDED.note
            """, (reg_id, e["field"], e.get("sha256"), e.get("byte_size"),
                  e.get("file_ext"), outcome, reviewed_by, e.get("note")))
        if gone:
            cur.execute(
                "UPDATE registrations SET " +
                ", ".join(f"{e['field']} = NULL" for e in gone) +
                (", documents_purged_at = NOW()" if complete else "") +
                " WHERE id = %s", (reg_id,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close(); conn.close()
    return complete


def get_document_reviews(reg_id):
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM registration_document_reviews "
                "WHERE reg_id = %s ORDER BY field", (reg_id,))
    rows = [dict(r) for r in cur.fetchall()]
    cur.close(); conn.close()
    return rows
