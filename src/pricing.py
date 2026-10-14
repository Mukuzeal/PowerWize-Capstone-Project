"""Published program prices — the one place a training fee is defined.

Lifted out of payment_bp so the corporate bulk-payment screen can quote the
same list price a trainee sees on /payment instead of carrying its own copy of
the numbers. Nothing here reads the session or the database: given a
registration's form_type and training_type it returns the fee breakdown.
"""

VAT_RATE = 0.12


def calculate_fee(form_type, training_type):
    ft = (form_type or "").lower()
    tt = (training_type or "").lower()

    if ft in ("cea_renewal", "cem_renewal"):
        base = 10000 if "face" in tt else 7500
        vat  = round(base * VAT_RATE, 2)
        mode = "Face-to-Face" if "face" in tt else "Online"
        return {"base": base, "vat": vat, "total": base + vat,
                "label": f"Recertification · {mode}", "has_vat": True}

    if ft in ("training", "cea_training"):
        if "hybrid" in tt:
            return {"base": 19500, "vat": 0, "total": 19500,
                    "label": "Training · Hybrid (5 days Online + 2 days F2F)", "has_vat": False}
        if "online" in tt and "self" not in tt:
            return {"base": 18000, "vat": 0, "total": 18000,
                    "label": "Training · Online (7 days, 56 hours)", "has_vat": False}
        if "self" in tt:
            mode = "Face-to-Face" if "face" in tt else "Online"
            return {"base": 19500, "vat": 0, "total": 19500,
                    "label": f"Training · Self-paced ({mode})", "has_vat": False}

    if ft in ("gemp_lgu", "gemp_oge"):
        base = 10000 if "face" in tt else 7500
        vat  = round(base * VAT_RATE, 2)
        mode = "Face-to-Face" if "face" in tt else "Online via Zoom"
        prog = "GEMP Training (LGU)" if ft == "gemp_lgu" else "GEMP Training (Gov't Entity)"
        return {"base": base, "vat": vat, "total": base + vat,
                "label": f"{prog} · {mode}", "has_vat": True}

    return None


def to_centavos(amount_php):
    """PHP -> integer centavos. Every amount handed to PayMongo goes through
    here so a float never reaches the gateway."""
    from decimal import Decimal, ROUND_HALF_UP
    return int(Decimal(str(amount_php)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) * 100)
