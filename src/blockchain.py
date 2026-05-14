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
    return Web3(Web3.HTTPProvider(rpc))


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
    try:
        w3  = _w3()
        tx  = w3.eth.get_transaction(tx_hash)
        if not tx:
            return {"verified": False, "reason": "Transaction not found on blockchain."}

        stored_hash = tx["input"].hex()
        match = stored_hash.lower() == expected_hash.lower()

        return {
            "verified":     match,
            "stored_hash":  stored_hash,
            "block_number": tx["blockNumber"],
            "explorer_url": _explorer_url(tx_hash),
            "reason":       "Payment is in Blockchain" if match else "Hash mismatch — payment not verified.",
        }
    except Exception as e:
        return {"verified": False, "reason": f"Blockchain query failed: {str(e)}"}
