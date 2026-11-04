"""Real browser HTTPS company forms through a local forwarded-host proxy.

The browser uses local TLS with forwarded ngrok-style headers.
CSRF token and strict HTTPS referrer checks remain enabled. Database writes
are isolated; mail and gateway are mocked; no real uploads or payments occur.
"""
import os
import sys
sys.path.insert(0,os.path.dirname(__file__))
from _testdb import use_test_db, assert_isolated
use_test_db(recreate=True)
os.environ['MAIL_TRANSPORT']='mock'
os.environ['PAYMONGO_MOCK']='1'
sys.path.insert(0,os.path.join(os.path.dirname(__file__),'..','src'))

import re
import threading
from datetime import datetime,timedelta
from unittest.mock import patch
from flask import request
from werkzeug.serving import make_server,WSGIRequestHandler
from playwright.sync_api import sync_playwright
from app import app
from db import create_intake,add_slot,issue_registration_token,list_classes,get_slots
import company_bp as company
import corporate_public_bp as public

app.config['WTF_CSRF_ENABLED']=True
app.config['WTF_CSRF_SSL_STRICT']=True
checks=0
def check(name,ok):
    global checks
    assert ok,name
    checks+=1
    print('PASS: '+name)

print('Isolated database: '+assert_isolated())
fixtures=[]
for program in ('training','cea_training','cem_renewal','cea_renewal','gemp_lgu','gemp_oge'):
    iid=create_intake('HTTPS Company '+program,'HR','hr@example.invalid','',program,'Online',None)
    email=program+'@example.invalid'
    add_slot(iid,'HTTPS Trainee',email)
    token=issue_registration_token(iid)
    fixtures.append((iid,email,token,list_classes(intake_id=iid)[0]['join_code']))

origin='https://powerwize-https.test'
path='/company/register/'+fixtures[0][2]
# Establish the original failure without changing app CSRF configuration.
c=app.test_client()
get=c.get(path,base_url=origin)
csrf=re.search(r'name="csrf_token" value="([^"]+)"',get.get_data(as_text=True)).group(1)
missing=c.post(path,base_url=origin,data={'csrf_token':csrf,'action':'enter_class','email':fixtures[0][1],'class_code':fixtures[0][3]})
check('HTTPS strict check still rejects a missing referrer',missing.status_code==400 and b'referrer header is missing' in missing.data)
bad=c.post(path,base_url=origin,headers={'Referer':'https://foreign.example/'},data={'csrf_token':csrf,'action':'enter_class','email':fixtures[0][1],'class_code':fixtures[0][3]})
check('cross-origin HTTPS POST is still rejected',bad.status_code==400)
no_token=c.post(path,base_url=origin,headers={'Referer':origin+path},data={'action':'enter_class','email':fixtures[0][1],'class_code':fixtures[0][3]})
check('same-origin form without CSRF token remains rejected',no_token.status_code==400)

class QuietHandler(WSGIRequestHandler):
    def log(self,*args,**kwargs):
        pass

def forwarded_proxy(environ,start_response):
    # Like ngrok: the application sees an HTTP upstream plus the original
    # HTTPS host/protocol. TLS terminates before this WSGI application.
    environ['wsgi.url_scheme']='http'
    environ['HTTP_X_FORWARDED_PROTO']='https'
    environ['HTTP_X_FORWARDED_HOST']=environ['HTTP_HOST']
    return app(environ,start_response)

srv=make_server('127.0.0.1',0,forwarded_proxy,threaded=True,
                request_handler=QuietHandler,ssl_context='adhoc')
threading.Thread(target=srv.serve_forever,daemon=True).start()
origin=f'https://127.0.0.1:{srv.server_port}'
errors=[]
requests_seen=[]
external_referrers=[]

try:
    with sync_playwright() as pw:
        browser=pw.chromium.launch()
        ctx=browser.new_context(ignore_https_errors=True)
        def proxy(route):
            req=route.request
            if req.url.startswith(origin+'/'):
                headers=req.all_headers()
                requests_seen.append((req.method,headers.get('referer'),req.url))
                route.continue_()
            else:
                external_referrers.append(req.headers.get('referer'))
                route.fulfill(status=200,body='',headers={'Access-Control-Allow-Origin':'*'},content_type='text/plain')
        ctx.route(re.compile(r'^https?://'),proxy)
        page=ctx.new_page()
        page.on('pageerror',lambda e:errors.append(str(e)))
        # Browser reproduction of the old header: the valid CSRF token is
        # sent, but the browser drops Referer and Flask rejects the form.
        original=company._no_leak
        def old_policy(body):
            resp=original(body)
            if request.endpoint=='company.company_register':
                resp.headers['Referrer-Policy']='no-referrer'
            return resp
        with patch.object(company,'_no_leak',old_policy):
            page.goto(origin+path,wait_until='networkidle')
            page.locator('#entry-class-code').fill(fixtures[0][3])
            page.locator('#entry-email').fill(fixtures[0][1])
            with page.expect_response(lambda r:r.request.method=='POST' and '/company/register/' in r.url) as pending:
                page.get_by_role('button',name='Continue to registration').click()
            check('old policy reproduces browser HTTPS failure',pending.value.status==400)
            check('browser actually omitted referrer under old policy',next(x for x in reversed(requests_seen) if x[0]=='POST')[1] is None)

        for iid,email,token,code in fixtures:
            path='/company/register/'+token
            response=page.goto(origin+path,wait_until='networkidle')
            check('HTTPS '+email.split('@')[0]+' entry uses same-origin policy',response.headers.get('referrer-policy')=='same-origin')
            page.locator('#entry-class-code').fill(code)
            page.locator('#entry-email').fill(email)
            with page.expect_response(lambda r:r.request.method=='POST' and '/company/register/' in r.url) as pending:
                page.get_by_role('button',name='Continue to registration').click()
            check('HTTPS '+email.split('@')[0]+' code/email POST succeeds',pending.value.status==302)
            page.wait_for_selector('input[name="action"][value="submit_registration"]',state='attached',timeout=5000)
            check('HTTPS '+email.split('@')[0]+' stays on company URL',page.url==origin+path)
            check('HTTPS '+email.split('@')[0]+' form binds roster email',page.locator('input[name="email"]').input_value()==email)
            # An invalid final submission must reach normal form validation,
            # not fail HTTPS CSRF; no registration or documents are written.
            result=page.evaluate("""async () => {
              const fd=new FormData();
              fd.append('csrf_token',document.querySelector('input[name=csrf_token]').value);
              fd.append('action','submit_registration');
              const r=await fetch(location.href,{method:'POST',body:fd});
              return {status:r.status,policy:r.headers.get('Referrer-Policy')};
            }""")
            check('HTTPS '+email.split('@')[0]+' upload form reaches validation',result=={'status':200,'policy':'same-origin'})
            check('validation creates no registration',all(s['registration_id'] is None for s in get_slots(iid)))
        check('fixed browser POST includes same-origin referrer',next(x for x in reversed(requests_seen) if x[0]=='POST')[1].startswith(origin+'/'))
        # The browser, not a header assertion alone, proves external requests
        # receive no token-bearing referrer.
        external_referrers.clear()
        page.evaluate("fetch('https://outside.test/pixel').then(r=>r.text())")
        check('external request receives no referrer',external_referrers and all(x is None for x in external_referrers))

        invoice={'id':999999,'reference':'CORP-HTTPS-TEST','company_name':'HTTPS Company',
                 'form_type':'training','status':'pending','amount_centavos':1800000,
                 'expires_at':datetime.now()+timedelta(days=1)}
        attempt={'status':'active','environment':'test','checkout_session_id':'cs_mock_https',
                 'checkout_url':'https://mock.paymongo.test/checkout/cs_mock_https',
                 'request_payload':{'payment_method_types':['card','qrph']}}
        with patch.object(public,'payment_by_token',return_value=(invoice,None)), \
             patch.object(public,'get_corporate_items',return_value=[]), \
             patch.object(public,'open_attempt',return_value=attempt), \
             patch.object(public,'audit_log'):
            response=page.goto(origin+'/pay/corporate/https-fixture',wait_until='networkidle')
            check('company payment page supports HTTPS same-origin POST',response.headers.get('referrer-policy')=='same-origin')
            result=page.evaluate("""async () => {
              const token=document.querySelector('meta[name=csrf-token]').content;
              const r=await fetch(location.pathname+'/connect-sandbox',{method:'POST',headers:{'X-CSRFToken':token}});
              return {status:r.status,body:await r.json()};
            }""")
            check('HTTPS payment POST passes CSRF and reaches mock guard',result['status']==409 and 'PAYMONGO_MOCK=1' in result['body']['error'])
        check('no uncaught browser exceptions',not errors)
        browser.close()
finally:
    srv.shutdown()
print(f'\nHTTPS company forms: {checks}/{checks} passed')
