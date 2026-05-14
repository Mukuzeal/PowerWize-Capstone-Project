from datetime import datetime
from flask import Blueprint, request, render_template, redirect, flash, session
from werkzeug.security import generate_password_hash
from db import get_db, get_account_token, mark_token_used

onboarding_bp = Blueprint("onboarding", __name__)


@onboarding_bp.route("/create-account/<token>", methods=["GET", "POST"])
def create_account(token):
    tok = get_account_token(token)

    if not tok:
        return render_template("auth/token_invalid.html", reason="This link is invalid.")
    if tok["used_at"]:
        return render_template("auth/token_invalid.html", reason="This link has already been used.")
    if datetime.now() > tok["expires_at"]:
        return render_template("auth/token_invalid.html", reason="This link has expired.")

    errors = []
    if request.method == "POST":
        password = request.form.get("password", "").strip()
        confirm  = request.form.get("confirm_password", "").strip()

        if not password:
            errors.append("Password is required.")
        elif len(password) < 8:
            errors.append("Password must be at least 8 characters.")
        if password and confirm != password:
            errors.append("Passwords do not match.")

        if not errors:
            conn = get_db()
            cur  = conn.cursor()
            # Check if account already exists for this email
            cur.execute("SELECT id FROM users WHERE email = %s", (tok["email"],))
            if cur.fetchone():
                errors.append("An account already exists for this email. Please log in.")
                cur.close(); conn.close()
            else:
                name_parts = tok["full_name"].split()
                fname = name_parts[0] if name_parts else tok["full_name"]
                lname = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""
                cur.execute(
                    "INSERT INTO users (role, fname, lname, email, password_hash, contact_number, company_name, payment_status, training_type) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    ("trainee", fname, lname, tok["email"],
                     generate_password_hash(password),
                     tok.get("contact_number", ""), tok.get("company_name", ""),
                     "unpaid", tok.get("training_type", "training"))
                )
                conn.commit()
                cur.close(); conn.close()
                mark_token_used(token)
                flash("Account created successfully! Please log in.", "success")
                return redirect("/auth")

    return render_template("shared/create_account.html", tok=tok, errors=errors)

