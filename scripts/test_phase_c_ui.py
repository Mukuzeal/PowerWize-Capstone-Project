"""Phase C browser-flow tests — admin console UI + company pages over HTTP.

Exercises the real routes with Flask's test client (no Selenium available in
this environment, so pixel rendering and JS execution are NOT verified — see
the report). Everything below is a genuine request/response through the app.

    cd src; ..\\venv\\Scripts\\python.exe ..\\scripts\\test_phase_c_ui.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from _testdb import use_test_db, assert_isolated   # noqa: E402

use_test_db(recreate=True)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import uuid                                        # noqa: E402
from datetime import datetime                      # noqa: E402

from app import app                                # noqa: E402
from db import (get_db, create_intake, add_slot, get_slots, get_intake,
                issue_coordinator_token, record_selfie_review,
                payment_link_eligibility)          # noqa: E402

app.config["WTF_CSRF_ENABLED"] = False
results = []


def check(name, passed, detail=""):
    results.append((name, passed, detail))
    print(f"  [{'PASS' if passed else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def _mkuser(role, email):
    """A real users row — `corporate_intakes.created_by` is a FK, so a session
    pointing at a non-existent id would fail the insert."""
    c = get_db(); cur = c.cursor()
    cur.execute("""INSERT INTO users (role, fname, lname, email, password_hash)
                   VALUES (%s,'Test','User',%s,'x')
                   ON CONFLICT (email) DO UPDATE SET role = EXCLUDED.role
                   RETURNING id""", (role, email))
    uid = cur.fetchone()[0]
    c.commit(); cur.close(); c.close()
    return uid


ADMIN_ID   = _mkuser("admin",    "admin@test.invalid")
TRAINEE_ID = _mkuser("trainee",  "trainee@test.invalid")
TRAINER_ID = _mkuser("employee", "trainer@test.invalid")


def staff(role="admin", uid=None):
    c = app.test_client()
    with c.session_transaction() as s:
        s["user_id"] = uid if uid is not None else ADMIN_ID
        s["user_role"] = role
    return c


print(f"\nisolated database: {assert_isolated()}")
anon = app.test_client()

print("\n1. Access boundaries on every intake route")
iid = create_intake("Acme Power", "Jo Cruz", "hr@acme.com", "0917", "training", "CEM", None)
ROUTES = [
    ("POST", "/admin/intake/new"),
    ("POST", f"/admin/intake/{iid}/slots"),
    ("GET",  f"/admin/intake/{iid}/panel"),
    ("POST", f"/admin/intake/{iid}/coordinator-link"),
    ("POST", f"/admin/intake/{iid}/coordinator-link/revoke"),
    ("POST", "/admin/intake/slot/1/revoke"),
]
anon_ok, trainee_ok = True, True
tr = staff("trainee", TRAINEE_ID)
for method, url in ROUTES:
    r = anon.open(url, method=method)
    if not (r.status_code in (301, 302) and "/auth" in r.headers.get("Location", "")):
        anon_ok = False
    r = tr.open(url, method=method)
    if r.status_code != 403:
        trainee_ok = False
check("anonymous is redirected to login on all 6 routes", anon_ok)
check("trainee gets 403 on all 6 routes (not a login bounce)", trainee_ok)

# Trainer has manage_modules but NOT review_registrations.
emp = staff("employee", TRAINER_ID)
r = emp.get(f"/admin/intake/{iid}/panel")
check("Trainer (employee) is refused the intake panel", r.status_code == 403,
      f"HTTP {r.status_code}")

print("\n2. Admin console renders the pane")
adm = staff()
r = adm.get("/admin")
body = r.get_data(as_text=True)
check("console loads", r.status_code == 200, f"HTTP {r.status_code}")
for frag, label in [("Company Intake", "nav item"),
                    ("section-intake", "pane"),
                    ("intake-new-overlay", "create modal"),
                    ("intake-overlay", "roster modal"),
                    ("function openIntake", "roster JS"),
                    ("function ikAddSlots", "add-roster JS"),
                    ("function ikCopy", "copy-link JS")]:
    check(f"console contains the {label}", frag in body)

print("\n3. Empty state")
r = adm.get(f"/admin/intake/{iid}/panel")
d = r.get_json()
check("empty roster reports zero slots", d["slots"] == [])
check("empty roster is not eligible", d["eligibility"]["eligible"] is False,
      d["eligibility"]["reason"])

print("\n4. Create intake through the route, with validation")
r = adm.post("/admin/intake/new", data={"company_name": "", "form_type": "nope",
                                        "contact_person": "", "contact_email": "bad"})
check("invalid create is refused with field errors", r.status_code == 400
      and len(r.get_json()["errors"]) >= 3, str(r.get_json()))
r = adm.post("/admin/intake/new", data={
    "company_name": "Beta Energy", "form_type": "training",
    "contact_person": "Mia Lim", "contact_email": "mia@beta.com"})
check("valid create succeeds", r.status_code == 200 and r.get_json().get("ok"))
bid = r.get_json()["id"]

print("\n5. Add roster through the route")
r = adm.post(f"/admin/intake/{bid}/slots", data={
    "roster": "Ana Reyes, ana@beta.com\nBen Santos <ben@beta.com>\nbroken line\nAna Dup, ANA@beta.com"})
d = r.get_json()
check("two valid lines accepted", d["added"] == 2, str(d["added"]))
check("malformed line reported, not silently dropped",
      any("broken line" in s for s in d["skipped"]), str(d["skipped"]))
check("duplicate email reported", any("already on this roster" in s for s in d["skipped"]))
check("invitation URLs returned once", len(d["invites"]) == 2
      and all("/company/invite/" in i["url"] for i in d["invites"]))

print("\n6. Coordinator link lifecycle through the routes")
r = adm.post(f"/admin/intake/{bid}/coordinator-link")
curl = r.get_json()["url"]
check("coordinator link generated", "/company/roster/" in curl)
ctok = curl.rsplit("/", 1)[-1]
r = anon.get(f"/company/roster/{ctok}")
check("company can open its roster anonymously", r.status_code == 200)
check("roster shows only this company's people",
      "Ana Reyes" in r.get_data(as_text=True)
      and "Acme Power" not in r.get_data(as_text=True))
adm.post(f"/admin/intake/{bid}/coordinator-link/revoke")
r = anon.get(f"/company/roster/{ctok}")
check("revoked link stops working", r.status_code == 404)

print("\n7. Invited registration through the real public form")
r = adm.post(f"/admin/intake/{bid}/slots", data={"roster": "Cy Lim, cy@beta.com"})
invite_url = r.get_json()["invites"][0]["url"]
itok = invite_url.rsplit("/", 1)[-1]

r = anon.get(f"/company/invite/{itok}")
check("invite redirects to the right program form",
      r.status_code == 302 and "/training?intake_invite=" in r.headers["Location"],
      r.headers.get("Location", ""))

# Submit the actual public form with the invite carried through.
form = {
    "intake_invite": itok, "title": "Mr", "full_name": "Cy Lim",
    "middle_name": "T", "residence": "Manila", "company_name": "Beta Energy",
    "designation": "Engineer", "company_address": "Makati",
    "contact_number": "0917", "email": "cy@beta.com", "birthdate": "1990-01-01",
    "age": "35", "agree": "yes", "training_type": "CEM Training", "batch_id": "",
}
r = anon.post("/training/submit", data=form)
# Uploads are required, so this submission is expected to fail validation —
# what matters is that the invite was NOT consumed by a failed attempt.
slot = next(s for s in get_slots(bid) if s["email"] == "cy@beta.com")
check("failed validation does NOT consume the invitation",
      slot["invite_used_at"] is None and slot["registration_id"] is None)

print("\n8. Registration without any invitation still works")
r = anon.get("/training")
check("public form loads with no invite", r.status_code == 200)
r = anon.get("/cea-training")
check("second program loads", r.status_code == 200)

print("\n9. Shared readiness drives both views")
# Attach a registration directly, then walk it through both review gates.
e_id = str(uuid.uuid4())[:8].upper()
c = get_db(); cur = c.cursor()
cur.execute("""INSERT INTO registrations (id, form_type, form_label, submitted_at,
               full_name, email, status, photo_id, resume, valid_id, selfie_with_id)
               VALUES (%s,'training','Training',NOW(),'Cy Lim','cy@beta.com','pending',
                       'a.png','b.pdf','c.png','s.png')""", (e_id,))
cur.execute("UPDATE corporate_intake_slots SET registration_id=%s, invite_used_at=NOW() "
            "WHERE id=%s", (e_id, slot["id"]))
c.commit(); cur.close(); c.close()

ctok2 = issue_coordinator_token(bid).rsplit("/", 1)[-1] if False else issue_coordinator_token(bid)
d = adm.get(f"/admin/intake/{bid}/panel").get_json()
row = next(s for s in d["slots"] if s["email"] == "cy@beta.com")
check("admin sees pending_review before any decision", row["status"] == "pending_review")

c = get_db(); cur = c.cursor()
cur.execute("UPDATE registrations SET status='accepted' WHERE id=%s", (e_id,))
c.commit(); cur.close(); c.close()
d = adm.get(f"/admin/intake/{bid}/panel").get_json()
row = next(s for s in d["slots"] if s["email"] == "cy@beta.com")
check("ACCEPTED + selfie pending is still not approved (admin view)",
      row["status"] == "pending_review", row["status"])
check("accepted application is labelled separately from identity review",
      row['status_label'] == 'Accepted — identity pending' and row['registration_status'] == 'accepted')
check("identity state reaches the roster instead of a blank dash",
      row['identity'] == 'pending' and row['identity_label'] == 'Pending')
b = anon.get(f"/company/roster/{ctok2}").get_data(as_text=True)
check("company view agrees it is not approved", "Approved" not in b or "Pending review" in b)

record_selfie_review(e_id, "approved", ADMIN_ID)
d = adm.get(f"/admin/intake/{bid}/panel").get_json()
row = next(s for s in d["slots"] if s["email"] == "cy@beta.com")
check("approved once BOTH gates pass (admin view)", row["status"] == "approved", row["status"])
check("completed identity approval remains visible", row['identity'] == 'approved' and row['status_label'] == 'Approved')
b = anon.get(f"/company/roster/{ctok2}").get_data(as_text=True)
check("company view now shows Approved", "Approved" in b)

print("\n10. Company page leaks nothing")
b = anon.get(f"/company/roster/{ctok2}").get_data(as_text=True)
for frag, label in [("/document/", "document route"),
                    ("/static/uploads", "legacy upload path"),
                    ("a.png", "a stored filename"),
                    ("s.png", "the selfie filename"),
                    (ctok2, "its own token echoed into the body")]:
    check(f"page does not expose {label}", frag not in b)
r = anon.get(f"/company/roster/{ctok2}")
check("no-store cache header", "no-store" in (r.headers.get("Cache-Control") or ""))

failed = [x for x in results if not x[1]]
print(f"\n{'='*64}\n{len(results) - len(failed)}/{len(results)} passed")
for n, _, dd in failed:
    print(f"  FAILED: {n} {dd}")
sys.exit(1 if failed else 0)
