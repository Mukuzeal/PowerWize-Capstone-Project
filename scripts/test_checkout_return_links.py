"""Checkout return after payable-link rotation; isolated DB and mocked gateway.

No network requests, mail delivery, real payments or blockchain writes.
"""
import os
import sys
sys.path.insert(0,os.path.dirname(__file__))
from _testdb import use_test_db,assert_isolated
use_test_db(recreate=True)
os.environ['MAIL_TRANSPORT']='mock'
os.environ['PAYMONGO_MOCK']='1'
sys.path.insert(0,os.path.join(os.path.dirname(__file__),'..','src'))

import json
import secrets
import uuid
from contextlib import ExitStack
from datetime import datetime,timedelta
from unittest.mock import patch
from app import app
from db import (get_db,dict_cur,create_corporate_payment,get_corporate_payment,
                issue_pay_token,payment_by_token,revoke_pay_token,
                reserve_attempt,record_session,get_attempts,attempt_for_return_token,
                mark_corporate_paid,mark_attempt_paid)
import paymongo
import admin.corporate as corporate


checks=0
def check(name,ok):
    global checks
    assert ok,name
    checks+=1
    print('PASS: '+name)


def sql(statement,params=(),one=False):
    c=get_db();cur=dict_cur(c)
    try:
        cur.execute(statement,params)
        rows=cur.fetchall() if cur.description else []
        c.commit()
        return (dict(rows[0]) if rows else None) if one else [dict(r) for r in rows]
    finally:
        cur.close();c.close()


def fixture():
    uid=sql("""INSERT INTO users(role,fname,lname,email,password_hash)
               VALUES('trainee','Return','Trainee',%s,'x') RETURNING id""",
            (uuid.uuid4().hex+'@return.test',),one=True)['id']
    cid,ref=create_corporate_payment('Return Company','HR','hr@return.test','',
        [{'user_id':uid,'training_type':'Online','form_type':'training','price_php':18000,'price_label':'Online'}],
        18000,10000,'Company agreement',1000000,datetime.now()+timedelta(days=1),None)
    old,version=issue_pay_token(cid)
    payload={'line_items':[],'success_url':'https://demo.example/pay/corporate/'+old+'/return',
             'cancel_url':'https://demo.example/pay/corporate/'+old,'metadata':{'reference':ref}}
    a,error=reserve_attempt(cid,1000000,ref,'test',payload)
    assert a,error
    session_id='cs_return_'+uuid.uuid4().hex
    record_session(a['attempt_ref'],session_id,'https://checkout.paymongo.com/return-fixture')
    current,new_version=issue_pay_token(cid)
    return cid,uid,old,current,a['attempt_ref'],session_id


def session(session_id,amount=1000000,status='paid',currency='PHP',livemode=False):
    return {'id':session_id,'livemode':livemode,'payments':[
        {'id':'pay_'+uuid.uuid4().hex,'status':status,'amount':amount,'currency':currency,'type':'card'}]}


app.config['WTF_CSRF_ENABLED']=True
print('Isolated database: '+assert_isolated())
client=app.test_client()
with ExitStack() as stack:
    stack.enter_context(patch('requests.sessions.Session.request',side_effect=AssertionError('No external network allowed')))
    stack.enter_context(patch.object(paymongo,'MOCK_GATEWAY',False))
    anchor=stack.enter_context(patch.object(corporate,'_anchor_receipt',return_value=False))
    cid,uid,old,current,ref,cs=fixture()
    callback='/pay/corporate/'+old+'/return'
    check('rotated payable token is invalid',payment_by_token(old)[0] is None)
    check('stored callback identifies its original attempt',attempt_for_return_token(old)['attempt_ref']==ref)
    check('new payable token remains active',payment_by_token(current)[0]['id']==cid)
    payload_before=get_attempts(cid)[0]['request_payload']
    with patch.object(paymongo,'retrieve_checkout_session',return_value=session(cs,status='pending')) as gateway:
        response=client.get(callback)
        check('old callback opens status page after rotation',response.status_code==200)
        check('redirect alone does not claim payment',b'Payment received' not in response.data and b'Not confirmed yet' in response.data)
        check('callback queries exact stored gateway session',gateway.call_args.args==(cs,))
        check('old return page does not re-enable invoice payment link',b'Back to invoice' not in response.data)
    check('old payable page remains rejected',client.get('/pay/corporate/'+old).status_code==404)
    check('old status API remains rejected',client.get('/pay/corporate/'+old+'/status').status_code==404)
    check('invalid payment page has payment-specific wording',b'Payment link unavailable' in client.get('/pay/corporate/'+old).data and b'No account was set up' not in client.get('/pay/corporate/'+old).data)
    check('pending invoice stays unpaid',get_corporate_payment(cid=cid)['status']=='pending')
    with patch.object(paymongo,'retrieve_checkout_session',return_value=session(cs)):
        response=client.get(callback)
        check('verified payment through old callback displays receipt',response.status_code==200 and b'Payment received' in response.data)
    check('validated callback settles invoice',get_corporate_payment(cid=cid)['status']=='paid')
    check('correct company override is retained',get_corporate_payment(cid=cid)['amount_centavos']==1000000 and b'10,000.00' in response.data)
    check('trainee paid flag updated by existing settlement transaction',sql('SELECT payment_status FROM users WHERE id=%s',(uid,),one=True)['payment_status']=='paid')
    check('immutable checkout request remains unchanged',get_attempts(cid)[0]['request_payload']==payload_before)
    with patch.object(paymongo,'retrieve_checkout_session',side_effect=AssertionError('Paid invoice must not be charged or queried again')):
        check('repeat return displays authoritative paid receipt',client.get(callback).status_code==200 and b'Payment received' in client.get(callback).data)
    check('rotation did not create another checkout attempt',len(get_attempts(cid))==1)
    check('old callback never reveals new payable token',current.encode() not in response.data)

    # A paid webhook may have arrived before the browser returns.
    paid,_,pold,_,pref,pcs=fixture()
    assert mark_corporate_paid(cid=paid)
    mark_attempt_paid(pref,'pay_already_confirmed')
    r=client.get('/pay/corporate/'+pold+'/return')
    check('already-paid rotated checkout returns receipt',r.status_code==200 and b'Payment received' in r.data)
    check('receipt supports HTTPS form checks',r.headers['Referrer-Policy']=='same-origin' and r.headers['Cache-Control']=='no-store')
    revoke_pay_token(paid)
    check('explicit invoice-link revocation still blocks callback',client.get('/pay/corporate/'+pold+'/return').status_code==404)

    # Same settlement checks apply to the recovery return path.
    for label,overrides in [('wrong amount',{'amount':1950000}),('wrong currency',{'currency':'USD'}),('wrong environment',{'livemode':True}),('wrong session',{'session_id':'cs_not_ours'})]:
        bad,_,token,_,_,session_id=fixture()
        values={'session_id':session_id};values.update(overrides)
        with patch.object(paymongo,'retrieve_checkout_session',return_value=session(**values)):
            r=client.get('/pay/corporate/'+token+'/return')
        check(label+' cannot settle return',get_corporate_payment(cid=bad)['status']=='pending' and b'Payment received' not in r.data)
    for state in ('cancelled','expired'):
        closed,_,token,_,_,session_id=fixture()
        sql('UPDATE corporate_payments SET status=%s WHERE id=%s',(state,closed))
        with patch.object(paymongo,'retrieve_checkout_session',return_value=session(session_id)):
            r=client.get('/pay/corporate/'+token+'/return')
        check(state+' invoice is not revived by return',get_corporate_payment(cid=closed)['status']==state and b'Payment received' not in r.data and b'Do not pay again' in r.data)
        check(state+' late money is flagged for reconciliation',get_corporate_payment(cid=closed)['needs_attention_at'] is not None)

    unknown=secrets.token_urlsafe(32)
    check('unknown return token rejected',client.get('/pay/corporate/'+unknown+'/return').status_code==404)
    check('invoice reference cannot authorize return',client.get('/pay/corporate/'+get_corporate_payment(cid=cid)['reference']+'/return').status_code==404)
    # A matching string in metadata must never authorize a callback.
    other,_,_,_,oref,_=fixture()
    path='/pay/corporate/'+unknown+'/return'
    sql('UPDATE corporate_payment_attempts SET request_payload=%s WHERE attempt_ref=%s',
        (json.dumps({'success_url':'https://demo.example/other','metadata':{'url':path}}),oref))
    check('token appearing only in metadata is refused',attempt_for_return_token(unknown) is None)
    for saved in ['https://demo.example/prefix'+path,'https://demo.example/préfix'+path,'https://demo.example'+path+'?other=1','https://demo.example'+path+'#other','not valid JSON '+path]:
        raw=saved if saved.startswith('not valid') else json.dumps({'success_url':saved})
        sql('UPDATE corporate_payment_attempts SET request_payload=%s WHERE attempt_ref=%s',(raw,oref))
        check('nonmatching or malformed return payload refused',attempt_for_return_token(unknown) is None)
    duplicate,_,_,_,duplicate_ref,_=fixture()
    for aref in (oref,duplicate_ref):
        sql('UPDATE corporate_payment_attempts SET request_payload=%s WHERE attempt_ref=%s',
            (json.dumps({'success_url':'https://demo.example'+path}),aref))
    check('callback shared by different invoices is refused',attempt_for_return_token(unknown) is None)

    # Browser rendering of the exact paid + rotated-link case.
    from werkzeug.serving import make_server,WSGIRequestHandler
    from playwright.sync_api import sync_playwright
    import threading
    class Quiet(WSGIRequestHandler):
        def log(self,*args,**kwargs):pass
    srv=make_server('127.0.0.1',0,app,threaded=True,request_handler=Quiet)
    threading.Thread(target=srv.serve_forever,daemon=True).start()
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch()
            ctx=browser.new_context()
            base=f'http://127.0.0.1:{srv.server_port}'
            ctx.route('**/*',lambda route:route.continue_() if route.request.url.startswith(base+'/') else route.fulfill(status=200,body='',content_type='text/plain'))
            page=ctx.new_page();errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            r=page.goto(base+callback,wait_until='networkidle')
            check('browser Return to merchant opens receipt after rotation',r.status==200 and page.get_by_role('heading',name='Payment received',exact=True).count()==1)
            check('browser receipt contains no account-setup error', 'No account was set up' not in page.locator('body').inner_text())
            check('no uncaught browser exceptions',not errors)
            browser.close()
    finally:srv.shutdown()
print(f'\nCheckout return links: {checks}/{checks} passed')
