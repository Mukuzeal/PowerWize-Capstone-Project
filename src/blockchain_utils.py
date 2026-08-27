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


def _build_token_uri(cert_id, user_name, training_label, issued_str, anchor=None):
    """The token's metadata, stored on-chain as a data: URI.

    Carrying the anchor as an attribute means one mint both tokenises the
    certificate and records its tamper-evident fingerprint: verification reads
    the metadata back out of the contract and compares the anchor against a
    fingerprint recomputed from the database row.
    """
    attributes = [
        {"trait_type": "Certificate ID", "value": cert_id},
        {"trait_type": "Recipient",      "value": user_name},
        {"trait_type": "Training",       "value": training_label},
        {"trait_type": "Issued",         "value": issued_str},
        {"trait_type": "Issuer",         "value": "EnergyWize Solutions Inc."},
    ]
    if anchor:
        attributes.append({"trait_type": "Anchor", "value": anchor})
    metadata = {
        "name":        f"EnergyWize Certificate – {training_label}",
        "description": (
            f"Certificate of completion issued by EnergyWize Solutions Inc. "
            f"Certificate ID: {cert_id}"
        ),
        "attributes": attributes,
    }
    encoded = base64.b64encode(json.dumps(metadata).encode()).decode()
    return f"data:application/json;base64,{encoded}"


def read_token_anchor(token_id):
    """Read a minted certificate's anchor back out of the contract.

    The point of verification is to consult the chain rather than the database,
    so this decodes the on-chain metadata instead of trusting a stored copy.
    """
    from blockchain import _w3
    w3  = _w3()
    abi = [{"inputs": [{"name": "tokenId", "type": "uint256"}], "name": "tokenURI",
            "outputs": [{"type": "string"}], "stateMutability": "view", "type": "function"}]
    c   = w3.eth.contract(address=w3.to_checksum_address(CONTRACT_ADDRESS), abi=abi)
    uri = c.functions.tokenURI(int(token_id)).call()
    if not uri.startswith("data:application/json;base64,"):
        return None, uri
    meta = json.loads(base64.b64decode(uri.split(",", 1)[1]))
    anchor = next((a.get("value") for a in meta.get("attributes", [])
                   if a.get("trait_type") == "Anchor"), None)
    return anchor, meta


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
        result = _mint_nft(cert_id, user_id)
        if result:
            return result
        # A mint can fail for reasons that have nothing to do with the
        # certificate - gas price spike, RPC blip, empty wallet. Falling back to
        # a plain hash anchor keeps the record verifiable instead of leaving it
        # with no on-chain trace at all, which is what used to happen.
        print("[NFT] mint failed, falling back to hash anchoring")
    return _hash_fallback(cert_id, user_id)


def _mint_nft(cert_id: str, user_id: int) -> dict | None:
    try:
        from blockchain import _w3, _chain_id

        from blockchain import compute_anchor
        from db import lms_get_certificate

        info         = _fetch_user_info(user_id)
        user_name    = f"{info.get('fname', '')} {info.get('lname', '')}".strip() or "Unknown"
        ft           = info.get("form_type") or info.get("training_type") or "training"
        training_lbl = _TRAINING_LABELS.get(ft, ft.replace("_", " ").title())
        issued_str   = date.today().strftime("%B %d, %Y")

        cert   = lms_get_certificate(cert_id=cert_id) or {}
        anchor = compute_anchor("certificate", {
            "cert_id":    cert_id,
            "user_id":    user_id,
            "issued_at":  cert.get("issued_at"),
            "expires_at": cert.get("expires_at"),
        })
        token_uri = _build_token_uri(cert_id, user_name, training_lbl, issued_str,
                                     anchor=anchor)

        w3          = _w3()
        private_key = os.getenv("SYSTEM_WALLET_PRIVATE_KEY")
        wallet      = w3.to_checksum_address(os.getenv("SYSTEM_WALLET_ADDRESS"))
        contract    = w3.eth.contract(address=w3.to_checksum_address(CONTRACT_ADDRESS),
                                      abi=_MINT_ABI)

        mint_fn = contract.functions.mint(wallet, token_uri)

        # The token URI is ~700-800 bytes of metadata written on-chain, and its
        # cost scales with the trainee's name and programme label. A fixed limit
        # goes stale the moment a name runs long: 300_000 was roughly half what
        # even the shortest name needs, so every mint burnt the lot and reverted.
        # Estimate per certificate and carry a margin for block-to-block drift.
        try:
            gas_limit = int(mint_fn.estimate_gas({"from": wallet}) * 1.25)
        except Exception as e:
            gas_limit = 900_000
            print(f"[NFT] gas estimate failed ({type(e).__name__}), using {gas_limit}")

        gas_price = w3.eth.gas_price
        balance   = w3.eth.get_balance(wallet)
        needed    = gas_limit * gas_price
        if balance < needed:
            raise RuntimeError(
                "wallet %s has %.6f POL but this mint reserves %.6f "
                "(gas %d @ %.1f gwei) - top up at faucet.polygon.technology"
                % (wallet, balance / 1e18, needed / 1e18, gas_limit, gas_price / 1e9)
            )

        tx = mint_fn.build_transaction({
            "chainId":  _chain_id(),
            "gas":      gas_limit,
            "gasPrice": gas_price,
            "nonce":    w3.eth.get_transaction_count(wallet),
        })
        signed  = w3.eth.account.sign_transaction(tx, private_key)
        raw     = w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = w3.eth.wait_for_transaction_receipt(raw, timeout=120)

        # A mined transaction is not a successful one. Without this, a revert
        # still returns a tx_hash and the certificate is recorded as anchored
        # on-chain when nothing was actually minted.
        if receipt.status != 1:
            raise RuntimeError(
                "mint reverted on-chain (tx %s, gas used %d of %d)"
                % (raw.hex(), receipt.gasUsed, gas_limit)
            )

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
        from blockchain import ANCHOR_VERSION
        return {"tx_hash": tx_hex, "token_id": token_id or cert_id,
                "anchor_version": ANCHOR_VERSION, "is_nft": True}

    except Exception as e:
        print(f"[NFT mint error] {type(e).__name__}: {e}")
        return None


def _hash_fallback(cert_id: str, user_id: int) -> dict | None:
    """Hash-on-chain anchoring, used when NFT_CONTRACT_ADDRESS is not set.

    Anchors the certificate's material facts - holder, issue date and expiry -
    rather than just cert_id:user_id. The old fingerprint covered neither date,
    so back-dating an expiry left the anchor matching and the certificate still
    read as verified.
    """
    try:
        from blockchain import store_hash_on_chain, compute_anchor, ANCHOR_VERSION
        from db import lms_get_certificate

        cert = lms_get_certificate(cert_id=cert_id) or {}
        record = {
            "cert_id":    cert_id,
            "user_id":    user_id,
            "issued_at":  cert.get("issued_at"),
            "expires_at": cert.get("expires_at"),
        }
        cert_hash = compute_anchor("certificate", record)
        result    = store_hash_on_chain(cert_hash)
        if result:
            return {"tx_hash": result["tx_hash"], "token_id": cert_id,
                    "anchor_version": ANCHOR_VERSION}
    except Exception as e:
        print(f"[hash fallback error] {type(e).__name__}: {e}")
    return None
