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

[src/db/core.py](src/db/core.py) `init_db()` is the entire schema: `CREATE TABLE IF NOT EXISTS` plus `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` plus inline backfill `UPDATE`s. It runs on every app start. **There are no migration files** — to add a column, append an idempotent `ALTER` (and its backfill) to `init_db()`. When you change `init_db()`, update the "Database schema" section below in the same change.

[src/db/](src/db/) is a package whose `__init__.py` star-exports every submodule (`core`, `solar`, `registrations`, `users`, `payments`, `lms`, `misc`, `corporate`, `discounts`, `intake`, `checkout`, `shared_registration`, `notifications`, `classes`, `rag`, `workflow`), so callers always write `from db import <anything>`. `get_db()` → connection, `dict_cur(conn)` → `RealDictCursor`; callers close both by hand.

## Database schema

40 tables (not 28 — that count is stale), all defined in [src/db/core.py](src/db/core.py) `init_db()`. Short types; `[a|b|c]` after a column lists the values actually written in code (CHECK constraint, constant, or literal), not a guess.

**Intake** — the public application and its review/correction lifecycle.

- `batches` (training-batch date groups registrations pick from): id serial PK, name varchar(100) NOT NULL, type varchar(30) NOT NULL, start_date date NOT NULL, dates date[], created_at timestamp
- `registrations` (a public form submission): id varchar(8) PK, form_type varchar(30) NOT NULL, form_label varchar(50) NOT NULL, submitted_at timestamp NOT NULL, full_name varchar(200), email varchar(150), training_type varchar(250), batch_id int FK->batches.id, status varchar(20) NOT NULL DEFAULT 'pending' [pending|accepted|rejected|needs_correction], is_qualified smallint NOT NULL DEFAULT 1, selfie_reviewed_at timestamp, selfie_outcome varchar(20) [approved|rejected], documents_purged_at timestamp, correction_note text, correction_version int NOT NULL DEFAULT 0, review_version int NOT NULL DEFAULT 1, gemp_designation varchar(200), plus upload-path columns (photo_id, resume, expired_doe, valid_id, selfie_with_id) varchar(255)
- `account_tokens` (invitation to claim an account): token varchar(64) PK, reg_id varchar(8) NOT NULL FK->registrations.id, email varchar(150) NOT NULL, is_qualified smallint NOT NULL DEFAULT 1, expires_at timestamp NOT NULL (7 days from issue), used_at timestamp, created_at timestamp — unique partial index: at most one unused token per reg_id
- `registration_document_reviews` (evidence kept after an upload is purged): id serial PK, reg_id varchar(8) NOT NULL FK->registrations.id, field varchar(30) NOT NULL, sha256 varchar(64), byte_size bigint, file_ext varchar(10), outcome varchar(20) [approved|rejected|superseded], note varchar(40) [deleted|missing], reviewed_by int FK->users.id, review_version int NOT NULL DEFAULT 1, purged_at timestamp — UNIQUE(reg_id, field, review_version)
- `registration_corrections` (correction requests — src/db/workflow.py): id serial PK, reg_id varchar(8) NOT NULL FK->registrations.id, version int NOT NULL, token_hash varchar(64) NOT NULL UNIQUE, fields text[] NOT NULL, note text NOT NULL, requested_by int FK->users.id, prior_status varchar(20) NOT NULL DEFAULT 'pending', expires_at timestamp NOT NULL DEFAULT now()+7days, used_at timestamp — UNIQUE(reg_id, version)
- `registration_retired_uploads` (superseded upload files awaiting disk cleanup): id serial PK, reg_id varchar(8) NOT NULL FK->registrations.id, field varchar(30) NOT NULL, filename varchar(255) NOT NULL, review_version int NOT NULL, purged_at timestamp, last_error varchar(120) — UNIQUE(reg_id, field, filename)
- `registration_review_history` (append-only per-application audit trail): id serial PK, reg_id varchar(8) NOT NULL FK->registrations.id, review_version int NOT NULL, action varchar(40) NOT NULL, snapshot text NOT NULL, actor_id int FK->users.id, created_at timestamp NOT NULL

**Identity** — accounts and who owns which application.

- `users`: id serial PK, role varchar(20) NOT NULL [admin|super_user|secretary|employee|trainee], fname varchar(100) NOT NULL, lname varchar(100) NOT NULL, email varchar(150) NOT NULL UNIQUE, password_hash varchar(255) NOT NULL, payment_status varchar(10) NOT NULL DEFAULT 'unpaid' [unpaid|paid], training_type varchar(250), failed_login_attempts smallint NOT NULL DEFAULT 0, locked_until timestamp, registration_id varchar(8) FK->registrations.id, created_at timestamp, archived_at timestamp
- `trainee_enrolments` (explicit account↔application link): registration_id varchar(8) PK FK->registrations.id, user_id int NOT NULL FK->users.id, verified_at timestamp NOT NULL
- `user_capabilities` (per-account capability overrides): id serial PK, user_id int NOT NULL FK->users.id, capability varchar(40) NOT NULL, granted smallint NOT NULL, set_by int FK->users.id, set_at timestamp — UNIQUE(user_id, capability)
- `password_reset_tokens`: token varchar(64) PK, email varchar(150) NOT NULL, expires_at timestamp NOT NULL (1 hour from issue), used_at timestamp, created_at timestamp
- `audit_logs` (generic admin/system action log): id serial PK, user_id int FK->users.id, action varchar(150) NOT NULL, entity_type varchar(50), entity_id varchar(50), details text, created_at timestamp

**Billing** — money movement, individual and corporate.

- `payments` (individual PayMongo payment): id serial PK, user_id int NOT NULL FK->users.id, registration_id varchar(8) FK->registrations.id, amount_php numeric(10,2) NOT NULL, method varchar(10) NOT NULL, paymongo_id varchar(120) NOT NULL, status varchar(10) NOT NULL DEFAULT 'pending' [pending|paid|failed], receipt_id varchar(30), receipt_hash varchar(66), tx_hash varchar(66), anchor_version smallint DEFAULT 1, discount_code_id int FK->discount_codes.id, discount_percent smallint, discount_amount_php numeric(10,2), qr_code_path varchar(255), created_at timestamp, paid_at timestamp
- `discount_codes`: id serial PK, code varchar(40) NOT NULL, code_key varchar(40) NOT NULL UNIQUE, percent_off smallint NOT NULL (CHECK 1–100), expires_on date NOT NULL, max_uses int NOT NULL, used int NOT NULL DEFAULT 0, training_type varchar(250), is_active smallint NOT NULL DEFAULT 1, created_by int FK->users.id, created_at timestamp
- `corporate_payments` (one invoice covering several trainees): id serial PK, reference varchar(40) NOT NULL UNIQUE, company_name varchar(200) NOT NULL, list_total_php numeric(12,2) NOT NULL, custom_total_php numeric(12,2), override_by int FK->users.id, amount_centavos bigint NOT NULL, status varchar(20) NOT NULL DEFAULT 'pending' [pending|paid|cancelled|expired], method varchar(10), paymongo_id varchar(120), intake_id int, pay_token_hash varchar(64), link_version int NOT NULL DEFAULT 0, needs_attention_at timestamp, receipt_hash varchar(66), tx_hash varchar(66), anchor_version smallint DEFAULT 2, expires_at timestamp NOT NULL, paid_at timestamp, cancelled_at timestamp, created_by int FK->users.id, created_at timestamp
- `corporate_payment_items` (per-trainee invoice line): id serial PK, corporate_payment_id int NOT NULL FK->corporate_payments.id, user_id int FK->users.id, registration_id varchar(8) FK->registrations.id, training_type varchar(250) NOT NULL, form_type varchar(30), price_php numeric(10,2) NOT NULL, price_label varchar(150), trainee_name varchar(200), trainee_email varchar(150) — UNIQUE(corporate_payment_id, user_id); unique partial index on (corporate_payment_id, registration_id) where set
- `corporate_payment_attempts` (one hosted-checkout attempt): id serial PK, corporate_payment_id int NOT NULL FK->corporate_payments.id, attempt_ref varchar(36) NOT NULL UNIQUE, idempotency_key varchar(255) NOT NULL UNIQUE, request_amount_centavos bigint NOT NULL, environment varchar(10) NOT NULL, status varchar(20) NOT NULL DEFAULT 'creating' [creating|active|expired|paid|failed|unknown], checkout_session_id varchar(120), payment_intent_id varchar(120), idempotency_expires_at timestamp, settlement_confirmed_at timestamp, creation_lease_until timestamp, created_by int FK->users.id, created_at timestamp
- `corporate_payment_events` (per-invoice inline audit trail): id serial PK, corporate_payment_id int NOT NULL FK->corporate_payments.id, actor_id int FK->users.id, action varchar(60) NOT NULL, details text, created_at timestamp
- `unresolved_payment_events` (webhooks that could not be matched/validated): id serial PK, source varchar(20) NOT NULL, event_type varchar(60), checkout_session_id varchar(120), payment_id varchar(120), amount_centavos bigint, reason text NOT NULL, raw_event text NOT NULL, resolved_at timestamp, resolved_by int FK->users.id, resolution_note text, received_at timestamp

**Courseware** — module/quiz/exam definitions a trainer authors.

- `lms_modules`: id serial PK, title varchar(200) NOT NULL, instructor_id int NOT NULL FK->users.id, training_type varchar(250) NOT NULL DEFAULT 'training', is_published smallint NOT NULL DEFAULT 0, sort_order int NOT NULL DEFAULT 0, is_locked smallint NOT NULL DEFAULT 0, created_at timestamp, archived_at timestamp
- `lms_module_files`: id serial PK, module_id int NOT NULL FK->lms_modules.id, filename varchar(255) NOT NULL, original_name varchar(255) NOT NULL, file_type varchar(50), file_size int, uploaded_at timestamp
- `lms_quizzes`: id serial PK, module_id int NOT NULL UNIQUE FK->lms_modules.id, title varchar(200) NOT NULL, time_limit_mins int NOT NULL DEFAULT 30, passing_score int NOT NULL DEFAULT 70, is_ai_generated smallint NOT NULL DEFAULT 0, is_published smallint NOT NULL DEFAULT 0, is_locked smallint NOT NULL DEFAULT 0, created_at timestamp
- `lms_quiz_questions`: id serial PK, quiz_id int NOT NULL FK->lms_quizzes.id, question_text text NOT NULL, question_type varchar(20) NOT NULL DEFAULT 'multiple_choice', correct_answer text, order_num int NOT NULL DEFAULT 0, points int NOT NULL DEFAULT 1
- `lms_quiz_choices`: id serial PK, question_id int NOT NULL FK->lms_quiz_questions.id, choice_text text NOT NULL, is_correct smallint NOT NULL DEFAULT 0
- `lms_practical_exams`: id serial PK, module_id int NOT NULL UNIQUE FK->lms_modules.id, title varchar(200) NOT NULL, instructions text NOT NULL, evaluation_criteria text, requires_camera smallint NOT NULL DEFAULT 0, is_locked smallint NOT NULL DEFAULT 0, created_at timestamp
- `lms_exam_questions`: id serial PK, exam_id int NOT NULL FK->lms_practical_exams.id, question_text text NOT NULL, question_type varchar(20) NOT NULL DEFAULT 'essay', correct_answer text, order_num int NOT NULL DEFAULT 0, points int NOT NULL DEFAULT 1

**Assessments** — a trainee's quiz/progress/certificate records.

- `lms_quiz_attempts`: id serial PK, user_id int NOT NULL FK->users.id, quiz_id int NOT NULL FK->lms_quizzes.id, registration_id varchar(8) FK->registrations.id, started_at timestamp, submitted_at timestamp, score numeric(5,2), tab_switches int NOT NULL DEFAULT 0, completed smallint NOT NULL DEFAULT 0
- `lms_quiz_answers`: id serial PK, attempt_id int NOT NULL FK->lms_quiz_attempts.id, question_id int NOT NULL FK->lms_quiz_questions.id, selected_choice_id int FK->lms_quiz_choices.id, answer_text text
- `lms_progress`: id serial PK, user_id int NOT NULL FK->users.id, module_id int NOT NULL FK->lms_modules.id, registration_id varchar(8) FK->registrations.id, quiz_score numeric(5,2), quiz_passed smallint NOT NULL DEFAULT 0, exam_graded smallint NOT NULL DEFAULT 0, exam_grade int, material_pct smallint NOT NULL DEFAULT 0, completed smallint NOT NULL DEFAULT 0, completed_at timestamp — unique partial indexes on (user_id, module_id, registration_id) and legacy (user_id, module_id) where registration_id IS NULL
- `lms_certificates`: id serial PK, user_id int NOT NULL FK->users.id, registration_id varchar(8) FK->registrations.id, cert_id varchar(32) NOT NULL UNIQUE, issued_at timestamp, expires_at date, approved_by int FK->users.id, tx_hash varchar(66), blockchain_token varchar(255), anchor_version smallint DEFAULT 1
- `feedback`: id serial PK, user_id int NOT NULL FK->users.id, module_id int NOT NULL FK->lms_modules.id, rating smallint NOT NULL, comment text, created_at timestamp — UNIQUE(user_id, module_id)

**Submissions** — practical-exam file submissions and grading.

- `lms_exam_submissions`: id serial PK, user_id int NOT NULL FK->users.id, exam_id int NOT NULL FK->lms_practical_exams.id, registration_id varchar(8) FK->registrations.id, file_path varchar(255), submitted_at timestamp, grade int, feedback text, graded_at timestamp, graded_by int FK->users.id, auto_score numeric(5,2), needs_review smallint NOT NULL DEFAULT 0
- `lms_exam_answers`: id serial PK, submission_id int NOT NULL FK->lms_exam_submissions.id, question_id int NOT NULL FK->lms_exam_questions.id, answer_text text

**Solar/RAG** — Solara consultations and the retrieval corpus behind them.

- `solar_requests`: id serial PK, user_id int FK->users.id, name varchar(200) NOT NULL, email varchar(150) NOT NULL, establishment_type varchar(20) NOT NULL, ownership varchar(10) NOT NULL, electrical_phase varchar(10) NOT NULL, grid_connection varchar(10) NOT NULL DEFAULT 'grid_tie', target_savings varchar(5) NOT NULL DEFAULT '100', monthly_bill_php numeric(10,2), feasibility varchar(20) [feasible|limited|unfeasible|unknown], status varchar(30) NOT NULL DEFAULT 'submitted' [submitted|ai_processed|pending_review|reviewed|completed|quotation_sent], out_of_scope smallint NOT NULL DEFAULT 0, out_of_scope_reason text, created_at timestamp, plus sizing/cost columns (system_size_kw, panel_count, cost_min/max, monthly_savings, roi_years, battery_kwh_capacity and their `final_*` staff-overridden counterparts)
- `rag_chunks`: id serial PK, source_type varchar(30) NOT NULL, source_ref varchar(255) NOT NULL, title varchar(200) NOT NULL, content text NOT NULL, visibility varchar(10) NOT NULL DEFAULT 'public' [public|admin], topic varchar(40), embedding real[] NOT NULL, embed_model varchar(100) NOT NULL, content_hash varchar(64) NOT NULL, updated_at timestamp

**Corporate intake & class workflow** — company roster, notifications, and class join codes.

- `corporate_intakes` (the company intake — src/admin/intake.py): id serial PK, company_name varchar(200) NOT NULL, contact_email varchar(150) NOT NULL, form_type varchar(30) NOT NULL, training_type varchar(250), coord_token_hash varchar(64) UNIQUE, coord_expires_at timestamp, coord_revoked_at timestamp, status varchar(20) NOT NULL DEFAULT 'open' [open|ready|closed|cancelled], payment_link_sent_at timestamp, registration_token_hash varchar(64), registration_expires_at timestamp, registration_revoked_at timestamp, archived_at timestamp, archived_by int FK->users.id, created_by int FK->users.id, created_at timestamp, closed_at timestamp
- `corporate_intake_slots` (one expected trainee, created before they submit): id serial PK, intake_id int NOT NULL FK->corporate_intakes.id, full_name varchar(200) NOT NULL, email varchar(150) NOT NULL, email_key varchar(150) NOT NULL, invite_token_hash varchar(64) UNIQUE, invite_expires_at timestamp, invite_used_at timestamp, invite_revoked_at timestamp, registration_id varchar(8) FK->registrations.id (unique when set), entry_class_id int FK->training_classes.id, entry_code_hash varchar(64), entry_code_expires_at timestamp, entry_code_attempts int NOT NULL DEFAULT 0, created_at timestamp — UNIQUE(intake_id, email_key)
- `corporate_notifications` (company notifications — src/db/notifications.py; durable send intents, leased by `attempt_id`): id serial PK, intake_id int FK->corporate_intakes.id, kind varchar(40) NOT NULL [needs_correction|payment_link|registration_link|trainee_correction], slot_id int FK->corporate_intake_slots.id, to_email varchar(150) NOT NULL, subject varchar(300), status varchar(20) NOT NULL DEFAULT 'queued' [queued|in_flight|previewed|mocked|submitted|failed|uncertain], attempts int NOT NULL DEFAULT 0, last_error text, dedupe_key varchar(120) NOT NULL UNIQUE, attempt_id varchar(36), attempt_started_at timestamp, attempt_expires_at timestamp, transport varchar(20), corporate_payment_id int, link_version int NOT NULL DEFAULT 0, payload text, created_by int FK->users.id, created_at timestamp, sent_at timestamp
- `training_classes` (a cohort and its join code — used by `class_gate()` in src/db/classes.py): id serial PK, name varchar(200) NOT NULL, training_type varchar(250) NOT NULL, program_code varchar(30), intake_id int FK->corporate_intakes.id, corporate_payment_id int FK->corporate_payments.id, join_code varchar(12) NOT NULL UNIQUE, join_open boolean NOT NULL DEFAULT true, instructor_id int FK->users.id, created_by int FK->users.id, created_at timestamp, closed_at timestamp
- `training_class_members` (used by `class_gate()` in src/db/classes.py): id serial PK, class_id int NOT NULL FK->training_classes.id, user_id int NOT NULL FK->users.id, authorised varchar(20) NOT NULL DEFAULT 'roster' [roster|staff], added_by int FK->users.id, joined_at timestamp — UNIQUE(class_id, user_id)

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
| `company` | token-scoped coordinator roster view + shared class registration (`/company/roster/<token>`, `/company/register/<token>`) — no staff auth |
| `corporate_public` | token-scoped corporate invoice payment page — no staff auth |
| `classes` | trainee self-join by class code, cohort progress view |

### The trainee lifecycle (spans most of the codebase)

```
public form (registration.py) → admin review (admin/registrations.py) → emailed token
  → /create-account/<token> (onboarding.py) → payment_status='unpaid'
  → /payment (payment_bp.py, PayMongo) → receipt hashed onto Polygon (blockchain.py)
  → /portal → LMS syllabus by training_type → quizzes + practical exam
  → certificate issued (lms_bp/certificates.py) → anchored on Polygon → QR verify page
```

A corporate trainee has one extra step: their company's **class join code**.
`class_gate()` in [src/db/classes.py](src/db/classes.py) opens the LMS only
once they are in the class their employer booked, and it re-derives that
entitlement on every access — a membership row is not standing authority, so a
later rejection, roster revocation or cancelled invoice closes access without
anyone deleting the row. The code names a class; it never authorises.

Two **documented exceptions** to "a corporate trainee must enter a code":

- **Individual enrolment is never gated.** Someone who paid for themselves is
  on no corporate invoice, so there is no class to join.
- **Access is open until a class exists** for their invoice or intake in that
  programme. If staff have not created one there is no code to enter, and
  denying training already paid for because of an internal gap is the wrong
  failure. The gate appears the moment the class does. This is a real hole in
  the rule and is accepted knowingly.

Two invariants that explain a lot of otherwise-odd code:

- **Account creation is invitation-only.** There is deliberately no email+password signup; a plain one would mint trainees that skipped ID upload, selfie liveness, and admin verification. The token carries the approved `training_type` and `payment_status`. See the comment block in [src/auth.py:74-79](src/auth.py#L74-L79).
- **A trainee's syllabus is decided by `training_type`, not by identity.** `normalize_training_type()` maps registration free text to program codes; `lms_get_modules_for_trainee()` resolves the module list. Trainer-facing and trainee-facing progress both fold through `_progress_steps()` in [src/lms_bp/_shared.py](src/lms_bp/_shared.py) so the two views can never disagree.

### Corporate intake & company workspace

A second lifecycle runs alongside the individual one, for an employer enrolling several trainees at once:

```
admin creates intake (admin/intake.py) → coordinator link (/company/roster/<token>)
  + shared registration link & class code (/company/register/<token>)
  → trainees self-register with the code, or admin adds slots directly
  → ordinary per-trainee admin review (admin/registrations.py — unchanged)
  → corporate invoice covering several accepted trainees (db/corporate.py)
  → /payment/corporate/<token> (corporate_public_bp, PayMongo) → class join code unlocks LMS (db/classes.py)
```

`company_bp` and `corporate_public_bp` are deliberately separate from every
staff blueprint and never import `permissions.require` — their routes are
reached by an unauthenticated coordinator or trainee holding a token, so "is
this route public?" is a structural, module-level fact rather than a
per-function capability check a future edit could get wrong.

Ownership is explicit, never inferred from email: `trainee_enrolments`
([src/db/workflow.py](src/db/workflow.py)) links one account to one
registration, and every read re-checks that link instead of trusting a
session hint as authority. The same module owns correction requests
(`request_correction`/`submit_correction`) — reopening an application for
specific fields without discarding an already-approved identity check.

Company notifications ([src/db/notifications.py](src/db/notifications.py))
are durable intent: a row is inserted before any send is attempted, leased by
a unique `attempt_id` during delivery, and only marked
`submitted`/`previewed`/`mocked` once the transport actually accepted it — a
crash mid-send leaves a retryable row instead of a silently lost email.

The Company Intake / Training tabs in [templates/admin/_corporate_panel.html](templates/admin/_corporate_panel.html)
poll every five seconds and patch in place rather than reload. See
[docs/INTAKE_LIVE_UPDATES.md](docs/INTAKE_LIVE_UPDATES.md) for exactly what
those GET endpoints are (and are not) allowed to do — they never contact
PayMongo, send mail, or settle a payment; only a verified webhook can do that.

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

## Behaviour facts

- **Login lockout:** 5 failed attempts (`MAX_LOGIN_ATTEMPTS` in [src/db/users.py](src/db/users.py)) locks the account for 5 minutes (`LOCKOUT_MINUTES`), tracked on `users.failed_login_attempts` / `users.locked_until`.
- **Token expiry:** `account_tokens.expires_at` is 7 days from issue; `password_reset_tokens.expires_at` is 1 hour from issue (both in [src/db/users.py](src/db/users.py)).
- **Certificates are minted as soulbound ERC-721 tokens**, not just a hash anchor — see [contracts/EnergyWizeCertificate.sol](contracts/EnergyWizeCertificate.sol) (`_update()` reverts any transfer/burn; only `mint()`, called by the contract owner, succeeds) and [src/blockchain_utils.py](src/blockchain_utils.py) `store_certificate_hash()`. `lms_certificates.blockchain_token` stores the minted token id (falls back to a plain hash-on-chain anchor, storing `cert_id` instead of a token id, only if `store_certificate_hash()` cannot mint — e.g. `NFT_CONTRACT_ADDRESS` unset or the mint call fails). The deployed contract address is read from env var `NFT_CONTRACT_ADDRESS` — not hardcoded, and not checked into the repo (`.env` is gitignored), but the local `.env` currently sets it to `0xf78d8F66E84Ee66aef446B91E300bF8c47BE32AD` on Polygon Amoy.
- **Certificate issuance is staff-triggered, not automatic.** Finishing a module only makes a trainee *eligible* (`lms_get_eligible_for_cert()`); an instructor/admin with the right capability must POST `/lms/certificates/issue/<user_id>` ([src/lms_bp/certificates.py](src/lms_bp/certificates.py)), which stamps `approved_by` with that staff member's `user_id`.
- **Solara chat does not require sign-in.** `/solar/chat` and `/solar/chat/msg` ([src/solar_bp.py](src/solar_bp.py)) carry no session/login check; a signed-in user's name/email are only used to prefill the form if present.
- **Admin Export Reports produces `.xlsx`** (via `openpyxl`) for every report — registrations, users, payments, LMS progress, solar requests. See [src/admin/exports.py](src/admin/exports.py). No CSV or PDF export path exists for these.
- **No production host is configured in the repo.** [Procfile](Procfile) runs `gunicorn --chdir src app:app`, deployable to Render, Azure, or similar, but there is no committed `render.yaml`/`fly.toml`/live URL. [docs/DEPLOY_RENDER.md](docs/DEPLOY_RENDER.md) and `docs/DEPLOY_AZURE.md` are setup guides, not records of a live deployment; `base_url()` ([src/utils.py](src/utils.py)) falls back to the incoming request's host unless `APP_BASE_URL` is set at deploy time.

## Frontend conventions

No build step, no framework. Vanilla ES5-ish scripts in `static/` that self-initialize off `data-` attributes:

- `wizard.js` — multi-step registration forms auto-init from `data-wizard`
- `form-busy.js` — submit-button busy states
- `motion.js` / `interactive.js` / `ewize.js` — `IntersectionObserver`-driven reveals, canvas hero, spotlight cards; all `transform`/`opacity`, no scroll listeners
- Registration uploads are validated by the vision model on file-select via `POST /api/validate-upload`

Templates are Jinja with shared macros in `templates/shared/`. Note [scripts/fix_template_unicode.py](scripts/fix_template_unicode.py) exists because templates have been corrupted by CP1252-as-UTF-8 mojibake before — write template files as UTF-8.

## Git

Never add a `Co-Authored-By: Claude` trailer to commits on this project.
