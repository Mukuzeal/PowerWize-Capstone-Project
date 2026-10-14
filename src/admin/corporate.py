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
                expire_stale_corporate_payments, save_corporate_receipt)
from permissions import require
from pricing import calculate_fee, to_centavos
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
            out.append({"code": code, "label": fee["label"], "total": fee["total"]})
    return out


# ── List ──────────────────────────────────────────────────────────────────────

@admin_bp.route("/admin/corporate")
def corporate_list():
    resp = require("corporate_payments")
    if resp:
        return resp
    expire_stale_corporate_payments()
    status = request.args.get("status", "").strip()
    q      = request.args.get("q", "").strip()
    if status not in STATUSES:
        status = ""
    records = get_corporate_payments(status=status or None, q=q or None)
    totals = {s: 0 for s in STATUSES}
    for r in get_corporate_payments():
        if r["status"] in totals:
            totals[r["status"]] += 1
    return render_template("admin/corporate_list.html",
                           records=records, status=status, q=q,
                           statuses=STATUSES, totals=totals)


# ── Create ────────────────────────────────────────────────────────────────────

@admin_bp.route("/admin/corporate/new", methods=["GET", "POST"])
def corporate_new():
    resp = require("corporate_payments")
    if resp:
        return resp

    trainees = get_unpaid_trainees()
    for t in trainees:
        t["programs"] = _programs_for(t)
        t["default_price"] = _price_for(t)["total"]

    if request.method == "GET":
        return render_template("admin/corporate_form.html", trainees=trainees,
                               errors=[], form_data=None,
                               default_expiry_hours=DEFAULT_EXPIRY_HOURS)

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
                      "price_label": fee["label"]})
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
        return render_template("admin/corporate_form.html", trainees=trainees,
                               errors=errors, form_data=f,
                               default_expiry_hours=DEFAULT_EXPIRY_HOURS), 400

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
    return redirect(url_for("admin.corporate_detail", cid=cid))


# ── Detail ────────────────────────────────────────────────────────────────────

@admin_bp.route("/admin/corporate/<int:cid>")
def corporate_detail(cid):
    resp = require("corporate_payments")
    if resp:
        return resp
    expire_stale_corporate_payments()
    rec = get_corporate_payment(cid=cid)
    if not rec:
        flash("That corporate payment no longer exists.", "error")
        return redirect(url_for("admin.corporate_list"))
    return render_template("admin/corporate_detail.html",
                           rec=rec,
                           items=get_corporate_items(cid),
                           events=get_corporate_events(cid))


@admin_bp.route("/admin/corporate/<int:cid>/cancel", methods=["POST"])
def corporate_cancel(cid):
    resp = require("corporate_payments")
    if resp:
        return resp
    rec = get_corporate_payment(cid=cid)
    if not rec:
        flash("That corporate payment no longer exists.", "error")
        return redirect(url_for("admin.corporate_list"))
    if cancel_corporate_payment(cid):
        reason = request.form.get("reason", "").strip()
        add_corporate_event(cid, session.get("user_id"), "cancelled",
                            reason or "Cancelled by staff.")
        audit_log(session.get("user_id"), "corporate_payment_cancelled",
                  "corporate_payment", cid, f"Cancelled invoice {rec['reference']}")
        flash("Invoice cancelled.", "warning")
    else:
        flash("Only a pending invoice can be cancelled.", "error")
    return redirect(url_for("admin.corporate_detail", cid=cid))


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


# ── Payment: QRPH ─────────────────────────────────────────────────────────────

@admin_bp.route("/admin/corporate/<int:cid>/pay/qrph", methods=["POST"])
def corporate_pay_qrph(cid):
    resp = require("corporate_payments")
    if resp:
        return resp
    rec, err = _payable(cid)
    if err:
        return err
    try:
        result = paymongo.create_qrph_intent(
            None, _description(rec), base_url().rstrip("/") + f"/admin/corporate/{cid}",
            metadata=_intent_metadata(rec), amount_centavos=rec["amount_centavos"])
        set_corporate_intent(cid, "qrph", result["pi_id"])
        add_corporate_event(cid, session.get("user_id"), "qrph_generated",
                            f"QRPH code generated for PHP {rec['amount_centavos'] / 100:,.2f}")
        return jsonify({"pi_id": result["pi_id"], "qr_image": result.get("qr_image"),
                        "test_url": result.get("test_url"),
                        "expires_at": rec["expires_at"].isoformat()})
    except Exception as e:
        current_app.logger.warning("Corporate QRPH failed for %s: %s", cid, e)
        return jsonify(error=str(e)), 500


@admin_bp.route("/admin/corporate/<int:cid>/poll")
def corporate_poll(cid):
    resp = require("corporate_payments")
    if resp:
        return resp
    rec = get_corporate_payment(cid=cid)
    if not rec:
        return jsonify(status="missing"), 404
    if rec["status"] == "paid":
        return jsonify(status="paid")
    if rec["status"] != "pending":
        return jsonify(status=rec["status"])
    if not rec["paymongo_id"]:
        return jsonify(status="awaiting_intent")
    try:
        pi = paymongo.retrieve_payment_intent(rec["paymongo_id"])
    except Exception as e:
        return jsonify(status="error", detail=str(e)), 500
    if pi["status"] == "succeeded":
        _settle(cid, rec["paymongo_id"])
        return jsonify(status="paid")
    return jsonify(status=pi["status"])


# ── Payment: card ─────────────────────────────────────────────────────────────

@admin_bp.route("/admin/corporate/<int:cid>/pay/card/initiate", methods=["POST"])
def corporate_card_initiate(cid):
    resp = require("corporate_payments")
    if resp:
        return resp
    rec, err = _payable(cid)
    if err:
        return err
    try:
        pi = paymongo.create_payment_intent(
            None, _description(rec), metadata=_intent_metadata(rec),
            amount_centavos=rec["amount_centavos"])
        set_corporate_intent(cid, "card", pi["id"])
        session["corp_pending_pi"] = pi["id"]
        session["corp_pending_id"] = cid
        add_corporate_event(cid, session.get("user_id"), "card_initiated",
                            f"Card checkout started for PHP {rec['amount_centavos'] / 100:,.2f}")
        return jsonify({"pi_id": pi["id"], "client_key": pi["client_key"]})
    except Exception as e:
        current_app.logger.warning("Corporate card intent failed for %s: %s", cid, e)
        return jsonify(error=str(e)), 500


@admin_bp.route("/admin/corporate/<int:cid>/pay/card/method", methods=["POST"])
def corporate_card_method(cid):
    resp = require("corporate_payments")
    if resp:
        return resp
    rec, err = _payable(cid)
    if err:
        return err
    data = request.get_json(force=True)
    try:
        pm_id = paymongo.create_card_payment_method(
            number    = str(data["number"]).replace(" ", "").replace("-", "").strip(),
            exp_month = int(data["exp_month"]),
            exp_year  = int(data["exp_year"]),
            cvc       = str(data["cvc"]).strip(),
            name      = str(data["name"]).strip(),
            email     = rec.get("contact_email") or session.get("user_email", "billing@energywize.com"),
        )
        return jsonify({"pm_id": pm_id})
    except Exception as e:
        return jsonify(error=str(e)), 400


@admin_bp.route("/admin/corporate/<int:cid>/pay/card/attach", methods=["POST"])
def corporate_card_attach(cid):
    resp = require("corporate_payments")
    if resp:
        return resp
    rec, err = _payable(cid)
    if err:
        return err
    data       = request.get_json(force=True)
    pm_id      = data.get("payment_method_id")
    client_key = data.get("client_key")
    pi_id      = rec["paymongo_id"]
    if not pm_id or not client_key or not pi_id:
        return jsonify(error="Missing parameters"), 400
    return_url = base_url().rstrip("/") + f"/admin/corporate/{cid}/card/return"
    try:
        result = paymongo.attach_payment_method(pi_id, pm_id, client_key, return_url)
        if result["status"] == "succeeded":
            _settle(cid, pi_id)
            return jsonify(status="paid")
        if result["status"] == "awaiting_next_action":
            return jsonify(status="redirect", url=result["redirect_url"])
        return jsonify(status=result["status"])
    except Exception as e:
        return jsonify(error=str(e)), 500


@admin_bp.route("/admin/corporate/<int:cid>/card/return")
def corporate_card_return(cid):
    resp = require("corporate_payments")
    if resp:
        return resp
    rec = get_corporate_payment(cid=cid)
    if not rec or not rec["paymongo_id"]:
        return redirect(url_for("admin.corporate_detail", cid=cid))
    try:
        pi = paymongo.retrieve_payment_intent(rec["paymongo_id"])
        if pi["status"] == "succeeded":
            _settle(cid, rec["paymongo_id"])
            flash("Payment confirmed. All listed trainees can now proceed to the LMS.", "success")
        else:
            flash("The card payment was not completed.", "error")
    except Exception as e:
        flash(f"Could not confirm the payment: {e}", "error")
    return redirect(url_for("admin.corporate_detail", cid=cid))


# ── Settlement ────────────────────────────────────────────────────────────────

def settle_corporate_payment(reference=None, paymongo_id=None, cid=None, actor_id=None):
    """Confirm a corporate invoice exactly once, whoever reports it first.

    mark_corporate_paid() does the record flip and every trainee's
    payment_status in one transaction and only matches a still-pending row, so
    a duplicate webhook delivery, a poll and a card return racing each other
    all collapse into a single settlement. Everything after it — the receipt
    anchor, the email — runs only for the caller that won.
    """
    rec = mark_corporate_paid(reference=reference, paymongo_id=paymongo_id, cid=cid)
    if not rec:
        return None
    _anchor_receipt(rec, actor_id)
    _notify_creator(rec)
    audit_log(actor_id, "corporate_payment_paid", "corporate_payment", rec["id"],
              f"Invoice {rec['reference']} paid "
              f"(PHP {rec['amount_centavos'] / 100:,.2f}, {rec['company_name']})")
    return rec


def _settle(cid, paymongo_id):
    return settle_corporate_payment(paymongo_id=paymongo_id, cid=cid,
                                    actor_id=session.get("user_id"))


def _anchor_receipt(rec, actor_id=None):
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
        chain        = store_hash_on_chain(receipt_hash)
        qr_path      = generate_receipt_qr(receipt_id, chain["tx_hash"])
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
        return redirect(url_for("admin.corporate_list"))
    if rec.get("tx_hash"):
        flash("This receipt is already anchored on-chain.", "success")
    elif rec["status"] != "paid":
        flash("Only a paid invoice has a receipt to anchor.", "error")
    elif _anchor_receipt(rec, session.get("user_id")):
        flash("Receipt successfully anchored on-chain.", "success")
    else:
        flash("Re-anchor attempt failed again — still Off-chain.", "warning")
    return redirect(url_for("admin.corporate_detail", cid=cid))


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
