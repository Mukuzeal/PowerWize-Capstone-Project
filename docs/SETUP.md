# PowerWize — Setup and Deployment Guide

Installation, configuration, and deployment for the PowerWize training and
consultation system.

**Contents**

1. [Requirements](#1-requirements)
2. [Installation](#2-installation)
3. [Configuration](#3-configuration)
4. [Database](#4-database)
5. [Running the application](#5-running-the-application)
6. [Seeding test data](#6-seeding-test-data)
7. [Building the retrieval index](#7-building-the-retrieval-index)
8. [Deployment](#8-deployment)
9. [Verification](#9-verification)
10. [Troubleshooting](#10-troubleshooting)

---

## 1. Requirements

| Component | Version | Notes |
|---|---|---|
| Python | 3.11 or newer | 3.13 is what the project is developed against |
| PostgreSQL | 15 or newer | 18 is what the project is developed against |
| Git | any recent | |

**Accounts and keys you will need.** The application starts without them, but the
corresponding feature is inert until each is supplied.

| Service | Needed for | Free tier |
|---|---|---|
| [Groq Cloud](https://console.groq.com) | AI quiz generation, Solara chat, document screening, bill OCR | yes |
| [PayMongo](https://dashboard.paymongo.com) | card and QRPH checkout | test keys are free |
| [Polygon Amoy faucet](https://faucet.polygon.technology) | gas for anchoring payments and certificates | yes, testnet |
| SMTP (e.g. Gmail app password) | invitation tokens, receipts, notices | yes |

Groq can be replaced entirely by a local [LM Studio](https://lmstudio.ai) server
if you would rather not use a hosted model — see
[section 3](#3-configuration).

---

## 2. Installation

```bash
git clone https://github.com/Mukuzeal/PowerWize-Capstone-Project.git
cd PowerWize-Capstone-Project
```

### Windows

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### Linux / macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

> **Note on the committed `venv/`.** If a `venv/` directory came with your clone,
> it is a Windows virtual environment and will not work from Linux. Create your
> own as shown above.

---

## 3. Configuration

Copy the template and fill it in:

```bash
cp .env.example .env
```

### Required

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string, e.g. `postgresql://postgres:password@localhost:5432/powerwize` |
| `SECRET_KEY` | Flask session signing key. Generate one with `python -c "import secrets; print(secrets.token_hex(32))"` |

### AI providers

Three independent knobs, each falling back to `AI_PROVIDER`. The split is
deliberate: a model good at reading a government ID is not the one you want
writing quiz questions, and changing the chat model must not force a re-index.

| Variable | Controls | Values |
|---|---|---|
| `AI_PROVIDER` | the fallback for the two below | `groq` · `lmstudio` |
| `TEXT_PROVIDER` | quiz generation, hints, Solara chat | `groq` · `lmstudio` |
| `VISION_PROVIDER` | ID and selfie screening, bill OCR | `groq` · `lmstudio` |
| `EMBED_PROVIDER` | retrieval embeddings | `local_cpu` · `lmstudio` |

For Groq:

```ini
AI_PROVIDER=groq
GROQ_API_KEY=gsk_...
GROQ_MODEL=llama-3.3-70b-versatile
```

For a local LM Studio server:

```ini
AI_PROVIDER=lmstudio
LM_STUDIO_URL=http://127.0.0.1:1234
LM_STUDIO_MODEL=local-model
```

> **Use `127.0.0.1`, not `localhost`.** On Windows, `localhost` resolves to IPv6
> `::1` first. LM Studio listens on IPv4 only, so every request waits about two
> seconds for the IPv6 attempt to fail before falling back — measured at 2046 ms
> against 3.2 ms per call, and a single Solara turn makes two or three of them.

`EMBED_PROVIDER=local_cpu` runs the embedding model on CPU through
fastembed/ONNX with no GPU required, so retrieval keeps working even when LM
Studio is not running. This is the recommended default.

### Retrieval tuning

```ini
EMBED_MODEL=BAAI/bge-small-en-v1.5
RAG_MIN_SCORE=0.55
RAG_CACHE_TTL=300
RAG_GROQ_FALLBACK=0
```

`RAG_MIN_SCORE` is the similarity floor below which a retrieved chunk is
discarded. It was tuned from the per-category score output of
`scripts/rag_eval.py`, not guessed — re-run that script before changing it.

`RAG_CACHE_TTL` is how long the fetched and normalised chunk matrix is reused
before `rag_chunks` is re-read. Opening a connection and re-parsing every
`REAL[]` accounted for roughly 57 ms of a 62 ms retrieval, which is why the cache
exists. Set it to `0` while hand-checking an index you are rebuilding, since
`build_rag_index.py` runs as a separate process and a live application will
serve the old vectors until the TTL lapses.

Full detail on retrieval, thresholds, off-topic gating, cancellation, and PII
handling is in **[RAG_SETUP.md](RAG_SETUP.md)**.

### Payments

```ini
PAYMONGO_SECRET_KEY=sk_test_...
PAYMONGO_PUBLIC_KEY=pk_test_...
PAYMONGO_WEBHOOK_SECRET=whsec_...
TRAINING_FEE=5000
```

Use `sk_test_` / `pk_test_` keys for development. The webhook needs a publicly
reachable URL — see [section 8](#8-deployment) for exposing a local server.

### Blockchain

```ini
POLYGON_NETWORK=amoy
AMOY_RPC_URL=https://rpc-amoy.polygon.technology
CHAIN_ID_AMOY=80002
SYSTEM_WALLET_PRIVATE_KEY=your-private-key
SYSTEM_WALLET_ADDRESS=0x...
```

Fund the wallet from the [Polygon faucet](https://faucet.polygon.technology).
Anchoring is best-effort — an unfunded or unreachable wallet degrades the UI to
an "Off-chain" badge with a re-anchor action and never blocks a payment or a
certificate.

> **Never commit `.env`.** The repository ignores `.env` and the whole `.env.*`
> family, because a backup of it carries every API key and the wallet private
> key. Only `.env.example` is admitted.

### Mail

```ini
EMAIL_USER=your@gmail.com
EMAIL_PASSWORD=your-app-password
EMAIL_FROM_NAME=EnergyWize
```

Gmail requires an [app password](https://support.google.com/accounts/answer/185833),
not your account password.

---

## 4. Database

Create an empty database:

```bash
createdb powerwize
```

```sql
-- or, from psql
CREATE DATABASE powerwize;
```

**There is nothing to migrate.** The entire schema lives in `init_db()` in
[../src/db/core.py](../src/db/core.py) as `CREATE TABLE IF NOT EXISTS` plus
idempotent `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` plus inline backfills, and
it re-runs on every application start. A fresh clone and a long-lived database
converge on the same 36-table shape automatically.

To add a column, append an idempotent `ALTER` and its backfill to `init_db()` —
do not create a migration file, because nothing reads them.

### PostgreSQL on Linux with Docker

If you would rather not install PostgreSQL directly:

```bash
docker run -d --name powerwize-db \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=powerwize \
  -p 5432:5432 \
  -v powerwize-pgdata:/var/lib/postgresql/data \
  postgres:18
```

Then set `DATABASE_URL=postgresql://postgres:postgres@localhost:5432/powerwize`.

> **A raw `pgdata/` directory cannot be shared between a Windows and a Linux
> boot.** `LC_COLLATE` is baked into the catalog at initialisation, so the
> cluster will refuse to start on the other side. Move the database as a SQL
> dump (`pg_dump` / `psql`) instead of copying the data directory.

---

## 5. Running the application

The application **must** run with `src/` as the working directory. Every module
imports its siblings flat — `from db import ...`, `from lms_bp._shared import ...`
— so `src/` has to be on `sys.path`.

### Windows

```powershell
cd src
..\venv\Scripts\python.exe app.py
```

Or use the launcher, which starts PostgreSQL if it is down, kills a stale
`app.py`, and serves on port 5000:

```powershell
.\run.ps1
```

> **Launcher gotcha.** `run.ps1` and `PowerWize.bat` both invoke
> `.venv\Scripts\python.exe`, but the virtual environment in this repository is
> `venv\` with no leading dot. Either create a `.venv` junction or invoke
> `venv\Scripts\python.exe` directly.

### Linux / macOS

```bash
source .venv/bin/activate
python src/app.py
```

Or use the provided script:

```bash
./run-linux.sh
```

The application serves on **http://localhost:5000**.

> Importing `app` runs `init_db()`, which needs a live database. If PostgreSQL is
> not up, startup fails — this is expected, not a bug.

---

## 6. Seeding test data

Maintenance scripts live in `scripts/` and write directly to whatever
`DATABASE_URL` resolves to. Anything destructive calls `require_local_db()` from
`scripts/_guard.py`, which refuses a non-localhost host unless
`POWERWIZE_ALLOW_REMOTE=1` is set.

**Pass credentials by environment variable — never hardcode them.** An earlier
literal password in `seed_users.py` ended up published.

```powershell
cd src
$env:SEED_PASSWORD="choose-a-password"
..\venv\Scripts\python.exe ..\scripts\seed_roles.py
```

```bash
cd src
SEED_PASSWORD="choose-a-password" python ../scripts/seed_roles.py
```

| Script | Creates |
|---|---|
| `seed_roles.py` | one account per role, plus one Trainer per work area — the fastest way to exercise the permission model |
| `seed_demo.py` | colloquium demonstration accounts |
| `backfill_training_types.py` | normalises legacy programme free-text onto programme codes |
| `reseed_lms_modules.py` | **destructive** — wipes every LMS module and reseeds |

Scripts run from any working directory: each one puts `src/` on `sys.path`
itself with

```python
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
```

That line is required in any new script, above its first `from db import ...`.
Running a script makes `sys.path[0]` the *script's own folder*, never the current
directory, so `cd src` alone does **not** make the flat imports resolve.

---

## 7. Building the retrieval index

Solara answers from `knowledge/solar/*.md`, chunked and embedded into the
`rag_chunks` table. Re-indexing is a deliberate manual step, not something the
application does on boot:

```bash
cd src
python ../scripts/build_rag_index.py
```

Run it after any edit to `knowledge/solar/*.md`. The script compares a content
hash per chunk and skips anything unchanged, so re-running it is cheap.

Then check retrieval quality:

```bash
cd src
python ../scripts/rag_eval.py
```

This reports per-category similarity scores and is what `RAG_MIN_SCORE` should be
tuned from.

---

## 8. Deployment

For a step-by-step hosted deployment on Azure App Service — the platform this
project is hosted on — see **[DEPLOY_AZURE.md](DEPLOY_AZURE.md)**. The rest of
this section covers what any platform needs.

### Production server

`Procfile` holds the production command:

```
web: gunicorn --chdir src app:app
```

The `--chdir src` is not optional — it is what satisfies the flat-import
requirement described in [section 5](#5-running-the-application).

### Platform checklist

1. Provision a PostgreSQL instance and set `DATABASE_URL` to its connection
   string. Most managed providers require TLS — append `?sslmode=require`.
2. Set every variable from [section 3](#3-configuration) in the platform's
   environment configuration. Do not upload `.env`.
3. **Point `POWERWIZE_DATA_DIR` at persistent storage outside the deployed
   tree.** Uploaded registration documents, module material and exam
   submissions are written to disk, and their database rows outlive the
   process — if the files are wiped by a redeploy, those rows point at nothing.
   Unset, uploads land next to the code, which is wrong anywhere the deployed
   tree is replaced on deployment.
4. **Point `EMBED_CACHE_DIR` at persistent storage too.** The embedding model
   is a ~130 MB download; without a durable cache it is re-fetched on every
   cold start, and the first visitor pays for it.
5. Set `TEXT_PROVIDER` and `VISION_PROVIDER` to `groq`. A hosted deployment has
   no LM Studio server to reach, so those calls would hang until they timed
   out. `EMBED_PROVIDER=local_cpu` is correct and runs in-process.
6. Deploy. `init_db()` creates the schema on first boot.
7. Register the PayMongo webhook against
   `https://your-domain/payment/webhook`.
8. Fund the Polygon wallet.
9. Create the first administrator with `scripts/create_admin.py`, passing the
   password by environment variable and `POWERWIZE_ALLOW_REMOTE=1` to clear the
   non-localhost guard.
10. Build the retrieval index ([section 7](#7-building-the-retrieval-index)),
    again with `POWERWIZE_ALLOW_REMOTE=1`.

### Exposing a local server for webhook testing

PayMongo needs a publicly reachable callback. For local development, tunnel the
port:

```bash
ngrok http 5000
```

Then register `https://<your-subdomain>.ngrok-free.app/payment/webhook` in the
PayMongo dashboard. The repository includes `run-linux-ngrok.sh` and
`PowerWize-Ngrok.bat` as convenience wrappers.

The webhook is one of three views deliberately exempt from CSRF protection,
along with the two upload-validation APIs. **Every other form must carry a CSRF
token**, including any new one you add.

---

## 9. Verification

There is no automated test suite. The de-facto check before declaring work done
is a compile pass plus an import pass, then exercising the route in a browser.

```powershell
venv\Scripts\python.exe -m py_compile src\app.py src\db\*.py src\lms_bp\*.py src\admin\*.py
cd src; ..\venv\Scripts\python.exe -c "from app import app; print('imports ok')"
```

```bash
python -m py_compile src/app.py src/db/*.py src/lms_bp/*.py src/admin/*.py
cd src && python -c "from app import app; print('imports ok')"
```

A few hand-rolled scripts guard specific regressions a compile pass cannot
catch. They are not a suite — run the relevant one after touching that area.

| Script | Guards |
|---|---|
| `scripts/solar_calc_check.py` | `solar_engine` sizing and ROI mathematics |
| `scripts/rag_eval.py` | retrieval threshold and grounding quality |
| `scripts/solar_chat_text_check.py` | Solara text-processing helpers |
| `scripts/solar_grounding_check.py` | the guard that stops the model authoring numbers |
| `scripts/solar_latency_check.py` | per-stage timing across providers |

### Inspecting a Solara turn

`scripts/solar_chat_devapp.py` serves the real application on port 5001 with a
`/dev/chat` page: the actual chat interface in an iframe beside a live trace of
the turn — gate decision, every retrieved chunk *with its score*, what the
extractor banked, the preview calculation, per-stage timings, and the exact
system prompt sent. It instruments `solar_bp` by monkeypatch from that process
only, so no development-only branch exists in a shipped route.

```bash
cd src
python ../scripts/solar_chat_devapp.py                  # provider from .env
python ../scripts/solar_chat_devapp.py --provider groq  # override
```

Use it when a reply looks wrong and you need to see whether retrieval, the gate,
extraction, or the model caused it.

---

## 10. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `ModuleNotFoundError: No module named 'db'` | You are not running from `src/`. Use `cd src && python app.py`, or add the `sys.path.insert` line if this is a new script in `scripts/`. |
| Startup fails on `init_db()` | PostgreSQL is not running or `DATABASE_URL` is wrong. Importing `app` always runs `init_db()`. |
| `run.ps1` cannot find Python | It invokes `.venv\Scripts\python.exe` but the environment here is `venv\`. Create a `.venv` junction or call `venv\Scripts\python.exe` directly. |
| Every AI call takes about two seconds | `LM_STUDIO_URL` is set to `localhost`. Change it to `127.0.0.1`. |
| Solara returns nothing relevant | The index is empty or stale. Run `scripts/build_rag_index.py`, then `scripts/rag_eval.py` to confirm scores clear `RAG_MIN_SCORE`. |
| Solara answers but cites no sources | Retrieved chunks all scored below `RAG_MIN_SCORE`. Check `scripts/rag_eval.py` output before lowering the floor. |
| Certificates and receipts show "Off-chain" | The Polygon wallet is unfunded or the RPC is unreachable. Anchoring is best-effort by design; fund the wallet and use the re-anchor action. |
| Payment succeeds but the invoice stays unpaid | The webhook never arrived. Confirm the registered URL is reachable and check `unresolved_payment_events`, where unmatched events are quarantined with their raw body. |
| Trainee sees no modules | Their `training_type` does not match any published module's. Check `normalize_training_type()` and whether modules are published. |
| Corporate trainee is asked for a join code they do not have | A class exists for their invoice but the code was not distributed. Rotate or re-send it from the admin class panel. |
| Template text renders as mojibake | A template was saved as CP1252 and read as UTF-8. Write template files as UTF-8; `scripts/fix_template_unicode.py` repairs existing damage. |
| `import fitz` fails (PyMuPDF) | Known local blocker on some Windows installs. Use `pypdfium2` for PDF rasterisation instead. |
