import re
import uuid
from datetime import datetime
from flask import Blueprint, request, render_template, session, redirect
from db import get_schedules, insert_registration, get_db, get_registration_by_email
from utils import save_file, check_required

registration_bp = Blueprint("registration", __name__)


def _file_prefix(form):
    full_name = form.get("full_name", "").strip()
    parts = full_name.split()
    fname = re.sub(r"[^\w]", "", parts[0])  if parts           else "unknown"
    lname = re.sub(r"[^\w]", "", parts[-1]) if len(parts) > 1  else "unknown"
    uid  = session.get("user_id",   "0")
    role = session.get("user_role", "trainee")
    return f"{uid}_{role}_{fname}_{lname}"


@registration_bp.route("/")
def index():
    if "user_id" in session:
        if session.get("user_role") == "admin":
            return redirect("/admin")
        return redirect("/portal")
    return render_template("home.html")


@registration_bp.route("/home")
def home():
    return render_template("home.html")


@registration_bp.route("/programs")
def programs():
    return render_template("programs.html")


@registration_bp.route("/portal")
def portal():
    if "user_id" not in session:
        return redirect("/auth")
    if session.get("user_role") == "admin":
        return redirect("/admin")

    # Fetch user info and their registration
    conn = get_db()
    cur  = conn.cursor(dictionary=True)
    cur.execute(
        "SELECT fname, lname, email, payment_status FROM users WHERE id=%s",
        (session["user_id"],)
    )
    user = cur.fetchone()
    cur.close(); conn.close()

    if not user:
        return redirect("/auth/logout")

    if user["payment_status"] == "unpaid":
        return redirect("/payment")

    reg = get_registration_by_email(user["email"])
    return render_template("portal.html", user=user, reg=reg)


# ── CEA Renewal ──────────────────────────────────────────────────────────────
@registration_bp.route("/renewalCEA")
def renewal():
    return render_template("renewalCEA.html", schedules=get_schedules(),
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

    prefix      = _file_prefix(f)
    photo_id    = save_file("photo_id",    prefix=prefix)
    expired_doe = save_file("expired_doe", prefix=prefix)
    valid_id    = save_file("valid_id",    prefix=prefix)
    if not photo_id:    errors.append("Please upload your recent 2x2 Photo ID.")
    if not expired_doe: errors.append("Please upload your expired DOE Certificate.")
    if not valid_id:    errors.append("Please upload your valid PRC ID or government-issued ID.")

    if errors:
        return render_template("renewalCEA.html", schedules=get_schedules(),
                               errors=errors, form_data=f,
                               uploaded={"photo_id": photo_id, "expired_doe": expired_doe, "valid_id": valid_id})

    entry = dict(id=str(uuid.uuid4())[:8].upper(), form_type="cea_renewal",
        form_label="CEA Renewal", submitted_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        title=title, full_name=full_name, middle_name=middle_name,
        company_name=company_name, designation=designation,
        company_address=company_address, contact_number=contact_number, email=email,
        birthdate=birthdate, age=age, doe_expiry=doe_expiry,
        training_type=training_type, batch_id=batch_id,
        photo_id=photo_id, expired_doe=expired_doe, valid_id=valid_id)
    insert_registration(entry)
    return render_template("success.html", entry=entry)


# ── CEM Renewal ──────────────────────────────────────────────────────────────
@registration_bp.route("/renewalCEM")
def renewal_cem():
    return render_template("renewalCEM.html", schedules=get_schedules(),
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

    prefix      = _file_prefix(f)
    photo_id    = save_file("photo_id",    prefix=prefix)
    expired_doe = save_file("expired_doe", prefix=prefix)
    valid_id    = save_file("valid_id",    prefix=prefix)
    if not photo_id:    errors.append("Please upload your recent 2x2 Photo ID.")
    if not expired_doe: errors.append("Please upload your expired DOE-CEM Certificate.")
    if not valid_id:    errors.append("Please upload your valid PRC ID or government-issued ID.")

    if errors:
        return render_template("renewalCEM.html", schedules=get_schedules(),
                               errors=errors, form_data=f,
                               uploaded={"photo_id": photo_id, "expired_doe": expired_doe, "valid_id": valid_id})

    entry = dict(id=str(uuid.uuid4())[:8].upper(), form_type="cem_renewal",
        form_label="CEM Renewal", submitted_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        title=title, full_name=full_name, middle_name=middle_name,
        company_name=company_name, designation=designation,
        company_address=company_address, contact_number=contact_number, email=email,
        birthdate=birthdate, age=age, doe_expiry=doe_expiry,
        training_type=training_type, batch_id=batch_id,
        photo_id=photo_id, expired_doe=expired_doe, valid_id=valid_id)
    insert_registration(entry)
    return render_template("success.html", entry=entry)


# ── CEA Training ─────────────────────────────────────────────────────────────
@registration_bp.route("/cea-training")
def cea_training():
    return render_template("cea_training.html", schedules=get_schedules(),
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

    prefix   = _file_prefix(f)
    photo_id = save_file("photo_id", prefix=prefix)
    resume   = save_file("resume",   prefix=prefix)
    valid_id = save_file("valid_id", prefix=prefix)
    if not photo_id: errors.append("Please upload your recent 2x2 Photo ID.")
    if not resume:   errors.append("Please upload your Resume or CV.")
    if not valid_id: errors.append("Please upload your valid PRC ID or government-issued ID.")

    if errors:
        return render_template("cea_training.html", schedules=get_schedules(),
                               errors=errors, form_data=f,
                               uploaded={"photo_id": photo_id, "resume": resume, "valid_id": valid_id})

    entry = dict(id=str(uuid.uuid4())[:8].upper(), form_type="cea_training",
        form_label="CEA Training", submitted_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        title=title, full_name=full_name, middle_name=middle_name,
        residence=residence, company_name=company_name, designation=designation,
        company_address=company_address, contact_number=contact_number, email=email,
        birthdate=birthdate, age=age, training_type=training_type, batch_id=batch_id,
        photo_id=photo_id, resume=resume, valid_id=valid_id)
    insert_registration(entry)
    return render_template("success.html", entry=entry)


# ── CEM Training ─────────────────────────────────────────────────────────────
@registration_bp.route("/training")
def training():
    return render_template("training.html", schedules=get_schedules(),
                           errors=[], form_data=None, uploaded={})


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

    prefix   = _file_prefix(f)
    photo_id = save_file("photo_id", prefix=prefix)
    resume   = save_file("resume",   prefix=prefix, pdf_only=True)
    valid_id = save_file("valid_id", prefix=prefix)
    if not photo_id: errors.append("Please upload your recent 2x2 Photo ID.")
    if not resume:   errors.append("Please upload your Resume or CV (PDF only).")
    if not valid_id: errors.append("Please upload your PRC License or valid government-issued ID.")

    if errors:
        return render_template("training.html", schedules=get_schedules(),
                               errors=errors, form_data=f,
                               uploaded={"photo_id": photo_id, "resume": resume, "valid_id": valid_id})

    entry = dict(id=str(uuid.uuid4())[:8].upper(), form_type="training",
        form_label="Training Registration", submitted_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        title=title, full_name=full_name, middle_name=middle_name,
        residence=residence, company_name=company_name, designation=designation,
        company_address=company_address, contact_number=contact_number, email=email,
        birthdate=birthdate, age=age, training_type=training_type, batch_id=batch_id,
        photo_id=photo_id, resume=resume, valid_id=valid_id)
    insert_registration(entry)
    return render_template("success.html", entry=entry)
