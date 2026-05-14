import os
import json
import qrcode


def generate_receipt_qr(receipt_id: str, tx_hash: str) -> str:
    payload = json.dumps({"receipt_id": receipt_id, "tx_hash": tx_hash})

    qr = qrcode.QRCode(version=1, box_size=8, border=4,
                       error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0D3B27", back_color="white")

    folder = os.path.join("static", "receipts")
    os.makedirs(folder, exist_ok=True)
    filename = f"qr_{receipt_id}.png"
    path = os.path.join(folder, filename)
    img.save(path)
    return path


def generate_certificate_qr(cert_id: str, tx_hash: str = None) -> str:
    if tx_hash:
        # Link to blockchain transaction
        verify_url = f"https://amoy.polygonscan.com/tx/{tx_hash}"
        payload = json.dumps({"cert_id": cert_id, "tx_hash": tx_hash, "verify_url": verify_url})
    else:
        # Fallback to local verification
        payload = json.dumps({"cert_id": cert_id})

    qr = qrcode.QRCode(version=1, box_size=8, border=4,
                       error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0D5E3B", back_color="white")

    folder = os.path.join("static", "certificates")
    os.makedirs(folder, exist_ok=True)
    filename = f"qr_{cert_id}.png"
    path = os.path.join(folder, filename)
    img.save(path)
    return path
