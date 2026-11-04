"""Company-batch instructor assignment, permission boundaries and browser flow.

Uses only powerwize_test, mock mail and mock gateway. No external operations.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from _testdb import use_test_db, assert_isolated

use_test_db(recreate=True)
os.environ['MAIL_TRANSPORT'] = 'mock'
os.environ['PAYMONGO_MOCK'] = '1'
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from app import app
from db import (get_db, dict_cur, init_db, create_intake, create_class, get_class,
                assign_class_instructor, instructor_classes, class_instructors,
                instructor_can_view_class, set_user_capability)


def sql(statement, params=(), one=False):
    c = get_db(); cur = dict_cur(c)
    try:
        cur.execute(statement, params)
        rows = cur.fetchall() if cur.description else []
        c.commit()
        return (dict(rows[0]) if rows else None) if one else [dict(r) for r in rows]
    finally:
        cur.close(); c.close()


checks = 0
def check(name, condition):
    global checks
    assert condition, name
    checks += 1
    print('PASS: '+name)


def user(role, name):
    return sql("""INSERT INTO users(role,fname,lname,email,password_hash)
                  VALUES(%s,%s,'Test',%s,'x') RETURNING id""",
               (role,name,name.lower().replace(' ','-')+'@instructor.test'),one=True)['id']


ADMIN = user('admin','Admin')
T1, T2 = user('employee','Instructor One'), user('employee','Instructor Two')
PV, ARCHIVED = user('employee','Solar Only'), user('employee','Archived Instructor')
LEARNER = user('trainee','Learner')
set_user_capability(PV,'manage_modules',False,ADMIN)
sql('UPDATE users SET archived_at=NOW() WHERE id=%s',(ARCHIVED,))
IA = create_intake('Alpha Company','HR','hr@alpha.test','','training','Online',ADMIN)
IB = create_intake('Beta Company','HR','hr@beta.test','','training','Online',ADMIN)
A, err = create_class('Alpha Batch','Online',ADMIN,intake_id=IA,form_type='training')
assert A, err
B, err = create_class('Beta Batch','Online',ADMIN,intake_id=IB,form_type='training')
assert B, err

print('Isolated database: '+assert_isolated())
check('fresh schema leaves batches unassigned', A['instructor_id'] is None)
# Simulate the immediately preceding schema with real company classes.
sql('ALTER TABLE training_classes DROP COLUMN instructor_id')
init_db()
check('upgrade adds nullable assignment without inventing an instructor', get_class(class_id=A['id'])['instructor_id'] is None)
check('upgrade preserves existing company class and join code', get_class(class_id=A['id'])['join_code'] == A['join_code'])
init_db()
check('schema rerun is idempotent', get_class(class_id=B['id'])['instructor_id'] is None)

app.config['WTF_CSRF_ENABLED'] = False
def client(uid=ADMIN,role='admin'):
    c=app.test_client()
    with c.session_transaction() as s:
        s['user_id'],s['user_role']=uid,role
    return c


adm=client()
url=f'/admin/class/{A["id"]}/instructor'
def assign(uid, expected='', path=url):
    return adm.post(path,data={'instructor_id':str(uid) if uid is not None else '',
                               'expected_instructor_id':str(expected) if expected else ''})

check('picker includes active training instructors only', {r['id'] for r in class_instructors()} == {T1,T2})
snapshot=get_class(class_id=A['id'])
r=assign(T1)
check('admin can assign instructor',r.status_code==200 and r.get_json()['changed'])
check('assignment persisted',get_class(class_id=A['id'])['instructor_id']==T1)
after=get_class(class_id=A['id']);after['instructor_id']=None
check('assignment preserves class code, roster authority and class state',after==snapshot)
audit=sql("SELECT * FROM audit_logs WHERE action='class_instructor_assigned' AND entity_id=%s",(str(A['id']),))
check('audit stores actor and old/new instructor',len(audit)==1 and audit[0]['user_id']==ADMIN and json.loads(audit[0]['details'])=={'previous_instructor_id':None,'instructor_id':T1,'intake_id':IA})
check('repeat save is idempotent',not assign(T1,T1).get_json()['changed'])
check('idempotent save adds no duplicate audit',len(sql("SELECT id FROM audit_logs WHERE action='class_instructor_assigned' AND entity_id=%s",(str(A['id']),)))==1)
check('stale save refuses to overwrite another assignment',assign(T2).status_code==409 and get_class(class_id=A['id'])['instructor_id']==T1)
check('one instructor may handle multiple company batches',assign(T1,path=f'/admin/class/{B["id"]}/instructor').status_code==200 and len(instructor_classes(T1))==2)

for bad,name in [(LEARNER,'trainee'),(ADMIN,'admin account'),(PV,'solar-only trainer'),(ARCHIVED,'archived trainer'),(2147483647,'missing account')]:
    check('refuses '+name,assign(bad,T1).status_code==400)
for raw in ('bad','-1','999999999999999999','2147483648'):
    check('invalid id refused: '+raw,adm.post(url,data={'instructor_id':raw,'expected_instructor_id':str(T1)}).status_code==400)
check('missing current assignment is refused',adm.post(url,data={'instructor_id':str(T2)}).status_code==400)
check('unknown batch returns 404',assign(T1,path='/admin/class/2147483647/instructor').status_code==404)

# Account/invoice/registration relationships are unaffected by staffing.
check('instructor not added to trainee roster',not sql('SELECT id FROM corporate_intake_slots'))
check('no payments or emails are generated',not sql('SELECT id FROM corporate_payments') and not sql('SELECT id FROM corporate_notifications'))
check('instructor account role unchanged',sql('SELECT role FROM users WHERE id=%s',(T1,),one=True)['role']=='employee')

for uid,role in [(T1,'employee'),(LEARNER,'trainee')]:
    c=client(uid,role)
    check(role+' cannot change assignment',c.post(url,data={'instructor_id':str(T2),'expected_instructor_id':str(T1)}).status_code==403)
check('anonymous cannot assign instructors',app.test_client().post(url,data={'instructor_id':T2,'expected_instructor_id':T1}).status_code==302)

# Assigned class progress is scoped separately from the existing staff console.
sql("INSERT INTO training_class_members(class_id,user_id,authorised,added_by) VALUES(%s,%s,'staff',%s)",(A['id'],LEARNER,ADMIN))
t1,t2=client(T1,'employee'),client(T2,'employee')
progress=f'/api/class/{A["id"]}/progress'
check('assigned instructor can view batch progress',t1.get(progress).status_code==200)
check('another instructor cannot guess the class id',t2.get(progress).status_code==403)
check('trainees cannot view cohort progress',client(LEARNER,'trainee').get(progress).status_code==403)
check('admin retains staff progress access',adm.get(progress).status_code==200)
check('own batch list has no other instructor batches',not instructor_classes(T2))
check('trainer console lists assigned batches',b'Alpha Batch' in t1.get('/employee').data and b'Beta Batch' in t1.get('/employee').data)
check('other instructor console omits batch details',b'Alpha Batch' not in t2.get('/employee').data)
check('trainee-assignment control was removed',b'Assign existing trainee' not in adm.get('/admin').data)

check('admin can change batch instructor',assign(T2,T1).status_code==200)
check('old instructor loses class access immediately',t1.get(progress).status_code==403)
check('new instructor gets class access',t2.get(progress).status_code==200)
set_user_capability(T2,'manage_modules',False,ADMIN)
check('revoked training remit blocks existing assignment access',t2.get(progress).status_code==403 and not instructor_classes(T2))
set_user_capability(T2,'manage_modules',None,ADMIN)
sql('UPDATE users SET archived_at=NOW() WHERE id=%s',(T2,))
check('archived instructor loses access despite old session',t2.get(progress).status_code==403)
sql('UPDATE users SET archived_at=NULL,role=\'trainee\' WHERE id=%s',(T2,))
check('changed account role loses access despite old session',t2.get(progress).status_code==403)
sql("UPDATE users SET role='employee' WHERE id=%s",(T2,))
check('admin can clear batch instructor',assign(None,T2).status_code==200 and get_class(class_id=A['id'])['instructor_id'] is None)
check('unassigned class inaccessible to instructors',t1.get(progress).status_code==403 and t2.get(progress).status_code==403)

# Audit failure must roll back the assignment, not leave unaudited staffing.
failed=False
try:
    assign_class_instructor(A['id'],T1,None,2147483647)
except Exception:
    failed=True
check('audit failure rolls back instructor change',failed and get_class(class_id=A['id'])['instructor_id'] is None)

barrier=threading.Barrier(2)
def compete(uid):
    barrier.wait()
    return assign_class_instructor(A['id'],uid,None,ADMIN)[1]
with ThreadPoolExecutor(max_workers=2) as pool:
    result=list(pool.map(compete,(T1,T2)))
check('simultaneous staff assignments have exactly one winner',sorted(result)==[200,409])
current=get_class(class_id=A['id'])['instructor_id']
assert assign(None,current).status_code==200

# Browser uses actual console scripts and CSRF. External CDNs are stubbed only
# in the browser test, so the test remains independent of network availability.
from werkzeug.serving import make_server
from flask.sessions import SecureCookieSessionInterface
from playwright.sync_api import sync_playwright
app.config['WTF_CSRF_ENABLED']=True
check('assignment endpoint enforces CSRF',assign(T1).status_code==400)
srv=make_server('127.0.0.1',0,app,threaded=True)
threading.Thread(target=srv.serve_forever,daemon=True).start()
base=f'http://127.0.0.1:{srv.server_port}'
errors=[]
try:
    with sync_playwright() as pw:
        browser=pw.chromium.launch()
        def context(uid,role):
            ctx=browser.new_context(base_url=base)
            ctx.add_init_script("""window.Swal={fire:()=>Promise.resolve({isConfirmed:false}),mixin:function(){return this;},stopTimer:()=>{},resumeTimer:()=>{}};
              window.flatpickr=()=>({selectedDates:[]});window.Chart=function(el,o){this.data=o.data;this.update=()=>{};};window.Chart.defaults={};""")
            ctx.route(re.compile(r'^https?://'),lambda route:route.continue_() if route.request.url.startswith(base+'/') else route.fulfill(status=200,body='',content_type='text/plain'))
            with app.test_request_context():
                cookie=SecureCookieSessionInterface().get_signing_serializer(app).dumps({'user_id':uid,'user_role':role,'user_name':'Instructor Test'})
            ctx.add_cookies([{'name':app.config.get('SESSION_COOKIE_NAME','session'),'value':cookie,'url':base}])
            return ctx
        ctx=context(ADMIN,'admin');page=ctx.new_page()
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto('/admin',wait_until='networkidle')
        page.evaluate("showSection('intake',document.querySelector('.nav-item'))")
        page.evaluate(f'openIntake({IA})')
        selector=f'#ik-instructor-{A["id"]}'
        page.wait_for_selector(selector)
        check('browser offers active instructors',page.locator(selector+' option').count()==3)
        page.select_option(selector,str(T1))
        page.get_by_role('button',name='Save instructor',exact=True).click()
        page.wait_for_selector(f'#ik-instructor-out-{A["id"]} .corp-note--ok')
        check('browser confirms saved instructor',get_class(class_id=A['id'])['instructor_id']==T1)
        page.reload(wait_until='networkidle')
        page.evaluate(f'openIntake({IA})')
        page.wait_for_selector(selector)
        check('assignment survives browser refresh',page.locator(selector).input_value()==str(T1))
        # Another operator assigns T2 after this browser loaded T1.
        assert assign_class_instructor(A['id'],T2,T1,ADMIN)[1]==200
        page.select_option(selector,'')
        page.get_by_role('button',name='Save instructor',exact=True).click()
        page.wait_for_selector(f'#ik-instructor-out-{A["id"]} .corp-note--err')
        check('browser shows stale-assignment refusal', 'assignment changed' in page.locator(f'#ik-instructor-out-{A["id"]}').inner_text())
        check('browser reloads the winning selection',page.locator(selector).input_value()==str(T2))
        trainer_ctx=context(T2,'employee');trainer_page=trainer_ctx.new_page()
        trainer_page.on('pageerror',lambda e:errors.append(str(e)))
        trainer_page.goto('/employee#company-batches',wait_until='networkidle')
        check('assigned instructor can open company batch pane',trainer_page.locator('#pane-company-batches').is_visible())
        check('trainer sees only assigned company batch', 'Alpha Batch' in trainer_page.locator('#pane-company-batches').inner_text() and 'Beta Batch' not in trainer_page.locator('#pane-company-batches').inner_text())
        trainer_page.locator('#pane-company-batches').get_by_role('button',name='Members & progress',exact=True).click()
        trainer_page.wait_for_selector(f'#assigned-batch-{A["id"]} table')
        check('instructor can load actual member progress', 'Learner Test' in trainer_page.locator(f'#assigned-batch-{A["id"]} table').inner_text())
        page.select_option(selector,'')
        page.get_by_role('button',name='Save instructor',exact=True).click()
        page.wait_for_selector(f'#ik-instructor-out-{A["id"]} .corp-note--ok')
        check('browser can clear instructor',get_class(class_id=A['id'])['instructor_id'] is None)
        trainer_page.locator('#pane-company-batches').get_by_role('button',name='Members & progress',exact=True).click()
        trainer_page.wait_for_function(f"document.getElementById('assigned-batch-{A['id']}').innerText.includes('no longer assigned')")
        check('open instructor page rechecks assignment on progress fetch', 'no longer assigned' in trainer_page.locator(f'#assigned-batch-{A["id"]}').inner_text())
        # Preserve the operation result even if the follow-up class GET fails.
        page.select_option(selector,str(T1))
        page.route(f'**/intake/{IA}/classes',lambda route:route.fulfill(status=503,body='Unavailable'))
        page.get_by_role('button',name='Save instructor',exact=True).click()
        page.wait_for_function("document.getElementById('ik-classes').innerText.includes('Instructor assigned')")
        check('successful assignment remains visible when refresh fails', 'Could not load classes' in page.locator('#ik-classes').inner_text())
        check('no uncaught browser errors',not errors)
        browser.close()
finally:
    srv.shutdown()
print(f'\nBatch instructor assignment: {checks}/{checks} passed')
