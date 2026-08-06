from datetime import date

from flask import request, redirect, flash, session

from db import (get_db, dict_cur, set_registration_status, build_batch_label,
                TYPE_OFFSETS, create_account_token, audit_log)
from email_utils import send_acceptance_email

from . import admin_bp


@admin_bp.route("/admin/registration/<reg_id>/status/<status>", methods=["POST"])
def admin_registration_status(reg_id, status):
    if status not in ("accepted", "rejected", "pending"):
        return redirect("/admin#registrations")

    is_qualified = request.form.get("qualified", "1") == "1"
    set_registration_status(reg_id, status, is_qualified if status == "accepted" else None)

    if status == "accepted":
        # Fetch the registration to get email and name
        conn = get_db()
        cur  = dict_cur(conn)
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
        audit_log(session.get("user_id"), "registration_accepted", "registration", reg_id,
                  f"Accepted registration #{reg_id} (qualified={is_qualified})")
    else:
        audit_log(session.get("user_id"), f"registration_{status}", "registration", reg_id,
                  f"Marked registration #{reg_id} as {status}")
        flash(f"Registration #{reg_id} marked as {status}.", "warning")

    return redirect("/admin#registrations")


@admin_bp.route("/admin/schedule/delete/<int:schedule_id>", methods=["POST"])
def admin_delete_schedule(schedule_id):
    conn = get_db()
    cur  = dict_cur(conn)
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
