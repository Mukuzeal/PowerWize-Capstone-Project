from flask import redirect, flash, session, request, render_template, abort, jsonify
from werkzeug.security import generate_password_hash

from db import get_db, dict_cur, audit_log
from utils import check_required

from . import admin_bp, require_admin

VALID_ROLES = ("admin", "employee", "trainee")


@admin_bp.route("/admin/user/create", methods=["GET", "POST"])
def admin_create_user():
    resp = require_admin()
    if resp:
        return resp

    if request.method == "GET":
        return render_template("admin/user_form.html", user=None, errors=[], form_data=None)

    fname          = request.form.get("fname", "").strip()
    lname          = request.form.get("lname", "").strip()
    email          = request.form.get("email", "").strip().lower()
    role           = request.form.get("role", "").strip()
    password       = request.form.get("password", "").strip()
    contact_number = request.form.get("contact_number", "").strip()
    company_name   = request.form.get("company_name", "").strip()
    training_type  = request.form.get("training_type", "").strip() or None
    payment_status = request.form.get("payment_status", "unpaid").strip()

    errors = check_required(First_Name=fname, Last_Name=lname, Email=email,
                            Role=role, Temporary_Password=password)
    if role and role not in VALID_ROLES:
        errors.append("Invalid role.")
    if password and len(password) < 8:
        errors.append("Password must be at least 8 characters.")
    if role != "trainee":
        training_type = None
        payment_status = "paid"
    elif not training_type:
        errors.append("Training Type is required.")

    if not errors:
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE email = %s", (email,))
        if cur.fetchone():
            errors.append(f"{email} is already registered.")
        cur.close(); conn.close()

    is_xhr = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    if errors:
        if is_xhr:
            return jsonify(errors=errors), 400
        return render_template("admin/user_form.html", user=None, errors=errors, form_data=request.form)

    conn = get_db(); cur = conn.cursor()
    cur.execute(
        """INSERT INTO users (role, fname, lname, email, password_hash, contact_number,
                              company_name, payment_status, training_type)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
        (role, fname, lname, email, generate_password_hash(password),
         contact_number or None, company_name or None, payment_status, training_type)
    )
    uid = cur.fetchone()[0]
    conn.commit(); cur.close(); conn.close()
    audit_log(session.get("user_id"), "create_user", "user", uid,
              f"Created {role} account for {fname} {lname} ({email})")
    flash(f"{fname} {lname} has been added as a{'n' if role == 'admin' else ''} {role}.", "success")
    if is_xhr:
        return jsonify(ok=True, redirect="/admin#users")
    return redirect("/admin#users")


@admin_bp.route("/admin/user/edit/<int:user_id>", methods=["GET", "POST"])
def admin_edit_user(user_id):
    resp = require_admin()
    if resp:
        return resp

    conn = get_db(); cur = dict_cur(conn)
    cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    user = cur.fetchone()
    cur.close(); conn.close()
    if not user:
        abort(404)

    if request.method == "GET":
        return render_template("admin/user_form.html", user=user, errors=[], form_data=None)

    fname          = request.form.get("fname", "").strip()
    lname          = request.form.get("lname", "").strip()
    email          = request.form.get("email", "").strip().lower()
    role           = request.form.get("role", "").strip()
    contact_number = request.form.get("contact_number", "").strip()
    company_name   = request.form.get("company_name", "").strip()
    training_type  = request.form.get("training_type", "").strip() or None
    payment_status = request.form.get("payment_status", user["payment_status"]).strip()

    errors = check_required(First_Name=fname, Last_Name=lname, Email=email, Role=role)
    if role and role not in VALID_ROLES:
        errors.append("Invalid role.")
    if role != "trainee":
        training_type = None
        payment_status = "paid"
    elif not training_type:
        errors.append("Training Type is required.")

    is_xhr = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    if not errors:
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE email = %s AND id != %s", (email, user_id))
        if cur.fetchone():
            errors.append(f"{email} is already used by another account.")
        cur.close(); conn.close()

    if errors:
        if is_xhr:
            return jsonify(errors=errors), 400
        merged = dict(user); merged.update(request.form)
        return render_template("admin/user_form.html", user=user, errors=errors, form_data=merged)

    conn = get_db(); cur = conn.cursor()
    cur.execute(
        """UPDATE users SET fname=%s, lname=%s, email=%s, role=%s, contact_number=%s,
                            company_name=%s, payment_status=%s, training_type=%s
           WHERE id=%s""",
        (fname, lname, email, role, contact_number or None, company_name or None,
         payment_status, training_type, user_id)
    )
    conn.commit(); cur.close(); conn.close()
    audit_log(session.get("user_id"), "edit_user", "user", user_id,
              f"Updated account details for {fname} {lname} ({email})")
    flash(f"{fname} {lname}'s account has been updated.", "success")
    if is_xhr:
        return jsonify(ok=True, redirect="/admin#users")
    return redirect("/admin#users")


@admin_bp.route("/admin/user/archive/<int:user_id>", methods=["POST"])
def admin_archive_user(user_id):
    resp = require_admin()
    if resp:
        return resp
    conn = get_db()
    cur  = dict_cur(conn)
    cur.execute("SELECT fname, lname FROM users WHERE id = %s", (user_id,))
    user = cur.fetchone()
    cur.execute("UPDATE users SET archived_at = NOW() WHERE id = %s", (user_id,))
    conn.commit()
    cur.close()
    conn.close()
    name = f"{user['fname']} {user['lname']}" if user else "User"
    audit_log(session.get("user_id"), "archive_user", "user", user_id, f"Archived {name}")
    flash(f"{name} has been archived.", "warning")
    return redirect("/admin#users")


@admin_bp.route("/admin/user/unarchive/<int:user_id>", methods=["POST"])
def admin_unarchive_user(user_id):
    resp = require_admin()
    if resp:
        return resp
    conn = get_db()
    cur  = dict_cur(conn)
    cur.execute("SELECT fname, lname FROM users WHERE id = %s", (user_id,))
    user = cur.fetchone()
    cur.execute("UPDATE users SET archived_at = NULL WHERE id = %s", (user_id,))
    conn.commit()
    cur.close()
    conn.close()
    name = f"{user['fname']} {user['lname']}" if user else "User"
    audit_log(session.get("user_id"), "unarchive_user", "user", user_id, f"Restored {name}")
    flash(f"{name} has been restored.", "success")
    return redirect("/admin#users")


@admin_bp.route("/admin/user/delete/<int:user_id>", methods=["POST"])
def admin_delete_user(user_id):
    resp = require_admin()
    if resp:
        return resp
    conn = get_db()
    cur  = dict_cur(conn)
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
    audit_log(session.get("user_id"), "delete_user", "user", user_id, f"Permanently deleted {name}")
    flash(f"{name} has been permanently deleted.", "error")
    return redirect("/admin#users")
