import os
from datetime import datetime
from flask import Blueprint, request, render_template, redirect, session, jsonify
from dotenv import load_dotenv
from db import (get_db, dict_cur, log_payment, mark_payment_paid, mark_payment_failed,
                mark_user_paid, get_user_payment_status, get_registration_by_email,
                save_blockchain_receipt, get_receipt_by_id, get_receipt_by_user)
import paymongo
from blockchain import generate_receipt_id, create_receipt_hash, store_hash_on_chain, verify_hash_on_chain
from qr_gen import generate_receipt_qr

load_dotenv()

payment_bp = Blueprint("payment", __name__)

VAT_RATE = 0.12


def calculate_fee(form_type, training_type):
    ft = (form_type or "").lower()
    tt = (training_type or "").lower()

    if ft in ("cea_renewal", "cem_renewal"):
        base = 10000 if "face" in tt else 7500
        vat  = round(base * VAT_RATE, 2)
        mode = "Face-to-Face" if "face" in tt else "Online"
        return {"base": base, "vat": vat, "total": base + vat,
                "label": f"Recertification · {mode}", "has_vat": True}

    if ft in ("training", "cea_training"):
        if "hybrid" in tt:
            return {"base": 19500, "vat": 0, "total": 19500,
                    "label": "Training · Hybrid (5 days Online + 2 days F2F)", "has_vat": False}
        if "online" in tt and "self" not in tt:
            return {"base": 18000, "vat": 0, "total": 18000,
                    "label": "Training · Online (7 days, 56 hours)", "has_vat": False}
        if "self" in tt:
            mode = "Face-to-Face" if "face" in tt else "Online"
            return {"base": 19500, "vat": 0, "total": 19500,
                    "label": f"Training · Self-paced ({mode})", "has_vat": False}

    if ft in ("gemp_lgu", "gemp_oge"):
        base = 10000 if "face" in tt else 7500
        vat  = round(base * VAT_RATE, 2)
        mode = "Face-to-Face" if "face" in tt else "Online via Zoom"
        prog = "GEMP Training (LGU)" if ft == "gemp_lgu" else "GEMP Training (Gov't Entity)"
        return {"base": base, "vat": vat, "total": base + vat,
                "label": f"{prog} · {mode}", "has_vat": True}

    return None


def _require_unpaid():
    uid = session.get("user_id")
    if not uid:
        return None
    return uid if get_user_payment_status(uid) == "unpaid" else None


# ── Payment wall ──────────────────────────────────────────────────────────────

@payment_bp.route("/payment")
def payment():
    if "user_id" not in session:
        return redirect("/auth")
    if session.get("user_role") == "employee":
        return redirect("/employee")
    if session.get("user_role") == "admin":
        return redirect("/admin")
    if get_user_payment_status(session["user_id"]) == "paid":
        return redirect("/portal")

    email = session.get("user_email")
    reg   = get_registration_by_email(email) if email else None
    fee   = calculate_fee(reg["form_type"], reg["training_type"]) if reg else None

    if fee is None:
        fallback = float(os.getenv("TRAINING_FEE", "5000"))
        fee = {"base": fallback, "vat": 0, "total": fallback,
               "label": "Training Fee", "has_vat": False}

    session["payment_fee"]  = fee["total"]
    session["payment_desc"] = fee["label"]

    error = "Payment was not completed. Please try again." if request.args.get("error") else None
    return render_template("payment/payment.html",
                           fee=fee,
                           public_key=os.getenv("PAYMONGO_PUBLIC_KEY", ""),
                           error=error)


# ── Card: create Payment Intent ───────────────────────────────────────────────

@payment_bp.route("/payment/card/initiate", methods=["POST"])
def card_initiate():
    uid = _require_unpaid()
    if not uid:
        return jsonify({"error": "Unauthorized"}), 403
    amount = session.get("payment_fee", float(os.getenv("TRAINING_FEE", "5000")))
    desc   = session.get("payment_desc", "EnergyWize Training Fee")
    try:
        pi = paymongo.create_payment_intent(amount, desc)
        log_payment(uid, amount, "card", pi["id"])
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
    return_url = request.host_url.rstrip("/") + "/payment/card/return"
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
    mark_payment_paid(pi_id)
    mark_user_paid(user_id)
    session.pop("pending_pi", None)
    _store_receipt_on_chain(user_id, pi_id)


def _store_receipt_on_chain(user_id, paymongo_id):
    try:
        receipt_id   = generate_receipt_id()
        receipt_data = {
            "receipt_id":  receipt_id,
            "user_id":     user_id,
            "paymongo_id": paymongo_id,
            "timestamp":   datetime.now().isoformat(),
        }
        receipt_hash = create_receipt_hash(receipt_data)
        chain_result = store_hash_on_chain(receipt_hash)
        qr_path      = generate_receipt_qr(receipt_id, chain_result["tx_hash"])
        save_blockchain_receipt(paymongo_id, receipt_id, receipt_hash,
                                chain_result["tx_hash"], qr_path)
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
    amount     = session.get("payment_fee", float(os.getenv("TRAINING_FEE", "5000")))
    desc       = session.get("payment_desc", "EnergyWize Training Fee")
    return_url = request.host_url.rstrip("/") + "/payment/card/return"
    try:
        result = paymongo.create_qrph_intent(amount, desc, return_url)
        log_payment(uid, amount, "qrph", result["pi_id"])
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
            mark_payment_paid(pi_id)
            mark_user_paid(uid)
            session.pop("pending_qr_pi", None)
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

    if secret and not paymongo.verify_webhook_signature(body, sig, secret):
        return jsonify({"error": "Invalid signature"}), 400

    event = request.get_json(force=True)
    etype = event.get("data", {}).get("attributes", {}).get("type", "")

    if etype == "payment.paid":
        paymongo_id = event["data"]["attributes"]["data"]["id"]
        _handle_payment_paid(paymongo_id)

    return jsonify({"received": True}), 200


def _handle_payment_paid(paymongo_id):
    from db import get_db
    conn = get_db()
    cur  = dict_cur(conn)
    cur.execute("SELECT user_id FROM payments WHERE paymongo_id=%s LIMIT 1", (paymongo_id,))
    row = cur.fetchone()
    cur.close(); conn.close()
    if row:
        mark_payment_paid(paymongo_id)
        mark_user_paid(row["user_id"])


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
            else:
                result = verify_hash_on_chain(tx_hash, receipt["receipt_hash"])

    return render_template("payment/verify_receipt.html", result=result, receipt=receipt)

