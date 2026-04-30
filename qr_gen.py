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
