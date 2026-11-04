"""Phase 2 tests — company notifications, invitation delivery, atomic redemption.

Isolated database, mock mail transport. No real email is sent.

    cd src; ..\\venv\\Scripts\\python.exe ..\\scripts\\test_notifications.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from _testdb import use_test_db, assert_isolated   # noqa: E402

use_test_db(recreate=True)
# Must also precede the app import: email_utils reads MAIL_TRANSPORT at import.
os.environ["MAIL_TRANSPORT"] = "mock"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import threading                                   # noqa: E402
import uuid                                        # noqa: E402
from datetime import datetime, timedelta           # noqa: E402

import email_utils                                 # noqa: E402
from app import app                                # noqa: E402
from db import (get_db, dict_cur, create_intake, add_slot, get_slots,
                claim_slot_with_registration, record_selfie_review,
                get_notifications, get_notification, begin_attempt,
                finish_attempt, recover_stale_attempts, force_retry_uncertain,
                set_correction_and_queue_notice, rotate_account_invitation,
                claim_account_invitation, account_exists_for_email,
                invitation_status, redeem_invitation_and_create_account,
                payment_link_eligibility,
                REGISTRATION_INSERT_SQL, registration_insert_params)  # noqa: E402

app.config["WTF_CSRF_ENABLED"] = False
results = []


def check(name, passed, detail=""):
    results.append((name, passed, detail))
    print(f"  [{'PASS' if passed else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def _mkuser(role, email):
    c = get_db(); cur = c.cursor()
    cur.execute("""INSERT INTO users (role, fname, lname, email, password_hash)
                   VALUES (%s,'T','U',%s,'x') ON CONFLICT (email) DO UPDATE
                   SET role=EXCLUDED.role RETURNING id""", (role, email))
    uid = cur.fetchone()[0]; c.commit(); cur.close(); c.close()
    return uid


ADMIN = _mkuser("admin", "a@test.invalid")


def admin_client():
    c = app.test_client()
    with c.session_transaction() as s:
        s["user_id"], s["user_role"] = ADMIN, "admin"
    return c


def _submit(intake_id, name, email):
    """Put a real registration behind a roster slot."""
    sid, tok = add_slot(intake_id, name, email)
    e = {"id": str(uuid.uuid4())[:8].upper(), "form_type": "training",
         "form_label": "Training", "submitted_at": datetime.now(),
         "full_name": name, "email": email, "photo_id": "p.png",
         "resume": "r.pdf", "valid_id": "v.png", "selfie_with_id": "s.png"}
    rid, err = claim_slot_with_registration(tok, e["id"], REGISTRATION_INSERT_SQL,
                                            registration_insert_params(e))
    assert rid, err
    return sid, rid


print(f"\nisolated database: {assert_isolated()}")
print(f"mail transport: {email_utils.MAIL_TRANSPORT}")
check("tests use the mock transport (no real email)",
      email_utils.MAIL_TRANSPORT == "mock", email_utils.MAIL_TRANSPORT)

iid = create_intake("Acme Power", "Jo Cruz", "hr@acme.com", None, "training", "CEM", ADMIN)
sid1, rid1 = _submit(iid, "Ana Reyes", "ana@acme.com")

print("\n1. Correction + notification intent commit together")
email_utils.SENT_MESSAGES.clear()
res, err = set_correction_and_queue_notice(rid1, "Your valid ID photo is blurred.", ADMIN)
check("correction recorded and intent queued", err is None and res["notification_id"], str(err))
notifs = get_notifications(iid)
check("exactly one notification queued", len(notifs) == 1, str(len(notifs)))
check("queued before any send attempt", notifs[0]["status"] == "queued"
      and notifs[0]["attempts"] == 0, f"{notifs[0]['status']}/{notifs[0]['attempts']}")
check("nothing sent yet", len(email_utils.SENT_MESSAGES) == 0)
nid = notifs[0]["id"]

print("\n2. Duplicate correction event does not re-queue")
res2, _ = set_correction_and_queue_notice(rid1, "Your valid ID photo is blurred.", ADMIN)
check("second request creates a NEW event (version bumped)",
      res2["notification_id"] is not None and res2["notification_id"] != nid,
      "a re-ask is a new correction event")
# Same version twice cannot happen via the helper, so assert the dedupe key directly.
c = get_db(); cur = c.cursor()
cur.execute("SELECT correction_version FROM registrations WHERE id=%s", (rid1,))
ver = cur.fetchone()[0]
cur.execute("""INSERT INTO corporate_notifications
               (intake_id, kind, to_email, subject, status, dedupe_key)
               VALUES (%s,'needs_correction','hr@acme.com','dup','queued',%s)
               ON CONFLICT (dedupe_key) DO NOTHING RETURNING id""",
            (iid, f"correction:{rid1}:v{ver}"))
dup = cur.fetchone()
c.commit(); cur.close(); c.close()
check("same dedupe_key is rejected by the database", dup is None)

print("\n3. Delivery: attempt recorded before send, honest terminal state")
adm = admin_client()
r = adm.post(f"/admin/notification/{nid}/retry")
d = r.get_json()
check("retry succeeds through the route", r.status_code == 200 and d["ok"], str(d))
check("wording never claims delivery", "delivered" not in d["message"].lower(), d["message"])
check("wording names the mock transport", "mock" in d["message"].lower(), d["message"])
n = get_notification(nid)
check("mock outcome recorded DISTINCTLY from a real send",
      n["status"] == "mocked" and n["transport"] == "mock",
      f"{n['status']}/{n['transport']}")
check("attempt counted and lease released",
      n["attempts"] == 1 and n["attempt_expires_at"] is None,
      f"{n['attempts']}/{n['attempt_expires_at']}")
check("mock transport captured one message", len(email_utils.SENT_MESSAGES) == 1)

print("\n4. Company-safe content only")
msg = email_utils.SENT_MESSAGES[0]
check("addressed to the company contact", msg["to"] == "hr@acme.com")
check("includes the trainee name", "Ana Reyes" in msg["html"])
check("includes the actionable correction", "valid ID photo is blurred" in msg["html"])
for frag, label in [("s.png", "selfie filename"), ("v.png", "ID filename"),
                    ("/document/", "document route"), ("/static/uploads", "upload path")]:
    check(f"excludes the {label}", frag not in msg["html"])

print("\n5. Failed send -> retryable, not marked sent")
res3, _ = set_correction_and_queue_notice(rid1, "Resubmit your resume.", ADMIN)
nid3 = res3["notification_id"]
real = email_utils.send_company_correction_notice


def _boom(*a, **k):
    raise email_utils.MailDeliveryError("SMTPAuthenticationError: simulated")


email_utils.send_company_correction_notice = _boom
import admin.registrations as areg                  # noqa: E402
areg.send_company_correction_notice = _boom         # the module-local binding
r = adm.post(f"/admin/notification/{nid3}/retry")
email_utils.send_company_correction_notice = real
n3 = get_notification(nid3)
check("failed send returns an error status", r.status_code == 502, f"HTTP {r.status_code}")
check("NOT marked submitted after failure", n3["status"] == "failed", n3["status"])
check("error text persisted", "simulated" in (n3["last_error"] or ""), str(n3["last_error"]))
check("sent_at left NULL", n3["sent_at"] is None)
check("attempt was counted", n3["attempts"] == 1, str(n3["attempts"]))

print("\n6. Retry after failure succeeds")
r = adm.post(f"/admin/notification/{nid3}/retry")
n3 = get_notification(nid3)
check("retry reaches a terminal success state",
      r.status_code == 200 and n3["status"] == "mocked", n3["status"])
check("attempts incremented to 2", n3["attempts"] == 2, str(n3["attempts"]))

print("\n7. Attempt ownership and explicit stale recovery")
res4, _ = set_correction_and_queue_notice(rid1, "Third thing.", ADMIN)
nid4 = res4["notification_id"]

a1, n_att, why = begin_attempt(nid4, lease_seconds=60)
check("first attempt claims the send", a1 is not None and why is None, str(why))
a2, _, why2 = begin_attempt(nid4, lease_seconds=60)
check("a second request CANNOT claim an in-flight send", a2 is None)
check("refusal explains why", "in flight" in (why2 or "").lower(), str(why2))

check("a non-owning attempt cannot record an outcome",
      finish_attempt(nid4, "not-the-owner", transport="mock") is None)
check("state untouched by the impostor",
      get_notification(nid4)["status"] == "in_flight")
check("the owner CAN record its outcome",
      finish_attempt(nid4, a1, transport="mock") == "mocked")

# Simulate the process dying mid-send: claim, then lapse the lease.
res5, _ = set_correction_and_queue_notice(rid1, "Fourth thing.", ADMIN)
nid5 = res5["notification_id"]
a3, _, _ = begin_attempt(nid5, lease_seconds=60)
c = get_db(); cur = c.cursor()
cur.execute("UPDATE corporate_notifications SET attempt_expires_at = NOW() - "
            "interval '1 minute' WHERE id=%s", (nid5,))
c.commit(); cur.close(); c.close()

check("a stale lease is NOT auto-resent",
      get_notification(nid5)["status"] == "in_flight")
recovered = recover_stale_attempts()
check("recovery marks it uncertain, explicitly",
      nid5 in recovered and get_notification(nid5)["status"] == "uncertain")
from db import unresolved_notifications       # noqa: E402
check("appears in the unresolved list",
      any(x["id"] == nid5 for x in unresolved_notifications()))
a4, _, why4 = begin_attempt(nid5)
check("uncertain is NOT blindly retryable", a4 is None, str(why4))
check("operator can force a retry deliberately",
      force_retry_uncertain(nid5) is True)
a5, _, _ = begin_attempt(nid5)
check("forced row becomes claimable again", a5 is not None)
finish_attempt(nid5, a5, transport="mock")

print("\n8. Invitation delivery is a ROTATION, not a resend")
c = get_db(); cur = c.cursor()
cur.execute("UPDATE registrations SET status='accepted' WHERE id=%s", (rid1,))
c.commit(); cur.close(); c.close()
record_selfie_review(rid1, "approved", ADMIN)

tok_a, created = claim_account_invitation(rid1, "ana@acme.com", True)
check("first invitation minted", created and tok_a)
tok_b, created_b = claim_account_invitation(rid1, "ana@acme.com", True)
check("second claim creates NO duplicate", created_b is False and tok_b is None)
check("invitation shows as active", invitation_status(rid1)["state"] == "active")

tok_c, rotated = rotate_account_invitation(rid1, "ana@acme.com", True)
check("rotation issues a NEW token", rotated and tok_c and tok_c != tok_a)
c = get_db(); cur = c.cursor()
cur.execute("SELECT COUNT(*) FROM account_tokens WHERE reg_id=%s AND used_at IS NULL", (rid1,))
check("old unused token was retired (exactly one live)", cur.fetchone()[0] == 1)
cur.close(); c.close()

print("\n9. Atomic redemption + authoritative account link")
uid, err = redeem_invitation_and_create_account(
    tok_c, "hash", "Ana", "Reyes", "0917", "Acme Power", "CEM Training")
check("account created from the live token", uid and err is None, str(err))
c = get_db(); cur = dict_cur(c)
cur.execute("SELECT registration_id FROM users WHERE id=%s", (uid,))
check("users.registration_id links back to the application",
      cur.fetchone()["registration_id"] == rid1)
cur.close(); c.close()
uid2, err2 = redeem_invitation_and_create_account(
    tok_c, "hash", "Ana", "Reyes", "0917", "Acme", "CEM Training")
check("replaying a spent token is refused", uid2 is None and err2, str(err2))
c = get_db(); cur = c.cursor()
cur.execute("SELECT COUNT(*) FROM users WHERE registration_id=%s", (rid1,))
check("no duplicate account from the replay", cur.fetchone()[0] == 1)
cur.close(); c.close()
check("account_exists_for_email now true (case-insensitive)",
      account_exists_for_email("ANA@acme.com"))
check("no further invitation needed", rotate_account_invitation(rid1, "ana@acme.com", True)[1] is False)

print("\n10. Concurrent redemption of one token")
sid5, rid5 = _submit(iid, "Cy Lim", "cy@acme.com")
c = get_db(); cur = c.cursor()
cur.execute("UPDATE registrations SET status='accepted' WHERE id=%s", (rid5,))
c.commit(); cur.close(); c.close()
record_selfie_review(rid5, "approved", ADMIN)
tok5, _ = claim_account_invitation(rid5, "cy@acme.com", True)
out, lk = [], threading.Lock()


def _race():
    try:
        u, e = redeem_invitation_and_create_account(
            tok5, "h", "Cy", "Lim", "", "Acme", "CEM Training")
    except Exception as exc:
        u, e = None, type(exc).__name__
    with lk:
        out.append((u, e))


ts = [threading.Thread(target=_race) for _ in range(5)]
[t.start() for t in ts]; [t.join() for t in ts]
check("exactly one of 5 concurrent redemptions won",
      len([o for o in out if o[0]]) == 1, str([o[1] for o in out if not o[0]]))
c = get_db(); cur = c.cursor()
cur.execute("SELECT COUNT(*) FROM users WHERE registration_id=%s", (rid5,))
check("exactly one account exists", cur.fetchone()[0] == 1)
cur.close(); c.close()

print("\n11. Roster change invalidates a stale eligibility check")
ok_before, _, _ = payment_link_eligibility(iid)
add_slot(iid, "Late Joiner", "late@acme.com")
ok_after, reason, _ = payment_link_eligibility(iid)
check("adding an unsubmitted trainee makes the intake ineligible again",
      ok_after is False, reason)

failed = [x for x in results if not x[1]]
print(f"\n{'='*64}\n{len(results) - len(failed)}/{len(results)} passed")
for n_, _, d in failed:
    print(f"  FAILED: {n_} {d}")
sys.exit(1 if failed else 0)
