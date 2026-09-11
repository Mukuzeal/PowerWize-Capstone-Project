from datetime import date

from flask import render_template

from db import (get_users, get_batches_full, get_registrations, get_solar_requests,
                lms_get_modules_with_counts, lms_get_trainee_progress_overview, get_pending_selfies)

from . import admin_bp, require_admin


@admin_bp.route("/admin")
def admin():
    resp = require_admin()
    if resp:
        return resp
    users = get_users()
    uc = {
        "admin":          sum(1 for u in users if u["role"] == "admin"),
        "employee":       sum(1 for u in users if u["role"] == "employee"),
        "trainee":        sum(1 for u in users if u["role"] == "trainee"),
        "archived":       sum(1 for u in users if u["archived_at"] is not None),
        "active":         sum(1 for u in users if u["archived_at"] is None),
        "active_trainee": sum(1 for u in users if u["role"] == "trainee" and u["archived_at"] is None),
    }
    all_batches = get_batches_full()
    today = date.today()
    upcoming, past = [], []
    for b in all_batches:
        b["end_date"] = b["dates"][-1]
        (past if b["end_date"] < today else upcoming).append(b)

    # Get LMS modules (active only)
    modules = lms_get_modules_with_counts(archived=False)

    # Get archived modules
    archived_modules = lms_get_modules_with_counts(archived=True)

    trainee_progress = lms_get_trainee_progress_overview()

    return render_template("admin/admin.html",
                           registrations=get_registrations(),
                           pending_selfies=get_pending_selfies(),
                           schedules=upcoming,
                           past_schedules=past,
                           users=users,
                           uc=uc,
                           solar_requests=get_solar_requests(),
                           modules=modules,
                           archived_modules=archived_modules,
                           trainee_progress=trainee_progress)
