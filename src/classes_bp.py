"""Training classes: the trainee self-join path and the cohort progress view.

The join code only names a class. Entitlement is decided by
db/classes.py::membership_authority(), which re-reads the roster, the
registration outcome and the payment status on every call — read the comment
block at the top of that module before changing anything here.
"""
from flask import (Blueprint, request, jsonify, session,
                   redirect, url_for, flash, abort)

from db import (audit_log, get_class, class_members, classes_for_user,
                join_class, lms_get_modules_for_trainee,
                lms_get_module_requirements, lms_get_progress, instructor_can_view_class)
from lms_bp._shared import _progress_steps
from permissions import current_can

classes_bp = Blueprint("classes", __name__)


def _require_trainee():
    if session.get("user_role") != "trainee":
        abort(403)
    return session["user_id"]


# ── Trainee: join and see your classes ───────────────────────────────────────

@classes_bp.route("/portal/join-class", methods=["POST"])
def portal_join_class():
    """Self-join by code.

    Every refusal names the fact that failed, because the person can usually
    act on it — pay, wait for review, or ask their coordinator. A generic
    "invalid code" would send all three to the wrong place.
    """
    uid = _require_trainee()
    code = (request.form.get("join_code") or "").strip()
    cls, err = join_class(uid, code)
    if err:
        flash(err, "error")
        return redirect(url_for("registration.portal"))
    audit_log(uid, "class_joined", "training_class", cls["id"],
              f"Self-joined '{cls['name']}' with the class code.")
    flash(f"You have joined {cls['name']}.", "success")
    return redirect(url_for("registration.portal"))


@classes_bp.route("/api/my-classes")
def api_my_classes():
    uid = _require_trainee()
    return jsonify(classes=[
        {"id": c["id"], "name": c["name"], "training_type": c["training_type"],
         "company": c["company_name"],
         "joined_at": c["joined_at"].isoformat() if c["joined_at"] else None}
        for c in classes_for_user(uid)])


# ── Trainer / staff: the cohort view ─────────────────────────────────────────

def _class_progress(class_id):
    """Per-member progress plus the cohort roll-up.

    Built from the same helpers as the trainer console (`_progress_steps`,
    `lms_get_modules_for_trainee`), so a class's numbers cannot disagree with
    the same trainee's numbers elsewhere.
    """
    members = class_members(class_id)
    rows = []
    for m in members:
        # Resolved per member, deliberately NOT cached by training type.
        # lms_get_modules_for_trainee() is a function of the USER: two people
        # with the same raw training_type can owe different modules, because
        # the syllabus also depends on their own certificate dates. Caching on
        # the type handed the first member's module list to everyone who
        # happened to share their label, so totals were silently wrong.
        mods = lms_get_modules_for_trainee(m["user_id"], published_only=True)
        reqs = lms_get_module_requirements([x["id"] for x in mods])
        prog_map = {p["module_id"]: p for p in lms_get_progress(m["user_id"])}
        total = len(mods)
        completed = sum(1 for x in mods
                        if prog_map.get(x["id"], {}).get("completed"))
        nxt = None
        for x in mods:
            steps = _progress_steps(prog_map.get(x["id"]), reqs.get(x["id"]))
            pending = next((s for s in steps["steps"] if not s["done"]), None)
            if pending:
                nxt = {"module": x["title"], "label": pending["label"]}
                break
        rows.append({
            "user_id": m["user_id"],
            "name": f"{m['fname']} {m['lname']}".strip(),
            "email": m["email"],
            "training_type": m.get("training_type") or "",
            "authorised": m["authorised"],
            "joined_at": m["joined_at"].isoformat() if m["joined_at"] else None,
            "completed": completed, "total": total,
            "pct": round(completed / total * 100) if total else 0,
            "next": nxt,
        })
    rows.sort(key=lambda r: (-r["pct"], r["name"].lower()))

    # The batch figure is the share of module-completions across the whole
    # cohort, NOT the average of percentages: averaging percentages lets one
    # member with a two-module syllabus outweigh ten with twelve each.
    done = sum(r["completed"] for r in rows)
    owed = sum(r["total"] for r in rows)
    return {
        "members": rows,
        "batch": {
            "members": len(rows),
            "modules_completed": done,
            "modules_total": owed,
            "pct": round(done / owed * 100) if owed else 0,
            "finished": sum(1 for r in rows if r["total"] and
                            r["completed"] == r["total"]),
        },
    }


@classes_bp.route("/api/class/<int:class_id>/progress")
def api_class_progress(class_id):
    """Cohort progress. Trainers and staff only — a trainee must not read a
    whole class's performance, only their own."""
    if not current_can("manage_modules") and not current_can("corporate_payments"):
        abort(403)
    cls = get_class(class_id=class_id)
    if not cls:
        return jsonify(error="No such class."), 404
    if not current_can('corporate_payments') and not instructor_can_view_class(class_id,session.get('user_id')):
        abort(403)
    d = _class_progress(class_id)
    d["class"] = {"id": cls["id"], "name": cls["name"],
                  "training_type": cls["training_type"],
                  "join_code": cls["join_code"], "join_open": cls["join_open"]}
    return jsonify(d)
