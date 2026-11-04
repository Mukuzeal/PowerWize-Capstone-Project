"""Company intake and roster — admin side.

Staff create an intake, list the trainees the company expects to enrol, and
hand out two kinds of link:

  * one coordinator link per intake — a read-only status view for the company
  * one shared registration link and automatically prepared class code — each
    trainee enters that code and their roster email, attached to their own slot

Nothing here approves anybody. Review stays in admin/registrations.py, and the
roster view derives its per-trainee state from `registrations.status` rather
than keeping a second copy that could drift.

Open to the same roles as registration review (`review_registrations`): an
intake is a view onto applications, not a billing screen.
"""
from flask import request, redirect, flash, session, jsonify, current_app

from db import (audit_log, create_intake, get_intake, get_intakes, get_slots,
                add_slot, issue_coordinator_token, revoke_coordinator_token,
                revoke_slot_invite, payment_link_eligibility,
                get_notifications, replace_slot_invite, issue_registration_token,
                revoke_registration_token, set_intake_archived,
                queue_registration_link_email, registration_email_payload,
                get_notification, notification_payload, begin_attempt, finish_attempt,
                force_retry_uncertain)
from permissions import require
from pricing import program_label
from utils import base_url

from . import admin_bp

# Programs an intake may be raised against; mirrors the public form_type
# values so an invitation cannot point at a form that does not exist.
FORM_TYPES = ("training", "cea_training", "cem_renewal", "cea_renewal",
              "gemp_lgu", "gemp_oge")


def dashboard_context():
    """Data for the console's Company Intake pane."""
    records = get_intakes()
    return {
        "intake_records":    records,
        "intake_active_count": sum(r["archived_at"] is None for r in records),
        "intake_archived_count": sum(r["archived_at"] is not None for r in records),
        "intake_form_types": FORM_TYPES,
        "intake_program_labels": {code: program_label(code) for code in FORM_TYPES},
    }


def _invite_url(token):
    return base_url().rstrip("/") + f"/company/invite/{token}"


def _coord_url(token):
    return base_url().rstrip("/") + f"/company/roster/{token}"


@admin_bp.route("/admin/intake/<int:intake_id>/archive", methods=["POST"])
@admin_bp.route("/admin/intake/<int:intake_id>/restore", methods=["POST"])
def intake_archive(intake_id):
    resp = require("review_registrations")
    if resp:
        return resp
    archived = request.path.endswith("/archive")
    row = set_intake_archived(intake_id, archived, session.get("user_id"))
    changed = row is not None
    if not changed:
        row = get_intake(intake_id=intake_id)
        if not row:
            return jsonify(error="No such intake."), 404
    if changed:
        audit_log(session.get("user_id"),
                  "intake_archived" if archived else "intake_restored",
                  "corporate_intake", intake_id,
                  f"{'Archived' if archived else 'Restored'} intake for {row['company_name']}")
    return jsonify(ok=True, id=intake_id, changed=changed,
                   archived=row["archived_at"] is not None,
                   message="Intake archived." if archived else "Intake restored to Active.")


@admin_bp.route("/admin/intake/new", methods=["POST"])
def intake_new():
    resp = require("review_registrations")
    if resp:
        return resp
    f = request.form
    company_name   = f.get("company_name", "").strip()
    contact_person = f.get("contact_person", "").strip()
    contact_email  = f.get("contact_email", "").strip()
    form_type      = f.get("form_type", "").strip()

    errors = []
    if not company_name:
        errors.append("Company name is required.")
    if not contact_person:
        errors.append("Contact person is required.")
    if not contact_email or "@" not in contact_email:
        errors.append("A valid contact email is required.")
    if form_type not in FORM_TYPES:
        errors.append("Select a training program.")
    if errors:
        return jsonify(errors=errors), 400

    iid = create_intake(company_name, contact_person, contact_email,
                        f.get("contact_number", "").strip(), form_type,
                        f.get("training_type", "").strip(), session.get("user_id"))
    audit_log(session.get("user_id"), "intake_created", "corporate_intake", iid,
              f"Created intake for {company_name} ({form_type})")
    return jsonify(ok=True, id=iid)


@admin_bp.route("/admin/intake/<int:intake_id>/slots", methods=["POST"])
def intake_add_slots(intake_id):
    """Add trainees from name/email fields; accept legacy bulk submissions too."""
    resp = require("review_registrations")
    if resp:
        return resp
    if not get_intake(intake_id=intake_id):
        return jsonify(error="No such intake."), 404

    names = request.form.getlist("trainee_name")
    emails = request.form.getlist("trainee_email")
    entries = []
    if names or emails:
        if len(names) != len(emails):
            return jsonify(error="Each trainee needs a name and email address."), 400
        entries = list(zip(names, emails))
    for raw in (() if names or emails else (request.form.get("roster", "") or "").splitlines()):
        line = raw.strip()
        if not line:
            continue
        if "," in line:
            name, _, email = line.partition(",")
        elif "<" in line and line.rstrip().endswith(">"):
            name, _, email = line.partition("<")
            email = email.rstrip(">")
        else:
            entries.append((line, ""))
            continue
        entries.append((name, email))

    added, skipped, invites = 0, [], []
    for name, email in entries:
        name, email = name.strip(), email.strip()
        if not name or "@" not in email:
            skipped.append(f"{name or email or 'Trainee'} (needs a name and a valid email)")
            continue
        slot_id, token = add_slot(intake_id, name, email)
        if slot_id is None:
            skipped.append(f"{email} (already on this roster)")
            continue
        added += 1
        # The new field-based UI shares one intake URL. Keep individual
        # responses only for compatibility with legacy bulk clients.
        if not names and not emails:
            invites.append({"slot_id": slot_id, "name": name, "email": email,
                            "url": _invite_url(token)})

    if added:
        audit_log(session.get("user_id"), "intake_slots_added",
                  "corporate_intake", intake_id, f"Added {added} roster slot(s)")
    # Legacy bulk callers can still receive single-use invitation links.
    # The field-based admin UI uses the shared registration entry instead.
    return jsonify(ok=True, added=added, skipped=skipped, invites=invites)


@admin_bp.route("/admin/intake/<int:intake_id>/panel")
def intake_panel(intake_id):
    """Roster + eligibility, as JSON for the console pane."""
    resp = require("review_registrations")
    if resp:
        return resp
    intake = get_intake(intake_id=intake_id)
    if not intake:
        return jsonify(error="No such intake."), 404
    eligible, reason, detail = payment_link_eligibility(intake_id)
    slots = [{
        "id":            s["id"],
        "full_name":     s["full_name"],
        "email":         s["email"],
        "status":        s["derived_status"],
        "status_label":  s['readiness']['display_label'] if s['readiness'] else 'Not submitted',
        "registration_status": s['reg_status'],
        "identity":      s['readiness']['identity'] if s['readiness'] else None,
        "identity_label": s['readiness']['identity_label'] if s['readiness'] else 'Not submitted',
        "review_blockers": s['readiness']['blockers'] if s['readiness'] else [],
        "registration":  s["registration_id"],
        "submitted_at":  s["submitted_at"].isoformat() if s["submitted_at"] else None,
        "correction":    s["correction_note"],
        "invite_used":   s["invite_used_at"] is not None,
        "invite_revoked": s["invite_revoked_at"] is not None,
    } for s in get_slots(intake_id)]
    return jsonify(intake={
        "id": intake["id"], "company_name": intake["company_name"],
        "contact_person": intake["contact_person"],
        "contact_email": intake["contact_email"],
        "form_type": intake["form_type"],
        "program_label": program_label(intake["form_type"]),
        "status": intake["status"],
        "archived_at": intake["archived_at"].isoformat() if intake["archived_at"] else None,
        "payment_link_sent_at": intake["payment_link_sent_at"].isoformat()
            if intake["payment_link_sent_at"] else None,
        "coord_link_active": bool(intake["coord_token_hash"]
                                  and not intake["coord_revoked_at"]),
        "registration_link_active": bool(intake.get("registration_token_hash")
            and not intake.get("registration_revoked_at")),
    }, slots=slots, eligibility={"eligible": eligible, "reason": reason,
                                 "detail": detail},
       notifications=[{
           "id":        n["id"],
           "kind":      n["kind"],
           "to_email":  n["to_email"],
           "slot_name": n["slot_name"],
           "status":    n["status"],
           "transport": n["transport"],
           "attempts":  n["attempts"],
           "error":     n["last_error"],
           "created_at": n["created_at"].isoformat() if n["created_at"] else None,
           "sent_at":   n["sent_at"].isoformat() if n["sent_at"] else None,
       } for n in get_notifications(intake_id)])


@admin_bp.route("/admin/intake/<int:intake_id>/registration-link", methods=["POST"])
def intake_issue_registration_link(intake_id):
    resp = require("review_registrations")
    if resp:
        return resp
    issued = issue_registration_token(intake_id, created_by=session.get("user_id"), with_class=True)
    if not issued:
        return jsonify(error="Only an open intake can receive a registration link."), 409
    audit_log(session.get("user_id"), "intake_registration_link_issued", "corporate_intake",
              intake_id, "Issued shared registration link with an automatically prepared class")
    response = jsonify(ok=True, url=base_url().rstrip('/') + '/company/register/' + issued['token'],
                       class_id=issued['class_id'], class_code=issued['class_code'], class_name=issued['class_name'],
                       contact_email=issued['contact_email'])
    response.headers['Cache-Control'] = 'no-store'
    return response


def _deliver_registration_notice(notif_id):
    """Revalidate the stored link/code and recipient before claiming delivery."""
    import email_utils
    notice = get_notification(notif_id)
    if not notice or notice['kind'] != 'registration_link':
        return jsonify(error='No such registration-link notice.'), 404
    stored, error = notification_payload(notif_id, link_kind='registration')
    if error or not stored:
        return jsonify(error=error or 'This notice has no stored registration link.'), 409
    current, error = registration_email_payload(notice['intake_id'], stored.get('registration_url'),
                                                stored.get('class_id'), base_url())
    if error:
        return jsonify(error=error), 409
    if current['class_code'] != stored.get('class_code') or current['to_email'] != notice['to_email']:
        return jsonify(error='The class code or company contact has changed. Send the current link and code as a new notice.'), 409
    if notice['status'] in ('submitted', 'in_flight', 'uncertain'):
        return jsonify(error='This notice was submitted, is in flight, or needs explicit delivery recovery. Check its delivery history.'), 409
    attempt_id, _, error = begin_attempt(notif_id)
    if not attempt_id:
        return jsonify(error=error), 409
    try:
        outcome = email_utils.send_company_registration_link(
            current['to_email'], current['company_name'], current['contact_person'],
            current['program_label'], current['registration_url'], current['class_code'], current['expires_at'])
        transport = {'mock': 'mock', 'preview': 'preview', 'submitted': 'smtp'}.get(outcome)
        if transport is None:
            raise email_utils.MailDeliveryError('Unknown mail transport outcome.')
    except Exception as exc:
        # Do not log exception messages: a transport may quote the secret URL.
        finish_attempt(notif_id, attempt_id, error=f'Delivery failed ({type(exc).__name__}). Use Retry.')
        current_app.logger.warning('Registration notice %s failed (%s)', notif_id, type(exc).__name__)
        return jsonify(error='Could not send the registration email. The notice is saved; use Retry.',
                       notification_id=notif_id), 502
    status = finish_attempt(notif_id, attempt_id, transport=transport)
    if status is None:
        return jsonify(error='The transport returned, but delivery ownership changed. Check the notice before retrying.'), 409
    if status == 'submitted':
        message = f'Registration link and class code submitted to the mail server for {notice["to_email"]}. This does not confirm inbox delivery.'
    elif status == 'previewed':
        message = f'Previewed only — written to outbox/, NOT emailed to {notice["to_email"]}.'
    else:
        message = f'Mocked only — NOT emailed to {notice["to_email"]}.'
    audit_log(session.get('user_id'), 'intake_registration_email_attempted',
              'corporate_intake', notice['intake_id'], f'Notice {notif_id}: {status}')
    return jsonify(ok=True, message=message, status=status, notification_id=notif_id)


@admin_bp.route('/admin/intake/<int:intake_id>/registration-link/send', methods=['POST'])
def intake_send_registration_link(intake_id):
    resp = require('review_registrations')
    if resp:
        return resp
    try:
        class_id = int(request.form.get('class_id', ''))
    except ValueError:
        return jsonify(error='Generate a registration link and class code first.'), 400
    from secretbox import SecretUnavailable
    try:
        notif_id, error = queue_registration_link_email(intake_id,
            request.form.get('registration_url', ''), class_id, base_url(), session.get('user_id'))
    except SecretUnavailable:
        return jsonify(error='Email retry storage is unavailable. Configure the application encryption key before sending.'), 503
    if error:
        return jsonify(error=error), 409
    return _deliver_registration_notice(notif_id)


@admin_bp.route('/admin/intake/<int:intake_id>/registration-notice/<int:notif_id>/retry', methods=['POST'])
def intake_retry_registration_link(intake_id, notif_id):
    resp = require('review_registrations')
    if resp:
        return resp
    notice = get_notification(notif_id)
    if not notice or notice['kind'] != 'registration_link' or notice['intake_id'] != intake_id:
        return jsonify(error='No such registration-link notice for this intake.'), 404
    if notice['status'] == 'uncertain':
        if request.form.get('confirm_resend') != 'yes':
            return jsonify(error='The earlier send has an unknown outcome. Confirm a possible duplicate email before retrying.'), 409
        force_retry_uncertain(notif_id, f'Operator {session.get("user_id")} confirmed a possible duplicate registration email')
    return _deliver_registration_notice(notif_id)


@admin_bp.route("/admin/intake/<int:intake_id>/registration-link/revoke", methods=["POST"])
def intake_revoke_registration_link(intake_id):
    resp = require("review_registrations")
    if resp:
        return resp
    revoke_registration_token(intake_id)
    audit_log(session.get("user_id"), "intake_registration_link_revoked", "corporate_intake",
              intake_id, "Revoked shared registration access, including outstanding verification grants")
    return redirect('/admin#intake')


@admin_bp.route("/admin/intake/<int:intake_id>/coordinator-link", methods=["POST"])
def intake_issue_coord_link(intake_id):
    resp = require("review_registrations")
    if resp:
        return resp
    token = issue_coordinator_token(intake_id)
    if not token:
        return jsonify(error="Only an open intake can be given a link."), 400
    audit_log(session.get("user_id"), "intake_coord_link_issued",
              "corporate_intake", intake_id, "Issued a coordinator link")
    # Shown once; only the hash is stored.
    return jsonify(ok=True, url=_coord_url(token))


@admin_bp.route("/admin/intake/<int:intake_id>/coordinator-link/revoke", methods=["POST"])
def intake_revoke_coord_link(intake_id):
    resp = require("review_registrations")
    if resp:
        return resp
    ok = revoke_coordinator_token(intake_id)
    if ok:
        audit_log(session.get("user_id"), "intake_coord_link_revoked",
                  "corporate_intake", intake_id, "Revoked the coordinator link")
    flash("Coordinator link revoked." if ok else "No active link to revoke.",
          "warning" if ok else "error")
    return redirect("/admin#intake")


@admin_bp.route("/admin/intake/slot/<int:slot_id>/invitation-link", methods=["POST"])
def intake_replace_invite(slot_id):
    resp = require("review_registrations")
    if resp:
        return resp
    slot, token = replace_slot_invite(slot_id)
    if not slot:
        return jsonify(error="A new link is available only for an unsubmitted trainee in an open intake."), 409
    audit_log(session.get("user_id"), "intake_invite_replaced",
              "corporate_intake_slot", slot_id,
              "Replaced trainee invitation; the previous link is invalid.")
    response = jsonify(ok=True, slot_id=slot_id, name=slot["full_name"],
                       url=_invite_url(token), expires_at=slot["invite_expires_at"].isoformat())
    response.headers["Cache-Control"] = "no-store"
    return response


@admin_bp.route("/admin/intake/slot/<int:slot_id>/revoke", methods=["POST"])
def intake_revoke_invite(slot_id):
    resp = require("review_registrations")
    if resp:
        return resp
    ok = revoke_slot_invite(slot_id)
    if ok:
        audit_log(session.get("user_id"), "intake_invite_revoked",
                  "corporate_intake_slot", slot_id, "Revoked a trainee invitation")
    return jsonify(ok=ok)
