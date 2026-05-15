from flask import Blueprint, render_template, redirect, session
from db import get_db, get_batches_full, get_users, get_registrations, get_solar_requests
from datetime import date, timedelta

employee_bp = Blueprint("employee", __name__)

# Import LMS functions
from db import lms_get_modules, lms_get_archived_modules, lms_get_all_submissions, lms_get_progress

@employee_bp.route("/employee")
def employee():
    from flask import session
    if session.get("user_role") != "employee":
        return redirect("/auth")

    # Get all users (trainees and other employees)
    users = get_users()

    # Count trainees (employees manage trainees)
    trainee_count = sum(1 for u in users if u["role"] == "trainee" and u["archived_at"] is None)

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
    # Employees are instructors, not trainees, so they don't have progress in their own modules
    progress_list = []
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

