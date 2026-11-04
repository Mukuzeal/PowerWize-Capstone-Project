"""Corporate bulk payments — one invoice for several approved trainees.

Open to Admin, Super User and Secretary (capability `corporate_payments`).

Account creation is untouched: this screen can only pick from trainees who
already exist and are still unpaid, i.e. people who went through the public
form -> admin review -> emailed token -> /create-account/<token> flow. There is
no signup route here and no way to create a user from this file.

Every amount handed to PayMongo is integer centavos computed on the server
from the stored record; nothing the browser sends is trusted as a price.
"""
from datetime import datetime, timedelta

from flask import (request, render_template, redirect, session, jsonify, flash,
                   current_app, url_for)

from db import (audit_log, get_unpaid_trainees, create_corporate_payment,
                get_corporate_payments, get_corporate_payment, get_corporate_items,
                add_corporate_event, get_corporate_events, set_corporate_intent,
                mark_corporate_paid, cancel_corporate_payment,
                expire_stale_corporate_payments, save_corporate_receipt,
                corporate_price_edit_state, update_corporate_price,
                update_corporate_email)
from permissions import require
from pricing import calculate_fee, program_option_label, to_centavos
import paymongo
from utils import base_url

from . import admin_bp

# How long a generated payment link/QR stays valid, unless staff pick otherwise.
DEFAULT_EXPIRY_HOURS = 24
MAX_EXPIRY_HOURS     = 24 * 14

STATUSES = ("pending", "paid", "expired", "cancelled")


def _price_for(trainee, training_type=None):
    """List price for one trainee, from the published program pricing.

    `training_type` overrides what the registration said, so staff can bill a
    trainee for the program the company actually wants them in. Falls back to
    the registration's own form_type/training_type otherwise.
    """
    form_type = training_type or trainee.get("form_type")
    fee = calculate_fee(form_type, trainee.get("reg_training_type"))
    if fee is None:
        # No published price matches this combination — surfaced as a zero line
        # the staff member has to resolve rather than a silently invented figure.
        return {"base": 0, "vat": 0, "total": 0,
                "label": "No published price for this program", "has_vat": False}
    return fee


def _programs_for(trainee):
    """The program options offered for one trainee in the picker. Their own
    registration first, then the other paid programs, so the common case is
    one click and a switch is still possible."""
    own = trainee.get("form_type")
    order = ["training", "cea_training", "cem_renewal", "cea_renewal", "gemp_lgu", "gemp_oge"]
    if own in order:
        order.remove(own)
        order.insert(0, own)
    out = []
    for code in order:
        fee = calculate_fee(code, trainee.get("reg_training_type"))
        if fee:
            # Named per program: calculate_fee's own label says "Training" for
            # both CEA and CEM, which is ambiguous in a list of options.
            out.append({"code": code,
                        "label": program_option_label(code, trainee.get("reg_training_type")),
                        "total": fee["total"]})
    return out


# ── Dashboard section ─────────────────────────────────────────────────────────

def dashboard_context():
    """Everything the admin console's Corporate Payments pane renders.

    This screen lives inside /admin as a hash-routed section like every other
    pane, so the data is shaped here (next to the feature) and handed to
    admin/dashboard.py rather than served from a page of its own.
    """
    expire_stale_corporate_payments()
    records = get_corporate_payments()
    totals = {st: 0 for st in STATUSES}
    for r in records:
        if r["status"] in totals:
            totals[r["status"]] += 1

    trainees = get_unpaid_trainees()
    for t in trainees:
        t["programs"] = _programs_for(t)
        t["default_price"] = _price_for(t)["total"]

    return {
        "corp_records":  records,
        "corp_totals":   totals,
        "corp_statuses": STATUSES,
        "corp_trainees": trainees,
        "corp_default_expiry_hours": DEFAULT_EXPIRY_HOURS,
    }


@admin_bp.route("/admin/corporate")
def corporate_list():
    """Kept so existing links and bookmarks still resolve; the screen itself is
    now a pane of the console."""
    resp = require("corporate_payments")
    if resp:
        return resp
    return redirect("/admin#corporate")


# ── Create ────────────────────────────────────────────────────────────────────

@admin_bp.route("/admin/corporate/new", methods=["GET", "POST"])
def corporate_new():
    resp = require("corporate_payments")
    if resp:
        return resp

    if request.method == "GET":
        # The create form is a modal on the console pane, not a page.
        return redirect("/admin#corporate")

    trainees = get_unpaid_trainees()
    for t in trainees:
        t["programs"] = _programs_for(t)
        t["default_price"] = _price_for(t)["total"]

    f = request.form
    company_name   = f.get("company_name", "").strip()
    contact_person = f.get("contact_person", "").strip()
    contact_email  = f.get("contact_email", "").strip().lower()
    contact_number = f.get("contact_number", "").strip()
    selected       = f.getlist("trainee_id")
    override_raw   = f.get("custom_total", "").strip()
    override_note  = f.get("override_note", "").strip()

    errors = []
    if not company_name:
        errors.append("Company name is required.")
    if not contact_person:
        errors.append("Contact person is required.")
    if not selected:
        errors.append("Select at least one trainee.")

    try:
        expiry_hours = int(f.get("expiry_hours", DEFAULT_EXPIRY_HOURS))
    except ValueError:
        expiry_hours = DEFAULT_EXPIRY_HOURS
    if not 1 <= expiry_hours <= MAX_EXPIRY_HOURS:
        errors.append(f"Expiry must be between 1 and {MAX_EXPIRY_HOURS} hours.")

    # Prices come from the pricing table keyed by the trainee the staff member
    # picked — never from a posted amount.
    by_id = {str(t["id"]): t for t in trainees}
    items, list_total = [], 0.0
    for sid in selected:
        t = by_id.get(sid)
        if not t:
            errors.append("One of the selected trainees is no longer unpaid — reload and try again.")
            continue
        chosen = f.get(f"program_{sid}", "").strip() or t.get("form_type")
        fee = _price_for(t, chosen)
        if not fee["total"]:
            errors.append(f"No published price for {t['fname']} {t['lname']}'s selected program.")
            continue
        items.append({"user_id": t["id"], "training_type": chosen,
                      "form_type": t.get("form_type"), "price_php": fee["total"],
                      "price_label": program_option_label(
                          chosen, t.get("reg_training_type"))})
        list_total += fee["total"]

    custom_total = None
    if override_raw:
        try:
            custom_total = round(float(override_raw.replace(",", "")), 2)
        except ValueError:
            errors.append("Custom total must be a number.")
        else:
            if custom_total <= 0:
                errors.append("Custom total must be greater than zero.")
            if not override_note:
                errors.append("A note is required when overriding the computed total.")

    if errors:
        # The modal posts over XHR so it can show these inline and keep what
        # the staff member already typed.
        return jsonify(errors=errors), 400

    amount_php      = custom_total if custom_total is not None else round(list_total, 2)
    amount_centavos = to_centavos(amount_php)
    expires_at      = datetime.now() + timedelta(hours=expiry_hours)

    cid, reference = create_corporate_payment(
        company_name, contact_person, contact_email, contact_number,
        items, round(list_total, 2), custom_total, override_note,
        amount_centavos, expires_at, session.get("user_id"))

    detail = (f"Created invoice {reference} for {company_name}: "
              f"{len(items)} trainee(s), list total PHP {list_total:,.2f}")
    if custom_total is not None:
        detail += f", charged PHP {custom_total:,.2f} — {override_note}"
    add_corporate_event(cid, session.get("user_id"), "created", detail)
    if custom_total is not None:
        add_corporate_event(cid, session.get("user_id"), "price_override",
                            f"List total PHP {list_total:,.2f} overridden to "
                            f"PHP {custom_total:,.2f}. Reason: {override_note}")
    audit_log(session.get("user_id"), "corporate_payment_created", "corporate_payment",
              cid, detail)
    flash(f"Corporate invoice {reference} created.", "success")
    return jsonify(ok=True, id=cid, reference=reference)


# ── Detail ────────────────────────────────────────────────────────────────────

@admin_bp.route("/admin/corporate/<int:cid>")
def corporate_detail(cid):
    resp = require("corporate_payments")
    if resp:
        return resp
    return redirect("/admin#corporate")


@admin_bp.route("/admin/corporate/<int:cid>/panel")
def corporate_panel(cid):
    """Server-rendered body for the record's modal.

    Returned as an HTML fragment rather than JSON: the panel is mostly static
    markup (summary, trainee table, audit trail), and rendering it in Jinja
    keeps it consistent with the rest of the console instead of duplicating
    the layout as string concatenation in JavaScript.
    """
    resp = require("corporate_payments")
    if resp:
        return resp
    expire_stale_corporate_payments()
    rec = get_corporate_payment(cid=cid)
    if not rec:
        return "<p class=\"empty\">That corporate payment no longer exists.</p>", 404
    price_editable, price_edit_reason = corporate_price_edit_state(cid)
    return render_template("admin/_corporate_panel.html",
                           rec=rec,
                           price_editable=price_editable, price_edit_reason=price_edit_reason,
                           items=get_corporate_items(cid),
                           events=get_corporate_events(cid))


@admin_bp.route('/admin/corporate/<int:cid>/email', methods=['POST'])
def corporate_edit_email(cid):
    resp = require('corporate_payments')
    if resp:
        return resp
    if 'expected_email' not in request.form:
        return jsonify(error='Reload the invoice before editing its company email.'), 400
    row, error, status = update_corporate_email(cid, request.form.get('contact_email'),
        request.form.get('expected_email'), session.get('user_id'))
    if error:
        return jsonify(error=error), status
    return jsonify(ok=True, contact_email=row['contact_email'],
        message='Company email saved. No email was sent. Use Send payment link when ready.')


@admin_bp.route('/admin/corporate/<int:cid>/price', methods=['POST'])
def corporate_override_price(cid):
    resp = require('corporate_payments')
    if resp:
        return resp
    expected = request.form.get('expected_centavos', '').strip()
    if not expected.isascii() or not expected.isdigit() or len(expected) > 15:
        return jsonify(error='Reload the invoice to get its current price before saving.'), 400
    row, error, status = update_corporate_price(cid, request.form.get('custom_total', ''),
        request.form.get('override_note', ''), session.get('user_id'), int(expected))
    if error:
        return jsonify(error=error), status
    return jsonify(ok=True, id=cid, amount_centavos=row['amount_centavos'],
                   custom_total_php=str(row['custom_total_php']) if row['custom_total_php'] is not None else None,
                   message='Invoice total updated. Generate the payment link when the amount is final.')


@admin_bp.route("/admin/corporate/<int:cid>/cancel", methods=["POST"])
def corporate_cancel(cid):
    resp = require("corporate_payments")
    if resp:
        return resp
    rec = get_corporate_payment(cid=cid)
    if not rec:
        flash("That corporate payment no longer exists.", "error")
        return redirect("/admin#corporate")
    if cancel_corporate_payment(cid):
        reason = request.form.get("reason", "").strip()
        add_corporate_event(cid, session.get("user_id"), "cancelled",
                            reason or "Cancelled by staff.")
        audit_log(session.get("user_id"), "corporate_payment_cancelled",
                  "corporate_payment", cid, f"Cancelled invoice {rec['reference']}")
        flash("Invoice cancelled.", "warning")
    else:
        flash("Only a pending invoice can be cancelled.", "error")
    return redirect("/admin#corporate")


# ── Payment: shared guards ────────────────────────────────────────────────────

def _payable(cid):
    """(record, error_json) — the record if it can still be charged."""
    rec = get_corporate_payment(cid=cid)
    if not rec:
        return None, (jsonify(error="Invoice not found"), 404)
    if rec["status"] != "pending":
        return None, (jsonify(error=f"This invoice is {rec['status']}."), 400)
    if rec["expires_at"] and rec["expires_at"] < datetime.now():
        expire_stale_corporate_payments()
        return None, (jsonify(error="This invoice has expired."), 400)
    return rec, None


def _intent_metadata(rec):
    """What PayMongo echoes back to us on the webhook. `reference` is the tie
    between a gateway callback and this record."""
    return {"reference": rec["reference"], "kind": "corporate",
            "company": rec["company_name"][:100]}


def _description(rec):
    return f"EnergyWize corporate training invoice {rec['reference']} — {rec['company_name']}"


# ── Payment: RETIRED ──────────────────────────────────────────────────────────
#
# The corporate card and QRPH entry points were removed. They accepted a raw
# PAN and CVC into this server (corporate_card_method forwarded them to
# PayMongo), which put the application in scope for card data it never needed
# to touch — and the operator-facing text claimed the opposite.
#
# Corporate invoices are now settled through PayMongo-hosted checkout:
# admin/payments_ops.py issues the link, corporate_public_bp.py serves the
# payer, and corporate_checkout.py validates every entry point before
# settlement. No card details reach this host.
#
# The INDIVIDUAL trainee flow in payment_bp.py is untouched and still uses the
# older card path. That is a separate migration and is NOT claimed here.


# ── Settlement ────────────────────────────────────────────────────────────────

def settle_corporate_payment(reference=None, paymongo_id=None, cid=None, actor_id=None,
                             payment_id=None, method=None):
    """Confirm a corporate invoice exactly once, whoever reports it first.

    mark_corporate_paid() does the record flip and every trainee's
    payment_status in one transaction and only matches a still-pending row, so
    a duplicate webhook delivery, a poll and a card return racing each other
    all collapse into a single settlement. Everything after it — the receipt
    anchor, the email — runs only for the caller that won.
    """
    rec = mark_corporate_paid(reference=reference, paymongo_id=paymongo_id, cid=cid,
                              confirmed_payment_id=payment_id, method=method)
    if not rec:
        return None
    _anchor_receipt(rec, actor_id)
    _notify_creator(rec)
    audit_log(actor_id, "corporate_payment_paid", "corporate_payment", rec["id"],
              f"Invoice {rec['reference']} paid "
              f"(PHP {rec['amount_centavos'] / 100:,.2f}, {rec['company_name']})")
    return rec


def _anchor_receipt(rec, actor_id=None):
    """Serialize anchoring per invoice, including admin retries."""
    from db import get_db
    conn = None; cur = None
    try:
        conn = get_db(); cur = conn.cursor()
        cur.execute('SELECT pg_try_advisory_lock(%s,%s)', (1506418001, rec['id']))
        owned = cur.fetchone()[0]
        conn.commit()
        if not owned:
            current_app.logger.info('Corporate receipt anchor already running for %s', rec['reference'])
            return False
        fresh = get_corporate_payment(cid=rec['id'])
        if not fresh or fresh['status'] != 'paid':
            return False
        if fresh.get('tx_hash'):
            return True
        return _write_corporate_anchor(fresh, actor_id)
    except Exception as e:
        current_app.logger.warning('Corporate invoice %s paid but receipt anchoring could not run: %s', rec.get('reference'), type(e).__name__)
        return False
    finally:
        # Closing the session releases its advisory lock even on RPC failure.
        if cur:
            cur.close()
        if conn:
            conn.close()


def _write_corporate_anchor(rec, actor_id=None):
    """Best-effort Polygon anchor, exactly like payments and certificates: the
    payment is valid whether or not the chain write lands, the failure is
    logged rather than swallowed, and the record shows Off-chain with a
    re-anchor action until it succeeds."""
    try:
        from blockchain import (generate_receipt_id, compute_anchor,
                                store_hash_on_chain, ANCHOR_VERSION)
        from qr_gen import generate_receipt_qr

        receipt_id = rec.get("receipt_id") or generate_receipt_id()
        record = {
            "receipt_id":      receipt_id,
            "reference":       rec["reference"],
            "company_name":    rec["company_name"],
            "paymongo_id":     rec["paymongo_id"],
            "amount_centavos": rec["amount_centavos"],
            "status":          "paid",
        }
        receipt_hash = compute_anchor("corporate_payment", record)
        # A receipt exists even if Polygon is unavailable. Its QR looks up the
        # stored transaction later, so retrying an anchor keeps the same ID.
        qr_path = generate_receipt_qr(receipt_id, None)
        save_corporate_receipt(rec["id"], receipt_id, receipt_hash,
                               None, qr_path, ANCHOR_VERSION)
        import os
        if paymongo.environment() == 'test' and os.getenv('POLYGON_NETWORK', 'amoy') != 'amoy':
            raise ValueError('PayMongo sandbox receipts require Polygon Amoy, not mainnet.')
        chain = store_hash_on_chain(receipt_hash)
        if not chain.get('confirmed'):
            raise RuntimeError('Polygon did not confirm a successful anchoring transaction.')
        save_corporate_receipt(rec["id"], receipt_id, receipt_hash,
                               chain["tx_hash"], qr_path, ANCHOR_VERSION)
        add_corporate_event(rec["id"], actor_id, "anchored",
                            f"Receipt {receipt_id} anchored on-chain ({chain['tx_hash']}).")
        return True
    except Exception as e:
        current_app.logger.warning(
            "Corporate invoice %s paid but chain write failed: %s: %s",
            rec.get("reference"), type(e).__name__, e)
        add_corporate_event(rec["id"], actor_id, "anchor_failed",
                            f"Blockchain anchor failed ({type(e).__name__}). "
                            f"Receipt is Off-chain — use Re-anchor to retry.")
        return False


@admin_bp.route("/admin/corporate/<int:cid>/reanchor", methods=["POST"])
def corporate_reanchor(cid):
    resp = require("corporate_payments")
    if resp:
        return resp
    rec = get_corporate_payment(cid=cid)
    if not rec:
        flash("That corporate payment no longer exists.", "error")
        return redirect("/admin#corporate")
    if rec.get("tx_hash"):
        flash("This receipt is already anchored on-chain.", "success")
    elif rec["status"] != "paid":
        flash("Only a paid invoice has a receipt to anchor.", "error")
    elif _anchor_receipt(rec, session.get("user_id")):
        flash("Receipt successfully anchored on-chain.", "success")
    else:
        flash("Re-anchor attempt failed again — still Off-chain.", "warning")
    return redirect("/admin#corporate")


def _notify_creator(rec):
    """Tell the staff member who raised the invoice that it settled — by email
    via the existing mailer, and in-app through the record's audit trail,
    which is the notification surface this app has."""
    items = get_corporate_items(rec["id"])
    add_corporate_event(rec["id"], rec.get("created_by"), "notified",
                        f"Confirmation sent to the staff member who created "
                        f"invoice {rec['reference']}.")
    try:
        from db import get_db, dict_cur
        conn = get_db(); cur = dict_cur(conn)
        cur.execute("SELECT fname, lname, email FROM users WHERE id=%s", (rec.get("created_by"),))
        staff = cur.fetchone()
        cur.close(); conn.close()
        if not staff or not staff.get("email"):
            return
        from email_utils import send_corporate_payment_confirmation
        send_corporate_payment_confirmation(
            staff["email"], f"{staff['fname']} {staff['lname']}".strip(), rec, items,
            base_url())
    except Exception as e:
        current_app.logger.warning(
            "Corporate invoice %s paid but the staff notification failed: %s: %s",
            rec.get("reference"), type(e).__name__, e)
