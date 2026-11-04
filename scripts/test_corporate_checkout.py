"""Hosted-checkout payment tests — isolated DB, mocked gateway, mock mail.

No network call is made: paymongo.MOCK_GATEWAY defaults on.

    cd src; ..\\venv\\Scripts\\python.exe ..\\scripts\\test_corporate_checkout.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from _testdb import use_test_db, assert_isolated   # noqa: E402

use_test_db(recreate=True)
os.environ["MAIL_TRANSPORT"] = "mock"
os.environ["PAYMONGO_MOCK"] = "1"
os.environ.setdefault("PAYMONGO_SECRET_KEY", "sk_test_fake_for_tests")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import json                                        # noqa: E402
import threading                                   # noqa: E402
import uuid                                        # noqa: E402
from datetime import datetime, timedelta           # noqa: E402

import paymongo                                    # noqa: E402
from app import app                                # noqa: E402
import admin.corporate as corporate_routes          # noqa: E402

# These regressions validate gateway state and settlement, not Polygon RPC.
real_anchor_receipt = corporate_routes._anchor_receipt
corporate_routes._anchor_receipt = lambda *args, **kwargs: False
from db import (get_db, dict_cur, create_corporate_payment, get_corporate_payment,
                replayable_attempts, expired_key_attempts, unconfirmed_settlements,
                closable_attempts, unresolved_events, outbound_args,
                confirm_settlement, mark_attempt_paid, cancel_corporate_payment,
                new_attempt_ref,
                issue_pay_token, revoke_pay_token, payment_by_token,
                reserve_attempt, open_attempt, record_session, attempt_by_session,
                mark_attempt_unknown, get_attempts, payments_needing_attention,
                open_attempts_all)                 # noqa: E402
from corporate_checkout import (ensure_checkout_session, validate_and_settle,
                                poll_attempt, expire_attempt_remotely,
                                SettlementRefused)  # noqa: E402

app.config["WTF_CSRF_ENABLED"] = False
results = []


def check(name, passed, detail=""):
    results.append((name, passed, detail))
    print(f"  [{'PASS' if passed else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def _mkuser(role, email):
    c = get_db(); cur = c.cursor()
    cur.execute("""INSERT INTO users (role, fname, lname, email, password_hash,
                   payment_status) VALUES (%s,'T','U',%s,'x','unpaid')
                   ON CONFLICT (email) DO UPDATE SET role=EXCLUDED.role
                   RETURNING id""", (role, email))
    uid = cur.fetchone()[0]; c.commit(); cur.close(); c.close()
    return uid


def _invoice(amount_centavos=500000, hours=24):
    uid = _mkuser("trainee", f"t{uuid.uuid4().hex[:8]}@acme.com")
    cid, ref = create_corporate_payment(
        "Acme Power", "Jo Cruz", "hr@acme.com", "0917",
        [{"user_id": uid, "training_type": "training", "form_type": "training",
          "price_php": amount_centavos / 100.0, "price_label": "Training"}],
        amount_centavos / 100.0, None, None, amount_centavos,
        datetime.now() + timedelta(hours=hours), None)
    return get_corporate_payment(cid=cid), uid


def _session(cs_id, amount, currency="PHP", status="paid", livemode=False):
    return {"id": cs_id, "status": "active", "livemode": livemode,
            "payment_intent_id": None, "reference_number": None,
            "payments": [{"id": f"pay_{uuid.uuid4().hex[:8]}", "status": status,
                          "amount": amount, "currency": currency}]}


print(f"\nisolated database: {assert_isolated()}")
print(f"gateway mocked   : {paymongo.MOCK_GATEWAY}")
check("gateway is mocked (no network)", paymongo.MOCK_GATEWAY is True)
check("environment derives from the key", paymongo.environment() == "test",
      paymongo.environment())

print("\n1. API versions are per-operation")
check("create uses v2", paymongo.CHECKOUT_CREATE_BASE.endswith("/v2"))
check("retrieve uses the working v1 resource route", paymongo.CHECKOUT_RETRIEVE_BASE.endswith("/v1"))
check("expire stays on v1", paymongo.CHECKOUT_EXPIRE_BASE.endswith("/v1"))
check("the legacy client base is untouched", paymongo.BASE.endswith("/v1"))

print("\n2. Attempt is persisted BEFORE the remote call")
inv, uid = _invoice()
with app.test_request_context():
    attempt, err = ensure_checkout_session(inv, "http://x/ok", "http://x/no")
check("session created", attempt is not None and err is None, str(err))
check("idempotency key persisted", bool(attempt["idempotency_key"]))
check("key is NOT day-bucketed",
      datetime.now().strftime("%Y%m%d") not in attempt["idempotency_key"],
      attempt["idempotency_key"])
check("immutable request snapshot stored",
      json.loads(attempt["request_payload"])["amount_centavos"] == 500000)
check("intent id is NULL at creation (v2 defers it)",
      attempt["payment_intent_id"] is None)
check("session id stored separately from intent id",
      attempt["checkout_session_id"].startswith("cs_"))
check("environment recorded on the attempt", attempt["environment"] == "test")

print("\n3. Reuse, never a second live session")
with app.test_request_context():
    again, err2 = ensure_checkout_session(inv, "http://x/ok", "http://x/no")
check("an active session is REUSED", again["attempt_ref"] == attempt["attempt_ref"])
check("exactly one attempt exists", len(get_attempts(inv["id"])) == 1)

print("\n4. Unknown outcome blocks replacement")
inv2, _ = _invoice()
a2, _ = reserve_attempt(inv2["id"], inv2["amount_centavos"], inv2["reference"],
                        "test", {"line_items": []})
mark_attempt_unknown(a2["attempt_ref"], "connection reset")
with app.test_request_context():
    blocked, why = ensure_checkout_session(inv2, "http://x/ok", "http://x/no")
check("refuses while an outcome is unknown", blocked is None)
check("refusal names reconciliation", "reconcil" in (why or "").lower(), str(why))
a3, err3 = reserve_attempt(inv2["id"], inv2["amount_centavos"], inv2["reference"],
                           "test", {"line_items": []})
check("database refuses a second OPEN attempt", a3 is None, str(err3))

print("\n5. Settlement validation gate")
cs = attempt["checkout_session_id"]

with app.test_request_context():
    try:
        validate_and_settle(_session("cs_not_ours", 500000), "webhook")
        check("unknown session is refused", False, "no exception")
    except SettlementRefused as e:
        check("unknown session is refused", "No attempt matches" in str(e))

with app.test_request_context():
    try:
        validate_and_settle(_session(cs, 499999), "webhook")
        check("wrong amount is refused", False, "no exception")
    except SettlementRefused as e:
        check("wrong amount is refused", "amount" in str(e).lower())
check("amount mismatch raises a persistent flag",
      any(p["id"] == inv["id"] for p in payments_needing_attention()))

with app.test_request_context():
    try:
        validate_and_settle(_session(cs, 500000, currency="USD"), "webhook")
        check("wrong currency is refused", False, "no exception")
    except SettlementRefused as e:
        check("wrong currency is refused", "currency" in str(e).lower())

with app.test_request_context():
    try:
        validate_and_settle(_session(cs, 500000, livemode=True), "webhook")
        check("live event against a test key is refused", False, "no exception")
    except SettlementRefused as e:
        check("live event against a test key is refused",
              "environment" in str(e).lower())

with app.test_request_context():
    ok, msg = validate_and_settle(_session(cs, 500000, status="awaiting_payment"),
                                  "webhook")
check("unpaid session does not settle", ok is False, msg)

print("\n6. Correct event settles exactly once")
with app.test_request_context():
    ok, msg = validate_and_settle(_session(cs, 500000), "webhook")
check("valid event settles the invoice", ok is True, msg)
check("invoice is paid", get_corporate_payment(cid=inv["id"])["status"] == "paid")
c = get_db(); cur = c.cursor()
cur.execute("SELECT payment_status FROM users WHERE id=%s", (uid,))
check("listed trainee flipped to paid", cur.fetchone()[0] == "paid")
cur.close(); c.close()

with app.test_request_context():
    ok2, msg2 = validate_and_settle(_session(cs, 500000), "webhook")
check("duplicate event is harmless", ok2 is False and "settled" in msg2.lower(), msg2)
att = attempt_by_session(cs)
check("attempt marked paid once", att["status"] == "paid" and att["paid_payment_id"])

print("\n7. Late money stays visible")
inv3, _ = _invoice()
a4, _ = reserve_attempt(inv3["id"], inv3["amount_centavos"], inv3["reference"],
                        "test", {"line_items": []})
record_session(a4["attempt_ref"], "cs_late_001", "http://x/pay")
c = get_db(); cur = c.cursor()
cur.execute("UPDATE corporate_payments SET status='cancelled' WHERE id=%s", (inv3["id"],))
c.commit(); cur.close(); c.close()
with app.test_request_context():
    ok3, msg3 = validate_and_settle(_session("cs_late_001", inv3["amount_centavos"]),
                                    "webhook")
check("payment for a cancelled invoice does not settle", ok3 is False, msg3)
check("it raises an attention flag",
      any(p["id"] == inv3["id"] for p in payments_needing_attention()))
check("the message says it was flagged", "flagged" in msg3.lower(), msg3)

print("\n8. Public payment link")
inv4, _ = _invoice()
tok, ver = issue_pay_token(inv4["id"])
check("token issued and link_version bumped", tok and ver == 1, f"v{ver}")
got, reason = payment_by_token(tok)
check("token resolves to its invoice", got and got["id"] == inv4["id"])
check("plaintext token is not stored",
      get_corporate_payment(cid=inv4["id"])["pay_token_hash"] != tok)
check("unknown token refused", payment_by_token("nope")[0] is None)

cl = app.test_client()
with app.test_request_context():
    a5, _ = ensure_checkout_session(inv4, "http://x/ok", "http://x/no")
r = cl.get(f"/pay/corporate/{tok}")
body = r.get_data(as_text=True)
check("public page renders", r.status_code == 200, f"HTTP {r.status_code}")
check("shows the amount", "5,000.00" in body)
check("does NOT list trainee names", "@acme.com" not in body)
check("no-store header", "no-store" in (r.headers.get("Cache-Control") or ""))
check("noindex header", "noindex" in (r.headers.get("X-Robots-Tag") or ""))
check("external referrers suppressed with HTTPS forms supported", r.headers.get("Referrer-Policy") == "same-origin")

revoke_pay_token(inv4["id"])
r = cl.get(f"/pay/corporate/{tok}")
check("revoked link stops working", r.status_code == 404)

print("\n9. Return redirect is not payment evidence")
tok2, _ = issue_pay_token(inv4["id"])
r = cl.get(f"/pay/corporate/{tok2}/return")
body = r.get_data(as_text=True)
check("return page does not claim payment", r.status_code == 200
      and "Payment received" not in body, f"HTTP {r.status_code}")
check("it says the payment is unconfirmed",
      "pending" in body.lower() or "not confirmed" in body.lower())

print("\n10. Expiry closes the gateway session first")
inv5, _ = _invoice(hours=-1)       # already lapsed
with app.test_request_context():
    a6, _ = ensure_checkout_session(inv5, "http://x/ok", "http://x/no")
with app.test_request_context():
    ok5, msg5 = expire_attempt_remotely(a6)
check("remote expire then local", ok5 is True, msg5)
check("attempt is expired locally",
      get_attempts(inv5["id"])[0]["status"] == "expired")
check("no open attempt remains", open_attempt(inv5["id"]) is None)

print("\n11. Webhook route handles the checkout envelope")
inv6, uid6 = _invoice()
with app.test_request_context():
    a7, _ = ensure_checkout_session(inv6, "http://x/ok", "http://x/no")
cs7 = a7["checkout_session_id"]
event = {"data": {"type": "checkout_session.payment.paid",
                  "livemode": False,
                  "data": {"id": cs7, "attributes": {
                      "reference_number": inv6["reference"],
                      "payments": [{"id": "pay_wh_1", "attributes": {
                          "status": "paid", "amount": inv6["amount_centavos"],
                          "currency": "PHP"}}]}}}}
import hmac as _hmac, hashlib as _hl, json as _json, time as _t
secret = "whsec_test"
os.environ["PAYMONGO_WEBHOOK_SECRET"] = secret
raw = _json.dumps(event).encode()
ts = str(int(_t.time()))
sig = _hmac.new(secret.encode(), f"{ts}.{raw.decode()}".encode(), _hl.sha256).hexdigest()
r = cl.post("/payment/webhook", data=raw,
            headers={"Paymongo-Signature": f"t={ts},te={sig}",
                     "Content-Type": "application/json"})
check("signed checkout webhook accepted", r.status_code == 200, f"HTTP {r.status_code}")
check("invoice settled through the webhook",
      get_corporate_payment(cid=inv6["id"])["status"] == "paid")
r2 = cl.post("/payment/webhook", data=raw,
             headers={"Paymongo-Signature": f"t={ts},te={sig}",
                      "Content-Type": "application/json"})
check("duplicate delivery is harmless", r2.status_code == 200
      and get_corporate_payment(cid=inv6["id"])["status"] == "paid")

bad = cl.post("/payment/webhook", data=raw,
              headers={"Paymongo-Signature": "t=1,te=deadbeef",
                       "Content-Type": "application/json"})
check("bad signature rejected", bad.status_code == 400, f"HTTP {bad.status_code}")

print("\n13. Recovery replays the EXACT stored request")
inv7, _ = _invoice()
with app.test_request_context():
    a8, _ = ensure_checkout_session(inv7, "http://live/ok", "http://live/cancel")
stored = json.loads(get_attempts(inv7["id"])[0]["request_payload"])
check("success_url persisted", stored["success_url"] == "http://live/ok",
      str(stored.get("success_url")))
check("cancel_url persisted", stored["cancel_url"] == "http://live/cancel")
check("metadata.attempt_ref persisted",
      stored["metadata"].get("attempt_ref") == a8["attempt_ref"])
args = outbound_args(stored)
check("replay args reproduce the URLs",
      args["success_url"] == "http://live/ok" and args["cancel_url"] == "http://live/cancel")
check("replay args reproduce metadata",
      args["metadata"].get("attempt_ref") == a8["attempt_ref"])

print("\n14. Replay window is enforced")
inv8, _ = _invoice()
a9, _ = reserve_attempt(inv8["id"], inv8["amount_centavos"], inv8["reference"],
                        "test", {"line_items": []})
mark_attempt_unknown(a9["attempt_ref"], "timeout")
check("fresh unknown attempt IS replayable",
      any(x["attempt_ref"] == a9["attempt_ref"] for x in replayable_attempts()))
c = get_db(); cur = c.cursor()
cur.execute("UPDATE corporate_payment_attempts SET idempotency_expires_at = NOW() - "
            "interval '1 hour' WHERE attempt_ref=%s", (a9["attempt_ref"],))
c.commit(); cur.close(); c.close()
check("past 24h it is NOT auto-replayed",
      not any(x["attempt_ref"] == a9["attempt_ref"] for x in replayable_attempts()))
check("it surfaces for investigation instead",
      any(x["attempt_ref"] == a9["attempt_ref"] for x in expired_key_attempts()))

print("\n15. Crash states are recoverable")
inv9, _ = _invoice()
a10, _ = reserve_attempt(inv9["id"], inv9["amount_centavos"], inv9["reference"],
                         "test", {"line_items": []})
check("a FRESH 'creating' attempt is owned, not swept",
      not any(x["attempt_ref"] == a10["attempt_ref"] for x in replayable_attempts()),
      "a live creation lease means the request may still be in flight")
c = get_db(); cur = c.cursor()
cur.execute("UPDATE corporate_payment_attempts SET creation_lease_until = NOW() - "
            "interval '1 minute' WHERE attempt_ref=%s", (a10["attempt_ref"],))
c.commit(); cur.close(); c.close()
check("once its lease lapses it IS recoverable",
      any(x["attempt_ref"] == a10["attempt_ref"] for x in replayable_attempts()),
      "creating must not be stranded forever")

inv10, _ = _invoice()
a11, _ = reserve_attempt(inv10["id"], inv10["amount_centavos"], inv10["reference"],
                         "test", {"line_items": []})
record_session(a11["attempt_ref"], "cs_orphan_1", "http://x")
mark_attempt_paid(a11["attempt_ref"], "pay_orphan")   # crash before invoice flip
check("paid attempt with unsettled invoice is caught",
      any(x["attempt_ref"] == a11["attempt_ref"] for x in unconfirmed_settlements()))
confirm_settlement(a11["attempt_ref"])
check("confirming removes it from the queue",
      not any(x["attempt_ref"] == a11["attempt_ref"] for x in unconfirmed_settlements()))

print("\n16. Environment evidence must be explicit")
inv11, _ = _invoice()
with app.test_request_context():
    a12, _ = ensure_checkout_session(inv11, "http://x/ok", "http://x/no")
cs12 = a12["checkout_session_id"]
sess_no_live = _session(cs12, inv11["amount_centavos"])
sess_no_live.pop("livemode")
with app.test_request_context():
    try:
        validate_and_settle(sess_no_live, "webhook")
        check("missing livemode is REFUSED", False, "it settled")
    except SettlementRefused as e:
        check("missing livemode is REFUSED", "environment evidence" in str(e), str(e))

c = get_db(); cur = c.cursor()
cur.execute("UPDATE corporate_payment_attempts SET environment='live' WHERE attempt_ref=%s",
            (a12["attempt_ref"],))
c.commit(); cur.close(); c.close()
with app.test_request_context():
    try:
        validate_and_settle(_session(cs12, inv11["amount_centavos"]), "webhook")
        check("attempt-environment mismatch is REFUSED", False, "it settled")
    except SettlementRefused as e:
        check("attempt-environment mismatch is REFUSED",
              "environment" in str(e).lower(), str(e))

print("\n17. Cancelled invoices still get their session closed")
inv12, _ = _invoice()
with app.test_request_context():
    a13, _ = ensure_checkout_session(inv12, "http://x/ok", "http://x/no")
cancel_corporate_payment(inv12["id"])
check("cancelled invoice appears in closable work",
      any(x["attempt_ref"] == a13["attempt_ref"] for x in closable_attempts()),
      "a cancelled invoice must not leave a payable session")

print("\n18. Blind closure without a session id is flagged")
inv13, _ = _invoice()
a14, _ = reserve_attempt(inv13["id"], inv13["amount_centavos"], inv13["reference"],
                         "test", {"line_items": []})
mark_attempt_unknown(a14["attempt_ref"], "lost")
with app.test_request_context():
    ok14, msg14 = expire_attempt_remotely(dict(a14, status="unknown"))
check("REFUSES to close without a session id",
      ok14 is False and "cannot be ruled out" in msg14, msg14)
check("and raises an attention flag",
      any(p["id"] == inv13["id"] for p in payments_needing_attention()))
# The guard, not just the flag: the attempt must still block replacements.
still = open_attempt(inv13["id"])
check("attempt STAYS open after the refusal",
      still is not None and still["attempt_ref"] == a14["attempt_ref"],
      str(still and still["status"]))
a15, err15 = reserve_attempt(inv13["id"], inv13["amount_centavos"],
                             inv13["reference"], "test", {"line_items": []})
check("duplicate-session guard is PRESERVED", a15 is None, str(err15))

print("\n19. Unmatched webhook money is STORED, not just logged")
before = len(unresolved_events())
ev = {"data": {"type": "checkout_session.payment.paid", "livemode": False,
               "data": {"id": "cs_never_persisted", "attributes": {
                   "reference_number": "CORP-GHOST",
                   "payments": [{"id": "pay_ghost", "attributes": {
                       "status": "paid", "amount": 123456, "currency": "PHP"}}]}}}}
raw2 = _json.dumps(ev).encode()
ts2 = str(int(_t.time()))
sig2 = _hmac.new(secret.encode(), f"{ts2}.{raw2.decode()}".encode(), _hl.sha256).hexdigest()
r = cl.post("/payment/webhook", data=raw2,
            headers={"Paymongo-Signature": f"t={ts2},te={sig2}",
                     "Content-Type": "application/json"})
check("unmatched event still acknowledged", r.status_code == 200)
evs = unresolved_events()
check("it is persisted for recovery", len(evs) == before + 1, f"{before} -> {len(evs)}")
if evs:
    e0 = evs[0]
    check("session id captured", e0["checkout_session_id"] == "cs_never_persisted")
    check("amount captured", e0["amount_centavos"] == 123456)
    check("raw event retained", "cs_never_persisted" in e0["raw_event"])


print("\n20. Atomic creation: complete payload in ONE insert")
inv14, _ = _invoice()
ref14 = new_attempt_ref()
payload14 = {"line_items": [], "success_url": "http://a/ok",
             "cancel_url": "http://a/no", "description": "d",
             "reference_number": inv14["reference"],
             "metadata": {"reference": inv14["reference"], "attempt_ref": ref14}}
a16, _ = reserve_attempt(inv14["id"], inv14["amount_centavos"], inv14["reference"],
                         "test", payload14, attempt_ref=ref14)
check("attempt_ref is the one the caller minted", a16["attempt_ref"] == ref14)
stored14 = json.loads(a16["request_payload"])
check("the FIRST committed row already carries attempt_ref",
      stored14["metadata"].get("attempt_ref") == ref14,
      "no second-stage rewrite window")
check("and the URLs", stored14["success_url"] == "http://a/ok")
check("no payload-rewrite helper is exported",
      not hasattr(__import__("db"), "update_attempt_payload"))

print("\n21. Creation ownership blocks a racing sweep")
inv15, _ = _invoice()
with app.test_request_context():
    a17, _ = ensure_checkout_session(inv15, "http://x/ok", "http://x/no")
c = get_db(); cur = c.cursor()
cur.execute("UPDATE corporate_payment_attempts SET status='creating', "
            "checkout_session_id=NULL, creation_lease_until = NOW() + interval '2 minutes' "
            "WHERE attempt_ref=%s", (a17["attempt_ref"],))
c.commit(); cur.close(); c.close()
check("an owned in-flight attempt is NOT swept",
      not any(x["attempt_ref"] == a17["attempt_ref"] for x in replayable_attempts()))
c = get_db(); cur = c.cursor()
cur.execute("UPDATE corporate_payment_attempts SET creation_lease_until = NOW() - "
            "interval '1 second' WHERE attempt_ref=%s", (a17["attempt_ref"],))
c.commit(); cur.close(); c.close()
check("it becomes sweepable only once ownership lapses",
      any(x["attempt_ref"] == a17["attempt_ref"] for x in replayable_attempts()))

print("\n22. Lost settlement race is preserved, not confirmed")
inv16, _ = _invoice()
with app.test_request_context():
    a18, _ = ensure_checkout_session(inv16, "http://x/ok", "http://x/no")
cs18 = a18["checkout_session_id"]
# Cancellation wins the race between validation and the guarded UPDATE.
cancel_corporate_payment(inv16["id"])
c = get_db(); cur = c.cursor()
cur.execute("UPDATE corporate_payments SET status='pending' WHERE id=%s", (inv16["id"],))
c.commit(); cur.close(); c.close()

import corporate_checkout as _cc
_real_settle = _cc.__dict__.get("settle_corporate_payment")


def _settle_but_cancelled(cid=None, actor_id=None, **kw):
    """Simulate cancellation landing between validation and settlement."""
    cc = get_db(); ccur = cc.cursor()
    ccur.execute("UPDATE corporate_payments SET status='cancelled' WHERE id=%s", (cid,))
    cc.commit(); ccur.close(); cc.close()
    return None            # guarded UPDATE matched nothing


import admin.corporate as _ac
_orig = _ac.settle_corporate_payment
_ac.settle_corporate_payment = _settle_but_cancelled
with app.test_request_context():
    ok18, msg18 = validate_and_settle(_session(cs18, inv16["amount_centavos"]),
                                      "webhook")
_ac.settle_corporate_payment = _orig

check("does not report success", ok18 is False, msg18)
check("names the invoice state rather than claiming a duplicate",
      "cancelled" in msg18.lower(), msg18)
a18b = attempt_by_session(cs18)
check("attempt is NOT confirmed as settled",
      a18b["settlement_confirmed_at"] is None, str(a18b["settlement_confirmed_at"]))
check("it stays in the unconfirmed queue for reconciliation",
      any(x["attempt_ref"] == a18["attempt_ref"] for x in unconfirmed_settlements()))
check("attention flag raised on the invoice",
      any(p["id"] == inv16["id"] for p in payments_needing_attention()))
check("the payment is stored as an unresolved event",
      any(e["checkout_session_id"] == cs18 for e in unresolved_events()))

print("\n23. Genuine duplicate still confirms cleanly")
inv17, _ = _invoice()
with app.test_request_context():
    a19, _ = ensure_checkout_session(inv17, "http://x/ok", "http://x/no")
cs19 = a19["checkout_session_id"]
with app.test_request_context():
    ok19a, _ = validate_and_settle(_session(cs19, inv17["amount_centavos"]), "webhook")
with app.test_request_context():
    ok19b, msg19 = validate_and_settle(_session(cs19, inv17["amount_centavos"]), "poll")
check("first settles", ok19a is True)
# Either duplicate path is correct: the invoice may already read paid when
# re-read, or the guarded UPDATE may lose the race. Both must refuse to
# settle twice and both must say so.
check("second reports an already-settled duplicate",
      ok19b is False and "settled" in msg19.lower(), msg19)
a19b = attempt_by_session(cs19)
check("and IS confirmed (invoice really is paid)",
      a19b["settlement_confirmed_at"] is not None)


print("\n12. Reconciliation sees what is open")
check("open attempts are enumerable for a scheduler",
      isinstance(open_attempts_all(), list))

print('\nPayMongo sandbox simulation controls and gateway transition')
from unittest.mock import patch, Mock
from db import retire_offline_mock_attempt
with patch.object(paymongo.requests, 'get') as gateway_get:
    check('offline methods include card, GCash and QR Ph', paymongo.checkout_payment_methods() == ['card','gcash','qrph'])
    check('offline method display never calls gateway', not gateway_get.called)
with patch.object(paymongo, 'MOCK_GATEWAY', False), patch.dict(os.environ, {'PAYMONGO_SECRET_KEY':'sk_live_fake_capabilities'}), patch.object(paymongo.requests, 'get', return_value=Mock(ok=True, json=lambda: ['qrph'])):
    check('live checkout requests only account-enabled methods', paymongo.checkout_payment_methods() == ['qrph'])
with patch.object(paymongo, 'MOCK_GATEWAY', False), patch.object(paymongo.requests, 'get') as capability_lookup:
    check('sandbox can request the three gateway-verified test methods', paymongo.checkout_payment_methods() == ['card','gcash','qrph'] and not capability_lookup.called)

def refuses_action(snapshot, intent=None):
    with patch.object(paymongo, 'MOCK_GATEWAY', False), patch.object(paymongo, 'retrieve_checkout_session', return_value=snapshot), patch.object(paymongo.requests, 'get', return_value=Mock(ok=True,json=lambda: intent)):
        try:
            paymongo.checkout_test_action('cs_test_controls')
            return False
        except ValueError:
            return True

snapshot = {'id':'cs_test_controls','livemode':False,'payment_intent_id':'pi_test_controls'}
intent = {'data':{'id':'pi_test_controls','attributes':{'livemode':False,'next_action':{'code':{'test_url':'https://test-sources.paymongo.com/qrph/demo'}}}}}
with patch.object(paymongo, 'MOCK_GATEWAY', False), patch.object(paymongo, 'retrieve_checkout_session', return_value=snapshot), patch.object(paymongo.requests, 'get', return_value=Mock(ok=True,json=lambda: intent)):
    action = paymongo.checkout_test_action(snapshot['id'])
    check('QR simulation URL comes from PayMongo intent', action['url'] == intent['data']['attributes']['next_action']['code']['test_url'] and action['kind'] == 'qrph')
check('live session cannot supply a simulation URL', refuses_action({**snapshot,'livemode':True}, intent))
check('unmatched session cannot supply a simulation URL', refuses_action({**snapshot,'id':'cs_other'}, intent))
check('live intent cannot supply a simulation URL', refuses_action(snapshot, {'data':{'id':'pi_test_controls','attributes':{'livemode':True}}}))
check('unmatched intent cannot supply a simulation URL', refuses_action(snapshot, {'data':{'id':'pi_other','attributes':{'livemode':False}}}))
for bad_url in ['https://evil.test/pretend', 'javascript:alert(1)', 'https://paymongo.com.evil.test/test']:
    bad_intent = {'data':{'id':'pi_test_controls','attributes':{'livemode':False,'next_action':{'code':{'test_url':bad_url}}}}}
    check('foreign or unsafe simulation address refused: '+bad_url, refuses_action(snapshot,bad_intent))
with patch.object(paymongo, 'MOCK_GATEWAY', False), patch.object(paymongo, 'retrieve_checkout_session', return_value={**snapshot,'payment_intent_id':None}), patch.object(paymongo.requests, 'get') as gateway_get:
    check('v2 missing intent gives instructions without creating anything', paymongo.checkout_test_action(snapshot['id'])['url'] is None and not gateway_get.called)
with patch.dict(os.environ, {'PAYMONGO_SECRET_KEY':'sk_live_fake_guard'}), patch.object(paymongo, 'MOCK_GATEWAY', False), patch.object(paymongo.requests, 'get') as gateway_get:
    try:
        paymongo.checkout_test_action(snapshot['id']); rejected_live = False
    except ValueError:
        rejected_live = True
    check('live key refuses simulation before network access', rejected_live and not gateway_get.called)

sandbox_invoice, _ = _invoice()
with app.test_request_context():
    offline_attempt, _ = ensure_checkout_session(sandbox_invoice, 'http://localhost/return', 'http://localhost/cancel')
admin_user = _mkuser('admin', 'sandbox-admin@test.invalid')
with cl.session_transaction() as s:
    s['user_id'] = admin_user; s['user_role'] = 'admin'
connected = {'id':'cs_test_connected','checkout_url':'https://checkout.paymongo.com/test-connected','payment_intent_id':None}
with patch.object(paymongo, 'MOCK_GATEWAY', False), patch.object(paymongo, 'checkout_payment_methods', return_value=['card','qrph']), patch.object(paymongo, 'create_checkout_session', return_value=connected) as create_call:
    issued = cl.post(f"/admin/corporate/{sandbox_invoice['id']}/payment-link")
    check('admin can replace a verified offline mock with sandbox checkout', issued.status_code == 200)
    check('sandbox creation is called once', create_call.call_count == 1)
    check('only one open checkout remains', open_attempt(sandbox_invoice['id'])['checkout_session_id'] == connected['id'])
    old = next(a for a in get_attempts(sandbox_invoice['id']) if a['attempt_ref'] == offline_attempt['attempt_ref'])
    check('mock retirement is labelled honestly', old['status'] == 'expired' and 'No remote session was expired' in old['last_error'])
    token_sandbox = issued.get_json()['url'].rsplit('/',1)[-1]
    rendered = cl.get('/pay/corporate/'+token_sandbox).get_data(as_text=True)
    check('card simulation instructions include official test card', '4343 4343 4343 4345' in rendered)
    check('QR simulation instructions prohibit real wallet payment', 'Do not scan and pay a test QR' in rendered)
    with patch.object(paymongo, 'checkout_test_action', return_value={'url':'https://test-sources.paymongo.com/qrph/demo','kind':'qrph','message':'Test only'}):
        test_control = cl.get('/pay/corporate/'+token_sandbox+'/sandbox-action')
    check('public simulation lookup is scoped to the company token', test_control.status_code == 200 and test_control.get_json()['kind'] == 'qrph')
    with patch('corporate_checkout.poll_attempt', return_value=(False,'not paid yet')):
        pending_test = cl.get('/pay/corporate/'+token_sandbox+'/status')
    check('status lookup cannot claim payment from a test-link click', pending_test.get_json()['paid'] is False and get_corporate_payment(cid=sandbox_invoice['id'])['status'] == 'pending')
    with patch.dict(os.environ, {'PAYMONGO_SECRET_KEY':'sk_live_fake_guard'}):
        hidden_live = cl.get('/pay/corporate/'+token_sandbox+'/sandbox-action')
    check('simulation route is unavailable with a live key', hidden_live.status_code == 404)
    revoke_pay_token(sandbox_invoice['id'])
    check('revocation also closes the simulation lookup', cl.get('/pay/corporate/'+token_sandbox+'/sandbox-action').status_code == 404)
    check('revocation also closes status polling', cl.get('/pay/corporate/'+token_sandbox+'/status').status_code == 404)

tampered_mock, _ = _invoice()
with app.test_request_context():
    tampered_attempt, _ = ensure_checkout_session(tampered_mock,'http://localhost/ok','http://localhost/no')
c=get_db();cur=c.cursor()
cur.execute("UPDATE corporate_payment_attempts SET checkout_session_id='cs_mock_unverified' WHERE attempt_ref=%s",(tampered_attempt['attempt_ref'],))
c.commit();cur.close();c.close()
safe, reason = retire_offline_mock_attempt(tampered_mock['id'],admin_user)
check('unverified mock identity cannot release duplicate-session guard', not safe and open_attempt(tampered_mock['id']) is not None)

print('\nCompany receipts, Polygon verification and best-effort recovery')
public_invoice, _ = _invoice()
public_token, public_version = issue_pay_token(public_invoice['id'])
with app.test_request_context():
    public_mock, _ = ensure_checkout_session(public_invoice, 'http://localhost/old-return', 'http://localhost/old-cancel')
with patch.object(paymongo, 'MOCK_GATEWAY', False), patch.object(paymongo,'create_checkout_session',return_value={**connected,'id':'cs_test_public_connect'}) as public_create:
    connected_response = cl.post('/pay/corporate/'+public_token+'/connect-sandbox')
    current_public = get_corporate_payment(cid=public_invoice['id'])
    check('payer can connect sandbox from the existing company link', connected_response.status_code == 200)
    check('connecting sandbox preserves the company link and version', current_public['link_version'] == public_version and payment_by_token(public_token)[0]['id'] == public_invoice['id'])
    check('connected checkout uses current link for gateway redirects', public_create.call_args.kwargs['success_url'].endswith('/pay/corporate/'+public_token+'/return'))
    check('public connection keeps the invoice unpaid', current_public['status'] == 'pending')
    repeated_connection = cl.post('/pay/corporate/'+public_token+'/connect-sandbox')
    check('repeated public connection reuses its checkout', repeated_connection.status_code == 200 and public_create.call_count == 1)
    with patch.dict(os.environ, {'PAYMONGO_SECRET_KEY':'sk_live_forbidden'}):
        forbidden_connection = cl.post('/pay/corporate/'+public_token+'/connect-sandbox')
    check('public sandbox connection cannot use a live key', forbidden_connection.status_code == 403)
    revoke_pay_token(public_invoice['id'])
    check('revoked token cannot connect checkout', cl.post('/pay/corporate/'+public_token+'/connect-sandbox').status_code == 404)
with patch.object(paymongo,'MOCK_GATEWAY',True):
    mock_disabled = cl.post('/pay/corporate/'+token_sandbox+'/connect-sandbox')
    check('invalid or revoked links do not connect while mocked', mock_disabled.status_code == 404)
import tempfile
import blockchain
import qr_gen
from pathlib import Path
with tempfile.TemporaryDirectory(prefix='company-receipt-test-') as receipt_dir, patch.object(qr_gen, '_PROJECT_ROOT', receipt_dir), patch.object(corporate_routes, '_anchor_receipt', real_anchor_receipt):
    receipt_invoice, receipt_user = _invoice()
    receipt_token, _ = issue_pay_token(receipt_invoice['id'])
    with app.test_request_context():
        receipt_attempt, _ = ensure_checkout_session(receipt_invoice, 'http://localhost/return', 'http://localhost/cancel')
    receipt_session = _session(receipt_attempt['checkout_session_id'], receipt_invoice['amount_centavos'])
    receipt_session['payments'][0]['method'] = 'qrph'
    chain_tx = '0x' + 'ac' * 32
    with patch.object(blockchain, 'store_hash_on_chain', return_value={'tx_hash':chain_tx,'confirmed':True}) as chain_write:
        with app.test_request_context():
            done, message = validate_and_settle(receipt_session, 'webhook')
            duplicate, _ = validate_and_settle(receipt_session, 'poll')
    paid_receipt = get_corporate_payment(cid=receipt_invoice['id'])
    check('verified PayMongo payment ID is stored before receipt hashing', paid_receipt['paymongo_id'] == receipt_session['payments'][0]['id'])
    check('verified payment method appears on invoice receipt', paid_receipt['method'] == 'qrph')
    check('company payment creates receipt and QR', done and paid_receipt['receipt_id'] and Path(receipt_dir, paid_receipt['qr_code_path']).is_file())
    check('duplicate payment performs only one blockchain write', not duplicate and chain_write.call_count == 1)
    check('stored receipt hash commits to the company payment record', paid_receipt['receipt_hash'] == blockchain.compute_anchor('corporate_payment', paid_receipt))
    receipt_html = cl.get('/pay/corporate/'+receipt_token).get_data(as_text=True)
    check('company success page displays receipt and blockchain transaction', paid_receipt['receipt_id'] in receipt_html and chain_tx in receipt_html and 'Verify company receipt on blockchain' in receipt_html)
    check('company success page identifies sandbox payment', 'PayMongo sandbox payment' in receipt_html)
    fake_w3 = Mock()
    fake_w3.eth.get_transaction.return_value = {'blockNumber':100, 'from':os.getenv('SYSTEM_WALLET_ADDRESS',''), 'input':'0x'+paid_receipt['receipt_hash']}
    fake_w3.eth.get_transaction_receipt.return_value = {'status':1}
    fake_w3.eth.block_number = 105
    fake_w3.eth.get_block.return_value = {'timestamp':1234567890}
    with patch.object(blockchain, '_w3', return_value=fake_w3):
        verified = cl.post('/verify', data={'qr_data':paid_receipt['receipt_id']})
        check('public verifier accepts company receipt IDs', verified.status_code == 200 and 'Payment found on chain' in verified.get_data(as_text=True))
        verified_qr = cl.post('/verify', data={'qr_data':json.dumps({'receipt_id':paid_receipt['receipt_id'],'tx_hash':None})})
        check('company receipt QR uses the stored transaction for verification', 'Payment found on chain' in verified_qr.get_data(as_text=True))
        c=get_db();cur=c.cursor();cur.execute('UPDATE corporate_payments SET amount_centavos=amount_centavos+1 WHERE id=%s',(receipt_invoice['id'],));c.commit();cur.close();c.close()
        tampered = cl.post('/verify', data={'qr_data':paid_receipt['receipt_id']})
        check('company receipt verifier detects amount tampering', 'Record does not match' in tampered.get_data(as_text=True))

    failed_invoice, _ = _invoice()
    with app.test_request_context():
        failed_attempt, _ = ensure_checkout_session(failed_invoice,'http://localhost/return','http://localhost/cancel')
    with patch.object(blockchain,'store_hash_on_chain',side_effect=RuntimeError('simulated RPC outage')):
        with app.test_request_context():
            still_paid, _ = validate_and_settle(_session(failed_attempt['checkout_session_id'], failed_invoice['amount_centavos']), 'webhook')
    off_chain = get_corporate_payment(cid=failed_invoice['id'])
    check('blockchain outage does not undo a verified payment', still_paid and off_chain['status'] == 'paid')
    check('off-chain payment still has a stable receipt ID, hash and QR', off_chain['receipt_id'] and off_chain['receipt_hash'] and off_chain['qr_code_path'] and not off_chain['tx_hash'])
    with patch.object(blockchain,'store_hash_on_chain',return_value={'tx_hash':'0x'+'bd'*32,'confirmed':True}) as retry_write:
        with app.test_request_context():
            reanchored = real_anchor_receipt(off_chain)
            already_anchored = real_anchor_receipt(off_chain)
    recovered_receipt = get_corporate_payment(cid=failed_invoice['id'])
    check('re-anchor preserves receipt identity and fingerprint', reanchored and recovered_receipt['receipt_id'] == off_chain['receipt_id'] and recovered_receipt['receipt_hash'] == off_chain['receipt_hash'])
    check('repeated anchor retry does not write again', already_anchored and retry_write.call_count == 1)

    from db import mark_corporate_paid
    concurrent_invoice, _ = _invoice()
    concurrent_paid = mark_corporate_paid(cid=concurrent_invoice['id'], confirmed_payment_id='pay_anchor_concurrency', method='qrph')
    anchor_started = threading.Event()
    anchor_release = threading.Event()
    anchored_results = []
    def slow_anchor(receipt_hash):
        anchor_started.set()
        if not anchor_release.wait(timeout=10):
            raise RuntimeError('test anchor release timed out')
        return {'tx_hash':'0x'+'ce'*32,'confirmed':True}
    def anchor_worker():
        with app.app_context():
            anchored_results.append(real_anchor_receipt(concurrent_paid))
    with patch.object(blockchain,'store_hash_on_chain',side_effect=slow_anchor) as concurrent_write:
        worker = threading.Thread(target=anchor_worker)
        worker.start()
        try:
            started = anchor_started.wait(timeout=5)
            with app.app_context():
                rival = real_anchor_receipt(concurrent_paid)
        finally:
            anchor_release.set()
            worker.join(timeout=10)
    check('simultaneous anchor attempts produce only one chain write', started and not rival and anchored_results == [True] and concurrent_write.call_count == 1)

failed = [x for x in results if not x[1]]
print(f"\n{'='*64}\n{len(results) - len(failed)}/{len(results)} passed")
for n, _, d in failed:
    print(f"  FAILED: {n} {d}")
sys.exit(1 if failed else 0)
