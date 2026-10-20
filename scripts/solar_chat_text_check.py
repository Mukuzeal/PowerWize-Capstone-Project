"""solar_chat_text_check.py — asserts _strip_emojis removes only emojis and
leaves curly quotes, en/em dashes, and accented Latin letters untouched.
Guards against the 2026-09 mojibake regression (UTF-8 read as Latin-1 in
_call_lmstudio's stream decode) ever being mistaken for something
_strip_emojis did — it never encodes/decodes bytes, only matches Unicode
codepoint ranges, so it can't be the source of that kind of corruption.

Run from the src/ directory so flat imports resolve:
    cd src && ..\\venv\\Scripts\\python.exe ..\\scripts\\solar_chat_text_check.py
"""
import os
import sys

# The Windows console defaults stdout to cp1252, which can't encode the
# emoji/curly-quote test input this script prints — reconfigure rather than
# let that crash the run (ironic, given what this script is guarding
# against: this codebase's history of UTF-8-vs-CP1252 mismatches).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from solar_bp import _strip_emojis

CASES = [
    ("They’re happy \U0001F600 with the quñay setup — great!",
     "They’re happy with the quñay setup — great!"),
    ("Mañana we’ll check – no rush \U0001F31E today.",
     "Mañana we’ll check – no rush today."),
    ("Plain ASCII sentence, nothing to strip.",
     "Plain ASCII sentence, nothing to strip."),
    ("Multiple emoji \U0001F600\U0001F389\U00002728 in a row.",
     "Multiple emoji in a row."),
]


def main():
    failures = 0
    for raw, expected in CASES:
        got = _strip_emojis(raw)
        ok = got == expected
        failures += 0 if ok else 1
        print(f"[{'OK' if ok else 'FAIL'}] {raw!r}\n       -> {got!r}\n       expected {expected!r}\n")
    if failures:
        print(f"{failures} of {len(CASES)} case(s) failed.")
        sys.exit(1)
    print(f"All {len(CASES)} case(s) passed.")


if __name__ == "__main__":
    main()
