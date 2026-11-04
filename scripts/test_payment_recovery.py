"""Regression: recovery state is reachable for EVERY invoice status, and
unresolved gateway events are linked to the right invoice.

Two gaps this locks down:

  * The payment panel was rendered only for `pending` invoices, so attempts,
    attention flags and unresolved events vanished once an invoice became
    paid, cancelled or expired — exactly the cases where money has moved and
    recovery is needed. The panel is now always available; only *issuing* a
    link is gated, via invoice.collectable.

  * Unresolved events were recorded but never surfaced. They are matched to an
    invoice by reference hint OR by a session id we recorded an attempt for.
    An event matching neither belongs to no invoice and must stay in the
    global queue rather than being attached to an arbitrary one.

    cd src; ..\\venv\\Scripts\\python.exe ..\\scripts\\test_payment_recovery.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from _testdb import use_test_db, assert_isolated   # noqa: E402

use_test_db(recreate=True)
os.environ["MAIL_TRANSPORT"] = "mock"
os.environ["PAYMONGO_MOCK"] = "1"
os.environ.setdefault("PAYMONGO_SECRET_KEY", "sk_test_fake_for_tests")
os.environ.setdefault("SECRET_KEY", "recovery-test-secret")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from datetime import datetime, timedelta             # noqa: E402

from app import app                                  # noqa: E402
from db import (get_db, create_corporate_payment, mark_corporate_paid,
                reserve_attempt, record_session, record_unresolved_event,
                unresolved_events, unresolved_events_for_payment,
                unresolved_event, resolve_event, flag_attention)  # noqa: E402

app.config["WTF_CSRF_ENABLED"] = False
results = []


def check(name, passed, detail=""):
    results.append((name, passed, detail))
    print(f"  [{'PASS' if passed else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))


def _mkuser(role, email):
    c = get_db(); cur = c.cursor()
    cur.execute("""INSERT INTO users (role, fname, lname, email, password_hash,
                   payment_status) VALUES (%s,'T','U',%s,'x','unpaid')
                   ON CONFLICT (email) DO UPDATE SET role = EXCLUDED.role
                   RETURNING id""", (role, email))
    uid = cur.fetchone()[0]; c.commit(); cur.close(); c.close()
    return uid


def _invoice(label):
    uid = _mkuser("trainee", f"{label}@rec.test")
    cid, ref = create_corporate_payment(
        f"{label} Co", "C", f"hr@{label}.test", "0900",
        [{"user_id": uid, "training_type": "Online", "form_type": "training",
          "price_php": 5000.0, "price_label": "CEM Training"}],
        5000.0, None, None, 500000,
        datetime.now() + timedelta(days=3), ADMIN)
    return cid, ref


def _set_status(cid, status):
    c = get_db(); cur = c.cursor()
    cur.execute("UPDATE corporate_payments SET status=%s WHERE id=%s", (status, cid))
    c.commit(); cur.close(); c.close()


print(f"\nisolated database: {assert_isolated()}")
ADMIN = _mkuser("admin", "admin@rec.test")

client = app.test_client()
with client.session_transaction() as s:
    s["user_id"] = ADMIN
    s["user_role"] = "admin"
    s["user_name"] = "Rec Admin"


print("\n1. The panel is served for every invoice status")
for status in ("pending", "paid", "cancelled", "expired"):
    cid, ref = _invoice(f"st{status}")
    if status == "paid":
        assert mark_corporate_paid(cid=cid), "fixture did not settle"
    elif status != "pending":
        _set_status(cid, status)
    r = client.get(f"/admin/corporate/{cid}/attempts")
    check(f"{status}: attempts endpoint answers", r.status_code == 200,
          f"HTTP {r.status_code}")
    d = r.get_json()
    check(f"{status}: collectable is {status == 'pending'}",
          d["invoice"]["collectable"] is (status == "pending"))
    check(f"{status}: attempts and events keys are present",
          "attempts" in d and "events" in d)

print("\n2. Issuing a link is refused once the invoice is not collectable")
cid_paid, ref_paid = _invoice("paidlink")
assert mark_corporate_paid(cid=cid_paid)
r = client.post(f"/admin/corporate/{cid_paid}/payment-link")
check("a paid invoice refuses a new link", r.status_code == 400,
      f"HTTP {r.status_code}")
check("and names the status in the refusal",
      "paid" in (r.get_json().get("error") or "").lower(),
      (r.get_json().get("error") or "")[:60])

print("\n3. A paid invoice still exposes its attempt and attention state")
_att, _err = reserve_attempt(
    cid_paid, 500000, ref_paid, "test",
    {"line_items": [], "description": "x", "reference_number": ref_paid,
     "success_url": "", "cancel_url": "", "metadata": {}}, created_by=ADMIN)
assert _att, _err
record_session(_att["attempt_ref"], "cs_rec_paid", "https://pay.test/a")
flag_attention(cid_paid, "Money arrived after the invoice was settled.")
d = client.get(f"/admin/corporate/{cid_paid}/attempts").get_json()
check("the attempt is listed on a paid invoice", len(d["attempts"]) == 1)
check("its session id is returned",
      d["attempts"][0]["session_id"] == "cs_rec_paid")
check("the attention flag is returned", d["invoice"]["needs_attention"] is True)
check("with its reason", "after the invoice was settled"
      in (d["invoice"]["attention_reason"] or ""))

print("\n4. Events link by reference, by session, or both - never by neither")
cid_a, ref_a = _invoice("evA")
cid_b, ref_b = _invoice("evB")
att_a, _ = reserve_attempt(
    cid_a, 500000, ref_a, "test",
    {"line_items": [], "description": "x", "reference_number": ref_a,
     "success_url": "", "cancel_url": "", "metadata": {}}, created_by=ADMIN)
record_session(att_a["attempt_ref"], "cs_rec_a", "https://pay.test/b")

by_ref = record_unresolved_event("webhook", "amount_mismatch", "Wrong amount.",
                                 {"n": 1}, reference_hint=ref_a)
by_session = record_unresolved_event("webhook", "settlement_lost_race",
                                     "Lost the race.", {"n": 2},
                                     cs_id="cs_rec_a")
by_both = record_unresolved_event("webhook", "livemode_mismatch",
                                  "Live event in test mode.", {"n": 3},
                                  cs_id="cs_rec_a", reference_hint=ref_a)
orphan = record_unresolved_event("webhook", "unmatched_session",
                                 "No invoice matches.", {"n": 4},
                                 cs_id="cs_never_seen")

ids_a = {e["id"] for e in unresolved_events_for_payment(cid_a, ref_a)}
check("an event matched by reference hint is found", by_ref in ids_a)
check("an event matched by session id is found", by_session in ids_a)
check("an event matching both is found once", by_both in ids_a and len(ids_a) == 3)
check("an orphan event is NOT attached to this invoice", orphan not in ids_a)

ids_b = {e["id"] for e in unresolved_events_for_payment(cid_b, ref_b)}
check("another invoice sees none of them", not ids_b)
check("but the orphan IS in the global queue",
      orphan in {e["id"] for e in unresolved_events()})

d = client.get(f"/admin/corporate/{cid_a}/attempts").get_json()
check("the route returns the same three", len(d["events"]) == 3)
check("the queue route returns the orphan too",
      orphan in {e["id"] for e in client.get(
          "/admin/corporate/attention").get_json()["events"]})

print("\n5. An unknown livemode is reported as unknown, not as test")
unknown = record_unresolved_event("webhook", "no_livemode", "Mode absent.",
                                  {"n": 5}, reference_hint=ref_a, livemode=None)
row = [e for e in client.get(
    f"/admin/corporate/{cid_a}/attempts").get_json()["events"]
    if e["id"] == unknown][0]
check("livemode None survives as null, not False", row["livemode"] is None)
known = record_unresolved_event("webhook", "test_mode", "Test event.",
                                {"n": 6}, reference_hint=ref_a, livemode=False)
row = [e for e in client.get(
    f"/admin/corporate/{cid_a}/attempts").get_json()["events"]
    if e["id"] == known][0]
check("an explicit test mode is reported as False", row["livemode"] is False)

print("\n6. Inspecting one event returns its stored payload")
r = client.get(f"/admin/corporate/event/{by_ref}")
check("inspect answers 200", r.status_code == 200, f"HTTP {r.status_code}")
d = r.get_json()
check("the raw payload comes back parsed", d["raw_event"] == {"n": 1},
      str(d["raw_event"])[:40])
check("the reference hint is shown", d["reference_hint"] is not None)
check("a missing event is a 404, not an empty payload",
      client.get("/admin/corporate/event/999999").status_code == 404)

print("\n7. Resolving an event demands a note and happens once")
r = client.post(f"/admin/corporate/event/{by_ref}/resolve", data={"note": ""})
check("an empty note is refused", r.status_code == 400, f"HTTP {r.status_code}")
r = client.post(f"/admin/corporate/event/{by_ref}/resolve", data={"note": "ok"})
check("a too-short note is refused", r.status_code == 400, f"HTTP {r.status_code}")
check("and the event is still unresolved",
      unresolved_event(by_ref)["resolved_at"] is None)

r = client.post(f"/admin/corporate/event/{by_ref}/resolve",
                data={"note": "Refunded in the dashboard on 4 Nov."})
check("a noted resolution succeeds", r.status_code == 200 and r.get_json()["ok"])
ev = unresolved_event(by_ref)
check("it records who and when",
      ev["resolved_at"] is not None and ev["resolved_by"] == ADMIN)
check("and keeps the note", "Refunded" in (ev["resolution_note"] or ""))
check("the resolved event leaves the invoice list",
      by_ref not in {e["id"] for e in unresolved_events_for_payment(cid_a, ref_a)})
check("and leaves the global queue",
      by_ref not in {e["id"] for e in unresolved_events()})

r = client.post(f"/admin/corporate/event/{by_ref}/resolve",
                data={"note": "Trying to resolve it twice."})
check("a second resolution reports ok=False, not a silent success",
      r.get_json().get("ok") is False, str(r.get_json()))
check("the original note is not overwritten",
      "Refunded" in (unresolved_event(by_ref)["resolution_note"] or ""))

print("\n8. The raw payload is preserved verbatim, not summarised")
big = {"data": {"attributes": {"amount": 500000, "currency": "PHP",
                               "livemode": True, "nested": {"deep": [1, 2, 3]}}}}
eid = record_unresolved_event("webhook", "verbatim", "Keep it all.", big,
                              reference_hint=ref_b)
got = client.get(f"/admin/corporate/event/{eid}").get_json()["raw_event"]
check("every field survives the round trip", got == big, str(got)[:60])

failed = [x for x in results if not x[1]]
print(f"\n{'='*64}\n{len(results) - len(failed)}/{len(results)} passed")
for n, _, d in failed:
    print(f"  FAILED: {n} {d}")
sys.exit(1 if failed else 0)
