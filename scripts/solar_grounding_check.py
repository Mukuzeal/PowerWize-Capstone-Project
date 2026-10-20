"""solar_grounding_check.py — asserts the 2026-09-24 grounding fixes behave
as intended:
  1. _split_into_subquestions splits a multi-question message on '?'/newline.
  2. _has_unverifiable_company_claim catches coverage/licensing/undocumented-
     offering phrases, while leaving genuinely-documented ones (licensed
     TECHNICIANS do installs; "smart monitoring" IS an offering) untouched.
  3. _trim_ungrounded_sentences cascades: a sentence whose only content is a
     reference to an already-trimmed sentence ("These are...") is dropped
     too, but the same referent survives when its antecedent does.

Run from the src/ directory so flat imports resolve:
    cd src && ..\\venv\\Scripts\\python.exe ..\\scripts\\solar_grounding_check.py
"""
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from solar_bp import (
    _split_into_subquestions,
    _has_unverifiable_company_claim,
    _trim_ungrounded_sentences,
    _context_supports_doe_claim,
)

failures = 0


def check(label, got, expected):
    global failures
    ok = got == expected
    failures += 0 if ok else 1
    print(f"[{'OK' if ok else 'FAIL'}] {label}")
    if not ok:
        print(f"       got:      {got!r}")
        print(f"       expected: {expected!r}")


# ── 1. Multi-question splitting ─────────────────────────────────────────
check(
    "split on ? and newline",
    _split_into_subquestions("What warranty do panels have? What brands do you use?\nHow does net metering work?"),
    ["What warranty do panels have", "What brands do you use", "How does net metering work"],
)
check(
    "single question is one fragment",
    _split_into_subquestions("How does net metering work?"),
    ["How does net metering work"],
)

# ── 2. Company-claim detection: new categories catch, documented ones don't ──
CLAIM_CASES = [
    ("We've installed systems across all provinces including Laguna.", True),
    ("Our team is fully licensed.", True),
    ("Our monitoring app lets you track output from your phone.", True),
    ("We also offer flexible financing options.", True),
    ("No hidden fees, ever.", True),
    # 2026-09-24 rag_eval.py 3x run: caught live, verbatim from the model,
    # surviving untrimmed before this fix.
    ("EnergyWize is licensed by the Department of Energy (DOE) in the Philippines "
     "and has been helping customers install solar PV systems since 2019.", True),
    ("We're officially registered with the Department of Energy (DOE) in the Philippines.", True),
    ("We've worked with clients across different provinces and property types.", True),
    ("We've been doing this for over a decade.", True),
    ("Our team has 15+ years of experience in solar installation.", True),
    # 2026-09-24, second pass: a FOLLOW-UP rag_eval.py 3x run (after the
    # first DOE/coverage fix above already shipped) produced these two new
    # paraphrases, neither caught by the literal phrase lists — this is what
    # motivated switching those two checks to regex.
    ("We're licensed and certified by the Department of Energy (DOE) to install solar systems.", True),
    ("We cover most provinces and cities across the Philippines.", True),
    # Must NOT trigger — these are genuinely documented, or a legitimate
    # regulatory citation rather than a claim about EnergyWize itself:
    ("Installation is done by licensed technicians.", False),
    ("Smart monitoring is included so performance can be verified.", False),
    ("Under ERC Resolution No. 15, Series of 2025, unused credits roll over indefinitely.", False),
    ("DOE Circular No. DC2026-04-0011 requires utilities to process applications within 10 working days.", False),
    ("This is a preliminary estimate, not a binding quotation.", False),
]
for text, expected in CLAIM_CASES:
    check(f"company-claim({text!r})", _has_unverifiable_company_claim(text), expected)

# ── 2b. DOE claim: unconditional by default, but survives once CONTEXT
#        genuinely grounds it. ─────────────────────────────────────────
doe_sentence = "EnergyWize is licensed by the Department of Energy (DOE)."
check("DOE claim trimmed with no context",
      _has_unverifiable_company_claim(doe_sentence, doe_grounded=False), True)
check("DOE claim survives when context grounds it",
      _has_unverifiable_company_claim(doe_sentence, doe_grounded=True), False)

ungrounded_context = "\n\nCONTEXT:\n[Net Metering] Credits roll over indefinitely.\n"
grounded_context = ("\n\nCONTEXT:\n[DOE registration] EnergyWize is licensed by the "
                     "Department of Energy under Registration No. RE-2024-00123.\n")
check("_context_supports_doe_claim False on unrelated context",
      _context_supports_doe_claim(ungrounded_context), False)
check("_context_supports_doe_claim True once the KB stub is filled in",
      _context_supports_doe_claim(grounded_context), True)

# 2026-09-24, third pass: knowledge/solar/our-offerings-and-process.md's now
# real "DOE registration" section says "DOE-Registered"/"DOE-Recognized"
# (DOE as an adjective prefix) — a different grammatical shape from "licensed
# BY THE Department of Energy" above. _context_supports_doe_claim tested
# False against this exact real chunk text until the regex grew a second
# alternative for it; this locks that shape in directly, not simulated.
real_doe_chunk_context = (
    "\n\nCONTEXT:\n[DOE registration]\nEnergyWize Solutions Inc. (E-Wize Solutions) "
    "is a DOE-Registered Energy Service Company (ESCO) and a DOE-Recognized "
    "Training Institution (RTI).\n"
)
check("_context_supports_doe_claim True against the real KB chunk's actual phrasing",
      _context_supports_doe_claim(real_doe_chunk_context), True)
check("model claim in the KB's own adjective shape is also detected as a claim",
      _has_unverifiable_company_claim("We are a DOE-registered ESCO.", doe_grounded=False), True)

# ── 3. Orphan-referent cascade ──────────────────────────────────────────
orphan_text = (
    "EnergyWize installs solar systems for residential and commercial properties across the areas it serves. "
    "The inverter comes with a 12-year warranty and the panels with a 25-year warranty. "
    "These are standard industry terms. "
    "We work with Deye inverters, chosen for their reliability and local support availability."
)
trimmed = _trim_ungrounded_sentences(orphan_text, allowed=set(), context_brands={"Deye"})
check("orphan referent dropped", "These are standard industry terms." not in (trimmed or ""), True)
check("ungrounded antecedent dropped", "12-year" not in (trimmed or ""), True)
check("unrelated sentence survives", "areas it serves" in (trimmed or ""), True)
check("grounded brand sentence survives", "Deye" in (trimmed or ""), True)

surviving_text = (
    "We work with Deye inverters, chosen for their reliability and local support availability. "
    "These are the same inverters EnergyWize has used across its residential and commercial installations."
)
trimmed2 = _trim_ungrounded_sentences(surviving_text, allowed=set(), context_brands={"Deye"})
check("referent survives when antecedent survives",
      "These are the same inverters" in (trimmed2 or ""), True)

if failures:
    print(f"\n{failures} case(s) failed.")
    sys.exit(1)
print(f"\nAll cases passed.")
