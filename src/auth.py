import math
from datetime import datetime

from flask import Blueprint, request, render_template, redirect, session, url_for
from werkzeug.security import generate_password_hash, check_password_hash
from db import (get_db, dict_cur, create_reset_token, get_reset_token, mark_reset_token_used,
                reset_user_password, get_user_by_email, register_failed_login,
                reset_login_attempts, MAX_LOGIN_ATTEMPTS, LOCKOUT_MINUTES)
from utils import base_url

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/auth")
def auth():
    return render_template("shared/landing.html", login_errors=[], login_data=None)


@auth_bp.route("/auth/login", methods=["POST"])
def auth_login():
    email    = request.form.get("email", "").strip()
    password = request.form.get("password", "").strip()

    errors = []
    if not email:    errors.append("Email is required.")
    if not password: errors.append("Password is required.")

    if not errors:
        conn = get_db()
        cur  = dict_cur(conn)
        cur.execute("""
            SELECT id, role, fname, lname, email, password_hash, payment_status, archived_at,
                   failed_login_attempts, locked_until
            FROM users WHERE email = %s AND archived_at IS NULL
        """, (email,))
        user = cur.fetchone()
        cur.close(); conn.close()

        if user and user["locked_until"] and user["locked_until"] > datetime.now():
            minutes_left = max(1, math.ceil((user["locked_until"] - datetime.now()).total_seconds() / 60))
            errors.append(f"Too many failed attempts. Try again in {minutes_left} "
                          f"minute{'s' if minutes_left != 1 else ''}.")
        elif not user or not check_password_hash(user["password_hash"], password):
            if user:
                state = register_failed_login(user["email"])
                attempts_left = MAX_LOGIN_ATTEMPTS - state["failed_login_attempts"]
                if attempts_left <= 0:
                    errors.append(f"Too many failed attempts. Your account is locked for "
                                  f"{LOCKOUT_MINUTES} minutes.")
                else:
                    errors.append(f"Invalid email or password. {attempts_left} "
                                  f"attempt{'s' if attempts_left != 1 else ''} left before "
                                  f"your account is locked.")
            else:
                errors.append("Invalid email or password.")
        else:
            reset_login_attempts(user["email"])
            session["user_id"]   = user["id"]
            session["user_role"] = user["role"]
            session["user_name"] = f"{user['fname']} {user['lname']}"
            session["user_email"] = user["email"]
            if user["role"] == "admin":
                return redirect("/admin")
            if user["role"] == "employee":
                return redirect("/employee")
            if user["role"] == "trainee" and user.get("payment_status") == "unpaid":
                return redirect("/payment")
            return redirect("/portal")

    return render_template("shared/landing.html",
                           login_errors=errors, login_data=request.form)


# There is deliberately no public self-registration route. An account is only
# created from a vetted invitation: registration form -> admin review -> emailed
# token -> /create-account/<token> (src/onboarding.py), which carries the
# training_type and payment_status the trainee was approved for. A plain
# email+password signup would mint trainees that skipped ID upload, selfie
# liveness and admin verification entirely.


@auth_bp.route("/auth/logout")
def auth_logout():
    session.clear()
    return redirect("/auth")


# ── Forgot password ───────────────────────────────────────────────────────────

@auth_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "GET":
        return render_template("auth/forgot_password.html", sent=False, error=None)

    email = request.form.get("email", "").strip().lower()
    if not email:
        return render_template("auth/forgot_password.html", sent=False, error="Email is required.")

    user = get_user_by_email(email)
    if user:
        try:
            from email_utils import send_password_reset_email
            token = create_reset_token(email)
            send_password_reset_email(user["email"], f"{user['fname']} {user['lname']}",
                                      token, base_url())
        except Exception as e:
            import traceback; traceback.print_exc()

    # Always show "sent" regardless of whether email exists (prevents enumeration)
    return render_template("auth/forgot_password.html", sent=True, error=None)


@auth_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    from datetime import datetime
    row = get_reset_token(token)

    if not row or row["used_at"] or row["expires_at"] < datetime.now():
        return render_template("auth/reset_password.html", token=token,
                               invalid=True, success=False, errors=[])

    if request.method == "GET":
        return render_template("auth/reset_password.html", token=token,
                               invalid=False, success=False, errors=[])

    password = request.form.get("password", "").strip()
    confirm  = request.form.get("confirm_password", "").strip()
    errors   = []
    if not password:
        errors.append("Password is required.")
    elif len(password) < 8:
        errors.append("Password must be at least 8 characters.")
    if password and confirm != password:
        errors.append("Passwords do not match.")

    if errors:
        return render_template("auth/reset_password.html", token=token,
                               invalid=False, success=False, errors=errors)

    reset_user_password(row["email"], generate_password_hash(password))
    mark_reset_token_used(token)
    return render_template("auth/reset_password.html", token=token,
                           invalid=False, success=True, errors=[])

