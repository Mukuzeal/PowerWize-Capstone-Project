"""Browser test — the REAL admin JavaScript, driven by Chromium.

Runs the Flask app on a throwaway port against the isolated test database and
drives the console the way a person would: clicking, typing, waiting for fetch
calls to resolve. Failure paths are exercised too, because "the happy path
renders" is not evidence that the error states work.

No network beyond localhost: the gateway is mocked and mail is mocked.

    cd src; ..\\venv\\Scripts\\python.exe ..\\scripts\\test_admin_browser.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from _testdb import use_test_db, assert_isolated   # noqa: E402

use_test_db(recreate=True)
os.environ["MAIL_TRANSPORT"] = "mock"
os.environ["PAYMONGO_MOCK"] = "1"
os.environ.setdefault("PAYMONGO_SECRET_KEY", "sk_test_fake_for_tests")
os.environ.setdefault("SECRET_KEY", "browser-test-secret")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import socket                                      # noqa: E402
import re                                          # noqa: E402
import json                                        # noqa: E402
import threading                                   # noqa: E402
import uuid                                        # noqa: E402
from datetime import datetime, timedelta           # noqa: E402

from werkzeug.serving import make_server           # noqa: E402
from playwright.sync_api import sync_playwright    # noqa: E402

from app import app                                # noqa: E402
from db import (get_db, create_intake, add_slot, claim_slot_with_registration,
                record_selfie_review, get_corporate_payment, get_attempts,
                create_corporate_payment, mark_corporate_paid,
                reserve_attempt, record_session, record_unresolved_event,
                REGISTRATION_INSERT_SQL, registration_insert_params)  # noqa: E402

# CSRF stays ON. Disabling it meant every POST in this test bypassed the
# check that the real console depends on — _ikCsrf() reading the meta tag and
# the X-CSRFToken header surviving each fetch were never actually exercised.
app.config["WTF_CSRF_ENABLED"] = True
results = []


def check(name, passed, detail=""):
    results.append((name, passed, detail))
    print(f"  [{'PASS' if passed else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _mkuser(role, email, reg_id=None):
    c = get_db(); cur = c.cursor()
    cur.execute("""INSERT INTO users (role, fname, lname, email, password_hash,
                   payment_status, registration_id)
                   VALUES (%s,'T','U',%s,'x','unpaid',%s)
                   ON CONFLICT (email) DO UPDATE SET registration_id =
                   EXCLUDED.registration_id RETURNING id""", (role, email, reg_id))
    uid = cur.fetchone()[0]; c.commit(); cur.close(); c.close()
    return uid


def _approved(intake_id, name, email):
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
    _mkuser("trainee", email, rid)
    return rid


print(f"\nisolated database: {assert_isolated()}")
ADMIN = _mkuser("admin", "browser@test.invalid")

iid = create_intake("Browser Co", "Bo Reyes", "hr@browser.test", "0917",
                    "training", "Online", ADMIN)
_approved(iid, "Ann Cruz", "ann@browser.test")
_approved(iid, "Ben Diaz", "ben@browser.test")

# A second intake that is NOT eligible, to exercise the blocked path.
iid_bad = create_intake("Blocked Co", "Bea", "hr@blocked.test", None,
                        "training", "Online", ADMIN)
_approved(iid_bad, "Cal Uy", "cal@blocked.test")
add_slot(iid_bad, "Dot Ng", "dot@blocked.test")        # never submitted

# ── A PAID invoice carrying unfinished recovery state ────────────────────────
# The panel used to be hidden for any status other than 'pending', which hid
# recovery exactly when it matters: money arrived, the attempt never closed,
# and a webhook could not be matched. All three are set up here.
PAID_UID = _mkuser("trainee", "paid@browser.test")
PAID_CID, PAID_REF = create_corporate_payment(
    "Settled Co", "Sol", "hr@settled.test", "0918",
    [{"user_id": PAID_UID, "training_type": "Online", "form_type": "training",
      "price_php": 5000.0, "price_label": "CEM Training"}],
    5000.0, None, None, 500000,
    datetime.now() + timedelta(days=3), ADMIN)
# Only cid: mark_corporate_paid() tests reference, then paymongo_id, then
# cid, so passing paymongo_id too would make it the WHERE clause and match
# nothing — the invoice would quietly stay pending.
assert mark_corporate_paid(cid=PAID_CID), "fixture: invoice did not settle"

_att, _err = reserve_attempt(
    PAID_CID, 500000, PAID_REF, "test",
    {"line_items": [], "description": "Settled Co",
     "reference_number": PAID_REF, "success_url": "",
     "cancel_url": "", "metadata": {}}, created_by=ADMIN)
assert _att, _err
record_session(_att["attempt_ref"], "cs_browser_orphan", "https://pay.test/x")

# Matches this invoice by reference AND by session, so the per-invoice view
# must find it. livemode is deliberately absent — "unknown" must not be
# rendered as "test".
record_unresolved_event(
    "webhook", "settlement_lost_race",
    "Invoice became 'paid' during settlement.",
    {"session": {"id": "cs_browser_orphan", "attributes": {"amount": 500000}}},
    cs_id="cs_browser_orphan", reference_hint=PAID_REF,
    amount_centavos=500000, currency="PHP", livemode=None)

# Matches NO invoice: no reference hint, and a session we never recorded. Only
# the section-level queue can surface this one.
record_unresolved_event(
    "webhook", "unmatched_session",
    "No invoice matches this checkout session.",
    {"session": {"id": "cs_browser_orphan2"}},
    cs_id="cs_browser_orphan2", amount_centavos=250000, currency="PHP",
    livemode=False)

port = _free_port()
srv = make_server("127.0.0.1", port, app, threaded=True)
t = threading.Thread(target=srv.serve_forever, daemon=True)
t.start()
BASE = f"http://127.0.0.1:{port}"
print(f"serving on {BASE}")

page_errors = []       # uncaught exceptions
console_errors = []    # console.error, incl. browser network logging

try:
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(base_url=BASE)
        # The tested controls use ordinary buttons. Keep unrelated CDN widgets
        # local so an unavailable CDN cannot stop dashboard initialisation.
        ctx.add_init_script("""window.Swal={fire:()=>Promise.resolve({isConfirmed:false}),
          mixin:function(){return this;},stopTimer:()=>{},resumeTimer:()=>{}};
          window.flatpickr=()=>({selectedDates:[]});
          window.Chart=function(el,o){this.data=o.data;this.update=()=>{};};window.Chart.defaults={};""")
        ctx.route(re.compile(r'^https?://'), lambda route: route.continue_()
                  if route.request.url.startswith(BASE + '/') else
                  route.fulfill(status=200,body='',content_type='text/plain'))
        page = ctx.new_page()
        page.on("pageerror", lambda e: page_errors.append(str(e)))
        page.on("console", lambda m: console_errors.append(m.text)
                if m.type == "error" else None)

        # Sign in by seeding the session cookie the app itself would set.
        with app.test_request_context():
            from flask.sessions import SecureCookieSessionInterface
            si = SecureCookieSessionInterface()
            s = si.get_signing_serializer(app)
            cookie = s.dumps({"user_id": ADMIN, "user_role": "admin",
                              "user_name": "Browser Admin"})
        ctx.add_cookies([{"name": app.config.get("SESSION_COOKIE_NAME", "session"),
                          "value": cookie, "url": BASE}])

        print("\n0. CSRF protection is live, not disabled for the test")
        page.goto("/admin", wait_until="networkidle")
        check("the page carries a CSRF token for the JS to read",
              page.locator('meta[name="csrf-token"]').count() == 1)
        # A POST with no token must be refused. Once this holds, every POST in
        # the sections below is genuinely carrying a valid token — which is
        # what makes _ikCsrf() and the X-CSRFToken header real coverage
        # rather than theatre against a disabled check.
        bare = page.evaluate("""async () => {
            const r = await fetch('/admin/corporate/1/payment-link',
                                  {method: 'POST'});
            return r.status;
        }""")
        check("a POST without a token is refused", bare in (400, 403),
              f"HTTP {bare}")

        print("\n1. Console loads and the card form is gone")
        check("admin console renders", page.title() is not None)
        check("no corporate card number field",
              page.locator("#corp-c-number").count() == 0)
        check("no corporate CVC field", page.locator("#corp-c-cvc").count() == 0)
        check("no card/QR tabs", page.locator("#corp-tab-card").count() == 0)
        check("Company Intake nav present",
              page.get_by_text("Company Intake", exact=False).count() > 0)

        print("\n2. Intake roster opens and prices the invoice")
        page.evaluate("showSection('intake', document.querySelector('.nav-item'))")
        page.evaluate(f"openIntake({iid})")
        page.wait_for_selector("#intake-body table", timeout=5000)
        check("roster table rendered",
              page.locator("#intake-body table tbody tr").count() >= 2)
        check("Create corporate invoice offered for an eligible roster",
              page.get_by_role("button", name="Create corporate invoice").count() == 1)

        page.get_by_role("button", name="Create corporate invoice").click()
        page.wait_for_selector("#ik-link-out table", timeout=5000)
        preview = page.locator("#ik-link-out").inner_text()
        check("preview shows a priced total", "Total" in preview and "PHP" in preview,
              preview[:60].replace("\n", " "))
        check("preview offers creation",
              page.get_by_role("button", name="Create this invoice").count() == 1)

        print("\n3. Blocked roster explains itself and refuses")
        page.evaluate("closeIntake()")
        page.evaluate(f"openIntake({iid_bad})")
        page.wait_for_selector("#intake-body", timeout=5000)
        body_bad = page.locator("#intake-body").inner_text()
        check("ineligible intake hides the invoice action",
              page.get_by_role("button", name="Create corporate invoice").count() == 0)
        check("it names who is blocking", "Dot Ng" in body_bad, body_bad[:80].replace("\n", " "))

        print("\n4. Create the invoice and land in Corporate Payments")
        page.evaluate("closeIntake()")
        page.evaluate(f"openIntake({iid})")
        page.wait_for_selector("#intake-body table", timeout=5000)
        page.get_by_role("button", name="Create corporate invoice").click()
        page.wait_for_selector("#ik-link-out table", timeout=5000)
        page.get_by_role("button", name="Create this invoice").click()
        page.wait_for_selector("text=Open in Corporate Payments", timeout=8000)
        check("creation confirmed before the view changes",
              "created" in page.locator("#ik-link-out").inner_text().lower())
        page.get_by_role("button", name="Open in Corporate Payments").click()
        page.wait_for_timeout(1500)

        page.wait_for_selector("#corp-hp", timeout=8000)
        # get_by_role(name=...) matches a SUBSTRING case-insensitively, so
        # "Resolve" also matches "Mark resolved", and the section-level queue
        # renders its own buttons behind the modal overlay. Every button
        # lookup below is scoped to the modal for that reason.
        modal = page.locator("#corp-hp")
        check("detail modal opened straight from intake",
              page.locator("#corp-hp").count() == 1)
        page.wait_for_selector("#corp-hp .corp-sub", timeout=8000)
        panel = page.locator("#corp-hp").inner_text()
        check("hosted-payment operations rendered", "Payment link" in panel,
              panel[:70].replace("\n", " "))
        check("attempts section present", "Checkout attempts" in panel)
        check("no card controls in the modal",
              page.locator("#corp-hp input[id*='corp-c-']").count() == 0)

        print('\n4a. Override the intake invoice total in Corporate Payments')
        check('custom total input is available', page.locator('#corp-custom-total').count() == 1)
        bare_price = page.evaluate("""async () => {
            const r=await fetch('/admin/corporate/'+CORP_DETAIL_ID+'/price',{method:'POST'});
            return {status:r.status, body:await r.text()};
        }""")
        check('price override requires a CSRF token', bare_price['status'] == 400 and 'CSRF' in bare_price['body'])
        page.fill('#corp-custom-total', '12,345.67')
        page.fill('#corp-override-note', 'Company discount agreed for this intake')
        page.get_by_role('button', name='Save invoice total', exact=True).click()
        page.wait_for_function("() => document.querySelector('#corp-price-result')?.textContent.includes('Invoice total updated')")
        check('modal shows the new charged total', '12,345.67' in page.locator('#corp-body .stats-grid').inner_text())
        check('published trainee price is preserved', '12,345.67' not in page.locator('#corp-body .table-card').first.inner_text())
        check('saved reason appears in the invoice', 'Company discount agreed' in page.locator('#corp-body').inner_text())
        check('saved override prefills the refreshed panel', page.locator('#corp-custom-total').input_value() == '12345.67')
        page.locator('#corp-overlay .docs-box').screenshot(path=os.path.join(os.environ['TEMP'], 'powerwize-price-override.png'))

        print("\n5. Issue a payment link (real fetch, real JS)")
        modal.get_by_role("button", name="Generate payment link").click()
        page.wait_for_selector("#hp-link-out input", timeout=8000)
        url_val = page.locator("#hp-link-out input").input_value()
        check("link returned to the browser", "/pay/corporate/" in url_val,
              url_val[:50])
        check('checkout uses the overridden total',
              json.loads(get_attempts(int(page.locator('#corp-hp').get_attribute('data-cid')))[0]['request_payload'])['line_items'][0]['amount'] == 1234567)
        check("send button offered",
              page.get_by_role("button", name="Send to the company").count() == 1)

        print("\n6. Send, and see the MOCK outcome labelled distinctly")
        page.get_by_role("button", name="Send to the company").click()
        page.wait_for_selector("#hp-send-out .corp-note", timeout=8000)
        page.wait_for_function(
            "() => {const e=document.querySelector('#hp-send-out');"
            "return e && e.textContent.trim() && !/Sending/.test(e.textContent);}",
            timeout=8000)
        sent = page.locator("#hp-send-out").inner_text()
        check("send reported", len(sent) > 0, sent[:70])
        check("mock is NOT described as sent/submitted",
              "mock" in sent.lower() and "submitted to the mail server" not in sent.lower(),
              sent[:90])
        page.wait_for_selector("#corp-hp table", timeout=8000)
        delivery = page.locator("#corp-hp").inner_text()
        check("delivery row shows 'Mocked only'", "Mocked only" in delivery)
        check("and explains it was NOT emailed",
              "NOT emailed" in delivery, "wording must not imply delivery")

        print('\nCompany email editing and saved-link delivery')
        page.locator('#corp-email-editor summary').click()
        page.locator('#corp-contact-email').fill('new-contact@browser.test')
        page.get_by_role('button', name='Save email', exact=True).click()
        page.wait_for_function("document.getElementById('corp-current-email').textContent === 'new-contact@browser.test'")
        check('email editor saves without a page navigation', 'No email was sent' in page.locator('#corp-email-result').inner_text())
        check('email editor closes after Save', not page.locator('#corp-email-editor').evaluate('el => el.open'))
        page.evaluate('openCorpDetail(CORP_DETAIL_ID)')
        page.wait_for_selector('#corp-hp .corp-sub', timeout=8000)
        check('edited company email survives modal refresh', page.locator('#corp-current-email').inner_text() == 'new-contact@browser.test')
        page.locator('[onclick^="corpSendSavedLink("]').click()
        page.wait_for_function("document.getElementById('corp-email-result').textContent.includes('Mock transport')")
        check('existing link can be sent after editing email', 'new-contact@browser.test' in page.locator('#corp-email-result').inner_text())
        page.wait_for_function("document.getElementById('corp-hp').textContent.includes('new-contact@browser.test')")
        check('both recipient history rows remain visible', 'hr@browser.test' in page.locator('#corp-hp').inner_text()
              and 'new-contact@browser.test' in page.locator('#corp-hp').inner_text())

        print("\n7. Attempts panel shows real state")
        att = page.locator("#corp-hp").inner_text()
        check("an active attempt is listed", "Active" in att)
        # Refresh the full detail fragment: price edits must be unavailable
        # once the hosted checkout has taken an immutable amount snapshot.
        page.evaluate('openCorpDetail(CORP_DETAIL_ID)')
        page.wait_for_selector('#corp-hp .corp-sub', timeout=8000)
        check('price form is locked after checkout creation', page.locator('#corp-custom-total').count() == 0
              and 'amount is fixed' in page.locator('#corp-body').inner_text())
        check("environment shown", "test" in att)
        check("Resolve offered for an open attempt",
              page.get_by_role("button", name="Resolve").count() >= 1)

        print("\n8. Evidence-based recovery UI")
        modal.get_by_role("button", name="Resolve", exact=True).first.click()
        page.wait_for_selector("#hp-resolve-out", timeout=5000)
        rv = page.locator("#hp-resolve-out").inner_text()
        check("Retrieve offered (the attempt has a session)",
              modal.get_by_role("button", name="Retrieve from gateway").count() == 1)
        check("Replay NOT offered (it already has a session)",
              modal.get_by_role("button", name="Replay original request").count() == 0)
        check("manual entry is labelled a human statement",
              "not gateway truth" in rv.lower(), rv[-90:].replace("\n", " "))

        # Failure path: a manual outcome on an attempt that HAS a session.
        page.fill("#hp-ev", "I am asserting this without checking anything.")
        modal.get_by_role("button", name="Record manual verification").click()
        page.wait_for_timeout(1200)
        rv2 = page.locator("#hp-resolve-out").inner_text()
        check("server refusal is surfaced in the UI",
              "Retrieve" in rv2, rv2[:100].replace("\n", " "))

        print("\n9. Revoke, then retry fails visibly")
        page.on("dialog", lambda d: d.accept())
        modal.get_by_role("button", name="Revoke link").click()
        page.wait_for_timeout(1500)
        page.wait_for_selector("#corp-hp", timeout=5000)
        after = page.locator("#corp-hp").inner_text()
        check("revocation reflected in the panel",
              "No active payment link" in after, after[:70].replace("\n", " "))
        modal.get_by_role("button", name="Retry", exact=True).first.click()
        page.wait_for_selector("#hp-send-out .corp-note--err", timeout=8000)
        err = page.locator("#hp-send-out").inner_text()
        check("retry after revoke fails visibly", "revoked" in err.lower(),
              err[:90].replace("\n", " "))

        print("\n10. A rejected fetch still gives the operator feedback")
        # fetch() REJECTS on a dropped connection; it does not resolve with
        # ok:false. Unguarded that threw out of hpPost, the handler stopped,
        # and the spinner span forever. Simulate it for one call only.
        page.evaluate("""() => {
            window.__realFetch = window.fetch;
            window.fetch = (u, o) => (o && o.method === 'POST')
                ? Promise.reject(new TypeError('Failed to fetch'))
                : window.__realFetch(u, o);
        }""")
        page.get_by_role("button", name="Generate payment link").click()
        page.wait_for_timeout(2000)
        offline = page.locator("#hp-link-out").inner_text()
        check("a dropped POST is reported, not left spinning",
              "could not confirm the outcome" in offline.lower(),
              offline[:80].replace("\n", " "))
        check("it does not claim the request never arrived",
              "did not reach the server" not in offline.lower())
        check("no spinner is left behind",
              "Creating" not in offline and "spinner" not in offline.lower())
        check("and it does not claim to know the outcome",
              "may or may not" in offline, offline[-70:].replace("\n", " "))

        # Harder case: the POST fails AND so does the refresh that follows.
        # hpLoad() then replaces the whole panel with its own load error,
        # which used to take the operation's outcome down with it — leaving
        # only "Could not load payment operations."
        page.evaluate("""() => {
            window.fetch = () => Promise.reject(new TypeError('Failed to fetch'));
        }""")
        page.evaluate("hpRevoke()")          # confirm() is auto-accepted
        page.wait_for_timeout(2500)
        both = page.locator("#corp-hp").inner_text()
        check("the operation outcome survives a failed refresh",
              "could not confirm the outcome" in both.lower(),
              both[:120].replace("\n", " "))
        check("the refresh failure is reported too, not hidden by it",
              "could not load" in both.lower(), both[:170].replace("\n", " "))
        page.evaluate("() => { window.fetch = window.__realFetch; }")
        page.evaluate("hpLoad()")
        page.wait_for_selector("#corp-hp .corp-sub", timeout=8000)

        print("\n11. Recovery stays visible once the invoice is no longer pending")
        page.evaluate(f"closeCorpDetail && closeCorpDetail()")
        page.wait_for_timeout(400)
        page.evaluate(f"openCorpDetail({PAID_CID})")
        page.wait_for_selector("#corp-hp .corp-sub", timeout=8000)
        paid = page.locator("#corp-hp").inner_text()
        check("the payment panel renders for a PAID invoice",
              page.locator("#corp-hp").count() == 1)
        check("attempts remain visible", "Checkout attempts" in paid)
        check("link issuance is refused, with the status named",
              "no new payment link can be issued" in paid.lower()
              and "paid" in paid.lower(), paid[:90].replace("\n", " "))
        check("Generate is not offered on a paid invoice",
              modal.get_by_role("button", name="Generate payment link").count() == 0)
        check("Retry is not offered on a paid invoice",
              modal.get_by_role("button", name="Retry", exact=True).count() == 0)

        print("\n12. Unresolved gateway events are inspectable and resolvable")
        ev = page.locator("#corp-hp").inner_text()
        check("the event is listed against its invoice",
              "Unresolved gateway events" in ev and "settlement_lost_race" in ev,
              ev[-120:].replace("\n", " "))
        check("an unknown livemode is called out, not assumed",
              "mode unknown" in ev)
        modal.get_by_role("button", name="Inspect payload").first.click()
        page.wait_for_selector("#corp-hp pre", timeout=8000)
        raw = page.locator("#corp-hp pre").inner_text()
        check("the stored payload is shown verbatim", "cs_browser_orphan" in raw,
              raw[:70].replace("\n", " "))

        # An empty note must be refused — resolving is an audit record.
        modal.get_by_role("button", name="Resolve event").first.click()
        page.wait_for_timeout(400)
        modal.get_by_role("button", name="Mark resolved").first.click()
        page.wait_for_timeout(1200)
        blank = page.locator("#corp-hp").inner_text()
        check("resolving with no note is refused in the UI",
              "say how it was resolved" in blank.lower(), blank[:80].replace("\n", " "))

        modal.locator("textarea[id^='hp-evnote-']").fill(
            "Refunded in the dashboard; session belonged to a cancelled booking.")
        modal.get_by_role("button", name="Mark resolved").first.click()
        page.wait_for_timeout(1800)
        done = page.locator("#corp-hp").inner_text()
        check("a noted resolution clears the event",
              "settlement_lost_race" not in done, done[-110:].replace("\n", " "))

        print("\n13. An event matching no invoice is still reachable")
        page.evaluate("closeCorpDetail && closeCorpDetail()")
        page.wait_for_timeout(300)
        page.evaluate("hpQueueLoad()")
        page.wait_for_selector("#hp-queue .corp-note", timeout=8000)
        q = page.locator("#hp-queue").inner_text()
        check("the orphan event appears in the section queue",
              "unmatched_session" in q, q[:110].replace("\n", " "))
        check("it is not silently attributed to an invoice",
              "no session" not in q.lower() or "cs_browser_orphan2" in q)
        page.locator("#hp-queue").get_by_role(
            "button", name="Inspect payload").first.click()
        page.wait_for_selector("#hp-queue pre", timeout=8000)
        check("its payload is inspectable from the queue",
              "cs_browser_orphan2" in page.locator("#hp-queue pre").inner_text())

        print("\n14. No JavaScript errors throughout")
        check("no uncaught JS exceptions", not page_errors,
              "; ".join(page_errors[:2])[:160])
        # Sections 8 and 9 deliberately provoke server refusals, and Chromium
        # logs every non-2xx to the console. Those are expected; anything else
        # (a 500, a missing asset, a real console.error) is not.
        unexpected = [e for e in console_errors
                      if "favicon" not in e.lower()
                      and "400 (BAD REQUEST)" not in e
                      and "409 (CONFLICT)" not in e]
        check("no unexpected console errors", not unexpected,
              "; ".join(unexpected[:2])[:160])
        print("     (expected refusals logged by the browser: "
              + str(len(console_errors) - len(unexpected)) + ")")

        browser.close()
finally:
    srv.shutdown()

failed = [x for x in results if not x[1]]
print(f"\n{'='*64}\n{len(results) - len(failed)}/{len(results)} passed")
for n, _, d in failed:
    print(f"  FAILED: {n} {d}")
sys.exit(1 if failed else 0)
