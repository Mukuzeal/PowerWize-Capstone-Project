from flask import Blueprint, request, render_template, redirect, session, url_for
from werkzeug.security import generate_password_hash, check_password_hash
from db import get_db

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/auth")
def auth():
    return render_template("landing.html", active_tab="login",
                           login_errors=[], login_data=None,
                           reg_errors=[], reg_data=None, reg_success=False)


@auth_bp.route("/auth/login", methods=["POST"])
def auth_login():
    email    = request.form.get("email", "").strip()
    password = request.form.get("password", "").strip()

    errors = []
    if not email:    errors.append("Email is required.")
    if not password: errors.append("Password is required.")

    if not errors:
        conn = get_db()
        cur  = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT id, role, fname, lname, email, password_hash, payment_status, archived_at
            FROM users WHERE email = %s AND archived_at IS NULL
        """, (email,))
        user = cur.fetchone()
        cur.close(); conn.close()

        if not user or not check_password_hash(user["password_hash"], password):
            errors.append("Invalid email or password.")
        else:
            session["user_id"]   = user["id"]
            session["user_role"] = user["role"]
            session["user_name"] = f"{user['fname']} {user['lname']}"
            if user["role"] == "admin":
                return redirect("/admin")
            if user.get("payment_status") == "unpaid":
                return redirect("/payment")
            return redirect("/portal")

    return render_template("landing.html", active_tab="login",
                           login_errors=errors, login_data=request.form,
                           reg_errors=[], reg_data=None, reg_success=False)


@auth_bp.route("/auth/register", methods=["POST"])
def auth_register():
    f        = request.form
    fname    = f.get("fname", "").strip()
    lname    = f.get("lname", "").strip()
    email    = f.get("email", "").strip()
    password = f.get("password", "").strip()
    confirm  = f.get("confirm_password", "").strip()
    contact  = f.get("contact_number", "").strip()
    company  = f.get("company_name", "").strip()

    errors = []
    if not fname:    errors.append("First name is required.")
    if not lname:    errors.append("Last name is required.")
    if not email:    errors.append("Email is required.")
    if not password: errors.append("Password is required.")
    elif len(password) < 8:
        errors.append("Password must be at least 8 characters.")
    if password and confirm != password:
        errors.append("Passwords do not match.")
    if not contact:  errors.append("Contact number is required.")

    if not errors:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("SELECT id FROM users WHERE email = %s", (email,))
        if cur.fetchone():
            errors.append("An account with that email already exists.")
        cur.close(); conn.close()

    if errors:
        return render_template("landing.html", active_tab="register",
                               login_errors=[], login_data=None,
                               reg_errors=errors, reg_data=f, reg_success=False)

    conn = get_db()
    cur  = conn.cursor()
    cur.execute(
        "INSERT INTO users (role, fname, lname, email, password_hash, contact_number, company_name) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
        ("trainee", fname, lname, email,
         generate_password_hash(password), contact, company)
    )
    conn.commit(); cur.close(); conn.close()

    return render_template("landing.html", active_tab="register",
                           login_errors=[], login_data=None,
                           reg_errors=[], reg_data=None, reg_success=True)


@auth_bp.route("/auth/logout")
def auth_logout():
    session.clear()
    return redirect("/auth")
