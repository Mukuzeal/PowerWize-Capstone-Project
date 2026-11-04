# PowerWize

### AI-Enhanced Training and Consultation System with Blockchain Payment Verification and Tokenized Certificates for EnergyWize Solutions Inc.

A capstone research project submitted to the **College of Computer Studies, Laguna State Polytechnic University**.

| | |
|---|---|
| **Researchers** | BANDAO, Jan McZeal A. · COSIO, Chelsea P. · ESGUERRA, Leinard Kurt V. |
| **Thesis Adviser** | MIA V. VILLARICA, DIT |
| **Partner Organization** | EnergyWize Solutions Inc. |
| **Project Website** | https://mukuzeal.github.io/PowerWize-Capstone-Project/ |

---

## What this system does

EnergyWize Solutions Inc. runs accredited energy-management training programmes
(CEM, CEA, GEMP for LGU and other government entities, plus renewals) and sells
solar photovoltaic installations. Before PowerWize, both sides of that business
ran on paper forms, spreadsheets, manually issued certificates, and
consultations that depended entirely on an engineer's availability.

PowerWize replaces that with one system that carries a trainee from a public
registration form through to a certificate whose authenticity anyone can verify,
and gives a solar prospect an immediate, grounded technical answer instead of a
callback.

Three things distinguish it from a conventional LMS:

**1 · Payments and certificates are anchored to a public blockchain.**
Each settled payment and each issued certificate is hashed and written to the
Polygon network. A QR code on the certificate resolves to a public verification
page that recomputes the hash and compares it against the chain, so a tampered
record is detectable by an employer with no access to the system. The write is
deliberately **best-effort** — a failed anchor never invalidates a paid
enrolment or an earned certificate; it surfaces as "Off-chain" with a re-anchor
action.

**2 · The solar consultant cannot invent numbers.**
Solara, the PV consultation assistant, answers from a retrieval index built over
a curated knowledge base, and every figure it quotes — system size, panel count,
cost range, monthly savings, payback period — is produced by a deterministic
sizing engine, not by the language model. A post-generation check discards the
model's text entirely and falls back to a template if the reply contains any
number that matches no computed value. Off-topic questions are refused by a
deterministic gate before a chat model is ever called.

**3 · Identity is verified before an account can exist.**
There is no public signup route. An account can only be created by redeeming a
token that an administrator issued after reviewing an uploaded government ID and
a selfie — the latter checked against the ID by a vision model. Once review is
complete the images are purged and only a hash, byte size, and outcome are
retained as audit evidence.

---

## Documentation

| Document | Contents |
|---|---|
| **[System Documentation](docs/SYSTEM_DOCUMENTATION.md)** | Architecture, context and level-1 DFDs, use-case diagram, the full 36-table ERD, and sequence diagrams — all derived from source |
| **[User Manual](docs/USER_MANUAL.md)** | Step-by-step guide for every role, illustrated with captured screens |
| **[Setup & Deployment Guide](docs/SETUP.md)** | Installation, configuration, database bootstrap, and deployment |
| **[Screenshots](docs/screenshots/)** | 48 captured frames across the six major feature areas |
| **[RAG Setup](docs/RAG_SETUP.md)** | Retrieval configuration, threshold tuning, and grounding internals for Solara |
| **[CLAUDE.md](CLAUDE.md)** | Developer-facing architecture notes and repository conventions |

---

## Features

### Training management

- **Seven public registration programmes** — CEM, CEA, GEMP-LGU, GEMP-OGE, and
  the corresponding renewals, each with its own form and document requirements.
- **AI-assisted document screening.** Uploaded IDs and selfies are classified and
  face-matched by a vision model at file-select time, so an applicant is told
  about an unreadable photo immediately rather than days later.
- **Administrative review queue** with approve/reject, document inspection, and a
  full audit trail.
- **Invitation-only account provisioning.** The token carries the approved
  programme and payment status; neither is chosen by the applicant.
- **Module authoring** with file attachments, publication control, and
  per-programme targeting. A trainee's syllabus is resolved from their
  programme, never from their identity.
- **Quiz builder supporting four question types** — multiple choice,
  identification, enumeration, and essay — with optional **AI generation** from
  module material. Multiple choice, identification, and enumeration are
  auto-graded; essays route to manual review.
- **Practical examinations** with evaluation criteria, optional camera
  requirement, file submission, and a grading queue.
- **In-module AI assistant** that answers trainee questions about the material
  they are studying.
- **Progress tracking** that folds trainer-facing and trainee-facing views
  through a single function, so the two can never disagree.

### Certification

- **Tokenized certificates** anchored to Polygon, with expiry tracking.
- **Public QR verification** — anyone can confirm a certificate is genuine and
  unmodified without an account.
- **Re-anchor action** for certificates issued while the network was unreachable.

### Payments

- **PayMongo card and QRPH** checkout for individual enrolments.
- **Corporate invoicing** — build an invoice from an approved employee roster,
  apply a negotiated override with a recorded reason, and send a hosted payment
  link. Settlement is idempotent at the database level via unique idempotency
  keys, so a retried webhook cannot double-charge.
- **Webhook quarantine.** An event that cannot be matched to an invoice is
  stored with its raw body in `unresolved_payment_events` for staff resolution
  rather than being dropped.
- **Discount codes** with percentage, expiry, usage cap, and programme scoping.
- **Public receipt verification** against the blockchain record.

### Corporate intake

- **Coordinator portal** reached by a hashed, expiring, revocable token — a
  company representative submits an employee roster without needing an account.
- **Per-employee invitation slots** that carry each employee into the normal
  registration and review pipeline.
- **Training classes with join codes.** The code *names* a class; it never
  authorises. Entitlement is re-derived on every access, so a later rejection,
  roster revocation, or cancelled invoice closes access without anyone deleting
  a membership row.

### Solar PV consultation

- **Structured site survey** with electricity-bill upload and OCR extraction of
  consumption and billed amount.
- **Deterministic sizing engine** computing system size, panel count, cost range,
  monthly savings, payback period, annual yield, and battery recommendation.
- **Solara** — a retrieval-grounded chat assistant that handles English and
  Taglish, cites its sources, and is barred from authoring figures.
- **Staff review workflow** that records reviewed figures alongside the computed
  ones rather than overwriting them, keeping both auditable.

### Administration

- **Role-based access** across five stored roles, with per-account capability
  overrides for trainers.
- **Analytics dashboard**, **audit log**, and **Excel report exports** for
  registrations, users, payments, LMS progress, and solar requests.
- **Schedule and batch management** for training cohorts.

---

## Screenshots

Full index with per-frame descriptions: **[docs/screenshots/README.md](docs/screenshots/README.md)**

| Area | Frames |
|---|---|
| [Administrative dashboard](docs/screenshots/1-administrative-dashboard/) | 13 |
| [Instructor training management](docs/screenshots/2-instructor-training-management/) | 11 |
| [Trainee training and AI feedback](docs/screenshots/3-trainee-training-ai-feedback/) | 7 |
| [Solar PV consultation](docs/screenshots/4-solar-pv-consultation/) | 7 |
| [Payment interface and verification](docs/screenshots/5-payment-verification/) | 6 |
| [Tokenized certificate and verification](docs/screenshots/6-tokenized-certificate-verification/) | 4 |

Every frame is the real running application captured at 1600×1000 with a
device scale factor of 2 — no mockups and no edited pixels. The certificate in
section 6 is a genuine Polygon Amoy anchor, not a placeholder.

---

## Technology

| Layer | Technology |
|---|---|
| Backend | Python 3 · Flask (13 blueprints) · gunicorn |
| Database | PostgreSQL 18 · raw `psycopg2`, no ORM |
| Templating | Jinja2 |
| Frontend | Vanilla JavaScript — no framework, no build step |
| Payments | PayMongo (card, QRPH, hosted checkout) |
| Blockchain | Polygon Amoy testnet via `web3.py` |
| AI | Groq Cloud or local LM Studio, selected per workload |
| Retrieval | Cosine similarity over PostgreSQL `REAL[]` embeddings |

---

## Quick start

Full instructions, including deployment: **[docs/SETUP.md](docs/SETUP.md)**

The application **must** run with `src/` as the working directory — every module
imports its siblings flat, so `src/` has to be on `sys.path`.

```bash
git clone https://github.com/Mukuzeal/PowerWize-Capstone-Project.git
cd PowerWize-Capstone-Project

python -m venv venv
venv/Scripts/activate          # Windows
# source venv/bin/activate     # Linux / macOS
pip install -r requirements.txt

cp .env.example .env           # then fill in DATABASE_URL, SECRET_KEY, API keys

cd src && python app.py        # serves on http://localhost:5000
```

The database schema is applied automatically on first boot — `init_db()` creates
every table and column idempotently, so there is nothing to migrate.

---

## Repository layout

```
src/                  application code — run from here
  app.py              entry point; registers all 13 blueprints
  db/                  persistence package (star-exported submodules)
  lms_bp/              learning-management blueprint package
  admin/               administrative console package
  rag/                 embeddings and retrieval for Solara
  solar_engine.py      deterministic PV sizing and ROI
  permissions.py       the single capability map
  blockchain.py        Polygon anchoring and verification
templates/            Jinja2 templates (project root, not under src/)
static/               CSS, JS, and generated assets
knowledge/solar/      the 10 source documents Solara retrieves from
scripts/              maintenance, seeding, and verification scripts
docs/                 system documentation, user manual, screenshots
ewize-2026/           detached static build of the marketing site
```

---

## Verification

There is no automated test suite. The checks that guard this codebase are a
compile pass, an import pass, and a set of targeted scripts for the areas a
compile pass cannot cover:

```bash
python -m py_compile src/app.py src/db/*.py src/lms_bp/*.py src/admin/*.py
cd src && python -c "from app import app; print('imports ok')"
```

| Script | Guards |
|---|---|
| `scripts/solar_calc_check.py` | the sizing and ROI mathematics |
| `scripts/rag_eval.py` | retrieval threshold and grounding quality |
| `scripts/solar_grounding_check.py` | the number-authorship guard |
| `scripts/solar_latency_check.py` | per-stage timing across providers |

`scripts/solar_chat_devapp.py` serves the application on a second port with a
live trace of each Solara turn — gate decision, every retrieved chunk with its
score, what the extractor banked, the preview calculation, per-stage timings,
and the exact prompt sent. Use it when a reply looks wrong and you need to see
whether retrieval, the gate, extraction, or the model caused it.

---

## Academic context

Submitted in partial fulfillment of the requirements for the degree of Bachelor
of Science in Information Technology at the College of Computer Studies, Laguna
State Polytechnic University. Developed in partnership with EnergyWize Solutions
Inc., whose training programmes and consultation workflow the system models.

System quality was evaluated against **ISO/IEC 25010** characteristics through
user acceptance testing with the partner organization's staff and trainees.

---

## License

Academic work. Copyright © 2026 the researchers named above. Not licensed for
redistribution or commercial use without written permission.
