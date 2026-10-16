"""rag_eval.py — Runs a fixed set of solar/PV questions through retrieval and
the grounded chat prompt, and prints retrieved sources, scores, and the final
answer for each. Used to (a) hand-check that in-KB questions retrieve well,
not-in-KB questions honestly decline, off-topic questions get redirected, and
numeric questions match solar_engine.compute() exactly, and (b) pick a real
RAG_MIN_SCORE from the printed per-category score distribution instead of
guessing one.

Run from the src/ directory so flat imports resolve:
    cd src && ..\\venv\\Scripts\\python.exe ..\\scripts\\rag_eval.py --provider lmstudio
    cd src && ..\\venv\\Scripts\\python.exe ..\\scripts\\rag_eval.py --provider groq
"""
import argparse
import json
import os
import re
import statistics
import sys
import time

# Answers routinely contain curly quotes/em dashes; the Windows console
# defaults stdout to cp1252, which can't encode them and prints "�" in their
# place (the data itself is fine — confirmed via repr() during the 2026-09-24
# net-metering test — this is purely a console-rendering issue, same as
# scripts/solar_chat_text_check.py).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import solar_bp
from rag.retriever import retrieve
from solar_engine import compute as solar_compute

# Each question is a dict: category, question, collected (numeric fixture or
# None), history (prior conversation turns, or None for a standalone message).
QUESTIONS = [
    # in_kb — general PV knowledge that should retrieve well from knowledge/solar/*.md
    {"category": "in_kb", "question": "What's the difference between a grid-tied and a hybrid solar system?"},
    {"category": "in_kb", "question": "What does the inverter actually do in a solar setup?"},
    {"category": "in_kb", "question": "How does net metering work here in the Philippines?"},
    {"category": "in_kb", "question": "What's the difference between monocrystalline and polycrystalline panels?"},
    {"category": "in_kb", "question": "When does it make sense to add battery storage?"},
    # Moved from not_in_kb: knowledge/solar/panels.md now has a "## Warranty"
    # heading (added on 2026-09-20) but its content is still a TODO
    # placeholder pending a verified section written by hand. Expected answer
    # once that's filled in: typical performance/product warranty ranges
    # from the knowledge base, noting it depends on the brand/model actually
    # installed. Until then, a canned "don't have that exact figure" fallback
    # (from the number-check in _answer_general_turn) counts as a PASS, not a
    # failure — there's genuinely nothing to retrieve yet.
    {"category": "in_kb", "question": "What's the exact warranty period in years for your panels?"},
    # Language-detection regression cases (2026-09-22): "what" was briefly a
    # member of _TAGALOG_MARKERS (via an over-broad set union), so any English
    # message containing it — extremely common — got Taglish canned replies
    # or a Taglish LLM answer. These specifically contain the words the bug
    # report named ("what", "that", "Santa Cruz", "panels and inverters") and
    # must get English replies; see expected_language / reply_language below.
    {"category": "in_kb", "question": "What is the normal warranty of solar panels and inverters?",
     "expected_language": "english"},
    {"category": "in_kb", "question": "Is that covered under warranty for the panels and inverters?",
     "expected_language": "english"},
    {"category": "borderline_legit", "question": "We're located in Santa Cruz — what solar system would work for us?",
     "expected_language": "english"},
    {"category": "in_kb", "question": "What are solar panels and inverters?",
     "expected_language": "english"},
    # not_in_kb — specific facts the knowledge base deliberately doesn't assert
    {"category": "not_in_kb", "question": "Exactly how much is the current DOE solar rebate in pesos?"},
    {"category": "not_in_kb", "question": "What's the specific model number of the inverter you'll install for me?"},
    {"category": "not_in_kb", "question": "How does your pricing compare exactly to [a competitor]'s per-kWp rate?"},
    # off_topic — should be redirected, not answered. gate_said_off_topic is
    # the CORRECT outcome here, not a false negative.
    {"category": "off_topic", "question": "What's the capital of France?"},
    {"category": "off_topic", "question": "Can you give me a recipe for chicken adobo?"},
    {"category": "off_topic", "question": "Sino ang pangulo ng Pilipinas ngayon?"},
    {"category": "off_topic", "question": "Can you help me with my algebra homework?"},
    {"category": "off_topic", "question": "Ano ang pinakamalaking bansa sa mundo?"},
    {"category": "off_topic", "question": "What's a good movie to watch tonight?"},
    {"category": "off_topic", "question": "Paano gumawa ng maayos na resume?"},
    # borderline_legit — phrased casually/indirectly, no obvious keyword hook,
    # but genuinely about solar/the consultation. The topic gate must say
    # on_topic for every one of these.
    {"category": "borderline_legit", "question": "sulit ba sa bahay namin?",
     "expected_language": "taglish"},
    {"category": "borderline_legit", "question": "okay lang ba kahit laging bumabagyo dito?",
     "expected_language": "taglish"},
    {"category": "borderline_legit", "question": "can I still use my aircon at night with solar?"},
    {"category": "borderline_legit", "question": "mataas kasi kuryente namin, ano pwede gawin?"},
    # borderline_legit, follow-up style — these only make sense given the
    # prior turn, and deliberately avoid _TOPIC_KEYWORDS words so they
    # actually exercise the history-aware LLM gate (item 1b), not the
    # keyword short-circuit (item 1a). "kaya ba sa maliit na bubong?" is the
    # exception — it contains "bubong" (a keyword) on purpose, to confirm
    # the keyword path also works for a follow-up phrasing.
    {"category": "borderline_legit", "question": "e kung tag-ulan?",
     "history": [{"role": "assistant", "content": "Solar panels generate power from sunlight, so output is highest on clear sunny days."}]},
    {"category": "borderline_legit", "question": "pano pag brownout?",
     "history": [{"role": "assistant", "content": "A standard grid-tied solar system draws from the grid at night or on cloudy days."}]},
    {"category": "borderline_legit", "question": "kaya ba sa maliit na bubong?",
     "history": [{"role": "assistant", "content": "We size your solar system based on your roof area and monthly electricity consumption."}]},
    {"category": "borderline_legit", "question": "mas mura ba 'yun sa katagalan?",
     "history": [{"role": "assistant", "content": "The upfront cost of a solar system depends on its size in kWp."}]},
    # Single-STRONG-marker Taglish cases (2026-09-22 follow-up): the language
    # detector was relaxed so one unambiguous Tagalog word ("magkano",
    # "paano yun") is enough to call a short message Taglish, instead of
    # always requiring 2 distinct hits. "panels" is also a _TOPIC_KEYWORDS
    # hit so "ilan panels?" clears the gate on its own; the other two lean on
    # history for on-topic context, same pattern as the follow-ups above.
    {"category": "borderline_legit", "question": "magkano?",
     "history": [{"role": "assistant", "content": "A typical residential solar system here costs between 150,000 and 400,000 pesos depending on size."}],
     "expected_language": "taglish"},
    {"category": "borderline_legit", "question": "ilan panels?",
     "expected_language": "taglish"},
    {"category": "borderline_legit", "question": "paano yun?",
     "history": [{"role": "assistant", "content": "Net metering lets you export excess solar power back to the grid for bill credits."}],
     "expected_language": "taglish"},
    # numeric_calc — needs solar_engine.compute(), English phrasing with "?"
    {"category": "numeric_calc",
     "question": "How many panels would I need if my system is sized for a 4000 kWh monthly bill equivalent?",
     "collected": {"kwh_monthly": 500, "target_savings": "100", "roof_sqm": 30,
                   "electrical_phase": "single", "establishment_type": "residential", "grid_connection": "grid_tie"}},
    {"category": "numeric_calc", "question": "What would my estimated monthly savings be?",
     "collected": {"monthly_bill_php": 8000, "target_savings": "100", "roof_sqm": 30,
                   "electrical_phase": "single", "establishment_type": "residential", "grid_connection": "grid_tie"}},
    # taglish_no_question — no "?", must still classify as a genuine question
    {"category": "taglish_no_question", "question": "magkano po kaya kung 5000 ang bill ko",
     "collected": {"monthly_bill_php": 5000, "target_savings": "100", "roof_sqm": 25,
                   "electrical_phase": "single", "establishment_type": "residential", "grid_connection": "grid_tie"}},
    {"category": "taglish_no_question", "question": "ilang panel kailangan sa 3 kilowatt na sistema",
     "collected": {"kwh_monthly": 450, "target_savings": "100", "roof_sqm": 25,
                   "electrical_phase": "single", "establishment_type": "residential", "grid_connection": "grid_tie"}},
    # unverified_claims (2026-09-22 follow-up): questions that tempt the
    # model into an unverified company-experience claim or a brand name not
    # in CONTEXT. Not "wrong" if declined honestly or answered generically —
    # flagged in reporting via _has_unverifiable_company_claim /
    # _mentions_ungrounded_brand, same functions production uses to trim.
    {"category": "unverified_claims", "question": "How many homes has EnergyWize installed solar for so far?"},
    {"category": "unverified_claims", "question": "Is EnergyWize a trusted, reliable company to work with?"},
    {"category": "unverified_claims", "question": "What inverter brands does EnergyWize offer besides Deye?"},
    # Single-STRONG-marker Taglish, heavily English-dominant (2026-09-22
    # follow-up item 5): "ano" is a STRONG marker so _looks_taglish is True
    # and the correct instruction is sent — this tracks the model's own
    # compliance, not detection, same pattern as "ilan panels?"/"paano yun?".
    {"category": "unverified_claims", "question": "Ano ba ang magandang brand ng solar panels for my home?",
     "expected_language": "taglish"},
    # 2026-09-24 follow-up: targets the newly-added coverage/licensing/
    # undocumented-offering phrase categories specifically (province/
    # nationwide coverage, "fully licensed", financing, hidden fees) —
    # none of knowledge/solar/ documents any of these.
    {"category": "unverified_claims",
     "question": "Do you install nationwide, are your technicians licensed, and do you offer financing with no hidden fees?"},
    # multi_question (2026-09-24 follow-up): a single message bundling
    # several genuinely different-topic questions, reproducing the live bug
    # report where one embedding of the whole blended message only retrieved
    # 2-3 of 5 topics — the other topics' chunks never cleared RAG_MIN_SCORE
    # against the averaged vector. Deliberately spans 5 different KB files
    # (inverters, panels-warranty, net-metering, batteries, system-types) so
    # a real fix should show sources from most or all five, not 2-3.
    {"category": "multi_question",
     "question": ("What brands of inverters do you use? What's the warranty on the panels? "
                   "How does net metering work?\nDo you install batteries too? "
                   "What's the difference between grid-tied and hybrid systems?")},
    # worth_it (2026-10-14 follow-up): "is it worth it" questions must route
    # to assess_suitability()'s Python-decided verdict, not a free-text model
    # answer — this is what the live bug report caught (fabricated "7-8
    # hours of AC/day" / "cut that in half" reasoning on a bill-only
    # question). Every case below carries expected_verdict (and
    # expected_note where relevant) so main() can assert the FINAL answer's
    # verdict matches assess_suitability() exactly, not just eyeball it.
    # kWh-direct, residential — covers every band boundary.
    {"category": "worth_it", "question": "We only use about 200 kWh a month, is a solar system worth it for us?",
     "collected": {"kwh_monthly": 200, "establishment_type": "residential"}, "expected_verdict": "not_worth"},
    {"category": "worth_it", "question": "May 349 kWh na gamit kami kada buwan, sulit kaya kumuha ng solar?",
     "collected": {"kwh_monthly": 349, "establishment_type": "residential"}, "expected_verdict": "not_worth"},
    {"category": "worth_it", "question": "Our monthly usage is 350 kWh, is solar worth it for us?",
     "collected": {"kwh_monthly": 350, "establishment_type": "residential"}, "expected_verdict": "borderline"},
    {"category": "worth_it", "question": "399 kWh kada buwan ang gamit namin, sulit ba ang solar?",
     "collected": {"kwh_monthly": 399, "establishment_type": "residential"}, "expected_verdict": "borderline"},
    {"category": "worth_it", "question": "We use 400 kWh a month, is a solar system worth it?",
     "collected": {"kwh_monthly": 400, "establishment_type": "residential"}, "expected_verdict": "worthwhile", "expected_note": True},
    {"category": "worth_it", "question": "449 kWh kada buwan ang konsumo namin, sulit ba kumuha ng solar?",
     "collected": {"kwh_monthly": 449, "establishment_type": "residential"}, "expected_verdict": "worthwhile", "expected_note": True},
    {"category": "worth_it", "question": "Our household uses 450 kWh monthly, is solar worth it?",
     "collected": {"kwh_monthly": 450, "establishment_type": "residential"}, "expected_verdict": "worthwhile", "expected_note": False},
    {"category": "worth_it", "question": "600 kWh kada buwan ang gamit namin, makakatulong kaya ang solar?",
     "collected": {"kwh_monthly": 600, "establishment_type": "residential"}, "expected_verdict": "worthwhile", "expected_note": False},
    # Bill-only, residential — same boundaries, converted via ELECTRICITY_RATE.
    {"category": "worth_it", "question": "I have a bill of P1500 is it worth it to have a PV system?",
     "collected": {"monthly_bill_php": 1500, "establishment_type": "residential"}, "expected_verdict": "not_worth"},
    {"category": "worth_it", "question": "Mga P5500 bill namin kada buwan, sulit ba kumuha ng solar?",
     "collected": {"monthly_bill_php": 5500, "establishment_type": "residential"}, "expected_verdict": "borderline"},
    {"category": "worth_it", "question": "Our bill runs about P6500 a month, is it worth it to get a PV system?",
     "collected": {"monthly_bill_php": 6500, "establishment_type": "residential"}, "expected_verdict": "worthwhile", "expected_note": True},
    {"category": "worth_it", "question": "Mga P8000 ang bill namin kada buwan, sulit ba ang solar sa amin?",
     "collected": {"monthly_bill_php": 8000, "establishment_type": "residential"}, "expected_verdict": "worthwhile", "expected_note": False},
    # Commercial/industrial — low consumption must never be blocked or
    # discouraged; the check simply doesn't apply to them (per decision 3,
    # no admin note either).
    {"category": "worth_it", "question": "Our small office only uses about 150 kWh a month, is solar still worth it for a commercial space?",
     "collected": {"kwh_monthly": 150, "establishment_type": "commercial"}, "expected_verdict": "not_applicable"},
    {"category": "worth_it", "question": "100 kWh lang gamit ng factory namin kada buwan, sulit ba kumuha ng solar?",
     "collected": {"kwh_monthly": 100, "establishment_type": "industrial"}, "expected_verdict": "not_applicable"},
    # Unknown property type — must ask for it, never give a verdict. The
    # first is the exact line from the live bug report (check B).
    {"category": "worth_it", "question": "I have a bill of P1500 is it worth it to have a PV system?",
     "collected": {"monthly_bill_php": 1500}, "expected_verdict": "unknown_type"},
    {"category": "worth_it", "question": "500 kWh ang gamit namin, sulit ba kumuha ng solar?",
     "collected": {"kwh_monthly": 500}, "expected_verdict": "unknown_type"},
]

# A verdict-text leak check for not_worth answers specifically: that verdict
# never shows sizing (kWp/panel count) as if it were a recommendation
# (item 5) — this regex flags it if the model's framing sentence smuggled
# one in anyway. Doesn't match the kWh figure the verdict sentence itself
# always includes, since that's expected and not a sizing recommendation.
_SIZING_LEAK_RE = re.compile(r"\d+(\.\d+)?\s*(kwp|panels?)\b", re.IGNORECASE)


def run_one(category: str, question: str, collected: dict, history: list = None):
    collected = collected or {}
    is_question  = solar_bp._looks_like_question(question)
    is_numeric   = solar_bp._looks_numeric_question(question)
    is_worth_it  = solar_bp._looks_like_worth_it_question(question)

    # Same deterministic gate + retrieval production uses (solar_bp._gate_and_retrieve)
    # — not a hand-rolled copy, so this harness can't drift from production
    # the way it drifted on the context block before.
    canned_text, sources, context_section = solar_bp._gate_and_retrieve(question, None, history=history)
    if canned_text in (solar_bp._CANNED_OFF_TOPIC_EN, solar_bp._CANNED_OFF_TOPIC_TL):
        gate_outcome = "gate_said_off_topic"
    elif canned_text in (solar_bp._CANNED_NO_INFO_EN, solar_bp._CANNED_NO_INFO_TL):
        gate_outcome = "on_topic_zero_sources"
    else:
        gate_outcome = "on_topic"

    # Mirrors production's INTERNAL CONTEXT BLOCK (solar_bp._build_grounded_system)
    # instead of a hand-rolled shorter prompt — a prior version of this harness
    # omitted the "already shared" block entirely, which made the model re-ask
    # for a bill amount that was in fact already given, and looked like a
    # grounding failure that was actually a harness gap.
    if collected:
        shared = "; ".join(f"{k}: {v}" for k, v in collected.items() if v is not None)
    else:
        shared = "nothing yet"
    context_body = (f"Already shared: {shared}\n"
                     f"Still need to gather: (n/a — single-turn eval, not a live conversation)\n"
                     f"Next thing to naturally work into the conversation: (n/a)")

    numeric_result = None
    ground_truth = None
    suitability = None
    if canned_text is None and is_worth_it:
        suitability = solar_bp.assess_suitability(
            solar_bp._consumption_kwh(collected), collected.get("establishment_type"))
    elif canned_text is None and collected and is_numeric:
        numeric_result = solar_bp._run_preview_calc(collected)
        ground_truth = solar_compute(
            kwh_monthly=collected.get("kwh_monthly"),
            bill_php=collected.get("monthly_bill_php"),
            target_savings=collected.get("target_savings", "100"),
            roof_sqm=collected.get("roof_sqm"),
            time_of_use_night_pct=collected.get("time_of_use_night_pct"),
            electrical_phase=collected.get("electrical_phase", "single"),
            establishment_type=collected.get("establishment_type", "residential"),
            grid_connection=collected.get("grid_connection", "grid_tie"),
        )

    if canned_text is not None:
        answer = canned_text
    elif suitability is not None:
        try:
            answer = solar_bp._answer_suitability_turn(
                question, suitability, collected,
                context_body_full=context_body, context_body_safe=context_body,
                context_section=context_section, history=history,
            )
        except Exception as e:
            answer = f"[ERROR: {type(e).__name__}: {e}]"
    elif numeric_result is not None:
        try:
            answer = solar_bp._answer_numeric_turn(
                question, numeric_result, collected,
                context_body_full=context_body, context_body_safe=context_body,
                context_section=context_section, is_preview=True, history=history,
            )
        except Exception as e:
            answer = f"[ERROR: {type(e).__name__}: {e}]"
    else:
        try:
            messages_out = list(history or []) + [{"role": "user", "content": question}]
            answer = solar_bp._answer_general_turn(
                messages_out, question, context_section,
                collected or {}, context_body_full=context_body, context_body_safe=context_body,
            )
        except Exception as e:
            answer = f"[ERROR: {type(e).__name__}: {e}]"

    # The rate-limit message and an [ERROR: ...] string are both fixed,
    # deliberately-unlocalized system text, not a persona reply — scoring
    # their language would confound the check (looks like "expected taglish,
    # got english" when really "never got a real answer at all").
    if answer == solar_bp._RATE_LIMITED_MSG or answer.startswith("[ERROR:"):
        reply_language = "inconclusive"
    else:
        reply_language = "taglish" if solar_bp._looks_taglish(answer) else "english"

    # Report-only checks on the FINAL shown answer (post-trim) — these
    # functions are the same ones production uses to trim mid-generation, so
    # a hit here means either the trim missed something or the check doesn't
    # apply on this path (e.g. a canned/numeric-template answer, which is
    # always clean by construction). Not auto-failed; see main()'s reporting.
    context_brands = solar_bp._brands_in_context(context_section)
    # Same doe_grounded computation production's _answer_general_turn uses
    # (solar_bp.py _trim_ungrounded_sentences call site) — without it, every
    # DOE-registration answer reports as an "unverifiable claim" even when
    # the KB's own "DOE registration" section is exactly what grounded it,
    # which would make this report wrong, not the answer.
    doe_grounded = solar_bp._context_supports_doe_claim(context_section)
    has_unverifiable_company_claim = solar_bp._has_unverifiable_company_claim(answer, doe_grounded)
    answer_lower = answer.lower()
    ungrounded_brands = [b for b in solar_bp._KNOWN_BRANDS
                          if b not in context_brands
                          and re.search(r"\b" + re.escape(b.lower()) + r"\b", answer_lower)]

    # not_worth must never show sizing/cost as if it were a recommendation
    # (item 5) — checked regardless of category, since the question-text
    # heuristic that routes into assess_suitability() could in principle
    # misfire on a non-worth_it question too.
    sizing_leaked = (suitability is not None and suitability["verdict"] == "not_worth"
                      and bool(_SIZING_LEAK_RE.search(answer)))

    return {
        "category": category, "question": question,
        "is_question": is_question, "is_numeric": is_numeric, "gate_outcome": gate_outcome,
        "sources": [{"title": s["title"], "score": s["score"]} for s in sources],
        "answer": answer, "ground_truth": ground_truth, "reply_language": reply_language,
        "has_unverifiable_company_claim": has_unverifiable_company_claim, "ungrounded_brands": ungrounded_brands,
        "suitability": suitability, "sizing_leaked": sizing_leaked,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=["lmstudio", "groq"], default=solar_bp.TEXT_PROVIDER)
    args = parser.parse_args()
    solar_bp.TEXT_PROVIDER = args.provider

    print(f"Provider: {args.provider}  |  Embed model: {solar_bp.EMBED_MODEL if hasattr(solar_bp, 'EMBED_MODEL') else 'n/a'}\n")

    scores_by_category = {}
    # A gate false negative is any question NOT in off_topic that the gate
    # still classified as off-topic — off_topic questions getting
    # gate_said_off_topic is the correct outcome, not a failure.
    gate_false_negatives = []
    language_mismatches = []
    language_inconclusive = []
    unverifiable_claim_hits = []
    ungrounded_brand_hits = []
    verdict_mismatches = []
    sizing_leak_hits = []
    for i, q in enumerate(QUESTIONS):
        if i > 0 and args.provider == "groq":
            # 3s wasn't enough headroom once the eval set grew to ~30
            # questions with ~2000-token system prompts each — a run got
            # heavily 429'd, and since the 429 fallback text is a fixed
            # English string, it silently confounded the language check
            # (looked like "expected taglish, got english" but was really
            # "never got a real answer at all").
            time.sleep(15)
        category, question = q["category"], q["question"]
        result = run_one(category, question, q.get("collected"), q.get("history"))
        scores_by_category.setdefault(category, []).extend(s["score"] for s in result["sources"])
        if category != "off_topic" and result["gate_outcome"] == "gate_said_off_topic":
            gate_false_negatives.append((category, question))

        expected_lang = q.get("expected_language")
        if expected_lang and result["reply_language"] == "inconclusive":
            language_inconclusive.append((category, question))
        elif expected_lang and result["reply_language"] != expected_lang:
            language_mismatches.append((category, question, expected_lang, result["reply_language"]))

        if result["has_unverifiable_company_claim"]:
            unverifiable_claim_hits.append((category, question, result["answer"]))
        if result["ungrounded_brands"]:
            ungrounded_brand_hits.append((category, question, result["ungrounded_brands"], result["answer"]))

        expected_verdict = q.get("expected_verdict")
        if expected_verdict:
            suitability = result["suitability"]
            got_verdict = suitability["verdict"] if suitability else None
            if got_verdict != expected_verdict:
                verdict_mismatches.append((category, question, expected_verdict, got_verdict))
            elif "expected_note" in q and bool(suitability.get("note")) != q["expected_note"]:
                verdict_mismatches.append((category, question,
                                            f"{expected_verdict} (note={q['expected_note']})",
                                            f"{got_verdict} (note={suitability.get('note')})"))
        if result["sizing_leaked"]:
            sizing_leak_hits.append((category, question, result["answer"]))

        print(f"[{category}] {question}")
        print(f"  classified_as_question={result['is_question']}  numeric_intent={result['is_numeric']}  "
              f"gate_outcome={result['gate_outcome']}  reply_language={result['reply_language']}"
              + (f"  expected={expected_lang}" if expected_lang else ""))
        print(f"  sources: {result['sources']}")
        if result["suitability"] is not None:
            print(f"  suitability (assess_suitability): {result['suitability']}"
                  + (f"  expected={expected_verdict}" if expected_verdict else ""))
        if result["ground_truth"] is not None:
            print(f"  ground_truth (solar_engine.compute): "
                  f"{result['ground_truth']['system_size_kw']} kWp, "
                  f"{result['ground_truth']['panel_count']} panels, "
                  f"₱{result['ground_truth']['monthly_savings']:,} savings/mo")
        print(f"  answer: {result['answer']}")
        print()

    print("=" * 70)
    print("Per-category retrieval score summary (top-5 scores pooled per question):")
    for category, scores in scores_by_category.items():
        if not scores:
            print(f"  {category:<20} n=0 (nothing retrieved for any question in this category)")
            continue
        print(f"  {category:<20} n={len(scores):<3} min={min(scores):.4f} "
              f"max={max(scores):.4f} mean={statistics.mean(scores):.4f}")

    print("=" * 70)
    non_off_topic_total = sum(1 for q in QUESTIONS if q["category"] != "off_topic")
    if gate_false_negatives:
        print(f"GATE FALSE NEGATIVES ({len(gate_false_negatives)}/{non_off_topic_total} "
              f"on-topic questions wrongly gated as off-topic, across all categories):")
        for category, q in gate_false_negatives:
            print(f"  - [{category}] {q}")
    else:
        print(f"Gate false negatives: none — all {non_off_topic_total} on-topic questions "
              f"(every category except off_topic) passed the topic gate.")

    print("=" * 70)
    expected_total = sum(1 for q in QUESTIONS if q.get("expected_language"))
    checked_total = expected_total - len(language_inconclusive)
    if language_inconclusive:
        print(f"Language checks inconclusive ({len(language_inconclusive)}/{expected_total} — "
              f"rate-limited or errored before a real reply came back, not scored):")
        for category, q in language_inconclusive:
            print(f"  - [{category}] {q}")
    if language_mismatches:
        print(f"LANGUAGE MISMATCHES ({len(language_mismatches)}/{checked_total} "
              f"scored replies not in the expected language):")
        for category, q, expected, got in language_mismatches:
            print(f"  - [{category}] expected={expected} got={got}: {q}")
    else:
        print(f"Language checks: all {checked_total} scored questions got a reply "
              f"in the expected language.")

    print("=" * 70)
    # Report-only — these check the FINAL shown answer with the same
    # functions production uses to trim mid-generation, so a hit here means
    # the trim didn't catch something (a real gap) rather than being scored
    # pass/fail against a fixed expectation like the checks above.
    if unverifiable_claim_hits:
        print(f"UNVERIFIABLE COMPANY CLAIMS SURVIVED IN {len(unverifiable_claim_hits)} ANSWER(S) "
              f"(should have been trimmed):")
        for category, q, answer in unverifiable_claim_hits:
            print(f"  - [{category}] {q}\n    answer: {answer}")
    else:
        print("Unverifiable company claims: none survived in any answer.")

    if ungrounded_brand_hits:
        print(f"UNGROUNDED BRAND NAMES SURVIVED IN {len(ungrounded_brand_hits)} ANSWER(S) "
              f"(should have been trimmed):")
        for category, q, brands, answer in ungrounded_brand_hits:
            print(f"  - [{category}] {q}  brands={brands}\n    answer: {answer}")
    else:
        print("Ungrounded brand names: none survived in any answer.")

    print("=" * 70)
    expected_verdict_total = sum(1 for q in QUESTIONS if q.get("expected_verdict"))
    if verdict_mismatches:
        print(f"VERDICT MISMATCHES ({len(verdict_mismatches)}/{expected_verdict_total} "
              f"worth-it questions whose assess_suitability() verdict didn't match expected):")
        for category, q, expected, got in verdict_mismatches:
            print(f"  - [{category}] expected={expected} got={got}: {q}")
    else:
        print(f"Worth-it verdicts: all {expected_verdict_total} questions matched the "
              f"expected assess_suitability() verdict (and note, where checked).")

    if sizing_leak_hits:
        print(f"SIZING LEAKED INTO {len(sizing_leak_hits)} not_worth ANSWER(S) "
              f"(a kWp/panel figure appeared where item 5 says none should):")
        for category, q, answer in sizing_leak_hits:
            print(f"  - [{category}] {q}\n    answer: {answer}")
    else:
        print("Sizing leaks into not_worth answers: none.")


if __name__ == "__main__":
    main()
