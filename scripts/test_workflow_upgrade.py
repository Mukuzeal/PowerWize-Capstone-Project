"""Representative pre-workflow schema upgrade with real legacy rows, isolated.

Reconstructs the previous constraints/columns before calling the new init_db.
No email ownership inference, grade loss, or repeated NULL-history backfill.
"""
import os
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'scripts'))
os.environ['MAIL_TRANSPORT']='mock';os.environ['PAYMONGO_MOCK']='1'
from _testdb import use_test_db,assert_isolated
use_test_db(recreate=True)
sys.path.insert(0,str(ROOT/'src'))
from db import init_db,get_db,dict_cur,get_registration_for_user,get_corporate_items,get_document_reviews,lms_get_progress
init_db()

def sql(statement,params=(),one=False):
    conn=get_db();cur=dict_cur(conn)
    try:
        cur.execute(statement,params)
        rows=[dict(r) for r in cur.fetchall()] if cur.description else []
        conn.commit()
        return (rows[0] if rows else None) if one else rows
    finally:cur.close();conn.close()

checks=0
def check(name,condition):
    global checks
    assert condition,name
    checks+=1;print('PASS: '+name,flush=True)

for rid,email in [('UPGRADE1','original@upgrade.test'),('UPGRADE2','ambiguous@upgrade.test'),('UPGRADE3','ambiguous@upgrade.test')]:
    sql("""INSERT INTO registrations(id,form_type,form_label,submitted_at,full_name,email,training_type,status,is_qualified)
        VALUES(%s,'training','CEM',NOW(),'Legacy application',%s,'Online','accepted',0)""",(rid,email))
OWNER=sql("""INSERT INTO users(role,fname,lname,email,password_hash,registration_id,payment_status)
    VALUES('trainee','Original','Account','original@upgrade.test','unchanged','UPGRADE1','paid') RETURNING id""",one=True)['id']
UNLINKED=sql("""INSERT INTO users(role,fname,lname,email,password_hash)
    VALUES('trainee','Unlinked','Account','ambiguous@upgrade.test','unchanged') RETURNING id""",one=True)['id']
ADMIN=sql("INSERT INTO users(role,fname,lname,email,password_hash) VALUES('admin','Upgrade','Reviewer','reviewer@upgrade.test','unchanged') RETURNING id",one=True)['id']
MID=sql("INSERT INTO lms_modules(instructor_id,title,training_type) VALUES(%s,'Original module','training') RETURNING id",(ADMIN,),True)['id']
sql('INSERT INTO lms_progress(user_id,module_id,completed,exam_grade) VALUES(%s,%s,1,94)',(OWNER,MID))
sql("INSERT INTO lms_certificates(user_id,cert_id,issued_at) VALUES(%s,'upgrade-certificate',NOW()-INTERVAL '1 day')",(OWNER,))
sql("INSERT INTO payments(user_id,amount_php,method,paymongo_id,status) VALUES(%s,18000,'card','upgrade-payment','paid')",(OWNER,))
CID=sql("""INSERT INTO corporate_payments(reference,company_name,contact_person,list_total_php,amount_centavos,expires_at,status)
    VALUES('CORP-UPGRADE','Legacy Company','HR',18000,1800000,NOW()+INTERVAL '1 day','paid') RETURNING id""",one=True)['id']
sql("""INSERT INTO corporate_payment_items(corporate_payment_id,user_id,training_type,form_type,price_php)
    VALUES(%s,%s,'Online','training',18000)""",(CID,OWNER))
sql("INSERT INTO registration_document_reviews(reg_id,field,sha256,outcome,note) VALUES('UPGRADE1','photo_id',%s,'accepted','deleted')",('a'*64,))

# Explicitly restore the columns and unique constraints of the preceding model.
for table in ('lms_progress','lms_quiz_attempts','lms_exam_submissions','lms_certificates','payments'):
    sql(f'ALTER TABLE {table} DROP COLUMN registration_id')
sql('ALTER TABLE lms_progress ADD CONSTRAINT uq_user_module UNIQUE(user_id,module_id)')
for column in ('registration_id','trainee_name','trainee_email'):
    sql('ALTER TABLE corporate_payment_items DROP COLUMN '+column)
sql('ALTER TABLE corporate_payment_items ALTER COLUMN user_id SET NOT NULL')
sql('ALTER TABLE registration_document_reviews DROP COLUMN review_version')
sql('ALTER TABLE registration_document_reviews ADD CONSTRAINT uq_regdoc_review UNIQUE(reg_id,field)')
sql('ALTER TABLE registrations DROP COLUMN review_version')
sql('ALTER TABLE corporate_intakes DROP COLUMN registration_delivery_secret')
sql('ALTER TABLE corporate_notifications ALTER COLUMN intake_id SET NOT NULL')
for table in ('trainee_enrolments','registration_corrections','registration_retired_uploads','registration_review_history'):
    sql('DROP TABLE '+table)
check('fixture has the prior unscoped progress constraint',bool(sql("SELECT 1 FROM pg_constraint WHERE conname='uq_user_module'")))

init_db()
check('upgrade preserves the original account pointer',get_registration_for_user(OWNER)['id']=='UPGRADE1')
check('only explicit original ownership is backfilled',sql('SELECT user_id FROM trainee_enrolments WHERE registration_id=%s',('UPGRADE1',),True)['user_id']==OWNER and len(sql('SELECT * FROM trainee_enrolments'))==1)
check('ambiguous matching email never becomes ownership',not sql('SELECT * FROM trainee_enrolments WHERE user_id=%s',(UNLINKED,)))
check('original grade and completion remain on original enrolment',lms_get_progress(OWNER,MID)['exam_grade']==94 and lms_get_progress(OWNER,MID)['completed']==1)
check('original certificate is scoped without changing its id',sql("SELECT registration_id FROM lms_certificates WHERE cert_id='upgrade-certificate'",one=True)['registration_id']=='UPGRADE1')
check('original payment is scoped without changing amount',sql("SELECT registration_id,amount_php FROM payments WHERE paymongo_id='upgrade-payment'",one=True)=={'registration_id':'UPGRADE1','amount_php':18000})
check('invoice coverage and price survive upgrade',get_corporate_items(CID)[0]['registration_id']=='UPGRADE1' and get_corporate_items(CID)[0]['price_php']==18000)
check('prior document checksum and qualification are retained',get_document_reviews('UPGRADE1')[0]['sha256']=='a'*64 and sql("SELECT is_qualified FROM registrations WHERE id='UPGRADE1'",one=True)['is_qualified']==0)
check('no historical identity approval is invented',sql("SELECT selfie_reviewed_at,selfie_outcome FROM registrations WHERE id='UPGRADE1'",one=True)=={'selfie_reviewed_at':None,'selfie_outcome':None})

# A later explicit link must not relabel previously unknown learning history.
sql('INSERT INTO lms_progress(user_id,module_id,exam_grade) VALUES(%s,%s,52)',(UNLINKED,MID))
sql("UPDATE users SET registration_id='UPGRADE2' WHERE id=%s",(UNLINKED,))
init_db()
check('restart does not infer enrolment for previously unscoped work',sql('SELECT registration_id FROM lms_progress WHERE user_id=%s',(UNLINKED,),True)['registration_id'] is None)
before=sql('SELECT user_id,module_id,registration_id,exam_grade,completed FROM lms_progress ORDER BY id')
init_db()
check('repeated upgrade leaves all progress history unchanged',sql('SELECT user_id,module_id,registration_id,exam_grade,completed FROM lms_progress ORDER BY id')==before)
print(f'\nWorkflow upgrade: {checks}/{checks} passed; '+assert_isolated())
