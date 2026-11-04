"""Account-bound pricing: duplicate emails must not choose another application.

All writes target powerwize_test; gateway and email transports are mocked.
"""
import os
import sys

sys.path.insert(0,os.path.dirname(__file__))
from _testdb import use_test_db, assert_isolated
use_test_db(recreate=True)
os.environ['MAIL_TRANSPORT']='mock'
os.environ['PAYMONGO_MOCK']='1'
os.environ['PAYMONGO_PUBLIC_KEY']='pk_test_pricing'
sys.path.insert(0,os.path.join(os.path.dirname(__file__),'..','src'))

import uuid
from datetime import datetime,timedelta,date
from unittest.mock import patch
from app import app
from db import (get_db,dict_cur,get_registration_for_user,get_registration_by_email,
                get_unpaid_trainees,get_user_training_type,create_discount_code,
                create_corporate_payment,get_corporate_payment,
                REGISTRATION_INSERT_SQL,registration_insert_params)
from pricing import calculate_fee
import payment_bp as payment


def sql(statement,params=(),one=False):
    c=get_db();cur=dict_cur(c)
    try:
        cur.execute(statement,params)
        rows=cur.fetchall() if cur.description else []
        c.commit()
        return (dict(rows[0]) if rows else None) if one else [dict(r) for r in rows]
    finally:
        cur.close();c.close()


checks=0
def check(name,condition):
    global checks
    assert condition,name
    checks+=1
    print('PASS: '+name)


def registration(email,mode='Online via Zoom, 7 days',program='training',days=1):
    rid=uuid.uuid4().hex[:8].upper()
    e={'id':rid,'form_type':program,'form_label':'Training','full_name':'Pricing Trainee',
       'email':email,'training_type':mode,'submitted_at':datetime.now()+timedelta(days=days)}
    sql(REGISTRATION_INSERT_SQL,registration_insert_params(e))
    sql("UPDATE registrations SET status='accepted',selfie_reviewed_at=NOW(),selfie_outcome='approved',documents_purged_at=NOW() WHERE id=%s",(rid,))
    return rid


def account(email,rid=None):
    return sql("""INSERT INTO users(role,fname,lname,email,password_hash,registration_id)
                  VALUES('trainee','Pricing','Trainee',%s,'x',%s) RETURNING id""",(email,rid),one=True)['id']


def client(uid,email='stale-or-forged@session.test'):
    c=app.test_client()
    with c.session_transaction() as s:
        s['user_id'],s['user_role'],s['user_email']=uid,'trainee',email
    return c


app.config['WTF_CSRF_ENABLED']=False
print('Isolated database: '+assert_isolated())
email='same-account@pricing.test'
online=registration(email,days=0)
uid=account(email,online)
hybrid=registration(email,'Hybrid, 5 days online + 2 days face to face','cea_training',days=2)
c=client(uid,email)
check('fixture reproduces old newest-email lookup',get_registration_by_email(email)['training_type'].startswith('Hybrid'))
check('account lookup keeps original registration',get_registration_for_user(uid)['id']==online)
check('published fee follows linked Online registration',payment._base_fee(uid)['total']==18000)
check('discount program follows linked CEM rather than newer CEA',get_user_training_type(uid)=='training')
page=c.get('/payment')
check('individual payment renders correct fee',page.status_code==200 and '18,000.00' in page.get_data(as_text=True))
check('individual payment no longer renders Hybrid amount','19,500.00' not in page.get_data(as_text=True))
check('stale session email cannot select another registration',client(uid).get('/payment').status_code==200 and payment._base_fee(uid)['total']==18000)
with c.session_transaction() as s:s.pop('user_email',None)
check('missing session email does not alter account pricing','18,000.00' in c.get('/payment').get_data(as_text=True))
picker=next(t for t in get_unpaid_trainees() if t['id']==uid)
check('manual corporate picker uses the same registration',picker['reg_training_type'].startswith('Online') and picker['form_type']=='training')
check('manual and individual fees agree',calculate_fee(picker['form_type'],picker['reg_training_type'])['total']==payment._base_fee(uid)['total'])

# The charged amount is tested at both gateway boundaries, not just in HTML.
with patch.object(payment.paymongo,'create_payment_intent',return_value={'id':'pi_pricing_card','client_key':'test'}) as gateway:
    result=c.post('/payment/card/initiate',json={'amount_centavos':1950000})
    check('card initiation succeeds with correct fee',result.status_code==200)
    check('card gateway receives exactly 1800000 centavos',gateway.call_args.kwargs['amount_centavos']==1800000)
with patch.object(payment.paymongo,'create_qrph_intent',return_value={'pi_id':'pi_pricing_qr','qr_image':'test'}) as gateway:
    result=c.post('/payment/qrph/initiate',json={'amount_centavos':1950000})
    check('QR initiation succeeds with correct fee',result.status_code==200)
    check('QR gateway receives the same 1800000 centavos',gateway.call_args.kwargs['amount_centavos']==1800000)

create_discount_code('CEM-PRICING',10,date.today()+timedelta(days=5),100,training_type='training')
create_discount_code('CEA-PRICING',10,date.today()+timedelta(days=5),100,training_type='cea_training')
result=c.post('/payment/discount/apply',json={'code':'CEM-PRICING'})
check('discount is validated against linked registration program',result.status_code==200)
check('discount applies to 18000 rather than 19500',result.get_json()['base_total']==18000 and result.get_json()['amount_due']==16200)
with patch.object(payment.paymongo,'create_payment_intent',return_value={'id':'pi_pricing_discount','client_key':'test'}) as gateway:
    check('discounted card initiation succeeds',c.post('/payment/card/initiate').status_code==200)
    check('discounted gateway amount is correct',gateway.call_args.kwargs['amount_centavos']==1620000)
check('discount for newer unrelated program refused',c.post('/payment/discount/apply',json={'code':'CEA-PRICING'}).status_code==400)
check('removing discount restores linked fee',c.post('/payment/discount/remove').get_json()['amount_due']==18000)

# Company overrides remain their own invoice amount; do not copy them into
# the person's published fee or rewrite any old invoice during a page view.
cid,_=create_corporate_payment('Pricing Co','HR','hr@pricing.test','',
    [{'user_id':uid,'training_type':'Online','form_type':'training','price_php':18000,'price_label':'Online'}],
    18000,10000,'Agreed meeting',1000000,datetime.now()+timedelta(days=1),None)
invoice_before=get_corporate_payment(cid=cid)
check('viewing individual payment leaves company override unchanged',c.get('/payment').status_code==200 and get_corporate_payment(cid=cid)==invoice_before)
check('company charge remains 10000 rather than individual list fee',invoice_before['amount_centavos']==1000000)

sql("UPDATE users SET payment_status='paid' WHERE id=%s",(uid,))
portal=c.get('/portal')
check('paid portal shows linked registration mode',portal.status_code==200 and 'Online via Zoom, 7 days' in portal.get_data(as_text=True))
check('paid portal does not show newer Hybrid application','Hybrid, 5 days' not in portal.get_data(as_text=True))
sql("UPDATE users SET payment_status='unpaid',email='changed@pricing.test' WHERE id=%s",(uid,))
check('account email change cannot detach registration price',get_registration_for_user(uid)['id']==online and payment._base_fee(uid)['total']==18000)

# Older unlinked accounts are usable only when registration identity is
# unambiguous. No inferred registration_id is written during these reads.
legacy_email='Legacy@pricing.test'
legacy_reg=registration(legacy_email.lower(),days=0)
legacy=account(legacy_email)
check('one unambiguous legacy email match remains supported',get_registration_for_user(legacy)['id']==legacy_reg)
check('legacy payment uses published fee','18,000.00' in client(legacy).get('/payment').get_data(as_text=True))
check('legacy lookup does not write an inferred account link',sql('SELECT registration_id FROM users WHERE id=%s',(legacy,),one=True)['registration_id'] is None)
registration(legacy_email.lower(),'Hybrid',days=4)
check('ambiguous legacy email match is not guessed',get_registration_for_user(legacy) is None)
legacy_client=client(legacy)
result=legacy_client.get('/payment')
check('ambiguous legacy payment shows actionable review page',result.status_code==409 and 'Payment needs review' in result.get_data(as_text=True))
check('ambiguous corporate picker has no invented program',next(t for t in get_unpaid_trainees() if t['id']==legacy)['form_type'] is None)
missing=account('no-registration@pricing.test')
unpriced_reg=registration('unpriced@pricing.test',mode='Unknown delivery mode')
unpriced=account('unpriced@pricing.test',unpriced_reg)
for who,label in [(legacy,'ambiguous'),(missing,'missing'),(unpriced,'unpriced')]:
    bad=client(who)
    with patch.object(payment.paymongo,'create_payment_intent') as card,patch.object(payment.paymongo,'create_qrph_intent') as qr:
        check(label+' registration cannot start card payment',bad.post('/payment/card/initiate').status_code==409)
        check(label+' registration cannot start QR payment',bad.post('/payment/qrph/initiate').status_code==409)
        check(label+' registration causes zero gateway calls',not card.called and not qr.called)

check('original registration remains unchanged',get_registration_for_user(uid)['id']==online)
print(f'\nAccount pricing: {checks}/{checks} passed')
