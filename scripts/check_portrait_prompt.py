"""Run the real validation prompt against one local image, via LM Studio.

Local only: it talks to LM_STUDIO_URL and nothing else, so the image never
leaves this machine. Use it to confirm on your own photo that the prompt
change actually fixes the false "composite" rejection.

    venv\\Scripts\\python.exe scripts\\check_portrait_prompt.py "C:\\path\\photo.jpg"

With --compare it runs the OLD prompt too, so you can see which one the model
is reacting to rather than guessing:

    venv\\Scripts\\python.exe scripts\\check_portrait_prompt.py photo.jpg --compare

Nothing is written anywhere and the image is not logged.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

# MUST precede the import: upload_validation reads VISION_PROVIDER and the
# model names at import time. Without this the script silently falls back to
# the built-in defaults and reports on a provider you are not using — and it
# is the same reason the running Flask app needs a RESTART after .env changes.
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))
except ImportError:
    pass

import upload_validation as uv      # noqa: E402

# The prompt as it stood when the false rejection was reported, kept here
# ONLY for this comparison. It is not used by the application.
OLD_PROMPT = (
    "You are validating a 2x2 PORTRAIT PHOTO (headshot) uploaded for a training "
    "registration. A 2x2 photo must be CROPPED to show the head and shoulders—NOT a "
    "full-body or mid-body shot.\n\n"
    "ACCEPT (valid=true) ONLY if the image is a clear HEADSHOT / PORTRAIT where:\n"
    "- The face and head are the dominant subject.\n"
    "- It is ONE real person, not a drawing, AI avatar, or composite.\n\n"
    "REJECT (valid=false) if ANY of these are true:\n"
    "- It is a layout/template/composite with multiple panels, sections, or "
    "placeholder silhouettes.\n"
    "- The image is a photograph or scan of an ID card, license, passport, "
    "certificate, or document.\n\n"
    "Reply ONLY with strict JSON: "
    "{\"valid\": true|false, \"reason\": \"short user-facing explanation\"}"
)


def run(prompt, data_url, label):
    print(f"\n--- {label} ---")
    try:
        result = uv._call_lmstudio_vision(prompt, data_url)   # noqa: SLF001
    except uv.ProviderError as e:
        print(f"  provider failed: {e.outcome} ({e.detail})")
        if e.outcome == uv.OUTCOME_UNAVAILABLE:
            print("  Is LM Studio's server running? Developer tab -> Start Server.")
        return
    verdict = uv._coerce_valid(result.get("valid"))            # noqa: SLF001
    print(f"  valid  : {verdict!r}" +
          ("" if isinstance(verdict, bool)
           else "   <-- not a real boolean; treated as malformed"))
    print(f"  reason : {str(result.get('reason'))[:300]}")
    extra = {k: v for k, v in result.items() if k not in ("valid", "reason")}
    if extra:
        print(f"  details: {json.dumps(extra)[:300]}")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    compare = "--compare" in sys.argv
    if len(args) != 1:
        sys.exit(__doc__)
    path = args[0]
    if not os.path.exists(path):
        sys.exit(f"No such file: {path}")

    with open(path, "rb") as f:
        raw = f.read()
    ext = path.rsplit(".", 1)[-1].lower()
    if ext == "pdf":
        raw = uv._pdf_first_page_png(raw)                      # noqa: SLF001
        ext = "png"
        if not raw:
            sys.exit("Could not render that PDF.")
    shrunk, new_ext = uv._downscale_for_vision(raw)            # noqa: SLF001
    data_url = uv._image_to_data_url(shrunk, new_ext or ext)   # noqa: SLF001

    print(f"file      : {path}")
    print(f"bytes sent: {len(shrunk)} (original {len(raw)})")
    print(f"endpoint  : {uv.LMSTUDIO_URL}")
    print(f"model     : {uv.LMSTUDIO_MODEL}")

    run(uv.PROMPTS["photo_2x2"], data_url, "CURRENT prompt (what the app uses)")
    if compare:
        run(OLD_PROMPT, data_url, "OLD prompt (the one that over-rejected)")
        print("\nIf the old prompt rejects and the current one accepts, the "
              "wording was the cause.\nIf both reject this photo, the model "
              "itself is too weak for the job — try a\nlarger VL model in LM "
              "Studio (for example a 7B/8B qwen2.5-vl) and re-run.")


if __name__ == "__main__":
    main()
