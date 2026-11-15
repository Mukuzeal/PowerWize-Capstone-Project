"""Intake payment labels and automatic browser updates; isolated DB, no gateway/mail."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
from _testdb import use_test_db, assert_isolated

use_test_db(recreate=True)
os.environ['MAIL_TRANSPORT'] = 'mock'
os.environ['PAYMONGO_MOCK'] = '1'
os.environ['APP_BASE_URL'] = 'http://localhost'
sys.path.insert(0, str(ROOT / 'src'))

import threading
import uuid
from datetime import datetime, timedelta
from unittest.mock import patch
from werkzeug.serving import make_server
from app import app
from db import (get_db, dict_cur, create_intake, add_slot, insert_registration,
                create_invoice_for_intake, mark_corporate_paid, create_class,
                add_member_as_staff)
from pricing import calculate_fee

app.config.update(TESTING=True, WTF_CSRF_ENABLED=True)
checks = 0


def check(name, value):
    global checks
    assert value, name
    checks += 1
    print('PASS: ' + name, flush=True)


def sql(statement, params=(), one=False):
    conn = get_db()
    cur = dict_cur(conn)
    try:
        cur.execute(statement, params)
        rows = [dict(row) for row in cur.fetchall()] if cur.description else []
        conn.commit()
        return (rows[0] if rows else None) if one else rows
    finally:
        cur.close()
        conn.close()


ADMIN = sql("""INSERT INTO users(role,fname,lname,email,password_hash)
    VALUES('admin','Live','Admin','admin@live.invalid','unused') RETURNING id""", one=True)['id']


def fixture(name):
    iid = create_intake(name, 'Coordinator', 'company@live.invalid', '',
                        'training', 'Online', ADMIN)
    rid = uuid.uuid4().hex[:8].upper()
    entry = dict(id=rid, form_type='training', form_label='CEM Training',
                 submitted_at=datetime.now(), full_name=name + ' Trainee',
                 email=rid.lower() + '@live.invalid', training_type='Online',
                 photo_id='portrait.jpg', resume='resume.pdf', valid_id='id.jpg',
                 selfie_with_id='selfie.jpg')
    insert_registration(entry)
    sid, _ = add_slot(iid, entry['full_name'], entry['email'])
    sql('UPDATE corporate_intake_slots SET registration_id=%s,invite_used_at=NOW() WHERE id=%s', (rid, sid))
    sql("UPDATE registrations SET status='accepted',selfie_outcome='approved',selfie_reviewed_at=NOW() WHERE id=%s", (rid,))
    invoice, error = create_invoice_for_intake(iid, datetime.now() + timedelta(days=1), ADMIN, calculate_fee)
    assert invoice, error
    sql('UPDATE corporate_intakes SET payment_link_sent_at=NOW() WHERE id=%s', (iid,))
    return iid, rid, invoice['id']


def client(role='admin', uid=ADMIN):
    result = app.test_client()
    with result.session_transaction() as session:
        session.update(user_id=uid, user_role=role, user_name='Live Test')
    return result


admin = client()
IID, RID, CID = fixture('Live Company')


def record(iid=IID):
    response = admin.get('/admin/intake/list')
    assert response.status_code == 200
    return next(row for row in response.get_json()['records'] if row['id'] == iid)


check('isolated test database', assert_isolated() == 'powerwize_test')
check('pending invoice with an email is link sent, not paid', record()['display_status'] == 'Payment link sent')
mark_corporate_paid(cid=CID)
check('paid invoice takes precedence over link-send timestamp', record()['display_status'] == 'Paid')
check('initial dashboard uses the same paid label', 'Paid</span>' in admin.get('/admin').get_data(as_text=True))
add_slot(IID, 'Late Trainee', 'late@live.invalid')
check('paid historical invoice does not label an expanded roster paid', record()['display_status'] == 'Roster changed - review billing')
sql("DELETE FROM corporate_intake_slots WHERE intake_id=%s AND email_key='late@live.invalid'", (IID,))
check('same roster restores the authoritative paid label', record()['display_status'] == 'Paid')

for state in ('cancelled', 'expired'):
    iid, _, cid = fixture('Invoice ' + state)
    sql('UPDATE corporate_payments SET status=%s WHERE id=%s', (state, cid))
    check(state + ' invoice does not keep a link-sent badge', record(iid)['display_status'] == 'Invoice ' + state)

sql("UPDATE corporate_intakes SET coord_token_hash='private-marker',registration_token_hash='private-marker',registration_delivery_secret='private-marker' WHERE id=%s", (IID,))
response = admin.get('/admin/intake/list')
check('live list is never browser-cached', response.headers.get('Cache-Control') == 'no-store')
check('live list uses a strict field allowlist', 'private-marker' not in response.get_data(as_text=True) and 'token_hash' not in response.get_data(as_text=True))
check('anonymous live-list access is blocked', app.test_client().get('/admin/intake/list').status_code in (302, 403))
uid = sql("""INSERT INTO users(role,fname,lname,email,password_hash,registration_id)
    VALUES('trainee','Live','Trainee','trainee@live.invalid','unused',%s) RETURNING id""", (RID,), one=True)['id']
check('trainee cannot read admin live-list data', client('trainee', uid).get('/admin/intake/list').status_code == 403)
before = sql('SELECT COUNT(*) AS n FROM audit_logs', one=True)['n']
admin.get('/admin/intake/list'); admin.get('/admin/intake/list')
check('status polling creates no audit writes', before == sql('SELECT COUNT(*) AS n FROM audit_logs', one=True)['n'])

# Reset only the isolated fixture, to observe an actual asynchronous payment.
sql("UPDATE corporate_payments SET status='pending',paid_at=NULL WHERE id=%s", (CID,))
cls, error = create_class('Live Batch', 'Online', ADMIN, intake_id=IID, corporate_payment_id=CID, form_type='training')
assert cls, error
CLASS_ID = cls['id']


def browser_checks():
    from playwright.sync_api import sync_playwright
    server = make_server('127.0.0.1', 0, app, threaded=True)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    origin = f'http://127.0.0.1:{server.server_port}'
    cookie = app.session_interface.get_signing_serializer(app).dumps(
        dict(user_id=ADMIN, user_role='admin', user_name='Live Admin'))
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(viewport={'width':1280, 'height':900})
            context.add_cookies([dict(name=app.config['SESSION_COOKIE_NAME'], value=cookie, url=origin)])
            context.add_init_script("""window.Swal={fire:()=>Promise.resolve({isConfirmed:false}),mixin:()=>({fire:()=>{}})};
                window.Chart=function(el,o){this.data=o.data;this.update=()=>{};};window.Chart.defaults={};
                window.flatpickr=()=>({selectedDates:[]});""")
            context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(origin + '/') else route.fulfill(status=200, body=''))
            page = context.new_page()
            errors, methods, navigations = [], [], []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda request: methods.append(request.method))
            page.on('framenavigated', lambda frame: navigations.append(frame.url) if frame == page.main_frame else None)
            page.goto(origin + '/admin#intake')
            page.evaluate("showSection('intake',document.querySelector(\".nav-item[onclick*=intake]\"))")
            row = page.locator(f'#ik-intake-table tr[data-intake-id="{IID}"]')
            row.get_by_text('Payment link sent', exact=True).wait_for()
            navigation_count = len(navigations)
            mark_corporate_paid(cid=CID)
            row.get_by_text('Paid', exact=True).wait_for(timeout=12000)
            check('payment label changes automatically without page refresh', len(navigations) == navigation_count)

            # Another admin's new intake also appears without a page refresh.
            new_iid = create_intake('New External Intake', 'Other Coordinator', 'other@live.invalid', '', 'training', 'Online', ADMIN)
            page.locator(f'#ik-intake-table tr[data-intake-id="{new_iid}"]').wait_for(timeout=12000)
            check('new company intake appears automatically', True)
            page.evaluate(f'openIntake({IID})')
            page.get_by_role('tab', name='Trainees & review').click()
            page.locator('#ik-section-trainees details').evaluate('(node)=>node.open=true')
            draft = page.locator('#ik-more input[data-trainee-name]')
            draft.fill('Keep my unsaved trainee')
            page.evaluate("document.querySelector('#ik-more input[data-trainee-name]').dataset.identity='original-node'")
            sql('UPDATE corporate_intakes SET contact_person=%s WHERE id=%s', ('Updated coordinator', IID))
            await_live = 'async()=>{await ikLiveRefresh();clearTimeout(IK_LIVE_TIMER);}'
            page.evaluate(await_live)
            check('live panel updates contact details', 'Updated coordinator' in page.locator('#intake-sub').inner_text())
            check('live panel preserves typed draft and original input node', draft.input_value() == 'Keep my unsaved trainee' and draft.get_attribute('data-identity') == 'original-node')
            check('live panel preserves input focus', draft.evaluate('(node)=>document.activeElement===node'))
            check('live panel preserves selected tab', page.locator('[data-ik-tab=trainees]').get_attribute('aria-selected') == 'true')

            page.get_by_role('tab', name='Training', exact=True).click()
            page.locator(f'#ik-cls-{CLASS_ID}').wait_for(state='attached')
            page.get_by_role('button', name='Members & progress', exact=True).click()
            page.get_by_text('Nobody has joined yet.', exact=True).wait_for()
            ok, error = add_member_as_staff(CLASS_ID, uid, ADMIN)
            assert ok, error
            page.evaluate(await_live)
            page.locator(f'#ik-cls-{CLASS_ID}').get_by_text('trainee@live.invalid', exact=True).wait_for()
            check('open class membership updates and panel stays expanded', page.locator(f'#ik-cls-{CLASS_ID}').get_attribute('data-live-class-open') == 'yes')

            # Payment operations can change without wiping recovery evidence.
            sql("UPDATE corporate_payments SET status='pending',paid_at=NULL,needs_attention_at=NOW(),attention_reason='Test attention' WHERE id=%s", (CID,))
            page.get_by_role('tab', name='Billing', exact=True).click()
            page.get_by_role('button', name='Open invoice', exact=True).click()
            evidence = page.locator('#hp-att-note')
            evidence.fill('Keep my investigation note')
            page.evaluate("document.querySelector('#hp-att-note').dataset.identity='original-evidence';document.querySelector('#hp-send-out').textContent='Previous action outcome';")
            mark_corporate_paid(cid=CID)
            page.evaluate(await_live)
            check('background payment checks preserve evidence drafts', evidence.input_value() == 'Keep my investigation note' and evidence.get_attribute('data-identity') == 'original-evidence')
            evidence.fill('')
            page.get_by_role('tab', name='Billing', exact=True).focus()
            page.evaluate(await_live)
            check('open invoice reflects confirmed payment after editing ends', 'This invoice is paid' in page.locator('#corp-hp').inner_text())
            check('background payment updates retain operation feedback', page.locator('#hp-send-out').inner_text() == 'Previous action outcome')
            check('simultaneous refresh triggers share one request cycle', page.evaluate('async()=>{const first=ikLiveRefresh(),second=ikLiveRefresh();const same=first===second;await first;clearTimeout(IK_LIVE_TIMER);return same;}'))

            # A failed background GET must preserve the last confirmed facts.
            page.route('**/admin/intake/list', lambda route: route.fulfill(status=503, content_type='application/json', body='{}'))
            page.evaluate(await_live)
            check('network failure leaves the last known paid label visible', row.get_by_text('Paid', exact=True).is_visible())
            check('network failure is visible and retryable', 'last known status' in page.locator('#ik-live-status').inner_text())
            page.unroute('**/admin/intake/list')
            page.evaluate(await_live)
            check('live updates recover after a failed request', 'Live updates on' in page.locator('#ik-live-status').inner_text())

            page.evaluate("ikFilterIntakes('archived')")
            page.evaluate(await_live)
            check('archive filter survives live updates', page.locator('[data-ik-view=archived]').get_attribute('aria-pressed') == 'true' and not row.is_visible())
            page.evaluate('closeIntake()')
            with patch('admin.intake.get_intakes', side_effect=AssertionError('No hidden polling expected')):
                page.evaluate("showSection('dashboard',document.querySelector(\".nav-item[onclick*=dashboard]\"))")
                check('hidden intake view performs no status request', page.evaluate('async()=>{await ikLiveRefresh();return IK_LIVE_INFLIGHT===null;}'))
            check('live updates use GET only', set(methods) == {'GET'})
            check('live updates produce no uncaught browser exceptions', not errors)
            browser.close()
    finally:
        server.shutdown()
        worker.join(timeout=5)


if __name__ == '__main__':
    browser_checks()
    print(f'\n{checks} live-update checks passed; mock gateway/mail; isolated database only.', flush=True)
