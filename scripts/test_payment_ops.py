"""Admin payment operations + reconciliation concurrency.

Isolated DB, mocked gateway, mock mail. No network, no real email.

    cd src; ..\\venv\\Scripts\\python.exe ..\\scripts\\test_payment_ops.py
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
from concurrent.futures import ThreadPoolExecutor   # noqa: E402
from decimal import Decimal                        # noqa: E402
from datetime import datetime, timedelta           # noqa: E402

import paymongo                                    # noqa: E402
import email_utils                                 # noqa: E402
from app import app                                # noqa: E402
from db import (get_db, dict_cur, create_intake, add_slot, get_slots,
                claim_slot_with_registration, record_selfie_review,
                get_corporate_payment, get_attempts, open_attempt,
                reserve_attempt, record_session, mark_attempt_unknown,
                new_attempt_ref, payments_needing_attention, unresolved_events,
                replayable_attempts, outbound_args, invoiceable_roster,
                notification_payload, get_notifications, issue_registration_token, list_classes,
                authorize_payment_link_send, update_corporate_price, get_corporate_items,
                REGISTRATION_INSERT_SQL, registration_insert_params)  # noqa: E402
from corporate_checkout import poll_attempt, SettlementRefused   # noqa: E402
import admin.corporate as corporate_routes          # noqa: E402

# Receipt anchoring is independent of price/checkout correctness. Keep this
# regression local instead of trying a Polygon RPC during settlement tests.
corporate_routes._anchor_receipt = lambda *args, **kwargs: False

app.config["WTF_CSRF_ENABLED"] = False
results = []


def check(name, passed, detail=""):
    results.append((name, passed, detail))
    print(f"  [{'PASS' if passed else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def _mkuser(role, email, reg_id=None):
    c = get_db(); cur = c.cursor()
    cur.execute("""INSERT INTO users (role, fname, lname, email, password_hash,
                   payment_status, registration_id)
                   VALUES (%s,'T','U',%s,'x','unpaid',%s)
                   ON CONFLICT (email) DO UPDATE SET registration_id =
                   EXCLUDED.registration_id RETURNING id""", (role, email, reg_id))
    uid = cur.fetchone()[0]; c.commit(); cur.close(); c.close()
    return uid


ADMIN = _mkuser("admin", "ops@test.invalid")


def admin_client():
    c = app.test_client()
    with c.session_transaction() as s:
        s["user_id"], s["user_role"] = ADMIN, "admin"
    return c


def _approved_trainee(intake_id, name, email, make_account=True):
    """A roster slot carried all the way to approved (and optionally an account)."""
    sid, tok = add_slot(intake_id, name, email)
    e = {"id": str(uuid.uuid4())[:8].upper(), "form_type": "training",
         "form_label": "Training", "submitted_at": datetime.now(),
         "full_name": name, "email": email, "training_type": "Online",
         "photo_id": "p.png", "resume": "r.pdf", "valid_id": "v.png",
         "selfie_with_id": "s.png"}
    rid, err = claim_slot_with_registration(tok, e["id"], REGISTRATION_INSERT_SQL,
                                            registration_insert_params(e))
    assert rid, err
    c = get_db(); cur = c.cursor()
    cur.execute("UPDATE registrations SET status='accepted' WHERE id=%s", (rid,))
    c.commit(); cur.close(); c.close()
    record_selfie_review(rid, "approved", ADMIN)
    uid = _mkuser("trainee", email, rid) if make_account else None
    return sid, rid, uid


print(f"\nisolated database: {assert_isolated()}")
adm = admin_client()

print("\n1. Invoice preview explains who cannot be billed")
iid = create_intake("Acme Power", "Jo Cruz", "hr@acme.com", "0917",
                    "training", "CEM Training", ADMIN)
_approved_trainee(iid, "Ana Reyes", "ana@acme.com")
_approved_trainee(iid, "Ben Santos", "ben@acme.com")
_approved_trainee(iid, "Cy Lim", "cy@acme.com", make_account=False)  # no account
add_slot(iid, "Dee Tan", "dee@acme.com")                              # not submitted

r = adm.get(f"/admin/intake/{iid}/invoice/preview")
d = r.get_json()
check("preview loads", r.status_code == 200, f"HTTP {r.status_code}")
check("bills only the two with accounts", len(d["lines"]) == 2,
      str([l["name"] for l in d["lines"]]))
check("total is computed server-side", d["total_php"] > 0, str(d["total_php"]))
blocked = {b["name"]: b["reason"] for b in d["blocked"]}
check("no-account trainee is explained, not dropped",
      "Cy Lim" in blocked and "account" in blocked["Cy Lim"].lower(),
      blocked.get("Cy Lim", ""))
check("unsubmitted trainee is explained",
      "Dee Tan" in blocked and "submit" in blocked["Dee Tan"].lower(),
      blocked.get("Dee Tan", ""))

print("\n2. Create invoice from the approved roster")
# A separate, fully-approved intake. `iid` above keeps its blocked members on
# purpose, and send-eligibility (rightly) requires EVERY expected trainee
# approved — so the send flow needs a clean roster of its own.
iid_ok = create_intake("Acme Power", "Jo Cruz", "hr@acme.com", "0917",
                       "training", "Online", ADMIN)
_approved_trainee(iid_ok, "Ana Reyes", "ana2@acme.com")
_approved_trainee(iid_ok, "Ben Santos", "ben2@acme.com")
issue_registration_token(iid_ok, created_by=ADMIN)
registration_class_id = list_classes(intake_id=iid_ok)[0]['id']
r = adm.post(f"/admin/intake/{iid_ok}/invoice", data={"expiry_hours": "24"})
d = r.get_json()
check("invoice created", r.status_code == 200 and d.get("ok"), str(d))
cid = d["id"]
check("line count matches the billable roster", d["trainee_count"] == 2)
inv = get_corporate_payment(cid=cid)
check("invoice is linked back to the intake", inv["intake_id"] == iid_ok)
check("automatically prepared class is bound to the new invoice",
      next(c for c in list_classes(intake_id=iid_ok) if c['id'] == registration_class_id)['corporate_payment_id'] == cid)
check("amount matches the preview",
      abs(inv["amount_centavos"] / 100.0 - d["total_php"]) < 0.01)

print("\n2a. Detail-modal price override before checkout")
original_amount = inv['amount_centavos']
items_before = get_corporate_items(cid)
price_endpoint = f'/admin/corporate/{cid}/price'
price_data = {'custom_total': '12,345.67', 'override_note': 'Agreed company rate',
              'expected_centavos': original_amount}
outsider = app.test_client()
with outsider.session_transaction() as session:
    session.update(user_id=items_before[0]['user_id'], user_role='trainee')
check('trainees cannot change invoice prices', outsider.post(price_endpoint, data=price_data).status_code == 403)
for invalid in ('NaN', 'Infinity', '-1', '0', '12.345', '1e6', '1,2', '10000000000.00'):
    rejected = adm.post(price_endpoint, data={**price_data, 'custom_total': invalid})
    check('invalid override refused: ' + invalid, rejected.status_code == 400)
check('override reason is required', adm.post(price_endpoint, data={**price_data, 'override_note': ' '}).status_code == 400)
check('stale operator price is refused', adm.post(price_endpoint, data={**price_data, 'expected_centavos': original_amount + 1}).status_code == 409)
r = adm.post(price_endpoint, data=price_data)
check('custom price can be saved from Corporate Payments', r.status_code == 200 and r.json['amount_centavos'] == 1234567)
custom_invoice = get_corporate_payment(cid=cid)
check('custom amount uses exact cents and records the actor', custom_invoice['custom_total_php'] == Decimal('12345.67')
      and custom_invoice['override_by'] == ADMIN and custom_invoice['override_at'] is not None)
check('override keeps published total and trainee items', custom_invoice['list_total_php'] == inv['list_total_php']
      and get_corporate_items(cid) == items_before)
check('detail modal shows the override and its reason', 'Agreed company rate' in adm.get(f'/admin/corporate/{cid}/panel').get_data(as_text=True))
c = get_db(); cur = c.cursor()
cur.execute("SELECT count(*) FROM corporate_payment_events WHERE corporate_payment_id=%s AND action='price_override' AND actor_id=%s", (cid, ADMIN))
check('price change is written to invoice history', cur.fetchone()[0] == 1)
cur.execute("SELECT count(*) FROM audit_logs WHERE entity_type='corporate_payment' AND entity_id=%s AND action='corporate_price_overridden'", (str(cid),))
check('price change is written to audit history', cur.fetchone()[0] == 1)
cur.close(); c.close()
r = adm.post(price_endpoint, data={'custom_total': '', 'override_note': 'Restore published total', 'expected_centavos': 1234567})
check('blank custom total restores the published price', r.status_code == 200
      and r.json['amount_centavos'] == original_amount and r.json['custom_total_php'] is None)

print("\n3. Issue the payment link")
r = adm.post(f"/admin/corporate/{cid}/payment-link")
d = r.get_json()
check("link issued", r.status_code == 200 and "/pay/corporate/" in d.get("url", ""),
      str(d)[:120])
pay_url = d["url"]
check("a checkout session was created", bool(d.get("checkout_url")))
check("link_version starts at 1", d["link_version"] == 1)
inv = get_corporate_payment(cid=cid)
check("only the hash is stored",
      inv["pay_token_hash"] and inv["pay_token_hash"] not in pay_url)
check('price cannot change after a link and session exist', adm.post(price_endpoint, data=price_data).status_code == 409
      and get_corporate_payment(cid=cid)['amount_centavos'] == original_amount)

print("\n4. Send is admin-initiated and eligibility is re-checked")
email_utils.SENT_MESSAGES.clear()
r = adm.post(f"/admin/corporate/{cid}/send-link", data={"pay_url": pay_url})
d = r.get_json()
check("send succeeds", r.status_code == 200 and d["ok"], str(d))
check("mock outcome is named honestly, not 'sent'",
      "mock" in d["message"].lower() and "submitted to the mail server" not in d["message"].lower(),
      d["message"])
check("message captured", len(email_utils.SENT_MESSAGES) == 1)
check("email carries no roster",
      "ana@acme.com" not in email_utils.SENT_MESSAGES[0]["html"])

inv = get_corporate_payment(cid=cid)
c = get_db(); cur = dict_cur(c)
cur.execute("SELECT payment_link_sent_at FROM corporate_intakes WHERE id=%s", (iid_ok,))
sent_at = cur.fetchone()["payment_link_sent_at"]
cur.close(); c.close()
check("display timestamp NOT set for a mock send", sent_at is None,
      "payment_link_sent_at must track real SMTP only")

r2 = adm.post(f"/admin/corporate/{cid}/send-link", data={"pay_url": pay_url})
check("a second send for the same link version is refused",
      r2.status_code == 409, f"HTTP {r2.status_code}")

print("\n5. Roster change after issue blocks a further send")
add_slot(iid_ok, "Late Joiner", "late@acme.com")
c = get_db(); cur = c.cursor()
cur.execute("UPDATE corporate_payments SET link_version = link_version + 1 WHERE id=%s",
            (cid,))
c.commit(); cur.close(); c.close()
r = adm.post(f"/admin/corporate/{cid}/send-link", data={"pay_url": pay_url})
check("send refused while someone is unapproved", r.status_code == 409,
      str(r.get_json())[:110])

print("\n6. Attempts panel")
r = adm.get(f"/admin/corporate/{cid}/attempts")
d = r.get_json()
check("panel loads", r.status_code == 200)
check("shows the attempt", len(d["attempts"]) == 1)
a0 = d["attempts"][0]
check("creation state visible", a0["status"] == "active", a0["status"])
check("session and intent are separate fields",
      a0["session_id"] and a0["intent_id"] is None)
check("environment shown", a0["environment"] == "test")
check("retrieve offered, replay not (it has a session)",
      a0["can_retrieve"] and not a0["can_replay"])
check("payment-link delivery is listed", len(d["notifications"]) >= 1)

print("\n7. Resolve requires evidence")
inv2_id = cid
a_stuck, _ = reserve_attempt(999999, 1, "X", "test", {"line_items": []}) \
    if False else (None, None)
iid2 = create_intake("Beta Co", "Mia", "mia@beta.com", None, "training", None, ADMIN)
_approved_trainee(iid2, "Ed Cruz", "ed@beta.com")
cid2 = adm.post(f"/admin/intake/{iid2}/invoice").get_json()["id"]
inv2 = get_corporate_payment(cid=cid2)
ref2 = new_attempt_ref()
a2, _ = reserve_attempt(cid2, inv2["amount_centavos"], inv2["reference"], "test",
                        {"line_items": [], "metadata": {"attempt_ref": ref2}},
                        attempt_ref=ref2)
mark_attempt_unknown(ref2, "connection lost")

r = adm.post(f"/admin/corporate/attempt/{ref2}/resolve",
             data={"mode": "verified", "outcome": "no_session", "evidence": "nope"})
check("bare assertion is refused", r.status_code == 400,
      str(r.get_json())[:100])
check("refusal explains the evidence requirement",
      "verif" in r.get_json()["error"].lower())

r = adm.post(f"/admin/corporate/attempt/{ref2}/resolve",
             data={"mode": "retrieve"})
check("retrieve refused without a session id", r.status_code == 400)

print("\n8. Replay is evidence, and only inside the key window")
r = adm.post(f"/admin/corporate/attempt/{ref2}/resolve", data={"mode": "replay"})
d = r.get_json()
check("replay inside the window recovers a session",
      r.status_code == 200 and d.get("session_id"), str(d)[:110])
att = [a for a in get_attempts(cid2) if a["attempt_ref"] == ref2][0]
check("attempt is active again", att["status"] == "active")

ref3 = new_attempt_ref()
c = get_db(); cur = c.cursor()
cur.execute("UPDATE corporate_payment_attempts SET status='unknown', "
            "checkout_session_id=NULL, idempotency_expires_at = NOW() - "
            "interval '1 hour' WHERE attempt_ref=%s", (ref2,))
c.commit(); cur.close(); c.close()
r = adm.post(f"/admin/corporate/attempt/{ref2}/resolve", data={"mode": "replay"})
check("replay refused past the retention window", r.status_code == 400,
      str(r.get_json())[:110])
check("refusal says a replay would CREATE a new session",
      "new session" in r.get_json()["error"].lower())

print("\n9. Verified outcome releases the guard, with a record")
r = adm.post(f"/admin/corporate/attempt/{ref2}/resolve",
             data={"mode": "verified", "outcome": "no_session",
                   "evidence": "Checked PayMongo dashboard for CORP ref; no "
                               "checkout session exists for this reference."})
check("verified resolution accepted", r.status_code == 200, str(r.get_json())[:110])
check("guard released — a new attempt is now possible",
      reserve_attempt(cid2, inv2["amount_centavos"], inv2["reference"], "test",
                      {"line_items": []})[0] is not None)
c = get_db(); cur = dict_cur(c)
cur.execute("SELECT last_error FROM corporate_payment_attempts WHERE attempt_ref=%s",
            (ref2,))
rec = cur.fetchone()["last_error"]
cur.close(); c.close()
check("operator, evidence, action and result are recorded",
      all(k in rec for k in ("manual_verification", "Checked PayMongo",
                             "action=", "result=")), rec[:120])

print("\n10. Attention + unresolved events surface for staff")
r = adm.get("/admin/corporate/attention")
d = r.get_json()
check("attention endpoint loads", r.status_code == 200)
check("returns both lists", "payments" in d and "events" in d)

print("\n11. CONCURRENCY: two reconciliation workers")
iid3 = create_intake("Gamma Co", "Rae", "rae@gamma.com", None, "training", None, ADMIN)
_approved_trainee(iid3, "Fay Lim", "fay@gamma.com")
cid3 = adm.post(f"/admin/intake/{iid3}/invoice").get_json()["id"]
adm.post(f"/admin/corporate/{cid3}/payment-link")
att3 = open_attempt(cid3)
inv3 = get_corporate_payment(cid=cid3)


def _paid_session(cs_id, amount):
    return {"id": cs_id, "status": "active", "livemode": False,
            "payment_intent_id": None, "reference_number": None,
            "payments": [{"id": "pay_race", "status": "paid",
                          "amount": amount, "currency": "PHP"}]}


_real_retrieve = paymongo.retrieve_checkout_session
paymongo.retrieve_checkout_session = lambda cs: _paid_session(
    cs, inv3["amount_centavos"])

outcomes, lock = [], threading.Lock()


def _worker():
    with app.test_request_context():
        try:
            ok, msg = poll_attempt(att3, source="reconcile")
        except SettlementRefused as e:
            ok, msg = False, str(e)
        except Exception as e:
            ok, msg = False, f"{type(e).__name__}: {e}"
    with lock:
        outcomes.append((ok, msg))


ts = [threading.Thread(target=_worker) for _ in range(2)]
[t.start() for t in ts]; [t.join() for t in ts]
paymongo.retrieve_checkout_session = _real_retrieve

wins = [o for o in outcomes if o[0]]
check("exactly one worker settles", len(wins) == 1,
      f"{len(wins)} of {len(outcomes)}: {[o[1][:40] for o in outcomes]}")
check("invoice is paid once", get_corporate_payment(cid=cid3)["status"] == "paid")
c = get_db(); cur = c.cursor()
cur.execute("SELECT COUNT(*) FROM users u JOIN corporate_payment_items i "
            "ON i.user_id=u.id WHERE i.corporate_payment_id=%s AND "
            "u.payment_status='paid'", (cid3,))
check("listed trainees flipped exactly once", cur.fetchone()[0] == 1)
cur.close(); c.close()

print("\n12. CONCURRENCY: late response from the original creation")
iid4 = create_intake("Delta Co", "Sam", "sam@delta.com", None, "training", None, ADMIN)
_approved_trainee(iid4, "Gil Roy", "gil@delta.com")
cid4 = adm.post(f"/admin/intake/{iid4}/invoice").get_json()["id"]
inv4 = get_corporate_payment(cid=cid4)

# A creation whose response never arrived.
ref4 = new_attempt_ref()
payload4 = {"line_items": [], "success_url": "http://x/ok", "cancel_url": "http://x/no",
            "description": "d", "reference_number": inv4["reference"],
            "metadata": {"reference": inv4["reference"], "attempt_ref": ref4}}
a4, _ = reserve_attempt(cid4, inv4["amount_centavos"], inv4["reference"], "test",
                        payload4, attempt_ref=ref4)
mark_attempt_unknown(ref4, "read timeout")

# Reconciliation replays the stored key and gets the ORIGINAL session back
# (the mock derives the id from the key, exactly as idempotency does).
replayed = paymongo.create_checkout_session(**outbound_args(payload4),
                                            idempotency_key=a4["idempotency_key"])
record_session(ref4, replayed["id"], replayed.get("checkout_url"))

# NOW the original request's response finally lands, carrying the same session.
late = paymongo.create_checkout_session(**outbound_args(payload4),
                                        idempotency_key=a4["idempotency_key"])
check("late response returns the SAME session (idempotent)",
      late["id"] == replayed["id"], f"{late['id']} vs {replayed['id']}")
applied_again = record_session(ref4, late["id"], late.get("checkout_url"))
check("recording it again is a no-op, not a second session",
      applied_again is False, "attempt already active")
check("exactly one attempt exists for the invoice",
      len(get_attempts(cid4)) == 1)
check("and exactly one session id is recorded",
      len({a["checkout_session_id"] for a in get_attempts(cid4)}) == 1)

print("\n13. Invoice creation obeys the SAME rule as preview")
iid_mix = create_intake("Mixed Co", "Pat", "pat@mixed.com", None,
                        "training", "Online", ADMIN)
_approved_trainee(iid_mix, "Ok One", "ok1@mixed.com")
add_slot(iid_mix, "Not Submitted", "ns@mixed.com")      # blocks the roster

prev = adm.get(f"/admin/intake/{iid_mix}/invoice/preview").get_json()
check("preview says it cannot be created", prev["can_create"] is False)
check("preview still lists the billable line", len(prev["lines"]) == 1)
r = adm.post(f"/admin/intake/{iid_mix}/invoice")
check("POST refuses too — no partial invoice", r.status_code == 400,
      f"HTTP {r.status_code}")
check("refusal names who is outstanding",
      "Not Submitted" in r.get_json()["error"], r.get_json()["error"][:110])
c = get_db(); cur = c.cursor()
cur.execute("SELECT COUNT(*) FROM corporate_payments WHERE intake_id=%s", (iid_mix,))
check("nothing was created", cur.fetchone()[0] == 0)
cur.close(); c.close()

print("\n14. Send requires invoice COVERAGE, not just approval")
iid_cov = create_intake("Cover Co", "Sal", "sal@cover.com", None,
                        "training", "Online", ADMIN)
_approved_trainee(iid_cov, "First Person", "fp@cover.com")
cid_cov = adm.post(f"/admin/intake/{iid_cov}/invoice").get_json()["id"]
link = adm.post(f"/admin/corporate/{cid_cov}/payment-link").get_json()
check("link issued for the covered invoice", bool(link.get("url")))

# Someone joins AND is approved AFTER the invoice was raised.
_approved_trainee(iid_cov, "Second Person", "sp@cover.com")
r = adm.post(f"/admin/corporate/{cid_cov}/send-link",
             data={"pay_url": link["url"]})
check("send refused — approved but not on the invoice",
      r.status_code == 409, f"HTTP {r.status_code}")
check("refusal says they are NOT on the invoice",
      "not on this invoice" in r.get_json()["error"].lower(),
      r.get_json()["error"][:120])

print("\n15. Payment URL is verified, not trusted")
iid_u = create_intake("Url Co", "Uma", "uma@url.com", None, "training", "Online", ADMIN)
_approved_trainee(iid_u, "Solo One", "solo@url.com")
cid_u = adm.post(f"/admin/intake/{iid_u}/invoice").get_json()["id"]
good = adm.post(f"/admin/corporate/{cid_u}/payment-link").get_json()["url"]

r = adm.post(f"/admin/corporate/{cid_u}/send-link",
             data={"pay_url": "https://evil.test/pay/corporate/attacker-token"})
check("a forged URL is refused", r.status_code == 400, f"HTTP {r.status_code}")
check("refusal names the foreign origin",
      "evil.test" in r.get_json()["error"], r.get_json()["error"][:110])

r = adm.post(f"/admin/corporate/{cid_u}/send-link", data={"pay_url": ""})
check("an empty URL is refused", r.status_code == 400)

r = adm.post(f"/admin/corporate/{cid_u}/send-link", data={"pay_url": good})
d = r.get_json()
check("the genuine URL is accepted", r.status_code == 200 and d["ok"], str(d)[:110])
notif_u = d["notification_id"]

print("\n16. Retry is self-contained (no browser state)")
stored, _perr = notification_payload(notif_u)
check("the URL was persisted with the intent", stored.get("pay_url") == good)
# Retry sends NO pay_url at all — exactly what a different operator would do.
r = adm.post(f"/admin/notification/{notif_u}/retry-link")
check("retry works without the browser supplying anything",
      r.status_code == 200 and r.get_json()["ok"], str(r.get_json())[:110])

adm.post(f"/admin/corporate/{cid_u}/payment-link/revoke")
r = adm.post(f"/admin/notification/{notif_u}/retry-link")
check("retry refuses once the link is revoked", r.status_code == 409,
      str(r.get_json())[:110])

print("\n17. Manual recovery respects creation ownership")
iid_o = create_intake("Own Co", "Ora", "ora@own.com", None, "training", "Online", ADMIN)
_approved_trainee(iid_o, "Own One", "own@own.com")
cid_o = adm.post(f"/admin/intake/{iid_o}/invoice").get_json()["id"]
inv_o = get_corporate_payment(cid=cid_o)
ref_o = new_attempt_ref()
a_o, _ = reserve_attempt(cid_o, inv_o["amount_centavos"], inv_o["reference"],
                         "test", {"line_items": [], "success_url": "http://x/ok",
                                  "cancel_url": "http://x/no", "description": "d",
                                  "reference_number": inv_o["reference"],
                                  "metadata": {"attempt_ref": ref_o}},
                         attempt_ref=ref_o, lease_seconds=300)

r = adm.post(f"/admin/corporate/attempt/{ref_o}/resolve", data={"mode": "replay"})
check("replay refused while creation is still owned", r.status_code == 409,
      f"HTTP {r.status_code}")
check("refusal names the in-flight request",
      "in-flight" in r.get_json()["error"].lower(), r.get_json()["error"][:110])

r = adm.post(f"/admin/corporate/attempt/{ref_o}/resolve",
             data={"mode": "verified", "outcome": "no_session",
                   "evidence": "Checked the dashboard, nothing for this ref."})
check("verified ALSO refused while owned", r.status_code == 409,
      f"HTTP {r.status_code}")
c = get_db(); cur = c.cursor()
cur.execute("SELECT status FROM corporate_payment_attempts WHERE attempt_ref=%s",
            (ref_o,))
check("the guard still holds", cur.fetchone()[0] in ("creating", "unknown"))
cur.close(); c.close()

# Once ownership lapses, recovery is allowed again.
c = get_db(); cur = c.cursor()
cur.execute("UPDATE corporate_payment_attempts SET creation_lease_until = NOW() - "
            "interval '1 second', status='unknown' WHERE attempt_ref=%s", (ref_o,))
c.commit(); cur.close(); c.close()
r = adm.post(f"/admin/corporate/attempt/{ref_o}/resolve",
             data={"mode": "verified", "outcome": "no_session",
                   "evidence": "Checked the PayMongo dashboard for this "
                               "reference; no checkout session exists."})
d = r.get_json()
check("recovery allowed once ownership lapses", r.status_code == 200, str(d)[:110])
check("labelled as MANUAL verification", d.get("verification") == "manual", str(d))
check("message says the gateway was not queried",
      "not queried" in d["message"].lower(), d["message"])
c = get_db(); cur = dict_cur(c)
cur.execute("SELECT last_error FROM corporate_payment_attempts WHERE attempt_ref=%s",
            (ref_o,))
rec_o = cur.fetchone()["last_error"]
cur.close(); c.close()
check("stored as manual_verification, not gateway truth",
      "manual_verification" in rec_o, rec_o[:90])

print("\n18. Retrieve is preferred when a session exists")
iid_p = create_intake("Pref Co", "Pia", "pia@pref.com", None, "training", "Online", ADMIN)
_approved_trainee(iid_p, "Pref One", "pref@pref.com")
cid_p = adm.post(f"/admin/intake/{iid_p}/invoice").get_json()["id"]
adm.post(f"/admin/corporate/{cid_p}/payment-link")
att_p = open_attempt(cid_p)
r = adm.post(f"/admin/corporate/attempt/{att_p['attempt_ref']}/resolve",
             data={"mode": "verified", "outcome": "session_closed",
                   "evidence": "I am asserting this without asking anyone."})
check("manual outcome refused when a session id exists",
      r.status_code == 400, f"HTTP {r.status_code}")
check("it points at Retrieve instead",
      "retrieve" in r.get_json()["error"].lower(), r.get_json()["error"][:110])



print("\n19. Foreign host carrying a VALID token is refused")
iid_f = create_intake("Forge Co", "Fay", "fay@forge.com", None,
                      "training", "Online", ADMIN)
_approved_trainee(iid_f, "Forge One", "f1@forge.com")
cid_f = adm.post(f"/admin/intake/{iid_f}/invoice").get_json()["id"]
real_url = adm.post(f"/admin/corporate/{cid_f}/payment-link").get_json()["url"]
real_token = real_url.rsplit("/", 1)[-1]

# The token is genuine and would pass any hash check — only the host differs.
forged = f"https://evil.test/pay/corporate/{real_token}"
r = adm.post(f"/admin/corporate/{cid_f}/send-link", data={"pay_url": forged})
check("valid token on a foreign host is REFUSED", r.status_code == 400,
      f"HTTP {r.status_code}")
check("the refusal is about the origin, not the token",
      "evil.test" in r.get_json()["error"], r.get_json()["error"][:110])
check("no notification was raised by the rejected attempt",
      len([n for n in get_notifications(iid_f) if n["kind"] == "payment_link"]) == 0)

# Same token, wrong path shape.
for bad, label in [(f"http://localhost/pay/corporate/{real_token}/extra", "extra path segment"),
                   (f"http://localhost/elsewhere/{real_token}", "wrong path"),
                   (f"http://localhost/pay/corporate/", "no token")]:
    rr = adm.post(f"/admin/corporate/{cid_f}/send-link", data={"pay_url": bad})
    check(f"refused: {label}", rr.status_code == 400, f"HTTP {rr.status_code}")

# The genuine URL still works afterwards — rejections consumed no dedupe key.
r = adm.post(f"/admin/corporate/{cid_f}/send-link", data={"pay_url": real_url})
check("the genuine URL still sends after those rejections",
      r.status_code == 200 and r.get_json()["ok"], str(r.get_json())[:110])
stored_f, _perr = notification_payload(r.get_json()["notification_id"])
check("the stored URL is this application's canonical one",
      stored_f["pay_url"] == real_url, stored_f.get("pay_url", ""))

print("\n20. Payload survives a crash between intent and persistence")
iid_c = create_intake("Crash Co", "Cal", "cal@crash.com", None,
                      "training", "Online", ADMIN)
_approved_trainee(iid_c, "Crash One", "c1@crash.com")
cid_c = adm.post(f"/admin/intake/{iid_c}/invoice").get_json()["id"]
url_c = adm.post(f"/admin/corporate/{cid_c}/payment-link").get_json()["url"]
inv_c = get_corporate_payment(cid=cid_c)

# Authorisation now writes the payload in its OWN transaction. Simulate the
# old crash window by checking the row is complete the instant it exists:
# there is no moment where the dedupe key is consumed but the URL is absent.
nid_c, err_c = authorize_payment_link_send(
    iid_c, cid_c, inv_c["link_version"], inv_c["contact_email"], "S", ADMIN,
    payload={"pay_url": url_c, "link_version": inv_c["link_version"]})
check("authorisation succeeded", nid_c and err_c is None, str(err_c))
check("payload is present immediately, same transaction",
      notification_payload(nid_c)[0].get("pay_url") == url_c)

# And the dedupe key really was consumed by that same commit.
nid_dup, err_dup = authorize_payment_link_send(
    iid_c, cid_c, inv_c["link_version"], inv_c["contact_email"], "S", ADMIN,
    payload={"pay_url": url_c, "link_version": inv_c["link_version"]})
check("dedupe key was consumed atomically with the payload",
      nid_dup is None and err_dup, str(err_dup)[:90])

# A retry needs nothing from the browser.
r = adm.post(f"/admin/notification/{nid_c}/retry-link")
check("retry works from the stored payload alone",
      r.status_code == 200 and r.get_json()["ok"], str(r.get_json())[:110])

print("\n21. Retry payload is encrypted at rest")
c = get_db(); cur = dict_cur(c)
cur.execute("SELECT payload FROM corporate_notifications WHERE id=%s", (nid_c,))
raw_c = cur.fetchone()["payload"]
cur.close(); c.close()
check("ciphertext does not contain the token",
      raw_c and url_c.rsplit("/", 1)[-1] not in raw_c, "token must not be readable")
check("ciphertext does not contain the path either",
      "pay/corporate" not in raw_c)
check("but it decrypts for the application",
      notification_payload(nid_c)[0]["pay_url"] == url_c)

import secretbox as _sb
_orig_key = os.environ.get("SECRET_KEY")
os.environ["SECRET_KEY"] = "a-totally-different-key"
_p, _e = notification_payload(nid_c)
check("a rotated SECRET_KEY is reported as UNREADABLE, not empty",
      _p is None and _e, str(_e)[:90])
check("the error warns against assuming nothing was sent",
      "do not assume" in (_e or "").lower(), str(_e)[:90])
os.environ["SECRET_KEY"] = _orig_key or ""

print('\n22. Checkout creation and price changes coordinate on the invoice')
state_intake = create_intake('Price state guard', 'Contact', 'hr@state.test', '', 'training', 'Online', ADMIN)
_approved_trainee(state_intake, 'State Guard', 'price-state-guard@test.invalid')
state_id = adm.post(f'/admin/intake/{state_intake}/invoice').json['id']
state_amount = get_corporate_payment(cid=state_id)['amount_centavos']
for state, expires_in in [('paid', 3600), ('cancelled', 3600), ('expired', -60), ('pending', -60)]:
    c = get_db(); cur = c.cursor()
    cur.execute('UPDATE corporate_payments SET status=%s, expires_at=NOW()+make_interval(secs=>%s) WHERE id=%s',
                (state, expires_in, state_id))
    c.commit(); cur.close(); c.close()
    refused = adm.post(f'/admin/corporate/{state_id}/price', data={**price_data, 'expected_centavos': state_amount})
    check('closed/expired price protected: ' + state + str(expires_in), refused.status_code == 409
          and get_corporate_payment(cid=state_id)['amount_centavos'] == state_amount)
c = get_db(); cur = c.cursor()
cur.execute("UPDATE corporate_payments SET status='pending', expires_at=NOW()+INTERVAL '1 hour', paymongo_id='pi_legacy_price_guard' WHERE id=%s", (state_id,))
c.commit(); cur.close(); c.close()
check('legacy gateway intent also locks the price', adm.post(f'/admin/corporate/{state_id}/price',
      data={**price_data, 'expected_centavos': state_amount}).status_code == 409)
for trial in range(3):
    race_intake = create_intake('Price race', 'Contact', 'hr@race.test', '', 'training', 'Online', ADMIN)
    _approved_trainee(race_intake, 'Price Racer', f'price-{trial}@race.test')
    race_id = adm.post(f'/admin/intake/{race_intake}/invoice').json['id']
    before = get_corporate_payment(cid=race_id)
    barrier = threading.Barrier(2)
    def override_racer():
        barrier.wait()
        return update_corporate_price(race_id, '100.01', 'Race test', ADMIN, before['amount_centavos'])
    def checkout_racer():
        barrier.wait()
        return reserve_attempt(race_id, before['amount_centavos'], before['reference'], 'test', {'line_items': []})
    with ThreadPoolExecutor(max_workers=2) as pool:
        one = pool.submit(override_racer); two = pool.submit(checkout_racer)
        override_result, attempt_result = one.result(), two.result()
    check(f'race {trial + 1}: only price change or old-price reservation wins',
          (override_result[0] is not None) + (attempt_result[0] is not None) == 1)
    current = get_corporate_payment(cid=race_id)
    if override_result[0] is not None:
        check(f'race {trial + 1}: stale checkout cannot reserve old amount', current['amount_centavos'] == 10001 and not get_attempts(race_id))
    else:
        check(f'race {trial + 1}: attempt keeps matching the invoice price', current['amount_centavos'] == attempt_result[0]['request_amount_centavos'])

print('\nCompany email editing and sending an existing link to its new recipient')
from db import get_intake, begin_attempt, finish_attempt
iid_email = create_intake('Email Edit Co', 'Mina Reyes', 'old@email.test', None, 'training', 'Online', ADMIN)
_approved_trainee(iid_email, 'Mika Tan', 'mika-edit@email.test')
cid_email = adm.post(f'/admin/intake/{iid_email}/invoice').get_json()['id']
link_email = adm.post(f'/admin/corporate/{cid_email}/payment-link').get_json()
original_url = link_email['url']
first_send = adm.post(f'/admin/corporate/{cid_email}/send-link', data={'pay_url': original_url})
old_notice = first_send.get_json()['notification_id']
before_email = get_corporate_payment(cid=cid_email)
before_count = len(email_utils.SENT_MESSAGES)
def edit_email(address, expected='old@email.test', client=adm):
    return client.post(f'/admin/corporate/{cid_email}/email', data={'contact_email':address, 'expected_email':expected})
for address in ['', 'not-an-email', 'a@', '.a@email.test', 'a..b@email.test', 'a@bad..test', 'a@email.test\r\nBcc:else@email.test']:
    check('invalid company email refused: '+repr(address), edit_email(address).status_code == 400)
check('email edit without current-value guard refused', adm.post(f'/admin/corporate/{cid_email}/email', data={'contact_email':'new@email.test'}).status_code == 400)
check('email edit with stale value refused', edit_email('new@email.test', 'stale@email.test').status_code == 409)
unprivileged = app.test_client()
with unprivileged.session_transaction() as sess:
    sess['user_id'] = _mkuser('trainee', 'email-editor-trainee@test.invalid'); sess['user_role'] = 'trainee'
check('trainee cannot edit company email', edit_email('new@email.test', client=unprivileged).status_code == 403)
app.config['WTF_CSRF_ENABLED'] = True
check('email edit requires CSRF', edit_email('new@email.test').status_code == 400)
app.config['WTF_CSRF_ENABLED'] = False
edited = edit_email(' NEW@email.test ')
after_email = get_corporate_payment(cid=cid_email)
check('company email saved and normalized', edited.status_code == 200 and after_email['contact_email'] == 'new@email.test')
check('linked Company Intake updated too', get_intake(iid_email)['contact_email'] == 'new@email.test')
check('saving email sends no message', len(email_utils.SENT_MESSAGES) == before_count)
check('price, token and link version preserved', all(after_email[k] == before_email[k] for k in ['amount_centavos','pay_token_hash','link_version']))
check('checkout attempt reused unchanged', len(get_attempts(cid_email)) == 1 and get_attempts(cid_email)[0]['checkout_session_id'].startswith('cs_mock_'))
old_delivery = next(n for n in get_notifications(iid_email) if n['id'] == old_notice)
check('old delivery recipient and state retained', old_delivery['to_email'] == 'old@email.test' and old_delivery['status'] == 'mocked')
from admin.payments_ops import _deliver_payment_link
with app.test_request_context():
    old_send_count = len(email_utils.SENT_MESSAGES)
    stale_ok, stale_message = _deliver_payment_link(old_notice, before_email, original_url)
check('a queued delivery cannot follow an edited recipient', not stale_ok and len(email_utils.SENT_MESSAGES) == old_send_count)
c = get_db(); cur = c.cursor()
cur.execute("SELECT count(*) FROM audit_logs WHERE entity_id=%s AND action='corporate_email_changed'", (str(cid_email),))
check('email change audited', cur.fetchone()[0] == 1)
cur.close(); c.close()
check('repeat Save is harmless', edit_email('new@email.test','new@email.test').status_code == 200)
resent = adm.post(f'/admin/corporate/{cid_email}/send-link', data={'use_saved_link':'1'})
check('saved link can be sent to new company email', resent.status_code == 200 and email_utils.SENT_MESSAGES[-1]['to'] == 'new@email.test')
check('resend retains the original payment URL', original_url in email_utils.SENT_MESSAGES[-1]['html'] and get_corporate_payment(cid=cid_email)['link_version'] == before_email['link_version'])
check('double send to new recipient refused', adm.post(f'/admin/corporate/{cid_email}/send-link', data={'use_saved_link':'1'}).status_code == 409)
check('old-address retry refused', adm.post(f'/admin/notification/{old_notice}/retry-link').status_code == 409)
history = adm.get(f'/admin/corporate/{cid_email}/attempts').get_json()['notifications']
check('delivery history distinguishes both recipients', {n['to_email'] for n in history} == {'old@email.test','new@email.test'} and sum(n['current_recipient'] for n in history) == 1)
new_notice = resent.get_json()['notification_id']
lease, _, why = begin_attempt(new_notice)
check('email cannot change while a send is in flight', lease is not None and edit_email('third@email.test', 'new@email.test').status_code == 409)
finish_attempt(new_notice, lease, transport='mock')
c = get_db(); cur = c.cursor()
cur.execute("UPDATE corporate_payments SET status='cancelled' WHERE id=%s", (cid_email,))
c.commit(); cur.close(); c.close()
check('cancelled invoice email remains historical', edit_email('third@email.test', 'new@email.test').status_code == 409 and get_corporate_payment(cid=cid_email)['contact_email'] == 'new@email.test')

print('\nReplacement invoice creation updates the original intake class')
from db import cancel_corporate_payment, create_class, get_class
replacement_intake = create_intake('Replacement Ops','Ria','hr@replacement-ops.test',None,'training','Online',ADMIN)
_approved_trainee(replacement_intake,'Ria Tan','ria@replacement-ops.test')
issue_registration_token(replacement_intake,created_by=ADMIN)
original_class = next(c for c in list_classes(intake_id=replacement_intake) if c['program_code'] == 'training')
other_program,_ = create_class('Separate CEA','Online',ADMIN,intake_id=replacement_intake,form_type='cea_training')
original_invoice = adm.post(f'/admin/intake/{replacement_intake}/invoice').get_json()['id']
cancel_corporate_payment(original_invoice)
replacement_response = adm.post(f'/admin/intake/{replacement_intake}/invoice')
check('replacement invoice can be created after cancellation', replacement_response.status_code == 200)
replacement_invoice = replacement_response.get_json()['id']
updated_class = get_class(class_id=original_class['id'])
check('class follows the replacement rather than cancelled original', updated_class['corporate_payment_id'] == replacement_invoice)
check('replacement creation keeps the original registration class code', updated_class['join_code'] == original_class['join_code'])
check('replacement creation does not bind a different-program class', get_class(class_id=other_program['id'])['corporate_payment_id'] is None)

failed = [x for x in results if not x[1]]
print(f"\n{'='*64}\n{len(results) - len(failed)}/{len(results)} passed")
for n, _, dd in failed:
    print(f"  FAILED: {n} {dd}")
sys.exit(1 if failed else 0)
