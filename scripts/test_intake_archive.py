"""Company intake archiving: isolated DB, real CSRF and Chromium workflow.

Run with venv/Scripts/python.exe scripts/test_intake_archive.py.
The existing test DB is preserved; this script cleans up its own fixtures.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from _testdb import use_test_db, assert_isolated

use_test_db()
os.environ["MAIL_TRANSPORT"] = "mock"
os.environ["PAYMONGO_MOCK"] = "1"
os.environ.setdefault("SECRET_KEY", "intake-archive-test-key")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import re
import threading
import uuid
from datetime import datetime, timedelta

from app import app
from db import (get_db, init_db, create_intake, get_intake, get_intakes,
                add_slot, get_slots, issue_registration_token,
                registration_link_access, issue_coordinator_token,
                coordinator_access, create_corporate_payment,
                get_corporate_payment, create_class, get_class)
from flask.sessions import SecureCookieSessionInterface
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

assert_isolated()
app.config["WTF_CSRF_ENABLED"] = True
init_db()  # Re-running the additive archive DDL must be safe.
tag = uuid.uuid4().hex[:10]
users, intakes = [], []
cid = cls = None
checks = 0


def check(name, ok):
    global checks
    assert ok, name
    checks += 1
    print("PASS:", name)


def user(role):
    conn = get_db(); cur = conn.cursor()
    cur.execute("""INSERT INTO users (role, fname, lname, email, password_hash)
                   VALUES (%s,'Archive','Test',%s,'unused') RETURNING id""",
                (role, f"archive-{role}-{tag}@test.invalid"))
    uid = cur.fetchone()[0]
    conn.commit(); cur.close(); conn.close()
    users.append(uid)
    return uid


def client(uid, role):
    c = app.test_client()
    with c.session_transaction() as s:
        s.update(user_id=uid, user_role=role, user_name="Archive Test")
    html = c.get("/admin").get_data(as_text=True) if role == "admin" else c.get("/auth").get_data(as_text=True)
    token = re.search(r'<meta name="csrf-token" content="([^"]+)"', html)
    if token is None:
        # Render a token in this client's signed session, without disabling CSRF.
        with app.test_request_context():
            from flask_wtf.csrf import generate_csrf
            from flask import session
            token_value = generate_csrf()
            csrf_value = session["csrf_token"]
        with c.session_transaction() as s:
            s["csrf_token"] = csrf_value
        return c, token_value
    return c, token.group(1)


try:
    admin = user("admin")
    trainee = user("trainee")
    trainer = user("employee")
    for label in ("Active", "Other"):
        intakes.append(create_intake(f"Archive {label} {tag}", "Contact", "hr@test.invalid",
                                     None, "training", "Online", admin))
    iid = intakes[0]
    add_slot(iid, "Demo Trainee", "trainee@test.invalid")
    registration_token = issue_registration_token(iid)
    coordinator_token = issue_coordinator_token(iid)
    cid, _ = create_corporate_payment("Archive Invoice", "Contact", "hr@test.invalid",
                                       None, [], 100, None, None, 10000,
                                       datetime.now() + timedelta(hours=24), admin)
    conn = get_db(); cur = conn.cursor()
    cur.execute("UPDATE corporate_payments SET intake_id=%s WHERE id=%s", (iid, cid))
    conn.commit(); cur.close(); conn.close()
    cls, err = create_class("Archive Class", "Online", admin, intake_id=iid,
                            corporate_payment_id=cid, form_type="training")
    assert cls, err
    invoice_before, class_before = get_corporate_payment(cid=cid), get_class(class_id=cls["id"])
    slots_before = get_slots(iid)
    adm, csrf = client(admin, "admin")
    headers = {"X-CSRFToken": csrf}
    check("tokenless archive is rejected", adm.post(f"/admin/intake/{iid}/archive").status_code == 400)
    for uid, role in ((trainee, "trainee"), (trainer, "employee")):
        c, token = client(uid, role)
        for action in ("archive", "restore"):
            check(role + " cannot " + action, c.post(f"/admin/intake/{iid}/{action}",
                  headers={"X-CSRFToken": token}).status_code == 403)
    r = adm.post(f"/admin/intake/{iid}/archive", headers=headers)
    check("archive succeeds with CSRF", r.status_code == 200 and r.json["archived"])
    archived = get_intake(intake_id=iid)
    check("archive records timestamp and actor", archived["archived_at"] is not None and archived["archived_by"] == admin)
    r = adm.post(f"/admin/intake/{iid}/archive", headers=headers)
    check("repeat archive preserves metadata", not r.json["changed"] and get_intake(intake_id=iid)["archived_at"] == archived["archived_at"])
    check("active DB filter excludes archived intake", iid not in {r["id"] for r in get_intakes(archived=False)})
    check("archived DB filter includes intake", iid in {r["id"] for r in get_intakes(status="open", archived=True)})
    check("archive preserves status", archived["status"] == "open")
    check("archive preserves roster", get_slots(iid) == slots_before)
    check("archive preserves registration link", registration_link_access(registration_token) is not None)
    check("archive preserves coordinator link", coordinator_access(coordinator_token)[0] is not None)
    check("archive preserves invoice", get_corporate_payment(cid=cid) == invoice_before)
    check("archive preserves class", get_class(class_id=cls["id"]) == class_before)
    check("archived intake remains manageable", adm.get(f"/admin/intake/{iid}/panel").json["intake"]["archived_at"] is not None)
    check("unknown intake is rejected", adm.post("/admin/intake/2147483647/archive", headers=headers).status_code == 404)

    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            context = browser.new_context(base_url=f"http://127.0.0.1:{server.server_port}")
            # Archiving uses inline feedback and ordinary buttons. Supply
            # unrelated CDN widgets locally so an offline CDN cannot break the
            # dashboard's existing toast/date/chart initialisation in this test.
            context.add_init_script("""window.Swal = {
                fire: function () { return Promise.resolve({isConfirmed:false}); },
                mixin: function () { return this; },
                stopTimer: function () {}, resumeTimer: function () {}
            };
            window.flatpickr = function () { return {selectedDates:[]}; };
            window.Chart = function (el, options) {
                this.data = options.data; this.update = function () {};
            };
            window.Chart.defaults = {};""")
            with app.test_request_context():
                cookie = SecureCookieSessionInterface().get_signing_serializer(app).dumps(
                    {"user_id": admin, "user_role": "admin", "user_name": "Archive Test"})
            context.add_cookies([{"name": app.config["SESSION_COOKIE_NAME"], "value": cookie,
                                 "url": f"http://127.0.0.1:{server.server_port}"}])
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto("/admin", wait_until="networkidle")
            page.get_by_role("button", name="Company Intake", exact=True).click()
            row = page.locator(f'#ik-intake-table tr[data-intake-id="{iid}"]')
            check("archived row hidden by default after refresh", not row.is_visible())
            page.locator('[data-ik-view="archived"]').click()
            check("Archived view reveals row", row.is_visible())
            row.get_by_role("button", name="Manage", exact=True).click()
            page.get_by_role("button", name="Restore to Active", exact=True).wait_for()
            check("Manage shows archive state", "Archived on" in page.locator("#intake-body").inner_text())
            page.get_by_role("button", name="Restore to Active", exact=True).click()
            page.wait_for_function("() => document.querySelector('#ik-archive-out')?.textContent.includes('restored')")
            check("restore from Manage updates DB", get_intake(intake_id=iid)["archived_at"] is None)
            page.evaluate("closeIntake()")
            check("restored row leaves Archived view", not row.is_visible())
            page.locator('[data-ik-view="active"]').click()
            check("restored row returns to Active", row.is_visible())
            row.get_by_role("button", name="Archive", exact=True).click()
            page.wait_for_function("() => document.querySelector('#ik-list-out').textContent.includes('archived')")
            check("archive from list hides row", not row.is_visible())
            page.locator('[data-ik-view="all"]').click()
            check("All view includes archived row", row.is_visible())
            page.reload(wait_until="networkidle")
            page.get_by_role("button", name="Company Intake", exact=True).click()
            check("archive survives page reload", not row.is_visible())
            check("no uncaught browser errors: " + "; ".join(errors), not errors)
            browser.close()
    finally:
        server.shutdown()

    r = adm.post(f"/admin/intake/{iid}/restore", headers=headers)
    check("restore clears archive metadata", r.json["ok"] and get_intake(intake_id=iid)["archived_by"] is None)
    r = adm.post(f"/admin/intake/{iid}/restore", headers=headers)
    check("repeat restore is harmless", r.json["ok"] and not r.json["changed"])
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT action FROM audit_logs WHERE entity_type='corporate_intake' AND entity_id=%s", (str(iid),))
    actions = [r[0] for r in cur.fetchall()]
    cur.close(); conn.close()
    check("archive and restore are audited", "intake_archived" in actions and "intake_restored" in actions)
    print(f"{checks} checks passed; isolated database only.")
finally:
    conn = get_db(); cur = conn.cursor()
    if cls:
        cur.execute("DELETE FROM training_classes WHERE id=%s", (cls["id"],))
    if cid:
        cur.execute("DELETE FROM corporate_payments WHERE id=%s", (cid,))
    if intakes:
        cur.execute("DELETE FROM training_classes WHERE intake_id = ANY(%s)", (intakes,))
        cur.execute("DELETE FROM audit_logs WHERE entity_type='corporate_intake' AND entity_id = ANY(%s)", ([str(i) for i in intakes],))
        cur.execute("DELETE FROM corporate_intakes WHERE id = ANY(%s)", (intakes,))
    if users:
        cur.execute("DELETE FROM audit_logs WHERE user_id = ANY(%s)", (users,))
        cur.execute("DELETE FROM users WHERE id = ANY(%s)", (users,))
    conn.commit(); cur.close(); conn.close()
