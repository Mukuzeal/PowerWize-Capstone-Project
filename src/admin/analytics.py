from flask import session, jsonify

from db import get_analytics_data, get_feedback, get_feedback_summary, get_audit_logs

from . import admin_bp


# ── Analytics JSON ────────────────────────────────────────────────────────────

@admin_bp.route("/admin/analytics")
def admin_analytics():
    if session.get("user_role") != "admin":
        return jsonify(error="Unauthorized"), 403
    data = get_analytics_data()
    # Convert Decimal to float for JSON serialisation
    for row in data.get("revenue_monthly", []):
        if row.get("revenue") is not None:
            row["revenue"] = float(row["revenue"])
    return jsonify(data)


# ── Feedback JSON ─────────────────────────────────────────────────────────────

@admin_bp.route("/admin/feedback-json")
def admin_feedback_json():
    if session.get("user_role") != "admin":
        return jsonify(error="Unauthorized"), 403
    feedback = get_feedback()
    summary  = get_feedback_summary()
    # Serialise datetime objects
    for row in feedback:
        if row.get("created_at"):
            row["created_at"] = str(row["created_at"])
    for s in summary:
        s["module_title"] = s["title"]
        s["avg_rating"] = float(s["avg_rating"] or 0)
    return jsonify(feedback=feedback, summary=summary)


# ── Audit log JSON ────────────────────────────────────────────────────────────

@admin_bp.route("/admin/audit-log-json")
def admin_audit_log_json():
    if session.get("user_role") != "admin":
        return jsonify(error="Unauthorized"), 403
    logs = get_audit_logs(limit=500)
    for row in logs:
        if row.get("created_at"):
            row["created_at"] = str(row["created_at"])
    return jsonify(logs=logs)
