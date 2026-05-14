import hashlib
import hmac
import os
from base64 import b64encode

import requests

BASE = "https://api.paymongo.com/v1"


def _auth(key=None):
    k = key or os.environ["PAYMONGO_SECRET_KEY"]
    return {"Authorization": "Basic " + b64encode(f"{k}:".encode()).decode()}


def _raise(r):
    if not r.ok:
        try:
            detail = r.json()
        except Exception:
            detail = r.text
        raise Exception(f"PayMongo {r.status_code}: {detail}")


def create_payment_intent(amount_php, description):
    r = requests.post(
        f"{BASE}/payment_intents",
        headers=_auth(),
        json={"data": {"attributes": {
            "amount": int(round(amount_php * 100)),
            "payment_method_allowed": ["card"],
            "currency": "PHP",
            "description": description,
            "capture_type": "automatic",
        }}},
    )
    r.raise_for_status()
    d = r.json()["data"]
    return {
        "id": d["id"],
        "client_key": d["attributes"]["client_key"],
        "status": d["attributes"]["status"],
    }


def attach_payment_method(pi_id, pm_id, client_key, return_url):
    r = requests.post(
        f"{BASE}/payment_intents/{pi_id}/attach",
        headers=_auth(),
        json={"data": {"attributes": {
            "payment_method": pm_id,
            "client_key": client_key,
            "return_url": return_url,
        }}},
    )
    r.raise_for_status()
    d = r.json()["data"]
    attrs = d["attributes"]
    result = {"id": d["id"], "status": attrs["status"]}
    if attrs.get("next_action") and attrs["next_action"].get("redirect"):
        result["redirect_url"] = attrs["next_action"]["redirect"]["url"]
    # Pull the PayMongo payment ID if already paid
    payments = attrs.get("payments", [])
    if payments:
        result["payment_id"] = payments[0]["id"]
    return result


def retrieve_payment_intent(pi_id):
    r = requests.get(f"{BASE}/payment_intents/{pi_id}", headers=_auth())
    r.raise_for_status()
    d = r.json()["data"]
    attrs = d["attributes"]
    result = {"id": d["id"], "status": attrs["status"]}
    payments = attrs.get("payments", [])
    if payments:
        result["payment_id"] = payments[0]["id"]
    return result


def create_qrph_intent(amount_php, description, return_url):
    """Create Payment Intent + QRPH Payment Method, attach, return QR image."""
    # 1. Create Payment Intent
    r = requests.post(
        f"{BASE}/payment_intents",
        headers=_auth(),
        json={"data": {"attributes": {
            "amount": int(round(amount_php * 100)),
            "payment_method_allowed": ["qrph"],
            "currency": "PHP",
            "description": description,
            "capture_type": "automatic",
        }}},
    )
    _raise(r)
    pi         = r.json()["data"]
    pi_id      = pi["id"]
    client_key = pi["attributes"]["client_key"]

    # 2. Create QRPH Payment Method (no card details needed)
    r = requests.post(
        f"{BASE}/payment_methods",
        headers=_auth(),
        json={"data": {"attributes": {"type": "qrph"}}},
    )
    _raise(r)
    pm_id = r.json()["data"]["id"]

    # 3. Attach PM to PI
    r = requests.post(
        f"{BASE}/payment_intents/{pi_id}/attach",
        headers=_auth(),
        json={"data": {"attributes": {
            "payment_method": pm_id,
            "client_key": client_key,
            "return_url": return_url,
        }}},
    )
    _raise(r)
    attrs       = r.json()["data"]["attributes"]
    next_action = attrs.get("next_action") or {}
    code        = next_action.get("code") or {}

    return {
        "pi_id":     pi_id,
        "status":    attrs["status"],
        "qr_image":  code.get("image_url"),
        "test_url":  code.get("test_url"),
        "expire_at": None,
    }


def verify_webhook_signature(payload_bytes, sig_header, secret):
    """
    PayMongo webhook signature format:
      Paymongo-Signature: t=<timestamp>,te=<test_hmac>,li=<live_hmac>
    Signed payload = "<timestamp>.<raw_body>"
    """
    parts = {}
    for part in sig_header.split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            parts[k.strip()] = v.strip()
    timestamp = parts.get("t", "")
    signature = parts.get("te") or parts.get("li", "")
    if not timestamp or not signature:
        return False
    signed = f"{timestamp}.{payload_bytes.decode('utf-8')}"
    computed = hmac.new(secret.encode(), signed.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed, signature)
