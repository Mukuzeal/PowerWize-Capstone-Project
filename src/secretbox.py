"""Encryption at rest for the few secrets that cannot be hashed.

Almost everything sensitive in this app is stored as a SHA-256 hash, because
nothing ever needs to read it back — account invitations, coordinator links,
payment links. Hashing is strictly better and should stay the default.

Link-delivery payloads break that rule: payment and company registration URLs kept for retry. A retry
must send the SAME link the company already received, so the value has to be
recoverable, and a hash cannot do that. Encryption is the honest second
choice — and it is worth being explicit that it is weaker than hashing: with
the key, the plaintext comes back.

Key derivation uses SECRET_KEY, so no new secret has to be managed. That ties
the ciphertext's lifetime to the app's session key: rotating SECRET_KEY makes
stored payloads unreadable, which degrades to "retry needs a fresh link"
rather than to anything unsafe.
"""
import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken


class SecretUnavailable(RuntimeError):
    """No usable key, so nothing can be encrypted or read back."""


def _key():
    secret = os.getenv("SECRET_KEY", "")
    if not secret:
        raise SecretUnavailable(
            "SECRET_KEY is not set, so retry payloads cannot be encrypted.")
    # Fernet wants 32 url-safe base64 bytes; SECRET_KEY is arbitrary text.
    digest = hashlib.sha256(f"powerwize-payload-v1:{secret}".encode()).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt(plaintext):
    if plaintext is None:
        return None
    return Fernet(_key()).encrypt(plaintext.encode()).decode()


def decrypt(ciphertext):
    """Plaintext, or None if it cannot be read.

    Returns None rather than raising on a bad token: the practical cause is a
    rotated SECRET_KEY, and the caller's correct response is "issue a fresh
    link", not a 500.
    """
    if not ciphertext:
        return None
    try:
        return Fernet(_key()).decrypt(ciphertext.encode()).decode()
    except (InvalidToken, SecretUnavailable, Exception):
        return None
