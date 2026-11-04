import hashlib
import os
from datetime import date

from flask import (request, redirect, flash, session, current_app,
                   send_from_directory, abort, jsonify)

from db import (get_db, dict_cur, set_registration_status, build_batch_label,
                build_label_from_dates, expand_offsets, TYPE_OFFSETS,
                create_account_token, audit_log, get_pending_selfies,
                record_selfie_review, set_correction_note, clear_correction_note)
from email_utils import send_acceptance_email
from permissions import require
from utils import base_url

from . import admin_bp, require_admin


@admin_bp.route("/admin/registration/<reg_id>/status/<status>", methods=["POST"])
def admin_registration_status(reg_id, status):
    resp = require("review_registrations")
    if resp:
        return resp
    # `needs_correction` is a fourth state: the application is neither
    # approved nor refused, the applicant has been asked to fix something.
    # Distinct from 'rejected' because the roster shows it as actionable and
    # the company is notified about it.
    if status not in ("accepted", "rejected", "pending", "needs_correction"):
        return redirect("/admin#registrations")

    is_qualified = request.form.get("qualified", "1") == "1"
    set_registration_status(reg_id, status, is_qualified if status == "accepted" else None)

    if status == "needs_correction":
        # Written FOR the applicant and shown to their company; private
        # reviewer reasoning does not belong in this field.
        note = request.form.get("correction_note", "").strip()
        if not note:
            flash("Say what needs correcting — the applicant and their "
                  "company both see this note.", "error")
            set_registration_status(reg_id, "pending")
            return redirect("/admin#registrations")

        # Correction + notification intent commit together. If the mail
        # transport later fails, the intent survives for an admin to retry.
        from db import set_correction_and_queue_notice
        result, err = set_correction_and_queue_notice(reg_id, note, session.get("user_id"))
        if err:
            flash(err, "error")
            return redirect("/admin#registrations")

        audit_log(session.get("user_id"), "registration_needs_correction",
                  "registration", reg_id, f"Requested correction: {note}")
        flash(f"Registration #{reg_id} marked as needing correction.", "warning")

        if result.get("notification_id"):
            ok, msg = _deliver_notification(result["notification_id"])
            flash(msg, "success" if ok else "warning")
        elif result.get("company") is None:
            flash("Not linked to a company intake, so no company was notified.", "warning")
        else:
            flash("The company was already notified about this correction.", "warning")
        return redirect("/admin#registrations")

    if status == "accepted":
        audit_log(session.get("user_id"), "registration_accepted", "registration", reg_id,
                  f"Accepted registration #{reg_id} (qualified={is_qualified})")
        flash(f"Registration #{reg_id} accepted.", "success")
        # Acceptance alone is not readiness — a required identity review may
        # still be pending. The shared gate decides, so the two reviews can
        # complete in either order.
        issued, note = _issue_invitation_if_ready(reg_id)
        if note:
            flash(note, "success" if issued else "warning")
    else:
        audit_log(session.get("user_id"), f"registration_{status}", "registration", reg_id,
                  f"Marked registration #{reg_id} as {status}")
        flash(f"Registration #{reg_id} marked as {status}.", "warning")

    if status in ("accepted", "rejected"):
        clear_correction_note(reg_id)
    purged, n = _purge_if_review_complete(reg_id)
    if purged:
        flash(f"Review complete — {n} uploaded document(s) deleted; "
              f"the outcome and a hash of each are retained.", "success")
    return redirect("/admin#registrations")


@admin_bp.route("/admin/schedule/delete/<int:schedule_id>", methods=["POST"])
def admin_delete_schedule(schedule_id):
    resp = require("manage_schedules")
    if resp:
        return resp
    conn = get_db()
    cur  = dict_cur(conn)
    cur.execute("SELECT name FROM batches WHERE id = %s", (schedule_id,))
    row = cur.fetchone()
    cur.execute("DELETE FROM batches WHERE id = %s", (schedule_id,))
    conn.commit()
    cur.close()
    conn.close()
    name = row["name"] if row else "Batch"
    flash(f'"{name}" has been deleted.', "error")
    return redirect("/admin#schedules")


@admin_bp.route("/admin/schedule/edit/<int:schedule_id>", methods=["POST"])
def admin_edit_schedule(schedule_id):
    """Update a batch's name and/or its individual run days. `dates` arrives
    as one repeated form field per day (in whatever order the admin's edit
    dialog rendered them) — exactly as many as the batch already has, since
    this only lets you move a day, not add or remove one."""
    resp = require("manage_schedules")
    if resp:
        return resp
    conn = get_db()
    cur  = dict_cur(conn)
    cur.execute("SELECT name, type, start_date, dates FROM batches WHERE id = %s", (schedule_id,))
    row = cur.fetchone()
    if not row:
        cur.close()
        conn.close()
        flash("Batch not found.", "error")
        return redirect("/admin#schedules")

    name = request.form.get("name", "").strip() or row["name"]
    date_strs = [d for d in request.form.getlist("dates") if d.strip()]
    if date_strs:
        dates = sorted(date.fromisoformat(d) for d in date_strs)
    else:
        dates = sorted(row["dates"]) if row["dates"] else [row["start_date"]]
    start_date = dates[0]

    cur.execute("UPDATE batches SET name = %s, start_date = %s, dates = %s WHERE id = %s",
                (name, start_date, dates, schedule_id))
    conn.commit()
    cur.close()
    conn.close()

    label = build_label_from_dates(name, dates)
    flash(f'"{label}" has been updated.', "success")
    return redirect("/admin#schedules")


@admin_bp.route("/admin/schedule/add", methods=["POST"])
def admin_add_schedule():
    resp = require("manage_schedules")
    if resp:
        return resp
    name      = request.form.get("name",       "").strip()
    start_str = request.form.get("start_date", "").strip()
    btype = request.form.get("btype", "").strip()
    if name and btype in ("training", "renewal") and start_str:
        start_date = date.fromisoformat(start_str)
        offsets    = TYPE_OFFSETS["training"] if btype == "training" else TYPE_OFFSETS["renewal"]
        dates      = expand_offsets(offsets, start_date)
        label      = build_batch_label(name, offsets, start_date)
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("INSERT INTO batches (name, type, start_date, dates) VALUES (%s, %s, %s, %s)",
                    (name, btype, start_date, dates))
        conn.commit()
        cur.close()
        conn.close()
        flash(f'"{label}" has been added.', "success")
    return redirect("/admin#schedules")


@admin_bp.route("/admin/registration/<reg_id>/selfie")
def admin_registration_selfie(reg_id):
    resp = require("review_registrations")
    if resp:
        return resp
    conn = get_db()
    cur  = dict_cur(conn)
    cur.execute("SELECT selfie_with_id FROM registrations WHERE id = %s", (reg_id,))
    reg = cur.fetchone()
    cur.close()
    conn.close()

    if not reg or not reg.get("selfie_with_id"):
        abort(404)
    return _serve_document(reg["selfie_with_id"])


def _invitation_delivery_message(outcome, email):
    if outcome == 'submitted':
        return f'Account setup email submitted to the mail server for {email}. Inbox delivery is not confirmed.'
    if outcome == 'preview':
        return f'Previewed only — account setup email saved to outbox/, NOT emailed to {email}.'
    if outcome == 'mock':
        return f'Mocked only — account setup email NOT emailed to {email}.'
    raise RuntimeError('Unknown invitation mail outcome.')


def _issue_invitation_if_ready(reg_id):
    """Mint and send the account-setup invitation, once, when ready.

    (issued: bool, message: str|None)

    One gate for both review paths. Registration acceptance and identity
    review may complete in either order; whichever is second lands here and
    finds the readiness rule satisfied. Neither can issue on its own.

    Repeat-safe: `claim_account_invitation()` is a guarded insert, so a double
    submit cannot mint a second valid token.

    Delivery recovery is a ROTATION, not a resend. Only sha256(token) is
    stored, so the plaintext link cannot be recovered by anyone — including
    us — once this function returns. A failed email is therefore recovered by
    admin_resend_invitation(), which issues a FRESH link and kills the old
    one. Any wording suggesting the same link can be re-sent would be false.
    """
    from db import (get_registration_full, claim_account_invitation,
                    account_exists_for_email)
    from review_policy import may_issue_account_invitation

    reg = get_registration_full(reg_id)
    if not reg:
        return False, None

    allowed, reason = may_issue_account_invitation(reg)
    if not allowed:
        return False, f"Not yet invited — {reason}"
    if not (reg.get("email") or "").strip():
        return False, "Approved, but there is no email on file — send the link manually."
    # No point inviting someone who already signed up: the token would be
    # dead weight and the email confusing.
    if account_exists_for_email(reg["email"]):
        return False, "An account already exists for this email — no invitation needed."

    # The admin's recorded qualification decision is carried through
    # unchanged; this path never asserts a value of its own.
    token, created = claim_account_invitation(reg_id, reg["email"],
                                              bool(reg.get("is_qualified", 1)))
    if not created:
        return False, "An account setup invitation has already been issued."

    try:
        outcome = send_acceptance_email(reg["email"], reg["full_name"], token,
                                        bool(reg.get("is_qualified", 1)), base_url())
        message = _invitation_delivery_message(outcome, reg['email'])
    except Exception as e:
        current_app.logger.warning("Invitation email failed for %s: %s", reg_id, e)
        audit_log(session.get("user_id"), "invitation_email_failed",
                  "registration", reg_id, f"{type(e).__name__}: {e}")
        # Honest wording: the invitation row exists, but only its hash is
        # stored, so Resend issues a NEW link rather than re-sending this one.
        return True, ("Invitation created, but the email could not be sent. "
                      "Use Resend — it will issue a fresh link.")

    audit_log(session.get("user_id"), "invitation_issued", "registration", reg_id,
              f"Account setup invitation issued ({outcome})")
    return True, message


def _deliver_notification(notif_id):
    """Attempt one queued company notification. (ok, message).

    Order matters and is deliberate:
      1. mark the attempt in flight (status -> uncertain, attempts += 1)
      2. hand the message to the transport
      3. record the terminal outcome

    If the process dies between 2 and 3 the row stays `uncertain` with an
    attempt counted — which is the truth: we do not know whether it went out.
    It shows up in the admin's unresolved list for a human to judge, rather
    than silently looking untried or falsely looking sent.
    """
    from db import (get_notification, begin_attempt, finish_attempt,
                    get_intake, get_slots)
    from email_utils import send_company_correction_notice
    from pricing import program_label

    import email_utils

    n = get_notification(notif_id)
    if not n:
        return False, "That notification no longer exists."
    if n['kind'] != 'needs_correction':
        return False, 'Use the delivery controls for this notification type.'
    if n["status"] == "submitted":
        return True, "Already submitted to the mail server."

    # Claim ownership. A live lease held by another attempt refuses here
    # rather than risking a duplicate email.
    attempt_id, attempts, why = begin_attempt(notif_id)
    if not attempt_id:
        return False, why

    intake = get_intake(intake_id=n["intake_id"])
    slot = next((s for s in get_slots(n["intake_id"]) if s["id"] == n["slot_id"]), None)
    if not intake or not slot:
        finish_attempt(notif_id, attempt_id, error="Intake or roster slot no longer exists")
        return False, "The intake or roster entry no longer exists."

    try:
        send_company_correction_notice(
            n["to_email"], intake["company_name"], slot["full_name"],
            slot["correction_note"] or "Please contact EnergyWize.",
            program_label(intake["form_type"]), base_url())
    except Exception as e:
        finish_attempt(notif_id, attempt_id, error=f"{type(e).__name__}: {e}")
        current_app.logger.warning("Company notice %s failed: %s", notif_id, e)
        return False, (f"Could not send the company notice (attempt {attempts}). "
                       f"It is queued — use Retry in the intake panel.")

    transport = email_utils.MAIL_TRANSPORT
    written = finish_attempt(notif_id, attempt_id, transport=transport)
    if written is None:
        # Lease lapsed while the transport was working: another attempt owns
        # the row now, so this outcome is not ours to record.
        return False, ("The message was handed to the transport, but this "
                       "attempt no longer owned the send. Check the "
                       "notification state before retrying.")

    audit_log(session.get("user_id"), "company_notified", "corporate_intake",
              n["intake_id"], f"Correction notice for {slot['full_name']} "
                              f"-> {n['to_email']} ({written})")
    # Wording follows what actually happened — a preview did not send anything.
    if written == "previewed":
        return True, (f"Previewed only (MAIL_TRANSPORT=preview) — written to "
                      f"outbox/, not sent to {n['to_email']}.")
    if written == "mocked":
        return True, f"Mock transport recorded the message for {n['to_email']}."
    return True, f"Correction notice submitted to the mail server for {n['to_email']}."


@admin_bp.route("/admin/notification/<int:notif_id>/retry", methods=["POST"])
def admin_retry_notification(notif_id):
    resp = require("review_registrations")
    if resp:
        return resp
    ok, msg = _deliver_notification(notif_id)
    return jsonify(ok=ok, message=msg), (200 if ok else 502)


@admin_bp.route("/admin/registration/<reg_id>/resend-invitation", methods=["POST"])
def admin_resend_invitation(reg_id):
    """Issue a FRESH account-setup link and send it.

    Not a re-send of the original: `account_tokens` stores only
    sha256(token), so the previous plaintext cannot be recovered by anyone,
    including us. Rotating is also the safer behaviour — a link that bounced
    around a mail system stops working.
    """
    resp = require("review_registrations")
    if resp:
        return resp

    from db import (get_registration_full, rotate_account_invitation,
                    account_exists_for_email)
    from review_policy import may_issue_account_invitation

    reg = get_registration_full(reg_id)
    if not reg:
        return jsonify(error="No such registration."), 404

    allowed, reason = may_issue_account_invitation(reg)
    if not allowed:
        return jsonify(error=f"Not ready to invite — {reason}"), 400
    if account_exists_for_email(reg.get("email") or ""):
        return jsonify(error="An account already exists for this email."), 400

    token, rotated = rotate_account_invitation(
        reg_id, reg["email"], bool(reg.get("is_qualified", 1)))
    if not rotated:
        return jsonify(error="This invitation has already been used — "
                             "the account exists."), 400

    try:
        outcome = send_acceptance_email(reg["email"], reg["full_name"], token,
                                        bool(reg.get("is_qualified", 1)), base_url())
        message = _invitation_delivery_message(outcome, reg['email'])
    except Exception as e:
        current_app.logger.warning("Invitation resend failed for %s: %s", reg_id, e)
        audit_log(session.get("user_id"), "invitation_resend_failed",
                  "registration", reg_id, f"{type(e).__name__}: {e}")
        # The new link is live even though this delivery attempt failed; the
        # old one is already dead. Say so rather than implying nothing changed.
        return jsonify(error="A new link was issued but the email failed to "
                             "send. The previous link no longer works. "
                             "Try again.", rotated=True), 502

    audit_log(session.get("user_id"), "invitation_resent", "registration", reg_id,
              f"Issued a fresh account setup link ({outcome})")
    return jsonify(ok=True, delivery=outcome, message=message + ' Any previous link no longer works.')


def _purge_if_review_complete(reg_id):
    """Delete a registration's uploads once BOTH review gates have closed.

    The gates are independent: `registrations.status` is the accept/reject on
    the application, and `selfie_reviewed_at` is the separate identity check.
    Deleting on either alone would take a document away from a reviewer who
    still needs it, so this runs after each gate and does nothing until both
    are done.

    Returns (purged: bool, count: int). Never raises into the request — a
    failed deletion must not undo a completed review.
    """
    from db import (registration_review_state, get_registration_documents,
                    record_document_purge)

    state = registration_review_state(reg_id)
    if not state or state["purged"]:
        return False, 0
    if state["status"] not in ("accepted", "rejected"):
        return False, 0
    # A registration with no selfie on file has nothing to verify, so that
    # gate is vacuously closed; one that has a selfie must have been reviewed.
    if state["has_selfie"] and not state["selfie_reviewed"]:
        return False, 0

    folders = [current_app.config["UPLOAD_FOLDER"]]
    legacy = current_app.config.get("LEGACY_UPLOAD_FOLDER")
    if legacy:
        folders.append(legacy)

    entries = []
    for field, fname in get_registration_documents(reg_id).items():
        entry = {"field": field, "file_ext": os.path.splitext(fname)[1].lower().lstrip(".")}
        path = next((os.path.join(d, fname) for d in folders
                     if os.path.isfile(os.path.join(d, fname))), None)
        if not path:
            entry["note"] = "missing"
            entries.append(entry)
            continue
        try:
            h = hashlib.sha256()
            with open(path, "rb") as f:
                for block in iter(lambda: f.read(65536), b""):
                    h.update(block)
            entry["sha256"] = h.hexdigest()
            entry["byte_size"] = os.path.getsize(path)
            os.remove(path)
            entry["note"] = "deleted"
        except Exception as e:
            current_app.logger.warning(
                "Could not purge %s for registration %s: %s", field, reg_id, type(e).__name__)
            entry["note"] = "error"
        entries.append(entry)

    if not entries:
        return False, 0
    try:
        complete = record_document_purge(reg_id, entries, state["status"],
                                         session.get("user_id"))
    except Exception as e:
        current_app.logger.warning(
            "Document purge bookkeeping failed for %s: %s", reg_id, type(e).__name__)
        return False, 0

    deleted = sum(1 for e in entries if e.get("note") == "deleted")
    stuck   = [e["field"] for e in entries if e.get("note") == "error"]
    detail  = f"Review closed ({state['status']}); {deleted} document(s) hashed and deleted."
    if stuck:
        # Left deliberately un-stamped so the next gate action or a sweep
        # tries again rather than treating the row as finished.
        detail += f" {len(stuck)} could not be deleted and will be retried: {', '.join(stuck)}."
        current_app.logger.warning("Registration %s: %s", reg_id, detail)
    audit_log(session.get("user_id"), "registration_documents_purged",
              "registration", reg_id, detail)
    return complete, deleted


def _serve_document(filename):
    """Serve a registration document from private storage.

    Falls back to the pre-Phase-0 location for rows that have not been
    migrated yet, so the review queue keeps working during the transition.
    Reaching that folder through here is safe — this helper is only ever
    called from routes behind require("review_registrations"), and the public
    /static/uploads/ path is blocked in app.py. send_from_directory re-joins
    safely, so a stored value containing ../ resolves to 404 rather than
    escaping either folder.
    """
    primary = current_app.config["UPLOAD_FOLDER"]
    if os.path.isfile(os.path.join(primary, filename)):
        return send_from_directory(primary, filename)
    legacy = current_app.config.get("LEGACY_UPLOAD_FOLDER")
    if legacy and os.path.isfile(os.path.join(legacy, filename)):
        current_app.logger.info(
            "Serving un-migrated registration document from legacy storage")
        return send_from_directory(legacy, filename)
    abort(404)


# The five non-selfie documents. Previously the console linked straight to
# /static/uploads/<name>, which Flask served to anybody — the gate above was
# bypassable by construction. The document is now addressed by registration
# id + field name, so the filename never appears in a URL and the only
# readable files are the ones actually recorded against that registration.
_DOC_FIELDS = ("photo_id", "resume", "expired_doe", "valid_id", "selfie_with_id")


@admin_bp.route("/admin/registration/<reg_id>/document/<field>")
def admin_registration_document(reg_id, field):
    resp = require("review_registrations")
    if resp:
        return resp
    if field not in _DOC_FIELDS:
        abort(404)
    conn = get_db()
    cur  = dict_cur(conn)
    # Interpolating `field` is safe only because it was just checked against
    # the tuple above; it is never free text from the request.
    cur.execute(f"SELECT {field} AS fname FROM registrations WHERE id = %s", (reg_id,))
    reg = cur.fetchone()
    cur.close()
    conn.close()

    if not reg or not reg.get("fname"):
        abort(404)
    return _serve_document(reg["fname"])


@admin_bp.route("/admin/selfie/<reg_id>/approve", methods=["POST"])
def admin_approve_selfie(reg_id):
    resp = require("review_registrations")
    if resp:
        return resp
    # Record the identity decision. That is ALL this action does — it no
    # longer mints an account invitation by itself.
    #
    # Previously this issued a token with is_qualified=True and no check on
    # registrations.status, so approving a selfie both bypassed application
    # review and silently overwrote a "not qualified" decision. The two
    # reviews may still happen in either order; whichever finishes second
    # triggers the invitation through the shared gate below.
    if not record_selfie_review(reg_id, "approved", session.get("user_id")):
        flash(f"Registration #{reg_id} identity review was already recorded.", "warning")
        return redirect("/admin#selfies")

    audit_log(session.get("user_id"), "selfie_verified", "registration", reg_id,
              f"Approved selfie verification for registration #{reg_id}")
    flash(f"Registration #{reg_id} identity verified.", "success")

    issued, note = _issue_invitation_if_ready(reg_id)
    if note:
        flash(note, "success" if issued else "warning")

    purged, n = _purge_if_review_complete(reg_id)
    if purged:
        flash(f"Review complete — {n} uploaded document(s) deleted; "
              f"the outcome and a hash of each are retained.", "success")
    return redirect("/admin#selfies")


@admin_bp.route("/admin/selfie/<reg_id>/reject", methods=["POST"])
def admin_reject_selfie(reg_id):
    resp = require("review_registrations")
    if resp:
        return resp
    reason = request.form.get("reason", "").strip()
    # Close the gate rather than clearing selfie_with_id: the old version
    # dropped the pointer and left the image sitting in storage with nothing
    # referencing it. The file is removed by the purge below once the
    # registration's own accept/reject has also happened.
    record_selfie_review(reg_id, "rejected", session.get("user_id"))
    flash(f"Registration #{reg_id} selfie rejected.", "warning")
    audit_log(session.get("user_id"), "selfie_rejected", "registration", reg_id,
              f"Rejected selfie: {reason}")
    purged, n = _purge_if_review_complete(reg_id)
    if purged:
        flash(f"Review complete — {n} uploaded document(s) deleted.", "success")
    return redirect("/admin#selfies")
