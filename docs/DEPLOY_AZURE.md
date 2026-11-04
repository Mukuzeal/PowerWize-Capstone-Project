# Deploying PowerWize to Azure App Service

A runbook for hosting PowerWize on Azure for Students: Linux App Service for the
application, Azure Database for PostgreSQL Flexible Server for the data.

For local installation see **[SETUP.md](SETUP.md)**. This document only covers
hosting.

**Contents**

1. [Why this shape](#1-why-this-shape)
2. [What it costs, honestly](#2-what-it-costs-honestly)
3. [Prerequisites](#3-prerequisites)
4. [Create the database](#4-create-the-database)
5. [Create the web app](#5-create-the-web-app)
6. [Configure application settings](#6-configure-application-settings)
7. [Deploy the code](#7-deploy-the-code)
8. [Post-deployment steps](#8-post-deployment-steps)
9. [Verifying the deployment](#9-verifying-the-deployment)
10. [Conserving credit](#10-conserving-credit)
11. [Troubleshooting](#11-troubleshooting)

---

## 1. Why this shape

Three properties of this application drive the hosting choice, and they rule
out most cheap options.

| Requirement | Why | Consequence |
|---|---|---|
| **Persistent filesystem** | Registration documents, LMS module material, and exam submissions are written to disk. Their database rows outlive the process, so if the files vanish the rows point at nothing — broken downloads and lost ungraded work. | A platform with a purely ephemeral filesystem is unusable without rewriting four upload paths against object storage. |
| **~1 GB RAM headroom** | `warm_embedder()` in [../src/app.py](../src/app.py) loads a ~130 MB ONNX model at boot, alongside Flask, numpy, web3 and Pillow. | 512 MB instances will not hold it. |
| **No sleeping** | Cold start pays `init_db()` (37 DDL statements) *plus* the embedder load. | A platform that sleeps after idle makes the first click of a demonstration hang. |

App Service satisfies all three: **`/home` is a persistent mount**, B-series
instances have enough memory, and Always On keeps the process warm.

The one subtlety is *where* on `/home`. Code is deployed to
`/home/site/wwwroot`, which is replaced wholesale on every deployment — so
uploads must not live there. `POWERWIZE_DATA_DIR` moves them to `/home/data`,
outside the deployed tree but still on the persistent mount. The same applies
to the embedder's weights, which `EMBED_CACHE_DIR` points at `/home/.cache`
so they are downloaded once rather than on every restart.

> QR images are deliberately **not** relocated. Certificate QRs are regenerated
> on each verification request and receipt QRs are reconstructed from the
> database, so losing them on redeploy costs nothing.

---

## 2. What it costs, honestly

Azure for Students gives **$100 of credit for 12 months, with no credit card**,
renewable each year you re-verify as a student. It does **not** stretch to 12
months of always-on B1 compute plus a managed database at list price — expect
roughly $25–30/month for that pairing, so about three to four months of credit.

Two things change the arithmetic in your favour, and you should check both in
the portal rather than taking this document's word for it:

- A new Azure account typically includes **750 hours/month of B1S Linux App
  Service free for the first 12 months**.
- Azure Database for PostgreSQL Flexible Server typically includes **750
  hours/month of Burstable B1MS plus 32 GB storage free for the first 12
  months**.

Between them, a single small instance of each can land at or near zero for the
first year, with the $100 absorbing overflow. **Set a budget alert before you
deploy** (section 3) and read [section 10](#10-conserving-credit).

The useful safety property: with no credit card on the account, exhausting the
credit **stops** the services. It cannot produce a bill.

---

## 3. Prerequisites

1. **Azure for Students** — activate at
   [azure.microsoft.com/free/students](https://azure.microsoft.com/free/students)
   with your university email. No credit card.
2. **Azure CLI** — [install](https://learn.microsoft.com/cli/azure/install-azure-cli),
   then:
   ```bash
   az login
   az account show --query "{subscription:name, state:state}" -o table
   ```
3. **A budget alert.** Do this first, not last:
   ```bash
   az consumption budget create \
     --budget-name powerwize-guard \
     --amount 25 \
     --time-grain Monthly \
     --category Cost
   ```
   Or Portal → Cost Management → Budgets. Alert yourself at 50% and 80%.

Set these once so the commands below can be pasted as-is:

```bash
RG=powerwize-rg
LOC=southeastasia          # closest region to the Philippines
APP=powerwize              # must be globally unique -> powerwize.azurewebsites.net
PGHOST=powerwize-db        # must be globally unique
PGADMIN=pwadmin
PGPASS='<a-strong-password>'
```

```bash
az group create --name $RG --location $LOC
```

> Pick `$LOC` for latency to your users, but verify the free-tier allowances
> exist in that region — they are not offered everywhere.

---

## 4. Create the database

```bash
az postgres flexible-server create \
  --resource-group $RG \
  --name $PGHOST \
  --location $LOC \
  --admin-user $PGADMIN \
  --admin-password "$PGPASS" \
  --tier Burstable \
  --sku-name Standard_B1ms \
  --storage-size 32 \
  --version 16 \
  --public-access 0.0.0.0 \
  --yes
```

`--public-access 0.0.0.0` is Azure's shorthand for "allow other Azure services",
not "allow the internet" — it creates the `AllowAllAzureIps` rule the web app
needs. To run the maintenance scripts from your own machine, add your address
too:

```bash
az postgres flexible-server firewall-rule create \
  --resource-group $RG --name $PGHOST \
  --rule-name my-laptop \
  --start-ip-address <your.ip> --end-ip-address <your.ip>
```

Create the database itself:

```bash
az postgres flexible-server db create \
  --resource-group $RG --server-name $PGHOST --database-name powerwize
```

**There is no schema step.** `init_db()` creates all 36 tables and every column
idempotently on first boot. Do not restore `powerwize_dump.sql` into this
server unless you intend to carry real personal data into the cloud — see
[section 8](#8-post-deployment-steps).

Your connection string, which Azure requires to be TLS:

```
postgresql://pwadmin:<password>@powerwize-db.postgres.database.azure.com:5432/powerwize?sslmode=require
```

---

## 5. Create the web app

```bash
az appservice plan create \
  --resource-group $RG --name powerwize-plan \
  --location $LOC --is-linux --sku B1

az webapp create \
  --resource-group $RG --plan powerwize-plan \
  --name $APP --runtime "PYTHON|3.12"
```

`PYTHON|3.12` matches the version this project is developed against. Do not let
it default.

### Startup command

The default Oryx startup looks for a Flask app at the repository root and will
not find one — every module imports its siblings flat, so the process must run
with `src/` as the working directory.

```bash
az webapp config set \
  --resource-group $RG --name $APP \
  --startup-file "gunicorn --chdir src app:app --bind=0.0.0.0:8000 --workers 1 --threads 4 --worker-class gthread --timeout 600"
```

Three details matter here:

- **`--chdir src`** is the whole reason this command is needed, and mirrors what
  `Procfile` already does.
- **`--workers 1`** is deliberate. Each worker loads its own copy of the ONNX
  model; two workers double the memory for no benefit at this scale. The four
  threads carry concurrency instead.
- **`--timeout 600`** covers the boot cost of `init_db()` plus the embedder
  warm, which can exceed gunicorn's 30-second default on a cold B1.

### Always On

```bash
az webapp config set --resource-group $RG --name $APP --always-on true
```

Without this the instance unloads when idle and the next visitor pays the full
cold start.

---

## 6. Configure application settings

These are the environment variables from [SETUP.md](SETUP.md), supplied through
App Service rather than a `.env` file. **Never deploy `.env` itself** — it is
gitignored precisely because it carries every API key and the wallet private
key.

```bash
az webapp config appsettings set --resource-group $RG --name $APP --settings \
  DATABASE_URL="postgresql://$PGADMIN:$PGPASS@$PGHOST.postgres.database.azure.com:5432/powerwize?sslmode=require" \
  SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')" \
  POWERWIZE_DATA_DIR="/home/data" \
  EMBED_CACHE_DIR="/home/.cache/fastembed" \
  SCM_DO_BUILD_DURING_DEPLOYMENT="1" \
  WEBSITES_CONTAINER_START_TIME_LIMIT="600" \
  AI_PROVIDER="groq" \
  TEXT_PROVIDER="groq" \
  VISION_PROVIDER="groq" \
  EMBED_PROVIDER="local_cpu" \
  GROQ_API_KEY="<your key>" \
  GROQ_MODEL="openai/gpt-oss-120b" \
  GROQ_VISION_MODEL="qwen/qwen3.8-27b" \
  EMBED_MODEL="BAAI/bge-small-en-v1.5" \
  RAG_MIN_SCORE="0.55" \
  RAG_CACHE_TTL="300" \
  PAYMONGO_SECRET_KEY="<sk_test_...>" \
  PAYMONGO_PUBLIC_KEY="<pk_test_...>" \
  PAYMONGO_WEBHOOK_SECRET="<whsec_...>" \
  TRAINING_FEE="5000" \
  POLYGON_NETWORK="amoy" \
  AMOY_RPC_URL="https://rpc-amoy.polygon.technology" \
  CHAIN_ID_AMOY="80002" \
  SYSTEM_WALLET_PRIVATE_KEY="<key>" \
  SYSTEM_WALLET_ADDRESS="<0x...>" \
  EMAIL_USER="<you@gmail.com>" \
  EMAIL_PASSWORD="<app password>" \
  EMAIL_FROM_NAME="EnergyWize"
```

The hosting-specific ones, and why each is needed:

| Setting | Why |
|---|---|
| `POWERWIZE_DATA_DIR=/home/data` | Uploads outside `/home/site/wwwroot`, so a redeploy cannot wipe them |
| `EMBED_CACHE_DIR=/home/.cache/fastembed` | The ONNX weights download once, not on every restart |
| `SCM_DO_BUILD_DURING_DEPLOYMENT=1` | Makes Oryx install `requirements.txt` on deployment |
| `WEBSITES_CONTAINER_START_TIME_LIMIT=600` | Raises Azure's 230-second container start limit, which the boot work can exceed on a cold B1 |
| `?sslmode=require` on `DATABASE_URL` | Azure PostgreSQL refuses non-TLS connections |

**Do not set `TEXT_PROVIDER=lmstudio`.** There is no LM Studio server in Azure;
the call would hang until it timed out. Groq is the only workable text and
vision provider for a hosted deployment. `EMBED_PROVIDER=local_cpu` is correct
and runs in-process — Groq offers no embedding endpoint, so there is no `groq`
value for that variable.

**Verify both Groq model names against your own key before deploying.** Groq
retires models with little notice, and a request naming a retired one returns a
400 that surfaces as a feature silently doing nothing rather than as an error:

```bash
curl -s https://api.groq.com/openai/v1/models \
  -H "Authorization: Bearer $GROQ_API_KEY" | grep '"id"'
```

`GROQ_VISION_MODEL` additionally has to be a model that accepts image input,
which most do not — it is read by both `upload_validation.py` (ID and selfie
screening) and `ocr_module.py` (electricity-bill reading). A text-only model
there fails with `content must be a string`.

---

## 7. Deploy the code

From a clean checkout of `main`:

```bash
az webapp up --resource-group $RG --name $APP --runtime "PYTHON|3.12"
```

Or deploy explicitly from a zip:

```bash
git archive --format=zip --output ../powerwize.zip HEAD
az webapp deploy --resource-group $RG --name $APP --src-path ../powerwize.zip --type zip
```

Using `git archive` rather than zipping the working directory matters: it
includes exactly what is committed and nothing ignored, so the 46 MB of
screenshots under `docs/` still ship but `venv/`, `pgdata/`, `.env` and the
database dump cannot.

Watch the build:

```bash
az webapp log tail --resource-group $RG --name $APP
```

First boot is slow — Oryx installs the dependency set, then the process runs
`init_db()` and downloads the embedding model. Subsequent restarts reuse the
cached weights.

---

## 8. Post-deployment steps

### 1 · Create the first administrator

Open an SSH session into the running container:

```bash
az webapp ssh --resource-group $RG --name $APP
```

```bash
cd /home/site/wwwroot/src
SEED_PASSWORD='<choose one>' POWERWIZE_ALLOW_REMOTE=1 python ../scripts/create_admin.py
```

`POWERWIZE_ALLOW_REMOTE=1` is required because `require_local_db()` in
`scripts/_guard.py` refuses any non-localhost host by default. That guard
exists to stop a seed or migration script being pointed at production by
accident — set it deliberately, per command, and never as an app setting.

### 2 · Build the retrieval index

Solara answers nothing useful until `rag_chunks` is populated:

```bash
cd /home/site/wwwroot/src
POWERWIZE_ALLOW_REMOTE=1 python ../scripts/build_rag_index.py
```

Re-run this after any edit to `knowledge/solar/*.md`. It compares a content hash
per chunk and skips anything unchanged.

### 3 · Register the PayMongo webhook

Point it at `https://<your-app>.azurewebsites.net/payment/webhook` in the
PayMongo dashboard. Without this, payments succeed at the gateway and the
invoice never settles — the symptom is a paid customer stuck as unpaid, with
the event sitting in `unresolved_payment_events`.

### 4 · Fund the Polygon wallet

From the [Amoy faucet](https://faucet.polygon.technology). Without gas,
anchoring degrades to an "Off-chain" badge — valid, but it undercuts the
feature you are demonstrating.

### About the local database dump

`powerwize_dump.sql` carries real names, residences, contact numbers,
birthdates and password hashes. Restoring it into a cloud database copies all
of that into a hosted service.

For a demonstration, **seed instead**:

```bash
cd /home/site/wwwroot/src
SEED_PASSWORD='<choose one>' POWERWIZE_ALLOW_REMOTE=1 python ../scripts/seed_roles.py
```

---

## 9. Verifying the deployment

| Check | How | Expected |
|---|---|---|
| App responds | `curl -I https://$APP.azurewebsites.net/` | `200` |
| Schema applied | `az webapp log tail` during boot | no `init_db` traceback |
| Sign-in works | visit `/auth/login` | the shared sign-in page |
| Uploads persist | upload module material, then `az webapp restart`, then download it | file still downloads |
| Uploads survive deploy | redeploy, then download again | still there — this is what `POWERWIZE_DATA_DIR` buys |
| Embedder loaded | `/solar/chat`, ask a PV question | a grounded answer with a `Sources:` line |
| Retrieval populated | SSH, `python -c "from db import get_db..."` count `rag_chunks` | non-zero |
| Memory headroom | Portal → Metrics → Memory working set | comfortably under 1.75 GB |

The upload-persistence check is the one worth doing properly. Restarting proves
the mount; **redeploying** proves the files are outside `wwwroot`. Only the
second confirms the fix.

---

## 10. Conserving credit

**Stop the database between demonstrations.** Flexible Server can be stopped
for up to seven days, and a stopped server bills only for storage:

```bash
az postgres flexible-server stop  --resource-group $RG --name $PGHOST
az postgres flexible-server start --resource-group $RG --name $PGHOST
```

**Stop the web app** when it is not needed:

```bash
az webapp stop  --resource-group $RG --name $APP
az webapp start --resource-group $RG --name $APP
```

Trade-off: with Always On enabled, restarting still pays the cold start. For a
scheduled defense, start both an hour beforehand and visit the site once to
warm it.

**Drop to B1S** if memory metrics show headroom, or **scale down to F1** only
if you are prepared to lose Always On and accept a 1 GB ceiling — the embedder
may not fit.

**When the credit runs out**, services stop rather than billing you. Re-verify
as a student to renew.

---

## 11. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `ModuleNotFoundError: No module named 'db'` | The startup command lost `--chdir src`. Re-apply it ([section 5](#5-create-the-web-app)). |
| Container fails to start, no Python traceback | Boot exceeded the start limit. Confirm `WEBSITES_CONTAINER_START_TIME_LIMIT=600` and read `az webapp log tail`. |
| `could not connect to server ... SSL` | `?sslmode=require` is missing from `DATABASE_URL`. |
| `no pg_hba.conf entry for host` | The firewall has no `AllowAllAzureIps` rule. Re-run with `--public-access 0.0.0.0`. |
| App restarts in a loop, exit 137 | Out of memory. `--workers 1`, not more, and confirm you are not on F1. |
| First Solara request takes ~30 s every restart | `EMBED_CACHE_DIR` is unset or points inside `wwwroot`, so weights re-download. Point it at `/home/.cache/fastembed`. |
| Uploaded files vanish after deployment | `POWERWIZE_DATA_DIR` is unset, so uploads landed in `wwwroot`. Set it to `/home/data` and redeploy. |
| Solara replies but cites no sources | The index was never built. Run `build_rag_index.py` ([section 8](#8-post-deployment-steps)). |
| Module assistant and AI quiz generation fail | `TEXT_PROVIDER` is `lmstudio`. There is no LM Studio in Azure — set it to `groq`. |
| Bill OCR returns nothing | `VISION_PROVIDER` must be `groq`; `pytesseract` has no tesseract binary on App Service and is inert. |
| Payment succeeds, invoice stays unpaid | The webhook is unregistered or unreachable. Check `unresolved_payment_events`, where unmatched events are quarantined with their raw body. |
| Certificates show "Off-chain" | Wallet unfunded or RPC unreachable. Anchoring is best-effort by design; fund it and use re-anchor. |
| Credit exhausted, site down | Expected behaviour with no card attached. Re-verify student status to renew. |
