# PowerWize — Interface Screenshots

Captured 2026-10-23 against the local stack (Flask on `:5000`, local Postgres)
at 1600×1000, `device_scale_factor=2`, full-page. Every frame is the real
running app — no mockups, no edited pixels.

AI panels ran with `TEXT_PROVIDER=groq` because LM Studio was not up. One
exception is noted under section 3.

---

## 1 · Administrative Dashboard
`1-administrative-dashboard/`

| File | Shows |
|---|---|
| `00_login.png` | Public sign-in (shared by every role) |
| `01_dashboard_overview.png` | KPI tiles — users, registrations, schedules, trainees |
| `02_user_management.png` | Account list with role labels and archive controls |
| `03_schedules.png` | Training schedule management |
| `04_registration_review.png` | The 45-row registration queue with approve/reject |
| `05_corporate_payments.png` | Corporate billing accounts |
| `06_discount_codes.png` | Discount code administration |
| `07_modules_oversight.png` | Cross-program module oversight |
| `08_export_reports.png` | CSV export surface |
| `09_trainee_feedback.png` | Collected module ratings |
| `10_audit_log.png` | Audit trail |
| `11_analytics.png` | `/admin/analytics` |
| `12_create_user_form.png` | Account creation form |

## 2 · Instructor Training Management
`2-instructor-training-management/` — signed in as Patricia Villanueva (Trainer)

| File | Shows |
|---|---|
| `01_trainer_console_dashboard.png` | Trainer console landing |
| `02_training_modules.png` | Modules the trainer owns |
| `03_exam_submissions_inbox.png` | Practical-exam inbox |
| `04_solar_consultations_queue.png` | PV consultations (per-account capability) |
| `05_trainee_progress.png` | Progress across their trainees |
| `06_module_library.png` | Full module library |
| `07_module_manage.png` | Single-module management |
| `08_quiz_builder.png` | Quiz Manager mid-*Generate with AI* — 10 questions drafted from the module PDF, awaiting review. The "Questions 7" badge is the saved count: generation returns drafts to the form and writes nothing until *Save AI Questions* |
| `09_practical_exam_builder.png` | Practical exam + evaluation criteria |
| `10_create_module_form.png` | New module form |
| `11_grading_queue.png` | Grading queue |

## 3 · Trainee Training and AI Feedback
`3-trainee-training-ai-feedback/` — signed in as Miguel Torres (Trainee, 5/5 complete)

| File | Shows |
|---|---|
| `01_trainee_portal.png` | Trainee portal |
| `02_my_syllabus.png` | Syllabus resolved from `training_type` |
| `03_module_workspace.png` | Materials, quiz, exam, completion, rating |
| `04_ai_assistant_question.png` | Question typed into the Module Assistant |
| `05_ai_assistant_reply.png` | **Shows the graceful failure path, not a live answer** |
| `06_my_progress.png` | Progress view |
| `07_quiz_attempt.png` | Quiz attempt screen |

> `05_ai_assistant_reply.png` was **re-shot on 2026-11-04** and now shows a live
> answer. The original rendered *"Sorry, I could not respond."* because
> `_ai_module_chat()` posted to `LM_STUDIO_URL` unconditionally and never
> branched on `TEXT_PROVIDER`, so under `TEXT_PROVIDER=groq` it could not work
> at all. Both it and `_ai_generate_quiz()` now dispatch through `_text_chat()`,
> which honours the provider setting, and the reply passes through
> `_strip_markdown()` / `_paragraphize()` so the panel shows prose rather than
> the raw `**` and `|---|` the model would otherwise emit.

## 4 · Solar PV Consultation
`4-solar-pv-consultation/`

| File | Shows |
|---|---|
| `01_consultation_intake.png` | Structured intake form |
| `02_solara_chat_opening.png` | Solara's opening turn + privacy notice |
| `03_solara_user_question.png` | Question composed |
| `04_solara_knowledge_reply.png` | **RAG-grounded answer with a `Sources:` citation line** |
| `05_solara_taglish_quotation.png` | Taglish turn; quotation panel fills; figures from `solar_engine.compute()` |
| `06_admin_consultation_queue.png` | Admin review queue |
| `07_admin_consultation_review.png` | Consultation detail / decision |

## 5 · Payment Interface and Verification Records
`5-payment-verification/`

| File | Shows |
|---|---|
| `01_receipt_verification_portal.png` | Public `/verify` receipt check |
| `02_corporate_billing_records.png` | Corporate payment records |
| `03_discount_code_records.png` | Discount code records |
| `04_payment_checkout.png` | ₱18,000 checkout, PayMongo card form |
| `05_payment_card_method.png` | Card method selected |
| `06_payment_qrph_method.png` | QRPH / e-wallet method |

## 6 · Tokenized Certificate and Verification
`6-tokenized-certificate-verification/`

| File | Shows |
|---|---|
| `01_certificate_issuance_console.png` | Eligible trainees before issuance |
| `02_certificate_issued_result.png` | 1 issued · 1 on blockchain · On-chain badge |
| `03_trainee_certificate_wallet.png` | The trainee's own certificate view |
| `04_public_qr_verification.png` | Public QR verification page |

The certificate in these frames is a **real Polygon Amoy anchor**, not a mock:

```
cert id      300cdcc6550be117ccb917953f3048a0
transaction  0x3021448c822ede73a67e2bdd5857e0d3dcef449b1b9304df30dc519ae3f52230
block        #50943409 · 9 confirmations
status       Verified on Polygon — the record is unchanged since issue
```
