# Solar RAG Setup

Retrieval-augmented grounding for Solara, the solar PV consultation chatbot (`src/solar_bp.py`). Keeps Solara's answers to actual open-ended solar questions sourced from a hand-edited knowledge base (`knowledge/solar/*.md`) and real computed numbers (`src/solar_engine.py`), instead of the model's own memory. Scoped to that chat only — bill OCR (`VISION_PROVIDER`) and structured field extraction are untouched.

## Env vars

Add these to `.env` (defaults shown are what ships in `.env.example`):

```
EMBED_PROVIDER=local_cpu           # local_cpu (default) | lmstudio
EMBED_MODEL=BAAI/bge-small-en-v1.5 # fastembed model id, or the LM Studio embedding model name if EMBED_PROVIDER=lmstudio
RAG_MIN_SCORE=0.55                 # cosine similarity floor — see the reasoning below
RAG_GROQ_FALLBACK=0                # 1 = retry through Groq once if LM Studio fails
RAG_CACHE_TTL=300                  # seconds to reuse the in-process chunk matrix; 0 = no cache
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

## Cost-effectiveness verdicts are deterministic too — `assess_suitability()`

Same principle as the numeric answers above, applied to "is solar worth it for me" questions (2026-09-24): `assess_suitability()` in `solar_engine.py` decides `not_worth` / `borderline` / `worthwhile` / `not_applicable` / `unknown_type` from the customer's actual monthly consumption — the model never judges this itself, it may only add short framing sentences around whichever verdict Python already reached (`SUITABILITY_MODE_RULES`, same pattern as `NUMERIC_MODE_RULES`).

The 400 kWh/month minimum-consumption guidance is a **household-only** rule — commercial/industrial accounts are exempt from the check entirely, not subject to a different number. 400 kWh is guidance from a professional client in the solar field; 350 kWh (borderline) and 450 kWh (where the "close to the minimum" note stops applying) are the team's own tolerance margins around that number, not from the professional. `solar_chat_msg`, the customer-facing results page, and the admin review view all call this same function fresh against the same two DB columns (`kwh_monthly`, `establishment_type`) — none of them cache or duplicate the verdict, so they can't disagree with each other.

## Groq fallback

`RAG_GROQ_FALLBACK=1` makes both LM-Studio-backed calls — Solara's conversational reply (`solar_chat_msg`) and the final quotation write-up (`_llama_recommendations`) — retry once through Groq if the LM Studio request fails (connection refused, timeout, any other request error). Off by default, so the existing "LM Studio down → show a friendly retry message" behavior is unchanged unless you opt in. A Groq HTTP 429 (rate limit) is caught and turned into a friendly "please try again shortly" message instead of a crash, on both providers-as-primary and providers-as-fallback paths.

## Request cancellation — Stop button and disconnected clients

`_call_lmstudio()` streams (`"stream": true`, `resp.iter_content(chunk_size=64)` with a hardcoded UTF-8 decode — not `resp.iter_lines(decode_unicode=True)`, see the function's docstring for why) instead of making one blocking non-streamed call — not for a token-by-token UI, but so the read loop has a checkpoint between chunks to notice a cancellation and close the connection early. Before this, a refreshed or closed browser tab left the Flask worker (and LM Studio itself) running the full completion with no way to notice nobody was listening, since Flask/gunicorn's sync workers don't observe a client disconnect mid-request and a non-streamed call gives LM Studio no signal either — only killing the whole worker process reliably freed it.

Mechanism: the frontend generates a `request_id` per `/solar/chat/msg` call (`static/solar-chat.js`); `solar_chat_msg` registers a `threading.Event` for it (`_register_request`) just before the LLM-calling dispatch and always clears it in a `finally`. `_call_lmstudio` checks that event between streamed chunks and raises `_RequestCancelled` if it's set, which `_ai_chat` re-raises rather than treating as a normal failure (no Groq fallback on a cancelled request — it should just stop). The Stop button and a `pagehide`/`visibilitychange` page-teardown handler both call `POST /solar/chat/cancel {request_id}`, which sets the event.

**Serving concurrently (2026-09-23):** a cancel POST has to actually reach the server *while* the original request is still being handled, and a single-threaded, single-worker server can't do that — it services one request at a time, full stop, so the cancel POST (or a page-refresh's next request) just queues behind whatever's already running instead of getting a chance to interrupt it. This was caught live: the local dev server ran `app.run(debug=True)` with no `threaded=True`, which meant Stop/refresh couldn't take effect until the blocked LM Studio call finished or timed out on its own — the exact "5-10 tokens still generating," duplicate-request-burst, and post-refresh-error symptoms all traced back to this one thing. Fixed on both paths:
- **Dev:** `src/app.py` now calls `app.run(debug=True, threaded=True)`.
- **Prod:** `Procfile` now runs `gunicorn ... --workers 1 --threads 4 --worker-class gthread` instead of the bare default (implicitly a single-threaded **sync** worker) — gthread lets one worker process handle several requests concurrently on separate threads, so a cancel POST can be serviced while another request is mid-stream.

**Known limitation:** `_active_requests` is a plain in-process `dict` (`solar_bp.py`), guarded by a `threading.Lock`. Threads share process memory, so gthread's multiple threads-per-worker still see the same dict — that's exactly what makes the fix above work, and why `--workers` was deliberately left at `1` rather than raised alongside `--threads`. If `--workers` is ever increased beyond 1, each worker process gets its **own** separate memory space and its own copy of `_active_requests` — a cancel request landing on a different worker than the one handling the original call would silently no-op, since nothing shares this state across processes. Moving to a shared store (Redis, or Postgres via a `cancelled_requests` table with a short TTL sweep) would be the fix if/when more worker processes are ever needed for throughput — not needed at the current scale.

The CSRF token for `/solar/chat/cancel` travels in the JSON body rather than the usual `X-CSRFToken` header, because `navigator.sendBeacon()` (used for the page-teardown case — a plain `fetch()` in `beforeunload`/`pagehide` is frequently killed mid-flight by the browser before it sends) can't set custom headers. The view is `csrf.exempt()`-ed from Flask-WTF's automatic header/form-only check for that reason and validates the body-carried token manually via `validate_csrf()` — it's a relocation of where the token travels, not a skip of validation, unlike the 3 exemptions in `app.py` for callers that can't present a token at all (PayMongo webhook, face-match/upload-validation APIs).

Scope: this only covers the LM Studio path used by the live chat-reply branches in `solar_chat_msg` (`_answer_general_turn`, `_answer_numeric_turn`, and the plain field-answer branch). Groq's call is short and non-streamed with its own tight 30s timeout, so it wasn't the call this was built for. `_llama_recommendations()` (the one-shot final quotation write-up, triggered once when the consultation completes rather than per-turn) isn't wired into cancellation either — a much rarer, shorter-lived call than the "prompt keeps processing while the user idles or refreshes mid-conversation" scenario this was built to fix.

### Request cancellation — verified behaviour (2026-09-23)

Confirmed end-to-end against a live LM Studio server, not just assumed from reading the code — a matched log pair from the same Stop click:

- **Flask:** `chunk #77` at `23:54:27.106` with `cancel_event.is_set()=True`, then `closing connection (cancelled=True, at_chunk=77, total_chunks_read=77)` at `23:54:27.107`.
- **LM Studio**, the same second: `"Client disconnected. Stopping generation..."`, then `cancel task, id_task = 2886` and the slot was released. The task was killed, not run to completion.

Earlier in this investigation, several "Stop didn't work" reports turned out to be Stop landing during the extract+gate phase (non-streaming, ~1.5–3s per call, before any LM Studio streaming connection even opens) rather than during actual generation — those always ran to completion because there was nothing streaming yet to close. That phase now runs concurrently instead of sequentially (see `_gate_future` in `solar_chat_msg`), which both shortens it and gives a genuine streaming window to test Stop against sooner. The clear marker for "cancelling now actually does something" is the `streaming started for <request_id>` log line in `_call_lmstudio` — a Stop click has to land after that line to hit the mechanism this section describes.

**Caveat:** if LM Studio is still processing the *prompt* (prompt eval — the 0%→100% progress logged before generation/streaming begins) when the disconnect arrives, it finishes that phase first before noticing the client is gone; cancellation only interrupts promptly once token generation (streaming) has actually started. For a short chat turn this phase is usually well under a second, but a long conversation history or a large retrieved-context block can stretch it.

## Privacy — what does and doesn't reach Groq

Whenever a call's target is Groq — whether Groq is the configured primary (`TEXT_PROVIDER=groq`) or the automatic fallback above — the system prompt uses a PII-free variant of the conversation's `<context>` block: stored fields like name, address, contact number, email, and notes are left out; only consumption figures, target savings, and already-computed numbers go in. This applies everywhere a Groq call can happen, including the primary-provider case, which previously sent the full context (including name and address) to Groq on every turn — that gap is fixed by this work, not new to it.

**What this does not do:** it does not scrub the user's own typed chat message. Whatever the user types in a given turn is still sent to Groq as-is when Groq is the active provider — the reply has to actually respond to what was asked. If a user types personal information directly into the chat box, that text still reaches Groq; the existing system-prompt rule telling Solara not to collect or repeat back sensitive identifiers (passwords, government ID numbers, etc.) is the only mitigation for that case, and this work doesn't change it.

## AMD (ROCm) notes

Chat generation runs through LM Studio's OpenAI-compatible HTTP API — this codebase never touches the GPU directly, so nothing here is GPU-vendor-specific on the Python side. On this project's RX 9060 XT:

- Use LM Studio's **ROCm llama.cpp runtime** for the chat model (confirmed working).
- Confirm GPU offload is actually active in LM Studio's model settings — a model silently running on CPU is what the generous `LM_STUDIO_TIMEOUT` is there to paper over, not something you want by default.
- If ROCm has issues after a driver update, fall back to the **Vulkan runtime** in LM Studio.
- Embeddings (`EMBED_PROVIDER=local_cpu`) run on CPU via fastembed/ONNX by default and don't depend on LM Studio being up at all — retrieval keeps working even if the GPU-backed chat model is down.
## `RAG_CACHE_TTL` — why retrieval caches the chunk matrix

Profiled on the 68-chunk corpus (2026-10-14), one `retrieve()` call cost ~62ms, spent almost entirely on work that had nothing to do with similarity:

| Step | Time |
|---|---|
| `get_db()` — open + close a fresh psycopg2 connection | 33.3ms |
| Query `rag_chunks` + parse 68 × 384 `REAL[]` into Python | ~15ms |
| Embed the query (fastembed CPU, warm) | 4.5ms |
| Normalize 68 vectors (per-row Python loop) | 1.0ms |
| **The actual cosine ranking** | **0.003ms** |

`_retrieve_multi()` in `solar_bp.py` calls `retrieve()` once per sub-question, so a 3-question message paid it three times — ~194ms refetching rows that cannot have changed between fragments.

`retriever.py` now caches the fetched chunks plus a row-normalized `(n, 384)` float32 matrix per visibility tuple, behind a lock so a cold cache under concurrent requests costs one fetch rather than one per thread. Ranking is a single `matrix @ q_vec`. Measured after: **5.3ms** for one question, **16.2ms** for three.

Two things the cache deliberately does *not* do:

- **It doesn't cache an empty result.** An empty `rag_chunks` almost always means the index hasn't been built yet, and pinning that for a full TTL would outlast the `build_rag_index.py` run that fixes it.
- **It doesn't detect a re-index.** `build_rag_index.py` is a separate process, so a running app keeps serving the old vectors until the TTL lapses. Checking for freshness would need the same connection the cache exists to avoid. Restart the app, wait out the TTL, or set `RAG_CACHE_TTL=0` while hand-checking an index you're actively rebuilding.

Keyed by visibility tuple because an admin/employee session ranks over a strictly larger candidate set than the public chat, and the two must not share a matrix.

Ranking order and scores are unchanged — verified identical to the pre-cache implementation across 20 query/role pairs (in-KB, off-topic, Taglish, both roles). The `argsort` is `kind="stable"` so score ties keep row order the way the previous `list.sort()` did, and `RAG_MIN_SCORE` is still applied *after* the top-k slice, not before it.

## Hands-on testing — `scripts/solar_chat_devapp.py`

`rag_eval.py` runs a fixed question set and prints a report. When you need to *talk* to Solara and see why a particular reply came out the way it did, this serves the real app on a second port with a debug page:

```powershell
cd src; ..\venv\Scripts\python.exe ..\scripts\solar_chat_devapp.py                  # provider from .env
cd src; ..\venv\Scripts\python.exe ..\scripts\solar_chat_devapp.py --provider groq   # override for this run
```

Then open `http://127.0.0.1:5001/dev/chat` — the real `solar_chat.html` in an iframe on the left, a live trace of each turn on the right.

It imports `app` from `app.py`, so `/solar/chat/msg` **is** the production route, not a reimplementation. Tracing is monkeypatched onto `solar_bp` from that process only (the same technique `rag_eval.py` uses to force `TEXT_PROVIDER`), and no production module imports the harness — so there is no dev-only branch living inside a shipped route. It calls `require_local_db()`, because the route it drives writes a `solar_requests` row once a conversation has every required field.

**The thing it shows that the shipped UI structurally cannot.** The chat response carries no source information at all — the Sources line was removed from the chatbot, along with `_top_source_titles()` and its display cutoff. Retrieval is therefore completely invisible in the real UI by design, and this panel is the only place to see it: every chunk above `RAG_MIN_SCORE`, with its score, source file and topic. When an answer looks like it came from nowhere, this is where you find out whether it did.

Also surfaced per turn: gate outcome (`on_topic` / `off_topic` / `on_topic_zero_sources`), whether the LLM topic gate ran at all or `_has_topic_keyword` short-circuited it, what the AI extractor banked, the `_run_preview_calc` result, per-step timings, and the exact system prompt — expandable, as sent.

One instrumentation limit worth knowing: only `_ai_extract` is traced. When it returns `ok=false` the route falls back to the regex extractor, whose result appears under **collected so far** but not under **ai extraction** — the panel labels this rather than letting an empty extraction read as "nothing was banked."

## Where a turn's latency actually goes

Measured with `scripts/solar_latency_check.py` on 2026-10-14, median ms per stage, after warm-up. Groq = `openai/gpt-oss-120b`; LM Studio = `qwen/qwen3-vl-4b` on the local GPU.

**Groq** (`--provider groq -n 3 --delay 3`) — small sample, this account rate-limits hard:

| turn type | extract | gate(llm) | retrieve | chat | TOTAL | chars |
|---|--:|--:|--:|--:|--:|--:|
| question, keyword hit | 394 | — | 6 | 1940 | **2341** | 436 |
| off-topic (canned, no chat call) | 506 | 485 | 6 | — | **515** | 96 |
| field answer | 424 | — | — | — | **1753** | 352 |
| numeric question | 472 | 515 | 7 | 454 | **980** | 422 |

**LM Studio** (`--provider lmstudio -n 3`), same cases:

| turn type | extract | gate(llm) | retrieve | chat | TOTAL | chars |
|---|--:|--:|--:|--:|--:|--:|
| question, keyword hit | 3634 | — | 7 | 4978 | **8649** | 846 |
| question, no keyword | 3688 | 2527 | 9 | 6812 | **10487** | 1056 |
| off-topic (canned, no chat call) | 3670 | 2553 | — | — | **3671** | 132 |
| field answer | 3594 | — | — | — | **6842** | 289 |
| numeric question | 3515 | 2520 | 8 | 4985 | **8508** | 482 |

So a real reply was roughly **2–2.3s on Groq vs 8.5–10.5s locally** — about 4x, on a 4B model.

**Both tables predate the two fixes below.** With `127.0.0.1` and `required: []` in place, the same local turn measures **3689ms** (extract 280ms, retrieve 8ms, chat 3398ms) — 2.3x faster than the 8649ms baseline, and the attribution adds up: ~4.1s from the connection fix (2 calls x ~2.05s) plus ~1.3s from the schema fix. Re-run the benchmark for current numbers rather than trusting these.

What the breakdown settles:

- **Two sequential LLM calls are ~95% of a turn** — `_ai_extract` then the chat call. Everything else is noise.
- **The speculative gate already works.** LM Studio pays a 2527ms gate call but the no-keyword row costs only ~1.8s more than keyword-hit, and most of that is its longer reply. The `ThreadPoolExecutor` fired before extraction is hiding nearly all of the gate. Don't "optimize" it; it's done.
- **Retrieval is 6–9ms on both.** Provider-independent, as expected — it never touches the chat model. See `RAG_CACHE_TTL` above.
- **Off-topic is the floor** (515ms / 3.7s), because the gate catches it and the chat call never happens.

### `required: []` on the extraction schema

LM Studio's `json_schema` response format applies a GBNF grammar. Listing every field in `required` forces the model to emit all 11 keys even when the message answers none of them — and "none of them" is the common case, because most turns are questions.

Observed in the LM Studio server log for "does more solar panels mean more harvest and is it better?":

```
completion_tokens: 87      eval time = 1486.81 ms / 87 tokens (17.29 ms per token)
content: {"name": null, "address": null, "notes": null, "establishment_type": null, ...}
```

**87 tokens, ~1.5s, to say "nothing" — on every single turn.** Same request with `"required": []`:

| schema | time | completion tokens |
|---|--:|--:|
| `strict`, all 11 required | 1568 ms | 87 |
| `strict`, `required: []` | **388 ms** | **17** |

The parser was already compatible: `_ai_extract` iterates `data.items()` and `continue`s on `None`/`""`, so an absent key and a null key are indistinguishable to it. Nothing downstream changed.

It is also the better answer for *correctness*, not just speed. A model forced to produce a key it has no value for is a model under pressure to invent one — which is precisely the padding the `_NULLISH` set below it exists to scrub ("the string 'null', and words lifted out of the schema itself"). Relaxing `required` removes the pressure rather than cleaning up after it.

Accuracy re-checked across 8 extraction cases (name, address, bill, kWh, roof, both enums, and a mixed field-plus-question message): **8/8 banked everything expected**, mean 347ms vs ~1550ms.

Does not apply to `_is_on_topic` — its single `on_topic` boolean genuinely is required, and it only costs 7 tokens.

### Use `127.0.0.1`, never `localhost`, for LM Studio

Measured 2026-10-14. Identical request, same server, same model:

| URL | per-call floor |
|---|--:|
| `http://localhost:1234` | **2046 ms** |
| `http://127.0.0.1:1234` | **3.2 ms** |

`GET /v1/models` — an endpoint that runs no inference at all — took 2039ms via `localhost`. The cost is fixed: a 9-token prompt cost the same as a 434-token one, so it is not prefill and not generation.

Cause: on Windows `localhost` resolves to IPv6 `::1` **before** IPv4 (`socket.getaddrinfo` returns `AF_INET6` first). LM Studio binds IPv4 only, so every single request opens a connection to `::1`, waits for it to fail, and retries on `127.0.0.1`. That retry is the ~2s.

A Solara turn makes 2–3 LM Studio calls (extract, topic gate, chat), so this was costing **~4–6 seconds per reply** while looking exactly like "the local model is slow." The `LM_STUDIO_URL` default in all five modules that read it is now `http://127.0.0.1:1234`, and `.env.example` carries the warning. If you ever point `LM_STUDIO_URL` at a remote GPU box, use its IP for the same reason — or verify the hostname resolves to IPv4 first.

### Watch for model thrashing when benchmarking

LM Studio JIT-loads a model on first request and evicts others under VRAM pressure. Calling two models alternately (easy to do when comparing `LM_STUDIO_MODEL` against `LM_STUDIO_TEXT_MODEL`) makes it swap on *every* request: observed extraction going from 3.6s to 24s, and generation throughput dropping from ~68 to ~12 tok/s across both models.

Check residency before trusting any measurement:

```powershell
curl http://127.0.0.1:1234/api/v0/models    # look at each model's "state"
```

Exactly one model should read `loaded` — the one `LM_STUDIO_TEXT_MODEL` names. If throughput stays low after the other is evicted, restart LM Studio; generation rate does not always recover on its own.

### Benchmarking pitfall: a refused call times fast

The first version of this script fired runs back to back, tripped Groq's rate limit, and reported a **468ms** "chat" stage — which was `_RATE_LIMITED_MSG` (exactly 73 characters) coming back from a refused request, not a reply. It made Groq look 4x faster than it is, and the harder the script hammered, the better the provider scored.

`solar_latency_check.py` now classifies every run and discards `rate_limited` / `[ERROR:` turns from the timing stats rather than averaging them in, printing how many it threw away. **If the `chars` column looks implausibly small for the turn type, distrust the row** — that column exists as the tell. Raise `--delay` when runs get discarded.

### The one large lever: extraction

`needs_judgement` skips `_ai_extract` once `name` *and* `address` are banked, which is measurable — same question, same provider, 826ms with extraction vs **424ms** with it skipped. That only helps late in a conversation; every turn before those two fields land pays full price. On LM Studio it is ~3.6s of every single turn.

It cannot simply be skipped earlier. The chat prompt's "Already shared / Still need to gather" block is built from `collected`, so running chat before extraction makes Solara re-ask for something the user just gave — the exact failure the `rag_eval.py` harness-gap comment describes. The dependency is real.

What's available, in order of value:

1. **A smaller model for extraction only.** Field-picking is not the same job as writing a reply, and the codebase already splits providers for exactly this reason (`TEXT_PROVIDER` vs `VISION_PROVIDER`). An `EXTRACT_MODEL` knob pointed at something small would cut ~3.6s locally, ~0.4s on Groq, from *every* turn. Needs an accuracy check against `rag_eval.py` first.
2. **Stream the chat reply.** Doesn't reduce total time, cuts time-to-first-token to near zero — which matters far more at 8.5s than at 2s. `_call_lmstudio` already streams internally; the route buffers the whole reply before responding. Needs SSE plus a frontend change.
3. ~~Pre-warm the embedder~~ — **done.** `rag.embeddings.warm()` is called from `app.py` after `init_db()`. The fastembed/ONNX load is ~1.5s and paid per process, so the first person to hit Solara after a gunicorn worker started used to wait it out. First `retrieve()` after boot is now 69ms instead of ~1500ms.

Parallelizing retrieval with extraction is not worth doing — it would save 7ms.

### Check `LM_STUDIO_TEXT_MODEL`

As measured, `LM_STUDIO_TEXT_MODEL=qwen/qwen3-vl-4b` — the **vision** model was answering chat, while `qwen/qwen3-8b` sat loaded and unused. That is the exact mix-up the comment above `LM_STUDIO_TEXT_MODEL` in `solar_bp.py` warns about ("the text side needs its own model name"). A VL model will answer text, so nothing looks broken; it is just not the model you meant to ship. Note the 8B would likely be *slower* than the 4B — this is a quality decision, not a speed one.

## Future enhancements (not built)

- **pgvector-backed ANN retrieval.** `init_db()` best-effort runs `CREATE EXTENSION IF NOT EXISTS vector` and logs whether it succeeded, but the only retrieval path implemented is brute-force cosine similarity over `REAL[]` in Python (via numpy) — fine at this corpus's size. If the knowledge base grows enough to matter, that's the place to add an ANN index.
- **Admin-triggered re-index.** Currently a terminal command only; a `require_admin()`-guarded route wrapping `build_rag_index.py` would be a small, self-contained addition if it's ever worth the extra surface area.
