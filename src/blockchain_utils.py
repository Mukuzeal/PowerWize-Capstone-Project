import os
import json
import base64
from datetime import date

CONTRACT_ADDRESS = os.getenv("NFT_CONTRACT_ADDRESS", "")

_MINT_ABI = [
    {
        "inputs": [
            {"internalType": "address", "name": "to",  "type": "address"},
            {"internalType": "string",  "name": "uri", "type": "string"},
        ],
        "name": "mint",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "from",    "type": "address"},
            {"indexed": True, "name": "to",      "type": "address"},
            {"indexed": True, "name": "tokenId", "type": "uint256"},
        ],
        "name": "Transfer",
        "type": "event",
    },
]

_TRAINING_LABELS = {
    "gemp_lgu":     "GEMP Training (LGU)",
    "gemp_oge":     "GEMP Training (Gov't Entity)",
    "cea_training": "CEA Training",
    "cea_renewal":  "CEA Renewal",
    "cem_renewal":  "CEM Renewal",
    "training":     "CEM Training",
}


def _build_token_uri(cert_id, user_name, training_label, issued_str):
    metadata = {
        "name":        f"EnergyWize Certificate – {training_label}",
        "description": (
            f"Certificate of completion issued by EnergyWize Solutions Inc. "
            f"Certificate ID: {cert_id}"
        ),
        "attributes": [
            {"trait_type": "Certificate ID", "value": cert_id},
            {"trait_type": "Recipient",      "value": user_name},
            {"trait_type": "Training",       "value": training_label},
            {"trait_type": "Issued",         "value": issued_str},
            {"trait_type": "Issuer",         "value": "EnergyWize Solutions Inc."},
        ],
    }
    encoded = base64.b64encode(json.dumps(metadata).encode()).decode()
    return f"data:application/json;base64,{encoded}"


def _fetch_user_info(user_id):
    try:
        import psycopg2.extras
        from db import get_db
        conn = get_db()
        cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT u.fname, u.lname, r.training_type, r.form_type
            FROM   users u
            LEFT JOIN registrations r ON r.email = u.email
            WHERE  u.id = %s
            ORDER  BY r.submitted_at DESC
            LIMIT  1
        """, (user_id,))
        row = cur.fetchone()
        cur.close(); conn.close()
        return dict(row) if row else {}
    except Exception:
        return {}


def store_certificate_hash(cert_id: str, user_id: int) -> dict | None:
    """
    Mint an NFT certificate to the system wallet on Polygon.
    Returns {'tx_hash': str, 'token_id': str} or None on failure.
    Falls back to plain hash-on-chain if NFT_CONTRACT_ADDRESS is not set.
    """
    if CONTRACT_ADDRESS:
        return _mint_nft(cert_id, user_id)
    return _hash_fallback(cert_id, user_id)


def _mint_nft(cert_id: str, user_id: int) -> dict | None:
    try:
        from blockchain import _w3, _chain_id

        info         = _fetch_user_info(user_id)
        user_name    = f"{info.get('fname', '')} {info.get('lname', '')}".strip() or "Unknown"
        ft           = info.get("form_type") or info.get("training_type") or "training"
        training_lbl = _TRAINING_LABELS.get(ft, ft.replace("_", " ").title())
        issued_str   = date.today().strftime("%B %d, %Y")

        token_uri   = _build_token_uri(cert_id, user_name, training_lbl, issued_str)

        w3          = _w3()
        private_key = os.getenv("SYSTEM_WALLET_PRIVATE_KEY")
        wallet      = os.getenv("SYSTEM_WALLET_ADDRESS")
        contract    = w3.eth.contract(address=CONTRACT_ADDRESS, abi=_MINT_ABI)

        tx = contract.functions.mint(wallet, token_uri).build_transaction({
            "chainId":  _chain_id(),
            "gas":      300_000,
            "gasPrice": w3.eth.gas_price,
            "nonce":    w3.eth.get_transaction_count(wallet),
        })
        signed  = w3.eth.account.sign_transaction(tx, private_key)
        raw     = w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = w3.eth.wait_for_transaction_receipt(raw, timeout=120)

        token_id = None
        try:
            logs = contract.events.Transfer().process_receipt(receipt)
            if logs:
                token_id = str(logs[0]["args"]["tokenId"])
        except Exception:
            pass

        tx_hex = raw.hex()
        if not tx_hex.startswith("0x"):
            tx_hex = "0x" + tx_hex

        print(f"[NFT] Minted certificate {cert_id} → tokenId={token_id} tx={tx_hex}")
        return {"tx_hash": tx_hex, "token_id": token_id or cert_id}

    except Exception as e:
        print(f"[NFT mint error] {type(e).__name__}: {e}")
        return None


def _hash_fallback(cert_id: str, user_id: int) -> dict | None:
    """Original hash-on-chain behaviour when NFT_CONTRACT_ADDRESS is not set."""
    try:
        import hashlib
        from blockchain import store_hash_on_chain
        cert_hash = hashlib.sha256(f"{cert_id}:{user_id}".encode()).hexdigest()
        result    = store_hash_on_chain(cert_hash)
        if result:
            return {"tx_hash": result["tx_hash"], "token_id": cert_id}
    except Exception as e:
        print(f"[hash fallback error] {type(e).__name__}: {e}")
    return None
