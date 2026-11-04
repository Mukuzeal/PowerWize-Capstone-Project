"""Shared company class-code entry: isolated DB, mock email, real routes and CSRF.

Run: venv/Scripts/python.exe scripts/test_shared_registration.py
Does not import app.py or access the real database/uploads.
"""
import os
import io
from pathlib import Path
import re
import sys
import uuid
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
from _testdb import test_db_url, use_test_db, assert_isolated

test_db_url()  # Validate local destination before ensure_test_db connects.
os.environ['MAIL_TRANSPORT'] = 'mock'
os.environ.setdefault('SECRET_KEY', 'shared-registration-email-test')
use_test_db()
sys.path.insert(0, str(ROOT / 'src'))

from flask import Flask, session
from flask_wtf import CSRFProtect
from db import (init_db, get_db, create_intake, add_slot, issue_registration_token,
                issue_coordinator_token, registration_link_access, get_slots,
                enter_registration_with_class_code, list_classes, rotate_join_code, set_join_open,
                get_notifications, get_notification, notification_payload,
                queue_registration_link_email,
                revoke_registration_token)
from company_bp import company_bp
from registration import registration_bp, save_registration
from site_bp import site_bp
from admin import admin_bp
import email_utils

assert_isolated()
init_db()
init_db()
app = Flask(__name__, template_folder=str(ROOT / 'templates'), static_folder=str(ROOT / 'static'))
app.secret_key = 'isolated-shared-registration-test'
app.config['TESTING'] = True
upload_sandbox = tempfile.TemporaryDirectory(prefix='powerwize-shared-registration-')
app.config['UPLOAD_FOLDER'] = upload_sandbox.name
CSRFProtect(app)
app.register_blueprint(site_bp)
app.register_blueprint(registration_bp)
app.register_blueprint(company_bp)
app.register_blueprint(admin_bp)
app.add_url_rule('/auth', endpoint='auth.auth', view_func=lambda: '')

passed = 0


def check(condition, message):
    global passed
    assert condition, message
    passed += 1
    print('PASS:', message)


def execute(sql, params=()):
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute(sql, params)
        conn.commit()
    finally:
        cur.close(); conn.close()


def post(client, path, **data):
    page = client.get(path)
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.get_data(as_text=True)).group(1)
    return client.post(path, data=dict(data, csrf_token=csrf))


def enter_class(client, path, email, code):
    before = len(email_utils.SENT_MESSAGES)
    response = post(client, path, action='enter_class', email=email, class_code=code)
    check(response.status_code == 302, 'class code and roster email open registration directly')
    check(len(email_utils.SENT_MESSAGES) == before, 'registration entry sends no verification email')
    return response


def submit_grant(client, email):
    rid = uuid.uuid4().hex[:8].upper()
    with client.session_transaction() as browser_session:
        grant = dict(browser_session['company_registration_grant'])
    with app.test_request_context('/training/submit', method='POST'):
        session['company_registration_grant'] = grant
        result = save_registration(dict(id=rid, form_type='training', form_label='CEM Training',
            submitted_at=datetime.now(), email=email, full_name='Shared-link Test Trainee'), grant['token'])
        if result[1] is None:
            registration_ids.append(rid)
    return result


def submit_without_session(grant, email):
    rid = uuid.uuid4().hex[:8].upper()
    with app.test_request_context('/training/submit', method='POST'):
        result = save_registration(dict(id=rid, form_type='training', form_label='CEM Training',
            submitted_at=datetime.now(), email=email, full_name='Class Code Test'), grant['token'])
        if result[1] is None:
            registration_ids.append(rid)
    return result


intake_ids, registration_ids, batch_ids, user_ids = [], [], [], []
try:
    # Sessions used to assume users.id=1 existed from a previous test run.
    # Real notification FKs require real isolated actor accounts.
    conn = get_db(); cur = conn.cursor()
    for role in ('admin', 'trainee'):
        cur.execute("""INSERT INTO users(role,fname,lname,email,password_hash)
                       VALUES(%s,'Shared','Test',%s,'x') RETURNING id""",
                    (role, uuid.uuid4().hex + '@shared-test.invalid'))
        user_ids.append(cur.fetchone()[0])
    conn.commit(); cur.close(); conn.close()
    admin_user, trainee_user = user_ids
    iid = create_intake('Shared Entry Test', 'Contact', 'contact@example.invalid', '', 'training', '', None)
    intake_ids.append(iid)
    for name in ('ana', 'ben', 'cy', 'dee'):
        add_slot(iid, name.title(), name + '@example.invalid')
    token = issue_registration_token(iid)
    classes = list_classes(intake_id=iid)
    check(len(classes) == 1, 'issuing a registration link automatically creates one class')
    class_id, class_code = classes[0]['id'], classes[0]['join_code']
    path = '/company/register/' + token
    coordinator = issue_coordinator_token(iid)
    check(registration_link_access(token)['id'] == iid, 'shared registration link resolves')
    check(app.test_client().get('/company/roster/' + token).status_code == 404,
          'registration link cannot access coordinator roster')
    check(app.test_client().get('/company/register/' + coordinator).status_code == 404,
          'coordinator token cannot be used as registration token')
    ana, ben = app.test_client(), app.test_client()
    landing = ana.get(path)
    body = landing.get_data(as_text=True)
    check('ana@example.invalid' not in body and 'ben@example.invalid' not in body,
          'shared entry never exposes roster emails')
    check(landing.headers['Cache-Control'] == 'no-store' and landing.headers['Referrer-Policy'] == 'same-origin',
          'entry prevents caching and external referrer leakage while supporting HTTPS CSRF')
    check('name="class_code"' in body and 'Send verification code' not in body,
          'entry asks for a class code instead of an emailed OTP')
    check(ana.post(path, data={'action': 'enter_class', 'email': 'ana@example.invalid', 'class_code': class_code}).status_code == 400,
          'class-code entry requires CSRF')
    response = post(ana, path, action='enter_class', email='ana@example.invalid', class_code='incorrect')
    with ana.session_transaction() as s:
        check('company_registration_grant' not in s, 'wrong class code does not grant access')
    response = enter_class(ana, path, 'ANA@example.invalid', ' ' + class_code.lower() + ' ')
    check(response.status_code == 302 and response.location == path,
          'trainee remains on the shared company URL')
    form = ana.get(path).get_data(as_text=True)
    check('value="ana@example.invalid" readonly' in form, 'company upload form binds the selected roster email')
    check('Verified email' not in form, 'class code is not misrepresented as proof of email ownership')
    check('Submit your <em>requirements</em>' in form and f'action="{path}"' in form,
          'company-branded upload form submits back to the same company URL')
    invalid = post(ana, path, action='submit_registration')
    check(invalid.status_code == 200 and f'action="{path}"' in invalid.get_data(as_text=True),
          'validation failure retains company context and upload action')
    check(submit_grant(ana, 'ben@example.invalid')[1] is not None, 'email substitution is rejected')
    check(submit_grant(ana, 'ana@example.invalid')[1] is None, 'class-code submission attaches atomically')
    check(submit_grant(ana, 'ana@example.invalid')[1] is not None, 'replay cannot create a second registration')
    response = enter_class(ben, path, 'ben@example.invalid', class_code)
    check(response.status_code == 302, 'another trainee uses the exact same shared entry link')
    check(submit_grant(ben, 'ben@example.invalid')[1] is None, 'second trainee attaches to their own slot')
    slots = {s['email']: s for s in get_slots(iid)}
    check(slots['ana@example.invalid']['registration_id'] != slots['ben@example.invalid']['registration_id'],
          'shared entry maintains independent registrations')
    unknown = app.test_client()
    before = len(email_utils.SENT_MESSAGES)
    response = post(unknown, path, action='enter_class', email='outsider@example.invalid', class_code=class_code)
    check(response.status_code == 200 and len(email_utils.SENT_MESSAGES) == before,
          'unknown email gets a generic refusal without sending email')
    grant = enter_registration_with_class_code(token, 'cy@example.invalid', class_code)
    check(grant is not None, 'shared class code remains usable by another unsubmitted trainee')
    cy = app.test_client()
    with cy.session_transaction() as browser_session:
        browser_session['company_registration_grant'] = dict(grant, link_token=token)
    class_code, err = rotate_join_code(class_id)
    check(submit_grant(cy, 'cy@example.invalid')[1] is not None, 'rotating the class code invalidates an unfinished upload grant')
    check(submit_without_session(grant, 'cy@example.invalid')[1] is not None,
          'dropping the session cannot bypass class-code rotation')
    grant = enter_registration_with_class_code(token, 'cy@example.invalid', class_code)
    with cy.session_transaction() as browser_session:
        browser_session['company_registration_grant'] = dict(grant, link_token=token)
    revoke_registration_token(iid)
    check(submit_without_session(grant, 'cy@example.invalid')[1] is not None,
          'dropping the session cannot bypass shared-link revocation')
    check(submit_grant(cy, 'cy@example.invalid')[1] is not None, 'revocation blocks an unfinished class-code submission')
    check(app.test_client().get(path).status_code == 404, 'revoked shared link stops entry')
    new_token = issue_registration_token(iid)
    check(registration_link_access(token) is None and registration_link_access(new_token),
          'replacement invalidates old shared link')
    check(len(list_classes(intake_id=iid)) == 1 and list_classes(intake_id=iid)[0]['join_code'] == class_code,
          'replacing a link reuses the open class and current code')
    check(enter_registration_with_class_code(new_token, 'ana@example.invalid', class_code) is None,
          'a submitted roster slot cannot be opened again with the class code')
    check(enter_registration_with_class_code(new_token, 'dee@example.invalid', 'BADCODE') is None,
          'wrong class code is refused')
    execute("UPDATE corporate_intakes SET registration_expires_at=NOW()-INTERVAL '1 minute' WHERE id=%s", (iid,))
    check(registration_link_access(new_token) is None, 'expired shared link is rejected')
    # Exercise the new staff endpoints with CSRF enabled and real permissions.
    token = issue_registration_token(iid)
    path = '/company/register/' + token
    anon, trainee, staff = app.test_client(), app.test_client(), app.test_client()
    with trainee.session_transaction() as s:
        s.update(user_id=trainee_user, user_role='trainee')
    with staff.session_transaction() as s:
        s.update(user_id=admin_user, user_role='admin')
    def staff_post(client, target, **data):
        page = client.get(path)
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.get_data(as_text=True)).group(1)
        return client.post(target, data=dict(data, csrf_token=csrf))
    endpoint = f'/admin/intake/{iid}/registration-link'
    check(staff_post(anon, endpoint).status_code == 302, 'anonymous user cannot issue a shared link')
    check(staff_post(trainee, endpoint).status_code == 403, 'trainee cannot issue a shared link')
    response = staff_post(staff, endpoint)
    check(response.status_code == 200 and '/company/register/' in response.get_json()['url'],
          'authorized admin can issue one shared registration link')
    check(response.json['class_code'] == class_code and response.json['class_id'] == class_id,
          'admin receives the reusable class code together with the registration link')
    check(response.headers['Cache-Control'] == 'no-store', 'issued shared secret response is not cacheable')
    issued = response.json
    path = '/company/register/' + response.get_json()['url'].rsplit('/', 1)[1]
    send_endpoint = endpoint + '/send'
    arguments = {'registration_url': issued['url'], 'class_id': issued['class_id']}
    check(staff.post(send_endpoint, data=arguments).status_code == 400,
          'sending a company registration email requires CSRF')
    check(staff_post(trainee, send_endpoint, **arguments).status_code == 403,
          'a trainee cannot email the company registration link')
    check(staff_post(anon, send_endpoint, **arguments).status_code == 302,
          'an anonymous visitor cannot email a registration link')
    before = len(email_utils.SENT_MESSAGES)
    foreign_url = issued['url'].replace('http://localhost', 'https://evil.invalid')
    check(staff_post(staff, send_endpoint, registration_url=foreign_url,
                     class_id=issued['class_id']).status_code == 409,
          'a valid registration token on a foreign origin is refused')
    check(not get_notifications(iid), 'a refused email URL consumes no notification intent')
    sent = staff_post(staff, send_endpoint, **arguments, to_email='attacker@example.invalid')
    check(sent.status_code == 200 and sent.json['status'] == 'mocked' and 'NOT emailed' in sent.json['message'],
          'registration email uses mock delivery with honest status')
    mail = email_utils.SENT_MESSAGES[-1]
    check(len(email_utils.SENT_MESSAGES) == before + 1 and mail['to'] == 'contact@example.invalid',
          'recipient comes from the company contact, never a posted address')
    check(issued['url'] in mail['html'] and issued['class_code'] in mail['html'],
          'company email contains the shared registration link and current class code')
    check('ana@example.invalid' not in mail['html'] and '/document/' not in mail['html'],
          'company email contains no trainee roster or documents')
    notice_id = sent.json['notification_id']
    notice = get_notification(notice_id)
    payload, error = notification_payload(notice_id, link_kind='registration')
    check(not error and payload['registration_url'] == issued['url'] and issued['url'] not in notice['payload'],
          'retry content is committed and encrypted at rest')
    check(staff_post(staff, send_endpoint, **arguments).status_code == 409
          and len(email_utils.SENT_MESSAGES) == before + 1,
          'a second send for the same link and code does not duplicate the email')
    retry_endpoint = f'/admin/intake/{iid}/registration-notice/{notice_id}/retry'
    check(staff_post(staff, f'/admin/intake/{iid + 100000}/registration-notice/{notice_id}/retry').status_code == 404,
          'a delivery retry is scoped to its intake')
    original_send = email_utils.send_company_registration_link
    def failed_send(*args, **kwargs):
        raise email_utils.MailDeliveryError('Simulated transport failure')
    email_utils.send_company_registration_link = failed_send
    try:
        failed = staff_post(staff, retry_endpoint)
        check(failed.status_code == 502 and get_notification(notice_id)['status'] == 'failed',
              'failed delivery remains visible and retryable')
    finally:
        email_utils.send_company_registration_link = original_send
    retried = staff_post(staff, retry_endpoint)
    check(retried.status_code == 200 and get_notification(notice_id)['attempts'] == 3
          and issued['url'] in email_utils.SENT_MESSAGES[-1]['html'],
          'retry uses the same stored link without requiring a browser URL')
    execute("UPDATE corporate_notifications SET status='in_flight', attempt_expires_at=NOW()-INTERVAL '1 second' WHERE id=%s", (notice_id,))
    check(staff_post(staff, retry_endpoint).status_code == 409,
          'an expired in-flight delivery is not blindly re-sent')
    execute("UPDATE corporate_notifications SET status='uncertain' WHERE id=%s", (notice_id,))
    check(staff_post(staff, retry_endpoint).status_code == 409,
          'an uncertain email needs explicit duplicate-send confirmation')
    check(staff_post(staff, retry_endpoint, confirm_resend='yes').status_code == 200,
          'an operator can explicitly retry an uncertain registration email')
    original_transport, original_outbox = email_utils.MAIL_TRANSPORT, email_utils.OUTBOX_DIR
    with tempfile.TemporaryDirectory(prefix='powerwize-email-preview-') as preview_dir:
        email_utils.MAIL_TRANSPORT, email_utils.OUTBOX_DIR = 'preview', preview_dir
        try:
            preview = staff_post(staff, retry_endpoint)
            check(preview.status_code == 200 and preview.json['status'] == 'previewed'
                  and 'NOT emailed' in preview.json['message'] and len(list(Path(preview_dir).glob('*.html'))) == 1,
                  'preview writes a local email and never claims it was emailed')
        finally:
            email_utils.MAIL_TRANSPORT, email_utils.OUTBOX_DIR = original_transport, original_outbox
    original_key = os.environ['SECRET_KEY']
    os.environ['SECRET_KEY'] = 'different-email-encryption-key'
    try:
        unreadable = staff_post(staff, retry_endpoint)
        check(unreadable.status_code == 409 and 'registration link could not be decrypted' in unreadable.json['error'],
              'an unreadable stored registration link produces an actionable refusal')
    finally:
        os.environ['SECRET_KEY'] = original_key
    email_utils.send_company_registration_link = lambda *args, **kwargs: 'submitted'
    try:
        smtp_result = staff_post(staff, retry_endpoint)
        check(smtp_result.status_code == 200 and smtp_result.json['status'] == 'submitted'
              and 'does not confirm inbox delivery' in smtp_result.json['message'],
              'a simulated SMTP acceptance is labelled submitted, not inbox delivery')
    finally:
        email_utils.send_company_registration_link = original_send
    check(staff_post(staff, retry_endpoint).status_code == 409,
          'an SMTP-submitted registration notice is not re-sent by ordinary Retry')
    check(staff_post(trainee, endpoint + '/revoke').status_code == 403, 'trainee cannot revoke the shared link')
    check(staff_post(staff, endpoint + '/revoke').status_code == 302, 'authorized admin can revoke shared access')
    # CSRF stays in the same session after revocation; no live entry GET needed.
    with app.test_request_context():
        from flask_wtf.csrf import generate_csrf
        retry_csrf = generate_csrf()
        csrf_value = session['csrf_token']
    with staff.session_transaction() as s:
        s['csrf_token'] = csrf_value
    check(staff.post(retry_endpoint, data={'csrf_token': retry_csrf}).status_code == 409,
          'revoking a registration link prevents delivery retry')
    # Every program uses its own fields on the company URL, never its public action.
    for program in ('training', 'cea_training', 'cem_renewal', 'cea_renewal', 'gemp_lgu', 'gemp_oge'):
        program_intake = create_intake('Program Upload Test', 'Contact', 'contact@example.invalid', '', program, '', None)
        intake_ids.append(program_intake)
        add_slot(program_intake, 'Program Trainee', 'program@example.invalid')
        program_token = issue_registration_token(program_intake)
        program_code = list_classes(intake_id=program_intake)[0]['join_code']
        grant = enter_registration_with_class_code(program_token, 'program@example.invalid', program_code)
        browser = app.test_client()
        with browser.session_transaction() as s:
            s['company_registration_grant'] = dict(grant, link_token=program_token)
        program_path = '/company/register/' + program_token
        program_page = browser.get(program_path)
        check(program_page.status_code == 200 and f'action="{program_path}"' in program_page.get_data(as_text=True)
              and 'Submit your <em>requirements</em>' in program_page.get_data(as_text=True),
              program + ' renders a company-specific upload form')
        if program == 'training':
            conn = get_db(); cur = conn.cursor()
            cur.execute("INSERT INTO batches (name,type,start_date) VALUES ('Shared Upload Test','training','2030-01-01') RETURNING id")
            batch_id = cur.fetchone()[0]; batch_ids.append(batch_id)
            conn.commit(); cur.close(); conn.close()
            response = post(browser, program_path, action='submit_registration', title='Ms.',
                full_name='Program Trainee', middle_name='Test', residence='Test address',
                company_name='Tampered company', designation='Engineer', company_address='Company address',
                contact_number='09000000000', email='program@example.invalid', birthdate='1990-01-01',
                age='36', agree='yes', training_type='Online', batch_id=str(batch_id),
                photo_id=(io.BytesIO(b'test photo'), 'photo.png'),
                valid_id=(io.BytesIO(b'test ID'), 'id.png'),
                resume=(io.BytesIO(b'%PDF test resume'), 'resume.pdf'))
            attached = get_slots(program_intake)[0]['registration_id']
            if attached:
                registration_ids.append(attached)
            check(response.status_code == 200 and attached is not None and 'Application recorded' in response.get_data(as_text=True),
                  'real multipart submission succeeds through company URL and attaches to roster')
            conn = get_db(); cur = conn.cursor()
            cur.execute('SELECT company_name FROM registrations WHERE id=%s', (attached,))
            stored_company = cur.fetchone()[0]; cur.close(); conn.close()
            check(stored_company == 'Program Upload Test', 'submission preserves authoritative company name')
            check(post(browser, program_path, action='submit_registration').status_code == 403,
                  'company upload POST without an active class-code grant is refused')
    public_form = app.test_client().get('/training').get_data(as_text=True)
    check('action="/training/submit"' in public_form and 'Submit your <em>requirements</em>' not in public_form,
          'ordinary public registration retains its original flow')
    concurrent_intake = create_intake('Concurrent Code Test', 'Contact', 'contact@example.invalid', '', 'training', '', None)
    intake_ids.append(concurrent_intake)
    with ThreadPoolExecutor(max_workers=5) as pool:
        issued = list(pool.map(lambda _: issue_registration_token(concurrent_intake, with_class=True), range(5)))
    check(len(list_classes(intake_id=concurrent_intake)) == 1 and len({x['class_code'] for x in issued}) == 1,
          'five concurrent link generations create only one class and one shared code')
    current_token = next(x['token'] for x in issued if registration_link_access(x['token']))
    add_slot(concurrent_intake, 'Concurrent Trainee', 'concurrent@example.invalid')
    other_code = issued[0]['class_code']
    check(enter_registration_with_class_code(current_token, 'concurrent@example.invalid', class_code) is None,
          'another company class code cannot open this intake')
    check(enter_registration_with_class_code(current_token, 'concurrent@example.invalid', other_code) is not None,
          'the same trainee is accepted with their own company code')
    with ThreadPoolExecutor(max_workers=5) as pool:
        queued = list(pool.map(lambda _: queue_registration_link_email(concurrent_intake,
            'http://localhost/company/register/' + current_token, issued[0]['class_id'], 'http://localhost/', None), range(5)))
    check(sum(nid is not None for nid, error in queued) == 1
          and len(get_notifications(concurrent_intake)) == 1,
          'five simultaneous email authorizations produce one durable notice')
    set_join_open(issued[0]['class_id'], False)
    check(enter_registration_with_class_code(current_token, 'concurrent@example.invalid', other_code) is None,
          'a closed class does not accept new registration entry')
finally:
    for iid in intake_ids:
        execute('DELETE FROM training_classes WHERE intake_id=%s', (iid,))
        execute("DELETE FROM audit_logs WHERE entity_type='corporate_intake' AND entity_id=%s", (str(iid),))
        execute('DELETE FROM corporate_intakes WHERE id=%s', (iid,))
    for rid in registration_ids:
        execute('DELETE FROM registrations WHERE id=%s', (rid,))
    for bid in batch_ids:
        execute('DELETE FROM batches WHERE id=%s', (bid,))
    for uid in user_ids:
        execute('DELETE FROM users WHERE id=%s', (uid,))
    upload_sandbox.cleanup()

print(f'{passed} checks passed; isolated records removed, real database/uploads untouched.')
