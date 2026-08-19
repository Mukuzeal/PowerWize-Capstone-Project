from datetime import date, timedelta

from flask import render_template, redirect, session

from db import get_users, get_batches_full, get_registrations, get_solar_requests, lms_get_modules_with_counts, get_pending_selfies

from . import admin_bp


@admin_bp.route("/admin")
def admin():
    if session.get("user_role") != "admin":
        return redirect("/auth")
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
    end_offsets = {"training": 9, "renewal": 1}
    upcoming, past = [], []
    for b in all_batches:
        b["end_date"] = b["start_date"] + timedelta(days=end_offsets.get(b["type"], 0))
        (past if b["end_date"] < today else upcoming).append(b)

    # Get LMS modules (active only)
    modules = lms_get_modules_with_counts(archived=False)

    # Get archived modules
    archived_modules = lms_get_modules_with_counts(archived=True)

    return render_template("admin/admin.html",
                           registrations=get_registrations(),
                           pending_selfies=get_pending_selfies(),
                           schedules=upcoming,
                           past_schedules=past,
                           users=users,
                           uc=uc,
                           solar_requests=get_solar_requests(),
                           modules=modules,
                           archived_modules=archived_modules)
