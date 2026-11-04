# Deploying PowerWize to Render + Supabase

Render runs the Flask app; Supabase is the PostgreSQL database. They are
independent choices — this split exists because Render's filesystem is
ephemeral and its managed Postgres expires on the free plan, while Supabase
gives a database that outlives both.

Read [SETUP.md](SETUP.md) first for what every environment variable means.
[DEPLOY_AZURE.md](DEPLOY_AZURE.md) covers the alternative target; the
application configuration is nearly identical, the hosting specifics are not.

---

## 1. What boots, and why it is slow

[src/app.py](../src/app.py) does two expensive things at **import time**,
before the first request is served:

```python
init_db()          # app.py:91  — 36 CREATE TABLE IF NOT EXISTS + backfills
warm_embedder()    # app.py:95  — loads the ~130MB fastembed/ONNX model
```

Both are deliberate and documented in place. The consequence for hosting is
that a cold start is not cheap, and on a plan that sleeps, every visitor after
an idle period pays it. Budget 60–90 seconds for a cold boot with an empty
model cache.

This is the single fact that should drive your plan choice below.

---

## 2. What it costs, honestly

| | Free tier | What it actually means |
|---|---|---|
| **Supabase** | 500 MB database | **Pauses after 7 days idle.** Needs a manual unpause from the dashboard. |
| **Render** | 512 MB RAM | **Spins down after 15 min idle**, no persistent disk, no shell access. |

512 MB is genuinely marginal for this app: Python + Flask + numpy +
onnxruntime + a loaded 130 MB model lands in the 350–450 MB range with little
headroom. It usually fits. It is not comfortable.

Two upgrades, in the order they become worth it:

- **Render Starter, $7/mo** — removes the spin-down. This is the one that
  matters for a scheduled defense, because it removes the cold start entirely.
- **Render Disk, ~$0.25/GB/mo** — persistent storage for uploads and the model
  cache. Without it, see [section 6](#if--and-only-if--you-add-a-render-disk).

> **Wake Supabase the day before your defense, not an hour before.** A paused
> project takes a few minutes to restore, and that is not something you want to
> discover on the day.

---

## 3. Create the Supabase project

1. [database.new](https://database.new) → name it, set a strong database
   password, pick the region closest to you (Southeast Asia).
2. Wait for provisioning, then open **Project Settings → Database**.

### Which connection string — this matters

Supabase offers three, and picking the wrong one is the most common failure:

| Mode | Host / port | Use it for |
|---|---|---|
| Direct | `db.<ref>.supabase.co:5432` | **IPv6 only.** Will not work from Render, or from most home ISPs. |
| **Session pooler** | `aws-0-<region>.pooler.supabase.com:5432` | **Use this.** IPv4, behaves like a normal Postgres connection. |
| Transaction pooler | `...pooler.supabase.com:6543` | Serverless only. Not this app. |

**Use the Session pooler string for both Render and your laptop.** Note that
the username changes under the pooler — it is `postgres.<project-ref>`, not
`postgres`. Copy the exact string from the dashboard rather than assembling it
by hand, and append TLS:

```
postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require
```

`init_db()` builds all 36 tables idempotently on first boot, so **there is no
schema step** and no migration files to run.

---

## 4. Import your local database

Put both ends in `.env` (see [.env.example](../.env.example)):

```
LOCAL_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/powerwize
SUPABASE_DATABASE_URL=postgresql://postgres.<ref>:<pw>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require
```

[scripts/db_sync.py](../scripts/db_sync.py) moves data one direction. It is a
**replace, not a merge** — both databases use the same serial primary keys, so
merging them would collide on every table.

### The choice you have to make

```powershell
$env:POWERWIZE_ALLOW_REMOTE="1"

# Structure only — 36 tables, zero rows. No personal data leaves your machine.
venv\Scripts\python.exe scripts\db_sync.py --to-supabase --schema-only

# Everything, including real trainee records.
venv\Scripts\python.exe scripts\db_sync.py --to-supabase
```

The local database carries real names, residences, contact numbers, birthdates
and password hashes. The second command copies all of it to a hosted service.
**Prefer `--schema-only`, then seed:**

```powershell
cd src
$env:SEED_PASSWORD="<choose one>"; $env:POWERWIZE_ALLOW_REMOTE="1"
..\venv\Scripts\python.exe ..\scripts\seed_roles.py
```

The demo looks identical and no real person's data is involved.

To pull hosted data back down later:

```powershell
venv\Scripts\python.exe scripts\db_sync.py --to-local
```

> Your local server is PostgreSQL 16. Check which major version your Supabase
> project runs; a plain-SQL dump normally crosses one major version fine, but
> confirm rather than assume.

---

## 5. Create the Render service

**New → Web Service**, connect the GitHub repo, then:

| Field | Value |
|---|---|
| Runtime | Python 3 |
| Build command | `pip install -r requirements.txt` |
| Start command | see below |
| Instance type | Free to start; Starter if the cold start hurts |

### Start command

```
gunicorn --chdir src app:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --worker-class gthread --timeout 600
```

Four details, each load-bearing:

- **`--chdir src`** — every module imports its siblings flat (`from db import
  ...`), so the process must run with `src/` as the working directory. Without
  this the app does not import at all. This mirrors what `Procfile` already does.
- **`--bind 0.0.0.0:$PORT`** — Render assigns the port; binding anything else
  makes the service unreachable and the deploy eventually fails with
  "no open ports detected".
- **`--workers 1`** — each worker loads its own copy of the ONNX model. Two
  workers double the memory for no benefit at this scale. The four threads
  carry concurrency instead.
- **`--timeout 600`** — `init_db()` plus the embedder warm routinely exceed
  gunicorn's 30-second default on a cold free instance.

### Pin the Python version

Render otherwise picks its own default. Set this as an environment variable:

```
PYTHON_VERSION = 3.12.10
```

---

## 6. Environment variables

Set these under **Environment → Environment Variables**. Never upload `.env` —
it is gitignored precisely because it holds every API key and the wallet
private key.

```
DATABASE_URL        postgresql://postgres.<ref>:<pw>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require
SECRET_KEY          <64 hex chars — python -c "import secrets; print(secrets.token_hex(32))">
PYTHON_VERSION      3.12.10

AI_PROVIDER         groq
TEXT_PROVIDER       groq
VISION_PROVIDER     groq
EMBED_PROVIDER      local_cpu
GROQ_API_KEY        <your key>
GROQ_MODEL          openai/gpt-oss-120b
GROQ_VISION_MODEL   qwen/qwen3.8-27b
EMBED_MODEL         BAAI/bge-small-en-v1.5
RAG_MIN_SCORE       0.55
RAG_CACHE_TTL       300

PAYMONGO_SECRET_KEY     <sk_test_...>
PAYMONGO_PUBLIC_KEY     <pk_test_...>
PAYMONGO_WEBHOOK_SECRET <whsec_...>
TRAINING_FEE            5000

POLYGON_NETWORK            amoy
AMOY_RPC_URL               https://rpc-amoy.polygon.technology
CHAIN_ID_AMOY              80002
SYSTEM_WALLET_PRIVATE_KEY  <key>
SYSTEM_WALLET_ADDRESS      <0x...>

EMAIL_USER          <you@gmail.com>
EMAIL_PASSWORD      <app password>
EMAIL_FROM_NAME     EnergyWize
```

**Do not set `TEXT_PROVIDER=lmstudio`.** There is no LM Studio server on
Render; the call would hang until it timed out. `EMBED_PROVIDER=local_cpu` is
correct and runs in-process — Groq offers no embedding endpoint, so there is no
`groq` value for that variable.

**Verify both Groq model names against your own key before deploying.** Groq
retires models with little notice, and a request naming a retired one returns a
400 that surfaces as a feature silently doing nothing rather than as an error:

```bash
curl -s https://api.groq.com/openai/v1/models \
  -H "Authorization: Bearer $GROQ_API_KEY" | grep '"id"'
```

`GROQ_VISION_MODEL` must additionally be a model that accepts image input,
which most are not — it is read by both [upload_validation.py](../src/upload_validation.py)
(ID and selfie screening) and [ocr_module.py](../src/ocr_module.py) (electricity
bill reading). A text-only model there fails with `content must be a string`.

### If — and only if — you add a Render Disk

A disk (mount path `/var/data`) makes uploads and the model cache survive
restarts. Add these two **only once the disk exists**; pointing them at a path
with no disk behind it is worse than leaving them unset:

```
POWERWIZE_DATA_DIR  /var/data
EMBED_CACHE_DIR     /var/data/.cache/fastembed
```

Without a disk, accept the consequence honestly: **uploaded registration
documents, module material and exam submissions are lost on every restart and
redeploy**, while their database rows survive — so the app will list records
whose files 404. For a defense demo that is usually acceptable. For anything
real it is not.

---

## 7. After the first deploy

Render's free plan has no shell, but **you do not need one** — Supabase is
reachable from your laptop. Point `DATABASE_URL` at Supabase locally and run
the scripts from there.

```powershell
cd src
$env:DATABASE_URL=$env:SUPABASE_DATABASE_URL
$env:POWERWIZE_ALLOW_REMOTE="1"

# 1. First administrator
$env:SEED_PASSWORD="<choose one>"
..\venv\Scripts\python.exe ..\scripts\create_admin.py

# 2. Retrieval index — Solara answers nothing useful until rag_chunks exists
..\venv\Scripts\python.exe ..\scripts\build_rag_index.py
```

`POWERWIZE_ALLOW_REMOTE=1` is required because `require_local_db()` in
[scripts/_guard.py](../scripts/_guard.py) refuses any non-localhost host by
default. That guard exists to stop a seed or migration script being pointed at
production by accident — set it deliberately, per command, never as a stored
variable.

Re-run `build_rag_index.py` after any edit to `knowledge/solar/*.md`; it hashes
each chunk and skips what has not changed.

3. **Register the PayMongo webhook** → `https://<service>.onrender.com/payment/webhook`.
   Without it, payments succeed at the gateway and the invoice never settles —
   the symptom is a paid customer stuck as unpaid, with the event sitting in
   `unresolved_payment_events`.
4. **Fund the Polygon wallet** from the [Amoy faucet](https://faucet.polygon.technology).
   Without gas, anchoring degrades to an "Off-chain" badge — valid, but it
   undercuts the feature you are demonstrating.

---

## 8. Verifying the deployment

| Check | How | Expected |
|---|---|---|
| App responds | `curl -I https://<service>.onrender.com/` | `200` |
| Schema applied | Render → Logs, during boot | no `init_db` traceback |
| Sign-in works | visit `/auth/login` | the shared sign-in page |
| Embedder loaded | `/solar/chat`, ask a PV question | grounded answer with a `Sources:` line |
| Retrieval populated | count `rag_chunks` in the Supabase SQL editor | non-zero |
| Memory headroom | Render → Metrics | under 512 MB, with room |
| Uploads (disk only) | upload material, restart, download | file still downloads |

The memory check is the one worth watching. If the service is OOM-killed during
the embedder warm, the log shows the worker dying mid-boot with no Python
traceback — that is the symptom, and Starter is the fix.

---

## 9. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `ModuleNotFoundError: No module named 'db'` | `--chdir src` missing from the start command |
| Deploy fails, "no open ports detected" | not bound to `$PORT` |
| `connection to server ... failed` | used the **direct** (IPv6) string; switch to the Session pooler |
| `password authentication failed` | pooler username must be `postgres.<project-ref>` |
| `SSL connection is required` | append `?sslmode=require` |
| Worker dies during boot, no traceback | out of memory on the 512 MB free plan |
| First request after idle takes ~90s | free-plan spin-down plus model re-download; Starter removes it |
| Vision / OCR silently does nothing | `GROQ_VISION_MODEL` retired or text-only |
| Uploaded file 404s after redeploy | no Render Disk — see [section 6](#if--and-only-if--you-add-a-render-disk) |
| Supabase refuses all connections | project auto-paused after 7 days; unpause in the dashboard |
