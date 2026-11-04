"""Phase C tests — company intake, roster and scoped access.

Runs against an ISOLATED database. `src/db/core.py` reads DATABASE_URL at
import time and importing `app` runs init_db(), so use_test_db() has to come
before any db/app import — see scripts/_testdb.py.

    cd src; ..\\venv\\Scripts\\python.exe ..\\scripts\\test_phase_c_intake.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from _testdb import use_test_db, assert_isolated   # noqa: E402

# MUST precede the app/db imports below.
use_test_db(recreate=True)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import threading                                    # noqa: E402
import uuid                                         # noqa: E402
from datetime import datetime, timedelta            # noqa: E402

from app import app                                 # noqa: E402
from db import (get_db, dict_cur, create_intake, get_intake, get_slots,
                add_slot, issue_coordinator_token, revoke_coordinator_token,
                coordinator_access, invitation_state, revoke_slot_invite,
                claim_slot_with_registration, payment_link_eligibility,
                authorize_payment_link_send, hash_token, record_selfie_review,
                REGISTRATION_INSERT_SQL, registration_insert_params,
                create_corporate_payment)  # noqa: E402

app.config["WTF_CSRF_ENABLED"] = False
results = []


def check(name, passed, detail=""):
    results.append((name, passed, detail))
    print(f"  [{'PASS' if passed else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def _entry(form_type="training", **kw):
    e = {"id": str(uuid.uuid4())[:8].upper(), "form_type": form_type,
         "form_label": "Training", "submitted_at": datetime.now(),
         "full_name": "Test Person", "email": "t@example.com"}
    e.update(kw)
    return e


def _set_status(reg_id, status, correction=None):
    c = get_db(); cur = c.cursor()
    cur.execute("UPDATE registrations SET status=%s, correction_note=%s WHERE id=%s",
                (status, correction, reg_id))
    c.commit(); cur.close(); c.close()


print(f"\nisolated database: {assert_isolated()}")

print("\n1. Intake and roster basics")
iid = create_intake("Acme Power", "Jo Cruz", "Jo@Acme.COM", "0917", "training",
                    "CEM Training", None)
intake = get_intake(intake_id=iid)
check("intake created", intake is not None and intake["company_name"] == "Acme Power")
check("contact email normalised to lowercase",
      intake["contact_email"] == "jo@acme.com", intake["contact_email"])

s1, tok1 = add_slot(iid, "Ana Reyes", "ana@acme.com")
s2, tok2 = add_slot(iid, "Ben Santos", "ben@acme.com")
check("two roster slots added", all([s1, s2, tok1, tok2]))

dup_id, dup_tok = add_slot(iid, "Ana Again", "ANA@acme.com")
check("duplicate email rejected case-insensitively", dup_id is None)
check("roster size is still 2", len(get_slots(iid)) == 2)

print("\n2. Derived status: not submitted")
slots = {s["full_name"]: s for s in get_slots(iid)}
check("unsubmitted slot reads not_submitted",
      slots["Ana Reyes"]["derived_status"] == "not_submitted")

print("\n3. Invitation redemption is one transaction")
e = _entry(email="ana@acme.com", full_name="Ana Reyes")
reg_id, err = claim_slot_with_registration(
    tok1, e["id"], REGISTRATION_INSERT_SQL, registration_insert_params(e))
check("invite claimed and registration inserted", reg_id == e["id"] and err is None, str(err))
slots = {s["full_name"]: s for s in get_slots(iid)}
check("slot now linked to the registration",
      slots["Ana Reyes"]["registration_id"] == e["id"])
check("submitted slot reads pending_review",
      slots["Ana Reyes"]["derived_status"] == "pending_review")

print("\n4. Invitation is single-use")
slot, reason = invitation_state(tok1)
check("spent invitation no longer valid", slot is None and reason == "used", str(reason))
e2 = _entry(email="ana@acme.com")
rid2, err2 = claim_slot_with_registration(
    tok1, e2["id"], REGISTRATION_INSERT_SQL, registration_insert_params(e2))
check("replay refused", rid2 is None and err2 == "invalid", str(err2))
c = get_db(); cur = c.cursor()
cur.execute("SELECT COUNT(*) FROM registrations WHERE id=%s", (e2["id"],))
orphan = cur.fetchone()[0]; cur.close(); c.close()
check("refused replay left NO orphan registration", orphan == 0)

print("\n5. Concurrent submissions on one invitation")
s3, tok3 = add_slot(iid, "Cy Lim", "cy@acme.com")
outcomes, lock = [], threading.Lock()


def _race():
    ent = _entry(email="cy@acme.com")
    try:
        rid, er = claim_slot_with_registration(
            tok3, ent["id"], REGISTRATION_INSERT_SQL, registration_insert_params(ent))
    except Exception as exc:                       # pragma: no cover
        rid, er = None, type(exc).__name__
    with lock:
        outcomes.append((rid, er))


threads = [threading.Thread(target=_race) for _ in range(5)]
[t.start() for t in threads]
[t.join() for t in threads]
wins = [o for o in outcomes if o[0]]
check("exactly one of 5 concurrent claims succeeded", len(wins) == 1,
      f"{len(wins)} winner(s) of {len(outcomes)}")
c = get_db(); cur = c.cursor()
cur.execute("SELECT COUNT(*) FROM corporate_intake_slots WHERE id=%s AND registration_id IS NOT NULL", (s3,))
check("slot holds exactly one registration", cur.fetchone()[0] == 1)
cur.close(); c.close()

print("\n6. Revocation and expiry")
s4, tok4 = add_slot(iid, "Di Cruz", "di@acme.com")
revoke_slot_invite(s4)
slot, reason = invitation_state(tok4)
check("revoked invitation refused", slot is None and reason == "invalid")

s5, tok5 = add_slot(iid, "Ed Tan", "ed@acme.com")
c = get_db(); cur = c.cursor()
cur.execute("UPDATE corporate_intake_slots SET invite_expires_at=%s WHERE id=%s",
            (datetime.now() - timedelta(days=1), s5))
c.commit(); cur.close(); c.close()
slot, reason = invitation_state(tok5)
check("expired invitation refused", slot is None and reason == "invalid")

print("\n7. Coordinator link scope, revocation, expiry")
ctok = issue_coordinator_token(iid)
got, reason = coordinator_access(ctok)
check("valid coordinator link resolves to its intake", got and got["id"] == iid)
check("plaintext token is not stored",
      get_intake(intake_id=iid)["coord_token_hash"] == hash_token(ctok))
check("unknown token refused", coordinator_access("nope-not-a-token")[0] is None)
revoke_coordinator_token(iid)
check("revoked coordinator link refused", coordinator_access(ctok)[0] is None)

ctok2 = issue_coordinator_token(iid)
c = get_db(); cur = c.cursor()
cur.execute("UPDATE corporate_intakes SET coord_expires_at=%s WHERE id=%s",
            (datetime.now() - timedelta(days=1), iid))
c.commit(); cur.close(); c.close()
check("expired coordinator link refused", coordinator_access(ctok2)[0] is None)

print("\n8. Company portal boundaries")
iid_b = create_intake("Other Co", "Someone", "s@other.com", None, "training", None, None)
add_slot(iid_b, "Not Yours", "ny@other.com")
ctok3 = issue_coordinator_token(iid)
c = get_db(); cur = c.cursor()
cur.execute("UPDATE corporate_intakes SET coord_expires_at=%s WHERE id=%s",
            (datetime.now() + timedelta(days=30), iid))
c.commit(); cur.close(); c.close()

cl = app.test_client()
r = cl.get(f"/company/roster/{ctok3}")
body = r.get_data(as_text=True)
check("coordinator page renders", r.status_code == 200, f"HTTP {r.status_code}")
check("shows this intake's trainee", "Ana Reyes" in body)
check("does NOT show another intake's trainee", "Not Yours" not in body)
check("no document URL anywhere in the page",
      "/document/" not in body and "/static/uploads" not in body)
check("Referrer-Policy is no-referrer",
      r.headers.get("Referrer-Policy") == "no-referrer")
check("page is noindex", "noindex" in (r.headers.get("X-Robots-Tag") or ""))
r404 = cl.get("/company/roster/definitely-not-a-real-token")
check("bad coordinator token -> 404 generic page", r404.status_code == 404)

print("\n9. Correction notes are visible; review internals are not")
_set_status(e["id"], "needs_correction", "Your valid ID photo is blurred.")
slots = {s["full_name"]: s for s in get_slots(iid)}
check("slot reads needs_correction",
      slots["Ana Reyes"]["derived_status"] == "needs_correction")
r = cl.get(f"/company/roster/{ctok3}")
body = r.get_data(as_text=True)
check("correction text shown to the company", "valid ID photo is blurred" in body)

print("\n10. Payment-link eligibility is recomputed server-side")
ok, reason, detail = payment_link_eligibility(iid)
check("not eligible while anyone is unapproved", ok is False, reason)
check("outstanding trainees are named", "outstanding" in detail)

# Trim the roster to the slots that actually submitted.
c = get_db(); cur = c.cursor()
cur.execute("DELETE FROM corporate_intake_slots WHERE intake_id=%s AND registration_id IS NULL", (iid,))
c.commit(); cur.close(); c.close()

# Accept them, but leave identity review untouched.
for s in get_slots(iid):
    if s["registration_id"]:
        _set_status(s["registration_id"], "accepted")
ok, reason, detail = payment_link_eligibility(iid)
check("ACCEPTED but selfie pending is NOT approved", ok is False, reason)
slots_now = [s for s in get_slots(iid) if s["registration_id"]]
check("accepted-selfie-pending slot reads pending_review",
      all(s["derived_status"] == "pending_review" for s in slots_now),
      str([s["derived_status"] for s in slots_now]))

# Reject identity on one: still not approved, and for the identity reason.
first = slots_now[0]["registration_id"]
record_selfie_review(first, "rejected", None)
r = next(s for s in get_slots(iid) if s["registration_id"] == first)
check("selfie-REJECTED slot is not approved", r["derived_status"] != "approved",
      r["derived_status"])
check("blocker names the identity review",
      any("Identity" in b for b in r["readiness"]["blockers"]),
      str(r["readiness"]["blockers"]))

# Now approve identity for everyone.
c = get_db(); cur = c.cursor()
cur.execute("UPDATE registrations SET selfie_reviewed_at=NULL, selfie_outcome=NULL "
            "WHERE id=%s", (first,))
c.commit(); cur.close(); c.close()
for s in get_slots(iid):
    if s["registration_id"]:
        record_selfie_review(s["registration_id"], "approved", None)
ok, reason, detail = payment_link_eligibility(iid)
check("eligible once accepted AND identity-approved", ok is True, reason)

# Send-once is owned by the notification row, scoped to (payment, version).
# Sending now checks invoice ownership, coverage, recipient and link version.
# A made-up invoice id no longer represents a valid sendable fixture.
items = []
c = get_db(); cur = c.cursor()
for s in get_slots(iid):
    cur.execute("""INSERT INTO users(role,fname,lname,email,password_hash,registration_id)
                   VALUES('trainee',%s,'Test',%s,'x',%s) RETURNING id""",
                (s['full_name'], s['email'], s['registration_id']))
    items.append({'user_id': cur.fetchone()[0], 'training_type': 'Online',
                  'form_type': 'training', 'price_php': 5000, 'price_label': 'CEM Training'})
c.commit(); cur.close(); c.close()
cid, _ = create_corporate_payment('Acme Power','Jo Cruz','hr@acme.com','',items,
    5000*len(items),None,None,500000*len(items),datetime.now()+timedelta(days=1),None)
c = get_db(); cur = c.cursor()
cur.execute('UPDATE corporate_payments SET intake_id=%s,link_version=1 WHERE id=%s', (iid,cid))
c.commit(); cur.close(); c.close()
n1, e1 = authorize_payment_link_send(iid, cid, 1, "hr@acme.com", "Pay", None)
check("first authorization creates the send intent", n1 and e1 is None, str(e1))
n2, e2 = authorize_payment_link_send(iid, cid, 1, "hr@acme.com", "Pay", None)
check("same invoice+version cannot be authorized twice", n2 is None, str(e2))
c = get_db(); cur = c.cursor()
cur.execute('UPDATE corporate_payments SET link_version=2 WHERE id=%s', (cid,))
c.commit(); cur.close(); c.close()
n3, e3 = authorize_payment_link_send(iid, cid, 2, "hr@acme.com", "Pay", None)
check("a REPLACED invoice version can be authorized", n3 and e3 is None, str(e3))

print("\n11. Empty roster is never eligible")
iid_c = create_intake("Empty Co", "Nobody", "n@empty.com", None, "training", None, None)
ok, reason, _ = payment_link_eligibility(iid_c)
check("empty roster refused", ok is False, reason)

print("\n12. Program mismatch is refused")
iid_d = create_intake("Renew Co", "R", "r@renew.com", None, "cea_renewal", None, None)
s6, tok6 = add_slot(iid_d, "Wrong Form", "wf@renew.com")
slot, _ = invitation_state(tok6)
check("invitation knows its program", slot and slot["form_type"] == "cea_renewal")

failed = [r for r in results if not r[1]]
print(f"\n{'='*64}\n{len(results) - len(failed)}/{len(results)} passed")
for n, _, d in failed:
    print(f"  FAILED: {n} {d}")
sys.exit(1 if failed else 0)
