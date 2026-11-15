"""Upload validation: rejection vs service failure, strict parsing, one prompt.

DB-free on purpose. It imports `upload_validation` directly and never
`app`, because importing app runs init_db(). No provider is ever contacted:
every HTTP call is replaced with a stub, so no document leaves this process
and no credentials are needed.

    venv\\Scripts\\python.exe scripts\\test_upload_validation.py
"""
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))

# Config must be set before import: the module reads provider settings at
# import time, which is itself worth knowing about.
os.environ.setdefault("GROQ_API_KEY", "test-key-not-real")
os.environ.pop("DEV_SKIP_VALIDATION", None)

import upload_validation as uv       # noqa: E402

results = []


def check(name, passed, detail=""):
    results.append((name, passed, detail))
    print(f"  [{'PASS' if passed else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))


def png_bytes(size=(48, 48), colour=(10, 120, 200)):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", size, colour).save(buf, "PNG")
    return buf.getvalue()


class FakeResponse:
    def __init__(self, status=200, payload=None, text=None, headers=None):
        self.status_code = status
        self._payload = payload
        self._text = text
        self.headers = headers or {}

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload

    @property
    def text(self):
        return self._text or json.dumps(self._payload)


def model_says(obj_or_text, status=200, headers=None):
    """A provider reply carrying `obj_or_text` as the assistant message."""
    content = obj_or_text if isinstance(obj_or_text, str) else json.dumps(obj_or_text)
    return FakeResponse(status,
                        {"choices": [{"message": {"content": content}}]},
                        headers=headers)


class Recorder:
    """Stands in for requests.post and records what was sent."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, url, json=None, headers=None, timeout=None, **kw):
        self.calls.append({"url": url, "payload": json,
                           "headers": headers or {}, "timeout": timeout})
        if not self.replies:
            raise AssertionError("provider called more times than expected")
        nxt = self.replies.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


def with_provider(provider, *replies):
    """Install a recorder and point the module at `provider`."""
    rec = Recorder(*replies)
    uv._http.post = rec                      # noqa: SLF001
    uv.AI_PROVIDER = provider
    return rec


_real_post = uv._http.post
_real_provider = uv.AI_PROVIDER
_real_sleep = uv.time.sleep
uv.time.sleep = lambda s: None               # no real waiting in tests


print("\n1. A clear accept and a clear reject are both verdicts")
rec = with_provider("groq", model_says({"valid": True, "reason": "Looks fine."}))
r = uv.validate_file(png_bytes(), "p.png", "photo_2x2")
check("accept -> outcome valid", r["outcome"] == uv.OUTCOME_VALID, str(r.get("outcome")))
check("accept -> valid is a real bool True", r["valid"] is True, repr(r.get("valid")))
check("accept maps to HTTP 200", uv.OUTCOME_HTTP[r["outcome"]] == 200)
check("a correlation id is returned", bool(r.get("correlation_id")))

rec = with_provider("groq", model_says({"valid": False, "reason": "Full-body shot."}))
r = uv.validate_file(png_bytes(), "p.png", "photo_2x2")
check("reject -> outcome rejected", r["outcome"] == uv.OUTCOME_REJECTED)
check("reject -> valid is a real bool False", r["valid"] is False, repr(r.get("valid")))
check("reject is still HTTP 200 (the question was answered)",
      uv.OUTCOME_HTTP[r["outcome"]] == 200)
check("the model's wording reaches the caller", "Full-body" in r["reason"])


print("\n2. A quoted boolean is NOT an approval")
# `{"valid": "false"}` is a truthy Python string. The old code did
# `result.get("valid")` and accepted every such document.
for bad in ("false", "true", "False", 1, 0, None, [], {}):
    rec = with_provider("groq", model_says({"valid": bad, "reason": "x"}))
    r = uv.validate_file(png_bytes(), "p.png", "photo_2x2")
    ok = r["outcome"] == uv.OUTCOME_MALFORMED and r["valid"] is None
    check(f"valid={bad!r} -> malformed, not approved", ok,
          f"outcome={r['outcome']} valid={r['valid']!r}")


print("\n3. Service failures are never verdicts")
cases = [
    ("429 rate limit", model_says({}, 429, {"retry-after": "4"}),
     uv.OUTCOME_RATE_LIMITED, 429),
    ("500 upstream", model_says({}, 500), uv.OUTCOME_UNAVAILABLE, 503),
    ("401 bad key", model_says({}, 401), uv.OUTCOME_NOT_CONFIGURED, 503),
    ("404 unknown model", model_says({}, 404), uv.OUTCOME_UNAVAILABLE, 503),
    ("timeout", uv._http.exceptions.Timeout("slow"), uv.OUTCOME_TIMEOUT, 504),
    ("connection refused",
     uv._http.exceptions.ConnectionError("refused"), uv.OUTCOME_UNAVAILABLE, 503),
    ("non-JSON body", model_says("I think it looks nice!"), uv.OUTCOME_MALFORMED, 502),
    ("no choices key", FakeResponse(200, {"oops": 1}), uv.OUTCOME_MALFORMED, 502),
]
for label, reply, want_outcome, want_http in cases:
    # Two replies for the 429 case: it retries once, then gives up.
    replies = [reply, reply] if want_outcome == uv.OUTCOME_RATE_LIMITED else [reply]
    rec = with_provider("groq", *replies)
    r = uv.validate_file(png_bytes(), "p.png", "valid_id")
    good = (r["outcome"] == want_outcome
            and r["valid"] is None
            and uv.OUTCOME_HTTP[r["outcome"]] == want_http)
    check(f"{label} -> {want_outcome} / HTTP {want_http}, valid=None", good,
          f"outcome={r['outcome']} valid={r['valid']!r}")
    check(f"  {label} is not described as an invalid document",
          "invalid" not in r["reason"].lower()
          and "not look like" not in r["reason"].lower(),
          r["reason"][:70])

rec = with_provider("groq", model_says({}, 429, {"retry-after": "4"}),
                    model_says({}, 429, {"retry-after": "4"}))
r = uv.validate_file(png_bytes(), "p.png", "valid_id")
check("a 429 is retried once before giving up", len(rec.calls) == 2,
      f"{len(rec.calls)} call(s)")
check("retry_after is surfaced for the UI", r.get("retry_after") == 4.0,
      repr(r.get("retry_after")))

# photo_2x2, not valid_id: an ID reply with no `extracted` fields is
# legitimately rejected by the format stage, which would mask the retry.
rec = with_provider("groq", model_says({}, 429, {"retry-after": "2"}),
                    model_says({"valid": True, "reason": "ok"}))
r = uv.validate_file(png_bytes(), "p.png", "photo_2x2")
check("a 429 that clears on retry yields a real verdict",
      r["outcome"] == uv.OUTCOME_VALID, str(r.get("outcome")))
check("  and the retry really was the second call", len(rec.calls) == 2,
      f"{len(rec.calls)} call(s)")


print("\n4. Missing credentials never contact anyone")
rec = with_provider("groq")
_key = uv.GROQ_API_KEY
uv.GROQ_API_KEY = ""
r = uv.validate_file(png_bytes(), "p.png", "photo_2x2")
check("no key -> not_configured", r["outcome"] == uv.OUTCOME_NOT_CONFIGURED)
check("and no request was attempted", not rec.calls, f"{len(rec.calls)} calls")
check("valid stays None", r["valid"] is None)
uv.GROQ_API_KEY = _key


print("\n5. Unusable files are rejected locally, with no provider call")
for fname, data, label in [
    ("notes.txt", b"hello", "unsupported extension"),
    ("empty.png", b"", "empty file"),
]:
    rec = with_provider("groq")
    r = uv.validate_file(data, fname, "photo_2x2")
    check(f"{label} -> invalid_file", r["outcome"] == uv.OUTCOME_INVALID_FILE,
          str(r.get("outcome")))
    check(f"  {label} contacts no provider", not rec.calls)
rec = with_provider("groq")
r = uv.validate_file(png_bytes(), "x.png", "not_a_type")
check("unknown doc type -> invalid_file", r["outcome"] == uv.OUTCOME_INVALID_FILE)
check("  and contacts no provider", not rec.calls)


print("\n6. BOTH providers receive the IDENTICAL prompt per document type")
for doc_type in sorted(uv.PROMPTS):
    img = png_bytes()
    g = with_provider("groq", model_says({"valid": True, "reason": "ok"}))
    uv.validate_file(img, "d.png", doc_type)
    l = with_provider("lmstudio", model_says({"valid": True, "reason": "ok"}))
    uv.validate_file(img, "d.png", doc_type)

    def prompt_of(rec):
        content = rec.calls[0]["payload"]["messages"][0]["content"]
        return next(p["text"] for p in content if p["type"] == "text")

    gp, lp = prompt_of(g), prompt_of(l)
    check(f"{doc_type}: same prompt text to both adapters", gp == lp,
          "differs" if gp != lp else "")
    check(f"{doc_type}: prompt is verbatim PROMPTS[{doc_type}]",
          gp == uv.PROMPTS[doc_type])

    def image_of(rec):
        content = rec.calls[0]["payload"]["messages"][0]["content"]
        return next(p["image_url"]["url"] for p in content if p["type"] == "image_url")

    check(f"{doc_type}: same image bytes to both", image_of(g) == image_of(l))
    # Only transport may differ.
    check(f"{doc_type}: groq uses json_object, lmstudio text",
          g.calls[0]["payload"]["response_format"]["type"] == "json_object"
          and l.calls[0]["payload"]["response_format"]["type"] == "text")
    check(f"{doc_type}: groq is authenticated, lmstudio local",
          "Authorization" in g.calls[0]["headers"]
          and "Authorization" not in l.calls[0]["headers"])
    check(f"{doc_type}: temperature pinned to 0 on both",
          g.calls[0]["payload"]["temperature"] == 0
          and l.calls[0]["payload"]["temperature"] == 0)

check("there is exactly one prompt table in the module",
      sum(1 for n in dir(uv) if isinstance(getattr(uv, n), dict)
          and set(getattr(uv, n)) == set(uv.PROMPTS)) == 1)


print("\n7. The configured provider is never silently swapped")
rec = with_provider("lmstudio", uv._http.exceptions.ConnectionError("refused"))
r = uv.validate_file(png_bytes(), "p.png", "photo_2x2")
check("LM Studio down -> service_unavailable", r["outcome"] == uv.OUTCOME_UNAVAILABLE)
check("and Groq was NOT contacted as a fallback",
      all("groq" not in c["url"] for c in rec.calls), str([c["url"] for c in rec.calls]))
check("exactly one endpoint was tried", len(rec.calls) == 1)
rec = with_provider("lmstudio", model_says({"valid": True, "reason": "ok"}))
uv.validate_file(png_bytes(), "p.png", "photo_2x2")
check("lmstudio posts to its own /v1/chat/completions",
      rec.calls[0]["url"].endswith("/v1/chat/completions")
      and "127.0.0.1" in rec.calls[0]["url"] or "localhost" in rec.calls[0]["url"],
      rec.calls[0]["url"])


print("\n8. The portrait prompt does not prime the model to see composites")
p = uv.PROMPTS["photo_2x2"]
# A long list of layout failure modes taught a small vision model to report
# one. qwen3-vl-4b rejected a plain single headshot as "a composite or tiled
# layout containing multiple cropped sections of the same person" — wording
# taken from the prompt it had just been handed. These guard the regression.
PRIMING = ["composite", "tiled", "grid", "sheet", "panel", "multiple cropped",
           "collage", "mosaic"]
for word in PRIMING:
    check(f"the prompt never says {word!r}", word not in p.lower(),
          "present" if word in p.lower() else "")
check("the schema does not ask about sheets or crops",
      "is_multi_print_sheet" not in p and "is_headshot_crop" not in p)
check("it tells the model not to speculate about layout",
      "Do not speculate about layout" in p)
check("and does so without naming the failure mode it is avoiding",
      "grids" not in p and "panels" not in p)
check("it leans toward acceptance", "When in doubt, accept" in p)
check("it asks one plain question",
      "is this a usable photo of one person" in p.lower())
check("a square photo is explicitly normal", "Square photos" in p)
check("it still rejects ID cards as portraits", "ID card" in p)
check("it still rejects non-photographs", "drawing, cartoon, avatar" in p)
check("it still rejects unreadable faces", "too blurred" in p)
check("it demands a genuine JSON boolean", "MUST be a JSON boolean" in p)
check("every prompt demands strict JSON",
      all("strict JSON" in v for v in uv.PROMPTS.values()))
check("the portrait prompt stays short enough not to drown a small model",
      len(p) < 1600, f"{len(p)} chars")


print("\n9. ID format checks can only tighten a verdict")
rec = with_provider("groq", model_says({
    "valid": True, "id_type": "PRC", "reason": "Readable PRC ID.",
    "extracted": {"holder_name": "JUAN DELA CRUZ", "id_number": "1234567",
                  "profession_or_class": "ARCHITECT"}}))
r = uv.validate_file(png_bytes(), "id.png", "valid_id")
check("a placeholder name turns accept into reject",
      r["outcome"] == uv.OUTCOME_REJECTED and r["valid"] is False,
      str(r.get("outcome")))
check("and the reason explains why", "sample" in r["reason"].lower()
      or "placeholder" in r["reason"].lower(), r["reason"][:60])

rec = with_provider("groq", model_says({
    "valid": False, "id_type": None, "reason": "This is a school ID.",
    "extracted": {}}))
r = uv.validate_file(png_bytes(), "id.png", "valid_id")
check("a reject is never upgraded to accept by the format stage",
      r["valid"] is False and r["outcome"] == uv.OUTCOME_REJECTED)


print("\n10. Large images are shrunk before they are sent")
big = png_bytes(size=(3000, 2200))
rec = with_provider("groq", model_says({"valid": True, "reason": "ok"}))
uv.validate_file(big, "big.png", "valid_id")
sent = rec.calls[0]["payload"]["messages"][0]["content"][1]["image_url"]["url"]
import base64 as _b64
raw = _b64.b64decode(sent.split(",", 1)[1])
from PIL import Image as _Img
w, h = _Img.open(io.BytesIO(raw)).size
check("the long edge is capped", max(w, h) <= uv.MAX_IMAGE_EDGE, f"{w}x{h}")
check("it is materially smaller than the original",
      len(raw) < len(big), f"{len(raw)} vs {len(big)} bytes")
small = png_bytes(size=(64, 64))
rec = with_provider("groq", model_says({"valid": True, "reason": "ok"}))
uv.validate_file(small, "small.png", "valid_id")
sent = rec.calls[0]["payload"]["messages"][0]["content"][1]["image_url"]["url"]
check("a small image is left untouched",
      _b64.b64decode(sent.split(",", 1)[1]) == small)


print("\n11. Diagnostics stay sanitized")
import contextlib
buf = io.StringIO()
rec = with_provider("groq", model_says({
    "valid": True, "id_type": "PRC", "reason": "ok",
    "extracted": {"holder_name": "REAL PERSON NAME", "id_number": "7654321",
                  "profession_or_class": "ENGINEER"}}))
with contextlib.redirect_stdout(buf):
    uv.validate_file(png_bytes(), "secret-filename.png", "valid_id")
logged = buf.getvalue()
check("the log names provider, model, type and outcome",
      "provider=groq" in logged and "model=" in logged
      and "type=valid_id" in logged and "outcome=" in logged, logged.strip()[:90])
check("it does not log extracted identity data",
      "REAL PERSON NAME" not in logged and "7654321" not in logged)
check("it does not log the image or a data URL",
      "base64" not in logged and "data:image" not in logged)
check("it does not log the API key", (uv.GROQ_API_KEY or "zzz") not in logged)

buf = io.StringIO()
rec = with_provider("groq", model_says("utter nonsense, no json here"))
with contextlib.redirect_stdout(buf):
    uv.validate_file(png_bytes(), "x.png", "resume")
logged = buf.getvalue()
check("a malformed reply is logged by category, not by body",
      "outcome=malformed_response" in logged and "nonsense" not in logged,
      logged.strip()[:90])


print("\n12. DEV_SKIP_VALIDATION is off unless explicitly set")
check("the shipped default does not skip validation", uv.DEV_SKIP_VALIDATION is False)

uv._http.post = _real_post
uv.AI_PROVIDER = _real_provider
uv.time.sleep = _real_sleep

failed = [x for x in results if not x[1]]
print(f"\n{'='*64}\n{len(results) - len(failed)}/{len(results)} passed")
for n, _, d in failed:
    print(f"  FAILED: {n} {d}")
print("No provider was contacted and no database was used.")
sys.exit(1 if failed else 0)
