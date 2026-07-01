"""
OCR module for Philippine electric bill extraction.
Primary: Groq vision API (same key used for upload validation).
Fallback: pytesseract + Tesseract binary (if installed).
"""
import os
import re
import io
import json
import base64


GROQ_API_KEY    = os.getenv("GROQ_API_KEY", "")
GROQ_VISION_MODEL = os.getenv("GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
GROQ_URL        = "https://api.groq.com/openai/v1/chat/completions"

_BILL_PROMPT = (
    "You are reading a Philippine electric bill photo or scan. "
    "Extract ONLY these two values:\n"
    "1. kwh: the actual electricity consumption for this billing period in kWh (look for "
    "'Actual Consumption', 'kWh Used', 'Total kWh', or the consumption figure near the kWh label).\n"
    "2. amount: the total amount due in PHP (look for 'Please Pay', 'Total Amount Due', "
    "'Amount Due', or the largest peso amount shown).\n\n"
    "Return ONLY strict JSON with no extra text: "
    "{\"kwh\": <number or null>, \"amount\": <number or null>}\n"
    "Use null if a value cannot be read clearly. Do NOT include units — just the numbers."
)


def extract_bill_data(file_path: str) -> dict | None:
    """Return {'kwh': float|None, 'amount': float|None} or None on failure."""
    ext = os.path.splitext(file_path)[1].lower()

    try:
        img_bytes, mime = _load_image(file_path, ext)
    except Exception:
        return None

    if not img_bytes:
        return None

    # Primary: Groq vision
    if GROQ_API_KEY:
        result = _groq_extract(img_bytes, mime)
        if result:
            return result

    # Fallback: pytesseract
    return _tesseract_extract(file_path, ext)


def _load_image(file_path: str, ext: str) -> tuple[bytes | None, str]:
    """Return (image_bytes, mime_type). Converts PDF first page to PNG if needed."""
    if ext == ".pdf":
        png = _pdf_to_png(file_path)
        return png, "image/png"
    with open(file_path, "rb") as f:
        data = f.read()
    mime = "image/jpeg" if ext in (".jpg", ".jpeg") else \
           "image/webp"  if ext == ".webp" else "image/png"
    return data, mime


def _pdf_to_png(path: str) -> bytes | None:
    try:
        import fitz
        doc = fitz.open(path)
        if doc.page_count == 0:
            doc.close()
            return None
        pix = doc.load_page(0).get_pixmap(dpi=150)
        png = pix.tobytes("png")
        doc.close()
        return png
    except ImportError:
        pass
    except Exception:
        pass

    try:
        from pdf2image import convert_from_path
        pages = convert_from_path(path, first_page=1, last_page=1, dpi=150)
        if not pages:
            return None
        buf = io.BytesIO()
        pages[0].save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return None


def _groq_extract(img_bytes: bytes, mime: str) -> dict | None:
    try:
        import requests as _http
        b64 = base64.b64encode(img_bytes).decode("ascii")
        data_url = f"data:{mime};base64,{b64}"

        payload = {
            "model": GROQ_VISION_MODEL,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text",      "text": _BILL_PROMPT},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }],
            "temperature": 0,
            "max_tokens": 100,
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
        data = _parse_json(content)
        if not data:
            return None

        kwh    = _to_float(data.get("kwh"))
        amount = _to_float(data.get("amount"))

        # Sanity checks
        if kwh    is not None and not (10 <= kwh    <= 100_000): kwh    = None
        if amount is not None and not (100 <= amount <= 1_000_000): amount = None

        if kwh or amount:
            return {"kwh": kwh, "amount": amount}
    except Exception as e:
        print(f"[OCR Groq error] {type(e).__name__}: {e}")
    return None


def _tesseract_extract(file_path: str, ext: str) -> dict | None:
    try:
        from PIL import Image
        import pytesseract
    except ImportError:
        return None
    try:
        if ext == ".pdf":
            text = _pdf_tesseract(file_path)
        else:
            text = pytesseract.image_to_string(Image.open(file_path))
        return _regex_parse(text) if text else None
    except Exception:
        return None


def _pdf_tesseract(path: str) -> str:
    try:
        from pdf2image import convert_from_path
        import pytesseract
        pages = convert_from_path(path, first_page=1, last_page=1)
        return pytesseract.image_to_string(pages[0]) if pages else ""
    except Exception:
        return ""


def _regex_parse(text: str) -> dict | None:
    kwh    = _find_kwh(text)
    amount = _find_amount(text)
    if kwh or amount:
        return {"kwh": kwh, "amount": amount}
    return None


def _find_kwh(text: str) -> float | None:
    patterns = [
        r"actual\s+consumption[:\s]+(\d[\d,]+)",
        r"(\d[\d,]+)\s*kWh",
        r"kWh\s*[:\-=]?\s*(\d[\d,]+)",
        r"consumption[:\s]+(\d[\d,]+)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            val = float(m.group(1).replace(",", ""))
            if 10 <= val <= 100_000:
                return val
    return None


def _find_amount(text: str) -> float | None:
    patterns = [
        r"(?:total\s+amount\s+due|please\s+pay|amount\s+due|total\s+bill)[:\s₱PHP]*([0-9,]+\.\d{2})",
        r"₱\s*([0-9,]+\.\d{2})",
        r"PHP\s+([0-9,]+\.\d{2})",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            val = float(m.group(1).replace(",", ""))
            if 100 <= val <= 1_000_000:
                return val
    return None


def _parse_json(text: str) -> dict | None:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
    return None


def _to_float(val) -> float | None:
    if val is None:
        return None
    try:
        return float(str(val).replace(",", ""))
    except (ValueError, TypeError):
        return None
