import psycopg2.extras

from .core import get_db


def save_solar_request(data: dict) -> int:
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("""
        INSERT INTO solar_requests (
            user_id, name, address, email, contact,
            establishment_type, ownership, electrical_phase,
            monthly_bill_php, kwh_monthly, time_of_use_night_pct,
            target_savings, roof_sqm, notes, bill_path,
            ocr_kwh, ocr_bill_amount
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        RETURNING id
    """, (
        data.get("user_id"), data.get("name"), data.get("address"),
        data.get("email"), data.get("contact"),
        data.get("establishment_type"), data.get("ownership"),
        data.get("electrical_phase"),
        data.get("monthly_bill_php"), data.get("kwh_monthly"),
        data.get("time_of_use_night_pct"), data.get("target_savings"),
        data.get("roof_sqm"), data.get("notes"), data.get("bill_path"),
        data.get("ocr_kwh"), data.get("ocr_bill_amount"),
    ))
    conn.commit()
    req_id = cur.fetchone()[0]
    cur.close(); conn.close()
    return req_id


def update_solar_request(req_id: int, **fields):
    if not fields:
        return
    allowed = {
        "system_size_kw", "panel_count", "cost_min", "cost_max",
        "monthly_savings", "roi_years", "feasibility", "system_type",
        "battery_recommended", "ai_explanation", "status",
        "reviewer_notes", "reviewed_at", "email", "contact",
        "final_system_kw", "final_panel_count", "final_cost",
    }
    safe = {k: v for k, v in fields.items() if k in allowed}
    if not safe:
        return
    clauses = ", ".join(f"{k}=%s" for k in safe)
    conn = get_db()
    cur  = conn.cursor()
    cur.execute(f"UPDATE solar_requests SET {clauses} WHERE id=%s",
                (*safe.values(), req_id))
    conn.commit()
    cur.close(); conn.close()


def get_solar_request(req_id: int) -> dict | None:
    conn = get_db()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM solar_requests WHERE id=%s", (req_id,))
    row = cur.fetchone()
    cur.close(); conn.close()
    return dict(row) if row else None


def get_solar_requests() -> list:
    conn = get_db()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM solar_requests ORDER BY created_at DESC")
    rows = cur.fetchall()
    cur.close(); conn.close()
    return [dict(r) for r in rows]


def get_solar_requests_by_user(user_id: int) -> list:
    conn = get_db()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM solar_requests WHERE user_id=%s ORDER BY created_at DESC", (user_id,))
    rows = cur.fetchall()
    cur.close(); conn.close()
    return [dict(r) for r in rows]
