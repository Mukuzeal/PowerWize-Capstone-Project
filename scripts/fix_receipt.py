"""
Run once to retroactively process the blockchain receipt for a payment
that already succeeded but whose blockchain step was skipped.

Usage:
    python fix_receipt.py pi_sT7CbDsxFTM3ohkS8ycQsxUx
"""
import sys
from dotenv import load_dotenv
load_dotenv()

from db import get_db, save_blockchain_receipt
from blockchain import generate_receipt_id, create_receipt_hash, store_hash_on_chain
from qr_gen import generate_receipt_qr
from datetime import datetime

def fix(paymongo_id):
    conn = get_db()
    cur  = conn.cursor(dictionary=True)
    cur.execute(
        "SELECT id, user_id, receipt_id, tx_hash FROM payments WHERE paymongo_id = %s LIMIT 1",
        (paymongo_id,)
    )
    row = cur.fetchone()
    cur.close(); conn.close()

    if not row:
        print(f"[ERROR] No payment found for {paymongo_id}")
        return

    if row.get("tx_hash"):
        print(f"[INFO] Blockchain already stored. tx_hash={row['tx_hash']}")
        return

    user_id = row["user_id"]
    print(f"[INFO] Processing payment for user_id={user_id} ...")

    receipt_id   = generate_receipt_id()
    receipt_data = {
        "receipt_id":  receipt_id,
        "user_id":     user_id,
        "paymongo_id": paymongo_id,
        "timestamp":   datetime.now().isoformat(),
    }
    receipt_hash = create_receipt_hash(receipt_data)
    print(f"[INFO] Receipt ID  : {receipt_id}")
    print(f"[INFO] Receipt hash: {receipt_hash}")
    print(f"[INFO] Sending to Polygon Amoy — this may take 30–60 seconds ...")

    chain_result = store_hash_on_chain(receipt_hash)
    print(f"[OK]   tx_hash     : {chain_result['tx_hash']}")
    print(f"[OK]   Block       : #{chain_result['block_number']}")
    print(f"[OK]   Explorer    : {chain_result['explorer_url']}")

    qr_path = generate_receipt_qr(receipt_id, chain_result["tx_hash"])
    print(f"[OK]   QR saved    : {qr_path}")

    save_blockchain_receipt(paymongo_id, receipt_id, receipt_hash,
                            chain_result["tx_hash"], qr_path)
    print("[DONE] Payment success page will now show the QR and blockchain link.")

if __name__ == "__main__":
    pid = sys.argv[1] if len(sys.argv) > 1 else "pi_sT7CbDsxFTM3ohkS8ycQsxUx"
    fix(pid)
