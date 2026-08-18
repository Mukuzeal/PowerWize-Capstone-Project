import psycopg2.extras

from .core import get_db, build_batch_dates, build_batch_label, TYPE_OFFSETS

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
    published calendar and the form dropdowns can never drift apart.
    """
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT name, type, start_date FROM batches "
        "WHERE type = ANY(%s) ORDER BY start_date, id",
        (list(PUBLIC_BATCH_TYPES),),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    out = {t: [] for t in PUBLIC_BATCH_TYPES}
    for name, btype, start_date in rows:
        offsets = TYPE_OFFSETS[PUBLIC_BATCH_TYPES[btype]]
        dates, year = build_batch_dates(offsets, start_date)
        out[btype].append({
            "name": name,
            "dates": dates,
            "year": year,
            "days": len(offsets),
            "start": start_date,
        })
    return out


def get_schedules():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, name, type, start_date FROM batches ORDER BY start_date, id")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    result = {
        "online": [], "face_to_face": [],
        "selfpaced_online": [], "selfpaced_f2f": [],
        "renewal_online": [], "renewal_f2f": [],
        "gemp_online": [], "gemp_f2f": [],
    }
    for bid, name, btype, start_date in rows:
        if btype == "training":
            t = {"id": bid, "label": build_batch_label(name, TYPE_OFFSETS["training"],  start_date)}
            s = {"id": bid, "label": build_batch_label(name, TYPE_OFFSETS["selfpaced"], start_date)}
            result["online"].append(t)
            result["face_to_face"].append(t)
            result["selfpaced_online"].append(s)
            result["selfpaced_f2f"].append(s)
        elif btype == "renewal":
            r = {"id": bid, "label": build_batch_label(name, TYPE_OFFSETS["renewal"], start_date)}
            result["renewal_online"].append(r)
            result["renewal_f2f"].append(r)
        elif btype == "gemp_training":
            g = {"id": bid, "label": build_batch_label(name, TYPE_OFFSETS["gemp_training"], start_date)}
            result["gemp_online"].append(g)
            result["gemp_f2f"].append(g)
    return result


def get_batches_full():
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT id, name, type, start_date, created_at FROM batches ORDER BY start_date")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [dict(r) for r in rows]


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
            photo_id, resume, expired_doe, valid_id,
            gemp_designation
        ) VALUES (%s,%s,%s,%s, %s,%s,%s,%s, %s,%s,%s, %s,%s,%s,%s,%s, %s,%s, %s,%s,%s,%s, %s)
    """, (
        entry.get("id"),           entry.get("form_type"),   entry.get("form_label"), entry.get("submitted_at"),
        entry.get("title"),        entry.get("full_name"),   entry.get("middle_name"), entry.get("residence"),
        entry.get("company_name"), entry.get("designation"), entry.get("company_address"),
        entry.get("contact_number"), entry.get("email"), entry.get("birthdate"), entry.get("age"), entry.get("doe_expiry"),
        entry.get("training_type"), entry.get("batch_id") or None,
        entry.get("photo_id"), entry.get("resume"), entry.get("expired_doe"), entry.get("valid_id"),
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
