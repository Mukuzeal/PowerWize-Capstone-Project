# PowerWize — Hands-on Walkthrough

One continuous session where you follow a single person from *never heard of EnergyWize*
to *certified, with a solar quotation*. Every role and nearly every screen gets touched,
in the order a real user would hit them, so each step sets up the next.

**Time:** ~90 minutes end to end. Each act stands alone if you want to skip around, except
Acts 2–5, which are one chain.

---

## Prep — 5 minutes

### 1. Fix the database connection

`.env` points `DATABASE_URL` at a Postgres role named `McZeal` that doesn't exist in your
Laragon cluster. Change the user to `postgres`:

```
DATABASE_URL=postgresql://postgres@localhost:5432/powerwize
```

### 2. Start Postgres

```bash
"C:\laragon\bin\postgresql\postgresql-18.4-1-windows-x64\bin\pg_ctl.exe" \
  -D "C:\laragon\data\postgresql" start
```

### 3. Decide about AI

`.env` currently routes all AI at LM Studio on `localhost:1234`. Either start LM Studio with
`qwen/qwen3-vl-8b`, **or** switch to Groq (your key is already set):

```
AI_PROVIDER=groq
TEXT_PROVIDER=groq
VISION_PROVIDER=groq
```

Affects: upload validation, face match, quiz generation, quiz hints, module chat, bill OCR,
Solara. Everything else works without it.

### 4. Test accounts — already set up

Four accounts are live and verified: each logs in through the real form and reaches its
dashboard.

> **Passwords are deliberately not written here.** This file is committed to the
> repository, and an earlier version of `demo_credentials.txt` put working passwords into
> git history. Read them from **`demo_credentials.txt`** at the project root, which is
> gitignored. It also carries the PayMongo test card numbers used in Act 5.

| Role | Email | Lands on | Why this one |
|---|---|---|---|
| **Admin** | `admin@ewize.com` | `/admin` | Full oversight |
| **Trainer** | `patricia.v@ewize.com` | `/employee` | Owns modules and submissions |
| **Trainee** | `miguel.torres@gmail.com` | `/portal` | Paid, 100% done, holds certificate NFT #2 — best case |
| **Trainee** | `yivoveh244@bitmah.com` | `/portal` | Paid, 0% progress — the zero state |

Two more, for the access-control checks in Act 11 (passwords not set, you only need them
as *targets*):

| Purpose | Email |
|---|---|
| Second trainer, for ownership isolation | `roberto.delacruz@ewize.com` |
| Unpaid trainee, for the payment gate | `ana.cruz@yahoo.com` |

To reset any password later:

```bash
cd src && ../venv/Scripts/python.exe -c "
from werkzeug.security import generate_password_hash as h
from db import get_db
c=get_db(); cur=c.cursor()
cur.execute('UPDATE users SET password_hash=%s WHERE email=%s', (h('NEW_PASSWORD_HERE'), 'EMAIL_HERE'))
c.commit(); print('done')"
```

### 4b. A schema fix has been applied

`/admin` crashed on every request with `column "selfie_with_id" does not exist`. The column
is declared in `src/db/core.py`, but `init_db()` uses `CREATE TABLE IF NOT EXISTS`, so it
was never added to this already-existing database. Fixed with:

```sql
ALTER TABLE registrations ADD COLUMN IF NOT EXISTS selfie_with_id VARCHAR(255);
```

All 32 registration rows are intact. **If you restore from `powerwize_dump.sql` or move to
another machine, run that ALTER again** — the dump predates the column.

### 5. Run it

```bash
cd src && ../venv/Scripts/python.exe app.py
```

Open **http://127.0.0.1:5000** in a normal window. Keep a **second browser profile or an
incognito window** open — you'll want two roles signed in at once, and one session cookie
can't hold both.

Keep a terminal on `tail -f app.log` to catch anything that fails quietly.

---

## Act 1 — Arrive as a stranger *(5 min)*

Signed out, in a fresh window.

1. **http://127.0.0.1:5000** — watch the entrance: the curtain wipes up, blueprint rails
   fade in column by column, the headline reveals line by line. Move your mouse around the
   hero; the dot field should bulge toward the cursor.
2. Scroll the whole page slowly. Section rules draw themselves left to right, the SVG chart
   in the hero panel strokes itself in, cards warm at the edge as the pointer crosses them.
3. Hover the nav — the green underline slides between items.
4. **Programs** → open any program → check the batch dates against what's really scheduled.
5. **Capabilities** → open one.
6. **Company** and **Contact**.
7. Squeeze the window under ~1100px. The nav rail is replaced by a burger. Open it — the
   panel slides in from the right and the items rise in sequence. On a touch screen, drag
   the panel rightward to dismiss it.

**What this proves:** the public site (SO-facing marketing), the design system you're about
to see reused in the dashboards, and the batch schedule reading live from the database.

---

## Act 2 — Apply for training *(10 min)*

Still signed out.

1. From the homepage, start a registration — or go straight to
   **http://127.0.0.1:5000/training**.
2. Work through the wizard. **Deliberately click Next with a required field empty** — the
   field should shake and refuse to advance.
3. Fill step 1 properly. Use an email you can recognise later, e.g.
   `walkthrough.test@example.com`.
4. Press **Back**, then **Next** again — your answers should still be there, and the step
   should slide in from the direction you're travelling.
5. At the upload step, drop in a photo of an ID. Watch the readout: the file is sent to
   `/api/validate-upload` and a vision model judges whether it's actually the document
   asked for. *(Needs AI.)*
6. Now try a **deliberately bad** upload — a blurry photo, or a picture of something else.
   It should be rejected with a reason. This is the check most people never see working.
7. Do the selfie/liveness step if the form asks for it — it compares your face against the
   uploaded ID via `/api/face-match`.
8. Submit.

**What you should see:** a confirmation. Your application now sits in `registrations` with
status `pending`.

**What this proves:** SO1 registration, the wizard, and AI document validation.

---

## Act 3 — Review the application as staff *(10 min)*

Switch to your **second window**. Sign in as **`admin@ewize.com`** (password in `demo_credentials.txt`).
You land on `/admin`.

1. **Try the theme toggle in the topbar.** Sun/moon. Reload the page — it remembers.
   Leave it in whichever mode you prefer, but look at both at least once.
2. Go to **Registrations**. Your application from Act 2 is at the top, `pending`.
3. Open it. Check the uploaded ID and selfie came through and are viewable.
4. Approve the selfie.
5. **Accept** the registration.

You'll get one of two flash messages:

- *"…Account setup email sent to…"* — email works. Go read that inbox for the link.
- *"…accepted, but email failed: …"* — **expected if SMTP isn't configured.** The
  registration is accepted, but the setup link is gone: the token is hashed in the database
  and the plaintext only ever existed in that email.

**If email failed, mint a link yourself.** Find the registration id in the admin table, then:

```bash
cd src && ../venv/Scripts/python.exe -c "
from db import create_account_token
print('http://127.0.0.1:5000/create-account/' + create_account_token(<REG_ID>, 'walkthrough.test@example.com', True))"
```

Copy the URL it prints.

6. While you're here, click **Reject** on some *other* pending application to see that path.
7. Open the **Audit log** — your accept and reject should both be recorded, with your user id.

**What this proves:** admin review, selfie approval, the onboarding token, audit logging.

---

## Act 4 — Become a real user *(5 min)*

Back in your **first window** (signed out).

1. Open the `/create-account/<token>` link.
2. Your approved details should be pre-filled — this is the point of the invitation flow:
   the account inherits the training type and payment status the admin approved.
3. Set a password. Submit.
4. Sign in as your new user.

**Where you land:** `/payment`, not the portal — new trainees are unpaid.

5. Go back and **open the same link a second time.** It should refuse: "already been used."

**What this proves:** SO1 onboarding, single-use tokens, and that there's no public
self-registration back door.

---

## Act 5 — Pay *(10 min)*

You're on `/payment`, fee ₱5,000.

1. Try the **card** flow. Use a PayMongo **test** card. It hands off to their 3DS page and
   returns to `/payment/card/return`. *(Needs PayMongo test keys.)*
2. Worth doing first: run a **declining** test card. You should land on `/payment/failed`
   and still be unpaid — failure handling is the half nobody demos.
3. Now pay successfully.
4. You land on **`/payment/success`** — a receipt with a QR code.
5. Open **http://127.0.0.1:5000/verify** and check that receipt code. It should verify.
6. Try `/verify` again with a code you invent. It should reject it.

**What this proves:** SO5 payment, receipts, and blockchain-backed receipt verification.

> **Short on time or no PayMongo keys?** Skip to Act 6 and sign in as
> `miguel.torres@gmail.com` instead — already paid, already finished, already certified.

---

## Act 6 — Be a trainee *(20 min)*

Sign in as your new user (now paid), or as **`miguel.torres@gmail.com`** (password in `demo_credentials.txt`).

### The portal — `/portal`

This is one of the two screens just redesigned.

1. Note it's continuous with the landing page — same substrate, same hairlines, same mono
   labels. You're still in the same world, just signed in.
2. **Syllabus progress** at the top: large percentage, module count, meter.
3. **Enrolment strip**: payment, programme, training mode, registration status.
4. **My modules**: every module with its own step meter and *the next thing you owe* —
   "Next: Pass the quiz", "Next: Open the material". A finished one just says "Completed".
5. Open **`/lms/progress`** in another tab and compare the percentage. They must match —
   both are computed by the same helper. This is the check worth doing.
6. **Certificate** block — issued with dates, or "Not yet issued" and how many modules remain.

### Actually learn something

7. Click a module row → you're in **`/lms/learn/<id>`**.
8. Read the content, download an attached file.
9. **Ask the module chatbot a question** about the material — it answers grounded in that
   module's content, not general knowledge. *(Needs AI.)*
10. Take the **quiz**. Use a **hint** on a question you're unsure about. *(Needs AI.)*
11. Mid-quiz, **switch browser tabs and come back** — the switch is logged as an integrity
    signal.
12. Submit the quiz.
13. Submit a **practical exam** — upload any PDF.
14. Leave **feedback** on the module (rating + comment).
15. Return to `/portal`. **The meter has moved** and the "next step" text has changed.

**What this proves:** SO2 training delivery, SO3's AI assistance, progress tracking, and
that the redesigned portal reflects live state.

---

## Act 7 — Be the trainer *(15 min)*

Second window. Sign out of admin, sign in as **`patricia.v@ewize.com`** (password in `demo_credentials.txt`).
You land on `/employee` — the other redesigned screen.

### The console

1. Same design language as the portal and the landing page. Fixed rail, numbered sections.
2. Click through all five sections. **Watch the URL** — it picks up `#modules`, `#solar`
   and so on.
3. Press **Back**. It returns to the previous section. Press **Refresh** — it stays put.
   Paste `/employee#progress` into a fresh tab; it opens there directly.
4. Squeeze the window under 900px — the rail collapses to icons, keeping the amber marker.

### Grade the work

5. **Exam submissions** — your trainee's practical exam from Act 6 is here.
6. Click **Review**. Read the answers. Give it a grade and feedback.
7. Try grading something **0**. Go back to the list: it must read **"0%"**, not "Pending".
8. The header count ("N awaiting a grade") should have dropped by one.

### Watch the class

9. **Trainee progress.** *This section was permanently empty before — it's the headline fix.*
   Eight trainees, each with their own meter.
10. Scan the percentages column. **They differ.** Previously every row would have shown the
    same number.
11. Read the sub-lines. They differ too — one trainee needs "Pass the quiz", another needs
    "Open the material". That's per-trainee state, not a template.
12. Pick a trainee, note their percentage, then sign in as them elsewhere and check
    `/lms/progress`. Same number.

### Manage modules

13. **Training modules** — only *your* modules, live and archived separated.
14. **Archive** one. Confirm. It drops into the archived group, dimmed with an amber edge.
15. Now sign in as a trainee and check `/lms/learn` — **the archived module is gone.**
16. Back as trainer: **Restore** it.
17. Try **Archive** and hit **Cancel** — nothing should change.
18. Open a module → **generate a quiz with AI** from its content. Takes 10–30 seconds.
    *(Needs AI.)*
19. Edit a generated question, save, and confirm it sticks.

**What this proves:** the trainer console, the two bugs fixed, module lifecycle, SO2 quiz
authoring.

---

## Act 8 — Get certified *(10 min)*

As the trainer (or admin), go to **`/lms/certificates/manage`**.

1. Eligible trainees are listed alongside already-issued certificates.
2. **Issue** a certificate to a trainee who has finished everything.
3. Behind the scenes it hashes `cert_id:user_id` and writes it to Polygon Amoy. Watch
   `app.log` — this takes a few seconds and **fails silently by design** if the chain is
   unreachable, so the certificate still issues either way.
4. Sign in as that trainee → **`/lms/certificates`**. Certificate with a QR code.
5. **Copy the QR's URL and open it in a signed-out window** — `/lms/certificates/verify/<id>`.
   It should show holder, dates and validity to a complete stranger. That's the point of
   putting it on-chain.
6. Change one character of the cert id in that URL. It should report invalid.
7. If the chain write worked, look the `tx_hash` up on **amoy.polygonscan.com**.

### See the expiry states

Certificates run 3 years. To see the other two states without waiting:

```sql
-- expiring soon (portal shows "Expiring soon" + day count)
UPDATE lms_certificates SET expires_at = CURRENT_DATE + 45 WHERE user_id = <id>;
-- expired
UPDATE lms_certificates SET expires_at = CURRENT_DATE - 10 WHERE user_id = <id>;
```

Reload `/portal` after each and watch the certificate block change. Set it back to
`CURRENT_DATE + 1000` when done.

**What this proves:** SO4 blockchain certification and public verification.

---

## Act 9 — Solar consultation *(15 min)*

As a trainee, from the portal: **Request a quotation**, or **http://127.0.0.1:5000/solar**.

> Your `solar_requests` table is currently **empty**, so this act is also what gives Act 10
> and the trainer's Solar pane anything to show.

1. Fill in the request. **Upload an electricity bill** — OCR pulls out the kWh and amount so
   you don't have to type them. *(Needs AI.)*
2. Submit. You get a sizing readout: system size, feasibility, indicative cost.
3. Sanity-check it — does the recommendation look sane for the consumption you entered?
4. Now try **Solara**, the chat route: **http://127.0.0.1:5000/solar/chat**. Same outcome,
   conversational. Watch the opener chips cascade in and the typing indicator. *(Needs AI.)*
5. Ask Solara something off-topic and see how it handles it.
6. **Stop LM Studio (or unset the key) and send one more message.** It should fail
   gracefully rather than hang forever — worth knowing before a live demo.

Now switch to the **trainer** window:

7. **Solar consultations** — your request is there. The stat strip counts it.
8. Click the **filter pills**. Rows filter by status; the counts match. Filter to a status
   with nothing in it and confirm you get "Nothing matches that filter" rather than a bare
   table header.
9. Open the request → review it → advance its status. Watch the pill colour change as it
   moves `ai_processed` → `pending_review` → `reviewed` → `quotation_sent`.

**What this proves:** SO3 AI consultation, bill OCR, Solara, and the staff review pipeline.

---

## Act 10 — Admin oversight *(15 min)*

Sign back in as **`admin@ewize.com`**.

1. **Analytics** — charts of registrations, payments, progress. Check them in **both**
   themes; chart colours are the thing most likely to break in one mode.
2. **Users** — archive a user. They vanish from the active lists. **Unarchive** them.
3. **Schedules** — add a batch. Then open the **public homepage** and confirm it appears in
   the schedule table. That round trip is a nice one to demo.
4. Delete that batch again.
5. **Exports** — download all five: users, registrations, payments, solar requests, LMS
   progress. Open one in Excel and check the row count matches what the dashboard claims.
6. **Feedback** — the module feedback you left in Act 6 should be here.
7. **Audit log** — scroll the whole session's actions: accept, reject, archive, issue
   certificate. This is your compliance story.

**What this proves:** SO6 monitoring, reporting and auditability.

---

## Act 11 — Try to break it *(10 min)*

The part that finds real problems.

1. Signed out, type **`/admin`**, **`/employee`**, **`/portal`** straight into the URL bar.
   All should bounce you to `/auth`.
2. Signed in **as a trainee**, type **`/admin`**. You must not get in.
3. Signed in **as a trainee**, type **`/employee`**. Same.
4. Signed in **as an employee**, type **`/admin`**. Employees are not admins.
5. Sign in as trainer **Patricia**, note a module id she owns. Sign in as **Roberto** and
   try `/lms/modules/<that id>/edit`. He should be refused.
6. Log out, then press **Back**. You must not see the dashboard again.
7. Log in with a **wrong password** — the error must not reveal whether the email exists.
8. Type `<script>alert(1)</script>` as your name in a form. It should render as text.
9. **Unpaid trainee** (`ana.cruz@yahoo.com`) → `/portal` should push you to `/payment`.
10. In DevTools → **Rendering** → tick **prefers-reduced-motion: reduce**. Reload both
    dashboards. Nothing should slide or fade, but every meter and status must still be
    readable.
11. Unplug the mouse — **Tab** through the trainer console. Every control reachable, focus
    ring always visible, no traps.

---

## When you're done

```bash
# stop Postgres
"C:\laragon\bin\postgresql\postgresql-18.4-1-windows-x64\bin\pg_ctl.exe" \
  -D "C:\laragon\data\postgresql" stop
```

Your walkthrough user, registration, payment, submission, certificate and solar request all
persist. To clean up, delete by the email you used in Act 2.

For per-case pass/fail recording and the objective-to-section mapping, see
[UAT_TEST_PLAN.md](UAT_TEST_PLAN.md).
