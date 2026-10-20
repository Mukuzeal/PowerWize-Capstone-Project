"""Discount code management — Admin, Super User and Secretary.

Codes apply to individual trainee payments on /payment only. A corporate
invoice already carries a staff-set custom total, so letting a code stack on
top of it would discount the same fee twice.
"""
from datetime import datetime

from flask import request, redirect, session, flash, jsonify

from db import (audit_log, create_discount_code, update_discount_code,
                set_discount_active, delete_discount_code, get_discount_codes,
                get_discount_code)
from permissions import require

from . import admin_bp

# Programs a code can be scoped to. Same codes lms_bp uses for a syllabus, so a
# code scoped to "cea_training" matches exactly the trainees on that program.
PROGRAMS = [
    ("",             "All programs"),
    ("training",     "CEM Training"),
    ("cea_training", "CEA Training"),
    ("cem_renewal",  "CEM Renewal"),
    ("cea_renewal",  "CEA Renewal"),
    ("gemp_lgu",     "GEMP (LGU)"),
    ("gemp_oge",     "GEMP (Gov't Entity)"),
]


def _parse(form):
    """(values, errors) from the create/edit form."""
    code    = form.get("code", "").strip()
    percent = form.get("percent_off", "").strip()
    expires = form.get("expires_on", "").strip()
    max_use = form.get("max_uses", "").strip()
    program = form.get("training_type", "").strip()

    errors = []
    if not code:
        errors.append("Code is required.")
    elif len(code) > 40:
        errors.append("Code must be 40 characters or fewer.")
    elif not code.replace("-", "").replace("_", "").isalnum():
        errors.append("Code may only contain letters, numbers, hyphens and underscores.")

    try:
        percent = int(percent)
        if not 1 <= percent <= 100:
            errors.append("Discount percentage must be between 1 and 100.")
    except ValueError:
        errors.append("Discount percentage must be a whole number between 1 and 100.")
        percent = 0

    try:
        expires = datetime.strptime(expires, "%Y-%m-%d").date()
    except ValueError:
        errors.append("Expiration date is required (YYYY-MM-DD).")
        expires = None

    try:
        max_use = int(max_use)
        if max_use < 1:
            errors.append("Maximum redemptions must be at least 1.")
    except ValueError:
        errors.append("Maximum redemptions must be a whole number.")
        max_use = 0

    valid_programs = [p[0] for p in PROGRAMS]
    if program not in valid_programs:
        errors.append("Unknown program scope.")
        program = ""

    return {"code": code, "percent_off": percent, "expires_on": expires,
            "max_uses": max_use, "training_type": program or None}, errors


def dashboard_context():
    """What the console's Discount Codes pane renders. Shaped here, next to the
    feature, and handed to admin/dashboard.py — the screen is a pane of
    /admin, not a page of its own."""
    return {"discount_codes": get_discount_codes(), "discount_programs": PROGRAMS}


@admin_bp.route("/admin/discounts")
def discounts_list():
    """Kept so existing links still resolve; the screen is now a console pane."""
    resp = require("discount_codes")
    if resp:
        return resp
    return redirect("/admin#discounts")


@admin_bp.route("/admin/discounts/create", methods=["POST"])
def discounts_create():
    resp = require("discount_codes")
    if resp:
        return resp
    values, errors = _parse(request.form)
    if not errors:
        new_id = create_discount_code(values["code"], values["percent_off"],
                                      values["expires_on"], values["max_uses"],
                                      values["training_type"], session.get("user_id"))
        if new_id is None:
            errors.append(f"The code \"{values['code']}\" already exists "
                          f"(codes are case-insensitive).")
        else:
            audit_log(session.get("user_id"), "discount_code_created", "discount_code",
                      new_id, f"Created {values['code']} — {values['percent_off']}% off, "
                              f"max {values['max_uses']} uses, expires {values['expires_on']}")
            flash(f"Discount code {values['code']} created.", "success")
            return jsonify(ok=True, id=new_id)
    return jsonify(errors=errors), 400


@admin_bp.route("/admin/discounts/<int:code_id>/edit", methods=["POST"])
def discounts_edit(code_id):
    resp = require("discount_codes")
    if resp:
        return resp
    row = get_discount_code(code_id)
    if not row:
        flash("That discount code no longer exists.", "error")
        return redirect("/admin#discounts")
    values, errors = _parse(request.form)
    if not errors and values["max_uses"] < (row["used"] or 0):
        errors.append(f"Maximum redemptions cannot be lower than the "
                      f"{row['used']} already redeemed.")
    if not errors:
        if update_discount_code(code_id, values["code"], values["percent_off"],
                                values["expires_on"], values["max_uses"],
                                values["training_type"]):
            audit_log(session.get("user_id"), "discount_code_edited", "discount_code",
                      code_id, f"Edited {values['code']} — {values['percent_off']}% off, "
                               f"max {values['max_uses']} uses, expires {values['expires_on']}")
            flash(f"Discount code {values['code']} updated.", "success")
            return jsonify(ok=True, id=code_id)
        errors.append(f"The code \"{values['code']}\" is already used by another entry.")
    return jsonify(errors=errors), 400


@admin_bp.route("/admin/discounts/<int:code_id>/toggle", methods=["POST"])
def discounts_toggle(code_id):
    resp = require("discount_codes")
    if resp:
        return resp
    row = get_discount_code(code_id)
    if not row:
        flash("That discount code no longer exists.", "error")
        return redirect("/admin#discounts")
    activate = not row["is_active"]
    set_discount_active(code_id, activate)
    audit_log(session.get("user_id"),
              "discount_code_activated" if activate else "discount_code_deactivated",
              "discount_code", code_id,
              f"{'Activated' if activate else 'Deactivated'} {row['code']}")
    flash(f"{row['code']} {'activated' if activate else 'deactivated'}.",
          "success" if activate else "warning")
    return redirect("/admin#discounts")


@admin_bp.route("/admin/discounts/<int:code_id>/delete", methods=["POST"])
def discounts_delete(code_id):
    resp = require("discount_codes")
    if resp:
        return resp
    row = get_discount_code(code_id)
    if not row:
        flash("That discount code no longer exists.", "error")
        return redirect("/admin#discounts")
    delete_discount_code(code_id)
    audit_log(session.get("user_id"), "discount_code_deleted", "discount_code",
              code_id, f"Deleted {row['code']} (had {row['used']} redemption(s))")
    flash(f"Discount code {row['code']} deleted.", "error")
    return redirect("/admin#discounts")
