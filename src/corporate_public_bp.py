"""Public company payment page.

A separate module that NEVER imports `permissions.require`. Every admin
surface is guarded by it, so putting unauthenticated money routes in the same
file would make "is this route public?" a per-function question a future edit
could get wrong. Here the answer is structural.

The page accepts no amount: the charge is read from the invoice row every
time. Nothing the browser sends can influence it.
"""
import json
import os
from datetime import datetime
from urllib.parse import urlsplit

from flask import (Blueprint, render_template, make_response, current_app,
                   url_for, jsonify)

import paymongo

from db import (payment_by_token, get_corporate_items, open_attempt, audit_log, get_attempts,
                attempt_for_return_token, get_corporate_payment)
from pricing import program_label

corporate_public_bp = Blueprint("corporate_public", __name__)


def _no_leak(body, status=200, form_page=False):
    resp = make_response(body, status)
    # Token-bearing form pages must support Flask-WTF's HTTPS origin check.
    # same-origin retains that check while suppressing external referrers.
    resp.headers["Referrer-Policy"] = "same-origin" if form_page else "no-referrer"
    resp.headers["X-Robots-Tag"] = "noindex, nofollow"
    resp.headers["Cache-Control"] = "no-store"
    return resp


def _invalid(msg="This payment link is not valid or has expired."):
    return _no_leak(render_template("payment/corporate_link_invalid.html", reason=msg), 404)


def _paid_page(invoice):
    from blockchain import _explorer_url
    attempts = get_attempts(invoice['id'])
    test_payment = any(a['status'] == 'paid' and a['environment'] == 'test' for a in attempts)
    return _no_leak(render_template('payment/corporate_paid.html', invoice=invoice,
        trainee_count=len(get_corporate_items(invoice['id'])), test_payment=test_payment,
        explorer_url=_explorer_url(invoice['tx_hash']) if invoice.get('tx_hash') else None), form_page=True)


def _checkout_presentation(attempt):
    """Display only methods on the immutable session request, never guesses.

    A mock response has no browser checkout. In particular, an old persisted
    mock URL must stay blocked even after PAYMONGO_MOCK is turned off.
    """
    attempt = attempt or {}
    payload = attempt.get("request_payload") or {}
    if isinstance(payload, str):
        payload = json.loads(payload)
    methods = payload.get("payment_method_types") or []
    groups = []
    if "card" in methods:
        groups.append({"id": "card", "label": "Credit / Debit Card",
                       "icon": "credit-card", "title": "Pay by card",
                       "detail": "Enter your card details and complete any bank verification on PayMongo's secure checkout."})
    wallets = [m for m in methods if m != "card"]
    if wallets:
        names = {"gcash": "GCash", "paymaya": "Maya", "qrph": "QRPH",
                 "grab_pay": "GrabPay"}
        groups.append({"id": "wallet", "label": "QR / E-wallet" if "qrph" in wallets else "E-wallet",
                       "has_qr": 'qrph' in wallets,
                       "icon": "qrcode" if "qrph" in wallets else "mobile-screen-button",
                       "title": "Pay by " + " / ".join(names.get(m, m) for m in wallets),
                       "detail": "Choose your payment method on PayMongo and follow its instructions to complete payment."})

    checkout_url = attempt.get("checkout_url") or ""
    try:
        parsed = urlsplit(checkout_url)
        host = (parsed.hostname or "").lower()
        valid_url = parsed.scheme == "https" and bool(host) and not parsed.username and not parsed.password
    except ValueError:
        host, valid_url = "", False
    mocked = (paymongo.MOCK_GATEWAY or
              (attempt.get("checkout_session_id") or "").startswith("cs_mock_") or
              host == "mock.paymongo.test" or host.endswith(".test"))
    notice = None
    can_connect_test = (not paymongo.MOCK_GATEWAY and os.getenv('PAYMONGO_SECRET_KEY','').startswith('sk_test_')
                        and (attempt.get('checkout_session_id') or '').startswith('cs_mock_'))
    if mocked:
        if can_connect_test:
            notice = 'This invoice still has an offline mock checkout. Connect PayMongo test checkout below to enable payment simulation. No money will be charged.'
        elif paymongo.MOCK_GATEWAY:
            notice = 'The running server has PAYMONGO_MOCK=1. No money will be charged. Restart Flask with PAYMONGO_MOCK=0 to enable PayMongo sandbox checkout.'
        else:
            notice = 'This offline test checkout is unavailable. Contact EnergyWize for a connected payment link. No money will be charged.'
    elif attempt and attempt.get("environment") != paymongo.environment():
        notice = "This checkout needs to be checked by EnergyWize before you can pay."
    elif attempt.get("status") != "active" or not valid_url:
        notice = "Payment is not available yet. Please contact EnergyWize before trying to pay."
    return {"payment_groups": groups, "checkout_url": checkout_url if not notice else None,
            "checkout_notice": notice, "mock_checkout": mocked,
            "can_connect_test": can_connect_test,
            "sandbox_checkout": not mocked and paymongo.environment() == "test"}


@corporate_public_bp.route("/pay/corporate/<token>")
def corporate_pay(token):
    invoice, reason = payment_by_token(token)
    if not invoice:
        # One generic page for unknown / revoked / cancelled / expired: telling
        # an anonymous visitor which it is would be an enumeration oracle.
        return _invalid()
    if reason == "paid":
        return _paid_page(invoice)

    items = get_corporate_items(invoice["id"])
    attempt = open_attempt(invoice["id"])
    audit_log(None, "corporate_pay_page_viewed", "corporate_payment",
              invoice["id"], "Public payment page opened")
    return _no_leak(render_template(
        "payment/corporate_pay.html",
        invoice=invoice,
        trainee_count=len(items),
        program=program_label(invoice.get("form_type") or ""),
        status_url=url_for("corporate_public.corporate_pay_return", token=token),
        status_api=url_for('corporate_public.corporate_payment_status', token=token),
        test_action_api=url_for('corporate_public.corporate_sandbox_action', token=token),
        connect_test_api=url_for('corporate_public.corporate_connect_sandbox', token=token),
        **_checkout_presentation(attempt),
        amount_php=invoice["amount_centavos"] / 100.0), form_page=True)


@corporate_public_bp.route('/pay/corporate/<token>/connect-sandbox', methods=['POST'])
def corporate_connect_sandbox(token):
    """Connect a real TEST checkout for a payer holding a valid invoice link.

    Keeps the link and price. Only the exact deterministic offline mock can
    be retired; unidentified outcomes continue to block a new session.
    Global CSRF applies, and this action never settles or charges an invoice.
    """
    invoice, reason = payment_by_token(token)
    if not invoice or reason == 'paid' or (invoice.get('expires_at') and invoice['expires_at'] <= datetime.now()):
        return _no_leak(jsonify(error='This invoice is no longer available for a test checkout.'), 404)
    if paymongo.MOCK_GATEWAY:
        return _no_leak(jsonify(error='The running Flask process still has PAYMONGO_MOCK=1. Restart it with PAYMONGO_MOCK=0, then reload this page.'), 409)
    if not os.getenv('PAYMONGO_SECRET_KEY','').startswith('sk_test_'):
        return _no_leak(jsonify(error='A PayMongo test key is required. This action cannot use live payments.'), 403)
    from db import retire_offline_mock_attempt
    from corporate_checkout import ensure_checkout_session
    safe, error = retire_offline_mock_attempt(invoice['id'], None)
    if not safe:
        return _no_leak(jsonify(error=error), 409)
    # Construct redirects from this valid bearer link, rather than reusing an
    # old mock payload that may contain a superseded token.
    payment_url = url_for('corporate_public.corporate_pay', token=token, _external=True)
    attempt, error = ensure_checkout_session(invoice, payment_url+'/return', payment_url)
    if error:
        return _no_leak(jsonify(error=error), 409)
    if not attempt or (attempt.get('checkout_session_id') or '').startswith('cs_mock_'):
        return _no_leak(jsonify(error='PayMongo did not confirm a connected sandbox checkout.'), 502)
    audit_log(None, 'corporate_sandbox_connected', 'corporate_payment', invoice['id'],
              'Payer connected PayMongo test checkout using the current payment link.')
    return _no_leak(jsonify(ok=True, url=url_for('corporate_public.corporate_pay', token=token)))


@corporate_public_bp.route('/pay/corporate/<token>/sandbox-action')
def corporate_sandbox_action(token):
    invoice, reason = payment_by_token(token)
    if not invoice:
        return _invalid()
    if paymongo.MOCK_GATEWAY or not os.getenv('PAYMONGO_SECRET_KEY', '').startswith('sk_test_'):
        return _no_leak(jsonify(error='PayMongo test checkout is not enabled.'), 404)
    attempt = open_attempt(invoice['id'])
    if reason == 'paid' or not attempt or attempt['environment'] != 'test' or not attempt.get('checkout_session_id'):
        return _no_leak(jsonify(error='No active PayMongo test checkout is available.'), 409)
    try:
        action = paymongo.checkout_test_action(attempt['checkout_session_id'])
    except Exception:
        current_app.logger.warning('PayMongo test action could not be retrieved for invoice %s', invoice['reference'])
        return _no_leak(jsonify(error='Could not retrieve the PayMongo simulation link. Open checkout, select a method, and try again.'), 502)
    return _no_leak(jsonify(action))


@corporate_public_bp.route('/pay/corporate/<token>/status')
def corporate_payment_status(token):
    invoice, reason = payment_by_token(token)
    if not invoice:
        return _no_leak(jsonify(error='This payment link is no longer available.'), 404)
    if reason == 'paid':
        return _no_leak(jsonify(paid=True, url=url_for('corporate_public.corporate_pay', token=token)))
    attempt = open_attempt(invoice['id'])
    if not attempt or _checkout_presentation(attempt)['mock_checkout']:
        return _no_leak(jsonify(paid=False, message='No confirmed PayMongo payment yet.'))
    from corporate_checkout import poll_attempt
    try:
        settled, message = poll_attempt(attempt, source='public_poll')
    except Exception:
        return _no_leak(jsonify(error='Could not check PayMongo just now. Try again shortly.'), 502)
    return _no_leak(jsonify(paid=settled, message=message,
        url=url_for('corporate_public.corporate_pay', token=token) if settled else None))


@corporate_public_bp.route("/pay/corporate/<token>/return")
def corporate_pay_return(token):
    """Where the gateway sends the payer back.

    A redirect here is NOT payment evidence — anyone can open this URL. The
    page re-reads the invoice and, if still pending, polls the SESSION before
    saying anything about the outcome.
    """
    invoice, reason = payment_by_token(token)
    attempt = None
    current_link = invoice is not None
    if not invoice:
        # A checkout session keeps the original success_url even when staff
        # replace the payable link. Accept only the exact stored callback,
        # without granting access to its old payment page or the new token.
        attempt = attempt_for_return_token(token)
        invoice = get_corporate_payment(cid=attempt['corporate_payment_id']) if attempt else None
        if not invoice or invoice.get('pay_token_revoked_at') is not None:
            return _invalid()
    if invoice['status'] == 'paid':
        return _paid_page(invoice)

    settled, message = False, "We have not seen this payment confirmed yet."
    attempt = attempt or open_attempt(invoice["id"])
    if attempt and _checkout_presentation(attempt)["mock_checkout"]:
        message = "Demo checkout cannot confirm an online payment. Please contact EnergyWize for a connected payment link."
    elif attempt:
        from corporate_checkout import poll_attempt
        try:
            settled, message = poll_attempt(attempt, source="return")
        except Exception as e:
            current_app.logger.warning("Return poll failed for %s: %s",
                                       invoice["reference"], e)
            message = "We could not confirm the payment just now."
    if settled:
        invoice = get_corporate_payment(cid=invoice['id'])
        if not invoice:
            return _invalid()
        if invoice['status'] == 'paid':
            return _paid_page(invoice)
    if invoice['status'] in ('cancelled','expired'):
        message = ('This invoice is ' + invoice['status'] + '. If you completed a payment, '
                   'contact EnergyWize to reconcile it. Do not pay again.')
    return _no_leak(render_template("payment/corporate_pending.html",
                                    invoice=invoice, message=message,
                                    payment_url=url_for("corporate_public.corporate_pay", token=token) if current_link else None,
                                    status_url=url_for("corporate_public.corporate_pay_return", token=token)))
