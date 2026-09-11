"""
AI-powered upload validation.

POST /api/validate-upload (multipart):
  file: the uploaded file (image or PDF)
  type: one of photo_2x2 | valid_id | expired_doe | resume | solar_bill

Returns JSON: { valid: bool, reason: str, details: {...} }

Uses Groq's vision-capable Llama model. For PDFs the first page is rendered
to PNG via pdf2image before submission to the vision API.
"""
import os
import io
import json
import base64
import re
from flask import Blueprint, request, jsonify

import requests as _http

validation_bp = Blueprint("upload_validation", __name__)

# Reading IDs, licences and selfies is vision work, so it follows
# VISION_PROVIDER independently of whatever model is answering the chat.
# See solar_bp.py for the split; AI_PROVIDER remains the fallback.
AI_PROVIDER = os.getenv("VISION_PROVIDER", os.getenv("AI_PROVIDER", "groq")).lower()

# Groq config
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_VISION_MODEL = os.getenv("GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# LMStudio config
LMSTUDIO_URL = os.getenv("LM_STUDIO_URL", "http://localhost:1234")
LMSTUDIO_MODEL = os.getenv("LM_STUDIO_MODEL", "qwen/qwen3-vl-4b")

# Dev-only escape hatch. Set DEV_SKIP_VALIDATION=1 in .env to make every
# validation call pass without hitting Groq. NEVER set this in production.
DEV_SKIP_VALIDATION = os.getenv("DEV_SKIP_VALIDATION", "").strip() in ("1", "true", "yes")

# Prompts keyed by document type. Each must instruct the model to reply with
# strict JSON: {"valid": bool, "reason": "...", "details": {...}}.
PROMPTS = {
    "photo_2x2": (
        "You are validating a 2x2 PORTRAIT PHOTO (headshot) uploaded for a training registration. "
        "A 2x2 photo must be CROPPED to show the head and shoulders—NOT a full-body or mid-body shot.\n\n"
        "ACCEPT (valid=true) ONLY if the image is a clear HEADSHOT / PORTRAIT where:\n"
        "- The face and head are the dominant subject (taking up at least 50% of the image height).\n"
        "- You see the head, neck, and upper shoulders (similar to ID photo or LinkedIn profile photo).\n"
        "- The person is reasonably centered and clearly identifiable.\n"
        "- It is ONE real person, not a drawing, AI avatar, or composite.\n"
        "- The face is sharp enough to make out basic facial features.\n\n"
        "Casual clothing, indoor/outdoor backgrounds, smiling, accessories (glasses, hats, earrings), "
        "tilted heads, and varied lighting are all FINE.\n\n"
        "REJECT (valid=false) if ANY of these are true:\n"
        "- The image is a full-body shot, mid-body shot, or taken from far away (body/legs visible, face is small).\n"
        "- The image is a photograph or scan of an ID card, license, passport, certificate, or document.\n"
        "- It is a layout/template/composite with multiple panels, sections, or placeholder silhouettes.\n"
        "- The 'face' is a generic avatar, illustration, drawing, cartoon, emoji, or silhouette icon.\n"
        "- It contains multiple people or you can't tell whose photo it is.\n"
        "- It is severely blurred, dark, or the face is not clearly recognizable.\n"
        "- It is obviously not a photo of a person (object, scenery, screenshot of text, etc.).\n\n"
        "Reply ONLY with strict JSON: "
        "{\"valid\": true|false, \"reason\": \"short user-facing explanation\", "
        "\"details\": {\"is_real_portrait\": bool, \"single_person\": bool, \"is_headshot_crop\": bool, "
        "\"is_document_or_template\": bool}}"
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

    Tries PyMuPDF (pure Python, no system deps) first, then falls back to
    pdf2image (requires poppler binary, not always installed on Windows).
    Returns None if both fail.
    """
    # Path 1: PyMuPDF (preferred — no system deps)
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        if doc.page_count == 0:
            doc.close()
            return None
        page = doc.load_page(0)
        # render at ~150 DPI
        pix = page.get_pixmap(dpi=150)
        png = pix.tobytes("png")
        doc.close()
        return png
    except ImportError:
        pass
    except Exception as e:
        print(f"[upload_validation] PyMuPDF render failed: {type(e).__name__}: {e}")

    # Path 2: pdf2image (requires poppler)
    try:
        from pdf2image import convert_from_bytes
        pages = convert_from_bytes(file_bytes, first_page=1, last_page=1, dpi=150)
        if not pages:
            return None
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


def _call_groq_vision(prompt: str, data_url: str) -> dict:
    """Call vision API (Groq or LMStudio). Returns parsed dict or raises."""
    if AI_PROVIDER == "lmstudio":
        return _call_lmstudio_vision(prompt, data_url)
    else:
        return _call_groq_vision_internal(prompt, data_url)


def _call_groq_vision_internal(prompt: str, data_url: str) -> dict:
    """Call Groq vision API."""
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY not configured")
    payload = {
        "model": GROQ_VISION_MODEL,
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
        "response_format": {"type": "json_object"},
    }
    r = _http.post(
        GROQ_URL,
        json=payload,
        headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
        timeout=30,
    )
    r.raise_for_status()
    content = r.json()["choices"][0]["message"]["content"]
    return _extract_json(content)


def _call_lmstudio_vision(prompt: str, data_url: str) -> dict:
    """Call LMStudio vision API using Qwen3.5 VL."""
    payload = {
        "model": LMSTUDIO_MODEL,
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
        "response_format": {"type": "text"},
    }
    url = f"{LMSTUDIO_URL}/v1/chat/completions"
    try:
        r = _http.post(url, json=payload, timeout=60)
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"]
        return _extract_json(content)
    except Exception as e:
        raise RuntimeError(f"LMStudio vision error: {str(e)}")


def _extract_json(text: str) -> dict:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            raise ValueError(f"No JSON object in response: {text[:200]}")
        return json.loads(m.group(0))


def validate_file(file_bytes: bytes, filename: str, doc_type: str) -> dict:
    """Public function: also callable from registration submit handler."""
    if DEV_SKIP_VALIDATION:
        return {"valid": True, "reason": "[DEV] validation skipped", "details": {}, "_dev_skipped": True}
    if doc_type not in PROMPTS:
        return {"valid": False, "reason": f"Unknown document type: {doc_type}"}

    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext == "pdf":
        img_bytes = _pdf_first_page_png(file_bytes)
        if not img_bytes:
            return {"valid": False, "reason": "Could not read this PDF. Please upload a clearer scan or convert to JPG/PNG."}
        ext_for_mime = "png"
    elif ext in SUPPORTED_IMG_EXT:
        img_bytes = file_bytes
        ext_for_mime = ext
    else:
        return {"valid": False, "reason": "Unsupported file format. Please upload a PDF, PNG, JPG, JPEG, or WEBP file."}

    data_url = _image_to_data_url(img_bytes, ext_for_mime)
    try:
        result = _call_groq_vision(PROMPTS[doc_type], data_url)
    except Exception as e:
        return {"valid": False, "reason": f"Validation service unavailable. Please try again. ({type(e).__name__})"}

    if not isinstance(result, dict) or "valid" not in result:
        return {"valid": False, "reason": "Validation service returned an unexpected response. Please try again."}

    result.setdefault("reason", "")
    result.setdefault("details", {})

    # Stage 2: deeper format validation for IDs based on extracted fields.
    if doc_type == "valid_id":
        result = _format_validate_id(result)

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
    f = request.files.get("file")
    doc_type = (request.form.get("type") or "").strip()
    if not f or not f.filename:
        return jsonify(valid=False, reason="No file uploaded."), 400
    if doc_type not in PROMPTS:
        return jsonify(valid=False, reason="Unknown document type."), 400

    data = f.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        return jsonify(valid=False, reason="File is too large (max 10 MB)."), 413

    return jsonify(validate_file(data, f.filename, doc_type))
