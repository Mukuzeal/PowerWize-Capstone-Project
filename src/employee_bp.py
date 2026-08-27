from flask import Blueprint, render_template, redirect, session
from db import get_db, get_batches_full, get_users, get_registrations, get_solar_requests
from datetime import date, timedelta

employee_bp = Blueprint("employee", __name__)

# Import LMS functions
from db import (lms_get_modules, lms_get_archived_modules, lms_get_all_submissions,
                lms_get_progress, lms_get_modules_for_trainee,
                lms_get_module_requirements, get_user_training_type)
from lms_bp._shared import _progress_steps


def _trainee_progress(trainees):
    """One progress row per trainee: how far through their own syllabus they are.

    Folds each trainee's modules through _progress_steps — the same helper
    /lms/progress uses — so a trainer's percentage can never disagree with the
    one the trainee is looking at.

    A trainee's syllabus is decided by their training type, not by who they
    are, so the module list and its quiz/exam requirements are looked up once
    per type rather than once per person.
    """
    by_type = {}
    rows = []
    for t in trainees:
        ttype = get_user_training_type(t["id"])
        if ttype not in by_type:
            mods = lms_get_modules_for_trainee(t["id"], published_only=True)
            by_type[ttype] = (mods, lms_get_module_requirements([m["id"] for m in mods]))
        mods, reqs = by_type[ttype]

        prog_map = {p["module_id"]: p for p in lms_get_progress(t["id"])}
        total     = len(mods)
        completed = sum(1 for m in mods if prog_map.get(m["id"], {}).get("completed"))
        # The next thing this trainee owes, taken from the first module that is
        # not finished. Nothing outstanding means the syllabus is done.
        nxt = None
        for m in mods:
            steps = _progress_steps(prog_map.get(m["id"]), reqs.get(m["id"]))
            pending = next((s for s in steps["steps"] if not s["done"]), None)
            if pending:
                nxt = {"module": m["title"], "label": pending["label"]}
                break

        rows.append({
            "trainee_id":   t["id"],
            "trainee_name": f"{t['fname']} {t['lname']}".strip(),
            "email":        t["email"],
            "training_type": ttype,
            "completed":    completed,
            "total":        total,
            "pct":          round(completed / total * 100) if total else 0,
            "next":         nxt,
        })

    rows.sort(key=lambda r: (-r["pct"], r["trainee_name"].lower()))
    return rows

@employee_bp.route("/employee")
def employee():
    from flask import session
    if session.get("user_role") != "employee":
        return redirect("/auth")

    # Get all users (trainees and other employees)
    users = get_users()

    # Count trainees (employees manage trainees)
    trainees = [u for u in users if u["role"] == "trainee" and u["archived_at"] is None]
    trainee_count = len(trainees)

    # Get batches/schedules
    all_batches = get_batches_full()
    today = date.today()
    end_offsets = {"training": 9, "renewal": 1}
    upcoming, past = [], []
    for b in all_batches:
        b["end_date"] = b["start_date"] + timedelta(days=end_offsets.get(b["type"], 0))
        (past if b["end_date"] < today else upcoming).append(b)

    # Get LMS data
    emp_id = session.get("user_id")
    modules = lms_get_modules(instructor_id=emp_id)
    archived_modules = lms_get_archived_modules(instructor_id=emp_id)
    submissions = lms_get_all_submissions(instructor_id=emp_id)
    # An employee has no progress of their own — they are the instructor. What
    # this section reports is their trainees' progress.
    progress_list = _trainee_progress(trainees)
    prog_map = {}

    return render_template("admin/employee.html",
                           registrations=get_registrations(),
                           schedules=upcoming,
                           past_schedules=past,
                           users=users,
                           trainee_count=trainee_count,
                           solar_requests=get_solar_requests(),
                           modules=modules,
                           archived_modules=archived_modules,
                           submissions=submissions,
                           progress_list=progress_list,
                           prog_map=prog_map)

