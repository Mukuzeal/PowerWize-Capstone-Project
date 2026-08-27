import os
import json
import secrets
from datetime import datetime
from web3 import Web3
from dotenv import load_dotenv

load_dotenv()


def _w3():
    network = os.getenv("POLYGON_NETWORK", "amoy")
    rpc = os.getenv("AMOY_RPC_URL") if network == "amoy" else os.getenv("MAINNET_RPC_URL")
    w3 = Web3(Web3.HTTPProvider(rpc))
    # Polygon is proof-of-authority, so its blocks carry a 105-byte extraData
    # field where web3 expects 32. Without this middleware every block-level
    # read (timestamps, confirmations) raises ExtraDataLengthError.
    try:
        from web3.middleware import ExtraDataToPOAMiddleware
        w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    except ImportError:          # web3 < 7
        from web3.middleware import geth_poa_middleware
        w3.middleware_onion.inject(geth_poa_middleware, layer=0)
    return w3


def _chain_id():
    network = os.getenv("POLYGON_NETWORK", "amoy")
    return int(os.getenv("CHAIN_ID_AMOY", "80002")) if network == "amoy" else int(os.getenv("CHAIN_ID_MAINNET", "137"))


def _explorer_url(tx_hash):
    network = os.getenv("POLYGON_NETWORK", "amoy")
    base = "https://amoy.polygonscan.com" if network == "amoy" else "https://polygonscan.com"
    return f"{base}/tx/{tx_hash}"


def generate_receipt_id():
    date = datetime.now().strftime("%Y%m%d")
    rand = secrets.token_hex(4).upper()
    return f"RCP-{date}-{rand}"


def create_receipt_hash(receipt_data: dict) -> str:
    w3 = _w3()
    data_str = json.dumps(receipt_data, sort_keys=True)
    return w3.keccak(text=data_str).hex()


def store_hash_on_chain(receipt_hash: str) -> dict:
    w3 = _w3()
    private_key = os.getenv("SYSTEM_WALLET_PRIVATE_KEY")
    wallet      = os.getenv("SYSTEM_WALLET_ADDRESS")
    chain_id    = _chain_id()

    data_bytes = Web3.to_bytes(hexstr=receipt_hash)
    nonce      = w3.eth.get_transaction_count(wallet)

    tx = {
        "nonce":    nonce,
        "to":       wallet,
        "value":    0,
        "gas":      50000,
        "gasPrice": w3.eth.gas_price,
        "chainId":  chain_id,
        "data":     data_bytes,
    }

    signed   = w3.eth.account.sign_transaction(tx, private_key)
    raw_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    tx_hex   = raw_hash.hex()
    if not tx_hex.startswith("0x"):
        tx_hex = "0x" + tx_hex

    receipt = w3.eth.wait_for_transaction_receipt(raw_hash, timeout=120)

    return {
        "tx_hash":      tx_hex,
        "block_number": receipt["blockNumber"],
        "confirmed":    receipt["status"] == 1,
        "explorer_url": _explorer_url(tx_hex),
    }


def verify_hash_on_chain(tx_hash: str, expected_hash: str) -> dict:
    """Legacy check: does the chain hold this exact hash?

    Kept for anchor_version 1 records. It proves a hash was anchored, but not
    that the hash describes the record you are looking at - the caller supplies
    the expected hash from the database, so editing the record does not change
    the answer. verify_anchor() below is the real check.
    """
    try:
        w3  = _w3()
        tx  = w3.eth.get_transaction(tx_hash)
        if not tx:
            return {"verified": False, "reason": "Transaction not found on blockchain."}

        stored_hash = _hex(tx["input"])
        match = stored_hash.lower() == _strip0x(expected_hash).lower()

        return {
            "verified":     match,
            "stored_hash":  stored_hash,
            "block_number": tx["blockNumber"],
            "explorer_url": _explorer_url(tx_hash),
            "reason":       "Payment is in Blockchain" if match else "Hash mismatch — payment not verified.",
        }
    except Exception as e:
        return {"verified": False, "reason": f"Blockchain query failed: {str(e)}"}


# ---------------------------------------------------------------------------
# Anchoring v2 - tamper-evident records
#
# v1 stored a hash on-chain and, at verification time, compared it against a
# hash column in the same database row. Both sides of that comparison came from
# the database, so it could only ever agree with itself: changing a payment's
# amount left the stored hash untouched and the receipt still read "verified".
#
# v2 fingerprints the record's material facts and RECOMPUTES that fingerprint
# from the live row at verification time. Any edit to a covered field changes
# the recomputed hash, which then no longer matches the chain. Every covered
# field must therefore be persisted - nothing derived at write time only.
# ---------------------------------------------------------------------------

ANCHOR_VERSION = 2

# The facts each record type commits to. Adding a field is a version bump:
# older anchors were computed without it and would stop matching.
ANCHOR_FIELDS = {
    "payment":     ("receipt_id", "user_id", "paymongo_id", "amount_php", "status"),
    "certificate": ("cert_id", "user_id", "issued_at", "expires_at"),
}


def _strip0x(s):
    s = str(s)
    return s[2:] if s.startswith(("0x", "0X")) else s


def _hex(value):
    """HexBytes.hex() gained a 0x prefix in web3 v7; normalise to bare hex."""
    h = value.hex() if hasattr(value, "hex") else str(value)
    return _strip0x(h)


def _norm(value):
    """Stable text for a field, so the same record always hashes the same."""
    from decimal import Decimal
    from datetime import date as _date, datetime as _dt

    if value is None:
        return ""
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    if isinstance(value, float):
        return f"{Decimal(str(value)):.2f}"
    if isinstance(value, (_dt, _date)):
        return value.isoformat()
    return str(value)


def canonical_payload(kind: str, record: dict) -> str:
    """Deterministic text for a record: v2|kind|field=value|... in fixed order."""
    if kind not in ANCHOR_FIELDS:
        raise ValueError(f"unknown anchor kind: {kind}")
    parts = [f"v{ANCHOR_VERSION}", kind]
    for f in ANCHOR_FIELDS[kind]:
        parts.append(f"{f}={_norm(record.get(f))}")
    return "|".join(parts)


def compute_anchor(kind: str, record: dict) -> str:
    import hashlib
    return hashlib.sha256(canonical_payload(kind, record).encode()).hexdigest()


def verify_anchor(tx_hash: str, kind: str, record: dict) -> dict:
    """Recompute the record's fingerprint and check it against the chain.

    Reports the four things that have to hold for an anchor to mean anything:
    the transaction exists, it succeeded, we are the ones who sent it, and the
    payload matches what this record hashes to right now.
    """
    out = {
        "verified": False, "version": ANCHOR_VERSION, "kind": kind,
        "expected_hash": None, "stored_hash": None, "block_number": None,
        "confirmations": None, "timestamp": None, "sender_ok": None,
        "explorer_url": _explorer_url(tx_hash) if tx_hash else None,
        "reason": "",
    }
    try:
        expected = compute_anchor(kind, record)
        out["expected_hash"] = expected

        w3 = _w3()
        try:
            tx = w3.eth.get_transaction(tx_hash)
        except Exception:
            tx = None
        if not tx:
            out["reason"] = "No such transaction on Polygon — this record was never anchored."
            return out

        if tx["blockNumber"] is None:
            out["reason"] = "Transaction is still pending — not yet confirmed."
            return out

        receipt = w3.eth.get_transaction_receipt(tx_hash)
        if receipt["status"] != 1:
            out["reason"] = "The anchoring transaction reverted on-chain."
            return out

        # Anyone can put arbitrary bytes in a transaction. Unless the sender is
        # our wallet, a matching payload proves nothing about who issued it.
        wallet = (os.getenv("SYSTEM_WALLET_ADDRESS") or "").lower()
        sender = str(tx["from"]).lower()
        out["sender_ok"] = (sender == wallet)

        stored = _hex(tx["input"])
        out["stored_hash"] = stored
        out["block_number"] = tx["blockNumber"]
        out["confirmations"] = max(0, w3.eth.block_number - tx["blockNumber"])
        try:
            out["timestamp"] = w3.eth.get_block(tx["blockNumber"])["timestamp"]
        except Exception:
            pass

        if stored.lower() != expected.lower():
            out["reason"] = ("Record does not match its blockchain anchor — it has been "
                             "altered since it was issued.")
            return out
        if not out["sender_ok"]:
            out["reason"] = f"Anchored by an unrecognised wallet ({sender})."
            return out

        out["verified"] = True
        out["reason"] = "Verified on Polygon — the record is unchanged since issue."
        return out

    except Exception as e:
        out["reason"] = f"Blockchain query failed: {type(e).__name__}: {e}"
        return out
