from datetime import date

from flask import request, redirect, flash, session, current_app, send_from_directory, abort

from db import (get_db, dict_cur, set_registration_status, build_batch_label,
                build_label_from_dates, expand_offsets, TYPE_OFFSETS,
                create_account_token, audit_log, get_pending_selfies)
from email_utils import send_acceptance_email
from utils import base_url

from . import admin_bp, require_admin


@admin_bp.route("/admin/registration/<reg_id>/status/<status>", methods=["POST"])
def admin_registration_status(reg_id, status):
    resp = require_admin()
    if resp:
        return resp
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
                send_acceptance_email(reg["email"], reg["full_name"], token, is_qualified, base_url())
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
    resp = require_admin()
    if resp:
        return resp
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


@admin_bp.route("/admin/schedule/edit/<int:schedule_id>", methods=["POST"])
def admin_edit_schedule(schedule_id):
    """Update a batch's name and/or its individual run days. `dates` arrives
    as one repeated form field per day (in whatever order the admin's edit
    dialog rendered them) — exactly as many as the batch already has, since
    this only lets you move a day, not add or remove one."""
    resp = require_admin()
    if resp:
        return resp
    conn = get_db()
    cur  = dict_cur(conn)
    cur.execute("SELECT name, type, start_date, dates FROM batches WHERE id = %s", (schedule_id,))
    row = cur.fetchone()
    if not row:
        cur.close()
        conn.close()
        flash("Batch not found.", "error")
        return redirect("/admin#schedules")

    name = request.form.get("name", "").strip() or row["name"]
    date_strs = [d for d in request.form.getlist("dates") if d.strip()]
    if date_strs:
        dates = sorted(date.fromisoformat(d) for d in date_strs)
    else:
        dates = sorted(row["dates"]) if row["dates"] else [row["start_date"]]
    start_date = dates[0]

    cur.execute("UPDATE batches SET name = %s, start_date = %s, dates = %s WHERE id = %s",
                (name, start_date, dates, schedule_id))
    conn.commit()
    cur.close()
    conn.close()

    label = build_label_from_dates(name, dates)
    flash(f'"{label}" has been updated.', "success")
    return redirect("/admin#schedules")


@admin_bp.route("/admin/schedule/add", methods=["POST"])
def admin_add_schedule():
    resp = require_admin()
    if resp:
        return resp
    name      = request.form.get("name",       "").strip()
    start_str = request.form.get("start_date", "").strip()
    btype = request.form.get("btype", "").strip()
    if name and btype in ("training", "renewal") and start_str:
        start_date = date.fromisoformat(start_str)
        offsets    = TYPE_OFFSETS["training"] if btype == "training" else TYPE_OFFSETS["renewal"]
        dates      = expand_offsets(offsets, start_date)
        label      = build_batch_label(name, offsets, start_date)
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("INSERT INTO batches (name, type, start_date, dates) VALUES (%s, %s, %s, %s)",
                    (name, btype, start_date, dates))
        conn.commit()
        cur.close()
        conn.close()
        flash(f'"{label}" has been added.', "success")
    return redirect("/admin#schedules")


@admin_bp.route("/admin/registration/<reg_id>/selfie")
def admin_registration_selfie(reg_id):
    resp = require_admin()
    if resp:
        return resp
    conn = get_db()
    cur  = dict_cur(conn)
    cur.execute("SELECT selfie_with_id FROM registrations WHERE id = %s", (reg_id,))
    reg = cur.fetchone()
    cur.close()
    conn.close()

    if not reg or not reg.get("selfie_with_id"):
        abort(404)
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], reg["selfie_with_id"])


@admin_bp.route("/admin/selfie/<reg_id>/approve", methods=["POST"])
def admin_approve_selfie(reg_id):
    resp = require_admin()
    if resp:
        return resp
    conn = get_db()
    cur  = dict_cur(conn)
    cur.execute("SELECT email, full_name FROM registrations WHERE id = %s", (reg_id,))
    reg = cur.fetchone()
    cur.close()

    if reg and reg.get("email"):
        try:
            token = create_account_token(reg_id, reg["email"], is_qualified=True)
            send_acceptance_email(reg["email"], reg["full_name"], token, True, base_url())
            flash(f"Registration #{reg_id} verified. Account setup email sent.", "success")
            audit_log(session.get("user_id"), "selfie_verified", "registration", reg_id,
                      f"Approved selfie verification for registration #{reg_id}")
        except Exception as e:
            flash(f"Verified but email failed: {e}", "warning")
    else:
        flash(f"Registration #{reg_id} verified. (No email on file.)", "warning")

    conn.close()
    return redirect("/admin#selfies")


@admin_bp.route("/admin/selfie/<reg_id>/reject", methods=["POST"])
def admin_reject_selfie(reg_id):
    resp = require_admin()
    if resp:
        return resp
    reason = request.form.get("reason", "").strip()
    conn = get_db()
    cur  = conn.cursor()
    cur.execute(
        "UPDATE registrations SET selfie_with_id = NULL WHERE id = %s",
        (reg_id,)
    )
    conn.commit()
    cur.close()
    conn.close()
    flash(f"Registration #{reg_id} selfie rejected.", "warning")
    audit_log(session.get("user_id"), "selfie_rejected", "registration", reg_id,
              f"Rejected selfie: {reason}")
    return redirect("/admin#selfies")
