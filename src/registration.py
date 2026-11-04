import uuid
from datetime import date, datetime
from flask import Blueprint, request, render_template, session, redirect
from db import (get_schedules, insert_registration, get_registration_for_user,
                get_user_basic_info, lms_get_modules_for_trainee, lms_get_progress,
                lms_get_module_requirements, lms_get_certificate,
                classes_for_user)
from permissions import is_staff, home_url_for
from site_bp import render_home, render_programs
from utils import save_file, check_required, owns_upload

registration_bp = Blueprint("registration", __name__)


# ── Company intake invitations ───────────────────────────────────────────────
#
# A company-invited applicant reaches the SAME public form; the invitation only
# decides which roster slot the submission attaches to. Nothing about
# validation, uploads or admin review changes, which is the point — there is no
# second registration pipeline.

INVITE_FIELD = "intake_invite"


@registration_bp.after_request
def private_company_registration(response):
    if session.get('company_registration_grant'):
        response.headers['Cache-Control'] = 'no-store'
        # HTTPS CSRF checks need a same-origin referrer; external sites must
        # never receive the company grant URL in a Referer header.
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['X-Robots-Tag'] = 'noindex, nofollow'
    return response


def _invite_token():
    """The invitation accompanying this submission, if any. Accepted from the
    query string (the emailed link) or a hidden form field (the POST)."""
    supplied = (request.values.get(INVITE_FIELD, "") or "").strip()
    grant = session.get('company_registration_grant') or {}
    return supplied or grant.get('token', '')


def save_registration(entry, invite_token=None):
    """Persist a registration, attaching it to a roster slot when invited.

    Returns (reg_id, error). On an invited submission the invitation claim and
    the insert share one transaction, so a half-written state is impossible.
    An invalid or spent invitation is refused outright rather than silently
    falling back to an unattached registration — otherwise a company would see
    a roster slot still reading "not submitted" while the person believes they
    have applied.
    """
    from db import (REGISTRATION_INSERT_SQL, registration_insert_params,
                    claim_slot_with_registration, invitation_state)

    if not invite_token:
        insert_registration(entry)
        return entry["id"], None

    slot, reason = invitation_state(invite_token)
    if not slot:
        return None, ("This invitation link has already been used."
                      if reason == "used" else
                      "This invitation link is not valid or has expired.")
    if slot["form_type"] != entry["form_type"]:
        return None, ("This invitation is for a different training program. "
                      "Please use the link your company sent you.")
    if entry.get('email', '').strip().lower() != slot['email_key']:
        return None, "Use the email address listed for you on the company roster."

    grant = session.get('company_registration_grant') or {}
    shared = grant.get('token') == invite_token
    if shared and entry.get('email', '').strip().lower() != grant.get('email_key'):
        return None, "Use the roster email address you entered for this company registration."
    if shared and (not grant.get('class_id') or not grant.get('class_code_hash')):
        return None, "Open the company registration link and enter your class code again."
    from db import get_intake
    intake = get_intake(intake_id=slot['intake_id'])
    entry['company_name'] = intake['company_name']

    reg_id, err = claim_slot_with_registration(
        invite_token, entry["id"], REGISTRATION_INSERT_SQL,
        registration_insert_params(entry),
        shared_token=grant.get('link_token') if shared else None,
        email_key=grant.get('email_key') if shared else None,
        registration_class_id=grant.get('class_id') if shared else None,
        registration_code_hash=grant.get('class_code_hash') if shared else None)
    if err:
        return None, "This invitation link has already been used."
    if shared:
        session.pop('company_registration_grant', None)
    return reg_id, None


# The public-facing pages live in site_bp; these endpoints keep their names
# because the rest of the app links to them by endpoint.
@registration_bp.route("/")
def index():
    return render_home()


@registration_bp.route("/home")
def home():
    return render_home()


@registration_bp.route("/programs")
def programs():
    return render_programs()


def _portal_learning(user_id):
    """Where this trainee stands in their syllabus, for the portal dashboard.

    Runs each module through _progress_steps — the same helper /lms/progress
    uses — so the bar on the portal and the bar on the progress page can never
    disagree. Any failure here degrades to an empty syllabus rather than taking
    down the account page: the enrolment and payment rows below matter more.
    """
    empty = {"modules": [], "steps_map": {}, "completed": 0, "total": 0, "pct": 0, "cert": None}
    try:
        from lms_bp._shared import _progress_steps

        mods      = lms_get_modules_for_trainee(user_id, published_only=True)
        prog_map  = {p["module_id"]: p for p in lms_get_progress(user_id)}
        reqs      = lms_get_module_requirements([m["id"] for m in mods])
        steps_map = {m["id"]: _progress_steps(prog_map.get(m["id"]), reqs.get(m["id"]))
                     for m in mods}
        completed = sum(1 for m in mods if prog_map.get(m["id"], {}).get("completed"))
        return {
            "modules":   mods,
            "steps_map": steps_map,
            "completed": completed,
            "total":     len(mods),
            "pct":       round(completed / len(mods) * 100) if mods else 0,
            "cert":      lms_get_certificate(user_id=user_id),
        }
    except Exception:
        return empty


@registration_bp.route("/portal")
def portal():
    if "user_id" not in session:
        return redirect("/auth")

    if is_staff():
        return redirect(home_url_for(session.get("user_role")))

    # Fetch user info and their registration
    user = get_user_basic_info(session["user_id"])

    if not user:
        return redirect("/auth/logout")

    if not is_staff() and user["payment_status"] == "unpaid":
        return redirect("/payment")

    reg = get_registration_for_user(session['user_id'])
    lms = _portal_learning(session["user_id"])

    # A certificate is valid for three years (lms_issue_certificate). Flagging
    # the last 90 days gives a trainee time to book a renewal batch.
    cert_days = None
    if lms["cert"] and lms["cert"].get("expires_at"):
        cert_days = (lms["cert"]["expires_at"] - date.today()).days

    return render_template("shared/portal.html", user=user, reg=reg,
                           cert_days=cert_days,
                           my_classes=classes_for_user(session["user_id"]),
                           **lms)


# ── CEA Renewal ──────────────────────────────────────────────────────────────
@registration_bp.route("/renewalCEA")
def renewal():
    return render_template("training/renewalCEA.html", schedules=get_schedules(),
                           errors=[], form_data=None, uploaded={})


@registration_bp.route("/renewal/submit", methods=["POST"])
def renewal_submit():
    f            = request.form
    title        = f.get("title", "").strip()
    full_name    = f.get("full_name", "").strip()
    middle_name  = f.get("middle_name", "").strip()
    company_name = f.get("company_name", "").strip()
    designation  = f.get("designation", "").strip()
    company_address = f.get("company_address", "").strip()
    contact_number  = f.get("contact_number", "").strip()
    email        = f.get("email", "").strip()
    birthdate    = f.get("birthdate", "").strip()
    age          = f.get("age", "").strip()
    doe_expiry   = f.get("doe_expiry", "").strip()
    agree        = f.get("agree", "").strip()
    training_type = f.get("training_type", "").strip()
    batch_id     = f.get("batch_id", "").strip()

    errors = check_required(Title=title, Full_Name=full_name, Middle_Name=middle_name,
        Company_Name=company_name, Designation=designation, Company_Address=company_address,
        Contact_Number=contact_number, Email=email, Birthdate=birthdate, Age=age,
        DOE_Certificate_Expiry=doe_expiry, Terms_and_Conditions=agree,
        Training_Type=training_type, Schedule=batch_id)
    if agree and agree != "yes":
        errors.append("You must agree to the Terms & Conditions.")

    photo_id    = save_file("photo_id")
    expired_doe = save_file("expired_doe")
    valid_id    = save_file("valid_id")
    selfie_with_id = f.get("selfie_with_id", "").strip()
    # Client-supplied filename: only honour it if this session uploaded it.
    selfie_with_id = selfie_with_id if owns_upload(selfie_with_id, "selfie_with_id") else None
    if not photo_id:    errors.append("Please upload your recent 2x2 Photo ID.")
    if not expired_doe: errors.append("Please upload your expired DOE Certificate.")
    if not valid_id:    errors.append("Please upload your valid PRC ID or government-issued ID.")

    if errors:
        return render_template("training/renewalCEA.html", schedules=get_schedules(),
                               errors=errors, form_data=f,
                               uploaded={"photo_id": photo_id, "expired_doe": expired_doe, "valid_id": valid_id})

    entry = dict(id=str(uuid.uuid4())[:8].upper(), form_type="cea_renewal",
        form_label="CEA Renewal", submitted_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        title=title, full_name=full_name, middle_name=middle_name,
        company_name=company_name, designation=designation,
        company_address=company_address, contact_number=contact_number, email=email,
        birthdate=birthdate, age=age, doe_expiry=doe_expiry,
        training_type=training_type, batch_id=batch_id,
        photo_id=photo_id, expired_doe=expired_doe, valid_id=valid_id, selfie_with_id=selfie_with_id)
    reg_id, invite_error = save_registration(entry, _invite_token())
    if invite_error:
        return render_template("auth/token_invalid.html",
                               reason=invite_error), 400
    return render_template("shared/success.html", entry=entry)


# ── CEM Renewal ──────────────────────────────────────────────────────────────
@registration_bp.route("/renewalCEM")
def renewal_cem():
    return render_template("training/renewalCEM.html", schedules=get_schedules(),
                           errors=[], form_data=None, uploaded={})


@registration_bp.route("/renewal-cem/submit", methods=["POST"])
def renewal_cem_submit():
    f            = request.form
    title        = f.get("title", "").strip()
    full_name    = f.get("full_name", "").strip()
    middle_name  = f.get("middle_name", "").strip()
    company_name = f.get("company_name", "").strip()
    designation  = f.get("designation", "").strip()
    company_address = f.get("company_address", "").strip()
    contact_number  = f.get("contact_number", "").strip()
    email        = f.get("email", "").strip()
    birthdate    = f.get("birthdate", "").strip()
    age          = f.get("age", "").strip()
    doe_expiry   = f.get("doe_expiry", "").strip()
    agree        = f.get("agree", "").strip()
    training_type = f.get("training_type", "").strip()
    batch_id     = f.get("batch_id", "").strip()

    errors = check_required(Title=title, Full_Name=full_name, Middle_Name=middle_name,
        Company_Name=company_name, Designation=designation, Company_Address=company_address,
        Contact_Number=contact_number, Email=email, Birthdate=birthdate, Age=age,
        DOE_Certificate_Expiry=doe_expiry, Terms_and_Conditions=agree,
        Training_Type=training_type, Schedule=batch_id)
    if agree and agree != "yes":
        errors.append("You must agree to the Terms & Conditions.")

    photo_id    = save_file("photo_id")
    expired_doe = save_file("expired_doe")
    valid_id    = save_file("valid_id")
    selfie_with_id = f.get("selfie_with_id", "").strip()
    # Client-supplied filename: only honour it if this session uploaded it.
    selfie_with_id = selfie_with_id if owns_upload(selfie_with_id, "selfie_with_id") else None
    if not photo_id:    errors.append("Please upload your recent 2x2 Photo ID.")
    if not expired_doe: errors.append("Please upload your expired DOE-CEM Certificate.")
    if not valid_id:    errors.append("Please upload your valid PRC ID or government-issued ID.")

    if errors:
        return render_template("training/renewalCEM.html", schedules=get_schedules(),
                               errors=errors, form_data=f,
                               uploaded={"photo_id": photo_id, "expired_doe": expired_doe, "valid_id": valid_id})

    entry = dict(id=str(uuid.uuid4())[:8].upper(), form_type="cem_renewal",
        form_label="CEM Renewal", submitted_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        title=title, full_name=full_name, middle_name=middle_name,
        company_name=company_name, designation=designation,
        company_address=company_address, contact_number=contact_number, email=email,
        birthdate=birthdate, age=age, doe_expiry=doe_expiry,
        training_type=training_type, batch_id=batch_id,
        photo_id=photo_id, expired_doe=expired_doe, valid_id=valid_id, selfie_with_id=selfie_with_id)
    reg_id, invite_error = save_registration(entry, _invite_token())
    if invite_error:
        return render_template("auth/token_invalid.html",
                               reason=invite_error), 400
    return render_template("shared/success.html", entry=entry)


# ── CEA Training ─────────────────────────────────────────────────────────────
@registration_bp.route("/cea-training")
def cea_training():
    return render_template("training/cea_training.html", schedules=get_schedules(),
                           errors=[], form_data=None, uploaded={})


@registration_bp.route("/cea-training/submit", methods=["POST"])
def cea_training_submit():
    f             = request.form
    title         = f.get("title", "").strip()
    full_name     = f.get("full_name", "").strip()
    middle_name   = f.get("middle_name", "").strip()
    residence     = f.get("residence", "").strip()
    company_name  = f.get("company_name", "").strip()
    designation   = f.get("designation", "").strip()
    company_address = f.get("company_address", "").strip()
    contact_number  = f.get("contact_number", "").strip()
    email         = f.get("email", "").strip()
    birthdate     = f.get("birthdate", "").strip()
    age           = f.get("age", "").strip()
    agree         = f.get("agree", "").strip()
    training_type = f.get("training_type", "").strip()
    batch_id      = f.get("batch_id", "").strip()

    errors = check_required(Title=title, Full_Name=full_name, Middle_Name=middle_name,
        Residence_Address=residence, Company_Name=company_name, Designation=designation,
        Company_Address=company_address, Contact_Number=contact_number, Email=email,
        Birthdate=birthdate, Age=age, Terms_and_Conditions=agree,
        Training_Type=training_type, Schedule=batch_id)
    if agree and agree != "yes":
        errors.append("You must agree to the Terms & Conditions.")

    photo_id = save_file("photo_id")
    resume   = save_file("resume")
    valid_id = save_file("valid_id")
    selfie_with_id = f.get("selfie_with_id", "").strip()
    # Client-supplied filename: only honour it if this session uploaded it.
    selfie_with_id = selfie_with_id if owns_upload(selfie_with_id, "selfie_with_id") else None
    if not photo_id: errors.append("Please upload your recent 2x2 Photo ID.")
    if not resume:   errors.append("Please upload your Resume or CV.")
    if not valid_id: errors.append("Please upload your valid PRC ID or government-issued ID.")

    if errors:
        return render_template("training/cea_training.html", schedules=get_schedules(),
                               errors=errors, form_data=f,
                               uploaded={"photo_id": photo_id, "resume": resume, "valid_id": valid_id})

    entry = dict(id=str(uuid.uuid4())[:8].upper(), form_type="cea_training",
        form_label="CEA Training", submitted_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        title=title, full_name=full_name, middle_name=middle_name,
        residence=residence, company_name=company_name, designation=designation,
        company_address=company_address, contact_number=contact_number, email=email,
        birthdate=birthdate, age=age, training_type=training_type, batch_id=batch_id,
        photo_id=photo_id, resume=resume, valid_id=valid_id, selfie_with_id=selfie_with_id)
    reg_id, invite_error = save_registration(entry, _invite_token())
    if invite_error:
        return render_template("auth/token_invalid.html",
                               reason=invite_error), 400
    return render_template("shared/success.html", entry=entry)


# ── CEM Training ─────────────────────────────────────────────────────────────
@registration_bp.route("/training")
def training():
    return render_template("training/training.html", schedules=get_schedules(),
                           errors=[], form_data=None, uploaded={})


@registration_bp.route("/gemp-lgu")
def gemp_lgu():
    return render_template("training/gemp_lgu.html", schedules=get_schedules(),
                           errors=[], form_data=None, uploaded={})


@registration_bp.route("/gemp-lgu/submit", methods=["POST"])
def gemp_lgu_submit():
    f               = request.form
    title           = f.get("title", "").strip()
    full_name       = f.get("full_name", "").strip()
    residence       = f.get("residence", "").strip()
    company_name    = f.get("company_name", "").strip()
    designation     = f.get("designation", "").strip()
    company_address = f.get("company_address", "").strip()
    contact_number  = f.get("contact_number", "").strip()
    email           = f.get("email", "").strip()
    birthdate       = f.get("birthdate", "").strip()
    age             = f.get("age", "").strip()
    gemp_designation = f.get("gemp_designation", "").strip()
    agree           = f.get("agree", "").strip()
    training_type   = f.get("training_type", "").strip()
    batch_id        = f.get("batch_id", "").strip()

    errors = check_required(Title=title, Full_Name=full_name, Residence_Address=residence,
        Company_Name=company_name, Designation=designation, Company_Address=company_address,
        Contact_Number=contact_number, Email=email, Birthdate=birthdate, Age=age,
        GEMP_Role=gemp_designation, Terms_and_Conditions=agree,
        Training_Type=training_type, Schedule=batch_id)
    if agree and agree != "yes":
        errors.append("You must agree to the Terms & Conditions.")

    photo_id = save_file("photo_id")
    resume   = save_file("resume", pdf_only=True)
    valid_id = save_file("valid_id")
    selfie_with_id = f.get("selfie_with_id", "").strip()
    # Client-supplied filename: only honour it if this session uploaded it.
    selfie_with_id = selfie_with_id if owns_upload(selfie_with_id, "selfie_with_id") else None
    if not photo_id: errors.append("Please upload your recent 2×2 Photo ID.")
    if not resume:   errors.append("Please upload your Resume or CV (PDF only).")
    if not valid_id: errors.append("Please upload your valid PRC ID or government-issued ID.")

    if errors:
        return render_template("training/gemp_lgu.html", schedules=get_schedules(),
                               errors=errors, form_data=f,
                               uploaded={"photo_id": photo_id, "resume": resume, "valid_id": valid_id})

    entry = dict(id=str(uuid.uuid4())[:8].upper(), form_type="gemp_lgu",
        form_label="GEMP Training (LGU)", submitted_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        title=title, full_name=full_name, middle_name="", residence=residence,
        company_name=company_name, designation=designation,
        company_address=company_address, contact_number=contact_number, email=email,
        birthdate=birthdate, age=age, training_type=training_type, batch_id=batch_id,
        gemp_designation=gemp_designation,
        photo_id=photo_id, resume=resume, valid_id=valid_id, selfie_with_id=selfie_with_id)
    reg_id, invite_error = save_registration(entry, _invite_token())
    if invite_error:
        return render_template("auth/token_invalid.html",
                               reason=invite_error), 400
    return render_template("shared/success.html", entry=entry)


@registration_bp.route("/gemp-oge")
def gemp_oge():
    return render_template("training/gemp_oge.html", schedules=get_schedules(),
                           errors=[], form_data=None, uploaded={})


@registration_bp.route("/gemp-oge/submit", methods=["POST"])
def gemp_oge_submit():
    f               = request.form
    title           = f.get("title", "").strip()
    full_name       = f.get("full_name", "").strip()
    residence       = f.get("residence", "").strip()
    company_name    = f.get("company_name", "").strip()
    designation     = f.get("designation", "").strip()
    company_address = f.get("company_address", "").strip()
    contact_number  = f.get("contact_number", "").strip()
    email           = f.get("email", "").strip()
    birthdate       = f.get("birthdate", "").strip()
    age             = f.get("age", "").strip()
    gemp_designation = f.get("gemp_designation", "").strip()
    agree           = f.get("agree", "").strip()
    training_type   = f.get("training_type", "").strip()
    batch_id        = f.get("batch_id", "").strip()

    errors = check_required(Title=title, Full_Name=full_name, Residence_Address=residence,
        Company_Name=company_name, Designation=designation, Company_Address=company_address,
        Contact_Number=contact_number, Email=email, Birthdate=birthdate, Age=age,
        GEMP_Role=gemp_designation, Terms_and_Conditions=agree,
        Training_Type=training_type, Schedule=batch_id)
    if agree and agree != "yes":
        errors.append("You must agree to the Terms & Conditions.")

    photo_id = save_file("photo_id")
    resume   = save_file("resume", pdf_only=True)
    valid_id = save_file("valid_id")
    selfie_with_id = f.get("selfie_with_id", "").strip()
    # Client-supplied filename: only honour it if this session uploaded it.
    selfie_with_id = selfie_with_id if owns_upload(selfie_with_id, "selfie_with_id") else None
    if not photo_id: errors.append("Please upload your recent 2×2 Photo ID.")
    if not resume:   errors.append("Please upload your Resume or CV (PDF only).")
    if not valid_id: errors.append("Please upload your valid PRC ID or government-issued ID.")

    if errors:
        return render_template("training/gemp_oge.html", schedules=get_schedules(),
                               errors=errors, form_data=f,
                               uploaded={"photo_id": photo_id, "resume": resume, "valid_id": valid_id})

    entry = dict(id=str(uuid.uuid4())[:8].upper(), form_type="gemp_oge",
        form_label="GEMP Training (Gov't Entity)", submitted_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        title=title, full_name=full_name, middle_name="", residence=residence,
        company_name=company_name, designation=designation,
        company_address=company_address, contact_number=contact_number, email=email,
        birthdate=birthdate, age=age, training_type=training_type, batch_id=batch_id,
        gemp_designation=gemp_designation,
        photo_id=photo_id, resume=resume, valid_id=valid_id, selfie_with_id=selfie_with_id)
    reg_id, invite_error = save_registration(entry, _invite_token())
    if invite_error:
        return render_template("auth/token_invalid.html",
                               reason=invite_error), 400
    return render_template("shared/success.html", entry=entry)


@registration_bp.route("/training/submit", methods=["POST"])
def training_submit():
    f             = request.form
    title         = f.get("title", "").strip()
    full_name     = f.get("full_name", "").strip()
    middle_name   = f.get("middle_name", "").strip()
    residence     = f.get("residence", "").strip()
    company_name  = f.get("company_name", "").strip()
    designation   = f.get("designation", "").strip()
    company_address = f.get("company_address", "").strip()
    contact_number  = f.get("contact_number", "").strip()
    email         = f.get("email", "").strip()
    birthdate     = f.get("birthdate", "").strip()
    age           = f.get("age", "").strip()
    agree         = f.get("agree", "").strip()
    training_type = f.get("training_type", "").strip()
    batch_id      = f.get("batch_id", "").strip()

    errors = check_required(Title=title, Full_Name=full_name, Middle_Name=middle_name,
        Residence_Address=residence, Company_Name=company_name, Designation=designation,
        Company_Address=company_address, Contact_Number=contact_number, Email=email,
        Birthdate=birthdate, Age=age, Terms_and_Conditions=agree,
        Training_Type=training_type, Schedule=batch_id)
    if agree and agree != "yes":
        errors.append("You must agree to the Terms & Conditions.")

    photo_id = save_file("photo_id")
    resume   = save_file("resume", pdf_only=True)
    valid_id = save_file("valid_id")
    selfie_with_id = f.get("selfie_with_id", "").strip()
    # Client-supplied filename: only honour it if this session uploaded it.
    selfie_with_id = selfie_with_id if owns_upload(selfie_with_id, "selfie_with_id") else None
    if not photo_id: errors.append("Please upload your recent 2x2 Photo ID.")
    if not resume:   errors.append("Please upload your Resume or CV (PDF only).")
    if not valid_id: errors.append("Please upload your PRC License or valid government-issued ID.")

    if errors:
        return render_template("training/training.html", schedules=get_schedules(),
                               errors=errors, form_data=f,
                               uploaded={"photo_id": photo_id, "resume": resume, "valid_id": valid_id})

    entry = dict(id=str(uuid.uuid4())[:8].upper(), form_type="training",
        form_label="Training Registration", submitted_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        title=title, full_name=full_name, middle_name=middle_name,
        residence=residence, company_name=company_name, designation=designation,
        company_address=company_address, contact_number=contact_number, email=email,
        birthdate=birthdate, age=age, training_type=training_type, batch_id=batch_id,
        photo_id=photo_id, resume=resume, valid_id=valid_id, selfie_with_id=selfie_with_id)
    reg_id, invite_error = save_registration(entry, _invite_token())
    if invite_error:
        return render_template("auth/token_invalid.html",
                               reason=invite_error), 400
    return render_template("shared/success.html", entry=entry)

