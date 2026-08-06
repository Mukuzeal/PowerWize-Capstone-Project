import psycopg2.extras

from .core import get_db


def save_feedback(user_id, module_id, rating, comment):
    conn = get_db(); cur = conn.cursor()
    cur.execute(
        "INSERT INTO feedback (user_id, module_id, rating, comment) VALUES (%s,%s,%s,%s) "
        "ON CONFLICT (user_id, module_id) DO UPDATE SET rating=EXCLUDED.rating, comment=EXCLUDED.comment, created_at=NOW()",
        (user_id, module_id, rating, comment)
    )
    conn.commit(); cur.close(); conn.close()


def get_feedback(module_id=None):
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if module_id:
        cur.execute("""
            SELECT f.*, u.fname, u.lname, m.title AS module_title
            FROM feedback f
            JOIN users u ON f.user_id = u.id
            JOIN lms_modules m ON f.module_id = m.id
            WHERE f.module_id = %s ORDER BY f.created_at DESC
        """, (module_id,))
    else:
        cur.execute("""
            SELECT f.*, u.fname, u.lname, m.title AS module_title
            FROM feedback f
            JOIN users u ON f.user_id = u.id
            JOIN lms_modules m ON f.module_id = m.id
            ORDER BY f.created_at DESC
        """)
    rows = cur.fetchall(); cur.close(); conn.close()
    return [dict(r) for r in rows]


def get_feedback_summary():
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT m.title, COUNT(*) AS count, ROUND(AVG(f.rating), 1) AS avg_rating
        FROM feedback f JOIN lms_modules m ON f.module_id = m.id
        GROUP BY f.module_id, m.title ORDER BY avg_rating DESC
    """)
    rows = cur.fetchall(); cur.close(); conn.close()
    return [dict(r) for r in rows]


def get_user_feedback(user_id, module_id):
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM feedback WHERE user_id=%s AND module_id=%s", (user_id, module_id))
    row = cur.fetchone(); cur.close(); conn.close()
    return dict(row) if row else None


# ── Audit log helpers ─────────────────────────────────────────────────────────

def audit_log(user_id, action, entity_type=None, entity_id=None, details=None):
    try:
        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "INSERT INTO audit_logs (user_id, action, entity_type, entity_id, details) "
            "VALUES (%s,%s,%s,%s,%s)",
            (user_id, action, entity_type, str(entity_id) if entity_id is not None else None, details)
        )
        conn.commit(); cur.close(); conn.close()
    except Exception:
        pass


def get_audit_logs(limit=300):
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT a.*, u.fname, u.lname, u.role
        FROM audit_logs a
        LEFT JOIN users u ON a.user_id = u.id
        ORDER BY a.created_at DESC LIMIT %s
    """, (limit,))
    rows = cur.fetchall(); cur.close(); conn.close()
    return [dict(r) for r in rows]


# ── Admin analytics ───────────────────────────────────────────────────────────

def get_analytics_data():
    conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("""
        SELECT TO_CHAR(paid_at, 'YYYY-MM') AS month, SUM(amount_php) AS revenue,
               COUNT(*) AS count
        FROM payments WHERE status='paid' AND paid_at IS NOT NULL
        GROUP BY month ORDER BY month ASC LIMIT 12
    """)
    revenue_monthly = [dict(r) for r in cur.fetchall()]

    cur.execute("SELECT COALESCE(SUM(amount_php),0) AS total FROM payments WHERE status='paid'")
    total_revenue = float(cur.fetchone()["total"])

    cur.execute("SELECT form_type, COUNT(*) AS count FROM registrations GROUP BY form_type ORDER BY count DESC")
    reg_by_type = [dict(r) for r in cur.fetchall()]

    cur.execute("SELECT status, COUNT(*) AS count FROM registrations GROUP BY status")
    reg_by_status = [dict(r) for r in cur.fetchall()]

    cur.execute("""
        SELECT m.title, COUNT(*) AS completions
        FROM lms_progress p JOIN lms_modules m ON p.module_id = m.id
        WHERE p.completed = 1
        GROUP BY m.id, m.title ORDER BY completions DESC LIMIT 10
    """)
    lms_completions = [dict(r) for r in cur.fetchall()]

    cur.execute("SELECT status, COUNT(*) AS count FROM solar_requests GROUP BY status ORDER BY count DESC")
    solar_by_status = [dict(r) for r in cur.fetchall()]

    cur.execute("""
        SELECT payment_status, COUNT(*) AS count FROM users
        WHERE role='trainee' AND archived_at IS NULL GROUP BY payment_status
    """)
    payment_split = [dict(r) for r in cur.fetchall()]

    cur.close(); conn.close()
    return {
        "revenue_monthly":  revenue_monthly,
        "total_revenue":    total_revenue,
        "reg_by_type":      reg_by_type,
        "reg_by_status":    reg_by_status,
        "lms_completions":  lms_completions,
        "solar_by_status":  solar_by_status,
        "payment_split":    payment_split,
    }
