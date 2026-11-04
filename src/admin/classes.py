"""Admin: create and manage training classes.

Creating a class from an intake is the normal path — the class then draws its
membership from that company's roster. A class with no roster behind it can be
created, but nobody can self-join it (see membership_authority()); staff add
members to it one by one.
"""
from flask import request, jsonify, session

from db import (audit_log, get_intake, get_corporate_payment, get_class,
                list_classes, class_members, create_class, rotate_join_code,
                set_join_open, add_member_as_staff, remove_member,
                membership_authority, class_roster_candidates,
                intake_invoices, class_instructors, assign_class_instructor)
from permissions import require

from . import admin_bp


@admin_bp.route("/admin/intake/<int:intake_id>/class", methods=["POST"])
def intake_create_class(intake_id):
    """Create a class for one company intake.

    The program comes from the intake, not from the browser: a class whose
    training_type disagreed with what the roster was approved and billed for
    would refuse every member at join time.
    """
    resp = require("corporate_payments")
    if resp:
        return resp
    intake = get_intake(intake_id=intake_id)
    if not intake:
        return jsonify(error="No such intake."), 404

    name = (request.form.get("name") or "").strip()
    if not name:
        name = f"{intake['company_name']} — {intake.get('training_type') or intake['form_type']}"

    # The invoice is the roster authority whenever one exists: it is what was
    # actually billed and paid. The caller may name one explicitly, but if it
    # does not, the intake's own invoice is looked up here rather than left
    # out — the browser omitting the id was silently downgrading every class
    # to intake authority, bypassing the invoice check entirely.
    cid = request.form.get("corporate_payment_id") or None
    if cid:
        inv = get_corporate_payment(cid=int(cid))
        if not inv or inv.get("intake_id") != intake_id:
            return jsonify(error="That invoice does not belong to this intake."), 400
        cid = inv["id"]
    else:
        for inv in intake_invoices(intake_id):
            # Prefer a settled one; fall back to the newest otherwise, so the
            # class still tracks the invoice it will be paid through.
            if inv["status"] == "paid":
                cid = inv["id"]
                break
            if cid is None:
                cid = inv["id"]

    cls, err = create_class(name, intake.get("training_type") or intake["form_type"],
                            session.get("user_id"), intake_id=intake_id,
                            corporate_payment_id=cid,
                            form_type=intake["form_type"])
    if err:
        return jsonify(error=err), 400
    audit_log(session.get("user_id"), "class_created", "training_class",
              cls["id"], f"Created '{cls['name']}' for intake {intake_id}.")
    return jsonify(ok=True, id=cls["id"], name=cls["name"],
                   join_code=cls["join_code"],
                   training_type=cls["training_type"])


@admin_bp.route("/admin/intake/<int:intake_id>/classes")
def intake_classes(intake_id):
    resp = require("corporate_payments")
    if resp:
        return resp
    return jsonify(instructors=class_instructors(), classes=[
        {"id": c["id"], "name": c["name"], "training_type": c["training_type"],
         "program_code": c.get("program_code"),
         "join_code": c["join_code"], "join_open": c["join_open"],
         "corporate_payment_id": c.get("corporate_payment_id"),
         "invoice_reference": c.get("invoice_reference"),
         "instructor_id": c.get("instructor_id"),
         "instructor_name": c.get("instructor_name"),
         "members": c["member_count"]}
        for c in list_classes(intake_id=intake_id)])


@admin_bp.route('/admin/class/<int:class_id>/instructor', methods=['POST'])
def class_assign_instructor(class_id):
    resp = require('corporate_payments')
    if resp:
        return resp
    def account_id(raw):
        if raw == '':
            return None
        if not raw or not raw.isascii() or not raw.isdigit() or len(raw)>10 or not 0<int(raw)<=2147483647:
            raise ValueError()
        return int(raw)
    try:
        instructor_id = account_id(request.form.get('instructor_id'))
        expected_id = account_id(request.form.get('expected_instructor_id'))
    except ValueError:
        return jsonify(error='Select an instructor and reload the batch if its current assignment is missing.'),400
    result, status = assign_class_instructor(class_id,instructor_id,expected_id,session.get('user_id'))
    return jsonify(result),status


@admin_bp.route("/admin/class/<int:class_id>/panel")
def class_panel(class_id):
    """One class: its code, its members, and who on the roster has NOT joined.

    The not-yet-joined list is the useful half. A trainer needs to know who is
    missing, and whether each of those people is merely late or actually
    blocked (unpaid, unreviewed), which is why each one carries the same
    reason membership_authority() would give them.
    """
    resp = require("corporate_payments")
    if resp:
        return resp
    cls = get_class(class_id=class_id)
    if not cls:
        return jsonify(error="No such class."), 404

    joined = class_members(class_id)
    joined_ids = {m["user_id"] for m in joined}

    outstanding = []
    for person in class_roster_candidates(class_id):
        if person["user_id"] in joined_ids:
            continue
        ok, reason = membership_authority(class_id, person["user_id"])
        outstanding.append({
            "user_id": person["user_id"],
            "name": person["name"],
            "email": person.get("email"),
            "can_join": ok,
            "reason": reason if not ok
                      else "Eligible — has not used the code yet.",
        })

    return jsonify(
        cls={"id": cls["id"], "name": cls["name"],
             "training_type": cls["training_type"],
             "join_code": cls["join_code"], "join_open": cls["join_open"],
             "intake_id": cls.get("intake_id"),
             "instructor_id": cls.get("instructor_id"),
             "corporate_payment_id": cls.get("corporate_payment_id")},
        members=[{"user_id": m["user_id"],
                  "name": f"{m['fname']} {m['lname']}".strip(),
                  "email": m["email"], "authorised": m["authorised"],
                  "joined_at": m["joined_at"].isoformat() if m["joined_at"] else None}
                 for m in joined],
        outstanding=outstanding)


@admin_bp.route("/admin/class/<int:class_id>/code/rotate", methods=["POST"])
def class_rotate_code(class_id):
    resp = require("corporate_payments")
    if resp:
        return resp
    code, err = rotate_join_code(class_id)
    if err:
        return jsonify(error=err), 400
    audit_log(session.get("user_id"), "class_code_rotated", "training_class",
              class_id, "Issued a new join code.")
    return jsonify(ok=True, join_code=code,
                   message=("New code issued. Existing members keep their "
                            "place — they were authorised by the roster, not "
                            "by the code."))


@admin_bp.route("/admin/class/<int:class_id>/join-open", methods=["POST"])
def class_join_open(class_id):
    resp = require("corporate_payments")
    if resp:
        return resp
    want_open = (request.form.get("open") or "").lower() in ("1", "true", "yes")
    if not set_join_open(class_id, want_open):
        return jsonify(error="No such class."), 404
    audit_log(session.get("user_id"), "class_join_toggled", "training_class",
              class_id, "Opened self-joining." if want_open else "Closed self-joining.")
    return jsonify(ok=True, join_open=want_open,
                   message=("Self-joining is open." if want_open else
                            "Self-joining is closed. Current members keep "
                            "their place."))


@admin_bp.route("/admin/class/<int:class_id>/member", methods=["POST"])
def class_add_member(class_id):
    """Add someone directly. Holds the SAME checks as a self-join."""
    resp = require("corporate_payments")
    if resp:
        return resp
    try:
        uid = int(request.form.get("user_id") or 0)
    except ValueError:
        return jsonify(error="Which account?"), 400
    ok, err = add_member_as_staff(class_id, uid, session.get("user_id"))
    if not ok:
        return jsonify(error=err), 400
    audit_log(session.get("user_id"), "class_member_added", "training_class",
              class_id, f"Added user {uid} to the class.")
    return jsonify(ok=True, message="Added to the class.")


@admin_bp.route("/admin/class/<int:class_id>/member/<int:uid>/remove",
                methods=["POST"])
def class_remove_member(class_id, uid):
    resp = require("corporate_payments")
    if resp:
        return resp
    if not remove_member(class_id, uid):
        return jsonify(error="That person is not in this class."), 400
    audit_log(session.get("user_id"), "class_member_removed", "training_class",
              class_id, f"Removed user {uid} from the class.")
    return jsonify(ok=True, message="Removed from the class.")
