# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).

## Running the app

The app **must** run with `src/` as the working directory — every module imports its siblings flat (`from db import ...`, `from lms_bp._shared import ...`), so `src/` has to be on `sys.path`. `Procfile` does this with `gunicorn --chdir src app:app`.

```powershell
# Windows: starts PostgreSQL if down, kills stale app.py, runs on :5000
.\run.ps1              # or double-click PowerWize.bat

# manual
cd src; ..\venv\Scripts\python.exe app.py
```

> `run.ps1` and `PowerWize.bat` both invoke `.venv\Scripts\python.exe`, but the venv in this repo is `venv\` (no dot). Either create a `.venv` junction or invoke `venv\Scripts\python.exe` directly.

Linux/dual-boot (same physical folder, see [LINUX_SETUP.md](LINUX_SETUP.md)):

```bash
sg docker -c "docker compose up -d"   # postgres:18, auto-restores powerwize_dump.sql on first boot
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
python src/app.py
```

The committed `venv/` is a Windows venv — do not use it from Linux. The raw `pgdata/` folder cannot cross boots either (Windows `LC_COLLATE` is baked into the catalog); move the database as `powerwize_dump.sql`.

## Verification

**There is no test suite.** The de-facto check before declaring work done is a compile pass plus an import pass, then exercising the route in the browser:

```powershell
venv\Scripts\python.exe -m py_compile src\app.py src\db\*.py src\lms_bp\*.py src\admin\*.py
cd src; ..\venv\Scripts\python.exe -c "from app import app; print('imports ok')"
```

Note that importing `app` runs `init_db()`, which needs a live database.

A few targeted, hand-rolled scripts guard specific regressions the same compile/import pass can't catch — not a suite, just run the relevant one after touching that area: `scripts/solar_calc_check.py` (solar_engine math), `scripts/rag_eval.py` (retrieval threshold / grounding quality), `scripts/solar_chat_text_check.py` and `scripts/solar_grounding_check.py` (Solara text-processing helpers). All run from `src/` the same way as the maintenance scripts below.

For hands-on testing of Solara specifically, [scripts/solar_chat_devapp.py](scripts/solar_chat_devapp.py) serves the real app on a second port (`:5001`) with a `/dev/chat` page: the actual chat UI in an iframe next to a live trace of the turn — gate decision, every retrieved chunk *with its score*, what the AI extractor banked, the preview calculation, per-step timings, and the exact system prompt sent. It instruments `solar_bp` by monkeypatch from that process only, so no dev-only branch exists in a shipped route. Use it when a reply looks wrong and you need to see whether retrieval, the gate, extraction, or the model caused it.

```powershell
cd src; ..\venv\Scripts\python.exe ..\scripts\solar_chat_devapp.py                     # provider from .env
cd src; ..\venv\Scripts\python.exe ..\scripts\solar_chat_devapp.py --provider groq      # override, as rag_eval.py does
```

[scripts/solar_latency_check.py](scripts/solar_latency_check.py) times a turn stage by stage (extract / topic gate / retrieval / chat) across five representative turn shapes, reusing the dev harness's instrumentation so the two can't drift. Run it once per provider and diff the tables — that's the local-GPU vs Groq comparison. Measured baseline and the latency breakdown live in [docs/RAG_SETUP.md](docs/RAG_SETUP.md).

```powershell
cd src; ..\venv\Scripts\python.exe ..\scripts\solar_latency_check.py --provider groq -n 3
```

## Maintenance scripts

`scripts/*.py` write directly to whatever `DATABASE_URL` resolves to. Anything destructive calls `require_local_db()` from [scripts/_guard.py](scripts/_guard.py), which refuses a non-localhost host unless `POWERWIZE_ALLOW_REMOTE=1`. Add that guard to any new seed/migration script.

They run from any working directory — each one puts `src/` on `sys.path` itself:

```python
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
```

That line is required in every new script, above its first `from db import ...`. Running a script makes `sys.path[0]` the *script's own folder*, never the current directory, so `cd src` alone does **not** make the flat imports resolve — six scripts failed with `ModuleNotFoundError: No module named 'db'` until each got the line.

Pass credentials by env var (never hardcode — an earlier literal in `seed_users.py` ended up published):

```powershell
cd src; $env:SEED_PASSWORD="..."; ..\venv\Scripts\python.exe ..\scripts\seed_users.py
```

`seed_all_data.py`, `seed_registrations.py`, `seed_demo.py` (colloquium accounts), `seed_roles.py` (one account per role, plus one Trainer per work area — see the auth model below), `create_admin.py`, `backfill_training_types.py`, `reseed_lms_modules.py` (destructive — wipes all LMS modules). `recover_databases.py` / `restore_backup.py` / `convert_to_pg.py` are MySQL-era leftovers from before the Postgres migration.

## Architecture

Flask, blueprints, **raw psycopg2 — no ORM**. `templates/` and `static/` live at the project root, not under `src/`; [src/app.py](src/app.py) points Flask at them explicitly.

### Schema lives in code, applied at import time

[src/db/core.py](src/db/core.py) `init_db()` is the entire schema: `CREATE TABLE IF NOT EXISTS` plus `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` plus inline backfill `UPDATE`s. It runs on every app start. **There are no migration files** — to add a column, append an idempotent `ALTER` (and its backfill) to `init_db()`.

[src/db/](src/db/) is a package whose `__init__.py` star-exports every submodule (`core`, `users`, `registrations`, `payments`, `lms`, `solar`, `misc`), so callers always write `from db import <anything>`. `get_db()` → connection, `dict_cur(conn)` → `RealDictCursor`; callers close both by hand.

### Blueprints

Registered in [src/app.py](src/app.py). `lms_bp/` and `admin/` are packages that create the blueprint in `__init__.py` then import their route modules at the bottom — the circular-looking import is deliberate, so route modules can `from . import lms_bp`.

| Blueprint | Owns |
|---|---|
| `auth` | login, logout, forgot/reset password. **No public signup route** — see below |
| `registration` | `/`, `/programs`, `/portal`, and the 7 public registration forms (CEM/CEA/GEMP-LGU/GEMP-OGE/renewals) |
| `site` | brochure pages (`/about`, `/capabilities/*`, `/programs/<code>`, legal) |
| `admin` / `employee` | dashboards; `employee` is a trainer console (hash-routed SPA) |
| `onboarding` | `/create-account/<token>` |
| `payment` | PayMongo card + QRPH, webhook, receipt verification |
| `lms` | modules, quizzes, practical exams, certificates, trainee learning |
| `solar` | AI solar consultation + admin review |
| `upload_validation` | `/api/validate-upload`, `/api/face-match` |

### The trainee lifecycle (spans most of the codebase)

```
public form (registration.py) → admin review (admin/registrations.py) → emailed token
  → /create-account/<token> (onboarding.py) → payment_status='unpaid'
  → /payment (payment_bp.py, PayMongo) → receipt hashed onto Polygon (blockchain.py)
  → /portal → LMS syllabus by training_type → quizzes + practical exam
  → certificate issued (lms_bp/certificates.py) → anchored on Polygon → QR verify page
```

Two invariants that explain a lot of otherwise-odd code:

- **Account creation is invitation-only.** There is deliberately no email+password signup; a plain one would mint trainees that skipped ID upload, selfie liveness, and admin verification. The token carries the approved `training_type` and `payment_status`. See the comment block in [src/auth.py:74-79](src/auth.py#L74-L79).
- **A trainee's syllabus is decided by `training_type`, not by identity.** `normalize_training_type()` maps registration free text to program codes; `lms_get_modules_for_trainee()` resolves the module list. Trainer-facing and trainee-facing progress both fold through `_progress_steps()` in [src/lms_bp/_shared.py](src/lms_bp/_shared.py) so the two views can never disagree.

### Auth model

Plain `session` keys (`user_id`, `user_role`, `user_name`, `user_email`) — no Flask-Login. Wrong role → `abort(403)` (not a redirect to login), and the 403 handler content-negotiates HTML vs JSON.

**Every permission decision goes through [src/permissions.py](src/permissions.py)** — one `CAPABILITIES` map of capability → roles. Nothing else compares a role string inline; `require_admin()` and `_is_instructor()` / `_owns_module()` are thin wrappers over it, and `can()` / `role_label()` are Jinja globals ([src/app.py](src/app.py)) so a hidden button and the route behind it read the same table.

Stored roles are `admin`, `super_user`, `secretary`, `employee`, `trainee`. **`employee` is the stored value for what the UI calls a "Trainer"** — the label changed, the value never did, so don't rename it. Super User is an Admin minus user management and minus deleting other people's modules; Secretary is a Super User minus PV consultations.

A Trainer's remit is set **per account**, not by role: `user_capabilities` stores deviations from the role default (no row = whatever the role says), so one trainer can run training modules, another PV consultations, another both. `can_user()` resolves default-then-override and `current_can()` routes through it — **enforce with `current_can()`, never bare `can()`**, or per-account grants are ignored. `OVERRIDABLE` / `OVERRIDABLE_ROLES` keep this to `manage_modules` and `review_solar` on Trainer only; user management, billing and console access are role-defining and deliberately not grantable per user. `scripts/seed_roles.py` seeds an account per role and per remit for testing.

CSRF is global via `CSRFProtect`. Three views are genuinely exempted in [src/app.py:55-57](src/app.py#L55-L57) (PayMongo webhook, the two upload-validation APIs). A fourth, `solar.solar_chat_cancel` ([src/app.py:62](src/app.py#L62)), is exempted only from Flask-WTF's automatic header check because `navigator.sendBeacon()` cannot set one — it validates the token out of the JSON body itself. Anything else must carry the token, including every new form.

### AI providers

Three env knobs, all falling back to `AI_PROVIDER` (`groq` or `lmstudio`):

- `TEXT_PROVIDER` — quiz generation, hints, solar chat ([src/lms_bp/_shared.py](src/lms_bp/_shared.py), [src/solar_bp.py](src/solar_bp.py))
- `VISION_PROVIDER` — ID/selfie validation, bill OCR ([src/upload_validation.py](src/upload_validation.py), [src/ocr_module.py](src/ocr_module.py))

The split exists because a model good at reading documents is not the one you want writing quiz questions. Keep it when adding AI calls — don't reach for `AI_PROVIDER` directly.

`EMBED_PROVIDER` (separate again, see below) picks the embedding backend for RAG retrieval and never needs re-indexing when `TEXT_PROVIDER` changes.

### Solar RAG grounding (Solara)

Solara ([src/solar_bp.py](src/solar_bp.py)) is retrieval-grounded: chat replies are built from `knowledge/solar/*.md` (chunked, embedded, stored via [src/db/rag.py](src/db/rag.py)) and real numbers from [src/solar_engine.py](src/solar_engine.py)`::compute()`, never from the model's own memory. Full detail — env vars, threshold tuning, off-topic gating, cancellation, PII handling — lives in [docs/RAG_SETUP.md](docs/RAG_SETUP.md); read it before touching `solar_bp.py`'s chat path. The short version:

- **Retrieval:** [src/rag/retriever.py](src/rag/retriever.py) does brute-force cosine similarity over `REAL[]` embeddings (no ANN index yet); `RAG_MIN_SCORE` is the similarity floor, tuned via `scripts/rag_eval.py`, not guessed.
- **Off-topic questions are gated deterministically before any chat LLM call** — a keyword allowlist first, then a cheap LLM yes/no gate only if that misses. This exists because relying on the chat model itself to decline off-topic questions was unreliable on Taglish input.
- **Numbers shown to the user are never LLM-authored.** `solar_engine.compute()` produces them; the model only writes number-free framing sentences, and a post-generation check discards the model's text (falling back to a deterministic template) if it contains any number that doesn't match a known value.
- Re-indexing after editing `knowledge/solar/*.md` is a manual terminal command (`scripts/build_rag_index.py`), not an app action.

### Blockchain is best-effort, never blocking

Payments and certificates are valid whether or not the Polygon write lands. Failures are logged and surfaced in the UI as "Off-chain" with a re-anchor action — they are never swallowed silently and never abort the transaction. See [src/lms_bp/certificates.py:31-58](src/lms_bp/certificates.py#L31-L58) for the pattern to copy. Network is `amoy` (testnet) by default.

### The marketing site exists twice

[ewize-2026/](ewize-2026/) is a standalone static build (`python build.py` regenerates 15 HTML pages from `content.py`). The **live** version is the Flask one: [src/site_bp.py](src/site_bp.py) + [src/site_content.py](src/site_content.py) + [templates/site/](templates/site/) + `static/ewize.css` + `static/ewize.js`. Edit the Flask side for anything shipping; the static build only matters as a detached deliverable. The two content models must be kept in sync — see [ewize-2026/README.md](ewize-2026/README.md) for the design system ("Instrument": square structure, round controls, dark green-black ground, one paper inversion for schedules).

## Frontend conventions

No build step, no framework. Vanilla ES5-ish scripts in `static/` that self-initialize off `data-` attributes:

- `wizard.js` — multi-step registration forms auto-init from `data-wizard`
- `form-busy.js` — submit-button busy states
- `motion.js` / `interactive.js` / `ewize.js` — `IntersectionObserver`-driven reveals, canvas hero, spotlight cards; all `transform`/`opacity`, no scroll listeners
- Registration uploads are validated by the vision model on file-select via `POST /api/validate-upload`

Templates are Jinja with shared macros in `templates/shared/`. Note [scripts/fix_template_unicode.py](scripts/fix_template_unicode.py) exists because templates have been corrupted by CP1252-as-UTF-8 mojibake before — write template files as UTF-8.

## Git

Never add a `Co-Authored-By: Claude` trailer to commits on this project.
