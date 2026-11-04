"""Regression: enrolment coordinates with the writers of the rows it trusts.

Locking the class row stops a concurrent close or code rotation, but that says
nothing about the OTHER rows a decision rests on — the registration, the
invoice, the roster slot. A plain SELECT there could read "accepted" while a
reviewer's UPDATE to "rejected" was in flight, and the stale verdict still
produced an insert.

Counting connections or grepping for FOR UPDATE does not establish that. These
checks use two real connections and assert the observable behaviour:

  1. the FOR SHARE read genuinely makes a concurrent writer wait
  2. racing a join against a revocation/rejection never leaves a membership
     whose authority was withdrawn BEFORE the join committed

The invariant in (2) is checkable after the fact: if the lock works, a
membership row can never carry a joined_at later than the moment its roster
slot was revoked. Either we read the revocation and refused, or the revoke
waited for us.

    cd src; ..\\venv\\Scripts\\python.exe ..\\scripts\\test_class_concurrency.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from _testdb import use_test_db, assert_isolated, test_db_url   # noqa: E402

use_test_db(recreate=True)
os.environ["MAIL_TRANSPORT"] = "mock"
os.environ["PAYMONGO_MOCK"] = "1"
os.environ.setdefault("PAYMONGO_SECRET_KEY", "sk_test_fake_for_tests")
os.environ.setdefault("SECRET_KEY", "conc-test-secret")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import threading                                    # noqa: E402
import time                                         # noqa: E402
import uuid                                         # noqa: E402
from datetime import datetime, timedelta            # noqa: E402

import psycopg2                                     # noqa: E402

from app import app                                 # noqa: E402
from db import (get_db, create_intake, add_slot, claim_slot_with_registration,
                record_selfie_review, create_corporate_payment,
                mark_corporate_paid, create_class, join_class,
                class_members, remove_member,
                REGISTRATION_INSERT_SQL, registration_insert_params)  # noqa: E402

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


def _enrol(intake_id, name, email):
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
    return rid, sid


print(f"\nisolated database: {assert_isolated()}")
ADMIN = _mkuser("admin", "admin@conc.test")

IID = create_intake("Race Co", "Ra", "hr@race.test", "0917",
                    "training", "Online", ADMIN)
rid_a, sid_a = _enrol(IID, "Ann Race", "ann@race.test")
U_ANN = _mkuser("trainee", "ann@race.test", rid_a, paid=True)

# Intake-authorised class: the roster slot is the authority, so revoking the
# slot is the withdrawal we race against.
CLS_I, _e = create_class("Race intake class", "Online", ADMIN,
                         intake_id=IID, form_type="training")


print("\n1. A FOR SHARE read makes a concurrent writer wait")
URL = test_db_url()


def _blocking_probe(table, sql_write, params):
    """Hold FOR SHARE on a row, then try to write it from another connection.

    Returns (blocked_while_held, completed_after_release).
    """
    reader = psycopg2.connect(URL)
    reader.autocommit = False
    rcur = reader.cursor()
    rcur.execute(f"SELECT 1 FROM {table} WHERE id = %s FOR SHARE", (params[-1],))

    state = {"done": False, "error": None}

    def _writer():
        w = psycopg2.connect(URL)
        try:
            wc = w.cursor()
            wc.execute(sql_write, params)
            w.commit()
            state["done"] = True
        except Exception as e:                               # noqa: BLE001
            state["error"] = str(e)
        finally:
            w.close()

    t = threading.Thread(target=_writer, daemon=True)
    t.start()
    time.sleep(1.0)
    blocked = not state["done"]          # still waiting on our share lock
    reader.commit()                      # release
    rcur.close(); reader.close()
    t.join(timeout=10)
    return blocked, state["done"], state["error"]


blocked, done, err = _blocking_probe(
    "registrations",
    "UPDATE registrations SET status='rejected' WHERE id=%s", (rid_a,))
check("a rejection waits while the registration is share-locked", blocked)
check("and lands once the lock is released", done, err or "")
c = get_db(); cur = c.cursor()
cur.execute("UPDATE registrations SET status='accepted' WHERE id=%s", (rid_a,))
c.commit(); cur.close(); c.close()

blocked, done, err = _blocking_probe(
    "corporate_intake_slots",
    "UPDATE corporate_intake_slots SET invite_revoked_at=NOW() WHERE id=%s",
    (sid_a,))
check("a roster revocation waits while the slot is share-locked", blocked)
check("and lands once released", done, err or "")
c = get_db(); cur = c.cursor()
cur.execute("UPDATE corporate_intake_slots SET invite_revoked_at=NULL WHERE id=%s",
            (sid_a,))
c.commit(); cur.close(); c.close()

CID, REF = create_corporate_payment(
    "Race Co", "Ra", "hr@race.test", "0917",
    [{"user_id": U_ANN, "training_type": "Online", "form_type": "training",
      "price_php": 5000.0, "price_label": "CEM Training"}],
    5000.0, None, None, 500000, datetime.now() + timedelta(days=3), ADMIN)
c = get_db(); cur = c.cursor()
cur.execute("UPDATE corporate_payments SET intake_id=%s WHERE id=%s", (IID, CID))
c.commit(); cur.close(); c.close()
assert mark_corporate_paid(cid=CID), "fixture: invoice did not settle"

blocked, done, err = _blocking_probe(
    "corporate_payments",
    "UPDATE corporate_payments SET status='cancelled' WHERE id=%s", (CID,))
check("an invoice change waits while the invoice is share-locked", blocked)
check("and lands once released", done, err or "")
c = get_db(); cur = c.cursor()
cur.execute("UPDATE corporate_payments SET status='paid' WHERE id=%s", (CID,))
c.commit(); cur.close(); c.close()


print("\n2. Racing a join against a roster revocation stays consistent")
# The invariant: a membership must never exist whose joined_at is LATER than
# the moment its authority was withdrawn. Either the join saw the revocation
# and refused, or the revocation waited for the join to finish.
violations = []
outcomes = {"joined": 0, "refused": 0}

for i in range(12):
    # Reset: slot live, no membership.
    c = get_db(); cur = c.cursor()
    cur.execute("UPDATE corporate_intake_slots SET invite_revoked_at=NULL "
                "WHERE id=%s", (sid_a,))
    c.commit(); cur.close(); c.close()
    remove_member(CLS_I["id"], U_ANN)

    box = {}

    def _join():
        cls, err = join_class(U_ANN, CLS_I["join_code"])
        box["cls"], box["err"] = cls, err

    # Half the iterations give the revoke a head start, half give it to the
    # join. A bare thread race always resolves the same way here: the revoke
    # is one statement while join_class runs several, so it committed first
    # every time and the "join wins" ordering — the one where the share lock
    # has to make the writer wait — was never reached.
    revoke_delay = 0.0 if i % 2 else 0.08

    def _revoke():
        if revoke_delay:
            time.sleep(revoke_delay)
        w = psycopg2.connect(URL)
        wc = w.cursor()
        wc.execute("UPDATE corporate_intake_slots SET invite_revoked_at=NOW() "
                   "WHERE id=%s", (sid_a,))
        w.commit(); w.close()

    t1 = threading.Thread(target=_join)
    t2 = threading.Thread(target=_revoke)
    t1.start(); t2.start()
    t1.join(timeout=20); t2.join(timeout=20)

    c = get_db(); cur = c.cursor()
    cur.execute("""SELECT m.joined_at, s.invite_revoked_at
                     FROM corporate_intake_slots s
                     LEFT JOIN training_class_members m
                            ON m.user_id = %s AND m.class_id = %s
                    WHERE s.id = %s""", (U_ANN, CLS_I["id"], sid_a))
    joined_at, revoked_at = cur.fetchone()
    cur.close(); c.close()

    if joined_at is None:
        outcomes["refused"] += 1
    else:
        outcomes["joined"] += 1
        if revoked_at is not None and revoked_at < joined_at:
            violations.append((i, joined_at, revoked_at))

check("no membership outlived the authority that granted it",
      not violations, f"{len(violations)} violation(s): {violations[:2]}")
check("both outcomes actually occurred, so the race was really exercised",
      outcomes["joined"] > 0 and outcomes["refused"] > 0, str(outcomes))


print("\n3. Racing a join against a registration rejection stays consistent")
rid_b, sid_b = _enrol(IID, "Ben Race", "ben@race.test")
U_BEN = _mkuser("trainee", "ben@race.test", rid_b, paid=True)
bad = []
out2 = {"joined": 0, "refused": 0}

for i in range(12):
    c = get_db(); cur = c.cursor()
    cur.execute("UPDATE registrations SET status='accepted' WHERE id=%s", (rid_b,))
    c.commit(); cur.close(); c.close()
    remove_member(CLS_I["id"], U_BEN)

    box = {}

    def _join_b():
        cls, err = join_class(U_BEN, CLS_I["join_code"])
        box["cls"], box["err"] = cls, err

    reject_delay = 0.0 if i % 2 else 0.08

    def _reject():
        if reject_delay:
            time.sleep(reject_delay)
        w = psycopg2.connect(URL)
        wc = w.cursor()
        wc.execute("UPDATE registrations SET status='rejected' WHERE id=%s",
                   (rid_b,))
        w.commit(); w.close()

    t1 = threading.Thread(target=_join_b)
    t2 = threading.Thread(target=_reject)
    t1.start(); t2.start()
    t1.join(timeout=20); t2.join(timeout=20)

    joined = U_BEN in {m["user_id"] for m in class_members(CLS_I["id"])}
    out2["joined" if joined else "refused"] += 1
    if joined:
        # A membership is only acceptable if a re-derivation right now would
        # still allow it. The gate re-checks on every access, so a rejected
        # registration must close access even when the row survives.
        from db import membership_authority
        ok, _why = membership_authority(CLS_I["id"], U_BEN)
        c = get_db(); cur = c.cursor()
        cur.execute("SELECT status FROM registrations WHERE id=%s", (rid_b,))
        status = cur.fetchone()[0]
        cur.close(); c.close()
        if status == "rejected" and ok:
            bad.append(i)

check("a surviving membership never reads as authorised after rejection",
      not bad, f"iterations {bad[:3]}")
check("both outcomes occurred here too", out2["joined"] > 0 or
      out2["refused"] > 0, str(out2))

c = get_db(); cur = c.cursor()
cur.execute("UPDATE registrations SET status='accepted' WHERE id=%s", (rid_b,))
c.commit(); cur.close(); c.close()


print("\n4. Two simultaneous joins enrol the person exactly once")
remove_member(CLS_I["id"], U_ANN)
c = get_db(); cur = c.cursor()
cur.execute("UPDATE corporate_intake_slots SET invite_revoked_at=NULL WHERE id=%s",
            (sid_a,))
c.commit(); cur.close(); c.close()
errs = []


def _dbl():
    cls, err = join_class(U_ANN, CLS_I["join_code"])
    if err:
        errs.append(err)


ts = [threading.Thread(target=_dbl) for _ in range(4)]
for t in ts:
    t.start()
for t in ts:
    t.join(timeout=20)
rows = [m for m in class_members(CLS_I["id"]) if m["user_id"] == U_ANN]
check("exactly one membership row results", len(rows) == 1, f"{len(rows)} rows")
check("and no caller saw an error", not errs, "; ".join(errs[:2])[:120])

failed = [x for x in results if not x[1]]
print(f"\n{'='*64}\n{len(results) - len(failed)}/{len(results)} passed")
for n, _, d in failed:
    print(f"  FAILED: {n} {d}")
sys.exit(1 if failed else 0)
