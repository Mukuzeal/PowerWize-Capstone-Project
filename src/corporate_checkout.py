"""Hosted-checkout orchestration for corporate invoices.

One validation gate, reused by every entry point — webhook, polling, the
return page and reconciliation. Each of them must prove the same five things
before settlement is allowed:

  1. identity     the session belongs to an attempt WE created
  2. paid status  a payment on that session actually reads 'paid'
  3. amount       exactly the centavos the attempt recorded
  4. currency     exactly PHP
  5. environment  the event's livemode matches the configured key

Settlement is `db.corporate.mark_corporate_paid()`, unchanged. Its guarded
`UPDATE ... WHERE status='pending' RETURNING *` is what makes duplicates
harmless; nothing here re-implements it.

Money that cannot be matched, or that arrives against a closed invoice, is
never silently dropped — it raises a persistent attention flag.
"""
from flask import current_app

import paymongo
from db import (get_corporate_payment, attempt_by_session, mark_attempt_paid,
                mark_attempt_expired, mark_attempt_unknown, mark_attempt_failed,
                record_session, reserve_attempt, open_attempt, flag_attention,
                confirm_settlement, record_unresolved_event,
                new_attempt_ref, outbound_args,
                add_corporate_event, audit_log, issue_pay_token,
                get_corporate_items)
from pricing import program_label


class SettlementRefused(Exception):
    """Validation failed. Carries the reason for the audit trail."""


# ── Session creation ─────────────────────────────────────────────────────────

def ensure_checkout_session(invoice, success_url, cancel_url, actor_id=None,
                            payment_method_types=None):
    """Return a usable checkout session for this invoice. (attempt, error).

    Reuses a live one rather than minting another: a session is single-use and
    cannot double-charge, but two SESSIONS can, so reuse is a correctness
    requirement and not an optimisation.

    If an earlier attempt's outcome is unknown, this refuses outright. Creating
    a replacement while a session may already be payable is exactly how a
    company ends up with two live links.
    """
    existing = open_attempt(invoice["id"])
    if existing:
        if not paymongo.MOCK_GATEWAY and (existing.get('checkout_session_id') or '').startswith('cs_mock_'):
            return None, 'This is an offline mock checkout. Regenerate its payment link in Corporate Payments to connect PayMongo sandbox.'
        if existing["status"] == "unknown":
            return None, ("A previous attempt's outcome is unknown. Run "
                          "reconciliation before creating another link.")
        if existing["status"] == "active" and existing["checkout_url"]:
            return existing, None
        if existing["status"] == "creating":
            return None, ("An attempt is mid-creation. Wait a moment, then "
                          "reconcile if it does not settle.")

    items = get_corporate_items(invoice["id"])
    line_items = [{
        "name": program_label(invoice["form_type"]) if invoice.get("form_type")
                else f"Training invoice {invoice['reference']}",
        "amount": int(invoice["amount_centavos"]),
        "currency": "PHP",
        "quantity": 1,
    }]
    # The EXACT outbound request, stored verbatim. PayMongo rejects a replayed
    # idempotency key whose parameters differ, so a recovery that reconstructed
    # these (with blank URLs, say, or without attempt_ref in metadata) would be
    # refused — and a refused recovery is no recovery at all. attempt_ref is
    # filled in below, once reserve_attempt() has minted it.
    # attempt_ref FIRST, so metadata is complete before anything is stored.
    attempt_ref = new_attempt_ref()
    try:
        methods = list(payment_method_types) if payment_method_types is not None else paymongo.checkout_payment_methods()
    except Exception as e:
        current_app.logger.warning('Checkout payment-method lookup failed: %s', e)
        return None, 'Could not load the enabled PayMongo payment methods. Check gateway settings and try again.'
    payload = {
        "line_items": line_items,
        "description": f"EnergyWize corporate training invoice {invoice['reference']}",
        "reference_number": invoice["reference"],
        "success_url": success_url,
        "cancel_url": cancel_url,
        "payment_method_types": methods,
        "metadata": {"reference": invoice["reference"], "kind": "corporate",
                     "attempt_ref": attempt_ref},
        "amount_centavos": int(invoice["amount_centavos"]),
        "trainee_count": len(items),
    }

    # Written down BEFORE the remote call. If the response is lost, the
    # idempotency key survives and recovery can replay it.
    attempt, err = reserve_attempt(
        invoice["id"], int(invoice["amount_centavos"]), invoice["reference"],
        paymongo.environment(), payload, created_by=actor_id,
        attempt_ref=attempt_ref)
    if err:
        return None, err

    try:
        session = paymongo.create_checkout_session(**outbound_args(payload),
                                                   idempotency_key=attempt["idempotency_key"])
    except Exception as e:
        # Distinguish "definitely refused" from "we never saw the answer".
        # Only a clear 4xx is a refusal; anything else may have succeeded.
        definite = "PayMongo 4" in str(e)
        if definite:
            mark_attempt_failed(attempt["attempt_ref"], e)
            return None, f"The payment gateway refused the request: {e}"
        mark_attempt_unknown(attempt["attempt_ref"], e)
        current_app.logger.warning("Checkout create outcome unknown for %s: %s",
                                   invoice["reference"], e)
        return None, ("The gateway did not confirm whether the link was "
                      "created. Run reconciliation before trying again.")

    record_session(attempt["attempt_ref"], session["id"],
                   session.get("checkout_url"), session.get("payment_intent_id"))
    add_corporate_event(invoice["id"], actor_id, "checkout_session_created",
                        f"Hosted checkout session {session['id']} created "
                        f"({paymongo.environment()} mode).")
    return open_attempt(invoice["id"]), None


# ── The one validation gate ──────────────────────────────────────────────────

def validate_and_settle(session, source, actor_id=None):
    """Validate a session snapshot and settle exactly once. (settled, message).

    `source` names the entry point for the audit trail: webhook | poll |
    return | reconcile.
    """
    from admin.corporate import settle_corporate_payment

    cs_id = session.get("id")
    if not cs_id:
        raise SettlementRefused("Event carried no checkout session id.")

    # 1. Identity — our own stored session id is the only authority. Metadata
    #    and reference_number are hints; reference_number in particular has no
    #    documented uniqueness, so it can locate but never authorise.
    attempt = attempt_by_session(cs_id)
    if not attempt:
        raise SettlementRefused(
            f"No attempt matches checkout session {cs_id}. Money may have "
            f"arrived for a session this system did not create.")

    invoice = get_corporate_payment(cid=attempt["corporate_payment_id"])
    if not invoice:
        raise SettlementRefused(f"Attempt {attempt['attempt_ref']} has no invoice.")

    # 5. Environment — requires EXPLICIT matching evidence, twice over.
    #
    #    A missing `livemode` is refused rather than accepted: absence of
    #    evidence is not evidence of a match, and treating it as one is how a
    #    sandbox event settles live money.
    #
    #    The attempt's own recorded environment is checked as well, so an
    #    invoice whose session was created under a different key cannot be
    #    settled by an event that merely agrees with the CURRENT key.
    current_env = paymongo.environment()
    expect_live = current_env == "live"
    livemode = session.get("livemode")
    if livemode is None:
        flag_attention(invoice["id"],
                       f"Event from {source} carried no livemode flag; refusing "
                       f"to settle without explicit environment evidence.")
        raise SettlementRefused("Event carried no environment evidence — "
                                "refusing to settle.")
    if bool(livemode) != expect_live:
        flag_attention(invoice["id"],
                       f"Environment mismatch from {source}: livemode={livemode} "
                       f"but this process is configured for {current_env} mode.")
        raise SettlementRefused("Environment mismatch — refusing to settle.")
    if (attempt.get("environment") or "") != current_env:
        flag_attention(invoice["id"],
                       f"Attempt {attempt['attempt_ref']} was created in "
                       f"'{attempt.get('environment')}' mode but this process "
                       f"runs in '{current_env}'. Refusing to settle.")
        raise SettlementRefused("Attempt environment does not match this "
                                "process — refusing to settle.")

    # 2. Paid status
    paid = paymongo.paid_payment(session)
    if not paid:
        return False, f"No settled payment on session {cs_id} yet."

    # 3 & 4. Exact amount and currency, against the IMMUTABLE request
    #        snapshot rather than anything the event asserts about itself.
    if (paid.get("currency") or "").upper() != "PHP":
        flag_attention(invoice["id"],
                       f"Currency mismatch from {source}: paid "
                       f"{paid.get('currency')} on {cs_id}.")
        raise SettlementRefused("Currency is not PHP — refusing to settle.")
    if int(paid.get("amount") or 0) != int(attempt["request_amount_centavos"]):
        flag_attention(invoice["id"],
                       f"Amount mismatch from {source}: paid "
                       f"{paid.get('amount')} centavos, attempt requested "
                       f"{attempt['request_amount_centavos']}.")
        raise SettlementRefused("Paid amount does not match the invoice — "
                                "refusing to settle.")

    # Late money: the invoice is no longer payable, but a real payment landed.
    if invoice["status"] != "pending":
        mark_attempt_paid(attempt["attempt_ref"], paid.get("id"))
        confirm_settlement(attempt["attempt_ref"])
        if invoice["status"] != "paid":
            flag_attention(invoice["id"],
                           f"Payment {paid.get('id')} arrived via {source} for an "
                           f"invoice that is {invoice['status']}. Refund or "
                           f"re-open — do not ignore.")
            add_corporate_event(invoice["id"], actor_id, "late_payment_received",
                                f"Money received after the invoice was "
                                f"{invoice['status']}.")
            return False, (f"Payment received for a {invoice['status']} invoice. "
                           f"Flagged for resolution.")
        return False, "Already settled."

    # Order matters. Settle the invoice FIRST, then record it on the attempt.
    #
    # The reverse order left a crash window: an attempt marked `paid` is no
    # longer in OPEN_STATES, so the reconciliation sweep would never look at
    # it again and a real payment could sit unsettled forever. This way a
    # crash leaves the attempt `active` — still swept, still self-healing —
    # and `unconfirmed_settlements()` catches the narrower case where the
    # invoice flipped but the attempt bookkeeping did not.
    method = paid.get('method') or 'checkout'
    if method not in ('card','gcash','qrph','paymaya','grab_pay','shopeepay'):
        method = 'checkout'
    rec = settle_corporate_payment(cid=invoice["id"], actor_id=actor_id,
                                  payment_id=paid.get('id'), method=method)
    if not rec:
        # The guarded UPDATE matched nothing. That has TWO very different
        # causes, and assuming the benign one loses money:
        #
        #   * another entry point settled first  -> invoice is now 'paid'
        #   * cancellation or expiry won the race -> invoice is closed and this
        #     payment is real money against something no longer payable
        #
        # So re-read the invoice and confirm only on the first.
        mark_attempt_paid(attempt["attempt_ref"], paid.get("id"),
                          session.get("payment_intent_id"))
        fresh = get_corporate_payment(cid=invoice["id"])
        if fresh and fresh["status"] == "paid":
            confirm_settlement(attempt["attempt_ref"])
            return False, "Already settled by another entry point."

        status_now = (fresh or {}).get("status", "missing")
        flag_attention(invoice["id"],
                       f"Payment {paid.get('id')} confirmed via {source} but the "
                       f"invoice became '{status_now}' before settlement. The "
                       f"money is real and unapplied — refund or re-open.")
        record_unresolved_event(
            source, "settlement_lost_race",
            f"Invoice became '{status_now}' during settlement.",
            {"session": session}, cs_id=cs_id, payment_id=paid.get("id"),
            reference_hint=invoice.get("reference"),
            amount_centavos=paid.get("amount"), currency=paid.get("currency"),
            livemode=session.get("livemode"))
        add_corporate_event(invoice["id"], actor_id, "settlement_lost_race",
                            f"Payment arrived but the invoice was "
                            f"'{status_now}' by settlement time.")
        # Deliberately NOT confirmed: settlement did not happen, so the
        # reconciliation queue must keep seeing this.
        return False, (f"Payment confirmed but the invoice is '{status_now}'. "
                       f"Preserved as unresolved and flagged.")
    mark_attempt_paid(attempt["attempt_ref"], paid.get("id"),
                      session.get("payment_intent_id"))
    confirm_settlement(attempt["attempt_ref"])

    audit_log(actor_id, "corporate_settled_via_checkout", "corporate_payment",
              invoice["id"], f"Settled from {source}: session {cs_id}, "
                             f"payment {paid.get('id')}.")
    return True, f"Invoice {invoice['reference']} settled."


def poll_attempt(attempt, source="poll", actor_id=None):
    """Retrieve the SESSION (not the intent) and settle if it reads paid.

    A v2 session may have no payment intent at all until the customer pays, so
    the intent-only poll used by the legacy flow cannot answer here.
    """
    if not attempt.get("checkout_session_id"):
        return False, "This attempt has no session to poll yet."
    session = paymongo.retrieve_checkout_session(attempt["checkout_session_id"])
    try:
        return validate_and_settle(session, source, actor_id)
    except SettlementRefused as e:
        return False, str(e)


def expire_attempt_remotely(attempt, actor_id=None):
    """Close a session at the gateway, then locally.

    Order matters: sessions never expire on their own, so if the remote call
    fails the local row must stay open — marking it expired locally while a
    payable page is still live is how a company gets charged for an invoice
    this system considers closed.
    """
    if not attempt.get("checkout_session_id"):
        # A missing session id is NOT proof that no remote session exists —
        # the create response may simply have been lost.
        #
        # So this does NOT mark the attempt expired. Doing so would move it out
        # of OPEN_STATES and release `uq_corp_attempt_open`, letting a second
        # payable session be created for the same invoice while the first may
        # still be live. An attention flag records the problem; it does not
        # preserve the guard. The attempt therefore stays open — blocking
        # replacements — until remote closure or nonexistence is actually
        # established, by replay inside the key window or by a human checking
        # the PayMongo dashboard.
        flag_attention(attempt["corporate_payment_id"],
                       f"Attempt {attempt['attempt_ref']} has no recorded "
                       f"session id and cannot be closed safely. If a session "
                       f"was created it may still be payable — check PayMongo "
                       f"for reference {attempt['request_reference']}, then "
                       f"resolve the attempt explicitly.")
        return False, ("Cannot close this attempt: no session id was recorded, "
                       "so a live remote session cannot be ruled out. It stays "
                       "open and keeps blocking new links until resolved.")
    try:
        paymongo.expire_checkout_session(attempt["checkout_session_id"])
    except Exception as e:
        current_app.logger.warning("Remote expire failed for %s: %s",
                                   attempt["checkout_session_id"], e)
        flag_attention(attempt["corporate_payment_id"],
                       f"Could not expire checkout session "
                       f"{attempt['checkout_session_id']}: {e}. The link may "
                       f"still be payable.")
        return False, ("The gateway session could not be expired, so the link "
                       "may still take payment. Flagged for resolution.")
    mark_attempt_expired(attempt["attempt_ref"])
    add_corporate_event(attempt["corporate_payment_id"], actor_id,
                        "checkout_session_expired",
                        f"Session {attempt['checkout_session_id']} expired remotely.")
    return True, "Checkout session expired."
