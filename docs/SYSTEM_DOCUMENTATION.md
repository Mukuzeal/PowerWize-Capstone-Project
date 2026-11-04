# PowerWize — System Documentation

System architecture, data-flow diagrams, UML models, and the entity-relationship
diagram for the PowerWize training-and-consultation platform.

Every diagram here was derived from the running source rather than drawn from
intent: the ERD is a transcription of `init_db()` in
[../src/db/core.py](../src/db/core.py), the component diagram follows the
blueprints registered in [../src/app.py](../src/app.py), and the use-case actors
match the `CAPABILITIES` map in [../src/permissions.py](../src/permissions.py).

Diagrams are written in Mermaid and render natively on GitHub.

**Contents**

1. [System architecture](#1-system-architecture)
2. [Context diagram (DFD level 0)](#2-context-diagram-dfd-level-0)
3. [Data-flow diagram (level 1)](#3-data-flow-diagram-level-1)
4. [Use-case diagram](#4-use-case-diagram)
5. [Entity-relationship diagram](#5-entity-relationship-diagram)
6. [Sequence diagrams](#6-sequence-diagrams)
7. [Module structure](#7-module-structure)

---

## 1. System architecture

PowerWize is a server-rendered Flask application. There is no SPA framework and
no build step: templates are Jinja2, the frontend is vanilla ES5-era JavaScript
that self-initialises from `data-` attributes, and persistence is raw `psycopg2`
against PostgreSQL with no ORM and no migration framework.

Four external services are integrated, and the system is deliberately designed so
that two of them can fail without taking a transaction down with them.

```mermaid
graph TB
    subgraph client["Client tier"]
        BROWSER["Browser<br/>Jinja2-rendered HTML<br/>vanilla JS, no build step"]
    end

    subgraph app["Application tier — Flask / gunicorn"]
        direction TB
        CORE["app.py<br/>app factory · CSRF · error handlers<br/>can() and role_label() Jinja globals"]

        subgraph bps["Blueprints (13)"]
            direction LR
            B1["auth · onboarding<br/>registration · site"]
            B2["admin · employee<br/>classes · company"]
            B3["payment · corporate_public<br/>upload_validation"]
            B4["lms · solar"]
        end

        subgraph svc["Domain services"]
            direction LR
            PERM["permissions.py<br/>CAPABILITIES map"]
            ENGINE["solar_engine.py<br/>compute()"]
            RAGMOD["rag/<br/>embeddings · retriever"]
            CHAIN["blockchain.py<br/>anchor · verify"]
            PRICE["pricing · review_policy<br/>secretbox · qr_gen"]
        end

        DB["db/ package<br/>get_db() · dict_cur()<br/>star-exported submodules"]
    end

    subgraph data["Data tier"]
        PG[("PostgreSQL<br/>36 tables<br/>schema applied by init_db()")]
        FS["Filesystem<br/>uploads/ · static/certificates/<br/>static/receipts/"]
        KB["knowledge/solar/*.md<br/>10 source documents"]
    end

    subgraph ext["External services"]
        PAYMONGO["PayMongo<br/>card + QRPH"]
        POLYGON["Polygon Amoy<br/>testnet anchoring"]
        AI["AI providers<br/>Groq Cloud / LM Studio"]
        SMTP["SMTP<br/>transactional mail"]
    end

    BROWSER -->|HTTPS| CORE
    CORE --> bps
    bps --> svc
    bps --> DB
    svc --> DB
    DB --> PG
    bps --> FS
    RAGMOD -.->|indexed offline by<br/>scripts/build_rag_index.py| KB
    RAGMOD --> PG

    B3 <-->|checkout session + webhook| PAYMONGO
    CHAIN -.->|best-effort, never blocking| POLYGON
    B4 --> AI
    svc --> AI
    CORE --> SMTP
```

### Architectural decisions worth noting

| Decision | Rationale |
|---|---|
| **Schema lives in code** | `init_db()` is the entire schema — `CREATE TABLE IF NOT EXISTS` plus idempotent `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` plus inline backfills. It re-runs on every boot, so a fresh clone and a long-lived database converge on the same shape without a migration tool. |
| **One capability map** | No route compares a role string inline. `CAPABILITIES` maps capability to roles, and `can()` is exposed as a Jinja global, so a hidden button and the route behind it read the same table and cannot disagree. |
| **Per-account capability overrides** | `user_capabilities` stores deviations from the role default, so one trainer can run training modules and another PV consultations. Enforcement goes through `current_can()`, which resolves default-then-override. |
| **Blockchain is best-effort** | Payments and certificates are valid whether or not the Polygon write lands. Failures are logged and surfaced in the UI as "Off-chain" with a re-anchor action; they never abort the transaction. |
| **Split AI providers** | `TEXT_PROVIDER`, `VISION_PROVIDER`, and `EMBED_PROVIDER` are independent knobs. A model good at reading a government ID is not the one you want writing quiz questions, and changing the chat model must not force a re-index. |
| **Numbers are never LLM-authored** | Every figure in a solar consultation comes from `solar_engine.compute()`. The model writes only number-free framing sentences, and a post-generation check discards its text if it contains a number matching no known value. |

### Technology stack

| Layer | Technology |
|---|---|
| Language / runtime | Python 3, Flask (WSGI, served by gunicorn) |
| Templating | Jinja2 — `templates/` at project root, shared macros in `templates/shared/` |
| Frontend | Vanilla JavaScript, no framework, no bundler; `IntersectionObserver`-driven motion |
| Database | PostgreSQL 18, accessed through raw `psycopg2` with `RealDictCursor` |
| Payments | PayMongo — card and QRPH, hosted checkout for corporate invoices |
| Blockchain | Polygon Amoy testnet via `web3.py` |
| AI | Groq Cloud or a local LM Studio server, selected per workload by env var |
| Retrieval | Brute-force cosine similarity over `REAL[]` embedding columns |
| Mail | SMTP |

---

## 2. Context diagram (DFD level 0)

The system boundary and the six external entities that cross it.

```mermaid
graph LR
    APPLICANT(["Applicant<br/>(public)"])
    TRAINEE(["Trainee"])
    TRAINER(["Trainer<br/>stored role: employee"])
    STAFF(["Admin · Super User<br/>Secretary"])
    COORD(["Company<br/>Coordinator"])
    PROSPECT(["Solar<br/>Prospect"])

    SYS{{"PowerWize<br/>Training and Consultation System"}}

    PAYMONGO[/"PayMongo<br/>payment gateway"/]
    POLYGON[/"Polygon Amoy<br/>blockchain"/]
    AIP[/"AI provider<br/>Groq / LM Studio"/]
    MAIL[/"SMTP<br/>mail server"/]

    APPLICANT -->|registration form,<br/>ID and selfie upload| SYS
    SYS -->|validation verdict,<br/>invitation token| APPLICANT

    TRAINEE -->|credentials, class join code,<br/>quiz and exam answers| SYS
    SYS -->|syllabus, AI feedback,<br/>progress, certificate| TRAINEE

    TRAINER -->|modules, quizzes,<br/>grades, consultation review| SYS
    SYS -->|submission inbox,<br/>trainee progress| TRAINER

    STAFF -->|approvals, schedules, accounts,<br/>discount codes, overrides| SYS
    SYS -->|dashboards, audit log,<br/>Excel exports| STAFF

    COORD -->|employee roster,<br/>requirements| SYS
    SYS -->|invoice, payment link,<br/>class join code| COORD

    PROSPECT -->|site survey, electricity bill,<br/>Taglish chat questions| SYS
    SYS -->|grounded answers,<br/>sizing and ROI quotation| PROSPECT

    SYS <-->|checkout session,<br/>webhook events| PAYMONGO
    SYS -.->|receipt and certificate hashes| POLYGON
    POLYGON -.->|transaction hash| SYS
    SYS <-->|prompts, completions,<br/>vision, embeddings| AIP
    SYS -->|tokens, receipts, notices| MAIL
```

---

## 3. Data-flow diagram (level 1)

The eight major processes inside the boundary and the data stores they touch.
Store numbering is reused in the ERD section.

```mermaid
graph TB
    APPLICANT(["Applicant"])
    STAFF(["Staff"])
    TRAINEE(["Trainee"])
    TRAINER(["Trainer"])
    COORD(["Coordinator"])
    PROSPECT(["Prospect"])
    PAYMONGO[/"PayMongo"/]
    POLYGON[/"Polygon Amoy"/]
    AIP[/"AI provider"/]

    P1("1.0<br/>Capture and validate<br/>registration")
    P2("2.0<br/>Review and admit<br/>applicant")
    P3("3.0<br/>Provision account")
    P4("4.0<br/>Collect payment<br/>and anchor receipt")
    P5("5.0<br/>Deliver training<br/>and assess")
    P6("6.0<br/>Issue and verify<br/>certificate")
    P7("7.0<br/>Advise on<br/>solar PV")
    P8("8.0<br/>Coordinate<br/>corporate intake")

    D1[("D1 · registrations<br/>+ document reviews")]
    D2[("D2 · users<br/>+ capabilities")]
    D3[("D3 · account_tokens")]
    D4[("D4 · payments<br/>+ corporate_payments")]
    D5[("D5 · lms_modules<br/>quizzes · exams")]
    D6[("D6 · lms_progress<br/>attempts · submissions")]
    D7[("D7 · lms_certificates")]
    D8[("D8 · solar_requests")]
    D9[("D9 · rag_chunks")]
    D10[("D10 · corporate_intakes<br/>slots · classes")]
    D11[("D11 · audit_logs")]

    APPLICANT -->|form + uploads| P1
    P1 -->|vision verdict request| AIP
    AIP -->|ID / selfie assessment| P1
    P1 --> D1
    P1 -->|accepted or rejected| APPLICANT

    D1 --> P2
    STAFF -->|approve · reject| P2
    P2 --> D1
    P2 -->|mint token| D3
    P2 --> D11

    D3 --> P3
    APPLICANT -->|token redemption| P3
    P3 -->|account, unpaid| D2

    D2 --> P4
    TRAINEE -->|card / QRPH| P4
    COORD -->|invoice settlement| P4
    P4 <-->|session + webhook| PAYMONGO
    P4 --> D4
    P4 -.->|receipt hash| POLYGON
    P4 -->|payment_status = paid| D2

    TRAINER -->|module, quiz, exam authoring| P5
    P5 -->|AI quiz generation| AIP
    P5 --> D5
    TRAINEE -->|answers, material progress| P5
    D5 --> P5
    P5 --> D6
    P5 -->|grades, AI feedback| TRAINEE
    D6 -->|progress rollup| TRAINER

    D6 --> P6
    P6 --> D7
    P6 -.->|certificate hash| POLYGON
    P6 -->|QR verification page| TRAINEE

    PROSPECT -->|survey + bill| P7
    P7 -->|bill OCR| AIP
    D9 -->|retrieved chunks| P7
    P7 -->|number-free framing only| AIP
    P7 --> D8
    D8 --> TRAINER
    TRAINER -->|reviewed figures| P7
    P7 -->|quotation| PROSPECT

    COORD -->|roster| P8
    STAFF -->|intake management| P8
    P8 --> D10
    P8 -->|slot invitations| D1
    D10 -->|join-code gate| P5
```

### Process summary

| # | Process | Implemented in |
|---|---|---|
| 1.0 | Capture and validate registration | [../src/registration.py](../src/registration.py), [../src/upload_validation.py](../src/upload_validation.py) |
| 2.0 | Review and admit applicant | [../src/admin/registrations.py](../src/admin/registrations.py), [../src/review_policy.py](../src/review_policy.py) |
| 3.0 | Provision account | [../src/onboarding.py](../src/onboarding.py), [../src/auth.py](../src/auth.py) |
| 4.0 | Collect payment and anchor receipt | [../src/payment_bp.py](../src/payment_bp.py), [../src/paymongo.py](../src/paymongo.py), [../src/corporate_checkout.py](../src/corporate_checkout.py) |
| 5.0 | Deliver training and assess | [../src/lms_bp/](../src/lms_bp/) |
| 6.0 | Issue and verify certificate | [../src/lms_bp/certificates.py](../src/lms_bp/certificates.py), [../src/blockchain.py](../src/blockchain.py) |
| 7.0 | Advise on solar PV | [../src/solar_bp.py](../src/solar_bp.py), [../src/solar_engine.py](../src/solar_engine.py), [../src/rag/](../src/rag/) |
| 8.0 | Coordinate corporate intake | [../src/admin/intake.py](../src/admin/intake.py), [../src/company_bp.py](../src/company_bp.py), [../src/classes_bp.py](../src/classes_bp.py) |

---

## 4. Use-case diagram

Five stored roles: `admin`, `super_user`, `secretary`, `employee`, `trainee`.
**`employee` is the stored value for what the interface calls a "Trainer"** — the
label changed, the value never did.

Super User is an Admin minus user management and minus deleting other people's
modules. Secretary is a Super User minus PV consultations. A Trainer's remit is
set per account rather than by role, so the two dashed capabilities below can be
granted or withdrawn individually.

```mermaid
graph LR
    APPLICANT(["Applicant"])
    TRAINEE(["Trainee"])
    TRAINER(["Trainer"])
    SEC(["Secretary"])
    SU(["Super User"])
    ADMIN(["Admin"])
    COORD(["Coordinator"])
    PROSPECT(["Prospect"])
    PUBLIC(["Public verifier"])

    subgraph UC_PUB["Public"]
        U1("Submit registration")
        U2("Redeem invitation token")
        U3("Request PV consultation")
        U4("Chat with Solara")
        U5("Verify certificate by QR")
        U6("Verify payment receipt")
    end

    subgraph UC_TRAINEE["Training"]
        U7("Pay enrolment fee")
        U8("Enter class join code")
        U9("Study module materials")
        U10("Attempt quiz")
        U11("Submit practical exam")
        U12("Request AI hint")
        U13("View progress")
        U14("Download certificate")
        U15("Rate module")
    end

    subgraph UC_TRAINER["Instruction"]
        U16("Author module")
        U17("Build quiz")
        U18("Generate quiz with AI")
        U19("Build practical exam")
        U20("Grade submission")
        U21("Track trainee progress")
        U22("Review PV consultation")
    end

    subgraph UC_STAFF["Administration"]
        U23("Review registration")
        U24("Manage schedules")
        U25("Manage accounts")
        U26("Manage corporate invoices")
        U27("Issue discount codes")
        U28("Create training class")
        U29("Export reports")
        U30("Read audit log")
        U31("Delete any module")
    end

    subgraph UC_CORP["Corporate"]
        U32("Submit employee roster")
        U33("Settle invoice")
        U34("Distribute join code")
    end

    APPLICANT --> U1
    APPLICANT --> U2
    PROSPECT --> U3
    PROSPECT --> U4
    PUBLIC --> U5
    PUBLIC --> U6

    TRAINEE --> U7
    TRAINEE --> U8
    TRAINEE --> U9
    TRAINEE --> U10
    TRAINEE --> U11
    TRAINEE --> U12
    TRAINEE --> U13
    TRAINEE --> U14
    TRAINEE --> U15

    TRAINER --> U16
    TRAINER --> U17
    TRAINER --> U18
    TRAINER --> U19
    TRAINER --> U20
    TRAINER --> U21
    TRAINER -.->|per-account<br/>review_solar| U22

    SEC --> U23
    SEC --> U24
    SEC --> U26
    SEC --> U27
    SEC --> U29
    SEC --> U28

    SU --> SEC
    SU --> U22

    ADMIN --> SU
    ADMIN --> U25
    ADMIN --> U30
    ADMIN --> U31

    COORD --> U32
    COORD --> U33
    COORD --> U34
```

### Capability matrix

Transcribed from `CAPABILITIES` in [../src/permissions.py](../src/permissions.py).
`O` marks a capability that can be overridden per account via `user_capabilities`.

| Capability | Admin | Super User | Secretary | Trainer | Trainee |
|---|:--:|:--:|:--:|:--:|:--:|
| `view_admin_console` | ✓ | ✓ | ✓ | | |
| `view_reports` | ✓ | ✓ | ✓ | | |
| `manage_users` | ✓ | | | | |
| `review_registrations` | ✓ | ✓ | ✓ | | |
| `manage_schedules` | ✓ | ✓ | ✓ | | |
| `manage_modules` | ✓ | ✓ | ✓ | ✓ **O** | |
| `manage_any_module` | ✓ | | | | |
| `review_solar` | ✓ | ✓ | | ✓ **O** | |
| `corporate_payments` | ✓ | ✓ | ✓ | | |
| `discount_codes` | ✓ | ✓ | ✓ | | |

User management, billing, and console access are role-defining and deliberately
**not** grantable per user; only `manage_modules` and `review_solar` on Trainer
are overridable.

---

## 5. Entity-relationship diagram

36 tables. Presented as five domain views rather than one unreadable sheet; a
consolidated relationship list follows. All keys are as declared in `init_db()`.

### 5.1 Identity, registration, and admission

```mermaid
erDiagram
    batches {
        serial id PK
        varchar name
        varchar type
        date start_date
        date_array dates
        timestamp created_at
    }
    registrations {
        varchar id PK "VARCHAR(8)"
        varchar form_type
        varchar form_label
        timestamp submitted_at
        varchar full_name
        varchar email
        varchar company_name
        varchar designation
        varchar training_type
        int batch_id FK
        varchar photo_id "stored filename"
        varchar resume
        varchar valid_id
        varchar selfie_with_id
        varchar status "pending|accepted|rejected"
        smallint is_qualified
        varchar gemp_designation
    }
    registration_document_reviews {
        serial id PK
        varchar reg_id FK
        varchar field
        varchar sha256 "evidence after purge"
        bigint byte_size
        varchar outcome
        int reviewed_by FK
        timestamp purged_at
    }
    account_tokens {
        varchar token PK
        varchar reg_id FK
        varchar email
        smallint is_qualified
        timestamp expires_at
        timestamp used_at
    }
    users {
        serial id PK
        varchar role "admin|super_user|secretary|employee|trainee"
        varchar fname
        varchar lname
        varchar email UK
        varchar password_hash
        varchar company_name
        varchar payment_status "unpaid|paid"
        varchar training_type
        smallint failed_login_attempts
        timestamp locked_until
        timestamp archived_at
    }
    user_capabilities {
        serial id PK
        int user_id FK
        varchar capability
        smallint granted
        int set_by FK
        timestamp set_at
    }
    password_reset_tokens {
        varchar token PK
        varchar email
        timestamp expires_at
        timestamp used_at
    }
    audit_logs {
        serial id PK
        int user_id FK
        varchar action
        varchar entity_type
        varchar entity_id
        text details
        timestamp created_at
    }

    batches ||--o{ registrations : "schedules"
    registrations ||--o{ account_tokens : "admits via"
    registrations ||--o{ registration_document_reviews : "evidence for"
    users ||--o{ user_capabilities : "overrides"
    users ||--o{ audit_logs : "acts in"
    users ||--o{ registration_document_reviews : "reviews"
```

`account_tokens` is the only bridge from `registrations` to `users`: there is
deliberately **no public signup route**, so an account cannot exist without an
approved registration behind it.

### 5.2 Learning management

```mermaid
erDiagram
    users {
        serial id PK
        varchar role
        varchar training_type
    }
    lms_modules {
        serial id PK
        varchar title
        text description
        int instructor_id FK
        varchar training_type
        smallint is_published
        int sort_order
        smallint is_locked
        timestamp archived_at
    }
    lms_module_files {
        serial id PK
        int module_id FK
        varchar filename
        varchar original_name
        varchar file_type
        int file_size
    }
    lms_quizzes {
        serial id PK
        int module_id FK,UK "one per module"
        varchar title
        int time_limit_mins
        int passing_score
        smallint is_ai_generated
        smallint is_published
    }
    lms_quiz_questions {
        serial id PK
        int quiz_id FK
        text question_text
        varchar question_type "multiple_choice|identification|enumeration|essay"
        text correct_answer
        int order_num
        int points
    }
    lms_quiz_choices {
        serial id PK
        int question_id FK
        text choice_text
        smallint is_correct
    }
    lms_quiz_attempts {
        serial id PK
        int user_id FK
        int quiz_id FK
        timestamp started_at
        timestamp submitted_at
        decimal score
        int tab_switches "proctoring signal"
        smallint completed
    }
    lms_quiz_answers {
        serial id PK
        int attempt_id FK
        int question_id FK
        int selected_choice_id FK
        text answer_text
    }
    lms_practical_exams {
        serial id PK
        int module_id FK,UK "one per module"
        varchar title
        text instructions
        text evaluation_criteria
        smallint requires_camera
    }
    lms_exam_questions {
        serial id PK
        int exam_id FK
        text question_text
        varchar question_type
        text correct_answer
        int order_num
        int points
    }
    lms_exam_submissions {
        serial id PK
        int user_id FK
        int exam_id FK
        varchar file_path
        timestamp submitted_at
        int grade
        text feedback
        int graded_by FK
        decimal auto_score
        smallint needs_review
    }
    lms_exam_answers {
        serial id PK
        int submission_id FK
        int question_id FK
        text answer_text
    }
    lms_progress {
        serial id PK
        int user_id FK
        int module_id FK
        decimal quiz_score
        smallint quiz_passed
        smallint exam_graded
        int exam_grade
        smallint material_pct
        smallint completed
        timestamp completed_at
    }
    lms_certificates {
        serial id PK
        int user_id FK
        varchar cert_id UK
        timestamp issued_at
        date expires_at
        int approved_by FK
        varchar tx_hash "Polygon anchor"
        varchar blockchain_token
        smallint anchor_version
    }
    feedback {
        serial id PK
        int user_id FK
        int module_id FK
        smallint rating
        text comment
    }

    users ||--o{ lms_modules : "instructs"
    lms_modules ||--o{ lms_module_files : "carries"
    lms_modules ||--|| lms_quizzes : "assessed by"
    lms_modules ||--|| lms_practical_exams : "assessed by"
    lms_quizzes ||--o{ lms_quiz_questions : "asks"
    lms_quiz_questions ||--o{ lms_quiz_choices : "offers"
    lms_quizzes ||--o{ lms_quiz_attempts : "attempted in"
    users ||--o{ lms_quiz_attempts : "attempts"
    lms_quiz_attempts ||--o{ lms_quiz_answers : "records"
    lms_quiz_questions ||--o{ lms_quiz_answers : "answered by"
    lms_quiz_choices ||--o{ lms_quiz_answers : "selected as"
    lms_practical_exams ||--o{ lms_exam_questions : "asks"
    lms_practical_exams ||--o{ lms_exam_submissions : "receives"
    users ||--o{ lms_exam_submissions : "submits"
    lms_exam_submissions ||--o{ lms_exam_answers : "records"
    lms_exam_questions ||--o{ lms_exam_answers : "answered by"
    users ||--o{ lms_progress : "progresses"
    lms_modules ||--o{ lms_progress : "tracked by"
    users ||--o{ lms_certificates : "earns"
    users ||--o{ feedback : "rates"
    lms_modules ||--o{ feedback : "rated in"
```

`lms_progress` and `feedback` both carry `UNIQUE (user_id, module_id)` — one
progress row and one rating per trainee per module. A trainee's syllabus is
resolved from `training_type`, never from identity.

### 5.3 Payments and billing

```mermaid
erDiagram
    users {
        serial id PK
        varchar payment_status
    }
    payments {
        serial id PK
        int user_id FK
        decimal amount_php
        varchar method "card|qrph"
        varchar paymongo_id
        varchar status
        varchar receipt_id
        varchar receipt_hash "SHA-256"
        varchar tx_hash "Polygon anchor"
        smallint anchor_version
        varchar qr_code_path
        timestamp paid_at
    }
    corporate_payments {
        serial id PK
        varchar reference UK
        varchar company_name
        varchar contact_person
        decimal list_total_php
        decimal custom_total_php "negotiated override"
        text override_note
        int override_by FK
        bigint amount_centavos
        varchar status
        varchar paymongo_id
        timestamp expires_at
        timestamp paid_at
        varchar receipt_hash
        varchar tx_hash
        int created_by FK
    }
    corporate_payment_items {
        serial id PK
        int corporate_payment_id FK
        int user_id FK
        varchar training_type
        decimal price_php
        varchar price_label
    }
    corporate_payment_attempts {
        serial id PK
        int corporate_payment_id FK
        varchar attempt_ref UK
        varchar idempotency_key UK
        bigint request_amount_centavos
        varchar environment
        varchar status
        varchar checkout_session_id
        text checkout_url
        varchar payment_intent_id
        varchar paid_payment_id
        text last_error
        timestamp settled_at
    }
    corporate_payment_events {
        serial id PK
        int corporate_payment_id FK
        int actor_id FK
        varchar action
        text details
    }
    unresolved_payment_events {
        serial id PK
        varchar source
        varchar event_type
        varchar checkout_session_id
        varchar payment_id
        varchar reference_hint
        bigint amount_centavos
        boolean livemode
        text reason
        text raw_event "verbatim webhook body"
        int resolved_by FK
        timestamp resolved_at
    }
    discount_codes {
        serial id PK
        varchar code
        varchar code_key UK
        smallint percent_off "1..100"
        date expires_on
        int max_uses
        int used
        varchar training_type
        smallint is_active
        int created_by FK
    }

    users ||--o{ payments : "pays"
    corporate_payments ||--o{ corporate_payment_items : "itemises"
    users ||--o{ corporate_payment_items : "billed in"
    corporate_payments ||--o{ corporate_payment_attempts : "attempted via"
    corporate_payments ||--o{ corporate_payment_events : "audited by"
    users ||--o{ corporate_payment_events : "acts in"
    users ||--o{ discount_codes : "issues"
    users ||--o{ unresolved_payment_events : "resolves"
```

`corporate_payment_attempts` carries `UNIQUE` on both `attempt_ref` and
`idempotency_key`, which is what makes settlement idempotent at the database
level rather than in application logic. A webhook that cannot be matched to an
invoice lands in `unresolved_payment_events` with its raw body intact instead of
being dropped — nothing is silently swallowed.

### 5.4 Corporate intake and class gating

```mermaid
erDiagram
    corporate_intakes {
        serial id PK
        varchar company_name
        varchar contact_person
        varchar contact_email
        varchar form_type
        varchar training_type
        varchar coord_token_hash UK "hashed, never stored raw"
        timestamp coord_expires_at
        timestamp coord_revoked_at
        varchar status "open|ready|closed|cancelled"
        timestamp payment_link_sent_at
        int created_by FK
    }
    corporate_intake_slots {
        serial id PK
        int intake_id FK
        varchar full_name
        varchar email
        varchar email_key "normalised, unique per intake"
        varchar invite_token_hash UK
        timestamp invite_expires_at
        timestamp invite_used_at
        timestamp invite_revoked_at
        varchar registration_id FK
    }
    corporate_notifications {
        serial id PK
        int intake_id FK
        varchar kind
        int slot_id FK
        varchar to_email
        varchar subject
        varchar status
        int attempts
        text last_error
        varchar dedupe_key UK
        timestamp sent_at
    }
    training_classes {
        serial id PK
        varchar name
        varchar training_type
        int intake_id FK
        int corporate_payment_id FK
        varchar join_code UK
        boolean join_open
        int created_by FK
        timestamp closed_at
    }
    training_class_members {
        serial id PK
        int class_id FK
        int user_id FK
        timestamp joined_at
        varchar authorised "roster|staff"
        int added_by FK
    }
    registrations {
        varchar id PK
    }
    corporate_payments {
        serial id PK
    }
    users {
        serial id PK
    }

    corporate_intakes ||--o{ corporate_intake_slots : "reserves"
    corporate_intakes ||--o{ corporate_notifications : "notifies via"
    corporate_intake_slots ||--o{ corporate_notifications : "addressed to"
    corporate_intake_slots |o--o| registrations : "fulfilled by"
    corporate_intakes |o--o{ training_classes : "cohorts into"
    corporate_payments |o--o{ training_classes : "funds"
    training_classes ||--o{ training_class_members : "rosters"
    users ||--o{ training_class_members : "enrolled as"
```

**The join code names a class; it never authorises.** `class_gate()` in
[../src/db/classes.py](../src/db/classes.py) re-derives entitlement on every
access, so a membership row is not standing authority — a later rejection,
roster revocation, or cancelled invoice closes access without anyone deleting
the row.

Two documented exceptions to "a corporate trainee must enter a code":

- **Individual enrolment is never gated.** Someone who paid for themselves is on
  no corporate invoice, so there is no class to join.
- **Access is open until a class exists** for their invoice or intake in that
  programme. If staff have not created one there is no code to enter, and
  denying training already paid for because of an internal gap is the wrong
  failure. The gate appears the moment the class does. This is a real hole in
  the rule, accepted knowingly.

### 5.5 Solar consultation and retrieval

```mermaid
erDiagram
    users {
        serial id PK
    }
    solar_requests {
        serial id PK
        int user_id FK "nullable — public intake"
        varchar name
        text address
        varchar email
        varchar contact
        varchar establishment_type
        varchar ownership
        varchar electrical_phase
        decimal monthly_bill_php
        decimal kwh_monthly
        int time_of_use_night_pct
        varchar target_savings
        decimal roof_sqm
        varchar bill_path
        decimal ocr_kwh "extracted from bill image"
        decimal ocr_bill_amount
        decimal system_size_kw "computed by solar_engine"
        int panel_count
        decimal cost_min
        decimal cost_max
        decimal monthly_savings
        decimal roi_years
        varchar feasibility
        varchar system_type
        varchar grid_connection "grid_tie|hybrid|off_grid"
        decimal battery_kwh_capacity
        decimal estimated_annual_yield_kwh
        smallint battery_recommended
        text ai_explanation "number-free framing only"
        varchar status
        text reviewer_notes
        decimal final_system_kw "staff-reviewed override"
        decimal final_cost
        decimal final_roi_years
        smallint out_of_scope
        text out_of_scope_reason
    }
    rag_chunks {
        serial id PK
        varchar source_type
        varchar source_ref "knowledge/solar/*.md"
        varchar title
        text content
        varchar visibility "public|internal"
        varchar topic
        real_array embedding "REAL[] — brute-force cosine"
        varchar embed_model
        varchar content_hash "re-index detection"
        timestamp updated_at
    }

    users |o--o{ solar_requests : "requests"
```

`rag_chunks` has no foreign keys by design: it is a derived index rebuilt from
`knowledge/solar/*.md` by `scripts/build_rag_index.py`, and `content_hash` is
what lets a re-index skip unchanged chunks. The paired `*_php` / `final_*`
columns on `solar_requests` keep the engine's computation and the staff-reviewed
figure separately auditable rather than overwriting one with the other.

### 5.6 Consolidated relationship list

| Parent | Child | Cardinality | On delete |
|---|---|---|---|
| `batches` | `registrations` | 1:N | SET NULL |
| `registrations` | `account_tokens` | 1:N | CASCADE |
| `registrations` | `registration_document_reviews` | 1:N | CASCADE |
| `registrations` | `corporate_intake_slots` | 1:1 | SET NULL |
| `users` | `user_capabilities` | 1:N | CASCADE |
| `users` | `payments` | 1:N | CASCADE |
| `users` | `solar_requests` | 1:N | SET NULL |
| `users` | `lms_modules` | 1:N | CASCADE |
| `users` | `lms_quiz_attempts` | 1:N | CASCADE |
| `users` | `lms_exam_submissions` | 1:N | CASCADE |
| `users` | `lms_progress` | 1:N | CASCADE |
| `users` | `lms_certificates` | 1:N | CASCADE |
| `users` | `feedback` | 1:N | CASCADE |
| `users` | `training_class_members` | 1:N | CASCADE |
| `users` | `corporate_payment_items` | 1:N | CASCADE |
| `users` | `audit_logs` | 1:N | SET NULL |
| `lms_modules` | `lms_module_files` | 1:N | CASCADE |
| `lms_modules` | `lms_quizzes` | 1:1 | CASCADE |
| `lms_modules` | `lms_practical_exams` | 1:1 | CASCADE |
| `lms_modules` | `lms_progress` | 1:N | CASCADE |
| `lms_modules` | `feedback` | 1:N | CASCADE |
| `lms_quizzes` | `lms_quiz_questions` | 1:N | CASCADE |
| `lms_quizzes` | `lms_quiz_attempts` | 1:N | CASCADE |
| `lms_quiz_questions` | `lms_quiz_choices` | 1:N | CASCADE |
| `lms_quiz_questions` | `lms_quiz_answers` | 1:N | CASCADE |
| `lms_quiz_choices` | `lms_quiz_answers` | 1:N | SET NULL |
| `lms_quiz_attempts` | `lms_quiz_answers` | 1:N | CASCADE |
| `lms_practical_exams` | `lms_exam_questions` | 1:N | CASCADE |
| `lms_practical_exams` | `lms_exam_submissions` | 1:N | CASCADE |
| `lms_exam_submissions` | `lms_exam_answers` | 1:N | CASCADE |
| `lms_exam_questions` | `lms_exam_answers` | 1:N | CASCADE |
| `corporate_intakes` | `corporate_intake_slots` | 1:N | CASCADE |
| `corporate_intakes` | `corporate_notifications` | 1:N | CASCADE |
| `corporate_intakes` | `training_classes` | 1:N | SET NULL |
| `corporate_intake_slots` | `corporate_notifications` | 1:N | SET NULL |
| `corporate_payments` | `corporate_payment_items` | 1:N | CASCADE |
| `corporate_payments` | `corporate_payment_attempts` | 1:N | CASCADE |
| `corporate_payments` | `corporate_payment_events` | 1:N | CASCADE |
| `corporate_payments` | `training_classes` | 1:N | SET NULL |
| `training_classes` | `training_class_members` | 1:N | CASCADE |
| `discount_codes` | — | standalone | — |
| `rag_chunks` | — | derived index | — |
| `password_reset_tokens` | — | keyed by email | — |
| `unresolved_payment_events` | — | webhook quarantine | — |

---

## 6. Sequence diagrams

### 6.1 The trainee lifecycle

This one flow spans most of the codebase, which is why several otherwise-odd
design choices exist.

```mermaid
sequenceDiagram
    autonumber
    actor A as Applicant
    participant REG as registration
    participant VAL as upload_validation
    participant VIS as Vision model
    actor S as Staff
    participant ADM as admin.registrations
    participant MAIL as SMTP
    participant ONB as onboarding
    participant PAY as payment
    participant PM as PayMongo
    participant CH as blockchain
    participant POLY as Polygon Amoy
    participant LMS as lms

    A->>REG: GET public registration form
    A->>VAL: POST /api/validate-upload (ID, selfie)
    VAL->>VIS: classify document, match faces
    VIS-->>VAL: verdict
    VAL-->>A: accept or ask for a better photo
    A->>REG: POST form + uploads
    REG->>REG: persist registration (status = pending)

    S->>ADM: review queue
    ADM->>ADM: approve — record document evidence, purge images
    ADM->>MAIL: email invitation token
    MAIL-->>A: /create-account/<token>

    A->>ONB: redeem token, set password
    ONB->>ONB: create user (payment_status = unpaid)
    Note over ONB: training_type and is_qualified<br/>are carried by the token,<br/>not chosen by the applicant

    A->>PAY: checkout (card or QRPH)
    PAY->>PM: create payment intent
    PM-->>PAY: webhook payment.paid
    PAY->>PAY: mark paid, mint receipt_id + receipt_hash
    PAY--)CH: anchor receipt hash
    CH--)POLY: write
    POLY--)CH: tx_hash (or failure — logged, not fatal)
    PAY->>PAY: users.payment_status = paid

    A->>LMS: GET /portal
    alt corporate trainee and a class exists
        LMS-->>A: ask for class join code
        A->>LMS: submit join code
        LMS->>LMS: class_gate() re-derives entitlement
    end
    LMS-->>A: syllabus resolved from training_type
    A->>LMS: attempt quizzes, submit practical exam
    LMS->>LMS: auto-grade MC / identification / enumeration
    Note over LMS: essays go to manual review
    LMS->>LMS: issue certificate once all modules complete
    LMS--)POLY: anchor certificate hash
    LMS-->>A: certificate + public QR verification page
```

### 6.2 A Solara consultation turn

The gate runs **before** any chat LLM call, and the model never authors a number.

```mermaid
sequenceDiagram
    autonumber
    actor P as Prospect
    participant SB as solar_bp
    participant EX as AI extractor
    participant GATE as Topic gate
    participant RET as rag.retriever
    participant DB as rag_chunks
    participant ENG as solar_engine
    participant LLM as Chat model

    P->>SB: question (English or Taglish)
    SB->>EX: extract any facts stated in the turn
    EX-->>SB: bill amount, roof area, phase, ...
    SB->>SB: bank extracted facts on the session

    SB->>GATE: is this about solar PV?
    GATE->>GATE: keyword allowlist first
    alt allowlist misses
        GATE->>LLM: cheap yes/no gate call
        LLM-->>GATE: verdict
    end
    alt off topic
        GATE-->>P: deterministic decline — no chat call made
    end

    SB->>RET: embed query, retrieve
    RET->>DB: brute-force cosine over REAL[]
    DB-->>RET: scored chunks
    RET-->>SB: chunks above RAG_MIN_SCORE

    opt enough facts banked
        SB->>ENG: compute()
        ENG-->>SB: sizing, cost range, savings, ROI
    end

    SB->>LLM: retrieved chunks + known values<br/>instruction: write framing, no numbers
    LLM-->>SB: prose
    SB->>SB: scan reply for numbers
    alt a number matches no known value
        SB->>SB: discard model text, fall back to<br/>deterministic template
    end
    SB-->>P: grounded answer with engine-authored figures
```

### 6.3 Corporate invoice settlement

```mermaid
sequenceDiagram
    autonumber
    actor C as Coordinator
    actor S as Staff
    participant INT as admin.intake
    participant CORP as admin.corporate
    participant CO as corporate_checkout
    participant PM as PayMongo
    participant WH as payment webhook
    participant CLS as classes

    C->>INT: submit employee roster
    INT->>INT: create intake + one slot per employee
    INT->>C: per-employee invitation links
    C->>INT: employees complete registration via slots

    S->>CORP: build invoice from approved employees
    CORP->>CORP: price each item, optional negotiated override
    S->>CO: send payment link
    CO->>PM: create hosted checkout session
    Note over CO: attempt row carries a UNIQUE<br/>idempotency_key — a retry cannot<br/>double-charge
    CO->>C: checkout URL

    C->>PM: pay
    PM-->>WH: checkout_session.payment.paid
    WH->>WH: envelope-agnostic extraction
    alt invoice matched
        WH->>CORP: settle, mint receipt, anchor hash
    else no match
        WH->>WH: quarantine in unresolved_payment_events<br/>with the raw body
    end

    S->>CLS: create training class for the invoice
    CLS->>C: join code
    C->>C: distribute to employees
    Note over CLS: class_gate() re-derives entitlement<br/>on every LMS access
```

---

## 7. Module structure

```mermaid
graph TB
    subgraph entry["Entry point"]
        APP["app.py<br/>registers 13 blueprints"]
    end

    subgraph public["Public-facing"]
        AUTH["auth.py"]
        REGI["registration.py"]
        SITE["site_bp.py<br/>site_content.py · site_icons.py"]
        ONBO["onboarding.py"]
        CPUB["corporate_public_bp.py"]
    end

    subgraph staff["Staff consoles"]
        ADMP["admin/<br/>dashboard · users · registrations<br/>analytics · exports · corporate<br/>intake · classes · discounts<br/>payments_ops"]
        EMPL["employee_bp.py<br/>trainer console (hash-routed)"]
        COMP["company_bp.py"]
        CLSB["classes_bp.py"]
    end

    subgraph domain["Domain blueprints"]
        LMSP["lms_bp/<br/>modules · quizzes · exams<br/>certificates · learning · _shared"]
        SOLP["solar_bp.py"]
        PAYP["payment_bp.py<br/>paymongo.py · corporate_checkout.py"]
        UPV["upload_validation.py"]
    end

    subgraph shared["Shared services"]
        PERMM["permissions.py"]
        ENGM["solar_engine.py"]
        RAGP["rag/<br/>embeddings · retriever"]
        BCH["blockchain.py<br/>blockchain_utils.py"]
        MISC["pricing · review_policy<br/>secretbox · qr_gen<br/>email_utils · ocr_module · utils"]
    end

    subgraph persist["Persistence"]
        DBP["db/<br/>core · users · registrations<br/>payments · lms · solar · rag<br/>corporate · intake · classes<br/>checkout · discounts<br/>notifications · misc"]
    end

    APP --> public
    APP --> staff
    APP --> domain
    public --> shared
    staff --> shared
    domain --> shared
    public --> DBP
    staff --> DBP
    domain --> DBP
    shared --> DBP
```

### Package conventions

- **Flat sibling imports.** Every module imports its siblings flat
  (`from db import ...`, `from lms_bp._shared import ...`), so the app must run
  with `src/` as the working directory and on `sys.path`. `Procfile` does this
  with `gunicorn --chdir src app:app`.
- **`db/` star-exports its submodules** from `__init__.py`, so callers always
  write `from db import <anything>` regardless of which file a function lives in.
  `get_db()` returns a connection and `dict_cur(conn)` a `RealDictCursor`;
  callers close both by hand.
- **`lms_bp/` and `admin/` create their blueprint in `__init__.py`, then import
  their route modules at the bottom.** The circular-looking import is
  deliberate — it is what lets each route module write `from . import lms_bp`.
- **Progress folds through one function.** Trainer-facing and trainee-facing
  progress both go through `_progress_steps()` in
  [../src/lms_bp/_shared.py](../src/lms_bp/_shared.py), so the two views cannot
  disagree.

### Security notes

| Control | Where |
|---|---|
| CSRF | Global via `CSRFProtect`. Three views are genuinely exempt (PayMongo webhook and the two upload-validation APIs). `solar_chat_cancel` is exempt only from the automatic header check — `navigator.sendBeacon()` cannot set one — and validates the token out of the JSON body itself. |
| Password storage | Werkzeug password hashing; `failed_login_attempts` and `locked_until` throttle credential stuffing. |
| Account creation | Invitation-only. A plain email+password signup would mint trainees that skipped ID upload, selfie liveness, and admin verification. |
| Token handling | Coordinator and slot invitation tokens are stored as SHA-256 hashes (`coord_token_hash`, `invite_token_hash`), never in the clear, and carry explicit expiry and revocation columns. |
| Document minimisation | Government IDs and selfies are purged after review; `registration_document_reviews` retains only a SHA-256 digest, byte size, extension, and the outcome as audit evidence. |
| Authorisation | Single `CAPABILITIES` table; `current_can()` resolves per-account overrides. Wrong role raises `abort(403)`, and the handler content-negotiates HTML against JSON. |
| Payment integrity | `UNIQUE` idempotency keys at the database level; unmatched webhooks are quarantined with their raw body rather than dropped. |
