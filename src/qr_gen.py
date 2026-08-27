import os
import json
import qrcode

# static/ sits at the project root, one level above this package. Resolving the
# output directory from __file__ rather than the working directory keeps the
# images in one place: launching the app from inside src/ used to create a
# second, half-populated src/static/ tree whose files no route ever served.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _qr_paths(subfolder: str, filename: str):
    """Where to write the image, and the URL path to hand back.

    Templates render the returned value as `/{{ path }}`, so it stays a
    relative, forward-slashed web path regardless of platform - os.path.join
    would produce backslashes on Windows.
    """
    folder = os.path.join(_PROJECT_ROOT, "static", subfolder)
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, filename), f"static/{subfolder}/{filename}"


def generate_receipt_qr(receipt_id: str, tx_hash: str) -> str:
    payload = json.dumps({"receipt_id": receipt_id, "tx_hash": tx_hash})

    qr = qrcode.QRCode(version=1, box_size=8, border=4,
                       error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0D3B27", back_color="white")

    disk_path, url_path = _qr_paths("receipts", f"qr_{receipt_id}.png")
    img.save(disk_path)
    return url_path


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

    disk_path, url_path = _qr_paths("certificates", f"qr_{cert_id}.png")
    img.save(disk_path)
    return url_path
