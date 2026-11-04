from datetime import datetime
from flask import Blueprint, request, render_template, redirect, flash, session
from werkzeug.security import generate_password_hash
from db import (get_account_token, normalize_training_type,
                redeem_invitation_and_create_account)

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
            name_parts = tok["full_name"].split()
            fname = name_parts[0] if name_parts else tok["full_name"]
            lname = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""

            # Token claim + account insert + registration link, in ONE
            # transaction. This used to be three separate connections (read
            # token / insert user / mark used), so a crash or a double submit
            # could leave a committed account with a still-live token.
            uid, err = redeem_invitation_and_create_account(
                token, generate_password_hash(password), fname, lname,
                tok.get("contact_number", ""), tok.get("company_name", ""),
                normalize_training_type(tok.get("form_type"), tok.get("training_type")))
            if err:
                errors.append(err)
            else:
                flash("Account created successfully! Please log in.", "success")
                return redirect("/auth")

    return render_template("shared/create_account.html", tok=tok, errors=errors)

