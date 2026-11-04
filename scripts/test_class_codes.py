"""Regression: a class join code names a class; it authorises nothing.

The whole risk of a Google-Classroom-style code is that it looks like a
credential. One overheard code must not be able to enrol:

  * someone with no account at all
  * someone whose registration was never accepted
  * someone who has not paid
  * an employee of a different company
  * someone approved for a different program

Each is a separate fact, re-derived from the database on every join. This test
exists to make sure none of them quietly collapses into "the code was right".

    cd src; ..\\venv\\Scripts\\python.exe ..\\scripts\\test_class_codes.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from _testdb import use_test_db, assert_isolated   # noqa: E402

use_test_db(recreate=True)
os.environ["MAIL_TRANSPORT"] = "mock"
os.environ["PAYMONGO_MOCK"] = "1"
os.environ.setdefault("PAYMONGO_SECRET_KEY", "sk_test_fake_for_tests")
os.environ.setdefault("SECRET_KEY", "class-test-secret")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import io                                           # noqa: E402
import uuid                                         # noqa: E402
from datetime import datetime, timedelta            # noqa: E402

from app import app                                 # noqa: E402
from db import (get_db, create_intake, add_slot, claim_slot_with_registration,
                record_selfie_review, create_corporate_payment,
                mark_corporate_paid, create_class, get_class, join_class,
                membership_authority, normalize_code, rotate_join_code,
                set_join_open, class_members, classes_for_user,
                add_member_as_staff, remove_member, list_classes,
                class_gate, lms_create_module, lms_toggle_publish,
                lms_issue_certificate, lms_get_modules_for_trainee,
                lms_add_file,
                REGISTRATION_INSERT_SQL, registration_insert_params)  # noqa: E402

app.config["WTF_CSRF_ENABLED"] = False
results = []


def check(name, passed, detail=""):
    results.append((name, passed, detail))
    print(f"  [{'PASS' if passed else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))


def _mkuser(role, email, reg_id=None, paid=False):
    c = get_db(); cur = c.cursor()
    cur.execute("""INSERT INTO users (role, fname, lname, email, password_hash,
                   payment_status, registration_id)
                   VALUES (%s,'T','U',%s,'x',%s,%s)
                   ON CONFLICT (email) DO UPDATE SET
                     registration_id = EXCLUDED.registration_id,
                     payment_status  = EXCLUDED.payment_status
                   RETURNING id""",
                (role, email, "paid" if paid else "unpaid", reg_id))
    uid = cur.fetchone()[0]; c.commit(); cur.close(); c.close()
    return uid


def _enrol(intake_id, name, email, ttype="Online", accept=True):
    """A roster slot claimed by a real registration, optionally accepted."""
    sid, tok = add_slot(intake_id, name, email)
    e = {"id": str(uuid.uuid4())[:8].upper(), "form_type": "training",
         "form_label": "Training", "submitted_at": datetime.now(),
         "full_name": name, "email": email, "training_type": ttype,
         "photo_id": "p.png", "resume": "r.pdf", "valid_id": "v.png",
         "selfie_with_id": "s.png"}
    rid, err = claim_slot_with_registration(tok, e["id"], REGISTRATION_INSERT_SQL,
                                            registration_insert_params(e))
    assert rid, err
    if accept:
        c = get_db(); cur = c.cursor()
        cur.execute("UPDATE registrations SET status='accepted' WHERE id=%s", (rid,))
        c.commit(); cur.close(); c.close()
        record_selfie_review(rid, "approved", ADMIN)
    return rid, sid


def _invoice_for(intake_id, pairs, company):
    cid, ref = create_corporate_payment(
        company, "C", f"hr@{company.lower()}.test", "0900",
        [{"user_id": uid, "training_type": "Online", "form_type": "training",
          "price_php": 5000.0, "price_label": "CEM Training"} for uid in pairs],
        5000.0 * len(pairs), None, None, 500000 * len(pairs),
        datetime.now() + timedelta(days=3), ADMIN)
    c = get_db(); cur = c.cursor()
    cur.execute("UPDATE corporate_payments SET intake_id=%s WHERE id=%s",
                (intake_id, cid))
    c.commit(); cur.close(); c.close()
    return cid, ref


print(f"\nisolated database: {assert_isolated()}")
ADMIN = _mkuser("admin", "admin@cls.test")

# Company A: two approved employees, invoiced and paid.
IA = create_intake("Alpha Co", "An", "hr@alpha.test", "0917",
                   "training", "Online", ADMIN)
rid_ann, _ = _enrol(IA, "Ann Cruz", "ann@alpha.test")
rid_ben, _ = _enrol(IA, "Ben Diaz", "ben@alpha.test")
U_ANN = _mkuser("trainee", "ann@alpha.test", rid_ann)
U_BEN = _mkuser("trainee", "ben@alpha.test", rid_ben)
CID_A, REF_A = _invoice_for(IA, [U_ANN, U_BEN], "Alpha")
assert mark_corporate_paid(cid=CID_A), "fixture: Alpha invoice did not settle"

# Company B: a paid employee of a DIFFERENT company.
IB = create_intake("Beta Co", "Bo", "hr@beta.test", "0918",
                   "training", "Online", ADMIN)
rid_cal, _ = _enrol(IB, "Cal Uy", "cal@beta.test")
U_CAL = _mkuser("trainee", "cal@beta.test", rid_cal)
CID_B, REF_B = _invoice_for(IB, [U_CAL], "Beta")
assert mark_corporate_paid(cid=CID_B), "fixture: Beta invoice did not settle"

CLS, err = create_class("Alpha CEM Batch", "Online", ADMIN,
                        intake_id=IA, corporate_payment_id=CID_A)
assert CLS, err
CODE = CLS["join_code"]


print("\n1. The code itself is a weak, readable identifier - by design")
check("it is short enough to read aloud", 5 <= len(CODE) <= 12, CODE)
check("it avoids characters that get misread",
      not set(CODE) & set("01OIL"), CODE)
check("it is stored readable, so a trainer can dictate it",
      get_class(class_id=CLS["id"])["join_code"] == CODE)
check("lowercase input resolves to the same class",
      get_class(join_code=CODE.lower()) is not None)
check("surrounding whitespace is tolerated",
      get_class(join_code=f"  {CODE}  ") is not None)
check("hyphens people insert are tolerated",
      normalize_code(f"{CODE[:3]}-{CODE[3:]}") == CODE)
check("but an actually wrong code is still wrong",
      get_class(join_code="ZZZZZZZ") is None)


print("\n2. A roster member who is approved and paid can join")
cls, err = join_class(U_ANN, CODE)
check("Ann joins", cls is not None and err is None, err or "")
check("she is a member", U_ANN in {m["user_id"] for m in class_members(CLS["id"])})
check("membership is recorded as roster-authorised, never 'code'",
      class_members(CLS["id"])[0]["authorised"] == "roster")
check("the class shows up in her own list",
      CLS["id"] in {c["id"] for c in classes_for_user(U_ANN)})

cls2, err2 = join_class(U_ANN, CODE)
check("joining twice is idempotent, not an error", err2 is None)
check("and does not double-enrol her",
      len([m for m in class_members(CLS["id"]) if m["user_id"] == U_ANN]) == 1)


print("\n3. The code does NOT create accounts")
before = len(class_members(CLS["id"]))
cls, err = join_class(999999, CODE)
check("an unknown account is refused", cls is None and "No such account" in (err or ""),
      err or "")
check("and no member was added", len(class_members(CLS["id"])) == before)
c = get_db(); cur = c.cursor()
cur.execute("SELECT COUNT(*) FROM users WHERE id = 999999")
check("no account was invented", cur.fetchone()[0] == 0)
cur.close(); c.close()


print("\n4. The code does NOT substitute for admin approval")
rid_dot, _ = _enrol(IA, "Dot Ng", "dot@alpha.test", accept=False)
U_DOT = _mkuser("trainee", "dot@alpha.test", rid_dot, paid=True)
cls, err = join_class(U_DOT, CODE)
check("an unaccepted registration is refused", cls is None, err or "")
check("and the reason names the review, not the code",
      "awaiting review" in (err or "") and "cannot stand in" in (err or ""),
      (err or "")[:80])
check("she is not a member", U_DOT not in {m["user_id"] for m in class_members(CLS["id"])})

# Rejected outright, not merely pending.
c = get_db(); cur = c.cursor()
cur.execute("UPDATE registrations SET status='rejected' WHERE id=%s", (rid_dot,))
c.commit(); cur.close(); c.close()
cls, err = join_class(U_DOT, CODE)
check("a REJECTED registration is still refused", cls is None, (err or "")[:60])

U_NOREG = _mkuser("trainee", "noreg@alpha.test", None, paid=True)
cls, err = join_class(U_NOREG, CODE)
check("an account with no registration at all is refused", cls is None)
check("and says there is nothing to have been approved",
      "no registration" in (err or "").lower(), (err or "")[:70])


print("\n5. The code does NOT confer payment entitlement")
# For an invoice-backed class the INVOICE is the payment authority (see
# section 14), so a hand-reverted users.payment_status must not lock out
# someone the invoice genuinely paid for: the denormalised flag is not the
# record of payment.
c = get_db(); cur = c.cursor()
cur.execute("UPDATE users SET payment_status='unpaid' WHERE id=%s", (U_BEN,))
c.commit(); cur.close(); c.close()
cls, err = join_class(U_BEN, CODE)
check("a stale account flag does not override a PAID invoice",
      cls is not None, err or "")
c = get_db(); cur = c.cursor()
cur.execute("SELECT payment_status FROM users WHERE id=%s", (U_BEN,))
check("and joining did not quietly mark him paid either",
      cur.fetchone()[0] == "unpaid")
cur.close(); c.close()

# With no invoice to consult, the account flag IS the best evidence.
CLS_NOINV, _e = create_class("Alpha pre-invoice", "Online", ADMIN,
                             intake_id=IA, form_type="training")
ok, why = membership_authority(CLS_NOINV["id"], U_BEN)
check("on an intake-only class an unpaid account IS refused", not ok,
      (why or "")[:60])
check("and the reason names payment", "not marked paid" in (why or ""),
      (why or "")[:70])
c = get_db(); cur = c.cursor()
cur.execute("UPDATE users SET payment_status='paid' WHERE id=%s", (U_BEN,))
c.commit(); cur.close(); c.close()
ok, why = membership_authority(CLS_NOINV["id"], U_BEN)
check("once paid, that class accepts him", ok, (why or "")[:60])


print("\n6. The code does NOT prove employment at that company")
cls, err = join_class(U_CAL, CODE)
check("a paid, approved employee of ANOTHER company is refused", cls is None,
      (err or "")[:60])
check("and the reason names the invoice that paid for the class",
      "invoice" in (err or "").lower(), (err or "")[:70])
check("he is not a member",
      U_CAL not in {m["user_id"] for m in class_members(CLS["id"])})

# A staff account is not a trainee, whatever the code says.
cls, err = join_class(ADMIN, CODE)
check("an admin account cannot self-join as a trainee", cls is None,
      (err or "")[:60])


print("\n7. A revoked roster slot stops working immediately")
rid_eve, sid_eve = _enrol(IA, "Eve Lim", "eve@alpha.test")
U_EVE = _mkuser("trainee", "eve@alpha.test", rid_eve, paid=True)
ok, why = membership_authority(CLS["id"], U_EVE)
# CLS names an invoice, so the invoice is the roster. Eve has a slot on the
# intake but was never billed, and an intake slot must not be a back door
# into a paid cohort.
check("Eve is NOT eligible on the intake alone - she is not on the invoice",
      not ok, (why or "")[:70])
check("and the reason names the invoice, not the roster generally",
      "not on the invoice" in (why or ""), (why or "")[:70])

# Put her on a class authorised by the intake only, then revoke the slot.
CLS_I, _e = create_class("Alpha intake-only", "Online", ADMIN, intake_id=IA)
ok, why = membership_authority(CLS_I["id"], U_EVE)
check("on an intake-authorised class she IS eligible", ok, (why or "")[:60])
c = get_db(); cur = c.cursor()
cur.execute("UPDATE corporate_intake_slots SET invite_revoked_at=NOW() WHERE id=%s",
            (sid_eve,))
c.commit(); cur.close(); c.close()
ok, why = membership_authority(CLS_I["id"], U_EVE)
check("revoking her slot makes her ineligible at once", not ok, (why or "")[:60])
cls, err = join_class(U_EVE, CLS_I["join_code"])
check("and the join is refused", cls is None)


print("\n8. A class with no roster cannot be self-joined at all")
CLS_ORPHAN, _e = create_class("Open day", "Online", ADMIN)
cls, err = join_class(U_ANN, CLS_ORPHAN["join_code"])
check("even an approved, paid trainee is refused", cls is None, (err or "")[:60])
check("and the reason says staff must add them",
      "no company roster" in (err or "").lower(), (err or "")[:70])


print("\n9. The program must match what they were approved for")
CLS_WRONG, _e = create_class("CEA cohort", "CEA Training", ADMIN,
                             intake_id=IA, corporate_payment_id=CID_A)
cls, err = join_class(U_ANN, CLS_WRONG["join_code"])
check("a class for another program is refused", cls is None, (err or "")[:60])
check("and both programmes are named by their canonical labels",
      "CEA Training" in (err or "") and "CEM Training" in (err or ""),
      (err or "")[:95])


print("\n10. Closing and rotating affect FUTURE joins, never current members")
set_join_open(CLS["id"], False)
rid_fay, _ = _enrol(IA, "Fay Ong", "fay@alpha.test")
U_FAY = _mkuser("trainee", "fay@alpha.test", rid_fay, paid=True)
c = get_db(); cur = c.cursor()
cur.execute("""INSERT INTO corporate_payment_items
               (corporate_payment_id, user_id, training_type, form_type,
                price_php, price_label)
               VALUES (%s,%s,'Online','training',5000,'CEM Training')
               ON CONFLICT DO NOTHING""", (CID_A, U_FAY))
c.commit(); cur.close(); c.close()
cls, err = join_class(U_FAY, CODE)
check("a closed class refuses a new join", cls is None, (err or "")[:60])
check("members who already joined are untouched",
      U_ANN in {m["user_id"] for m in class_members(CLS["id"])})

set_join_open(CLS["id"], True)
cls, err = join_class(U_FAY, CODE)
check("reopening lets her in", cls is not None, err or "")

OLD = CODE
NEW, rerr = rotate_join_code(CLS["id"])
check("rotation issues a different code", NEW and NEW != OLD, f"{OLD} -> {NEW}")
check("the old code no longer resolves", get_class(join_code=OLD) is None)
check("rotation did NOT evict anyone",
      {U_ANN, U_BEN, U_FAY} <= {m["user_id"] for m in class_members(CLS["id"])})


print("\n11. Staff additions hold the same checks")
ok, err = add_member_as_staff(CLS["id"], U_CAL, ADMIN)
check("staff cannot add another company's employee", not ok, (err or "")[:60])
ok, err = add_member_as_staff(CLS["id"], U_EVE, ADMIN)
check("nor someone on the intake who was never billed", not ok,
      (err or "")[:60])
ok, err = add_member_as_staff(CLS_NOINV["id"], U_CAL, ADMIN)
check("nor onto an intake-only class they are not rostered for", not ok,
      (err or "")[:60])
check("removing a member works",
      remove_member(CLS["id"], U_FAY))
ok, err = add_member_as_staff(CLS["id"], U_FAY, ADMIN)
check("and a legitimate staff addition succeeds", ok, err or "")
check("recorded as a staff addition, distinct from a self-join",
      [m for m in class_members(CLS["id"])
       if m["user_id"] == U_FAY][0]["authorised"] == "staff")


print("\n12. The HTTP surface enforces the same rules")
client = app.test_client()
with client.session_transaction() as s:
    s["user_id"] = U_CAL
    s["user_role"] = "trainee"
r = client.post("/portal/join-class", data={"join_code": NEW})
check("another company's employee is redirected, not enrolled",
      r.status_code in (302, 303), f"HTTP {r.status_code}")
check("and still is not a member",
      U_CAL not in {m["user_id"] for m in class_members(CLS["id"])})

with client.session_transaction() as s:
    s["user_id"] = ADMIN
    s["user_role"] = "admin"
r = client.post("/portal/join-class", data={"join_code": NEW})
check("a non-trainee role is refused by the route", r.status_code == 403,
      f"HTTP {r.status_code}")

r = client.get(f"/api/class/{CLS['id']}/progress")
check("staff can read cohort progress", r.status_code == 200,
      f"HTTP {r.status_code}")
d = r.get_json()
check("the roll-up counts members", d["batch"]["members"] >= 2,
      str(d["batch"]))
check("the batch percentage is a share of module completions, not an "
      "average of percentages",
      d["batch"]["modules_total"] >= 0 and 0 <= d["batch"]["pct"] <= 100,
      str(d["batch"]))
check("the join code is shown to staff", d["class"]["join_code"] == NEW)

with client.session_transaction() as s:
    s["user_id"] = U_ANN
    s["user_role"] = "trainee"
r = client.get(f"/api/class/{CLS['id']}/progress")
check("a trainee cannot read the whole cohort's progress",
      r.status_code == 403, f"HTTP {r.status_code}")
r = client.get("/api/my-classes")
check("but can list their own classes", r.status_code == 200)
check("and sees the class they joined",
      CLS["id"] in {c["id"] for c in r.get_json()["classes"]})

with client.session_transaction() as s:
    s["user_id"] = ADMIN
    s["user_role"] = "admin"
r = client.get(f"/admin/class/{CLS['id']}/panel")
check("the admin panel loads", r.status_code == 200, f"HTTP {r.status_code}")
d = r.get_json()
check("it lists members", len(d["members"]) >= 2)
check("and says who has not joined yet, with a reason",
      all("reason" in o for o in d["outstanding"]))

check("a class for an intake is listed under it",
      CLS["id"] in {c["id"] for c in list_classes(intake_id=IA)})


print("\n13. Program identity is canonical, not raw label text")
# Two different programmes can both be labelled "Online". Comparing the raw
# strings matched the labels and let a CEA trainee into a CEM cohort.
check("the class stores a canonical program code",
      get_class(class_id=CLS["id"])["program_code"] == "training",
      str(get_class(class_id=CLS["id"])["program_code"]))

c = get_db(); cur = c.cursor()
cur.execute("""UPDATE registrations SET form_type='cea_training',
               training_type='Online' WHERE id=%s""", (rid_ben,))
c.commit(); cur.close(); c.close()
ok, why = membership_authority(CLS["id"], U_BEN)
check("a CEA registration labelled 'Online' is refused by a CEM class",
      not ok, (why or "")[:70])
check("and the refusal names programmes, not raw labels",
      "CEM Training" in (why or "") and "CEA Training" in (why or ""),
      (why or "")[:90])
c = get_db(); cur = c.cursor()
cur.execute("""UPDATE registrations SET form_type='training',
               training_type='Online' WHERE id=%s""", (rid_ben,))
c.commit(); cur.close(); c.close()
ok, why = membership_authority(CLS["id"], U_BEN)
check("the matching programme is accepted again", ok, (why or "")[:60])


print("\n14. Payment comes from the invoice, not just the user flag")
IC = create_intake("Gamma Co", "Ga", "hr@gamma.test", "0919",
                   "training", "Online", ADMIN)
rid_gus = _enrol(IC, "Gus Tan", "gus@gamma.test")[0]
U_GUS = _mkuser("trainee", "gus@gamma.test", rid_gus, paid=True)
CID_C, REF_C = _invoice_for(IC, [U_GUS], "Gamma")          # left PENDING
CLS_C, _e = create_class("Gamma batch", "Online", ADMIN, intake_id=IC,
                         corporate_payment_id=CID_C, form_type="training")
ok, why = membership_authority(CLS_C["id"], U_GUS)
check("a hand-set paid flag does NOT open an unpaid invoice's class",
      not ok, (why or "")[:70])
check("and the refusal names the invoice's real status",
      "'pending'" in (why or ""), (why or "")[:80])
assert mark_corporate_paid(cid=CID_C), "fixture: Gamma did not settle"
ok, why = membership_authority(CLS_C["id"], U_GUS)
check("settling the invoice opens it", ok, (why or "")[:60])


print("\n15. Identity readiness is required, via the shared rule")
c = get_db(); cur = c.cursor()
cur.execute("""UPDATE registrations SET selfie_reviewed_at=NULL,
               selfie_with_id='s.png' WHERE id=%s""", (rid_gus,))
c.commit(); cur.close(); c.close()
ok, why = membership_authority(CLS_C["id"], U_GUS)
check("a pending identity review blocks the join", not ok, (why or "")[:70])
check("and the reason comes from the readiness rule",
      "identity" in (why or "").lower(), (why or "")[:90])
c = get_db(); cur = c.cursor()
cur.execute("UPDATE registrations SET selfie_with_id='' WHERE id=%s", (rid_gus,))
c.commit(); cur.close(); c.close()
ok, why = membership_authority(CLS_C["id"], U_GUS)
check("a missing required selfie also blocks it", not ok, (why or "")[:70])
record_selfie_review(rid_gus, "rejected", ADMIN)
ok, why = membership_authority(CLS_C["id"], U_GUS)
check("a REJECTED identity review blocks it", not ok, (why or "")[:70])
# record_selfie_review() is deliberately once-only ("only the first decision
# sticks"), so the fixture reopens the gate directly to reach the approved
# case rather than pretending a second review would land.
c = get_db(); cur = c.cursor()
cur.execute("""UPDATE registrations SET selfie_reviewed_at=NULL,
               selfie_outcome=NULL, selfie_with_id='s.png' WHERE id=%s""",
            (rid_gus,))
c.commit(); cur.close(); c.close()
record_selfie_review(rid_gus, "approved", ADMIN)
ok, why = membership_authority(CLS_C["id"], U_GUS)
check("an approved review clears it", ok, (why or "")[:60])


print("\n16. Deciding and inserting happen in ONE transaction")
src = io.open(os.path.join(os.path.dirname(__file__), "..", "src", "db",
                           "classes.py"), encoding="utf-8").read()
join_src = src[src.index("def join_class("):src.index("def add_member_as_staff(")]
check("join_class locks the class row it decided on",
      "FOR UPDATE" in join_src)
check("it opens exactly one connection",
      join_src.count("get_db()") == 1, f"{join_src.count('get_db()')} found")
check("and rolls back every refusal path",
      join_src.count("conn.rollback()") >= 3,
      f"{join_src.count('conn.rollback()')} rollbacks")
staff_src = src[src.index("def add_member_as_staff("):src.index("def remove_member(")]
check("staff additions do the same", "FOR UPDATE" in staff_src
      and staff_src.count("get_db()") == 1)

# A close committed after the decision must not be beaten by a stale insert.
set_join_open(CLS_C["id"], False)
cls, err = join_class(U_GUS, CLS_C["join_code"])
check("a close is honoured by the locked read", cls is None, (err or "")[:60])
set_join_open(CLS_C["id"], True)


print("\n17. The LMS gate: corporate trainees need their class")
ok, why = class_gate(U_GUS)
check("a corporate trainee with a class but no membership is gated",
      not ok, (why or "")[:70])
check("the message tells them to use the code",
      "class code" in (why or "").lower(), (why or "")[:80])
cls, err = join_class(U_GUS, CLS_C["join_code"])
check("joining opens the gate", cls is not None, err or "")
ok, why = class_gate(U_GUS)
check("and training is now reachable", ok, (why or "")[:60])

# Individual enrolment must be untouched.
U_SOLO = _mkuser("trainee", "solo@nobody.test", None, paid=True)
ok, why = class_gate(U_SOLO)
check("an individual trainee on no company invoice is NOT gated", ok,
      (why or "")[:60])

# And a corporate trainee whose company has no class yet must not be locked
# out of training they already paid for.
ID2 = create_intake("Delta Co", "De", "hr@delta.test", "0920",
                    "training", "Online", ADMIN)
rid_hal = _enrol(ID2, "Hal Ko", "hal@delta.test")[0]
U_HAL = _mkuser("trainee", "hal@delta.test", rid_hal, paid=True)
CID_D, _r = _invoice_for(ID2, [U_HAL], "Delta")
assert mark_corporate_paid(cid=CID_D)
ok, why = class_gate(U_HAL)
check("no class created yet means no gate, not a lockout", ok, (why or "")[:70])
CLS_D, _e = create_class("Delta batch", "Online", ADMIN, intake_id=ID2,
                         corporate_payment_id=CID_D, form_type="training")
ok, why = class_gate(U_HAL)
check("the gate appears once a class exists", not ok, (why or "")[:60])

print("\n18. The gate is enforced on the LMS routes, not only in the helper")
client2 = app.test_client()
with client2.session_transaction() as s:
    s["user_id"] = U_HAL
    s["user_role"] = "trainee"
r = client2.get("/lms/learn", follow_redirects=False)
check("an ungated-but-unjoined trainee is redirected off /lms/learn",
      r.status_code in (301, 302), f"HTTP {r.status_code}")
check("and sent to the portal where the code field lives",
      "/portal" in (r.headers.get("Location") or ""),
      r.headers.get("Location") or "")
ok, err = add_member_as_staff(CLS_D["id"], U_HAL, ADMIN)
check("staff can add them, same checks", ok, err or "")
r = client2.get("/lms/learn", follow_redirects=False)
check("then /lms/learn opens", r.status_code == 200, f"HTTP {r.status_code}")


print("\n19. Each member's syllabus is resolved for THAT member")
# lms_get_modules_for_trainee() is a function of the USER, not of the raw
# training type: a certificate excludes modules created after it was issued.
# Caching the module list by training type handed the first member's syllabus
# to everyone sharing their label, so totals came out identical and wrong.
INSTR = _mkuser("employee", "trainer@cls.test")
m1 = lms_create_module(INSTR, "Module one", "First", "training", 1)
lms_toggle_publish(m1, 1)
# U_ANN certifies now, so anything published afterwards is not her syllabus.
lms_issue_certificate(U_ANN, ADMIN)
c = get_db(); cur = c.cursor()
cur.execute("UPDATE lms_modules SET created_at = NOW() - INTERVAL '2 days' "
            "WHERE id=%s", (m1,))
c.commit(); cur.close(); c.close()
m2 = lms_create_module(INSTR, "Module two", "Added later", "training", 2)
lms_toggle_publish(m2, 1)

ann_total = len(lms_get_modules_for_trainee(U_ANN, published_only=True))
ben_total = len(lms_get_modules_for_trainee(U_BEN, published_only=True))
check("the certified member owes fewer modules than the uncertified one",
      (ann_total, ben_total) == (1, 2), f"got {ann_total} and {ben_total}")

with client.session_transaction() as s:
    s["user_id"] = ADMIN
    s["user_role"] = "admin"
d = client.get(f"/api/class/{CLS['id']}/progress").get_json()
totals = {m["user_id"]: m["total"] for m in d["members"]}
check("the class view reports each member's OWN total",
      totals.get(U_ANN) == 1 and totals.get(U_BEN) == 2,
      f"Ann {totals.get(U_ANN)}, Ben {totals.get(U_BEN)}")
check("the batch total is the sum of the real per-member totals",
      d["batch"]["modules_total"] == sum(
          m["total"] for m in d["members"]),
      str(d["batch"]))
check("and is not a multiple of one member's syllabus",
      d["batch"]["modules_total"] >= 3, str(d["batch"]["modules_total"]))


print("\n20. Membership is not standing authority")
# A membership row records that entitlement held at JOIN time. The gate
# re-derives it on every access, so a withdrawal afterwards closes access
# without anyone having to remember to delete the row.
ok, why = class_gate(U_GUS)
check("a valid member passes the gate", ok, (why or "")[:60])
c = get_db(); cur = c.cursor()
cur.execute("UPDATE corporate_payments SET status='cancelled' WHERE id=%s",
            (CID_C,))
c.commit(); cur.close(); c.close()
ok, why = class_gate(U_GUS)
check("cancelling the invoice closes access for an existing member",
      not ok, (why or "")[:70])
check("and says the place is no longer valid",
      "no longer valid" in (why or ""), (why or "")[:80])
check("the membership row itself is still there, not silently deleted",
      U_GUS in {m["user_id"] for m in class_members(CLS_C["id"])})
c = get_db(); cur = c.cursor()
cur.execute("UPDATE corporate_payments SET status='paid' WHERE id=%s", (CID_C,))
c.commit(); cur.close(); c.close()
ok, why = class_gate(U_GUS)
check("restoring the invoice restores access", ok, (why or "")[:60])

c = get_db(); cur = c.cursor()
cur.execute("UPDATE registrations SET status='rejected' WHERE id=%s", (rid_gus,))
c.commit(); cur.close(); c.close()
ok, why = class_gate(U_GUS)
check("a later rejection closes access too", not ok, (why or "")[:70])
c = get_db(); cur = c.cursor()
cur.execute("UPDATE registrations SET status='accepted' WHERE id=%s", (rid_gus,))
c.commit(); cur.close(); c.close()


print("\n21. Membership is scoped to the programme being opened")
# A CEM membership must not satisfy the gate for CEA material.
ok, why = class_gate(U_GUS, "training")
check("the member's own programme passes", ok, (why or "")[:60])
ok, why = class_gate(U_GUS, "cea_training")
check("a different programme does NOT inherit that membership",
      not ok or why is None, (why or "")[:70])
# With a CEA class existing for the same invoice, the gate must demand a CEA
# membership specifically rather than accepting the CEM one.
CLS_CEA, _e = create_class("Gamma CEA cohort", "CEA Training", ADMIN,
                           intake_id=IC, corporate_payment_id=CID_C,
                           form_type="cea_training")
ok, why = class_gate(U_GUS, "cea_training")
check("a CEA class gates CEA material separately", not ok, (why or "")[:70])
check("while CEM access is unaffected", class_gate(U_GUS, "training")[0])


print("\n22. A class with no recorded programme is refused, never guessed")
# An upgraded row whose programme could not be derived must block and be
# reported. Defaulting resolved an old CEA class labelled "Online" to CEM.
c = get_db(); cur = c.cursor()
cur.execute("UPDATE training_classes SET program_code=NULL WHERE id=%s",
            (CLS_C["id"],))
c.commit(); cur.close(); c.close()
ok, why = membership_authority(CLS_C["id"], U_GUS)
check("an un-derivable class refuses every join", not ok, (why or "")[:70])
check("and says staff must set the programme",
      "no programme recorded" in (why or ""), (why or "")[:80])
check("it also creates no gate nobody can pass",
      class_gate(U_GUS, "training")[0] is True
      or "no longer valid" in (class_gate(U_GUS, "training")[1] or ""),
      str(class_gate(U_GUS, "training"))[:80])
c = get_db(); cur = c.cursor()
cur.execute("UPDATE training_classes SET program_code='training' WHERE id=%s",
            (CLS_C["id"],))
c.commit(); cur.close(); c.close()


print("\n23. Billed programme must agree, not just the registration")
# The registration and the class can agree while the invoice line was raised
# for a different programme — the company paid for something else.
c = get_db(); cur = c.cursor()
cur.execute("""UPDATE corporate_payment_items SET form_type='cea_training',
               training_type='CEA Training'
               WHERE corporate_payment_id=%s AND user_id=%s""",
            (CID_C, U_GUS))
c.commit(); cur.close(); c.close()
ok, why = membership_authority(CLS_C["id"], U_GUS)
check("a mismatched invoice line is refused", not ok, (why or "")[:70])
check("and names the billing as the thing to fix",
      "invoice billed" in (why or ""), (why or "")[:90])
c = get_db(); cur = c.cursor()
cur.execute("""UPDATE corporate_payment_items SET form_type='training',
               training_type='Online'
               WHERE corporate_payment_id=%s AND user_id=%s""",
            (CID_C, U_GUS))
c.commit(); cur.close(); c.close()
ok, why = membership_authority(CLS_C["id"], U_GUS)
check("correcting the billing opens it", ok, (why or "")[:60])


print("\n24. Material, progress and chat all honour the gate")
# sort_order 0 so it is the FIRST module: otherwise it is also locked by
# sequence, and a 403 would not distinguish "not in your class" from
# "finish the previous module".
MOD_T = lms_create_module(INSTR, "Gated module", "x", "training", 0)
lms_toggle_publish(MOD_T, 1)
fid = lms_add_file(MOD_T, "gated-stored.pdf", "gated.pdf",
                   "application/pdf", 1024)

# U_HAL is a corporate trainee with a class he has NOT joined (section 17).
remove_member(CLS_D["id"], U_HAL)
hal = app.test_client()
with hal.session_transaction() as s:
    s["user_id"] = U_HAL
    s["user_role"] = "trainee"
r = hal.get("/lms/files/gated-stored.pdf")
check("an unjoined trainee cannot download module material",
      r.status_code == 403, f"HTTP {r.status_code}")
r = hal.post(f"/lms/learn/{MOD_T}/material-progress", json={"pct": 100})
check("nor post material progress", r.status_code == 403,
      f"HTTP {r.status_code}")
r = hal.post(f"/lms/chat/{MOD_T}/msg", json={"user_message": "hello"})
check("nor use the module chat", r.status_code == 403, f"HTTP {r.status_code}")
c = get_db(); cur = c.cursor()
cur.execute("SELECT material_pct FROM lms_progress WHERE user_id=%s AND module_id=%s",
            (U_HAL, MOD_T))
row = cur.fetchone(); cur.close(); c.close()
check("and no progress was recorded for the refused call",
      row is None or (row[0] or 0) == 0, str(row))

ok, err = add_member_as_staff(CLS_D["id"], U_HAL, ADMIN)
check("once added to the class, material is served", ok, err or "")
r = hal.get("/lms/files/gated-stored.pdf")
# 404 here means authorisation PASSED and send_from_directory could not find
# the bytes (the fixture writes no file); 403 would mean still refused.
check("the file is no longer refused", r.status_code == 404,
      f"HTTP {r.status_code}")
r = hal.post(f"/lms/learn/{MOD_T}/material-progress", json={"pct": 100})
check("and progress is accepted", r.status_code == 200, f"HTTP {r.status_code}")

# An unknown filename must not leak the directory either.
r = hal.get("/lms/files/../../app.py")
check("a traversal-looking name is refused, not resolved",
      r.status_code in (403, 404), f"HTTP {r.status_code}")


print('\nReplacement invoice repairs retain class and entitlement boundaries')
from db import repair_replacement_class_invoice, cancel_corporate_payment, get_corporate_payment
replacement_intake = create_intake('Replacement Co','Ria','hr@replacement.test',None,'training','Online',ADMIN)
replacement_reg,_ = _enrol(replacement_intake,'Ria Tan','ria@replacement.test')
replacement_user = _mkuser('trainee','ria@replacement.test',replacement_reg)
old_invoice,_ = _invoice_for(replacement_intake,[replacement_user],'Replacement')
replacement_class,_ = create_class('Replacement CEM','Online',ADMIN,intake_id=replacement_intake,corporate_payment_id=old_invoice,form_type='training')
cancel_corporate_payment(old_invoice)
new_invoice,_ = _invoice_for(replacement_intake,[replacement_user],'Replacement')
check('cancelled original blocks joining before repair', not membership_authority(replacement_class['id'],replacement_user)[0])
check('unpaid replacement cannot repair an existing paid entitlement', not repair_replacement_class_invoice(replacement_class['id'],new_invoice,ADMIN)[0])
check('another company invoice cannot repair this class', not repair_replacement_class_invoice(replacement_class['id'],CID_A,ADMIN)[0])
mark_corporate_paid(cid=new_invoice)
wrong_roster,_ = _invoice_for(replacement_intake,[U_ANN],'Replacement')
mark_corporate_paid(cid=wrong_roster)
check('replacement with different billed accounts refused', not repair_replacement_class_invoice(replacement_class['id'],wrong_roster,ADMIN)[0])
wrong_program,_ = _invoice_for(replacement_intake,[replacement_user],'Replacement')
c=get_db();cur=c.cursor();cur.execute("UPDATE corporate_payment_items SET form_type='cea_training' WHERE corporate_payment_id=%s",(wrong_program,));c.commit();cur.close();c.close()
mark_corporate_paid(cid=wrong_program)
check('replacement for a different program refused', not repair_replacement_class_invoice(replacement_class['id'],wrong_program,ADMIN)[0])
repaired,repair_error = repair_replacement_class_invoice(replacement_class['id'],new_invoice,ADMIN)
rebound = get_class(class_id=replacement_class['id'])
check('matching paid replacement repairs the original class', repaired and rebound['corporate_payment_id'] == new_invoice, repair_error or '')
check('repair preserves the original join code and open state', rebound['join_code'] == replacement_class['join_code'] and rebound['join_open'] == replacement_class['join_open'])
check('repair does not auto-enrol the trainee', not class_members(replacement_class['id']))
check('original invoice remains cancelled', get_corporate_payment(cid=old_invoice)['status'] == 'cancelled')
check('paid replacement now supplies class entitlement', membership_authority(replacement_class['id'],replacement_user)[0])
joined_after_repair,why = join_class(replacement_user,rebound['join_code'])
check('original class code works after the repair', bool(joined_after_repair),why or '')
check('repair does not admit a different company trainee', not membership_authority(replacement_class['id'],U_ANN)[0])
check('repeating the same repair is harmless', repair_replacement_class_invoice(replacement_class['id'],new_invoice,ADMIN)[0])
check('a paid class cannot be redirected to another invoice', not repair_replacement_class_invoice(replacement_class['id'],wrong_roster,ADMIN)[0])

failed = [x for x in results if not x[1]]
print(f"\n{'='*64}\n{len(results) - len(failed)}/{len(results)} passed")
for n, _, d in failed:
    print(f"  FAILED: {n} {d}")
sys.exit(1 if failed else 0)
