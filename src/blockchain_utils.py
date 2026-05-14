import hashlib
from blockchain import store_hash_on_chain


def store_certificate_hash(cert_id: str, user_id: int) -> str:
    """
    Store certificate hash on Polygon Amoy blockchain.
    Returns the transaction hash if successful, None otherwise.
    """
    try:
        # Create a hash of the certificate ID
        cert_hash = hashlib.sha256(f"{cert_id}:{user_id}".encode()).hexdigest()

        # Store on blockchain
        result = store_hash_on_chain(cert_hash)

        if result and result.get("tx_hash"):
            return result["tx_hash"]
        return None
    except Exception as e:
        print(f"Error storing certificate on blockchain: {e}")
        return None
