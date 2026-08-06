import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))
import psycopg2

conn = psycopg2.connect(os.getenv('DATABASE_URL'))
cur = conn.cursor()
cur.execute("SELECT id, email, payment_status, role FROM users WHERE email IN ('demo.fail@powerwize.com','demo.ready@powerwize.com')")
rows = cur.fetchall()
for r in rows:
    print(f"id={r[0]}  email={r[1]}  payment_status={r[2]}  role={r[3]}")
cur.close()
conn.close()
