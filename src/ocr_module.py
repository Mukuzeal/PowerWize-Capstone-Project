"""
OCR module for Philippine electric bill extraction.
Requires pytesseract + Tesseract binary (optional).
Falls back gracefully to None so the form still works without it.
"""
import os
import re


def extract_bill_data(file_path: str) -> dict | None:
    """Return {'kwh': float|None, 'amount': float|None} or None on any failure."""
    try:
        from PIL import Image
        import pytesseract
    except ImportError:
        return None

    try:
        ext = os.path.splitext(file_path)[1].lower()
        if ext == ".pdf":
            text = _pdf_to_text(file_path)
        else:
            img  = Image.open(file_path)
            text = pytesseract.image_to_string(img)
        return _parse(text) if text else None
    except Exception:
        return None


def _pdf_to_text(path: str) -> str:
    try:
        from pdf2image import convert_from_path
        import pytesseract
        pages = convert_from_path(path, first_page=1, last_page=1)
        return pytesseract.image_to_string(pages[0]) if pages else ""
    except Exception:
        return ""


def _parse(text: str) -> dict | None:
    kwh = _find_kwh(text)
    amount = _find_amount(text)
    if kwh or amount:
        return {"kwh": kwh, "amount": amount}
    return None


def _find_kwh(text: str) -> float | None:
    patterns = [
        r"(\d[\d,]+)\s*kWh",
        r"kWh\s*[:\-=]?\s*(\d[\d,]+)",
        r"consumption[:\s]+(\d[\d,]+)",
        r"kwh\s+used[:\s]+(\d[\d,]+)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            val = float(m.group(1).replace(",", ""))
            if 10 <= val <= 100_000:   # sanity range
                return val
    return None


def _find_amount(text: str) -> float | None:
    patterns = [
        r"(?:total\s+amount\s+due|amount\s+due|total\s+bill)[:\s₱PHP]*([0-9,]+\.?\d*)",
        r"(?:current\s+charges)[:\s₱PHP]*([0-9,]+\.?\d*)",
        r"₱\s*([0-9,]+\.\d{2})",
        r"PHP\s+([0-9,]+\.\d{2})",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            val = float(m.group(1).replace(",", ""))
            if 100 <= val <= 1_000_000:  # sanity range
                return val
    return None
