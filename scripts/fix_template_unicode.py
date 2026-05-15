"""
Scan templates/ for CP1252-as-UTF-8 mojibake and fix it.

Mojibake happens when a UTF-8 file is decoded as Windows-1252 and then re-saved
as UTF-8. The fix: encode the bad sequence back to cp1252 bytes and decode as
UTF-8.

Run from project root:  python scripts/fix_template_unicode.py
"""
import os, re

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "templates"))

# Map mojibake string -> intended character.
# Each key is built with explicit \uXXXX escapes so the source file is portable.
# 'â' = U+00E2, 'Ã' = U+00C3, 'Â' = U+00C2 — the three classic mojibake prefixes.
PAIRS = {
    # â† + U+2019 (')  -> → (right arrow)   [bytes E2 86 92]
    "â†’": "→",
    # â† + U+0090 (ctl) -> ← (left arrow)   [bytes E2 86 90]
    "â†": "←",
    # â† + NBSP         -> ← + NBSP (some files)  [keep trailing space-like char gone]
    # â” + €            -> ─ (box draw H)   [bytes E2 94 80]   ('"' = U+201D)
    "â”€": "─",
    # â• + U+0090       -> ═ (box draw 2H)  [bytes E2 95 90]
    "â•": "═",
    # â˜ + …           -> ★ (black star)    [bytes E2 98 85]   ('˜' = U+02DC, '…' = U+2026)
    "â˜…": "★",
    # â˜ + †           -> ☆ (white star)    [bytes E2 98 86]
    "â˜†": "☆",
    # â– + ²            -> ▲ (up triangle)   [bytes E2 96 B2]   ('–' = U+2013)
    "â–²": "▲",
    # â– + ¼            -> ▼ (down triangle) [bytes E2 96 BC]
    "â–¼": "▼",
    # âœ + "           -> ✓ (check)         [bytes E2 9C 93]   ('œ' = U+0153, '"' = U+201C)
    "âœ“": "✓",
    # âœ + —            -> ✗ (ballot x)      [bytes E2 9C 97]   ('—' = U+2014)
    "âœ—": "✗",
    # âœ + …            -> ✅ (white check)   [bytes E2 9C 85]
    "âœ…": "✅",
    # â› + "           -> ⛔ (no entry)      [bytes E2 9B 94]   ('›' = U+203A)
    "â›”": "⛔",
    # âš + NBSP         -> ⚠ (warning)       [bytes E2 9A A0]   ('š' = U+0161)
    "âš ": "⚠",
    # Common 2-byte mojibake:
    "Ã—": "×",  # Ã—  -> ×  (multiplication)
    "Â¾": "¾",  # Â¾  -> ¾
    "Â¼": "¼",  # Â¼  -> ¼
    "Â²": "²",  # Â²  -> ²
    "Â°": "°",  # Â°  -> °
    "Â·": "·",  # Â·  -> ·
    "Â©": "©",  # Â©  -> ©
    "Â®": "®",  # Â®  -> ®
    "Â½": "½",  # Â½  -> ½
}

def fix_text(text):
    for bad, good in PAIRS.items():
        text = text.replace(bad, good)
    return text

def scan_remaining(text):
    """Return a sample list of mojibake-looking sequences still in the text."""
    found = set()
    for m in re.finditer(r"[âÃÂ][-ÿĀ-⿿]{1,2}", text):
        found.add(m.group(0))
    return sorted(found)

def main():
    changed = []
    leftovers = {}
    for dirpath, _, files in os.walk(ROOT):
        for fn in files:
            if not fn.endswith(".html"):
                continue
            p = os.path.join(dirpath, fn)
            with open(p, "r", encoding="utf-8") as f:
                src = f.read()
            new = fix_text(src)
            if new != src:
                with open(p, "w", encoding="utf-8", newline="") as f:
                    f.write(new)
                changed.append(os.path.relpath(p, ROOT))
            rem = scan_remaining(new)
            if rem:
                leftovers[os.path.relpath(p, ROOT)] = rem

    print("=" * 60)
    if changed:
        print(f"Fixed {len(changed)} file(s):")
        for c in changed:
            print(f"  - {c}")
    else:
        print("No fixes applied.")
    print("=" * 60)
    if leftovers:
        print("Remaining mojibake-looking sequences (review manually):")
        for f, seqs in leftovers.items():
            print(f"  {f}")
            for s in seqs:
                pts = " ".join(f"U+{ord(c):04X}" for c in s)
                print(f"    {s!r}  ({pts})")
    else:
        print("No residual mojibake detected.")

if __name__ == "__main__":
    main()
