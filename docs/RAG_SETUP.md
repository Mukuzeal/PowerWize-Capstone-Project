# Solar RAG Setup

Retrieval-augmented grounding for Solara, the solar PV consultation chatbot (`src/solar_bp.py`). Keeps Solara's answers to actual open-ended solar questions sourced from a hand-edited knowledge base (`knowledge/solar/*.md`) and real computed numbers (`src/solar_engine.py`), instead of the model's own memory. Scoped to that chat only — bill OCR (`VISION_PROVIDER`) and structured field extraction are untouched.

## Env vars

Add these to `.env` (defaults shown are what ships in `.env.example`):

```
EMBED_PROVIDER=local_cpu           # local_cpu (default) | lmstudio
EMBED_MODEL=BAAI/bge-small-en-v1.5 # fastembed model id, or the LM Studio embedding model name if EMBED_PROVIDER=lmstudio
RAG_MIN_SCORE=0.55                 # cosine similarity floor — see the reasoning below
RAG_GROQ_FALLBACK=0                # 1 = retry through Groq once if LM Studio fails
```

`EMBED_PROVIDER` is independent of `TEXT_PROVIDER`. Switching which model answers chat (LM Studio vs Groq) never requires re-indexing, and `local_cpu` embeddings work even when LM Studio isn't running — that's the whole point of defaulting to CPU (fastembed/ONNX, no GPU, no torch/CUDA) on a machine where the chat model needs the GPU.

## Running the indexer

```powershell
cd src
..\venv\Scripts\python.exe ..\scripts\build_rag_index.py            # incremental — only changed chunks re-embed
..\venv\Scripts\python.exe ..\scripts\build_rag_index.py --rebuild  # wipe rag_chunks and re-embed everything
```

It indexes `knowledge/solar/*.md` (chunked by heading, ~300-500 tokens each, small overlap) plus the non-personal "renewable-energy" capability row of `src/site_content.py`. It never touches `solar_requests` or any other table with customer data — only PV knowledge and EnergyWize's own published offerings go in the index, since retrieved chunks can be sent to Groq's cloud API.

Re-indexing is a normal terminal command, not an admin UI action — there's no in-app re-index button. If that becomes annoying, a `require_admin()`-guarded route that shells out to this script is a reasonable future addition; it just isn't built now.

## Editing the knowledge base

Edit any file under `knowledge/solar/` and re-run the indexer (no `--rebuild` needed — unchanged chunks are skipped via content hash, changed/new ones re-embed, removed headings get deleted).

**Don't put numbers in these files that also live in `solar_engine.py`** — electricity rate, peak sun hours, panel wattage, cost per kWp, battery cost, maintenance percentage. Refer to them by name ("the system's electricity-rate assumption") and let the CALCULATIONS block (built live from `solar_engine.compute()`) supply the actual figure. This is why the old "₱10-12/kWh" fact that used to live in the chat's system prompt is gone rather than fixed in place — it disagreed with `solar_engine.ELECTRICITY_RATE` and there's no way to keep two hand-maintained copies of the same number in sync. Same rule for ROI/payback: describe what it means conceptually, never state a number or range.

Every fact not already sourced from code carries a `TODO: verify ...` marker — treat those as unverified until checked against a real source (DOE/ERC/DU guideline, manufacturer datasheet) before relying on them for a real customer conversation.

## Where the calculation assumptions live

`src/solar_engine.py::compute()` — the single deterministic source for system size, panel count, cost range, battery sizing, savings, and payback. Named module-level constants (`ELECTRICITY_RATE`, `PEAK_SUN_HOURS`, `COST_MIN_PER_KWP`/`COST_MAX_PER_KWP`, `PANEL_WATTAGE_W`, `MAINTENANCE_ANNUAL_PCT`, the battery cost/DOD/autonomy constants) are what to edit to change an assumption — update the constant, not any prompt text. `ELECTRICITY_RATE` specifically carries a `TODO: verify ... against the current published Meralco/DU rate` comment; confirm it before trusting it for a real quotation.

The LLM never computes these numbers itself, in chat or in the final write-up — `solar_bp.py` calls `solar_compute()` and only asks the model to explain the resulting dict in plain language. `scripts/solar_calc_check.py` prints the function's output for a handful of sample inputs so the math can be hand-checked without going through the chat at all.

## `RAG_MIN_SCORE` — how it was chosen

BGE-family embedding models score unrelated text higher than intuition suggests, so a threshold can't be guessed — it has to come from actual scores. `scripts/rag_eval.py` prints the cosine similarity for every retrieved chunk, grouped by question category, against the real indexed corpus. Current eval set is 20 questions (5 in-KB, 4 not-in-KB, **7 off-topic — English and Taglish**, 2 numeric, 2 Taglish with no `?`):

- Off-topic questions' worst (highest) top-1 score was **0.6339** ("Ano ang pinakamalaking bansa sa mundo?" — a Tagalog geography question that partly matched a PH-focused chunk on language/lexical similarity rather than actual topic relevance).
- The weakest top-1 score among every genuinely solar-related question was **0.6581** (a not-in-KB pricing-comparison question).

`RAG_MIN_SCORE=0.55` sits below both of those, not between them — the margin here is thin (~0.024 between the two, and the threshold itself is a further ~0.08 below the off-topic ceiling). Adding harder Tagalog off-topic questions to the eval set shrank the gap considerably from an earlier smaller-set run (which showed off-topic capping at 0.5275). **Retrieval score alone is not a reliable off-topic filter for Tagalog queries against this corpus** — the actual defense against off-topic answers is the grounding-prompt instruction below, not the score cutoff. Re-run `rag_eval.py` and revisit both the constant and the grounding prompt if the knowledge base or question mix changes.

```powershell
cd src
..\venv\Scripts\python.exe ..\scripts\rag_eval.py --provider lmstudio
..\venv\Scripts\python.exe ..\scripts\rag_eval.py --provider groq
```

## Embedding model choice — `bge-small-en-v1.5` vs a multilingual model

Solara gets a lot of Taglish traffic, so a multilingual embedding model (`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, also fastembed-supported, same 384 dims) was tested as an alternative to the English-only default. Raw top-1 cosine scores across the same 20-question eval set (unfiltered, no threshold applied), sorted:

| Model | Off-topic worst (max) top-1 | Weakest *legitimate* top-1 | Verdict |
|---|---|---|---|
| `BAAI/bge-small-en-v1.5` (default) | 0.6339 | 0.6581 (not_in_kb) | Thin (0.024) but **unbroken** gap — every legitimate question outscores every off-topic one |
| `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | 0.4350 | **0.2947** (a legitimate Taglish numeric question) | **No usable threshold** — that Taglish question ("magkano po kaya kung 5000 ang bill ko") scored *below* 4 of the 7 off-topic questions |

The multilingual model does fix the narrow "Pilipinas" lexical-overlap problem (see the grounding-rules fix above) — off-topic Tagalog questions score lower overall. But it does so by compressing scores generally, which pulled a real Taglish question about the user's own bill down into the same range as off-topic Tagalog chit-chat — a worse, unresolvable failure mode for this corpus and question mix, not a better one.

**Kept `BAAI/bge-small-en-v1.5` as the default.** The residual off-topic margin risk it has is handled by the grounding-prompt fix above (a marginally-scoring chunk no longer licenses an off-topic answer), which is a more robust fix than chasing a cleaner score gap. `EMBED_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` remains a documented, tested option if the corpus or question mix changes enough to revisit this — re-run the comparison above before switching, don't assume it still holds.

## Off-topic handling is a deterministic gate, not a prompt instruction

An earlier version of this pipeline relied on `GROUNDING_RULES` alone (a prompt instruction telling the model to decline off-topic questions). That measurably helped but wasn't reliable on the local model — English off-topic questions declined cleanly and consistently, but Tagalog ones were inconsistent run to run: a clean decline one time, a partial answer slipping through the next (stating a country's land area, or a real person's name), and at least once a degenerate repetition loop until `max_tokens` cut it off.

**The fix is to stop asking the model to decide, and decide before it's ever invoked.** Two layers run before any chat call, in order:

1. **`_has_topic_keyword()`** — a deterministic keyword allowlist (`_TOPIC_KEYWORDS`: solar, panel, inverter, battery, kwh, bill, kuryente, bagyo, brownout, warranty, etc. — plus "magkano"/"how much" combined with a digit, plus "net metering"). A hit here skips the LLM gate entirely and treats the message as on-topic, no model call at all. This exists because the LLM gate, even with history and few-shot examples, was observed to *consistently* (not flakily) misclassify some self-contained Taglish questions with clear domain vocabulary — e.g. "magkano po kaya kung 5000 ang bill ko" was wrongly gated off-topic in 3/3 test runs despite containing "bill" and a number. A false "off-topic" blocks a real customer, which is worse than a false "on-topic" (worst case there: a slightly off-target retrieval, or a "don't have that info" fallback) — so the list is deliberately generous, and the LLM gate only ever gets a chance to block messages that hit none of these words.
2. **`_is_on_topic()`** — only reached if the keyword check misses. Same provider-dispatch pattern as `_ai_extract` (JSON-schema on LM Studio, `json_object` on Groq, `temperature=0`), but with two additions over the first version: it's given the **last 1-2 conversation turns** (`history` param) so a context-dependent follow-up ("okay lang ba kahit laging bumabagyo dito?", "e kung tag-ulan?") is judged with the conversation it belongs to rather than in isolation, and the system prompt carries a handful of **few-shot examples** — including a Taglish money question (on-topic) and Tagalog general-knowledge questions (off-topic) — since those were exactly the cases the plain instruction got wrong.

`_gate_and_retrieve()` wires this together with retrieval:
- Keyword hit, or gate says on-topic → proceeds toward retrieval.
- No keyword hit and gate says off-topic → a fixed canned redirect (`_CANNED_OFF_TOPIC_EN`/`_TL`), no chat LLM call at all.
- On-topic (by either path) but retrieval finds nothing → a fixed "don't have that information" canned reply (`_CANNED_NO_INFO_EN`/`_TL`), also no chat LLM call. Distinct from off-topic — it means the question was legitimate, retrieval just didn't find a match above `RAG_MIN_SCORE`.
- On-topic and retrieval finds something → proceeds to the normal numeric or general-grounded chat path.

The canned reply's language (English vs Taglish) is picked by `_pick_canned()` off a broad Tagalog marker-word list (`_TAGALOG_MARKERS`) — deliberately broader than `_QUESTION_WORDS`, since this is a language-identification problem, not a question-intent one. It needs to be broad: an earlier, narrower version of this list missed core words like "ang", "ng", "sino", "ngayon", and sent an English canned reply to a fully-Tagalog off-topic question.

**The gate can still be wrong** — even with all of the above, it's a small model making a judgment call, not infallible. `scripts/rag_eval.py`'s `borderline_legit` category (including four follow-up-style questions that only make sense given prior turns, run with `history` set) exists specifically to catch this; a false negative is reported for **every** category except `off_topic` itself (where a "gated off-topic" result is the *correct* outcome, not a failure). If the provider call itself fails (network error), `_is_on_topic()` returns `None`, which is treated as "don't gate" — falls through to the normal flow rather than silently blocking a legitimate question on a hiccup.

## The number-check is unit-aware, not just value-aware

`_extract_numbers()` returns `(value, unit)` pairs — e.g. `(100.0, "pct")` — rather than bare numbers. This matters: `collected["target_savings"] = "100"` (meaning 100%) and a fabricated "₱100" both round to the bare value `100.0`, so an earlier bare-value version of this check let a model's "you're aiming for ₱100 in savings" slip through ungrounded, since `100` genuinely was an allowed number — just meant as a percentage, not pesos. `_raw_numbers_from_dict()` now maps each known field (`collected`, `solar_engine.compute()`'s `result`, `req`) to its real unit via `_FIELD_UNITS` before comparing, so a value can only ground a claim that uses it with the *same* unit. Applies everywhere the check runs: `_answer_numeric_turn`, `_answer_general_turn`, and `_llama_recommendations` (where `PANEL_WATTAGE_W` is now tagged `"watt"` explicitly, since it's a prompt-stated fact that isn't itself a key in `result`).

This makes the general chat path stricter than the numeric-only version was — a correct-but-unretrieved general-knowledge aside would now get discarded too, and exact-match strictness means even a *rounded* real number (e.g. "around 4,200 kWh" for an actual value of 4,182.6) fails the check and falls back to the deterministic template. Both are the intended tradeoff (never show an unverified — or even imprecisely restated — figure), not bugs.

## Repetition loops

Three layers, in order of when they act:

1. **`repeat_penalty: 1.12`** in the LM Studio request body (`_call_lmstudio`) — a llama.cpp-native sampling parameter, not part of the OpenAI schema, but LM Studio's server passes extra JSON fields through to the sampler. Verified empirically, not just "no HTTP error": the same prompt that reliably produced a repeated block without this field produced clean, non-repeating output with it, across a direct side-by-side test outside the full pipeline.
2. **`max_tokens=384`** for normal chat replies specifically (`_answer_general_turn`) — shortens the window a loop has to run away in, while leaving enough room that a legitimate multi-point Taglish answer doesn't routinely truncate mid-sentence (256 was tried first and cut off answers too often). Numeric-turn framing is separately capped by `_cap_sentences`; `_llama_recommendations()` keeps 512, since it's a deliberately longer write-up.
3. **`_detect_repetition()`** — deterministic, no LLM: if any normalized sentence repeats 3+ times, truncates to whatever came before its first occurrence. Runs inside `_ai_chat()` itself, so every caller gets it for free. If what's left is too short to be useful (under ~15 characters — the loop started almost immediately), `_ai_chat()` falls back to a generic, language-matched retry prompt (`_GENERIC_RETRY_EN`/`_TL`) rather than showing a near-empty reply.

In practice, the topic gate above removes the main trigger observed in testing (off-topic Tagalog questions reaching the chat model at all), so these three layers are now mostly defense-in-depth rather than the primary fix.

## Numeric answers are deterministic, not LLM-written

For a turn where the numeric-intent keywords fire (`_looks_numeric_question`) and a CALCULATIONS preview successfully computes (`_run_preview_calc`), the actual numbers shown to the user never come from the LLM at all:

1. `_numeric_answer_template()` builds a fixed, itemized block (system size, panel count, cost range, savings/payback or battery capacity) straight from `solar_engine.compute()`'s output — plain Python string formatting, no model involved.
2. The LLM is asked for **only** 1-2 short, number-free framing sentences (`NUMERIC_MODE_RULES`), at `temperature=0.1`. Its response is deterministically capped to 2 sentences (`_cap_sentences`) — the model doesn't reliably self-limit length even when it correctly omits numbers.
3. A post-generation check (`_numbers_are_grounded`) scans those sentences for any ₱ amount, kWp/kWh figure, percentage, year count, panel count, or wattage that isn't part of what the model was actually given (the CALCULATIONS block plus the already-known `collected` fields — not just a text match, the raw numeric values are compared directly so a correct "100%" isn't wrongly flagged just because the context string spelled it "100"). If anything doesn't match, the framing sentences are discarded entirely (logged as `[SOLAR] numeric answer discarded: ...`, no retry) and the template block is shown alone.

`_llama_recommendations()` (the final quotation write-up) gets the same post-generation check against `result` + `req` + `PANEL_WATTAGE_W` (the panel-wattage prompt hardcodes "400W", which isn't itself a key in `result`). If the check fails, or the LM Studio/Groq call fails outright, `_recommendation_template()` — a deterministic paragraph built the same way — is returned instead, so `ai_explanation` is never empty and never contains an ungrounded figure.

`scripts/rag_eval.py` calls the same `_answer_numeric_turn()` function production uses, not a hand-rolled copy — a prior version of this harness diverged from production prompt construction and produced a misleading eval result (see the git history / PR notes around the Q18 harness fix) that looked like a model failure but was actually a harness gap.

## Groq fallback

`RAG_GROQ_FALLBACK=1` makes both LM-Studio-backed calls — Solara's conversational reply (`solar_chat_msg`) and the final quotation write-up (`_llama_recommendations`) — retry once through Groq if the LM Studio request fails (connection refused, timeout, any other request error). Off by default, so the existing "LM Studio down → show a friendly retry message" behavior is unchanged unless you opt in. A Groq HTTP 429 (rate limit) is caught and turned into a friendly "please try again shortly" message instead of a crash, on both providers-as-primary and providers-as-fallback paths.

## Privacy — what does and doesn't reach Groq

Whenever a call's target is Groq — whether Groq is the configured primary (`TEXT_PROVIDER=groq`) or the automatic fallback above — the system prompt uses a PII-free variant of the conversation's `<context>` block: stored fields like name, address, contact number, email, and notes are left out; only consumption figures, target savings, and already-computed numbers go in. This applies everywhere a Groq call can happen, including the primary-provider case, which previously sent the full context (including name and address) to Groq on every turn — that gap is fixed by this work, not new to it.

**What this does not do:** it does not scrub the user's own typed chat message. Whatever the user types in a given turn is still sent to Groq as-is when Groq is the active provider — the reply has to actually respond to what was asked. If a user types personal information directly into the chat box, that text still reaches Groq; the existing system-prompt rule telling Solara not to collect or repeat back sensitive identifiers (passwords, government ID numbers, etc.) is the only mitigation for that case, and this work doesn't change it.

## AMD (ROCm) notes

Chat generation runs through LM Studio's OpenAI-compatible HTTP API — this codebase never touches the GPU directly, so nothing here is GPU-vendor-specific on the Python side. On this project's RX 9060 XT:

- Use LM Studio's **ROCm llama.cpp runtime** for the chat model (confirmed working).
- Confirm GPU offload is actually active in LM Studio's model settings — a model silently running on CPU is what the generous `LM_STUDIO_TIMEOUT` is there to paper over, not something you want by default.
- If ROCm has issues after a driver update, fall back to the **Vulkan runtime** in LM Studio.
- Embeddings (`EMBED_PROVIDER=local_cpu`) run on CPU via fastembed/ONNX by default and don't depend on LM Studio being up at all — retrieval keeps working even if the GPU-backed chat model is down.

## Future enhancements (not built)

- **pgvector-backed ANN retrieval.** `init_db()` best-effort runs `CREATE EXTENSION IF NOT EXISTS vector` and logs whether it succeeded, but the only retrieval path implemented is brute-force cosine similarity over `REAL[]` in Python (via numpy) — fine at this corpus's size. If the knowledge base grows enough to matter, that's the place to add an ANN index.
- **Admin-triggered re-index.** Currently a terminal command only; a `require_admin()`-guarded route wrapping `build_rag_index.py` would be a small, self-contained addition if it's ever worth the extra surface area.
