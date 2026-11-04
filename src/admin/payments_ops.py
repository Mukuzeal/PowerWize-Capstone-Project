"""Corporate payment operations — admin side.

Wires Company Intake to Corporate Payments and gives staff the controls the
hosted-checkout backend needs: create an invoice from an approved roster,
issue and send the payment link, watch delivery, inspect attempts, and resolve
an attempt whose outcome the system could not establish on its own.

Capability is `corporate_payments`, matching the rest of billing.
"""
import json as _json
from datetime import datetime, timedelta

from flask import request, jsonify, session, current_app

from db import (audit_log, get_intake, invoiceable_roster, get_corporate_payment,
                create_corporate_payment, get_corporate_items, get_attempts,
                issue_pay_token, revoke_pay_token, payments_needing_attention,
                unresolved_events, unresolved_events_for_payment,
                unresolved_event, resolve_event, clear_attention,
                resolve_attempt, record_session, authorize_payment_link_send,
                note_payment_link_submitted, get_notification, begin_attempt,
                finish_attempt, get_notifications, outbound_args,
                get_db, dict_cur, create_invoice_for_intake,
                validate_pay_url, notification_payload)
from permissions import require
from pricing import calculate_fee, program_option_label, to_centavos
from utils import base_url

from . import admin_bp

DEFAULT_EXPIRY_HOURS = 24
OPEN_ATTEMPT_STATES = ("creating", "active", "unknown")


def _pay_url(token):
    return base_url().rstrip("/") + f"/pay/corporate/{token}"


# ── Intake → invoice ─────────────────────────────────────────────────────────

@admin_bp.route("/admin/intake/<int:intake_id>/invoice/preview")
def intake_invoice_preview(intake_id):
    """Who would be billed, who cannot be, and the total — before committing."""
    resp = require("corporate_payments")
    if resp:
        return resp
    intake = get_intake(intake_id=intake_id)
    if not intake:
        return jsonify(error="No such intake."), 404

    billable, blocked = invoiceable_roster(intake_id)
    blocked = [{"name": b["full_name"], "email": b["email"],
                "reason": b["reason"]} for b in blocked]
    lines, total = [], 0.0
    for b in billable:
        fee = calculate_fee(b["form_type"], b["training_type"])
        if not fee:
            # No published price for this program/mode combination. Surfaced
            # as a blocker with the reason rather than a zero-peso line, which
            # would quietly understate the invoice.
            blocked.append({
                "name": b["full_name"], "email": b["email"],
                "reason": (f"No published price for "
                           f"{program_option_label(b['form_type'], b['training_type'])}"
                           f" — check their training type.")})
            continue
        total += fee["total"]
        lines.append({"name": b["full_name"], "email": b["email"],
                      "user_id": b["user_id"], "price_php": fee["total"],
                      "label": program_option_label(b["form_type"],
                                                    b["training_type"])})
    return jsonify(
        intake={"id": intake["id"], "company_name": intake["company_name"],
                "contact_person": intake["contact_person"],
                "contact_email": intake["contact_email"]},
        lines=lines, total_php=round(total, 2), blocked=blocked,
        can_create=bool(lines) and not blocked)


@admin_bp.route("/admin/intake/<int:intake_id>/invoice", methods=["POST"])
def intake_create_invoice(intake_id):
    """Create a corporate invoice from the approved roster.

    Prices are recomputed here from the published pricing table — the browser
    sends no amounts. Anyone the roster cannot bill is reported rather than
    quietly excluded from the total.
    """
    resp = require("corporate_payments")
    if resp:
        return resp
    intake = get_intake(intake_id=intake_id)
    if not intake:
        return jsonify(error="No such intake."), 404

    try:
        hours = int(request.form.get("expiry_hours", DEFAULT_EXPIRY_HOURS))
    except ValueError:
        hours = DEFAULT_EXPIRY_HOURS
    hours = max(1, min(hours, 24 * 14))

    # Same rule the preview showed, re-derived with the intake row locked and
    # committed with the invoice. Previously the preview said "cannot create"
    # while this endpoint created one for whoever happened to be billable,
    # silently undercharging.
    result, err = create_invoice_for_intake(
        intake_id, datetime.now() + timedelta(hours=hours),
        session.get("user_id"), calculate_fee)
    if err:
        return jsonify(error=err), 400
    cid, ref, total = result["id"], result["reference"], result["total_php"]

    audit_log(session.get("user_id"), "corporate_invoice_from_intake",
              "corporate_payment", cid,
              f"Created {ref} from intake {intake_id}: "
              f"{result['trainee_count']} trainee(s), PHP {total:,.2f}")
    return jsonify(ok=True, id=cid, reference=ref,
                   trainee_count=result["trainee_count"], total_php=total)


# ── Payment link ─────────────────────────────────────────────────────────────

@admin_bp.route("/admin/corporate/<int:cid>/payment-link", methods=["POST"])
def corporate_issue_link(cid):
    """Mint the public link and create its hosted-checkout session."""
    resp = require("corporate_payments")
    if resp:
        return resp
    invoice = get_corporate_payment(cid=cid)
    if not invoice:
        return jsonify(error="No such invoice."), 404
    if invoice["status"] != "pending":
        return jsonify(error=f"This invoice is {invoice['status']}."), 400

    import paymongo
    if not paymongo.MOCK_GATEWAY and paymongo.environment() == 'test':
        from db import retire_offline_mock_attempt
        safe, reason = retire_offline_mock_attempt(cid, session.get('user_id'))
        if not safe:
            return jsonify(error=reason), 409

    token, version = issue_pay_token(cid)
    if not token:
        return jsonify(error="Could not issue a link for this invoice."), 400
    pay_url = _pay_url(token)

    from corporate_checkout import ensure_checkout_session
    invoice = get_corporate_payment(cid=cid)
    attempt, err = ensure_checkout_session(
        invoice, pay_url + "/return", pay_url, actor_id=session.get("user_id"))
    if err:
        # The link exists but has no payable session. Say both things.
        return jsonify(error=err, url=pay_url, link_version=version), 409

    audit_log(session.get("user_id"), "corporate_link_issued",
              "corporate_payment", cid, f"Issued payment link v{version}")
    # Plaintext shown once; only its hash is stored.
    return jsonify(ok=True, url=pay_url, link_version=version,
                   checkout_url=attempt.get("checkout_url"))


@admin_bp.route("/admin/corporate/<int:cid>/payment-link/revoke", methods=["POST"])
def corporate_revoke_link(cid):
    resp = require("corporate_payments")
    if resp:
        return resp
    ok = revoke_pay_token(cid)
    if ok:
        audit_log(session.get("user_id"), "corporate_link_revoked",
                  "corporate_payment", cid, "Revoked the public payment link")
    return jsonify(ok=ok)


@admin_bp.route("/admin/corporate/<int:cid>/send-link", methods=["POST"])
def corporate_send_link(cid):
    """Admin-initiated send. Never fires automatically on the last approval."""
    resp = require("corporate_payments")
    if resp:
        return resp
    invoice = get_corporate_payment(cid=cid)
    if not invoice:
        return jsonify(error="No such invoice."), 404
    if not invoice.get("intake_id"):
        return jsonify(error="This invoice is not linked to a company intake."), 400
    if not invoice.get("pay_token_hash"):
        return jsonify(error="Issue a payment link first."), 400
    if invoice.get("pay_token_revoked_at"):
        return jsonify(error="The payment link is revoked. Issue a new one."), 400

    # The submitted URL is VERIFIED and then REBUILT from this application's
    # own origin. Checking only the final path segment was not enough:
    # `https://evil.test/pay/corporate/<valid-token>` carries a genuine token,
    # so a token-only check would have emailed the company an attacker's host.
    #
    # Checked BEFORE authorising: authorisation consumes the dedupe key for
    # this link version, so validating afterwards left a dangling queued
    # notification that blocked every later attempt for the same version.
    pay_url = (request.form.get("pay_url") or "").strip()
    if request.form.get('use_saved_link') == '1':
        # A contact edit should not force a new invoice or break a link that
        # the company may already have. Recover only this invoice's current
        # encrypted link, and run the ordinary validation and approval gate.
        notices = [n for n in get_notifications(invoice['intake_id'])
                   if n['kind'] == 'payment_link' and n.get('corporate_payment_id') == cid
                   and n['link_version'] == invoice['link_version']]
        if not notices:
            return jsonify(error='No saved payment link is available. Generate a payment link, then use Send.'), 409
        stored, error = notification_payload(max(notices, key=lambda n: n['id'])['id'])
        if error:
            return jsonify(error=error), 409
        pay_url = (stored or {}).get('pay_url', '')
    canonical, why = validate_pay_url(
        cid, pay_url,
        base_url(), invoice["link_version"])
    if not canonical:
        return jsonify(error=why), 400

    # Eligibility is re-derived server-side with the intake locked, so a roster
    # change since the button rendered cannot authorise this send. The
    # encrypted retry payload is written in the SAME transaction — a crash
    # between the two used to consume the dedupe key while leaving no URL to
    # retry with.
    notif_id, err = authorize_payment_link_send(
        invoice["intake_id"], cid, invoice["link_version"],
        invoice["contact_email"],
        f"Payment link — {invoice['company_name']} invoice {invoice['reference']}",
        session.get("user_id"),
        payload={"pay_url": canonical, "link_version": invoice["link_version"]})
    if err:
        return jsonify(error=err), 409
    pay_url = canonical

    ok, msg = _deliver_payment_link(notif_id, invoice, pay_url)
    return jsonify(ok=ok, message=msg, notification_id=notif_id), (200 if ok else 502)


def _deliver_payment_link(notif_id, invoice, pay_url=""):
    """Attempt delivery under a lease and record the real transport outcome."""
    import email_utils

    attempt_id, attempts, why = begin_attempt(notif_id)
    if not attempt_id:
        return False, why

    # Contact edits lock notification rows and refuse in-flight sends. After
    # claiming, re-read the invoice so a queued send to an old address cannot
    # silently be attributed to that old history row but sent somewhere else.
    current = get_corporate_payment(cid=invoice['id'])
    notice = get_notification(notif_id)
    if (not current or not notice or current['status'] != 'pending'
            or notice['link_version'] != current['link_version']
            or current.get('pay_token_revoked_at')
            or notice['to_email'].strip().lower() != (current.get('contact_email') or '').strip().lower()):
        finish_attempt(notif_id, attempt_id, error='Company email or payment link changed. Send a new notice to the current company email.')
        return False, 'Company email or payment link changed. Send a new notice to the current company email.'
    invoice = current

    try:
        items = get_corporate_items(invoice["id"])
        email_utils.send_company_payment_link(
            invoice["contact_email"], invoice["company_name"],
            invoice["contact_person"], invoice["reference"],
            invoice["amount_centavos"] / 100.0, len(items), pay_url,
            invoice["expires_at"].strftime("%d %b %Y")
            if invoice["expires_at"] else "the date in your email")
    except Exception as e:
        finish_attempt(notif_id, attempt_id, error=f"{type(e).__name__}: {e}")
        current_app.logger.warning("Payment link send failed for %s: %s",
                                   invoice["reference"], e)
        return False, (f"Could not send (attempt {attempts}). The intent is "
                       f"stored — use Retry.")

    transport = email_utils.MAIL_TRANSPORT
    written = finish_attempt(notif_id, attempt_id, transport=transport)
    if written is None:
        return False, ("Handed to the transport, but this attempt no longer "
                       "owned the send. Check the notification state before "
                       "retrying.")

    # payment_link_sent_at is a DISPLAY value, touched only when a real mail
    # server accepted the message — never for a preview or a mock.
    if written == "submitted":
        note_payment_link_submitted(invoice["intake_id"])
        audit_log(session.get("user_id"), "corporate_link_sent",
                  "corporate_payment", invoice["id"],
                  f"Payment link submitted to {invoice['contact_email']}")
        return True, (f"Payment link submitted to the mail server for "
                      f"{invoice['contact_email']}.")
    if written == "previewed":
        return True, (f"Previewed only (MAIL_TRANSPORT=preview) — written to "
                      f"outbox/, NOT sent to {invoice['contact_email']}.")
    return True, f"Mock transport recorded the message for {invoice['contact_email']}."


@admin_bp.route("/admin/notification/<int:notif_id>/retry-link", methods=["POST"])
def corporate_retry_link(notif_id):
    resp = require("corporate_payments")
    if resp:
        return resp
    n = get_notification(notif_id)
    if not n or n["kind"] != "payment_link":
        return jsonify(error="No such payment-link notification."), 404
    invoice = get_corporate_payment(cid=n["corporate_payment_id"])
    if not invoice:
        return jsonify(error="The invoice no longer exists."), 404
    if n['to_email'].strip().lower() != (invoice.get('contact_email') or '').strip().lower():
        return jsonify(error='This notice belongs to the previous company email. Use Send payment link for the current address.'), 409
    stored, perr = notification_payload(notif_id)
    if perr:
        # Actionable, not silent: an unreadable payload is NOT the same as an
        # absent one, and must not be answered with "just issue a new link".
        return jsonify(error=perr, recovery="payload_unreadable"), 409
    pay_url = (stored or {}).get("pay_url", "")
    if not pay_url:
        return jsonify(error="This notification has no stored payment URL. "
                             "Issue a link and send again."), 400
    # Re-validated on every retry: the link may have been revoked or replaced
    # since the intent was authorised.
    canonical, why = validate_pay_url(invoice["id"], pay_url, base_url(),
                                      stored.get("link_version"))
    if not canonical:
        return jsonify(error=f"{why} The stored link is no longer usable."), 409

    ok, msg = _deliver_payment_link(notif_id, invoice, canonical)
    return jsonify(ok=ok, message=msg), (200 if ok else 502)


# ── Attempts, attention, unresolved events ───────────────────────────────────

@admin_bp.route("/admin/corporate/<int:cid>/attempts")
def corporate_attempts(cid):
    """Every attempt for one invoice, plus delivery and attention state."""
    resp = require("corporate_payments")
    if resp:
        return resp
    invoice = get_corporate_payment(cid=cid)
    if not invoice:
        return jsonify(error="No such invoice."), 404

    notices = []
    if invoice.get("intake_id"):
        notices = [n for n in get_notifications(invoice["intake_id"])
                   if n["kind"] == "payment_link" and n.get('corporate_payment_id') == cid]

    return jsonify(
        invoice={"id": invoice["id"], "reference": invoice["reference"],
                 "status": invoice["status"],
                 # Issuing/revoking only makes sense while money is still
                 # owed. Recovery state below is returned for EVERY status:
                 # a paid or cancelled invoice with a stuck attempt or an
                 # unapplied payment is exactly when it is needed.
                 "collectable": invoice["status"] == "pending",
                 "amount_php": invoice["amount_centavos"] / 100.0,
                 "link_active": bool(invoice.get("pay_token_hash")
                                     and not invoice.get("pay_token_revoked_at")),
                 "link_version": invoice.get("link_version"),
                 "intake_id": invoice.get("intake_id"),
                 "needs_attention": invoice.get("needs_attention_at") is not None,
                 "attention_reason": invoice.get("attention_reason")},
        attempts=[{
            "attempt_ref": a["attempt_ref"],
            "status": a["status"],
            "environment": a["environment"],
            "session_id": a["checkout_session_id"],
            "intent_id": a["payment_intent_id"],
            "paid_payment_id": a["paid_payment_id"],
            "created_at": a["created_at"].isoformat() if a["created_at"] else None,
            "settled_at": a["settled_at"].isoformat() if a["settled_at"] else None,
            "expired_at": a["expired_at"].isoformat() if a["expired_at"] else None,
            "confirmed": a["settlement_confirmed_at"] is not None,
            "key_expires_at": a["idempotency_expires_at"].isoformat()
                if a["idempotency_expires_at"] else None,
            "owned_until": a["creation_lease_until"].isoformat()
                if a["creation_lease_until"] else None,
            "error": a["last_error"],
            # Which resolution routes are actually available, decided here so
            # the UI cannot offer one the server would refuse.
            "resolvable": a["status"] in OPEN_ATTEMPT_STATES,
            "can_retrieve": bool(a["checkout_session_id"]),
            "can_replay": (not a["checkout_session_id"]
                           and a["idempotency_expires_at"] is not None
                           and a["idempotency_expires_at"] > datetime.now()),
        } for a in get_attempts(cid)],
        events=[{"id": e["id"], "source": e["source"],
                 "event_type": e["event_type"], "reason": e["reason"],
                 "session_id": e["checkout_session_id"],
                 "payment_id": e["payment_id"],
                 "livemode": e["livemode"],
                 "amount_php": (e["amount_centavos"] / 100.0)
                     if e["amount_centavos"] else None,
                 "currency": e["currency"],
                 "received_at": e["received_at"].isoformat()
                     if e["received_at"] else None}
                for e in unresolved_events_for_payment(cid, invoice["reference"])],
        notifications=[{
            "id": n["id"], "status": n["status"], "attempts": n["attempts"],
            "to_email": n["to_email"], "transport": n["transport"],
            "current_recipient": (n['to_email'].strip().lower() == (invoice.get('contact_email') or '').strip().lower()),
            "error": n["last_error"],
            "sent_at": n["sent_at"].isoformat() if n["sent_at"] else None,
        } for n in notices])


@admin_bp.route("/admin/corporate/attempt/<attempt_ref>/resolve", methods=["POST"])
def corporate_resolve_attempt(attempt_ref):
    """Close out a stuck attempt — only on evidence.

    Three routes, matching how the truth can actually be learned:

      retrieve  ask the gateway about a session we DO have an id for
      replay    re-send the stored request under its original idempotency key,
                allowed only inside the 24-hour retention window
      verified  an operator checked the PayMongo dashboard and records what
                they saw

    The replacement guard is held until one of these succeeds. An operator
    assertion with no stated evidence is refused.
    """
    resp = require("corporate_payments")
    if resp:
        return resp

    import paymongo

    conn = get_db(); cur = dict_cur(conn)
    cur.execute("SELECT * FROM corporate_payment_attempts WHERE attempt_ref = %s",
                (attempt_ref,))
    row = cur.fetchone()
    cur.close(); conn.close()
    if not row:
        return jsonify(error="No such attempt."), 404
    attempt = dict(row)
    if attempt["status"] not in OPEN_ATTEMPT_STATES:
        return jsonify(error=f"This attempt is already {attempt['status']}."), 400

    # Creation ownership. While the lease holds, the original request may
    # still be in flight: replaying its key would race a live call, and
    # releasing the guard could let a second payable session be created
    # alongside one that is about to exist. Manual recovery waits.
    lease = attempt.get("creation_lease_until")
    if lease is not None and lease > datetime.now():
        return jsonify(error=(
            "This attempt is still owned by an in-flight creation request "
            f"(until {lease:%H:%M:%S}). Wait for it to finish or lapse before "
            "recovering it manually.")), 409

    mode = (request.form.get("mode") or "").strip()
    note = (request.form.get("evidence") or "").strip()
    actor = session.get("user_id")

    if mode == "retrieve":
        if not attempt["checkout_session_id"]:
            return jsonify(error="This attempt has no session id to retrieve."), 400
        try:
            sess = paymongo.retrieve_checkout_session(attempt["checkout_session_id"])
        except Exception as e:
            return jsonify(error=f"The gateway could not be queried: {e}"), 502
        if paymongo.paid_payment(sess):
            from corporate_checkout import validate_and_settle, SettlementRefused
            try:
                settled, msg = validate_and_settle(sess, "resolve", actor)
            except SettlementRefused as e:
                return jsonify(error=str(e)), 409
            audit_log(actor, "corporate_attempt_resolved", "corporate_payment",
                      attempt["corporate_payment_id"],
                      f"{attempt_ref}: retrieved session showed payment. {msg}")
            return jsonify(ok=True, settled=settled, message=msg)

        from corporate_checkout import expire_attempt_remotely
        ok, msg = expire_attempt_remotely(attempt, actor)
        if ok:
            resolve_attempt(attempt_ref, actor, "session_retrieved",
                            f"session status={sess.get('status')}, no paid payment",
                            "expired remotely", msg)
            audit_log(actor, "corporate_attempt_resolved", "corporate_payment",
                      attempt["corporate_payment_id"],
                      f"{attempt_ref}: retrieved, unpaid, closed remotely.")
        return jsonify(ok=ok, message=msg)

    if mode == "replay":
        if attempt["checkout_session_id"]:
            return jsonify(error="This attempt already has a session; "
                                 "use Retrieve."), 400
        if attempt["idempotency_expires_at"] and \
                attempt["idempotency_expires_at"] <= datetime.now():
            return jsonify(error=(
                "The idempotency key has expired. Replaying it now would create "
                "a NEW session rather than recover the original — check the "
                "PayMongo dashboard and use Record verified outcome.")), 400
        try:
            payload = _json.loads(attempt["request_payload"] or "{}")
            sess = paymongo.create_checkout_session(
                **outbound_args(payload),
                idempotency_key=attempt["idempotency_key"])
        except Exception as e:
            return jsonify(error=f"Replay failed: {e}"), 502
        record_session(attempt_ref, sess["id"], sess.get("checkout_url"),
                       sess.get("payment_intent_id"))
        audit_log(actor, "corporate_attempt_replayed", "corporate_payment",
                  attempt["corporate_payment_id"],
                  f"Replayed {attempt_ref} under its original key -> "
                  f"session {sess['id']}")
        return jsonify(ok=True, session_id=sess["id"],
                       message=f"Recovered session {sess['id']}. The attempt "
                               f"is active again.")

    if mode == "verified":
        # This branch does NOT establish gateway state. It records that a named
        # operator looked and says what they saw. Text length is a floor on
        # carelessness, not evidence — so the outcome is stored and labelled as
        # MANUAL VERIFICATION, and Retrieve/Replay are preferred wherever they
        # are available.
        if attempt["checkout_session_id"]:
            return jsonify(error=(
                "This attempt has a session id — use Retrieve, which asks the "
                "gateway directly, instead of recording a manual outcome.")), 400
        if len(note) < 10:
            return jsonify(error=(
                "Describe what you verified — which reference you checked in "
                "the PayMongo dashboard and what it showed. The guard is not "
                "released on an unexplained assertion.")), 400
        outcome = (request.form.get("outcome") or "").strip()
        if outcome not in ("no_session", "session_closed"):
            return jsonify(error="State the verified outcome."), 400
        pid = resolve_attempt(attempt_ref, actor, "manual_verification", note,
                              f"recorded outcome={outcome}",
                              "attempt closed on operator statement")
        if pid is None:
            return jsonify(error="The attempt was no longer open."), 409
        audit_log(actor, "corporate_attempt_manually_resolved",
                  "corporate_payment", pid,
                  f"{attempt_ref} closed on MANUAL VERIFICATION ({outcome}). "
                  f"Not confirmed by the gateway. Operator statement: {note}")
        return jsonify(ok=True, verification="manual",
                       message=("Recorded as manual verification — the gateway "
                                "was not queried. The attempt is closed."))

    return jsonify(error="Choose Retrieve, Replay, or Record verified outcome."), 400


@admin_bp.route("/admin/corporate/attention")
def corporate_attention():
    """Everything money-related that still needs a human."""
    resp = require("corporate_payments")
    if resp:
        return resp
    return jsonify(
        payments=[{"id": p["id"], "reference": p["reference"],
                   "status": p["status"], "company": p["company_name"],
                   "reason": p["attention_reason"],
                   "since": p["needs_attention_at"].isoformat()
                       if p["needs_attention_at"] else None}
                  for p in payments_needing_attention()],
        events=[{"id": e["id"], "source": e["source"],
                 "event_type": e["event_type"], "reason": e["reason"],
                 "session_id": e["checkout_session_id"],
                 "payment_id": e["payment_id"],
                 "amount_php": (e["amount_centavos"] / 100.0)
                     if e["amount_centavos"] else None,
                 "received_at": e["received_at"].isoformat()
                     if e["received_at"] else None}
                for e in unresolved_events()])


@admin_bp.route("/admin/corporate/<int:cid>/attention/clear", methods=["POST"])
def corporate_clear_attention(cid):
    resp = require("corporate_payments")
    if resp:
        return resp
    note = (request.form.get("note") or "").strip()
    if len(note) < 5:
        return jsonify(error="Say how it was resolved."), 400
    clear_attention(cid)
    audit_log(session.get("user_id"), "corporate_attention_cleared",
              "corporate_payment", cid, note)
    return jsonify(ok=True)


@admin_bp.route("/admin/corporate/event/<int:event_id>")
def corporate_inspect_event(event_id):
    """One unresolved event, raw payload included.

    The payload is gateway bookkeeping — session, amount, currency, livemode.
    It is shown so an operator can decide what actually happened before
    recording a resolution; resolving without reading it is guesswork.
    """
    resp = require("corporate_payments")
    if resp:
        return resp
    e = unresolved_event(event_id)
    if not e:
        return jsonify(error="No such event."), 404
    raw = e["raw_event"]
    if isinstance(raw, str):
        try:
            raw = _json.loads(raw)
        except ValueError:
            pass
    return jsonify(
        id=e["id"], source=e["source"], event_type=e["event_type"],
        reason=e["reason"], session_id=e["checkout_session_id"],
        payment_id=e["payment_id"], reference_hint=e["reference_hint"],
        livemode=e["livemode"], currency=e["currency"],
        amount_php=(e["amount_centavos"] / 100.0) if e["amount_centavos"] else None,
        received_at=e["received_at"].isoformat() if e["received_at"] else None,
        resolved_at=e["resolved_at"].isoformat() if e["resolved_at"] else None,
        resolution_note=e["resolution_note"],
        raw_event=raw)


@admin_bp.route("/admin/corporate/event/<int:event_id>/resolve", methods=["POST"])
def corporate_resolve_event(event_id):
    resp = require("corporate_payments")
    if resp:
        return resp
    note = (request.form.get("note") or "").strip()
    if len(note) < 5:
        return jsonify(error="Say how it was resolved."), 400
    ok = resolve_event(event_id, session.get("user_id"), note)
    if ok:
        audit_log(session.get("user_id"), "unresolved_event_resolved",
                  "payment_event", event_id, note)
    return jsonify(ok=ok)
