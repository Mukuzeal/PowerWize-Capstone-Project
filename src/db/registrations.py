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


def insert_registration(entry):
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("""
        INSERT INTO registrations (
            id, form_type, form_label, submitted_at,
            title, full_name, middle_name, residence,
            company_name, designation, company_address,
            contact_number, email, birthdate, age, doe_expiry,
            training_type, batch_id,
            photo_id, resume, expired_doe, valid_id, selfie_with_id,
            gemp_designation
        ) VALUES (%s,%s,%s,%s, %s,%s,%s,%s, %s,%s,%s, %s,%s,%s,%s,%s, %s,%s, %s,%s,%s,%s,%s, %s)
    """, (
        entry.get("id"),           entry.get("form_type"),   entry.get("form_label"), entry.get("submitted_at"),
        entry.get("title"),        entry.get("full_name"),   entry.get("middle_name"), entry.get("residence"),
        entry.get("company_name"), entry.get("designation"), entry.get("company_address"),
        entry.get("contact_number"), entry.get("email"), entry.get("birthdate"), entry.get("age"), entry.get("doe_expiry"),
        entry.get("training_type"), entry.get("batch_id") or None,
        entry.get("photo_id"), entry.get("resume"), entry.get("expired_doe"), entry.get("valid_id"), entry.get("selfie_with_id"),
        entry.get("gemp_designation"),
    ))
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
    for row in rows:
        if row.get("submitted_at"):
            row["submitted_at"] = row["submitted_at"].strftime("%Y-%m-%d %H:%M")
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


def get_pending_selfies():
    """Get registrations with submitted selfies pending admin review."""
    conn = get_db()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT id, full_name, email, submitted_at, form_label, selfie_with_id
        FROM registrations
        WHERE selfie_with_id IS NOT NULL AND selfie_with_id != ''
        ORDER BY submitted_at DESC
    """)
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return rows
