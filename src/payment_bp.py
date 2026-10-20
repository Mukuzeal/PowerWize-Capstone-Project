import os
import secrets
from datetime import datetime
from flask import (Blueprint, request, render_template, redirect, session, jsonify,
                   current_app)
from dotenv import load_dotenv
from db import (get_db, dict_cur, log_payment, mark_payment_paid, mark_payment_failed,
                mark_user_paid, get_user_payment_status, get_registration_by_email,
                save_blockchain_receipt, get_receipt_by_id, get_receipt_by_user,
                get_user_id_for_paymongo, get_payment_discount, get_user_training_type,
                validate_discount, redeem_discount)
import paymongo
from blockchain import generate_receipt_id, create_receipt_hash, store_hash_on_chain, verify_hash_on_chain
from qr_gen import generate_receipt_qr
from permissions import is_staff, home_url_for
from pricing import calculate_fee, to_centavos
from utils import base_url

load_dotenv()

payment_bp = Blueprint("payment", __name__)



def _require_unpaid():
    uid = session.get("user_id")
    if not uid:
        return None
    return uid if get_user_payment_status(uid) == "unpaid" else None


def _base_fee(email):
    """The published fee for whoever is paying, read from their registration."""
    reg = get_registration_by_email(email) if email else None
    fee = calculate_fee(reg["form_type"], reg["training_type"]) if reg else None
    if fee is None:
        fallback = float(os.getenv("TRAINING_FEE", "5000"))
        fee = {"base": fallback, "vat": 0, "total": fallback,
               "label": "Training Fee", "has_vat": False}
    return fee


def _charge_for(user_id):
    """What this trainee is actually charged, recomputed from scratch.

    Called again on every gateway call rather than reading a total out of the
    session: the base fee comes from the registration and the discount is
    re-validated against the database each time, so a stale session or a
    tampered request body cannot move the amount. Returns
    (amount_php, amount_centavos, description, discount_row_or_None, discount_php).
    """
    fee  = _base_fee(session.get("user_email"))
    code = session.get("discount_code")
    discount, discount_php, desc = None, 0.0, fee["label"]
    if code:
        row, err = validate_discount(code, get_user_training_type(user_id))
        if err:
            # The code went stale between entry and payment (expired, hit its
            # cap, deactivated). Drop it and charge full price rather than
            # honouring a discount that is no longer valid.
            session.pop("discount_code", None)
        else:
            discount     = row
            discount_php = round(fee["total"] * row["percent_off"] / 100.0, 2)
            desc         = f"{fee['label']} ({row['code']} -{row['percent_off']}%)"
    amount_php = round(fee["total"] - discount_php, 2)
    return amount_php, to_centavos(amount_php), desc, discount, discount_php


def _log_intent(user_id, method, pi_id, amount_php, discount, discount_php):
    log_payment(user_id, amount_php, method, pi_id,
                discount_code_id=discount["id"] if discount else None,
                discount_percent=discount["percent_off"] if discount else None,
                discount_amount_php=discount_php if discount else None)


def _settle_trainee_payment(user_id, paymongo_id):
    """Mark one trainee payment paid, exactly once.

    mark_payment_paid() only matches a still-pending row, so whichever of the
    card attach, the QRPH poll or the webhook arrives first is the one that
    burns the discount redemption; the rest are no-ops.
    """
    first = mark_payment_paid(paymongo_id)
    mark_user_paid(user_id)
    if first:
        _redeem_for_payment(paymongo_id)
    return first


def _redeem_for_payment(paymongo_id):
    code_id, percent = get_payment_discount(paymongo_id)
    if not code_id:
        return
    if not redeem_discount(code_id):
        # The payment already went through, so it is honoured regardless — but
        # the cap was passed, which is worth knowing about.
        current_app.logger.warning(
            "Discount code %s was redeemed past its limit on payment %s",
            code_id, paymongo_id)


# ── Payment wall ──────────────────────────────────────────────────────────────

@payment_bp.route("/payment")
def payment():
    if "user_id" not in session:
        return redirect("/auth")
    if is_staff():
        return redirect(home_url_for(session.get("user_role")))
    if get_user_payment_status(session["user_id"]) == "paid":
        return redirect("/portal")

    fee = _base_fee(session.get("user_email"))
    amount_php, _, _, discount, discount_php = _charge_for(session["user_id"])

    error = "Payment was not completed. Please try again." if request.args.get("error") else None
    return render_template("payment/payment.html",
                           fee=fee,
                           amount_due=amount_php,
                           discount=discount,
                           discount_php=discount_php,
                           public_key=os.getenv("PAYMONGO_PUBLIC_KEY", ""),
                           error=error)


# ── Discount codes ────────────────────────────────────────────────────────────
#
# Applying a code only records *which* code the trainee typed. The charge is
# recomputed from the database on every gateway call (_charge_for), so the
# browser never gets to name a price.

@payment_bp.route("/payment/discount/apply", methods=["POST"])
def discount_apply():
    uid = _require_unpaid()
    if not uid:
        return jsonify({"error": "Unauthorized"}), 403
    code = (request.get_json(force=True) or {}).get("code", "")
    row, err = validate_discount(code, get_user_training_type(uid))
    if err:
        session.pop("discount_code", None)
        return jsonify({"error": err}), 400
    session["discount_code"] = row["code"]
    fee = _base_fee(session.get("user_email"))
    amount_php, _, _, _, discount_php = _charge_for(uid)
    return jsonify({
        "code":          row["code"],
        "percent_off":   row["percent_off"],
        "base_total":    fee["total"],
        "discount_php":  discount_php,
        "amount_due":    amount_php,
        "display":       f"₱{amount_php:,.2f}",
    })


@payment_bp.route("/payment/settle-free", methods=["POST"])
def settle_free():
    """Complete enrollment when a 100% code brings the charge to zero.

    PayMongo will not take a zero-amount intent (and has a PHP 20 floor), so a
    fully-discounted fee has to be settled here instead of at the gateway. The
    amount is recomputed server-side first — this is refused for any charge
    that is actually payable.
    """
    uid = _require_unpaid()
    if not uid:
        return jsonify({"error": "Unauthorized"}), 403
    amount, centavos, desc, discount, discount_php = _charge_for(uid)
    if centavos > 0:
        return jsonify({"error": "This fee still has an amount due."}), 400
    # Synthetic id so the payment row, its discount and the exactly-once
    # redemption guard all work exactly as they do for a gateway payment.
    free_id = f"FREE-{secrets.token_hex(8)}"
    _log_intent(uid, "free", free_id, 0, discount, discount_php)
    _settle_trainee_payment(uid, free_id)
    session.pop("discount_code", None)
    _store_receipt_on_chain(uid, free_id)
    return jsonify({"status": "paid"})


@payment_bp.route("/payment/discount/remove", methods=["POST"])
def discount_remove():
    uid = _require_unpaid()
    if not uid:
        return jsonify({"error": "Unauthorized"}), 403
    session.pop("discount_code", None)
    amount_php, _, _, _, _ = _charge_for(uid)
    return jsonify({"amount_due": amount_php, "display": f"₱{amount_php:,.2f}"})


# ── Card: create Payment Intent ───────────────────────────────────────────────

@payment_bp.route("/payment/card/initiate", methods=["POST"])
def card_initiate():
    uid = _require_unpaid()
    if not uid:
        return jsonify({"error": "Unauthorized"}), 403
    amount, centavos, desc, discount, discount_php = _charge_for(uid)
    try:
        pi = paymongo.create_payment_intent(None, desc, amount_centavos=centavos)
        _log_intent(uid, "card", pi["id"], amount, discount, discount_php)
        session["pending_pi"] = pi["id"]
        return jsonify({
            "pi_id":      pi["id"],
            "client_key": pi["client_key"],
            "public_key": os.environ["PAYMONGO_PUBLIC_KEY"],
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Card: create Payment Method (server-side, avoids JS SDK auth issues) ─────

@payment_bp.route("/payment/card/method", methods=["POST"])
def card_create_method():
    uid = _require_unpaid()
    if not uid:
        return jsonify({"error": "Unauthorized"}), 403
    data = request.get_json(force=True)
    try:
        num = str(data["number"]).replace(" ", "").replace("-", "").strip()
        pm_id = paymongo.create_card_payment_method(
            number    = num,
            exp_month = int(data["exp_month"]),
            exp_year  = int(data["exp_year"]),
            cvc       = str(data["cvc"]).strip(),
            name      = str(data["name"]).strip(),
            email     = session.get("user_email", "user@powerwize.com"),
        )
        return jsonify({"pm_id": pm_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ── Card: attach Payment Method ───────────────────────────────────────────────

@payment_bp.route("/payment/card/attach", methods=["POST"])
def card_attach():
    uid = _require_unpaid()
    if not uid:
        return jsonify({"error": "Unauthorized"}), 403
    data       = request.get_json(force=True)
    pm_id      = data.get("payment_method_id")
    pi_id      = session.get("pending_pi")
    client_key = data.get("client_key")
    if not pm_id or not pi_id or not client_key:
        return jsonify({"error": "Missing parameters"}), 400
    return_url = base_url().rstrip("/") + "/payment/card/return"
    try:
        result = paymongo.attach_payment_method(pi_id, pm_id, client_key, return_url)
        if result["status"] == "succeeded":
            _complete_card_payment(uid, pi_id)
            return jsonify({"status": "paid"})
        if result["status"] == "awaiting_next_action":
            return jsonify({"status": "redirect", "url": result["redirect_url"]})
        return jsonify({"status": result["status"]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Card: 3DS return URL ──────────────────────────────────────────────────────

@payment_bp.route("/payment/card/return")
def card_return():
    uid   = session.get("user_id")
    pi_id = session.get("pending_pi") or request.args.get("payment_intent_id")
    if not uid or not pi_id:
        return redirect("/payment")
    try:
        pi = paymongo.retrieve_payment_intent(pi_id)
        if pi["status"] == "succeeded":
            _complete_card_payment(uid, pi_id)
            return redirect("/payment/success")
        else:
            mark_payment_failed(pi_id)
            return redirect("/payment/failed")
    except Exception:
        return redirect("/payment/failed")


def _complete_card_payment(user_id, pi_id):
    _settle_trainee_payment(user_id, pi_id)
    session.pop("pending_pi", None)
    session.pop("discount_code", None)
    _store_receipt_on_chain(user_id, pi_id)


def _store_receipt_on_chain(user_id, paymongo_id):
    try:
        from blockchain import compute_anchor, ANCHOR_VERSION
        from db import get_payment_by_paymongo_id

        receipt_id = generate_receipt_id()

        # Anchor the payment as it now stands in the database. The old version
        # hashed a datetime.now() that was never stored, so the fingerprint
        # could not be recomputed later and verification degenerated into
        # comparing the database against itself. Every field below is read back
        # out of the row at verification time.
        row = get_payment_by_paymongo_id(paymongo_id) or {}
        record = {
            "receipt_id":  receipt_id,
            "user_id":     user_id,
            "paymongo_id": paymongo_id,
            "amount_php":  row.get("amount_php"),
            "status":      row.get("status"),
        }
        receipt_hash = compute_anchor("payment", record)
        chain_result = store_hash_on_chain(receipt_hash)
        qr_path      = generate_receipt_qr(receipt_id, chain_result["tx_hash"])
        save_blockchain_receipt(paymongo_id, receipt_id, receipt_hash,
                                chain_result["tx_hash"], qr_path,
                                anchor_version=ANCHOR_VERSION)
        session["last_receipt_id"] = receipt_id
    except Exception as e:
        import traceback
        print(f"[BLOCKCHAIN ERROR] {e}")
        traceback.print_exc()


# ── QRPH: create Payment Intent ───────────────────────────────────────────────

@payment_bp.route("/payment/qrph/initiate", methods=["POST"])
def qrph_initiate():
    uid = _require_unpaid()
    if not uid:
        return jsonify({"error": "Unauthorized"}), 403
    amount, centavos, desc, discount, discount_php = _charge_for(uid)
    return_url = base_url().rstrip("/") + "/payment/card/return"
    try:
        result = paymongo.create_qrph_intent(None, desc, return_url, amount_centavos=centavos)
        _log_intent(uid, "qrph", result["pi_id"], amount, discount, discount_php)
        session["pending_qr_pi"] = result["pi_id"]
        return jsonify({
            "pi_id":     result["pi_id"],
            "qr_image":  result.get("qr_image"),
            "test_url":  result.get("test_url"),
            "expire_at": result.get("expire_at"),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── QRPH: poll payment intent status ─────────────────────────────────────────

@payment_bp.route("/payment/qrph/poll/<pi_id>")
def qrph_poll(pi_id):
    uid = session.get("user_id")
    if not uid:
        return jsonify({"status": "unauthorized"}), 403
    if session.get("pending_qr_pi") != pi_id:
        return jsonify({"status": "invalid"}), 400
    try:
        pi = paymongo.retrieve_payment_intent(pi_id)
        if pi["status"] == "succeeded":
            _settle_trainee_payment(uid, pi_id)
            session.pop("pending_qr_pi", None)
            session.pop("discount_code", None)
            _store_receipt_on_chain(uid, pi_id)
            return jsonify({"status": "paid"})
        if pi["status"] in ("payment_error", "failed"):
            mark_payment_failed(pi_id)
            return jsonify({"status": "failed"})
        return jsonify({"status": pi["status"]})
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[POLL ERROR] {e}")
        return jsonify({"status": "error", "detail": str(e)}), 500


# ── Webhook ───────────────────────────────────────────────────────────────────

@payment_bp.route("/payment/webhook", methods=["POST"])
def webhook():
    secret = os.getenv("PAYMONGO_WEBHOOK_SECRET", "")
    sig    = request.headers.get("Paymongo-Signature", "")
    body   = request.get_data()

    if not secret or not paymongo.verify_webhook_signature(body, sig, secret):
        return jsonify({"error": "Invalid signature"}), 400

    event = request.get_json(force=True)
    etype = event.get("data", {}).get("attributes", {}).get("type", "")

    if etype == "payment.paid":
        payment_obj = event["data"]["attributes"]["data"]
        attrs       = payment_obj.get("attributes", {}) or {}
        paymongo_id = payment_obj["id"]
        # The event carries a payment id (pay_...), but what we stored when we
        # created the charge is the payment *intent* id (pi_...) — so both are
        # tried. Corporate invoices additionally echo back their own reference
        # in the intent metadata, which is the most direct match of the three.
        intent_id   = attrs.get("payment_intent_id")
        reference   = (attrs.get("metadata") or {}).get("reference")

        if not _handle_corporate_paid(reference, intent_id, paymongo_id):
            _handle_payment_paid(paymongo_id, intent_id)

    return jsonify({"received": True}), 200


def _handle_corporate_paid(reference, intent_id, paymongo_id):
    """True if this event belonged to a corporate invoice (settled now or
    already settled by an earlier delivery), so the trainee path is skipped."""
    from admin.corporate import settle_corporate_payment
    from db import get_corporate_payment

    rec = None
    if reference:
        rec = get_corporate_payment(reference=reference)
    for pmid in (intent_id, paymongo_id):
        if rec is None and pmid:
            rec = get_corporate_payment(paymongo_id=pmid)
    if not rec:
        return False
    # Already paid/cancelled/expired -> settle_corporate_payment matches no
    # row and returns None. Either way the event is accounted for here.
    settle_corporate_payment(cid=rec["id"])
    return True


def _handle_payment_paid(paymongo_id, intent_id=None):
    for pmid in (paymongo_id, intent_id):
        if not pmid:
            continue
        user_id = get_user_id_for_paymongo(pmid)
        if user_id:
            _settle_trainee_payment(user_id, pmid)
            return True
    return False


# ── Success / Failed pages ────────────────────────────────────────────────────

@payment_bp.route("/payment/success")
def payment_success():
    if "user_id" not in session:
        return redirect("/auth")
    receipt = get_receipt_by_user(session["user_id"])
    return render_template("payment/payment_success.html", receipt=receipt)


@payment_bp.route("/payment/failed")
def payment_failed():
    if "user_id" not in session:
        return redirect("/auth")
    return redirect("/payment?error=1")


# ── Receipt Verification ──────────────────────────────────────────────────────

@payment_bp.route("/verify", methods=["GET", "POST"])
def verify_receipt():
    result = None
    receipt = None
    if request.method == "POST":
        import json
        raw = request.form.get("qr_data", "").strip()
        try:
            data = json.loads(raw)
            receipt_id = data.get("receipt_id")
            tx_hash    = data.get("tx_hash")
        except Exception:
            receipt_id = raw
            tx_hash    = None

        receipt = get_receipt_by_id(receipt_id) if receipt_id else None
        if not receipt:
            result = {"verified": False, "reason": "Receipt ID not found in database."}
        else:
            tx_hash = tx_hash or receipt.get("tx_hash")
            if not tx_hash:
                result = {"verified": False, "reason": "No blockchain transaction found for this receipt."}
            elif (receipt.get("anchor_version") or 1) >= 2:
                # Rebuild the fingerprint from the row as it stands right now,
                # so an edited amount or status fails to match the chain.
                from blockchain import verify_anchor
                result = verify_anchor(tx_hash, "payment", receipt)
            else:
                # Anchored before v2: the payload cannot be recomputed, so this
                # only shows a hash was recorded, not that the row is unchanged.
                result = verify_hash_on_chain(tx_hash, receipt["receipt_hash"])
                result["legacy"] = True

    # This page is public — no login required, so anyone with a receipt ID can
    # land here. The payer's full name only goes to the payer themselves or
    # staff; everyone else sees an initial-masked name. The amount stays
    # visible either way since it's just the published training/consultation
    # fee, not a secret.
    full_disclosure = False
    if receipt:
        uid = session.get("user_id")
        role = session.get("user_role")
        full_disclosure = is_staff(role) or (uid is not None and uid == receipt.get("user_id"))

    return render_template("payment/verify_receipt.html", result=result, receipt=receipt,
                           full_disclosure=full_disclosure)

