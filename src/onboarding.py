from datetime import datetime
from flask import Blueprint, request, render_template, redirect, flash, session, make_response
from werkzeug.security import generate_password_hash
from db import (get_account_token, normalize_training_type,
                redeem_invitation_and_create_account)

onboarding_bp = Blueprint("onboarding", __name__)


@onboarding_bp.after_request
def private_activation(response):
    response.headers.update({'Cache-Control':'no-store','Referrer-Policy':'same-origin','X-Robots-Tag':'noindex, nofollow'})
    return response


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
    from db import account_exists_for_email, claim_existing_enrolment
    if account_exists_for_email(tok['email']):
        if request.method == 'POST':
            reg_id, error = claim_existing_enrolment(token, session.get('user_id'))
            if error:
                errors.append(error)
            else:
                session['active_registration_id'] = reg_id
                for key in ('pending_pi','pending_qr_pi','discount_code','last_receipt_id'):
                    session.pop(key,None)
                session.pop('activation_claim_token', None)
                flash('Your approved enrolment is now linked to your existing account.', 'success')
                return redirect('/portal')
        return render_template('shared/claim_enrolment.html', tok=tok, errors=errors)
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
                # Redeeming the private invitation and choosing a password
                # already established this new account's identity. Avoid a
                # second password form, and discard the previous session.
                session.clear()
                session.update(user_id=uid,user_role='trainee',user_email=tok['email'],
                               user_name=tok['full_name'],active_registration_id=tok['reg_id'])
                flash('Account activated. Here is your enrolment and its next step.', 'success')
                return redirect('/portal')

    return render_template("shared/create_account.html", tok=tok, errors=errors)


@onboarding_bp.route('/create-account/<token>/sign-in', methods=['POST'])
def sign_in_to_claim(token):
    tok = get_account_token(token)
    if not tok or tok['used_at'] or tok['expires_at'] < datetime.now():
        return render_template('auth/token_invalid.html', reason='This invitation is no longer available.'), 404
    session['activation_claim_token'] = token
    return redirect('/auth')

