from datetime import date
from flask import Blueprint, request, render_template, redirect, flash, url_for
from db import get_db, get_batches_full, get_users, get_registrations, set_registration_status, build_batch_label, TYPE_OFFSETS, create_account_token
from email_utils import send_acceptance_email

admin_bp = Blueprint("admin", __name__)


@admin_bp.route("/admin")
def admin():
    users = get_users()
    uc = {
        "admin":          sum(1 for u in users if u["role"] == "admin"),
        "employee":       sum(1 for u in users if u["role"] == "employee"),
        "trainee":        sum(1 for u in users if u["role"] == "trainee"),
        "archived":       sum(1 for u in users if u["archived_at"] is not None),
        "active":         sum(1 for u in users if u["archived_at"] is None),
        "active_trainee": sum(1 for u in users if u["role"] == "trainee" and u["archived_at"] is None),
    }
    from datetime import timedelta
    all_batches = get_batches_full()
    today = date.today()
    end_offsets = {"training": 9, "renewal": 1}
    upcoming, past = [], []
    for b in all_batches:
        b["end_date"] = b["start_date"] + timedelta(days=end_offsets.get(b["type"], 0))
        (past if b["end_date"] < today else upcoming).append(b)

    return render_template("admin.html",
                           registrations=get_registrations(),
                           schedules=upcoming,
                           past_schedules=past,
                           users=users,
                           uc=uc)


@admin_bp.route("/admin/user/archive/<int:user_id>", methods=["POST"])
def admin_archive_user(user_id):
    conn = get_db()
    cur  = conn.cursor(dictionary=True)
    cur.execute("SELECT fname, lname FROM users WHERE id = %s", (user_id,))
    user = cur.fetchone()
    cur.execute("UPDATE users SET archived_at = NOW() WHERE id = %s", (user_id,))
    conn.commit()
    cur.close()
    conn.close()
    name = f"{user['fname']} {user['lname']}" if user else "User"
    flash(f"{name} has been archived.", "warning")
    return redirect("/admin#users")


@admin_bp.route("/admin/user/unarchive/<int:user_id>", methods=["POST"])
def admin_unarchive_user(user_id):
    conn = get_db()
    cur  = conn.cursor(dictionary=True)
    cur.execute("SELECT fname, lname FROM users WHERE id = %s", (user_id,))
    user = cur.fetchone()
    cur.execute("UPDATE users SET archived_at = NULL WHERE id = %s", (user_id,))
    conn.commit()
    cur.close()
    conn.close()
    name = f"{user['fname']} {user['lname']}" if user else "User"
    flash(f"{name} has been restored.", "success")
    return redirect("/admin#users")


@admin_bp.route("/admin/user/delete/<int:user_id>", methods=["POST"])
def admin_delete_user(user_id):
    conn = get_db()
    cur  = conn.cursor(dictionary=True)
    cur.execute("SELECT fname, lname, archived_at FROM users WHERE id = %s", (user_id,))
    user = cur.fetchone()
    if not user or user["archived_at"] is None:
        cur.close(); conn.close()
        flash("Only archived users can be deleted.", "error")
        return redirect("/admin#users")
    cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
    conn.commit()
    cur.close(); conn.close()
    name = f"{user['fname']} {user['lname']}"
    flash(f"{name} has been permanently deleted.", "error")
    return redirect("/admin#users")


@admin_bp.route("/admin/registration/<reg_id>/status/<status>", methods=["POST"])
def admin_registration_status(reg_id, status):
    if status not in ("accepted", "rejected", "pending"):
        return redirect("/admin#registrations")

    is_qualified = request.form.get("qualified", "1") == "1"
    set_registration_status(reg_id, status, is_qualified if status == "accepted" else None)

    if status == "accepted":
        # Fetch the registration to get email and name
        conn = get_db()
        cur  = conn.cursor(dictionary=True)
        cur.execute("SELECT email, full_name FROM registrations WHERE id = %s", (reg_id,))
        reg = cur.fetchone()
        cur.close(); conn.close()

        if reg and reg.get("email"):
            try:
                token    = create_account_token(reg_id, reg["email"], is_qualified)
                base_url = request.host_url
                send_acceptance_email(reg["email"], reg["full_name"], token, is_qualified, base_url)
                flash(f"Registration #{reg_id} accepted. Account setup email sent to {reg['email']}.", "success")
            except Exception as e:
                flash(f"Registration #{reg_id} accepted, but email failed: {e}", "warning")
        else:
            flash(f"Registration #{reg_id} accepted. (No email on file — send link manually.)", "warning")
    else:
        flash(f"Registration #{reg_id} marked as {status}.", "warning")

    return redirect("/admin#registrations")


@admin_bp.route("/admin/schedule/delete/<int:schedule_id>", methods=["POST"])
def admin_delete_schedule(schedule_id):
    conn = get_db()
    cur  = conn.cursor(dictionary=True)
    cur.execute("SELECT name FROM batches WHERE id = %s", (schedule_id,))
    row = cur.fetchone()
    cur.execute("DELETE FROM batches WHERE id = %s", (schedule_id,))
    conn.commit()
    cur.close()
    conn.close()
    name = row["name"] if row else "Batch"
    flash(f'"{name}" has been deleted.', "error")
    return redirect("/admin#schedules")


@admin_bp.route("/admin/schedule/add", methods=["POST"])
def admin_add_schedule():
    name      = request.form.get("name",       "").strip()
    start_str = request.form.get("start_date", "").strip()
    btype = request.form.get("btype", "").strip()
    if name and btype in ("training", "renewal") and start_str:
        start_date = date.fromisoformat(start_str)
        offsets    = TYPE_OFFSETS["training"] if btype == "training" else TYPE_OFFSETS["renewal"]
        label      = build_batch_label(name, offsets, start_date)
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("INSERT INTO batches (name, type, start_date) VALUES (%s, %s, %s)", (name, btype, start_date))
        conn.commit()
        cur.close()
        conn.close()
        flash(f'"{label}" has been added.', "success")
    return redirect("/admin#schedules")
