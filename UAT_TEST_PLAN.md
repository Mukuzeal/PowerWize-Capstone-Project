# PowerWize — System Test Plan

**Scope:** every route and flow in the application (~100 endpoints, 6 capstone objectives)
**Last updated:** 2026-08-27
**Owner:** Jan McZeal Bandao

Work top to bottom. Sections 0–2 gate everything else — if the preflight fails, later
results are meaningless. Each test has an ID so you can record pass/fail against it.

Legend for the **Needs** column:
`DB` local Postgres · `AI` LM Studio on :1234 · `PAY` PayMongo test keys ·
`CHAIN` Polygon Amoy testnet · `MAIL` SMTP credentials

---

## 0. Preflight — read this first

### 0.1 Known blockers in the current environment

These will make specific tests fail for environmental reasons, not defects. Resolve or
consciously skip before you start.

| # | Issue | Effect | Fix |
|---|---|---|---|
| B1 | `.env`'s `DATABASE_URL` points at role **`McZeal`**, which does not exist in the Laragon cluster | App cannot connect at all | Change the user in `DATABASE_URL` to `postgres`, or `CREATE ROLE "McZeal" LOGIN SUPERUSER;` |
| B2 | `AI_PROVIDER`, `TEXT_PROVIDER`, `VISION_PROVIDER` are all **`lmstudio`** at `localhost:1234` | Every AI test (§9, §11, §12, §5.2) fails if LM Studio is not running | Start LM Studio with `qwen/qwen3-vl-8b`, **or** set the three vars to `groq` (`GROQ_API_KEY` is populated) |
| B3 | `PAYMONGO_WEBHOOK_SECRET` is **empty** | `/payment/webhook` cannot verify signatures | Populate it, or skip T-PAY-07 |
| B4 | `solar_requests` table is **empty (0 rows)** | Nothing to review in §11.3 and the trainer's Solar pane | Create one via T-SOL-01 before testing the review flow |
| B5 | Only **2 of 8 trainees are `paid`** | Unpaid trainees are redirected `/portal → /payment`, so you cannot reach the portal as them | Use a paid trainee, or run T-PAY-01 first |
| B6 | `Handoff.md` lists accounts that **do not exist** (`trainer@energywize.com`, `student@energywize.com`) | Login attempts fail and look like an auth bug | Use §0.3 instead. Consider correcting `Handoff.md`. |
| B7 | `Handoff.md` §12 references five docs that are **absent** from the repo: `ALIGNMENT_ASSESSMENT.md`, `ISO_25010_QUALITY_REPORT.md`, `REGISTRATION_CRITERIA.md`, `DEVELOPMENT_ENVIRONMENT.md`, and this file (now created) | Capstone traceability gap | Write them, or drop the references |

### 0.2 Start the stack

```bash
# 1. Postgres (Laragon build, Windows)
"C:\laragon\bin\postgresql\postgresql-18.4-1-windows-x64\bin\pg_ctl.exe" \
  -D "C:\laragon\data\postgresql" start

# 2. Confirm the DB answers and has data
psql -U postgres -d powerwize -c "select role, count(*) from users where archived_at is null group by role;"

# 3. LM Studio  ->  load qwen/qwen3-vl-8b, start the server on :1234
curl http://localhost:1234/v1/models

# 4. App
cd src && ../venv/Scripts/python.exe app.py      # http://127.0.0.1:5000
```

**Baseline data** as of writing — use it to spot unintended mutations:

| Table | Rows |
|---|---|
| users (active) | 12 — 2 admin, 2 employee, 8 trainee |
| registrations | 32 — 16 pending, 11 accepted, 5 rejected |
| lms_modules (published) | 8 |
| lms_quizzes / lms_practical_exams | 13 / 8 |
| lms_certificates | 1 |
| solar_requests | 0 |
| payments | 1 |
| batches | 14 |

### 0.3 Accounts

Passwords are not recorded here. If you do not have them, reset one directly:

```bash
cd src && ../venv/Scripts/python.exe -c "
from werkzeug.security import generate_password_hash
from db import get_db
c=get_db();cur=c.cursor()
cur.execute('UPDATE users SET password_hash=%s WHERE email=%s',
            (generate_password_hash('NEW_PASSWORD_HERE'), 'patricia.v@ewize.com'))
c.commit(); print('reset')"
```

| Role | Email | Notes |
|---|---|---|
| Admin | `admin@ewize.com` | System admin |
| Admin | `admin@energywize.demo` | Demo admin |
| Employee (trainer) | `patricia.v@ewize.com` | Owns modules — use for §10 |
| Employee (trainer) | `roberto.delacruz@ewize.com` | Second trainer, for ownership-isolation tests |
| Trainee — **paid, 100% done, has cert** | `miguel.torres@gmail.com` | Best case for §7, §12 |
| Trainee — **paid, 0% done** | `yivoveh244@bitmah.com` | Zero-state for §7 |
| Trainee — unpaid | `ana.cruz@yahoo.com` (+5 others) | Use for the payment gate, T-AUTH-06 |

---

## 1. Smoke test — 3 minutes

Fail here and stop; everything downstream is invalid.

| ID | Step | Expected |
|---|---|---|
| T-SMK-01 | `GET /` | 200, landing page, dark substrate, no unstyled flash |
| T-SMK-02 | Open DevTools → Console on `/` | No errors, no failed asset requests |
| T-SMK-03 | `GET /auth` | Login page renders |
| T-SMK-04 | Log in as admin | Redirects to `/admin` |
| T-SMK-05 | Log in as employee | Redirects to `/employee` |
| T-SMK-06 | Log in as paid trainee | Redirects to `/portal` |
| T-SMK-07 | `tail -f app.log` during the above | No tracebacks |

---

## 2. Authentication & access control

The highest-value section — these are the tests that catch real security defects. There
are 76 role guards across the codebase; these probe the boundaries.

| ID | Step | Expected | Needs |
|---|---|---|---|
| T-AUTH-01 | Log in with a wrong password | "Invalid email or password." Generic — must **not** reveal whether the email exists | DB |
| T-AUTH-02 | Log in with an empty email / empty password | Field-level validation messages | DB |
| T-AUTH-03 | Log in as an **archived** user | Rejected (query filters `archived_at IS NULL`) | DB |
| T-AUTH-04 | `/auth/logout` then press Back | Cannot reach the dashboard; bounced to `/auth` | |
| T-AUTH-05 | Signed out, `GET /portal`, `/admin`, `/employee`, `/lms/learn` | Each redirects to `/auth` | |
| T-AUTH-06 | As an **unpaid** trainee, `GET /portal` | 302 → `/payment` | DB |
| T-AUTH-07 | **As trainee**, `GET /admin` | Redirect/403 — never the admin page | DB |
| T-AUTH-08 | **As trainee**, `GET /employee` | Redirect to `/auth` | DB |
| T-AUTH-09 | **As employee**, `GET /admin` | Redirect — employees are not admins | DB |
| T-AUTH-10 | **As trainee**, `POST /lms/modules/1/delete` (curl, valid CSRF) | 403 — must not delete | DB |
| T-AUTH-11 | **As trainee**, `GET /lms/certificates/manage` | 403 | DB |
| T-AUTH-12 | **As employee A**, open a module owned by **employee B** (`/lms/modules/<id>/edit`) | Blocked by `_owns_module()` | DB |
| T-AUTH-13 | **As trainee**, `GET /lms/submissions/<id>/answers` for someone else's submission | Blocked | DB |
| T-AUTH-14 | Strip the `csrf_token` from any POST and submit | 400 CSRF error | |
| T-AUTH-15 | Tamper one character of the `session` cookie | Session rejected, treated as signed out | |
| T-AUTH-16 | Log in in two browsers, log out of one | Other session behaves per design (document which) | |

### 2.1 Password recovery

| ID | Step | Expected | Needs |
|---|---|---|---|
| T-PWD-01 | `/forgot-password` with a known email | Success message; token row created | DB, MAIL |
| T-PWD-02 | Same with an unknown email | **Same** message — no account enumeration | DB |
| T-PWD-03 | Follow the emailed link → `/reset-password/<token>` | Form renders | MAIL |
| T-PWD-04 | Set a new password, then log in with it | Works; old password rejected | DB |
| T-PWD-05 | Reuse the same token twice | Second attempt rejected (`mark_reset_token_used`) | DB |
| T-PWD-06 | Use a garbage/expired token | Rejected cleanly, no traceback | DB |

---

## 3. Public marketing site

| ID | Route | Expected |
|---|---|---|
| T-PUB-01 | `/` | Hero, stats, capability bento, method steps, schedule, CTA all render |
| T-PUB-02 | `/about`, `/contact` | Render; contact details match `site_content.py` |
| T-PUB-03 | `/capabilities` and each `/capabilities/<slug>` | All resolve, no 404 |
| T-PUB-04 | `/programs` and each `/programs/<code>` | All resolve |
| T-PUB-05 | Public schedule table on `/` | Matches the `batches` table (14 rows); empty state shows if none |
| T-PUB-06 | Nav rail at ≥1101px | Sliding indicator tracks hover, `aria-current` on the active page |
| T-PUB-07 | Burger menu at ≤1100px | Panel slides from the right; swipe-to-dismiss works on touch |
| T-PUB-08 | Signed out, click "Sign in" | → `/auth` |
| T-PUB-09 | Signed in as each role, check the nav's account link | admin→`/admin`, employee→`/employee`, trainee→`/portal` |
| T-PUB-10 | Scroll the whole page | Reveals fire once, no layout shift, no jank |
| T-PUB-11 | Footer links | All resolve |

---

## 4. Registration (SO1)

Five form types: `/training`, `/cea-training`, `/renewalCEA`, `/renewalCEM`, `/gemp-lgu`, `/gemp-oge`.

| ID | Step | Expected | Needs |
|---|---|---|---|
| T-REG-01 | Open each of the six registration pages | Multi-step wizard initialises via `data-wizard` | |
| T-REG-02 | Click Next with required fields empty | Blocked; invalid field shakes and is announced | |
| T-REG-03 | Next → Back → Next | Entered data survives; direction-aware transition | |
| T-REG-04 | Enter a malformed email / phone | Rejected client-side and server-side | |
| T-REG-05 | Upload a valid ID image | Groq/LM Studio vision check runs via `/api/validate-upload`; readout shows accepted | AI |
| T-REG-06 | Upload a blurred or wrong-document image | Rejected with a reason | AI |
| T-REG-07 | Upload a non-image (e.g. `.exe` renamed) | Rejected | |
| T-REG-08 | Selfie / liveness widget | Captures; `/api/face-match` compares against the ID | AI |
| T-REG-09 | Submit a complete form | Row appears in `registrations` with `status='pending'`; file saved under `uploads/` | DB |
| T-REG-10 | Submit the same email twice | Handled per `REGISTRATION_CRITERIA.md` rules — document actual behaviour | DB |
| T-REG-11 | Disable JS and submit | Server-side validation still rejects bad input | |

---

## 5. Onboarding → account creation

| ID | Step | Expected | Needs |
|---|---|---|---|
| T-ONB-01 | Admin accepts a pending registration (§8) | Token generated, email sent | DB, MAIL |
| T-ONB-02 | Open `/create-account/<token>` | Form pre-filled with the approved details | DB |
| T-ONB-03 | Set a password meeting the policy | User created with the `training_type` and `payment_status` approved for | DB |
| T-ONB-04 | Reuse the same token | Rejected | DB |
| T-ONB-05 | Use an invalid token | Clean error, no traceback | DB |
| T-ONB-06 | Confirm there is **no** public self-registration route | Only the invitation path exists (`auth.py` comment) | |

---

## 6. Payment (SO5)

| ID | Step | Expected | Needs |
|---|---|---|---|
| T-PAY-01 | As an unpaid trainee, land on `/payment` | Fee shows ₱5,000 (`TRAINING_FEE`) | DB |
| T-PAY-02 | Card flow: `/payment/card/initiate` → `method` → `attach` → `return` | Redirects through PayMongo test 3DS, returns success | PAY |
| T-PAY-03 | Use a PayMongo **declining** test card | `/payment/failed`, user stays unpaid | PAY |
| T-PAY-04 | QR Ph: `/payment/qrph/initiate`, then poll | QR renders; `/payment/qrph/poll/<pi_id>` reports status | PAY |
| T-PAY-05 | Complete a payment | `payments` row written; user `payment_status='paid'`; receipt QR generated in `static/receipts/` | PAY, DB |
| T-PAY-06 | `/payment/success` | Receipt with QR renders | DB |
| T-PAY-07 | `POST /payment/webhook` with a signed payload | Verified and processed — **blocked by B3** | PAY |
| T-PAY-08 | `/verify` — scan/enter the receipt code | Verifies against the record | DB |
| T-PAY-09 | `/verify` with a forged code | Reports invalid | DB |
| T-PAY-10 | After paying, retry `/portal` | Reaches the portal, no longer redirected | DB |

---

## 7. Trainee portal — `/portal` *(redesigned)*

Sign in as **`miguel.torres@gmail.com`** (paid, 100%, has a certificate).

| ID | Step | Expected | Needs |
|---|---|---|---|
| T-POR-01 | Load `/portal` | Instrument styling; continuous with the landing page — no palette or type seam | DB |
| T-POR-02 | Syllabus progress panel | Large mono %, `N / M modules`, meter filled to match | DB |
| T-POR-03 | **Cross-check**: open `/lms/progress` in another tab | Percentages **identical** — both use `_progress_steps` | DB |
| T-POR-04 | Enrolment strip | Payment, programme, training mode, registration status as pills | DB |
| T-POR-05 | Module list | One row per module, per-module step meter, next outstanding step named | DB |
| T-POR-06 | A finished module's row | Reads "Completed", no next step | DB |
| T-POR-07 | Click a module row | → `/lms/learn/<id>` for that module | DB |
| T-POR-08 | Certificate block | "Issued", with issue and expiry dates; tile links to `/lms/certificates` | DB |
| T-POR-09 | Sign in as **`yivoveh244@bitmah.com`** (0%) | 0%, "Not yet issued", counts remaining modules | DB |
| T-POR-10 | Trainee with **no** registration | "No registration found for <email>" — no crash | DB |
| T-POR-11 | Trainee with **no** modules | Progress panel and module list omitted entirely; page still coherent | DB |
| T-POR-12 | All action tiles: learning, progress, quotation, receipt, verify | Each navigates correctly | DB |
| T-POR-13 | Every card visible on load without scrolling first | Nothing stuck at `opacity: 0` — the `data-reveal-off` opt-out | |
| T-POR-14 | Sign in as employee, `GET /portal` | Redirected to `/employee` (no staff block on this page any more) | DB |

---

## 8. Admin dashboard — `/admin`

| ID | Area | Expected | Needs |
|---|---|---|---|
| T-ADM-01 | Load `/admin` | Loads; theme toggle persists across reload (`powerwize-theme`) | DB |
| T-ADM-02 | Light **and** dark mode across every section | Readable, no invisible text, adequate contrast | |
| T-ADM-03 | Registrations list | All 32 rows; filters by pending/accepted/rejected work | DB |
| T-ADM-04 | Accept a registration | Status flips, audit row written, onboarding email sent | DB, MAIL |
| T-ADM-05 | Reject a registration | Status flips; trainee informed | DB |
| T-ADM-06 | Selfie approve / reject | Updates the record | DB |
| T-ADM-07 | Users: archive → unarchive | Archived user disappears from active lists, then returns | DB |
| T-ADM-08 | Delete a user | Removed; verify FK dependants behave (see Handoff "Red Flags") | DB |
| T-ADM-09 | Schedules: add a batch | Appears here **and** on the public `/` schedule | DB |
| T-ADM-10 | Delete a batch | Removed from both | DB |
| T-ADM-11 | `/admin/analytics` | Charts render in both themes; numbers match the DB | DB |
| T-ADM-12 | Audit log (`/admin/audit-log-json`) | Records the actions taken above | DB |
| T-ADM-13 | Feedback (`/admin/feedback-json`) | Returns trainee module feedback | DB |
| T-ADM-14 | Each export: users, registrations, payments, solar-requests, lms-progress | `.xlsx` downloads, opens, row counts match | DB |
| T-ADM-15 | `/admin/solar` and `/admin/solar/<id>` | Lists requests; detail view opens — **needs B4** | DB |
| T-ADM-16 | Flatpickr date pickers | Themed correctly in both modes | |

---

## 9. Trainer console — `/employee` *(redesigned)*

Sign in as **`patricia.v@ewize.com`**.

### 9.1 Shell and navigation

| ID | Step | Expected |
|---|---|---|
| T-TRN-01 | Load `/employee` | Instrument styling — dark substrate, hairlines, mono labels, square panels / round controls |
| T-TRN-02 | Click each of the 5 rail items | Correct pane shows; exactly one visible at a time |
| T-TRN-03 | Check the URL after clicking | Hash updates (`#modules`, `#submissions`, …) |
| T-TRN-04 | Press **Back** | Returns to the previous pane |
| T-TRN-05 | **Refresh** on `#progress` | Still on Trainee progress |
| T-TRN-06 | Paste `/employee#solar` into a fresh tab | Opens directly on Solar |
| T-TRN-07 | Bad hash: `/employee#nonsense` | Falls back to Dashboard, no error |
| T-TRN-08 | Four "Jump to" tiles on the Dashboard | Each switches to its pane |
| T-TRN-09 | DevTools Console | No JS errors |
| T-TRN-10 | Run `document.querySelectorAll('[style]').length` | Only meter fills (`--pct`) — no leftover inline styling |

### 9.2 Modules

| ID | Step | Expected | Needs |
|---|---|---|---|
| T-TRN-11 | Modules pane | Only **this trainer's** modules; live and archived separated | DB |
| T-TRN-12 | Published vs Draft pills | Green vs amber, correct per `is_published` | DB |
| T-TRN-13 | Manage | → `/lms/modules/<id>` | DB |
| T-TRN-14 | Archive → confirm | Module moves to Archived; hidden from trainees (verify as a trainee) | DB |
| T-TRN-15 | Archive → **cancel** | Nothing changes | |
| T-TRN-16 | Restore | Returns to live | DB |
| T-TRN-17 | Delete (live) → confirm | Deleted via the hidden CSRF form | DB |
| T-TRN-18 | Delete archived permanently | Removed | DB |
| T-TRN-19 | Trainer with zero modules | Empty state renders (not a blank pane) | DB |

### 9.3 Submissions, solar, progress

| ID | Step | Expected | Needs |
|---|---|---|---|
| T-TRN-20 | Exam submissions table | Trainee, module, date, grade; only this trainer's modules | DB |
| T-TRN-21 | A submission graded **0** | Shows "0%", **not** "Pending" | DB |
| T-TRN-22 | Header count | "N awaiting a grade" counts only ungraded | DB |
| T-TRN-23 | Review → grade → return | Grade persists and shows | DB |
| T-TRN-24 | Solar pane filter pills | Rows filter; counts correct; "Nothing matches that filter" when empty — **needs B4** | DB |
| T-TRN-25 | Status labels | "AI processed", not "Ai Processed" | DB |
| T-TRN-26 | **Trainee progress pane** | 8 rows — one per active trainee. *This was permanently empty before the fix.* | DB |
| T-TRN-27 | Percentages down the column | **Differ** per trainee — not one repeated number | DB |
| T-TRN-28 | Next-step text | Differs by trainee (e.g. "Pass the quiz" vs "Open the material") | DB |
| T-TRN-29 | Cross-check one trainee against their own `/lms/progress` | Identical percentage | DB |
| T-TRN-30 | A trainee whose training type has no modules | "No modules published for … yet" — no divide-by-zero | DB |

---

## 10. LMS

### 10.1 Trainee side (SO2)

| ID | Step | Expected | Needs |
|---|---|---|---|
| T-LMS-01 | `/lms/learn` | Only modules for this trainee's training type, published only | DB |
| T-LMS-02 | Open a module | Content, files, quiz and exam sections render | DB |
| T-LMS-03 | Download a material file | `/lms/files/<name>` serves it | DB |
| T-LMS-04 | Opening a module | Marks the "study" step done | DB |
| T-LMS-05 | Take a quiz, pass it | `quiz_passed` set; progress advances | DB |
| T-LMS-06 | Take a quiz, fail it | Recorded; retry policy behaves as designed | DB |
| T-LMS-07 | Quiz hints | AI hint returns | AI |
| T-LMS-08 | Switch browser tabs mid-quiz | `/quiz/tabswitch` logs it | DB |
| T-LMS-09 | Submit a practical exam | File accepted, submission recorded | DB |
| T-LMS-10 | Module chat (`/lms/chat/<id>/msg`) | AI answers grounded in module content | AI |
| T-LMS-11 | Leave module feedback (1–5 + comment) | Saved; visible to admin | DB |
| T-LMS-12 | Rating outside 1–5 via curl | 400 | DB |
| T-LMS-13 | `/lms/progress` | Per-module checklists correct | DB |
| T-LMS-14 | Complete everything | All modules complete; eligible for a certificate | DB |

### 10.2 Instructor side

| ID | Step | Expected | Needs |
|---|---|---|---|
| T-LMS-15 | `/lms/modules/create` | Module created | DB |
| T-LMS-16 | Edit a module | Changes persist | DB |
| T-LMS-17 | Upload a material file | Stored under `src/uploads/lms/`, listed | DB |
| T-LMS-18 | Delete a file | Removed | DB |
| T-LMS-19 | Publish / unpublish | Visibility to trainees flips | DB |
| T-LMS-20 | **AI quiz generation** from module content | Questions generated (10–30s) | AI |
| T-LMS-21 | Request a specific question count | Honoured | AI |
| T-LMS-22 | Edit generated questions and save | Persist — **do not rename `quiz_manage.html` field names** (Handoff "Red Flags") | DB |
| T-LMS-23 | Create a practical exam | Saved | DB |
| T-LMS-24 | `/lms/submissions` → grade with feedback | Trainee sees the grade | DB |
| T-LMS-25 | Upload a disallowed extension | Rejected (`ALLOWED_MATERIAL` / `ALLOWED_SUBMISSION`) | |

---

## 11. Solar PV consultation (SO3)

| ID | Step | Expected | Needs |
|---|---|---|---|
| T-SOL-01 | `/solar` — submit a request | Row created; **clears blocker B4** | DB |
| T-SOL-02 | Upload an electricity bill → `/solar/ocr` | OCR extracts kWh/amount | AI |
| T-SOL-03 | Upload an unreadable bill | Graceful failure, manual entry still possible | AI |
| T-SOL-04 | `/solar/result/<id>` | Sizing, feasibility and cost readout | DB |
| T-SOL-05 | Sanity-check the sizing | Output plausible for the input consumption | |
| T-SOL-06 | Solara chat `/solar/chat` | Conversational sizing; openers cascade in | AI |
| T-SOL-07 | Solara with LM Studio **stopped** | Fails gracefully — no hung spinner | |
| T-SOL-08 | Staff review `/admin/solar/<id>` → `/review` | Status advances ai_processed → pending_review → reviewed → quotation_sent | DB |
| T-SOL-09 | `/solar/decision/<id>` | Records the decision | DB |
| T-SOL-10 | Each status in the trainer's Solar pane | Correct pill colour and label | DB |

---

## 12. Certificates & blockchain (SO4)

| ID | Step | Expected | Needs |
|---|---|---|---|
| T-CER-01 | `/lms/certificates/manage` as instructor | Lists issued certs and eligible trainees | DB |
| T-CER-02 | Issue a certificate | Row created; `cert_id` is a 32-char hex token | DB |
| T-CER-03 | Expiry date | Exactly **3 years** after issue | DB |
| T-CER-04 | Blockchain write | `tx_hash` and `blockchain_token` populated | CHAIN |
| T-CER-05 | Look up the tx on `amoy.polygonscan.com` | Transaction exists | CHAIN |
| T-CER-06 | Blockchain **unreachable** | Certificate still issues; write fails silently by design | |
| T-CER-07 | `/lms/certificates` as the trainee | Certificate renders with QR | DB |
| T-CER-08 | Scan the QR | Opens `/lms/certificates/verify/<cert_id>` | |
| T-CER-09 | Public verify page | Shows holder, dates, validity — **signed out** | DB |
| T-CER-10 | Verify a forged `cert_id` | Reports invalid | DB |
| T-CER-11 | Issue twice to the same user | No duplicate (guarded by `lms_get_certificate`) | DB |
| T-CER-12 | Portal certificate block within 90 days of expiry | Reads "Expiring soon" + day count | DB |
| T-CER-13 | Portal block past expiry | Reads "Expired" | DB |

To test T-CER-12/13 without waiting three years:

```sql
UPDATE lms_certificates SET expires_at = CURRENT_DATE + 45 WHERE user_id = <id>;  -- expiring
UPDATE lms_certificates SET expires_at = CURRENT_DATE - 10 WHERE user_id = <id>;  -- expired
```

---

## 13. Cross-cutting

### 13.1 Responsive

Check `/`, `/portal`, `/employee`, `/admin` at **375**, **768**, **900**, **1440** px.

| ID | Check | Expected |
|---|---|---|
| T-RSP-01 | Horizontal scroll | None at any width — `scrollWidth <= innerWidth` |
| T-RSP-02 | Trainer rail below 900px | Collapses to an icon strip, active marker still visible |
| T-RSP-03 | Tables on mobile | Scroll inside `.sched__wrap`, page itself does not |
| T-RSP-04 | Card actions on mobile | Wrap; delete stays compact |
| T-RSP-05 | Tap targets | ≥44px |

### 13.2 Accessibility

| ID | Check | Expected |
|---|---|---|
| T-A11Y-01 | Keyboard-only through each dashboard | Every control reachable; visible focus ring; no traps |
| T-A11Y-02 | DevTools → Rendering → `prefers-reduced-motion: reduce` | No travel anywhere; state still legible; meters still show values |
| T-A11Y-03 | `prefers-reduced-transparency: reduce` | Translucent surfaces go solid |
| T-A11Y-04 | Screen reader on the trainer rail | Announces the active section (`aria-current`) |
| T-A11Y-05 | Progress meters | Announce as progressbars with their value |
| T-A11Y-06 | Contrast audit (Lighthouse / axe) | Body text ≥7:1, UI ≥3:1 |
| T-A11Y-07 | Icon-only buttons | Have `aria-label` |
| T-A11Y-08 | Lighthouse Accessibility score | Record it per page |

### 13.3 Security

| ID | Check | Expected |
|---|---|---|
| T-SEC-01 | `<script>alert(1)</script>` into every free-text field | Escaped on render, never executed |
| T-SEC-02 | `' OR 1=1 --` into login and search fields | No SQL injection (queries are parameterised) |
| T-SEC-03 | Path traversal on `/lms/files/../../.env` | Blocked |
| T-SEC-04 | Upload a `.php`/`.exe` renamed to `.pdf` | Rejected |
| T-SEC-05 | `git log -p` / `git show` for secrets | `.env` never committed |
| T-SEC-06 | Response headers | No stack traces or server internals leaked |
| T-SEC-07 | Direct object reference: change an `<id>` in a URL to another user's | Blocked |

### 13.4 Performance

| ID | Check | Target |
|---|---|---|
| T-PRF-01 | Landing page load | < 2s |
| T-PRF-02 | Dashboard load | < 2s |
| T-PRF-03 | AI quiz generation | 10–30s (known, per Handoff) |
| T-PRF-04 | Blockchain write | ~5s+ (known) |
| T-PRF-05 | Animation smoothness | 60fps, no dropped frames |
| T-PRF-06 | `/employee` with many trainees | Progress query stays reasonable — it is one query per trainee plus one per training type |

---

## 14. Regression — the recent dashboard redesign

Re-run after any change to `ewize.css`, `ewize-forms.css`, `ewize-dash.css` or `ewize.js`,
since all four are shared with the public site and the registration flow.

| ID | Check | Expected |
|---|---|---|
| T-REG-A | Registration wizards still animate | `data-reveal-off` did **not** disable form pages — only `/portal` |
| T-REG-B | Solar result and receipt pages | Still 42rem wide — `.portal` widening must not leak |
| T-REG-C | Landing page reveals | Still fire on scroll |
| T-REG-D | Status pills everywhere | Consistent across portal, trainer, admin, solar |
| T-REG-E | Empty states | `.emptystate` now styled — check the public schedule too |
| T-REG-F | Flash banners | `.flash-banner` now styled — trigger one and confirm |

---

## Recording results

| ID | Result | Notes | Tester | Date |
|---|---|---|---|---|
| T-SMK-01 | ☐ Pass ☐ Fail | | | |
| … | | | | |

For the capstone, summarise as: total cases, pass rate, defects by severity, and map each
section to its Specific Objective — §4 → SO1, §10 → SO2, §11 → SO3, §12 → SO4, §6 → SO5,
and this whole document → SO6.
