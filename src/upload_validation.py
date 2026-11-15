"""
AI-powered upload validation.

POST /api/validate-upload (multipart):
  file: the uploaded file (image or PDF)
  type: one of photo_2x2 | valid_id | expired_doe | resume | solar_bill

Returns JSON: { outcome: str, valid: bool|null, reason: str, details: {...} }

`outcome` is the machine-readable result and is authoritative. `valid` is a
REAL boolean only when the model actually answered; for operational failures
it is null, never false. That distinction is the whole point of this module's
contract: a provider outage or a rate limit is not a verdict on the
applicant's document, and must never be shown as "your ID is invalid" nor
treated as a pass.

    OUTCOME_VALID         the model answered and accepted the document
    OUTCOME_REJECTED      the model answered and rejected it
    OUTCOME_INVALID_FILE  unusable upload (bad type, too big, empty, bad PDF)
    OUTCOME_RATE_LIMITED  provider throttled us; retry_after seconds given
    OUTCOME_UNAVAILABLE   provider unreachable / erroring
    OUTCOME_TIMEOUT       provider did not answer in time
    OUTCOME_MALFORMED     provider answered with something unparseable
    OUTCOME_NOT_CONFIGURED  no credentials / provider misconfigured

The vision provider follows VISION_PROVIDER (groq | lmstudio) and is never
switched implicitly: if the configured provider fails, the caller is told the
service failed. Sending a document to a different service than the one the
operator configured would be a disclosure, not a fallback.

For PDFs the first page is rendered to PNG before submission.
"""
import os
import io
import json
import base64
import re
import time
import uuid
from flask import Blueprint, request, jsonify

import requests as _http

validation_bp = Blueprint("upload_validation", __name__)

# ── Outcomes ─────────────────────────────────────────────────────────────────
OUTCOME_VALID          = "valid"
OUTCOME_REJECTED       = "rejected"
OUTCOME_INVALID_FILE   = "invalid_file"
OUTCOME_RATE_LIMITED   = "rate_limited"
OUTCOME_UNAVAILABLE    = "service_unavailable"
OUTCOME_TIMEOUT        = "timeout"
OUTCOME_MALFORMED      = "malformed_response"
OUTCOME_NOT_CONFIGURED = "not_configured"

# Outcomes that say something about the DOCUMENT. Everything else is about the
# service, and callers must treat those as "unknown", not as a rejection.
DECISIVE_OUTCOMES = {OUTCOME_VALID, OUTCOME_REJECTED, OUTCOME_INVALID_FILE}

# HTTP status per outcome. A verdict is a successful request even when the
# verdict is "rejected" — the question was answered. Operational failures get
# real error statuses so the browser, logs and any proxy agree on what
# happened instead of every result looking like 200/OK.
OUTCOME_HTTP = {
    OUTCOME_VALID:          200,
    OUTCOME_REJECTED:       200,
    OUTCOME_INVALID_FILE:   400,
    OUTCOME_RATE_LIMITED:   429,
    OUTCOME_UNAVAILABLE:    503,
    OUTCOME_TIMEOUT:        504,
    OUTCOME_MALFORMED:      502,
    OUTCOME_NOT_CONFIGURED: 503,
}


class ProviderError(Exception):
    """A vision provider failed. `outcome` says how, for the caller to map."""

    def __init__(self, outcome, detail="", retry_after=None):
        super().__init__(detail or outcome)
        self.outcome = outcome
        self.detail = detail
        self.retry_after = retry_after

# Reading IDs, licences and selfies is vision work, so it follows
# VISION_PROVIDER independently of whatever model is answering the chat.
# See solar_bp.py for the split; AI_PROVIDER remains the fallback.
AI_PROVIDER = os.getenv("VISION_PROVIDER", os.getenv("AI_PROVIDER", "groq")).lower()

# Groq config
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_VISION_MODEL = os.getenv("GROQ_VISION_MODEL", "qwen/qwen3.8-27b")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# LMStudio config
LMSTUDIO_URL = os.getenv("LM_STUDIO_URL", "http://127.0.0.1:1234")
LMSTUDIO_MODEL = os.getenv("LM_STUDIO_MODEL", "qwen/qwen3-vl-4b")

# Dev-only escape hatch. Set DEV_SKIP_VALIDATION=1 in .env to make every
# validation call pass without hitting Groq. NEVER set this in production.
DEV_SKIP_VALIDATION = os.getenv("DEV_SKIP_VALIDATION", "").strip() in ("1", "true", "yes")

# Prompts keyed by document type. Each must instruct the model to reply with
# strict JSON: {"valid": bool, "reason": "...", "details": {...}}.
#
# THIS DICT IS THE SINGLE AUTHORITATIVE SOURCE for every provider. Both
# adapters are handed PROMPTS[doc_type] verbatim by validate_file(); neither
# keeps its own copy, and provider differences are confined to transport
# concerns (auth, timeout, response_format support). Identical instructions
# still do not guarantee identical verdicts — different models disagree — so
# do not "fix" a disagreement by editing one provider's criteria.
PROMPTS = {
    # Deliberately SHORT, and phrased as one question rather than a checklist.
    #
    # An earlier version of this prompt listed many ways a photo could be a
    # "composite / tiled layout / sheet of prints". Small vision models are
    # suggestible: given that list, qwen3-vl-4b rejected an ordinary
    # single headshot on a white background as "a composite or tiled layout
    # containing multiple cropped sections of the same person" — language
    # lifted straight from the prompt it had just been given. The detail
    # schema asking for `is_multi_print_sheet` made it worse by inviting the
    # model to assert the thing it was primed to look for.
    #
    # So: ask what the picture IS, not what it might fail. The real job here
    # is only to tell a usable headshot apart from an ID card or an unrelated
    # image. Anything finer is the admin's identity review, not this check.
    "photo_2x2": (
        "Look at this image. It was uploaded as someone's portrait photo for a "
        "training registration.\n\n"
        "QUESTION: is this a usable photo of one person's face?\n\n"
        "Set valid=true if you can see a person's face clearly enough to recognise "
        "them. Square photos, plain white or coloured backgrounds, casual clothes, "
        "glasses, smiling or neutral expressions, and ordinary phone photos are all "
        "perfectly normal — accept them. When in doubt, accept.\n\n"
        "Set valid=false ONLY if the image is clearly one of these:\n"
        "- a photo or scan of an ID card, licence, passport page or certificate\n"
        "- a picture with no person in it (object, scenery, text, screenshot)\n"
        "- a drawing, cartoon, avatar or silhouette instead of a photograph\n"
        "- a distant or full-body shot where the face is too small to make out\n"
        "- too blurred or too dark to see the face\n"
        "- several different people, so it is unclear whose photo it is\n\n"
        # Naming the failure mode here — even to forbid it — reintroduces the
        # priming. State the positive instruction only.
        "Describe only what is actually visible. Do not speculate about layout "
        "or about how the photo was produced.\n\n"
        "Reply ONLY with strict JSON. `valid` MUST be a JSON boolean (true or "
        "false), never the strings \"true\"/\"false\": "
        "{\"valid\": true|false, \"reason\": \"short user-facing explanation\", "
        "\"details\": {\"face_visible\": bool, \"is_photograph\": bool, "
        "\"is_document\": bool}}"
    ),
    "valid_id": (
        "You are strictly validating a Philippine government-issued ID upload AND extracting "
        "its key fields for downstream format validation.\n\n"
        "ACCEPTABLE id_type values: PRC, UMID, SSS, Drivers_License, Passport, Postal, Voters, "
        "PhilHealth, TIN, PhilSys, Senior_Citizen, PWD, OFW, NBI. Use null if it is not a Philippine "
        "government ID.\n\n"
        "REJECT (valid=false) if ANY of:\n"
        "- The image is a plain portrait photo (no ID card visible) — wrong document.\n"
        "- It is a school ID, company/employee ID, library card, gym card, or any private/non-government ID.\n"
        "- It is a certificate, diploma, resume, receipt, or unrelated document.\n"
        "- The ID card is so blurry that the name, photo, or ID number cannot be read.\n"
        "- The ID is a SAMPLE / TEMPLATE / DUMMY (placeholder silhouette photos, registration "
        "number like '00000000', 'Juan Dela Cruz' placeholder name, visible 'sample' / 'specimen' "
        "watermark, illustrated avatar instead of a real photograph).\n\n"
        "EXTRACT and return these fields exactly as they appear on the ID (or null if not visible):\n"
        "- holder_name: full printed name on the card\n"
        "- id_number: the primary ID/registration/license/passport/CRN number (digits and any letters)\n"
        "- issue_date: in YYYY-MM-DD if possible, else the raw string as printed\n"
        "- expiry_date: in YYYY-MM-DD if possible, else the raw string as printed\n"
        "- profession_or_class: e.g. 'ARCHITECT' for PRC, 'NON PRO' for LTO, etc. (null if N/A)\n\n"
        "Reply ONLY with strict JSON: "
        "{\"valid\": true|false, \"id_type\": \"PRC|UMID|...\"|null, "
        "\"reason\": \"short user-facing explanation\", "
        "\"extracted\": {\"holder_name\": str|null, \"id_number\": str|null, "
        "\"issue_date\": str|null, \"expiry_date\": str|null, \"profession_or_class\": str|null}, "
        "\"details\": {\"is_government\": bool, \"readable\": bool, \"appears_genuine\": bool}}"
    ),
    "expired_doe": (
        "You are strictly validating an upload of an EXPIRED Department of Energy (DOE) Philippines "
        "professional accreditation certificate (Certified Energy Manager / CEM or Certified Energy "
        "Auditor / CEA). The document must:\n"
        "- Clearly bear DOE Philippines branding (DOE seal, 'Department of Energy', 'Republic of the Philippines').\n"
        "- Show the holder's full name printed on it.\n"
        "- Show a certificate number / accreditation number.\n"
        "- Show issue date and expiry/valid-until date.\n"
        "- Reference CEM, CEA, or DOE Energy Conservation accreditation.\n\n"
        "REJECT (valid=false) if the document is:\n"
        "- A government ID card (PRC, UMID, etc.) — not a certificate.\n"
        "- A school diploma, training certificate from a non-DOE entity, or unrelated certificate.\n"
        "- A blank template, sample, or placeholder.\n"
        "- Unreadable due to blur or low resolution.\n\n"
        "Reply ONLY with strict JSON: "
        "{\"valid\": true|false, \"reason\": \"short user-facing explanation\", "
        "\"details\": {\"has_doe_branding\": bool, \"is_certificate\": bool, \"readable\": bool}}"
    ),
    "resume": (
        "You are strictly validating a resume / curriculum vitae (CV) for a training registration. "
        "The document MUST be a personal resume/CV with recognisable sections such as: contact info / "
        "header, work experience, education, skills, certifications. A single block of text without "
        "structure is NOT a resume.\n\n"
        "REJECT (valid=false) if the document is:\n"
        "- An ID card, certificate, diploma, license, or other non-resume document.\n"
        "- A photo, screenshot of a chat, or random image.\n"
        "- A blank template / sample CV with placeholder text (e.g., 'Lorem ipsum', 'Your Name Here', "
        "'[Job Title]') instead of real information.\n"
        "- Mostly unreadable due to scanning quality.\n\n"
        "Reply ONLY with strict JSON: "
        "{\"valid\": true|false, \"reason\": \"short user-facing explanation\", "
        "\"details\": {\"has_resume_structure\": bool, \"has_real_info\": bool, \"readable\": bool}}"
    ),
    "solar_bill": (
        "You are strictly validating a Philippine electricity bill upload for a solar PV consultation. "
        "Accept ONLY a clear bill from a Philippine electric utility (Meralco, VECO, BENECO, ILECO, "
        "DLPC, CEPALCO, or other Philippine cooperative/utility) showing: utility branding, account "
        "holder name, billing period, kWh consumption, and amount due in PHP.\n\n"
        "REJECT (valid=false) if the document is:\n"
        "- A water bill, internet bill, phone bill, cable bill, or other non-electric utility bill.\n"
        "- An ID, certificate, receipt for purchase, or unrelated document.\n"
        "- A blank template/sample.\n"
        "- So blurry that kWh and amount cannot be read.\n\n"
        "Reply ONLY with strict JSON: "
        "{\"valid\": true|false, \"reason\": \"short user-facing explanation\", "
        "\"details\": {\"is_electricity_bill\": bool, \"has_kwh\": bool, \"has_amount\": bool}}"
    ),
}

MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 MB
SUPPORTED_IMG_EXT = {"png", "jpg", "jpeg", "webp"}

# ── Per-ID-type format validators ─────────────────────────────────────────
# Each validator receives the `extracted` dict from the vision model and
# returns (ok: bool, reason: str). Reason is shown to the user on failure.

_DUMMY_NUMBERS = {"00000000", "0000000", "000000000", "11111111", "12345678", "1234567"}
_DUMMY_NAMES   = {"JUAN DELA CRUZ", "JUAN A. DELA CRUZ", "JUAN MICHAEL DELA CRUZ",
                  "JUAN DE LA CRUZ", "JUAN MICHAEL BIENVENIDO DELA CRUZ",
                  "JOHN DOE", "JANE DOE"}


def _strip_nondigit(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def _looks_dummy(extracted: dict) -> str | None:
    name = (extracted.get("holder_name") or "").strip().upper()
    num  = _strip_nondigit(extracted.get("id_number") or "")
    if name in _DUMMY_NAMES:
        return "The name on the card looks like a sample/placeholder. Please upload your real ID."
    if num and num in _DUMMY_NUMBERS:
        return "The ID number looks like a placeholder (e.g., all zeros). Please upload your real ID."
    if num and len(set(num)) == 1:  # all same digit
        return "The ID number looks like a placeholder. Please upload your real ID."
    return None


def _validate_prc(ex: dict) -> tuple[bool, str]:
    num = _strip_nondigit(ex.get("id_number") or "")
    if not num:
        return False, "Could not read the PRC registration number on this card."
    if not (6 <= len(num) <= 8):
        return False, f"PRC registration number should be 6-8 digits, but read '{num}'."
    if not (ex.get("holder_name") or "").strip():
        return False, "Could not read the holder's name on this PRC ID."
    if not (ex.get("profession_or_class") or "").strip():
        return False, "Could not read the profession on this PRC ID."
    return True, "PRC ID format checks passed."


def _validate_drivers_license(ex: dict) -> tuple[bool, str]:
    raw = (ex.get("id_number") or "").strip()
    if not raw:
        return False, "Could not read the driver's license number."
    return True, "Driver's license format checks passed."


def _validate_passport(ex: dict) -> tuple[bool, str]:
    raw = (ex.get("id_number") or "").strip()
    if not raw:
        return False, "Could not read the passport number."
    return True, "Passport format checks passed."


def _validate_philsys(ex: dict) -> tuple[bool, str]:
    raw = _strip_nondigit(ex.get("id_number") or "")
    if not raw:
        return False, "Could not read the PhilSys card number (PCN)."
    return True, "PhilSys number format checks passed."


def _validate_umid(ex: dict) -> tuple[bool, str]:
    raw = _strip_nondigit(ex.get("id_number") or "")
    if not raw:
        return False, "Could not read the UMID CRN."
    return True, "UMID format checks passed."


def _validate_generic_id(ex: dict) -> tuple[bool, str]:
    """For ID types without a specific known format pattern, require at least name + number."""
    if not (ex.get("holder_name") or "").strip():
        return False, "Could not read the holder's name on this ID."
    if not (ex.get("id_number") or "").strip():
        return False, "Could not read the ID number on this card."
    return True, "Basic ID format checks passed."


_VALIDATORS = {
    "PRC": _validate_prc,
    "Drivers_License": _validate_drivers_license,
    "Passport": _validate_passport,
    "PhilSys": _validate_philsys,
    "UMID": _validate_umid,
}


def _format_validate_id(result: dict) -> dict:
    """Augment AI result with format-validation pass for valid_id docs."""
    if not isinstance(result, dict):
        return result
    if not result.get("valid"):
        return result
    extracted = result.get("extracted") or {}
    dummy_msg = _looks_dummy(extracted)
    if dummy_msg:
        result["valid"] = False
        result["reason"] = dummy_msg
        return result
    id_type = result.get("id_type") or ""
    validator = _VALIDATORS.get(id_type, _validate_generic_id)
    ok, reason = validator(extracted)
    if not ok:
        result["valid"] = False
        result["reason"] = reason
    return result


def _pdf_first_page_png(file_bytes: bytes) -> bytes | None:
    """Render first page of a PDF to PNG bytes.

    Three paths, all pip-installable, tried in turn. PyMuPDF is first because
    it is already a dependency elsewhere, but its native _mupdf.pyd is refused
    outright by Windows Smart App Control on some machines, and pdf2image needs
    a poppler binary that often isn't installed on Windows — pypdfium2 covers
    both gaps with a self-contained wheel. Returns None only if all three fail.
    """
    # Path 1: PyMuPDF
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        if doc.page_count:
            page = doc.load_page(0)
            # render at ~150 DPI
            pix = page.get_pixmap(dpi=150)
            png = pix.tobytes("png")
            doc.close()
            return png
        doc.close()
    except Exception as e:
        # Logged, never silently passed: an ImportError here means a blocked or
        # mismatched native binding, and swallowing it made that undiagnosable.
        print(f"[upload_validation] PyMuPDF render failed: {type(e).__name__}: {e}")

    # Path 2: pypdfium2 (self-contained wheel, no system deps)
    try:
        import pypdfium2 as pdfium
        doc = pdfium.PdfDocument(file_bytes)
        if len(doc):
            buf = io.BytesIO()
            doc[0].render(scale=150 / 72).to_pil().save(buf, format="PNG")
            return buf.getvalue()
    except Exception as e:
        print(f"[upload_validation] pypdfium2 render failed: {type(e).__name__}: {e}")

    # Path 3: pdf2image (requires poppler)
    try:
        from pdf2image import convert_from_bytes
        pages = convert_from_bytes(file_bytes, first_page=1, last_page=1, dpi=150)
        if pages:
            buf = io.BytesIO()
            pages[0].save(buf, format="PNG")
            return buf.getvalue()
    except Exception as e:
        print(f"[upload_validation] pdf2image render failed: {type(e).__name__}: {e}")

    return None


def _image_to_data_url(img_bytes: bytes, ext: str) -> str:
    mime = "image/png"
    if ext in {"jpg", "jpeg"}:
        mime = "image/jpeg"
    elif ext == "webp":
        mime = "image/webp"
    b64 = base64.b64encode(img_bytes).decode("ascii")
    return f"data:{mime};base64,{b64}"


# A provider charges input tokens by pixel area, and the free Groq tier caps
# INPUT TOKENS PER MINUTE (7000 at the time of writing) — roughly three or
# four full-size photos. A registration form validates four uploads in a row,
# so phone-camera originals exhausted the minute budget and every later upload
# came back 429. Downscaling the long edge keeps ID numbers and faces legible
# while cutting the per-image cost several-fold.
MAX_IMAGE_EDGE = int(os.getenv("VISION_MAX_IMAGE_EDGE", "1400"))


def _downscale_for_vision(img_bytes: bytes):
    """(bytes, ext) shrunk to MAX_IMAGE_EDGE, or the original if that fails.

    Never raises: if Pillow cannot read it, the provider gets the original and
    decides. Downscaling is an efficiency measure, not a validation step.
    """
    if MAX_IMAGE_EDGE <= 0:
        return img_bytes, None
    try:
        from PIL import Image
        with Image.open(io.BytesIO(img_bytes)) as im:
            if max(im.size) <= MAX_IMAGE_EDGE:
                return img_bytes, None
            im = im.convert("RGB")
            im.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE), Image.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=88)
            return buf.getvalue(), "jpg"
    except Exception:
        return img_bytes, None


def _vision_payload(model: str, prompt: str, data_url: str, json_mode: bool) -> dict:
    """The request body. Built in ONE place so both providers demonstrably
    receive the same prompt and the same image; only `response_format` differs,
    because LM Studio's OpenAI shim does not accept json_object for every
    local model."""
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
        "temperature": 0,
        "max_tokens": 500,
        "response_format": {"type": "json_object"} if json_mode else {"type": "text"},
    }
    return payload


def _retry_after_seconds(resp, fallback=None):
    """Seconds the provider asked us to wait, clamped to something sane."""
    raw = (resp.headers.get("retry-after") or "").strip() if resp is not None else ""
    try:
        secs = float(raw)
    except (TypeError, ValueError):
        secs = fallback if fallback is not None else 0.0
    return max(0.0, min(secs, 60.0))


def _post_vision(url: str, payload: dict, headers: dict, timeout: float,
                 provider: str, attempts: int = 2) -> dict:
    """POST to an OpenAI-compatible vision endpoint and parse the JSON reply.

    Raises ProviderError with a specific outcome. A 429 is retried once inside
    the window the provider itself asked for, because the cause is usually a
    burst from the four uploads on one registration form rather than sustained
    overuse. If it is still throttled, the caller is TOLD it was throttled —
    the wait is never extended into a silent hang, and the throttle is never
    laundered into a document rejection.
    """
    last_retry_after = None
    for attempt in range(attempts):
        try:
            r = _http.post(url, json=payload, headers=headers, timeout=timeout)
        except _http.exceptions.Timeout as e:
            raise ProviderError(OUTCOME_TIMEOUT, f"{type(e).__name__}") from e
        except _http.exceptions.RequestException as e:
            raise ProviderError(OUTCOME_UNAVAILABLE, f"{type(e).__name__}") from e

        if r.status_code == 429:
            last_retry_after = _retry_after_seconds(r, fallback=5.0)
            if attempt + 1 < attempts and last_retry_after <= 10.0:
                time.sleep(last_retry_after + 0.25)
                continue
            raise ProviderError(OUTCOME_RATE_LIMITED, "HTTP 429",
                                retry_after=last_retry_after)
        if r.status_code in (401, 403):
            raise ProviderError(OUTCOME_NOT_CONFIGURED, f"HTTP {r.status_code}")
        if r.status_code >= 500:
            raise ProviderError(OUTCOME_UNAVAILABLE, f"HTTP {r.status_code}")
        if r.status_code >= 400:
            # 4xx other than the above is our own request being wrong (bad
            # model name, unsupported image). Operational, not the user's
            # document — but it must be loud, not retried forever.
            raise ProviderError(OUTCOME_UNAVAILABLE, f"HTTP {r.status_code}")

        try:
            body = r.json()
            content = body["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as e:
            raise ProviderError(OUTCOME_MALFORMED,
                                f"{type(e).__name__} reading choices") from e
        try:
            return _extract_json(content)
        except (ValueError, json.JSONDecodeError) as e:
            raise ProviderError(OUTCOME_MALFORMED, f"{type(e).__name__}") from e

    raise ProviderError(OUTCOME_RATE_LIMITED, "HTTP 429",
                        retry_after=last_retry_after)


def _call_vision(prompt: str, data_url: str) -> dict:
    """Dispatch to the CONFIGURED provider. Never falls back to another one:
    silently sending a document elsewhere would be a disclosure."""
    if AI_PROVIDER == "lmstudio":
        return _call_lmstudio_vision(prompt, data_url)
    return _call_groq_vision_internal(prompt, data_url)


# Kept under the old name because other modules import it.
_call_groq_vision = _call_vision


def _call_groq_vision_internal(prompt: str, data_url: str) -> dict:
    if not GROQ_API_KEY:
        raise ProviderError(OUTCOME_NOT_CONFIGURED, "GROQ_API_KEY missing")
    return _post_vision(
        GROQ_URL,
        _vision_payload(GROQ_VISION_MODEL, prompt, data_url, json_mode=True),
        {"Authorization": f"Bearer {GROQ_API_KEY}"},
        timeout=float(os.getenv("GROQ_VISION_TIMEOUT", "45")),
        provider="groq",
    )


def _call_lmstudio_vision(prompt: str, data_url: str) -> dict:
    return _post_vision(
        f"{LMSTUDIO_URL}/v1/chat/completions",
        # Same prompt, same image. json_mode off only because LM Studio's shim
        # rejects json_object for some local builds.
        _vision_payload(LMSTUDIO_MODEL, prompt, data_url, json_mode=False),
        {},
        timeout=float(os.getenv("LM_STUDIO_TIMEOUT", "120")),
        provider="lmstudio",
    )


def _extract_json(text: str) -> dict:
    text = (text or "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            # The response body is NOT included: it can echo document content.
            raise ValueError("No JSON object in provider response")
        return json.loads(m.group(0))


def _coerce_valid(raw):
    """The model's `valid` field as a real bool, or None if it is not one.

    Deliberately strict. `{"valid": "false"}` is a STRING, and a string is
    truthy in Python, so the previous `result.get("valid")` test accepted
    every document whose model reply used quoted booleans. Anything that is
    not a genuine bool is treated as no answer at all, which surfaces as
    OUTCOME_MALFORMED rather than as an approval.
    """
    return raw if isinstance(raw, bool) else None


def _service_result(outcome: str, reason: str, corr: str, retry_after=None) -> dict:
    """An operational (non-verdict) result.

    `valid` is None, never False. A caller that treats falsy as "rejected"
    would tell the applicant their document failed because our provider was
    busy, and a caller that treats it as truthy would let an unchecked
    document through. Both are wrong, so there is no boolean to misread.
    """
    out = {"outcome": outcome, "valid": None, "reason": reason,
           "details": {}, "retryable": True, "correlation_id": corr}
    if retry_after is not None:
        out["retry_after"] = round(float(retry_after), 1)
    return out


def _log_outcome(corr, doc_type, outcome, detail=""):
    """Sanitized diagnostics: provider, model, document TYPE, outcome, id.

    Never the image, never extracted identity fields, never the provider's
    raw body (it can quote document text), never the API key.
    """
    model = LMSTUDIO_MODEL if AI_PROVIDER == "lmstudio" else GROQ_VISION_MODEL
    suffix = f" detail={detail}" if detail else ""
    print(f"[upload_validation] id={corr} provider={AI_PROVIDER} "
          f"model={model} type={doc_type} outcome={outcome}{suffix}")


def validate_file(file_bytes: bytes, filename: str, doc_type: str) -> dict:
    """Validate one upload. Returns the outcome dict described at module top.

    Never raises for provider problems — it returns an operational outcome so
    every caller handles failure the same way.
    """
    corr = uuid.uuid4().hex[:12]
    if DEV_SKIP_VALIDATION:
        _log_outcome(corr, doc_type, "dev_skipped")
        return {"outcome": OUTCOME_VALID, "valid": True,
                "reason": "[DEV] validation skipped", "details": {},
                "_dev_skipped": True, "correlation_id": corr}
    if doc_type not in PROMPTS:
        return {"outcome": OUTCOME_INVALID_FILE, "valid": False,
                "reason": "Unknown document type.", "details": {},
                "correlation_id": corr}

    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if not file_bytes:
        return {"outcome": OUTCOME_INVALID_FILE, "valid": False,
                "reason": "That file is empty. Please choose the file again.",
                "details": {}, "correlation_id": corr}

    if ext == "pdf":
        img_bytes = _pdf_first_page_png(file_bytes)
        if not img_bytes:
            return {"outcome": OUTCOME_INVALID_FILE, "valid": False,
                    "reason": ("Could not read this PDF. Please upload a clearer "
                               "scan or convert it to JPG/PNG."),
                    "details": {}, "correlation_id": corr}
        ext_for_mime = "png"
    elif ext in SUPPORTED_IMG_EXT:
        img_bytes = file_bytes
        ext_for_mime = ext
    else:
        return {"outcome": OUTCOME_INVALID_FILE, "valid": False,
                "reason": ("Unsupported file format. Please upload a PDF, PNG, "
                           "JPG, JPEG, or WEBP file."),
                "details": {}, "correlation_id": corr}

    shrunk, new_ext = _downscale_for_vision(img_bytes)
    data_url = _image_to_data_url(shrunk, new_ext or ext_for_mime)

    try:
        result = _call_vision(PROMPTS[doc_type], data_url)
    except ProviderError as e:
        _log_outcome(corr, doc_type, e.outcome, e.detail)
        messages = {
            OUTCOME_RATE_LIMITED: ("The document checker is busy right now. "
                                   "Your file is still selected — try again in "
                                   "a moment."),
            OUTCOME_TIMEOUT: ("The document checker did not respond in time. "
                              "Your file is still selected — please try again."),
            OUTCOME_NOT_CONFIGURED: ("Document checking is not configured on "
                                     "this server. Please contact support."),
            OUTCOME_MALFORMED: ("The document checker returned an unreadable "
                                "answer. Please try again."),
        }
        return _service_result(
            e.outcome,
            messages.get(e.outcome,
                         "Could not validate right now. Your file is still "
                         "selected — please try again."),
            corr, retry_after=e.retry_after)
    except Exception as e:                                       # noqa: BLE001
        # Anything unforeseen is still operational, never a verdict.
        _log_outcome(corr, doc_type, OUTCOME_UNAVAILABLE, type(e).__name__)
        return _service_result(OUTCOME_UNAVAILABLE,
                               "Could not validate right now. Your file is "
                               "still selected — please try again.", corr)

    if not isinstance(result, dict):
        _log_outcome(corr, doc_type, OUTCOME_MALFORMED, "not an object")
        return _service_result(OUTCOME_MALFORMED,
                               "The document checker returned an unreadable "
                               "answer. Please try again.", corr)

    verdict = _coerce_valid(result.get("valid"))
    if verdict is None:
        # Missing, null, or a quoted "true"/"false". Not an approval and not a
        # rejection: we genuinely do not know what the model decided.
        _log_outcome(corr, doc_type, OUTCOME_MALFORMED,
                     f"valid={type(result.get('valid')).__name__}")
        return _service_result(OUTCOME_MALFORMED,
                               "The document checker returned an unclear "
                               "answer. Please try again.", corr)

    result["valid"] = verdict
    result.setdefault("reason", "")
    result.setdefault("details", {})
    result["correlation_id"] = corr

    # Stage 2: deeper format validation for IDs based on extracted fields.
    # This can only turn an accept into a reject, never the reverse.
    if doc_type == "valid_id":
        result = _format_validate_id(result)
        result["valid"] = bool(result.get("valid"))

    result["outcome"] = OUTCOME_VALID if result["valid"] else OUTCOME_REJECTED
    _log_outcome(corr, doc_type, result["outcome"])
    return result


def face_match(selfie_bytes: bytes, selfie_filename: str) -> dict:
    """Accept the selfie+ID photo after basic format/size checks and save it.

    No AI quality gate here — low-quality webcams produced enough blurry/
    dim false rejections that it did more harm than good. Liveness is
    handled client-side (center-and-hold capture); identity is confirmed
    by an admin afterward (admin_approve_selfie / admin_reject_selfie).
    """
    from flask import current_app
    import uuid

    ext = selfie_filename.rsplit(".", 1)[-1].lower() if "." in selfie_filename else ""

    if ext == "pdf":
        return {"valid": False, "reason": "Please upload a photo (PNG, JPG, JPEG, WEBP), not a PDF."}
    if ext not in SUPPORTED_IMG_EXT:
        return {"valid": False, "reason": "Unsupported file format. Please upload PNG, JPG, JPEG, or WEBP."}

    if len(selfie_bytes) > MAX_FILE_BYTES:
        return {"valid": False, "reason": "File is too large (max 10 MB)."}

    if len(selfie_bytes) == 0:
        return {"valid": False, "reason": "File is empty."}

    try:
        saved_filename = f"selfie_{uuid.uuid4().hex}.{ext}"
        upload_path = os.path.join(current_app.config["UPLOAD_FOLDER"], saved_filename)
        with open(upload_path, "wb") as f:
            f.write(selfie_bytes)
        # The registration form posts this name back as a plain string, so
        # record it against the session — that is what lets registration.py
        # tell "my selfie" from "a filename someone typed in".
        from utils import remember_upload
        remember_upload(saved_filename, "selfie_with_id")
    except Exception as e:
        return {"valid": False, "reason": f"Error saving photo: {str(e)}"}

    return {"valid": True, "filename": saved_filename,
            "reason": "Photo uploaded. An admin will verify your identity."}


@validation_bp.route("/api/face-match", methods=["POST"])
def api_face_match():
    selfie_f = request.files.get("selfie")
    if not selfie_f or not selfie_f.filename:
        return jsonify(valid=False, reason="No selfie uploaded."), 400

    selfie_data = selfie_f.read(MAX_FILE_BYTES + 1)
    result = face_match(selfie_data, selfie_f.filename)
    return jsonify(result), (200 if result.get("valid") else 400)


@validation_bp.route("/api/validate-upload", methods=["POST"])
def validate_upload():
    """Validate one upload.

    The HTTP status carries the same information as `outcome`, so the browser
    can tell a verdict (200) from an operational failure (4xx/5xx) without
    parsing prose. Previously every result was 200 and the only signal was a
    `valid:false` that a rate limit and a forged ID shared.
    """
    f = request.files.get("file")
    doc_type = (request.form.get("type") or "").strip()
    if not f or not f.filename:
        return jsonify(outcome=OUTCOME_INVALID_FILE, valid=False,
                       reason="No file uploaded."), 400
    if doc_type not in PROMPTS:
        return jsonify(outcome=OUTCOME_INVALID_FILE, valid=False,
                       reason="Unknown document type."), 400

    data = f.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        return jsonify(outcome=OUTCOME_INVALID_FILE, valid=False,
                       reason="File is too large (max 10 MB)."), 413

    result = validate_file(data, f.filename, doc_type)
    status = OUTCOME_HTTP.get(result.get("outcome"), 200)
    resp = jsonify(result)
    resp.status_code = status
    if result.get("retry_after") is not None:
        resp.headers["Retry-After"] = str(int(result["retry_after"]) or 1)
    return resp
