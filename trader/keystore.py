from cryptography.fernet import Fernet, InvalidToken
from solders.keypair import Keypair

import base58


class KeystoreError(Exception):
    pass


class Keystore:
    """Encrypts wallet secret keys before they touch the database."""

    def __init__(self, key: str | None):
        if not key:
            raise KeystoreError("WALLET_ENCRYPTION_KEY is not set")
        try:
            self._fernet = Fernet(key.encode())
        except ValueError as e:
            raise KeystoreError("WALLET_ENCRYPTION_KEY is not a valid Fernet key") from e

    def encrypt(self, keypair: Keypair) -> str:
        return self._fernet.encrypt(bytes(keypair)).decode()

    def decrypt(self, token: str) -> Keypair:
        try:
            return Keypair.from_bytes(self._fernet.decrypt(token.encode()))
        except InvalidToken as e:
            raise KeystoreError("Could not decrypt wallet (wrong WALLET_ENCRYPTION_KEY?)") from e


def parse_secret_key(text: str) -> Keypair:
    """Accept a base58 secret key (Phantom/Solflare export) or a JSON byte array (solana-keygen)."""
    text = text.strip()
    try:
        if text.startswith("["):
            import json

            raw = bytes(json.loads(text))
        else:
            raw = base58.b58decode(text)
    except Exception as e:
        raise ValueError("Not a valid secret key") from e
    if len(raw) == 64:
        return Keypair.from_bytes(raw)
    if len(raw) == 32:
        return Keypair.from_seed(raw)
    raise ValueError("Secret key must be 32 or 64 bytes")


def export_secret_key(keypair: Keypair) -> str:
    return base58.b58encode(bytes(keypair)).decode()
