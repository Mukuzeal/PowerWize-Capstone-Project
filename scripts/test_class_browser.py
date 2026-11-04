"""Browser test: class join codes, driven by Chromium with CSRF ON.

Covers the two sides that only exist in the browser:

  * the admin intake panel — create a class, read the code, see members and
    batch progress, see WHO has not joined and why, rotate, close
  * the trainee portal — type a code and join; and the refusal paths, which
    must say what is actually wrong rather than "invalid code"

    cd src; ..\\venv\\Scripts\\python.exe ..\\scripts\\test_class_browser.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from _testdb import use_test_db, assert_isolated   # noqa: E402

use_test_db(recreate=True)
os.environ["MAIL_TRANSPORT"] = "mock"
os.environ["PAYMONGO_MOCK"] = "1"
os.environ.setdefault("PAYMONGO_SECRET_KEY", "sk_test_fake_for_tests")
os.environ.setdefault("SECRET_KEY", "class-browser-secret")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import socket                                      # noqa: E402
import re                                          # noqa: E402
import threading                                   # noqa: E402
import uuid                                        # noqa: E402
from datetime import datetime, timedelta           # noqa: E402

from werkzeug.serving import make_server           # noqa: E402
from playwright.sync_api import sync_playwright    # noqa: E402

from app import app                                # noqa: E402
import email_utils                                 # noqa: E402
from db import (get_db, create_intake, add_slot, claim_slot_with_registration,
                record_selfie_review, create_corporate_payment,
                mark_corporate_paid, class_members, get_class,
                REGISTRATION_INSERT_SQL, registration_insert_params)  # noqa: E402

app.config["WTF_CSRF_ENABLED"] = True
results = []


def check(name, passed, detail=""):
    results.append((name, passed, detail))
    print(f"  [{'PASS' if passed else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))


def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]; s.close(); return port


def _mkuser(role, email, reg_id=None, paid=False):
    c = get_db(); cur = c.cursor()
    cur.execute("""INSERT INTO users (role, fname, lname, email, password_hash,
                   payment_status, registration_id)
                   VALUES (%s,%s,'User',%s,'x',%s,%s)
                   ON CONFLICT (email) DO UPDATE SET
                     registration_id = EXCLUDED.registration_id,
                     payment_status  = EXCLUDED.payment_status
                   RETURNING id""",
                (role, email.split("@")[0].title(), email,
                 "paid" if paid else "unpaid", reg_id))
    uid = cur.fetchone()[0]; c.commit(); cur.close(); c.close()
    return uid


def _enrol(intake_id, name, email, accept=True):
    sid, tok = add_slot(intake_id, name, email)
    e = {"id": str(uuid.uuid4())[:8].upper(), "form_type": "training",
         "form_label": "Training", "submitted_at": datetime.now(),
         "full_name": name, "email": email, "training_type": "Online",
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
    return rid


print(f"\nisolated database: {assert_isolated()}")
ADMIN = _mkuser("admin", "admin@clsb.test")

IID = create_intake("Cohort Co", "Coe", "hr@cohort.test", "0917",
                    "training", "Online", ADMIN)
rid_ann = _enrol(IID, "Ann Cruz", "ann@cohort.test")
rid_ben = _enrol(IID, "Ben Diaz", "ben@cohort.test")
U_ANN = _mkuser("trainee", "ann@cohort.test", rid_ann)
U_BEN = _mkuser("trainee", "ben@cohort.test", rid_ben)
CID, REF = create_corporate_payment(
    "Cohort Co", "Coe", "hr@cohort.test", "0917",
    [{"user_id": u, "training_type": "Online", "form_type": "training",
      "price_php": 5000.0, "price_label": "CEM Training"} for u in (U_ANN, U_BEN)],
    10000.0, None, None, 1000000, datetime.now() + timedelta(days=3), ADMIN)
c = get_db(); cur = c.cursor()
cur.execute("UPDATE corporate_payments SET intake_id=%s WHERE id=%s", (IID, CID))
c.commit(); cur.close(); c.close()
assert mark_corporate_paid(cid=CID), "fixture: invoice did not settle"

# Someone on the roster who has NOT paid, so the panel must explain them.
rid_cal = _enrol(IID, "Cal Uy", "cal@cohort.test")
U_CAL = _mkuser("trainee", "cal@cohort.test", rid_cal)

port = _free_port()
srv = make_server("127.0.0.1", port, app, threaded=True)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{port}"
print(f"serving on {BASE}")

page_errors, console_errors = [], []


def _cookie(uid, role, name):
    with app.test_request_context():
        from flask.sessions import SecureCookieSessionInterface
        si = SecureCookieSessionInterface()
        return si.get_signing_serializer(app).dumps(
            {"user_id": uid, "user_role": role, "user_name": name})


COOKIE_NAME = app.config.get("SESSION_COOKIE_NAME", "session")

def local_context(browser):
    """Real app traffic; unrelated CDN widgets use local test doubles."""
    context = browser.new_context(base_url=BASE)
    context.add_init_script("""window.Swal={
        fire:()=>Promise.resolve({isConfirmed:false}),mixin:function(){return this;},
        stopTimer:()=>{},resumeTimer:()=>{}};
        window.flatpickr=()=>({selectedDates:[]});
        window.Chart=function(el,o){this.data=o.data;this.update=()=>{};};
        window.Chart.defaults={};""")
    context.route(re.compile(r"^https?://"), lambda route:
                  route.continue_() if route.request.url.startswith(BASE + '/') else
                  route.fulfill(status=200, body='', content_type=(
                      'text/css' if route.request.resource_type == 'stylesheet' else 'application/javascript')))
    return context

try:
    with sync_playwright() as pw:
        browser = pw.chromium.launch()

        # ── Admin: create and manage the class ──────────────────────────────
        ctx = local_context(browser)
        ctx.add_cookies([{"name": COOKIE_NAME,
                          "value": _cookie(ADMIN, "admin", "Admin"),
                          "url": BASE}])
        page = ctx.new_page()
        page.on("pageerror", lambda e: page_errors.append(str(e)))
        page.on("console", lambda m: console_errors.append(m.text)
                if m.type == "error" else None)
        page.on("dialog", lambda d: d.accept())

        print("\n1. Generating a registration link automatically prepares its class code")
        page.goto("/admin", wait_until="networkidle")
        page.evaluate("showSection('intake', document.querySelector('.nav-item'))")
        page.evaluate(f"openIntake({IID})")
        page.wait_for_selector("#ik-classes", timeout=8000)
        page.wait_for_selector("#ik-classes .corp-note", timeout=8000)
        check("the classes section loads",
              "class" in page.locator("#ik-classes").inner_text().lower())
        check("manual class creation is no longer needed",
              page.get_by_role("button", name="Create a class").count() == 0)
        page.get_by_role("button", name="Generate shared registration link", exact=True).click()
        page.wait_for_selector('#ik-upload-link-out input', timeout=8000)
        REGISTRATION_URL = page.locator('#ik-upload-link-out input').input_value()
        page.wait_for_selector("#ik-classes code", timeout=8000)
        CODE = page.locator("#ik-classes code").first.inner_text().strip()
        check("a readable join code is shown", 5 <= len(CODE) <= 12, CODE)
        check("it avoids easily-misread characters",
              not set(CODE) & set("01OIL"), CODE)
        panel = page.locator("#ik-classes").inner_text()
        check("the class is open to joins", "Open to joins" in panel)
        check("the program is shown", "Online" in panel)
        check("the registration link displays its class code immediately",
              CODE in page.locator('#ik-upload-link-out').inner_text())
        before_mail = len(email_utils.SENT_MESSAGES)
        page.get_by_role('button', name='Send registration link to company', exact=True).click()
        page.wait_for_function("() => document.querySelector('#ik-registration-send-out')?.textContent.includes('Mocked only')")
        check("the email button reports mock delivery honestly",
              'NOT emailed' in page.locator('#ik-registration-send-out').inner_text())
        check("the company contact receives the link and class code in the mock message",
              len(email_utils.SENT_MESSAGES) == before_mail + 1
              and email_utils.SENT_MESSAGES[-1]['to'] == 'hr@cohort.test'
              and REGISTRATION_URL in email_utils.SENT_MESSAGES[-1]['html']
              and CODE in email_utils.SENT_MESSAGES[-1]['html'])
        page.get_by_role('button', name='Send registration link to company', exact=True).click()
        page.wait_for_function("() => document.querySelector('#ik-registration-send-out')?.textContent.includes('already have a delivery record')")
        check("duplicate send is refused visibly", len(email_utils.SENT_MESSAGES) == before_mail + 1)
        page.reload(wait_until='networkidle')
        page.evaluate("showSection('intake', document.querySelector('.nav-item'))")
        page.evaluate(f"openIntake({IID})")
        notice_row = page.locator('#intake-body tr').filter(has_text='Registration link and class code')
        notice_row.wait_for()
        check("email history survives refresh", 'Mocked only - NOT emailed' in notice_row.inner_text())
        notice_row.get_by_role('button', name='Retry', exact=True).click()
        page.wait_for_function("() => document.querySelector('#ik-registration-send-out')?.textContent.includes('Mocked only')")
        check("retry after refresh uses the stored link", len(email_utils.SENT_MESSAGES) == before_mail + 2
              and REGISTRATION_URL in email_utils.SENT_MESSAGES[-1]['html'])
        add_slot(IID, 'New Applicant', 'new@cohort.test')
        entry_ctx = local_context(browser)
        entry_page = entry_ctx.new_page()
        entry_page.goto(REGISTRATION_URL, wait_until='networkidle')
        check("registration asks for the class code instead of an email OTP",
              entry_page.locator('#entry-class-code').count() == 1
              and entry_page.get_by_role('button', name='Send verification code').count() == 0)
        entry_page.fill('#entry-class-code', CODE.lower())
        entry_page.fill('#entry-email', 'new@cohort.test')
        entry_page.get_by_role('button', name='Continue to registration', exact=True).click()
        entry_page.wait_for_load_state('networkidle')
        check("the class code opens the company upload form at the same URL",
              entry_page.url == REGISTRATION_URL
              and 'Submit your' in entry_page.locator('body').inner_text()
              and entry_page.locator('input[name="email"]').input_value() == 'new@cohort.test')
        entry_ctx.close()

        print("\n2. The class panel names who has not joined, and why")
        page.get_by_role("button", name="Members & progress").first.click()
        page.wait_for_selector("text=Batch progress", timeout=8000)
        det = page.locator("#ik-classes").inner_text()
        check("it says nobody has joined yet", "Nobody has joined yet" in det,
              det[-80:].replace("\n", " "))
        check("eligible-but-absent people are listed", "Ann" in det and "Ben" in det)
        # Cal is on the intake roster but was never on the invoice. The
        # invoice decides membership, so he cannot join — but he must still be
        # VISIBLE with that reason, not silently absent from the trainer's
        # list of who is missing.
        check("the un-billed roster member is explained, not just omitted",
              "Cal" in det and "invoice" in det.lower(),
              det[-160:].replace("\n", " "))
        check("batch progress is shown from the start", "Batch progress" in det)

        print("\n3. A trainee joins with the code")
        tctx = local_context(browser)
        tctx.add_cookies([{"name": COOKIE_NAME,
                           "value": _cookie(U_ANN, "trainee", "Ann Cruz"),
                           "url": BASE}])
        tpage = tctx.new_page()
        tpage.on("pageerror", lambda e: page_errors.append(str(e)))
        tpage.goto("/portal", wait_until="networkidle")
        check("the portal offers a class code field",
              tpage.locator("#join_code").count() == 1)
        check("and explains the code is not an entitlement",
              "paid you into" in tpage.locator("#join-code-help").inner_text(),
              tpage.locator("#join-code-help").inner_text()[:70])

        # Typed the way a person would: lowercase, with a stray space.
        tpage.fill("#join_code", f" {CODE.lower()} ")
        tpage.get_by_role("button", name="Join class").click()
        tpage.wait_for_load_state("networkidle")
        check("the join succeeds despite case and spacing",
              U_ANN in {m["user_id"] for m in class_members(
                  get_class(join_code=CODE)["id"])})
        body = tpage.locator("body").inner_text()
        check("the portal confirms the class", "Cohort Co" in body or "joined" in body.lower(),
              body[:0] or "")
        check("and now lists it as mine",
              "My class" in body and "Online" in body)

        print("\n4. A wrong code and an ineligible account fail DIFFERENTLY")
        tpage.fill("#join_code", "ZZZZZZZ")
        tpage.get_by_role("button", name="Join class").click()
        tpage.wait_for_load_state("networkidle")
        wrong = tpage.locator("body").inner_text()
        check("a wrong code says the code is wrong",
              "No class has that code" in wrong,
              [ln for ln in wrong.split("\n") if "code" in ln.lower()][:1])

        cctx = local_context(browser)
        cctx.add_cookies([{"name": COOKIE_NAME,
                           "value": _cookie(U_CAL, "trainee", "Cal Uy"),
                           "url": BASE}])
        cpage = cctx.new_page()
        cpage.on("pageerror", lambda e: page_errors.append(str(e)))
        # An unpaid trainee is bounced to /payment before the portal, which is
        # itself the right answer — the code is not the way past that.
        cpage.goto("/portal", wait_until="networkidle")
        check("an unpaid trainee never reaches the join form",
              cpage.locator("#join_code").count() == 0,
              f"landed on {cpage.url.split(str(port))[-1]}")
        # And the route refuses him directly, not only by redirect.
        status = cpage.evaluate("""async (code) => {
            const r = await fetch('/portal/join-class', {
                method: 'POST',
                headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                body: 'join_code=' + encodeURIComponent(code)
            });
            return r.status;
        }""", CODE)
        check("a direct POST without a CSRF token is refused",
              status in (400, 403), f"HTTP {status}")
        check("and he is still not a member",
              U_CAL not in {m["user_id"] for m in class_members(
                  get_class(join_code=CODE)["id"])})

        print("\n5. Admin sees the new member and real progress")
        page.reload(wait_until="networkidle")
        page.evaluate("showSection('intake', document.querySelector('.nav-item'))")
        page.evaluate(f"openIntake({IID})")
        page.wait_for_selector("#ik-classes code", timeout=8000)
        page.get_by_role("button", name="Members & progress").first.click()
        page.wait_for_selector("[id^='ik-cls-'] table", timeout=8000)
        det = page.locator("#ik-classes").inner_text()
        check("the member is listed", "Ann" in det)
        check("their join route is shown as a self-join", "Self-joined" in det,
              det[-120:].replace("\n", " "))
        check("Ann is no longer in the not-joined list",
              det.count("Ann") == 1, f"appears {det.count('Ann')} times")

        print("\n6. Rotating and closing behave as described")
        page.get_by_role("button", name="New code").first.click()
        page.wait_for_timeout(2000)
        rotated = page.locator("#ik-classes code").first.inner_text().strip()
        check("a different code is issued", rotated != CODE, f"{CODE} -> {rotated}")
        check("the message says members keep their place",
              "keep their place" in page.locator("#ik-classes").inner_text(),
              page.locator("#ik-classes").inner_text()[-90:].replace("\n", " "))
        check("and they really do",
              U_ANN in {m["user_id"] for m in class_members(
                  get_class(join_code=rotated)["id"])})

        page.get_by_role("button", name="Close joining").first.click()
        page.wait_for_timeout(2000)
        check("the class reads as closed",
              "Closed" in page.locator("#ik-classes").inner_text())

        # The old code must be dead for a fresh trainee.
        bctx = local_context(browser)
        bctx.add_cookies([{"name": COOKIE_NAME,
                           "value": _cookie(U_BEN, "trainee", "Ben Diaz"),
                           "url": BASE}])
        bpage = bctx.new_page()
        bpage.on("pageerror", lambda e: page_errors.append(str(e)))
        bpage.goto("/portal", wait_until="networkidle")
        bpage.fill("#join_code", CODE)
        bpage.get_by_role("button", name="Join class").click()
        bpage.wait_for_load_state("networkidle")
        check("the rotated-away code no longer works",
              "No class has that code" in bpage.locator("body").inner_text())
        bpage.fill("#join_code", rotated)
        bpage.get_by_role("button", name="Join class").click()
        bpage.wait_for_load_state("networkidle")
        check("and the current code is refused while joining is closed",
              "no longer accepting" in bpage.locator("body").inner_text(),
              [ln for ln in bpage.locator("body").inner_text().split("\n")
               if "accepting" in ln][:1])
        check("Ben did not get in", U_BEN not in {m["user_id"] for m in
              class_members(get_class(join_code=rotated)["id"])})

        print("\n7. No JavaScript errors throughout")
        check("no uncaught JS exceptions", not page_errors,
              "; ".join(page_errors[:2])[:160])
        unexpected = [e for e in console_errors
                      if "favicon" not in e.lower()
                      and "400 (BAD REQUEST)" not in e
                      and "409 (CONFLICT)" not in e
                      and "403 (FORBIDDEN)" not in e]
        check("no unexpected console errors", not unexpected,
              "; ".join(unexpected[:2])[:160])

        browser.close()
finally:
    srv.shutdown()

failed = [x for x in results if not x[1]]
print(f"\n{'='*64}\n{len(results) - len(failed)}/{len(results)} passed")
for n, _, d in failed:
    print(f"  FAILED: {n} {d}")
sys.exit(1 if failed else 0)
