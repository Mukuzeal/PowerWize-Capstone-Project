"""Compare batch-panel orchestration to a pinned git revision, in powerwize_test.

Example: venv/Scripts/python.exe scripts/benchmark_company_workflow.py --baseline <commit>
Both handlers use the current database helpers/schema and identical fixture.
This measures redundant reads/request orchestration, not gateway or SMTP speed.
"""
import os
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'scripts'))
os.environ['MAIL_TRANSPORT']='mock'
os.environ['PAYMONGO_MOCK']='1'
from _testdb import use_test_db,assert_isolated
use_test_db(recreate=True)
sys.path.insert(0,str(ROOT/'src'))

import argparse
import ast
import json
import statistics
import subprocess
import time
from unittest.mock import patch
import psycopg2
from flask import session
from app import app
from db import get_db,dict_cur
import admin.intake as intake_module

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--baseline',required=True)
args=parser.parse_args()
revision=subprocess.check_output(['git','rev-parse',args.baseline],cwd=ROOT,text=True).strip()
source=subprocess.check_output(['git','show',revision+':src/admin/intake.py'],cwd=ROOT,text=True,encoding='utf-8')
node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='intake_panel')
node.decorator_list=[];node.name='baseline_panel'
namespace=dict(vars(intake_module))
exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<baseline panel>','exec'),namespace)

conn=get_db();cur=dict_cur(conn)
cur.execute("INSERT INTO users(role,fname,lname,email,password_hash) VALUES('admin','Performance','Fixture','performance@workflow.test','unused') RETURNING id")
actor=cur.fetchone()['id']
cur.execute("""INSERT INTO corporate_intakes(company_name,contact_person,contact_email,form_type,training_type,created_by)
    VALUES('Performance fixture','Coordinator','hr@workflow.test','training','Online',%s) RETURNING id""",(actor,))
iid=cur.fetchone()['id']
for index in range(100):
    reg_id=f'PERF{index:04}'
    cur.execute("""INSERT INTO registrations(id,form_type,form_label,submitted_at,full_name,email,training_type,
        status,selfie_reviewed_at,selfie_outcome,documents_purged_at) VALUES(%s,'training','CEM',NOW(),%s,%s,'Online','accepted',NOW(),'approved',NOW())""",
        (reg_id,f'Trainee {index}',f'perf{index}@workflow.test'))
    cur.execute('INSERT INTO corporate_intake_slots(intake_id,full_name,email,email_key,registration_id) VALUES(%s,%s,%s,%s,%s)',
        (iid,f'Trainee {index}',f'perf{index}@workflow.test',f'perf{index}@workflow.test',reg_id))
conn.commit();cur.close();conn.close()

guarded=psycopg2.connect
def sample(handler):
    count=0
    def connect(*a,**kw):
        nonlocal count
        count+=1
        return guarded(*a,**kw)
    with app.test_request_context(f'/admin/intake/{iid}/panel'):
        session.update(user_id=actor,user_role='admin')
        start=time.perf_counter()
        with patch.object(psycopg2,'connect',connect):
            response=handler(iid)
        elapsed=(time.perf_counter()-start)*1000
        assert response.status_code==200
    return count,elapsed

old=namespace['baseline_panel'];new=intake_module.intake_panel
sample(old);sample(new)
results={'baseline':[],'current':[]}
for repeat in range(10):
    for name,handler in ([('baseline',old),('current',new)] if repeat%2 else [('current',new),('baseline',old)]):
        results[name].append(sample(handler))
report={'baseline_revision':revision,'database':assert_isolated(),'trainees':100,
        'method':'Alternating Flask handler calls; same current DB helpers/schema, mock mail/gateway; excludes network transport.'}
for name,values in results.items():
    report[name]={'connections_per_request':statistics.median(v[0] for v in values),
                  'median_ms':round(statistics.median(v[1] for v in values),2),'samples':len(values)}
(ROOT/'docs'/'workflow-performance.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
print(json.dumps(report,indent=2))
