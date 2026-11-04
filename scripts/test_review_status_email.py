"""Review status, account email outcomes, and temporary document retention.

Uses only powerwize_test, mock mail, and temporary upload directories.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from _testdb import use_test_db, assert_isolated
use_test_db()
os.environ['MAIL_TRANSPORT'] = 'mock'
os.environ['PAYMONGO_MOCK'] = '1'
os.environ.setdefault('SECRET_KEY', 'review-email-test')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import base64
import re
import smtplib
import tempfile
import threading
import uuid
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from app import app
import email_utils
from db import (get_db, create_intake, add_slot, claim_slot_with_registration,
                REGISTRATION_INSERT_SQL, registration_insert_params,
                get_registration_full, get_slots, get_document_reviews,
                get_pending_selfies)
from flask.sessions import SecureCookieSessionInterface
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

assert_isolated()
app.config['WTF_CSRF_ENABLED'] = True
checks = 0
reg_ids = []
iid = admin = None
tag = uuid.uuid4().hex[:10]


def check(name, condition):
    global checks
    assert condition, name
    checks += 1
    print('PASS:', name)


def sql(statement, params=(), fetch=False):
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute(statement, params)
        result = cur.fetchall() if fetch else None
        conn.commit()
        return result
    finally:
        cur.close(); conn.close()


def post(client, path, **data):
    html = client.get('/admin').get_data(as_text=True)
    csrf = re.search(r'<meta name="csrf-token" content="([^"]+)"', html).group(1)
    return client.post(path, data=dict(data, csrf_token=csrf))


def make_registration(directory, suffix):
    rid = uuid.uuid4().hex[:8].upper()
    email = f'review-{tag}-{suffix}@test.invalid'
    _, invitation = add_slot(iid, f'Review Trainee {suffix}', email)
    entry = dict(id=rid, form_type='training', form_label='CEM Training',
                 full_name=f'Review Trainee {suffix}', email=email,
                 training_type='Online', submitted_at=datetime.now())
    png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jgXcAAAAASUVORK5CYII=')
    paths = []
    for field in ('photo_id', 'resume', 'valid_id', 'selfie_with_id'):
        name = rid + '-' + field + ('.pdf' if field == 'resume' else '.png')
        path = Path(directory) / name
        path.write_bytes(b'%PDF test' if field == 'resume' else png)
        paths.append(path)
        entry[field] = name
    reg_id, error = claim_slot_with_registration(invitation, rid, REGISTRATION_INSERT_SQL,
                                                registration_insert_params(entry))
    assert reg_id, error
    reg_ids.append(rid)
    return rid, email, paths


with tempfile.TemporaryDirectory(prefix='powerwize-review-retention-') as directory:
    app.config['UPLOAD_FOLDER'] = directory
    app.config['LEGACY_UPLOAD_FOLDER'] = directory
    # Even an accidentally bypassed mail transport must never contact SMTP.
    with patch.object(smtplib, 'SMTP', side_effect=AssertionError('SMTP must not be contacted by this test')):
        try:
            admin = sql("INSERT INTO users (role,fname,lname,email,password_hash) "
                        "VALUES ('admin','Review','Admin',%s,'unused') RETURNING id",
                        (f'review-admin-{tag}@test.invalid',), fetch=True)[0][0]
            iid = create_intake('Review Test ' + tag, 'Contact', 'contact@test.invalid', '', 'training', 'Online', admin)
            rid, email, paths = make_registration(directory, 'Accepted')
            client = app.test_client()
            with client.session_transaction() as s:
                s.update(user_id=admin, user_role='admin', user_name='Review Admin')
            email_utils.SENT_MESSAGES.clear()
            response = post(client, f'/admin/registration/{rid}/status/accepted')
            check('acceptance alone records the application decision', response.status_code == 302
                  and get_registration_full(rid)['status'] == 'accepted')
            row = client.get(f'/admin/intake/{iid}/panel').json['slots'][0]
            check('intake explains accepted but identity pending', row['status_label'] == 'Accepted — identity pending')
            check('identity column receives the real state', row['identity'] == 'pending' and row['identity_label'] == 'Pending')
            check('no account invitation before identity approval', not email_utils.SENT_MESSAGES
                  and sql('SELECT count(*) FROM account_tokens WHERE reg_id=%s', (rid,), fetch=True)[0][0] == 0)
            check('all temporary documents remain while identity review is pending', all(p.exists() for p in paths))

            server = make_server('127.0.0.1', 0, app, threaded=True)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            base = f'http://127.0.0.1:{server.server_port}'
            try:
                with sync_playwright() as pw:
                    browser = pw.chromium.launch()
                    context = browser.new_context(base_url=base)
                    context.add_init_script("""window.Swal={fire:()=>Promise.resolve({isConfirmed:false}),
                        mixin:function(){return this;},stopTimer:()=>{},resumeTimer:()=>{}};
                        window.flatpickr=()=>({selectedDates:[]});
                        window.Chart=function(el,o){this.data=o.data;this.update=()=>{};};window.Chart.defaults={};""")
                    context.route(re.compile(r'^https?://'), lambda route: route.continue_()
                                  if route.request.url.startswith(base + '/') else route.fulfill(status=200,body='',content_type='text/plain'))
                    with app.test_request_context():
                        cookie = SecureCookieSessionInterface().get_signing_serializer(app).dumps(
                            dict(user_id=admin, user_role='admin', user_name='Review Admin'))
                    context.add_cookies([dict(name=app.config['SESSION_COOKIE_NAME'], value=cookie, url=base)])
                    page = context.new_page(); errors = []
                    page.on('pageerror', lambda e: errors.append(str(e)))
                    page.goto('/admin', wait_until='networkidle')
                    page.get_by_role('button', name='Company Intake', exact=True).click()
                    page.evaluate(f'openIntake({iid})')
                    roster = page.locator('#intake-body tr').filter(has_text=email)
                    roster.wait_for()
                    check('browser shows the missing identity step', 'Accepted — identity pending' in roster.inner_text())
                    roster.get_by_role('button', name='Review identity', exact=True).click()
                    review_row = page.locator('#identity-review-' + rid)
                    check('Review identity opens the correct private review row', review_row.is_visible()
                          and page.locator('#section-selfies').evaluate("el => el.classList.contains('active')"))
                    review_row.get_by_role('button', name='Approve identity', exact=True).click()
                    page.wait_for_load_state('networkidle')
                    check('identity approval issues exactly one mock account email', len(email_utils.SENT_MESSAGES) == 1
                          and email_utils.SENT_MESSAGES[0]['to'] == email)
                    check('preview or mock email is not called sent', 'Mocked only' in page.content()
                          and 'Account setup email sent to' not in page.content())
                    check('no uncaught JavaScript errors', not errors)
                    browser.close()
            finally:
                server.shutdown()
            row = next(s for s in client.get(f'/admin/intake/{iid}/panel').json['slots'] if s['registration'] == rid)
            check('both approvals produce Approved', row['status'] == 'approved' and row['identity'] == 'approved')
            check('approved identity leaves the pending queue', rid not in {r['id'] for r in get_pending_selfies()})
            check('approval deletes every temporary upload', all(not p.exists() for p in paths))
            reg = get_registration_full(rid)
            check('approval clears file pointers and records purge completion', reg['documents_purged_at'] is not None
                  and all(reg[f] is None for f in ('photo_id','resume','valid_id','selfie_with_id')))
            check('hashes and review evidence remain in the database', len(get_document_reviews(rid)) == 4
                  and all(r['sha256'] and r['outcome'] == 'accepted' for r in get_document_reviews(rid)))
            with tempfile.TemporaryDirectory(prefix='powerwize-account-preview-') as outbox:
                with patch.object(email_utils, 'MAIL_TRANSPORT', 'preview'), patch.object(email_utils, 'OUTBOX_DIR', outbox):
                    preview = post(client, f'/admin/registration/{rid}/resend-invitation')
                    check('account Resend reports preview honestly', preview.status_code == 200 and preview.json['delivery'] == 'preview'
                          and 'NOT emailed' in preview.json['message'] and len(list(Path(outbox).glob('*.html'))) == 1)
            with patch('admin.registrations.send_acceptance_email', return_value='submitted'):
                submitted = post(client, f'/admin/registration/{rid}/resend-invitation')
                check('simulated SMTP acceptance is labelled submitted', submitted.status_code == 200
                      and 'submitted to the mail server' in submitted.json['message'])
            with patch('admin.registrations.send_acceptance_email', side_effect=email_utils.MailDeliveryError('test failure')):
                failed = post(client, f'/admin/registration/{rid}/resend-invitation')
                check('failed account email exposes recovery and link rotation', failed.status_code == 502 and failed.json['rotated'])

            rejected_id, _, rejected_paths = make_registration(directory, 'Rejected')
            post(client, f'/admin/registration/{rejected_id}/status/rejected')
            check('rejection preserves documents needed for the unfinished identity review', all(p.exists() for p in rejected_paths))
            post(client, f'/admin/selfie/{rejected_id}/reject', reason='Test rejection')
            check('final rejection deletes all temporary uploads', all(not p.exists() for p in rejected_paths))
            rejected = get_registration_full(rejected_id)
            check('rejected trainee and review outcome remain in DB', rejected['status'] == 'rejected'
                  and rejected['selfie_outcome'] == 'rejected' and rejected['documents_purged_at'] is not None)
            check('rejection preserves hashes without issuing an account invitation', len(get_document_reviews(rejected_id)) == 4
                  and sql('SELECT count(*) FROM account_tokens WHERE reg_id=%s', (rejected_id,), fetch=True)[0][0] == 0)
            print(f'{checks} checks passed; isolated DB, mock mail, temporary uploads only.')
        finally:
            if iid:
                sql('DELETE FROM corporate_intakes WHERE id=%s', (iid,))
            for reg_id in reg_ids:
                sql('DELETE FROM account_tokens WHERE reg_id=%s', (reg_id,))
                sql('DELETE FROM registrations WHERE id=%s', (reg_id,))
            if admin:
                sql('DELETE FROM audit_logs WHERE user_id=%s', (admin,))
                sql('DELETE FROM users WHERE id=%s', (admin,))
