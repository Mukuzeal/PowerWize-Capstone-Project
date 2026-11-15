"""Isolated company journey, secure corrections, ownership, billing and browser UX.

No production connections, external mail, payment or blockchain operations.
"""
import os
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'scripts'))
os.environ['MAIL_TRANSPORT']='mock'
os.environ['PAYMONGO_MOCK']='1'
os.environ['APP_BASE_URL']='http://localhost'
from _testdb import use_test_db, assert_isolated
use_test_db(recreate=True)
sys.path.insert(0,str(ROOT/'src'))

import ast
import io
import json
import re
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta
from unittest.mock import patch
from werkzeug.security import generate_password_hash
from werkzeug.serving import make_server
from app import app
import email_utils
from db import *
from pricing import calculate_fee

app.config.update(TESTING=True,WTF_CSRF_ENABLED=True)
sandbox=tempfile.TemporaryDirectory(prefix='powerwize-workflow-')
app.config['UPLOAD_FOLDER']=sandbox.name
app.config['LEGACY_UPLOAD_FOLDER']=sandbox.name+'/legacy'
os.makedirs(app.config['LEGACY_UPLOAD_FOLDER'])
checks=0

def check(name,ok):
    global checks
    assert ok,name
    checks+=1
    print('PASS: '+name,flush=True)

def sql(statement,params=(),one=False):
    conn=get_db();cur=dict_cur(conn)
    try:
        cur.execute(statement,params)
        rows=[dict(r) for r in cur.fetchall()] if cur.description else []
        conn.commit()
        return (rows[0] if rows else None) if one else rows
    finally:cur.close();conn.close()

def user(name,role='trainee',reg=None):
    uid=sql("""INSERT INTO users(role,fname,lname,email,password_hash,registration_id)
        VALUES(%s,%s,'Workflow',%s,%s,%s) RETURNING id""",
        (role,name,name.lower()+'@workflow.test',generate_password_hash('workflow-test-password'),reg),True)['id']
    if reg:sql('INSERT INTO trainee_enrolments(user_id,registration_id) VALUES(%s,%s)',(uid,reg))
    return uid

def registration(name,status='accepted',form='training',email=None,files=False):
    rid=uuid.uuid4().hex[:8].upper()
    sql("""INSERT INTO registrations(id,form_type,form_label,submitted_at,full_name,email,training_type,status,
        selfie_reviewed_at,selfie_outcome,documents_purged_at)
        VALUES(%s,%s,'Workflow test',NOW(),%s,%s,'Online',%s,NOW(),'approved',%s)""",
        (rid,form,name,email or name.lower().replace(' ','-')+'@workflow.test',status,None if files else datetime.now()))
    if files:
        for field in ('photo_id','resume','valid_id','selfie_with_id'):
            fname=uuid.uuid4().hex+('.pdf' if field=='resume' else '.jpg')
            Path(sandbox.name,fname).write_bytes(('temporary-'+field).encode())
            sql('UPDATE registrations SET '+field+'=%s WHERE id=%s',(fname,rid))
    return rid

def intake(name,reg=None,email=None):
    iid=create_intake(name,'Coordinator','hr@workflow.test','','training','Online',ADMIN)
    if reg:
        r=get_registration_full(reg)
        sid,_=add_slot(iid,r['full_name'],email or r['email'])
        sql('UPDATE corporate_intake_slots SET registration_id=%s,invite_used_at=NOW() WHERE id=%s',(reg,sid))
    return iid

def client(uid=None,role='trainee'):
    c=app.test_client()
    if uid:
        account=sql('SELECT * FROM users WHERE id=%s',(uid,),True)
        with c.session_transaction() as s:
            s.update(user_id=uid,user_role=role,user_email=account['email'],user_name=account['fname'])
    return c

def csrf(c,path='/auth'):
    page=c.get(path).get_data(as_text=True)
    match=re.search(r'name="csrf_token"[^>]*value="([^"]+)"',page)
    if not match:match=re.search(r'name="csrf-token"[^>]*content="([^"]+)"',page)
    assert match,'CSRF token missing'
    return match.group(1)

def post(c,path,data=None):
    return c.post(path,data=data or {},headers={'X-CSRFToken':csrf(c),'Accept':'application/json'})

def correction_token(nid):
    payload,error=notification_payload(nid,link_kind='correction')
    assert not error
    return payload['url'].rsplit('/',1)[-1]

ADMIN=user('Admin','admin')
admin=client(ADMIN,'admin')
print('Isolated database: '+assert_isolated(),flush=True)

# Approvals can be invoiced before accounts exist; no partial coverage.
RID=registration('Ana')
IID=intake('Ana Company',RID)
token=issue_registration_token(IID,ADMIN,with_class=True)
preview=admin.get(f'/admin/intake/{IID}/invoice/preview').get_json()
check('approved trainee is invoiceable without an account',preview['can_create'] and preview['lines'][0]['user_id'] is None)
response=post(admin,f'/admin/intake/{IID}/invoice')
check('invoice creation works before account activation',response.status_code==200)
CID=response.get_json()['id']
items=get_corporate_items(CID)
check('invoice preserves application identity and roster snapshot',len(items)==1 and items[0]['registration_id']==RID and items[0]['user_id'] is None and items[0]['fname']=='Ana')
check('second create cannot produce a duplicate pending invoice',post(admin,f'/admin/intake/{IID}/invoice').status_code==400)
mark_corporate_paid(cid=CID,confirmed_payment_id='pay_workflow_test')
check('payment before account activation retains the paid application',get_corporate_payment(cid=CID)['status']=='paid' and len(get_corporate_items(CID))==1)
activation,_=claim_account_invitation(RID,'ana@workflow.test',True)
trainee=client()
activated=post(trainee,'/create-account/'+activation,{'password':'chosen-test-password','confirm_password':'chosen-test-password'})
check('trainee chooses a password through the one-use activation link',activated.status_code==302)
with trainee.session_transaction() as activated_session:
    check('successful activation signs in the trainee without a second password form',activated.location=='/portal' and activated_session.get('user_role')=='trainee')
ANA=sql('SELECT id FROM users WHERE registration_id=%s',(RID,),True)['id']
check('late account activation binds the original invoice line',get_corporate_items(CID)[0]['user_id']==ANA)
check('settled company payment is recognized after activation',get_user_payment_status(ANA)=='paid')
check('spent activation token cannot create another account',get_account_token(activation)['used_at'] is not None)
learner=client(ANA)
portal=learner.get('/portal').get_data(as_text=True)
check('portal offers assigned class without another code entry','Join your assigned class' in portal and 'name="join_code"' not in portal)
check('direct class join rechecks entitlement',post(learner,'/portal/join-class',{'class_id':token['class_id']}).status_code==302 and class_gate(ANA)[0])
stranger=user('Stranger')
check('unrelated account cannot join by guessing the assigned id',post(client(stranger),'/portal/join-class',{'class_id':token['class_id']}).status_code==403)

# Existing accounts explicitly claim a new application. Email alone is insufficient.
NEW=registration('Ana Return',email='ana@workflow.test')
NEW_IID=intake('Ana Second Company',NEW)
return_token,_=claim_account_invitation(NEW,'ana@workflow.test',True)
original=get_registration_for_user(ANA)['id']
check('email match alone does not attach a new application',not sql('SELECT * FROM trainee_enrolments WHERE registration_id=%s',(NEW,)))
check('another authenticated account cannot claim the invitation',post(client(stranger),'/create-account/'+return_token).status_code==200 and not get_account_token(return_token)['used_at'])
response=post(learner,'/create-account/'+return_token)
check('existing account explicitly claims its emailed enrolment',response.status_code==302 and get_account_token(return_token)['used_at'] is not None)
check('claim preserves original registration pointer',sql('SELECT registration_id FROM users WHERE id=%s',(ANA,),True)['registration_id']==original)
check('one account retains both explicit enrolments',len(enrolments_for_user(ANA))==2)
page=learner.get('/portal').get_data(as_text=True)
check('new sponsored enrolment shows company waiting state','Your company’s payment is pending' in page and 'do not need to pay an individual' in page)
check('company-sponsored enrolment is not sent to personal checkout',learner.get('/payment').location=='/portal')
with patch('paymongo.create_payment_intent',side_effect=AssertionError('gateway must not be called')):
    check('personal card API refuses company-sponsored enrolment',post(learner,'/payment/card/initiate').status_code==409)
check('unowned enrolment selection is refused',post(learner,'/portal/enrolment',{'registration_id':registration('Someone Else')}).status_code==403)
check('trainee can switch back to an owned earlier enrolment',post(learner,'/portal/enrolment',{'registration_id':RID}).status_code==302 and 'Join your assigned class' not in learner.get('/portal').get_data(as_text=True))

# Corrections update one registration, preserve identity and send truthful notices.
CR=registration('Correction',status='pending',files=True)
CI=intake('Correction Company',CR)
before=get_registration_full(CR)
result=post(admin,f'/admin/registration/{CR}/status/needs_correction',{
    'correction_note':'Please replace the photograph.','correction_fields':['photo_id'],'review_version':'1'})
check('correction request and both notification intents are saved',result.status_code==200 and len(sql('SELECT id FROM corporate_notifications WHERE intake_id=%s',(CI,)))==2)
notice=sql("SELECT id FROM corporate_notifications WHERE intake_id=%s AND kind='trainee_correction'",(CI,),True)
CT=correction_token(notice['id'])
check('trainee receives a private correction link',any('/registration/correct/' in m['html'] and m['to']=='correction@workflow.test' for m in email_utils.SENT_MESSAGES))
check('company notice makes no false delivery or shared-edit claim',all('We have contacted them directly' not in m['html'] and 'resubmit using the same' not in m['html'] for m in email_utils.SENT_MESSAGES))
check('same correction event does not send duplicate notices',post(admin,f'/admin/registration/{CR}/status/needs_correction',{'correction_note':'Please replace the photograph.','correction_fields':['photo_id'],'review_version':'1'}).status_code==200 and len(sql('SELECT id FROM corporate_notifications WHERE intake_id=%s',(CI,)))==2)
c=client()
check('shared company code cannot edit a submitted application',enter_registration_with_class_code(issue_registration_token(CI,ADMIN), 'correction@workflow.test',list_classes(CI)[0]['join_code']) is None)
page=c.get('/registration/correct/'+CT)
check('correction page uses no-store and same-origin HTTPS referrer policy',page.headers['Cache-Control']=='no-store' and page.headers['Referrer-Policy']=='same-origin')
check('CSRF is enforced on correction submission',c.post('/registration/correct/'+CT,data={'photo_id_existing':'foreign.jpg'}).status_code==400)
check('foreign upload reference does not satisfy correction',post(c,'/registration/correct/'+CT,{'photo_id_existing':before['photo_id']}).status_code==200 and correction_access(CT) is not None)
response=post(c,'/registration/correct/'+CT,{'photo_id':(io.BytesIO(b'new temporary photograph'),'replacement.jpg')})
check('correction submits successfully','Corrections submitted' in response.get_data(as_text=True))
after=get_registration_full(CR)
check('same application and roster are retained',after['id']==CR and get_slots(CI)[0]['registration_id']==CR and sql('SELECT COUNT(*) AS n FROM registrations WHERE id=%s',(CR,),True)['n']==1)
check('only affected application gate reopened; identity approval retained',after['status']=='pending' and after['selfie_outcome']=='approved' and after['selfie_reviewed_at']==before['selfie_reviewed_at'])
check('unaffected uploads remain while review is pending',all(Path(sandbox.name,after[f]).exists() for f in ('resume','valid_id','selfie_with_id')))
check('superseded file deleted with retained checksum history',not Path(sandbox.name,before['photo_id']).exists() and bool(sql('SELECT sha256 FROM registration_document_reviews WHERE reg_id=%s',(CR,),True)['sha256']))
check('correction token is single-use',c.get('/registration/correct/'+CT).status_code==404)
check('stale application review cannot accept replacement documents',post(admin,f'/admin/registration/{CR}/status/accepted',{'review_version':'1'}).status_code==409 and get_registration_full(CR)['status']=='pending')
check('current review accepts and purges temporary uploads',post(admin,f'/admin/registration/{CR}/status/accepted',{'review_version':'2'}).status_code==200 and get_registration_full(CR)['documents_purged_at'] is not None)
check('both document revisions retain independent hashes',len([r for r in get_document_reviews(CR) if r['field']=='photo_id'])==2)
check('reviewed documents are no longer served',admin.get(f'/admin/registration/{CR}/document/resume').status_code==404)

# Expiry, rotation and identity-only corrections.
request_correction(CR,'Please retake your selfie.',['selfie_with_id'],ADMIN,'http://localhost')
n=sql("SELECT id FROM corporate_notifications WHERE kind='trainee_correction' AND intake_id=%s ORDER BY id DESC LIMIT 1",(CI,),True)
ST=correction_token(n['id'])
with c.session_transaction() as sess:
    name=uuid.uuid4().hex+'.jpg';sess['uploaded_files']=['selfie_with_id:'+name]
Path(sandbox.name,name).write_bytes(b'new selfie')
check('identity-only correction can be submitted after prior purge',post(c,'/registration/correct/'+ST,{'selfie_with_id':name}).status_code==200)
after=get_registration_full(CR)
check('selfie correction reopens only identity, preserving application acceptance',after['status']=='accepted' and after['selfie_reviewed_at'] is None and after['selfie_outcome'] is None)
post(admin,f'/admin/selfie/{CR}/approve',{'review_version':str(after['review_version'])})
check('replacement selfie purged after its review closes',not Path(sandbox.name,name).exists())
request_correction(CR,'Correct contact number.',['contact_number'],ADMIN,'http://localhost')
old_n=sql("SELECT id FROM corporate_notifications WHERE kind='trainee_correction' AND intake_id=%s ORDER BY id DESC LIMIT 1",(CI,),True)
old_t=correction_token(old_n['id'])
request_correction(CR,'Correct address.',['residence'],ADMIN,'http://localhost')
check('replacement correction invalidates prior correction link',correction_access(old_t) is None)

# Stable invitation delivery after refresh. No rotation on retry.
FR=intake('Fresh Invitation')
add_slot(FR,'Fresh Trainee','fresh@workflow.test')
first=post(admin,f'/admin/intake/{FR}/registration-link/send')
link_hash=get_intake(intake_id=FR)['registration_token_hash']
check('one Send action prepares shared link and class automatically',first.status_code==200 and len(list_classes(FR))==1)
post(admin,f'/admin/intake/{FR}/registration-link/send')
check('send after page refresh reuses link and notification intent',get_intake(intake_id=FR)['registration_token_hash']==link_hash and len(get_notifications(FR))==1)
stored=get_intake(intake_id=FR)['registration_delivery_secret']
check('recoverable invitation is encrypted, not plaintext',stored and '/company/register/' not in stored)
n=get_notifications(FR)[0]
sql("UPDATE corporate_notifications SET status='in_flight',attempt_expires_at=NOW()-INTERVAL '1 second' WHERE id=%s",(n['id'],))
check('expired send lease cannot be blindly reclaimed',begin_attempt(n['id'])[0] is None)
recover_stale_attempts()
check('expired send becomes visible uncertainty without resend',get_notification(n['id'])['status']=='uncertain')
check('uncertain invitation requires explicit retry confirmation',post(admin,f'/admin/intake/{FR}/registration-notice/{n["id"]}/retry').status_code==409)

# Instructor assignment permits teaching a shared module, never editing it.
T1=user('Assigned','employee');T2=user('Other','employee')
assign_class_instructor(token['class_id'],T1,None,ADMIN)
MID=lms_create_module(T2,'Shared company module','Teaching scope','training')
sql('UPDATE lms_modules SET is_published=1 WHERE id=%s',(MID,))
check('assigned instructor can assess its paid class member',instructor_can_assess(T1,ANA,MID))
check('unassigned shared-module owner cannot assess another company batch',not instructor_can_assess(T2,ANA,MID))
check('instructor cannot assess unrelated trainee',not instructor_can_assess(T1,stranger,MID))
check('trainer console hides unrelated trainee details','stranger@workflow.test' not in client(T1,'employee').get('/employee').get_data(as_text=True))

# Summary uses the same approvals without implying account activation is required.
panel=admin.get(f'/admin/intake/{NEW_IID}/panel').get_json()
check('workspace exposes distinct counts and billing readiness',panel['summary']['approved']==1 and panel['summary']['activated']==1 and panel['billing']['can_create'])
check('fresh schema and upgrade are repeatable',init_db() is None and init_db() is None)

# Initial batch creation is one transaction and one browser POST.
created=post(admin,'/admin/intake/new',{'company_name':'Atomic Company','contact_person':'Coordinator',
    'contact_email':'atomic@workflow.test','form_type':'training','training_type':'Online via Zoom, 7 days',
    'instructor_id':str(T1),'trainee_name':['Mara Santos','Ben Cruz'],'trainee_email':['mara@workflow.test','ben@workflow.test']})
ATOMIC=created.get_json()['id']
check('one request creates intake and whole roster',created.status_code==200 and len(get_slots(ATOMIC))==2)
check('initial instructor assignment prepares its class automatically',list_classes(ATOMIC)[0]['instructor_id']==T1)
count=sql('SELECT COUNT(*) AS n FROM corporate_intakes',one=True)['n']
bad=post(admin,'/admin/intake/new',{'company_name':'Invalid Atomic','contact_person':'Coordinator','contact_email':'atomic@workflow.test',
    'form_type':'training','instructor_id':str(stranger),'trainee_name':['Mara'],'trainee_email':['mara@workflow.test']})
check('invalid instructor rolls back intake and roster together',bad.status_code==400 and sql('SELECT COUNT(*) AS n FROM corporate_intakes',one=True)['n']==count)

with enrolment_scope(ANA,RID):
    lms_update_progress(ANA,MID,completed=True,exam_grade=94)
    _,old_cert=lms_issue_certificate(ANA,ADMIN)
    old_progress=lms_get_progress(ANA,MID)
with enrolment_scope(ANA,NEW):
    check('returning enrolment does not inherit old grades',lms_get_progress(ANA,MID) is None)
    check('returning enrolment does not inherit an old certificate',lms_get_certificate(user_id=ANA) is None)
    check('old certificate cannot exclude modules from new syllabus',MID in {m['id'] for m in lms_get_modules_for_trainee(ANA)})
    lms_update_progress(ANA,MID,exam_grade=72)
with enrolment_scope(ANA,RID):
    check('new enrolment cannot overwrite previous completion or grade',lms_get_progress(ANA,MID)['completed'] and lms_get_progress(ANA,MID)['exam_grade']==94)
    check('original certificate remains available on its own enrolment',lms_get_certificate(user_id=ANA)['cert_id']==old_cert)

RACE_REG=registration('Concurrent Invoice')
RACE_IID=intake('Concurrent Billing',RACE_REG)
with ThreadPoolExecutor(max_workers=2) as workers:
    results=list(workers.map(lambda _:create_invoice_for_intake(RACE_IID,datetime.now()+timedelta(days=1),ADMIN,calculate_fee),range(2)))
check('two simultaneous invoice requests create exactly one invoice',sum(r is not None for r,e in results)==1 and len(intake_invoices(RACE_IID))==1)

result,error=request_correction(CR,'Correct telephone number.',['contact_number'],ADMIN,'http://localhost')
correction_nid=next(n for n in result['notification_ids'] if get_notification(n)['kind']=='trainee_correction')
concurrent_token=correction_token(correction_nid)
with ThreadPoolExecutor(max_workers=2) as workers:
    results=list(workers.map(lambda _:submit_correction(concurrent_token,{'contact_number':'09170000000'}),range(2)))
check('two simultaneous corrections consume a token once',sum(r is not None for r,e in results)==1)

# An unreadable stored secret must not silently invalidate a distributed link.
unchanged=get_intake(intake_id=FR)['registration_token_hash']
with patch.dict(os.environ,{'SECRET_KEY':'a-different-test-key'}):
    result=post(admin,f'/admin/intake/{FR}/registration-link/send')
check('unreadable existing invitation refuses without rotating it',result.status_code==409 and get_intake(intake_id=FR)['registration_token_hash']==unchanged)

LIMIT=registration('Field Limit')
intent,error=request_correction(LIMIT,'Correct your contact number.',['contact_number'],ADMIN,'http://localhost')
LIMIT_TOKEN=correction_token(intent['notification_ids'][0])
bad=post(c,'/registration/correct/'+LIMIT_TOKEN,{'contact_number':'1'*200})
check('oversized correction is a validation error, not HTTP 500',bad.status_code==200 and 'too long' in bad.get_data(as_text=True) and correction_access(LIMIT_TOKEN) is not None)
good=post(c,'/registration/correct/'+LIMIT_TOKEN,{'contact_number':'09171234567','email':'attacker@workflow.test','status':'accepted'})
check('correction cannot change unrequested identity or approval fields','Corrections submitted' in good.get_data(as_text=True) and get_registration_full(LIMIT)['email']=='field-limit@workflow.test' and get_registration_full(LIMIT)['status']=='pending')
MISSING=registration('Missing Selfie')
sql('UPDATE registrations SET selfie_reviewed_at=NULL,selfie_outcome=NULL,documents_purged_at=NULL WHERE id=%s',(MISSING,))
check('missing required selfie cannot be approved by a direct POST',post(admin,f'/admin/selfie/{MISSING}/approve').status_code==409 and get_registration_full(MISSING)['selfie_reviewed_at'] is None)
PERSONAL=registration('Personal')
PERSONAL_UID=user('Personal',reg=PERSONAL)
check('unpaid individual cannot bypass payment by opening LMS directly',client(PERSONAL_UID).get('/lms/learn').status_code==302)

def browser_checks():
    from playwright.sync_api import sync_playwright
    server=make_server('127.0.0.1',0,app,threaded=True)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    origin=f'http://127.0.0.1:{server.server_port}'
    serializer=app.session_interface.get_signing_serializer(app)
    cookie=serializer.dumps({'user_id':ADMIN,'user_role':'admin','user_name':'Admin','user_email':'admin@workflow.test'})
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True)
            context=browser.new_context(viewport={'width':1280,'height':900})
            context.add_cookies([{'name':app.config['SESSION_COOKIE_NAME'],'value':cookie,'url':origin}])
            context.add_init_script("window.Swal={fire:()=>Promise.resolve({isConfirmed:false}),mixin:()=>({fire:()=>{}})};window.Chart=function(el,o){this.data=o.data;this.update=()=>{};};window.Chart.defaults={};window.flatpickr=()=>({selectedDates:[]});")
            context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin) else route.fulfill(status=200,body=''))
            page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(origin+'/admin');page.evaluate(f'openIntake({FR})')
            page.get_by_role('tab',name='Trainees & review').wait_for()
            check('browser displays four workflow tabs',page.locator('[data-ik-tab]').count()==4)
            page.get_by_role('button',name='Send registration invitation to company',exact=True).click()
            page.wait_for_function("document.querySelector('#ik-registration-send-out').textContent.trim().length > 0")
            check('failed invitation send remains visible after refresh',page.locator('#ik-registration-send-out').inner_text().strip() != '')
            page.get_by_role('tab',name='Trainees & review').click()
            page.locator('#ik-section-trainees details').evaluate('(el)=>el.open=true')
            page.locator('#ik-more input[data-trainee-name]').fill('Unsaved trainee')
            page.evaluate('loadIntake()')
            check('workspace retains selected tab and unsaved roster input',page.locator('[data-ik-tab=trainees]').get_attribute('aria-selected')=='true' and page.locator('#ik-more input[data-trainee-name]').input_value()=='Unsaved trainee')
            page.reload();page.evaluate(f'openIntake({IID})')
            page.get_by_role('tab',name='Billing',exact=True).click()
            page.get_by_role('button',name='Open invoice',exact=True).first.click()
            page.locator('#ik-billing-detail #corp-hp').wait_for()
            check('invoice operates inside the company workspace',page.locator('#intake-overlay').evaluate('(el)=>el.classList.contains("open")') and not page.locator('#corp-overlay').evaluate('(el)=>el.classList.contains("open")'))
            page.get_by_role('tab',name='Trainees & review').click()
            page.get_by_role('button',name='Review requirements',exact=True).click()
            page.locator('#ik-correction-form').wait_for()
            check('review combines application and identity controls',page.get_by_role('button',name='Accept application',exact=True).is_visible() and page.get_by_text('Identity decision',exact=True).is_visible())
            page.locator('#intake-overlay .docs-box').screenshot(path=str(ROOT/'docs'/'company-workspace-preview.png'))
            assert not errors,repr(errors)
            check('browser executes without uncaught JavaScript errors',True)
            browser.close()
    finally:server.shutdown();thread.join(timeout=5)

if __name__=='__main__':
    browser_checks()
    print(f'\n{checks} workflow checks passed. Mock mail and payments; isolated database only.',flush=True)
    sandbox.cleanup()
