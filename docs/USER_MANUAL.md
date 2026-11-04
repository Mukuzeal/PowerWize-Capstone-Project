# PowerWize — User Manual

How to use the system, role by role. Every screen shown here is a capture of the
real running application.

For installation and configuration, see **[SETUP.md](SETUP.md)**. For the
architecture behind these screens, see
**[SYSTEM_DOCUMENTATION.md](SYSTEM_DOCUMENTATION.md)**.

**Contents**

1. [Who uses what](#1-who-uses-what)
2. [Signing in](#2-signing-in)
3. [Applicant — registering for a programme](#3-applicant--registering-for-a-programme)
4. [Trainee — paying, training, and getting certified](#4-trainee--paying-training-and-getting-certified)
5. [Trainer — running training](#5-trainer--running-training)
6. [Administrator — running the organisation](#6-administrator--running-the-organisation)
7. [Company coordinator — enrolling a team](#7-company-coordinator--enrolling-a-team)
8. [Solar prospect — getting a PV consultation](#8-solar-prospect--getting-a-pv-consultation)
9. [Anyone — verifying a certificate or receipt](#9-anyone--verifying-a-certificate-or-receipt)

---

## 1. Who uses what

PowerWize has five stored roles. **The role stored as `employee` is what the
interface calls a "Trainer"** — the label changed, the stored value never did.

| Role | Console | What they can do |
|---|---|---|
| **Trainee** | `/portal` | Study modules, take quizzes and practical exams, track progress, collect a certificate |
| **Trainer** (`employee`) | `/employee` | Author modules, build quizzes and exams, grade submissions, track trainees; optionally review PV consultations |
| **Secretary** | `/admin` | Everything a Super User can do except review PV consultations |
| **Super User** | `/admin` | Everything an Admin can do except manage accounts and delete other people's modules |
| **Admin** | `/admin` | Everything, including account management, the audit log, and deleting any module |

Two things are **not** determined by role:

- **A Trainer's remit is set per account.** One trainer can run training modules,
  another PV consultations, another both. An administrator grants or withdraws
  these individually; there is no separate role for each combination.
- **A trainee's syllabus is determined by their programme**, not by who they are.
  Approving someone for CEM and approving them for GEMP-LGU produces two
  different module lists from the same system.

Some pages need no account at all: the registration forms, the Solara
consultation, certificate verification, and receipt verification are all public.

---

## 2. Signing in

Go to `/auth/login`. Every role uses the same sign-in page and is routed to the
correct console automatically.

![Sign-in page](screenshots/1-administrative-dashboard/00_login.png)

**If you cannot sign in:**

- *Wrong email or password* — use **Forgot password** to receive a reset link.
  The link expires; request a new one if it lapses.
- *Account temporarily locked* — repeated failed attempts lock an account for a
  cooling-off period. Wait it out or ask an administrator.
- *You never received an invitation* — accounts cannot be self-registered. See
  [section 3](#3-applicant--registering-for-a-programme).

> **There is no "Sign up" link, and this is deliberate.** A plain email-and-password
> signup would create trainees who skipped ID upload, selfie verification, and
> administrative review. An account exists only after a registration has been
> approved.

---

## 3. Applicant — registering for a programme

### Step 1 · Choose a programme

Visit `/programs` to see what is offered. Each programme has its own form:

| Programme | Form |
|---|---|
| Certified Energy Manager | `/training` |
| Certified Energy Auditor | `/cea-training` |
| GEMP — Local Government Units | `/gemp-lgu` |
| GEMP — Other Government Entities | `/gemp-oge` |
| CEM renewal | `/renewalCEM` |
| CEA renewal | `/renewalCEA` |

### Step 2 · Complete the form

Forms are multi-step. Your progress through the steps is kept as you go, so a
validation error on the last step does not clear the first.

You will be asked for personal and employment details, your chosen programme,
and supporting documents — which vary by programme but generally include a
résumé, a valid government ID, and a selfie holding that ID. Renewals also ask
for the expiring certificate.

### Step 3 · Upload documents

**Documents are checked the moment you select them, not after you submit.** A
vision model reads each upload and confirms it is the right kind of document and
legible; for the selfie it also compares the face against the one on your ID.

If something is wrong you are told immediately — a blurry ID, a cropped corner, a
selfie where the ID is unreadable. Retake and reselect. This is faster for you
than discovering the problem days later in review.

### Step 4 · Submit and wait for review

Submitting puts your registration in the administrative queue. Staff review your
documents and either approve or reject.

**If approved**, you receive an email containing a single-use invitation link of
the form `/create-account/<token>`. The token carries the programme you were
approved for and your payment status, so neither can be altered by you.

### Step 5 · Create your account

Open the link and set a password. That is the whole account-creation step —
your name, email, and programme are already known.

Invitation links **expire**. If yours has lapsed, ask staff to resend it; they
can do so from the registration record.

> **About your ID and selfie.** Once review is complete, the images themselves are
> deleted. The system keeps only a cryptographic digest, the file size, the
> extension, and the review outcome as audit evidence. Your documents are not
> retained after they have served their purpose.

---

## 4. Trainee — paying, training, and getting certified

### Step 1 · Pay the enrolment fee

A new account starts as **unpaid**, and the learning portal stays closed until
payment settles. Go to `/payment`.

![Checkout](screenshots/5-payment-verification/04_payment_checkout.png)

Two methods are offered:

| Method | Screen |
|---|---|
| **Card** | ![Card](screenshots/5-payment-verification/05_payment_card_method.png) |
| **QRPH / e-wallet** | ![QRPH](screenshots/5-payment-verification/06_payment_qrph_method.png) |

If you hold a **discount code**, enter it before paying — the total updates
immediately. A code may be restricted to one programme, capped in total uses, or
expired; the form tells you which if it is refused.

When payment settles you receive a receipt with an ID and a verification hash.
That hash is written to the Polygon blockchain, which is what lets anyone
confirm the receipt later without access to the system. If the blockchain write
fails, your payment is still complete and valid — the receipt simply shows
**Off-chain** until it is re-anchored.

> **Company-paid trainees do not pay here.** Your employer settles one invoice
> covering everyone. Skip to step 2.

### Step 2 · Open the portal

Go to `/portal`.

![Trainee portal](screenshots/3-trainee-training-ai-feedback/01_trainee_portal.png)

**If you were enrolled by your employer**, you may be asked for a **class join
code** — a short code your coordinator distributes. Enter it once.

Two situations where no code is asked for, both expected:

- You paid for yourself. You are on no corporate invoice, so there is no class
  to join.
- Staff have not created a class for your company's invoice yet. Access stays
  open until one exists; the prompt appears the moment it does.

> The join code **names** a class — it does not grant permission. Your
> entitlement is re-checked on every visit, so a withdrawn roster place or a
> cancelled invoice closes access even though you already entered the code.

### Step 3 · Work through the syllabus

![My syllabus](screenshots/3-trainee-training-ai-feedback/02_my_syllabus.png)

Your syllabus is assembled from your approved programme. You see the modules for
that programme and no others.

Open a module to reach its workspace:

![Module workspace](screenshots/3-trainee-training-ai-feedback/03_module_workspace.png)

Each module holds:

- **Materials** — documents and files to study. Your reading progress is recorded
  as you go.
- **A quiz** — scored automatically where possible.
- **A practical exam** — reviewed by your trainer.
- **A rating** — leave one when you finish. One rating per module.

### Step 4 · Ask the module assistant

Each module has an AI assistant that answers questions about the material you are
studying.

![Asking the assistant](screenshots/3-trainee-training-ai-feedback/04_ai_assistant_question.png)

Type your question and send. If the assistant replies that it could not respond,
the configured text provider is unreachable — tell your administrator; it is a
configuration problem, not something you did.

### Step 5 · Take the quiz

![Quiz attempt](screenshots/3-trainee-training-ai-feedback/07_quiz_attempt.png)

Quizzes are **timed** and carry a passing score set by your trainer. Four kinds
of question appear:

| Type | Graded |
|---|---|
| Multiple choice | automatically, on the selected choice |
| Identification | automatically, on an exact match |
| Enumeration | automatically, as a set — order does not matter |
| Essay | by your trainer |

A quiz containing essay questions shows a partial score until your trainer has
reviewed it.

**Hints** are available during an attempt where your trainer enabled them.

> **Leaving the quiz tab is recorded.** The count of tab switches is stored with
> your attempt and visible to your trainer. Stay on the page.

### Step 6 · Submit the practical exam

Open the practical exam from the module workspace, read the instructions and the
evaluation criteria, and submit your work as a file. Some exams require camera
access. Your trainer grades it and returns a numeric grade with written feedback.

### Step 7 · Track progress

![My progress](screenshots/3-trainee-training-ai-feedback/06_my_progress.png)

A module counts as complete when its materials are read, its quiz is passed, and
its practical exam is graded. Your trainer sees exactly the same calculation —
the two views are produced by the same code and cannot disagree.

### Step 8 · Collect your certificate

When every module in your programme is complete you become eligible, and staff
issue the certificate.

![Certificate wallet](screenshots/6-tokenized-certificate-verification/03_trainee_certificate_wallet.png)

Your certificate carries a certificate ID, an issue date, an expiry date where
the programme sets one, and a QR code. The QR resolves to a public verification
page that anyone — an employer, an accrediting body — can open without an
account. See [section 9](#9-anyone--verifying-a-certificate-or-receipt).

---

## 5. Trainer — running training

Sign in and you land on the trainer console at `/employee`, a single page that
switches views without reloading.

![Trainer console](screenshots/2-instructor-training-management/01_trainer_console_dashboard.png)

> **What you see depends on your account, not only your role.** Module management
> and PV consultation review are granted individually. If a section described
> here is missing, your administrator has not granted that capability.

### Authoring a module

From **Modules**, choose *Create module*:

![Create module](screenshots/2-instructor-training-management/10_create_module_form.png)

Set the title, description, and — importantly — the **programme** the module
belongs to. That field is what decides which trainees ever see it. Set the sort
order to control its position in the syllabus.

A new module is **unpublished**. Trainees see nothing until you publish it, so
build it fully first.

![Module management](screenshots/2-instructor-training-management/07_module_manage.png)

From a module's management view you can upload and remove material files, build
the quiz and practical exam, publish or unpublish, lock, archive, or restore.

| Action | Effect |
|---|---|
| **Publish** | Makes the module visible to trainees in that programme |
| **Lock** | Freezes content against further edits |
| **Archive** | Removes it from active syllabi while preserving all trainee records |
| **Restore** | Returns an archived module to service |
| **Delete** | Permanent. Only an Admin may delete a module owned by someone else. |

Your module library lists everything you own:

![Module library](screenshots/2-instructor-training-management/06_module_library.png)

### Building a quiz

![Quiz builder](screenshots/2-instructor-training-management/08_quiz_builder.png)

Set the time limit and passing score, then add questions. Mix the four types
freely — multiple choice, identification, enumeration, and essay.

**Generate with AI** drafts questions from the module's material. Treat the
output as a first draft: read every question, fix the ones that are wrong, and
delete the ones that are trivial. The generator is a time-saver, not an author.

Publish the quiz when it is ready. One quiz per module.

### Building a practical exam

![Practical exam builder](screenshots/2-instructor-training-management/09_practical_exam_builder.png)

Write the instructions and the **evaluation criteria** — the criteria are shown
to trainees, so they know what they are being judged on. Require camera access if
the exercise needs it. One practical exam per module.

### Grading

Submissions arrive in your inbox:

![Submissions inbox](screenshots/2-instructor-training-management/03_exam_submissions_inbox.png)

![Grading queue](screenshots/2-instructor-training-management/11_grading_queue.png)

Open a submission to read the trainee's answers and download any attached file,
then enter a grade and written feedback. Items flagged as needing review are
those the automatic grader could not settle — essay answers, chiefly.

### Tracking trainees

![Trainee progress](screenshots/2-instructor-training-management/05_trainee_progress.png)

Progress per trainee across your modules, including quiz scores, exam grades,
material completion, and **recorded tab switches** during quiz attempts.

### Reviewing PV consultations

If your account carries the PV review capability, consultations queue here:

![Consultations queue](screenshots/2-instructor-training-management/04_solar_consultations_queue.png)

See [section 8](#8-solar-prospect--getting-a-pv-consultation) for what the
prospect submitted and what the review decides.

---

## 6. Administrator — running the organisation

Sign in to reach `/admin`.

![Dashboard overview](screenshots/1-administrative-dashboard/01_dashboard_overview.png)

The dashboard opens on counts across users, registrations, schedules, and
trainees. Sections not available to your role are not shown — Super User and
Secretary see a subset of what follows.

### Reviewing registrations

This is the gate into the whole system. Nothing else proceeds until it is worked.

![Registration review](screenshots/1-administrative-dashboard/04_registration_review.png)

For each registration, open the submitted documents — résumé, government ID,
selfie with ID — and compare them against the stated details.

- **Approve** — records the review, purges the document images, and emails the
  applicant an invitation link.
- **Reject** — closes the registration. The applicant is notified.
- **Resend invitation** — issues a fresh link when the previous one expired.

Approving is what mints the invitation token. There is no other route to an
account.

> **Document images are deleted once you decide.** What remains is a SHA-256
> digest, the byte size, the extension, and your outcome — enough to prove what
> was reviewed, without holding copies of government IDs indefinitely.

### Managing accounts

*(Admin only. Super User and Secretary cannot mint or remove accounts.)*

![User management](screenshots/1-administrative-dashboard/02_user_management.png)

![Create user](screenshots/1-administrative-dashboard/12_create_user_form.png)

Create staff accounts directly, edit details, and **archive** accounts that
should no longer sign in. Prefer archiving to deletion — it preserves the
person's training records.

This is also where a **Trainer's remit** is set. Grant module management, PV
consultation review, either, or both. Capabilities that define a role — account
management, billing, console access — are deliberately not grantable this way.

### Schedules

![Schedules](screenshots/1-administrative-dashboard/03_schedules.png)

Create and edit the training batches that registrations are booked against.

### Corporate billing

![Corporate payments](screenshots/1-administrative-dashboard/05_corporate_payments.png)

![Corporate billing records](screenshots/5-payment-verification/02_corporate_billing_records.png)

For each company invoice you can:

- **Build it from the approved employee roster**, priced per employee by
  programme.
- **Override the total** with a negotiated figure. The reason and your identity
  are recorded against it.
- **Send a hosted payment link**, and revoke it if circumstances change.
- **Inspect every attempt** — each carries a unique idempotency key, so a retried
  webhook cannot charge twice.
- **Re-anchor** a receipt whose blockchain write failed.
- **Resolve a quarantined event.** A webhook that matched no invoice is held in
  full, raw, for you to reconcile. Nothing is silently dropped. The **Needs
  attention** view lists these.

### Discount codes

![Discount codes](screenshots/1-administrative-dashboard/06_discount_codes.png)

![Discount records](screenshots/5-payment-verification/03_discount_code_records.png)

Issue codes with a percentage, expiry date, maximum uses, and optional programme
restriction. Codes can be deactivated without deletion, which keeps the record of
those already redeemed.

### Module oversight

![Modules oversight](screenshots/1-administrative-dashboard/07_modules_oversight.png)

Every module across every programme and trainer. Admin is the only role that may
delete a module owned by someone else.

### Training classes

Create a class for a corporate invoice or intake, which generates its **join
code**. From the class panel you can rotate the code, open or close joining,
assign an instructor, add or remove members, and watch progress across the
cohort.

### Reports and analytics

![Analytics](screenshots/1-administrative-dashboard/11_analytics.png)

![Export reports](screenshots/1-administrative-dashboard/08_export_reports.png)

Excel exports are available for registrations, users, payments, LMS progress,
and solar requests. Every export is written to the audit log.

### Trainee feedback

![Trainee feedback](screenshots/1-administrative-dashboard/09_trainee_feedback.png)

Module ratings and comments collected from trainees.

### Audit log

*(Admin only.)*

![Audit log](screenshots/1-administrative-dashboard/10_audit_log.png)

Who did what, to which record, and when — approvals, account changes, price
overrides, exports, and certificate issuance.

### Issuing certificates

![Certificate issuance](screenshots/6-tokenized-certificate-verification/01_certificate_issuance_console.png)

Eligible trainees — those who completed every module in their programme — are
listed for issuance. Issue, and the certificate is created and its hash written
to Polygon.

![Certificate issued](screenshots/6-tokenized-certificate-verification/02_certificate_issued_result.png)

The result reports how many were issued and how many reached the chain. A
certificate marked **Off-chain** is fully valid; use **re-anchor** to retry the
blockchain write when the network or wallet is available again.

---

## 7. Company coordinator — enrolling a team

A company enrolling several employees does not need an account. Staff send you a
coordinator link; the token in it is stored only as a hash, expires, and can be
revoked.

### Step 1 · Submit your roster

Open the coordinator link and enter each employee's name and email. Each becomes
a **slot** on the intake.

### Step 2 · Employees register

Each slot generates a personal invitation link. Your employees complete the
normal registration form through it — including document upload — and go through
the same review as any other applicant.

You can watch which slots are filled, and revoke or re-send an individual
invitation.

### Step 3 · Settle the invoice

Once employees are approved, staff build an invoice from the roster and send you
a payment link. Pay it once, for everyone.

If payment succeeds but the invoice still shows unpaid, tell staff — the
confirmation is held, raw and complete, for them to reconcile. Do not pay again.

### Step 4 · Distribute the join code

Staff create a training class for your invoice, which produces a **join code**.
Pass it to your employees; each enters it once in their portal.

> The code identifies the class. It does not grant access — entitlement is
> re-checked on every visit, so removing someone from the roster closes their
> access even after they have used the code.

---

## 8. Solar prospect — getting a PV consultation

No account needed. Go to `/solar`.

### Step 1 · Describe the site

![Consultation intake](screenshots/4-solar-pv-consultation/01_consultation_intake.png)

Provide your contact details and the site's particulars: establishment type,
ownership, electrical phase, monthly bill or consumption, night-time usage share,
savings target, and roof area.

**Upload a recent electricity bill** and the system reads the consumption and
billed amount off it directly, which is more accurate than estimating.

### Step 2 · Talk to Solara

![Solara opening](screenshots/4-solar-pv-consultation/02_solara_chat_opening.png)

Solara answers questions about solar PV in **English or Taglish**.

![Asking a question](screenshots/4-solar-pv-consultation/03_solara_user_question.png)

Answers are drawn from EnergyWize's own documentation, and the reply cites which
documents it used:

![Grounded reply](screenshots/4-solar-pv-consultation/04_solara_knowledge_reply.png)

As you supply enough detail, a quotation panel fills in alongside the
conversation:

![Taglish quotation](screenshots/4-solar-pv-consultation/05_solara_taglish_quotation.png)

**Every number in that panel is calculated, not written by the AI.** System size,
panel count, cost range, monthly savings, and payback period come from a sizing
engine. The assistant writes only the explanation around them, and if its text
contains a figure that does not match a calculated value, that text is discarded
and replaced with a plain statement of the real numbers.

Solara answers questions about solar PV and declines everything else. That
boundary is enforced before the assistant is consulted at all.

> **What is kept.** Your contact details and site information are stored so that
> an engineer can follow up. Read the privacy notice shown at the start of the
> conversation.

### Step 3 · Engineer review

An EnergyWize engineer reviews your consultation:

![Admin review queue](screenshots/4-solar-pv-consultation/06_admin_consultation_queue.png)

![Consultation review](screenshots/4-solar-pv-consultation/07_admin_consultation_review.png)

They can confirm the computed figures or substitute reviewed ones — site access,
roof condition, and utility specifics that a form cannot capture. **Reviewed
figures are stored alongside the computed ones, never on top of them**, so what
the engine said and what the engineer concluded both remain on record.

A site outside what EnergyWize can serve is marked out of scope with a stated
reason rather than being quietly dropped.

---

## 9. Anyone — verifying a certificate or receipt

No account, no permission, no relationship with EnergyWize required. This is the
point.

### Verifying a certificate

Scan the QR code on the certificate, or go to `/lms/certificates/verify/<cert_id>`.

![Public QR verification](screenshots/6-tokenized-certificate-verification/04_public_qr_verification.png)

The page shows the holder, the programme, the issue and expiry dates, and the
blockchain record — transaction hash, block number, and confirmation count. It
recomputes the certificate's hash and compares it against what was written to
Polygon at issue.

A match means the record is unchanged since issue. An altered certificate cannot
produce a matching hash, so tampering is detectable by an employer with no access
to the system.

The certificates in these captures are genuine Polygon Amoy anchors:

```
cert id      300cdcc6550be117ccb917953f3048a0
transaction  0x3021448c822ede73a67e2bdd5857e0d3dcef449b1b9304df30dc519ae3f52230
block        #50943409 · 9 confirmations
status       Verified on Polygon — the record is unchanged since issue
```

A certificate showing **Off-chain** was issued while the network was unreachable.
It is valid; it simply has no chain record yet, and staff can re-anchor it.

### Verifying a payment receipt

Go to `/verify` and enter the receipt ID.

![Receipt verification](screenshots/5-payment-verification/01_receipt_verification_portal.png)

The same check applies: the receipt's hash is recomputed and compared against the
blockchain record.
