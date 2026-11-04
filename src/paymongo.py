import hashlib
import hmac
import os
from base64 import b64encode

import requests

BASE = "https://api.paymongo.com/v1"

# Hosted Checkout is versioned PER OPERATION, not globally.
#
#   create   -> v2. Recommended for new integrations; it DEFERS Payment Intent
#               creation until the customer pays, so an attempt's intent id is
#               legitimately NULL until then.
#   retrieve -> v1. Verified against a v2-created sandbox session; the v2
#               retrieval route returns 404 on the configured account.
#   expire   -> v1. The documented Expire endpoint still lives there.
#
# `BASE` is deliberately left alone: the existing payment-intent and QRPH
# calls (individual trainee payments) stay on v1 and are not being migrated.
CHECKOUT_CREATE_BASE   = "https://api.paymongo.com/v2"
CHECKOUT_RETRIEVE_BASE = "https://api.paymongo.com/v1"
CHECKOUT_EXPIRE_BASE   = "https://api.paymongo.com/v1"

# With the gateway mocked, no network call is made at all. Default ON so a
# developer or a test can never reach PayMongo by accident; set
# PAYMONGO_MOCK=0 deliberately for sandbox work.
MOCK_GATEWAY = os.getenv("PAYMONGO_MOCK", "1").strip().lower() not in ("0", "false", "no")


def environment():
    """('test'|'live') implied by the configured secret key.

    Used to reject a webhook whose `livemode` disagrees with the key this
    process is running under, so a sandbox event can never settle live data.
    """
    return "live" if os.getenv("PAYMONGO_SECRET_KEY", "").startswith("sk_live_") else "test"


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


def _intent_attrs(amount_php, description, methods, metadata=None, amount_centavos=None):
    """Shared payment-intent body. `amount_centavos` wins when given so a
    caller that already holds an exact integer amount (corporate invoices)
    never round-trips it through a float."""
    attrs = {
        "amount": amount_centavos if amount_centavos is not None else int(round(amount_php * 100)),
        "payment_method_allowed": list(methods),
        "currency": "PHP",
        "description": description,
        "capture_type": "automatic",
    }
    if metadata:
        # Carried back to us on the webhook, which is how a gateway callback
        # is matched to the record that created it.
        attrs["metadata"] = {k: str(v) for k, v in metadata.items()}
    return attrs


def create_payment_intent(amount_php, description, metadata=None, amount_centavos=None):
    r = requests.post(
        f"{BASE}/payment_intents",
        headers=_auth(),
        json={"data": {"attributes": _intent_attrs(
            amount_php, description, ["card"], metadata, amount_centavos)}},
    )
    r.raise_for_status()
    d = r.json()["data"]
    return {
        "id": d["id"],
        "client_key": d["attributes"]["client_key"],
        "status": d["attributes"]["status"],
    }


def create_card_payment_method(number, exp_month, exp_year, cvc, name, email):
    pub_key = os.environ.get("PAYMONGO_PUBLIC_KEY") or os.environ["PAYMONGO_SECRET_KEY"]
    payload = {"data": {"attributes": {
        "type": "card",
        "details": {"card_number": number, "exp_month": exp_month,
                    "exp_year": exp_year, "cvc": cvc},
        "billing": {"name": name, "email": email},
    }}}
    r = requests.post(f"{BASE}/payment_methods", headers=_auth(pub_key), json=payload)
    _raise(r)
    return r.json()["data"]["id"]


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


def create_qrph_intent(amount_php, description, return_url, metadata=None,
                       amount_centavos=None):
    """Create Payment Intent + QRPH Payment Method, attach, return QR image."""
    # 1. Create Payment Intent
    r = requests.post(
        f"{BASE}/payment_intents",
        headers=_auth(),
        json={"data": {"attributes": _intent_attrs(
            amount_php, description, ["qrph"], metadata, amount_centavos)}},
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


# ── Hosted Checkout ──────────────────────────────────────────────────────────

def _mock_session(reference, amount_centavos, idempotency_key):
    """Deterministic stand-in so the whole flow is exercisable offline.

    Derived from the idempotency key, so replaying the same key returns the
    same session id — which is exactly the property the real API provides and
    the thing the recovery path depends on.
    """
    digest = hashlib.sha256(idempotency_key.encode()).hexdigest()[:24]
    return {
        "id": f"cs_mock_{digest}",
        "status": "active",
        "reference_number": reference,
        "checkout_url": f"https://mock.paymongo.test/checkout/cs_mock_{digest}",
        "payment_intent_id": None,       # v2 defers intent creation
        "payments": [],
        "livemode": environment() == "live",
        "amount_centavos": amount_centavos,
    }


def checkout_payment_methods():
    """Select test methods separately from live account capabilities.

    The configured sandbox accepted card, GCash and QR Ph together even
    though its capabilities endpoint returned only QR Ph. Live capability
    filtering must therefore not hide methods in a test checkout.
    """
    requested = [m.strip() for m in os.getenv('CORPORATE_PAYMENT_METHODS', 'card,gcash,qrph').split(',') if m.strip()]
    if MOCK_GATEWAY or os.getenv('PAYMONGO_SECRET_KEY','').startswith('sk_test_'):
        return list(dict.fromkeys(requested))
    response = requests.get(f'{BASE}/merchants/capabilities/payment_methods',
                            headers=_auth(), timeout=20)
    _raise(response)
    enabled = response.json()
    if not isinstance(enabled, list) or any(not isinstance(m, str) for m in enabled):
        raise ValueError('PayMongo returned an unsupported payment-capabilities response.')
    methods = list(dict.fromkeys(m for m in requested if m in enabled))
    if not methods:
        raise ValueError('None of the configured company payment methods is enabled on this PayMongo account.')
    return methods


def checkout_test_action(cs_id):
    """Retrieve PayMongo's own test action for the session's latest intent.

    Never creates a second intent, changes a payment outcome, or invents a
    simulator URL. v2 may not have an intent until a method is selected.
    """
    from urllib.parse import urlsplit
    if MOCK_GATEWAY or not os.getenv('PAYMONGO_SECRET_KEY', '').startswith('sk_test_') or cs_id.startswith('cs_mock_'):
        raise ValueError('A connected PayMongo test checkout is required.')
    snapshot = retrieve_checkout_session(cs_id)
    if snapshot.get('id') != cs_id or snapshot.get('livemode') is not False:
        raise ValueError('PayMongo did not confirm this session is in test mode.')
    pi_id = snapshot.get('payment_intent_id')
    if not pi_id:
        return {'url': None, 'kind': None,
                'message': 'Open PayMongo checkout and select QR Ph or an e-wallet first, then check for its simulation link here.'}
    response = requests.get(f'{BASE}/payment_intents/{pi_id}', headers=_auth(), timeout=20)
    _raise(response)
    data = response.json()['data']
    attrs = data.get('attributes') or {}
    if data.get('id') != pi_id or attrs.get('livemode', data.get('livemode')) is not False:
        raise ValueError('PayMongo did not confirm this payment intent is in test mode.')
    action = attrs.get('next_action') or {}
    code = action.get('code') or {}
    url = code.get('test_url') or (action.get('redirect') or {}).get('url')
    if not url:
        return {'url': None, 'kind': None,
                'message': 'No simulation action is available yet. Select a payment method on PayMongo, or check payment status if testing is complete.'}
    parsed = urlsplit(url)
    host = (parsed.hostname or '').lower()
    if parsed.scheme != 'https' or not (host == 'paymongo.com' or host.endswith('.paymongo.com')) or parsed.username or parsed.password:
        raise ValueError('PayMongo returned an unexpected test-action address.')
    return {'url': url, 'kind': 'qrph' if code.get('test_url') else 'authorization',
            'message': 'Open this PayMongo test page and choose the test outcome. Return here to check confirmation.'}


def create_checkout_session(line_items, description, reference_number,
                            success_url, cancel_url, idempotency_key,
                            payment_method_types=None, metadata=None):
    """POST /v2/checkout_sessions. Returns a normalised session dict.

    `idempotency_key` MUST be persisted by the caller before this is invoked:
    if the response is lost, replaying the same key is the only way to learn
    whether a session was created, and a key invented here would be gone.

    `line_items` amounts are integer centavos. `payment_method_types` is
    required by the API; the caller passes what the account supports.
    """
    payload = {"data": {"attributes": {
        "line_items": line_items,
        "payment_method_types": list(payment_method_types or ["card", "gcash"]),
        "description": description,
        "reference_number": reference_number,
        "success_url": success_url,
        "cancel_url": cancel_url,
        "send_email_receipt": False,
        "show_description": True,
        "show_line_items": True,
    }}}
    if metadata:
        payload["data"]["attributes"]["metadata"] = {k: str(v) for k, v in metadata.items()}

    if MOCK_GATEWAY:
        total = sum(li["amount"] * li.get("quantity", 1) for li in line_items)
        return _mock_session(reference_number, total, idempotency_key)

    r = requests.post(f"{CHECKOUT_CREATE_BASE}/checkout_sessions",
                      headers={**_auth(), "Idempotency-Key": idempotency_key},
                      json=payload, timeout=30)
    _raise(r)
    return _normalise_session(r.json()["data"])


def retrieve_checkout_session(cs_id):
    """GET /v1/checkout_sessions/<id>, including v2-created sessions.

    This is what hosted-checkout polling uses. The intent-only poll
    (`retrieve_payment_intent`) cannot answer for a v2 session: there may be
    no intent at all until the customer pays.
    """
    if MOCK_GATEWAY:
        return {"id": cs_id, "status": "active", "payments": [],
                "payment_intent_id": None, "livemode": environment() == "live",
                "reference_number": None}
    r = requests.get(f"{CHECKOUT_RETRIEVE_BASE}/checkout_sessions/{cs_id}",
                     headers=_auth(), timeout=30)
    _raise(r)
    return _normalise_session(r.json()["data"])


def expire_checkout_session(cs_id):
    """POST /v1/checkout_sessions/<id>/expire — still a v1 endpoint.

    Sessions never expire on their own, so an invoice that lapses locally
    leaves a payable page open unless this is called.
    """
    if MOCK_GATEWAY:
        return {"id": cs_id, "status": "expired"}
    r = requests.post(f"{CHECKOUT_EXPIRE_BASE}/checkout_sessions/{cs_id}/expire",
                      headers=_auth(), timeout=30)
    _raise(r)
    return _normalise_session(r.json()["data"])


def _normalise_session(data):
    """One shape for the rest of the app, whichever envelope the API used."""
    attrs = data.get("attributes", {}) or {}
    payments = []
    for p in attrs.get("payments") or []:
        pa = p.get("attributes", {}) or {}
        payments.append({
            "id":       p.get("id"),
            "status":   pa.get("status"),
            "amount":   pa.get("amount"),
            "currency": pa.get("currency"),
            "method":   (pa.get('source') or {}).get('type') or (pa.get('payment_method') or {}).get('type'),
        })
    intent = attrs.get("payment_intent") or {}
    return {
        "id":                data.get("id"),
        "status":            attrs.get("status"),
        "reference_number":  attrs.get("reference_number"),
        "checkout_url":      attrs.get("checkout_url"),
        # Nullable by design on v2 until the customer actually pays.
        "payment_intent_id": intent.get("id") if isinstance(intent, dict) else None,
        "payments":          payments,
        "livemode":          attrs.get("livemode", data.get("livemode")),
        "metadata":          attrs.get("metadata") or {},
    }


def paid_payment(session):
    """The single settled payment on a session, or None.

    PayMongo documents at most one entry with status 'paid'; anything else is
    an attempt that did not succeed and must not settle an invoice.
    """
    for p in session.get("payments") or []:
        if (p.get("status") or "").lower() == "paid":
            return p
    return None
