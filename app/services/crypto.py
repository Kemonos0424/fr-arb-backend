"""Fernet encryption/decryption for API keys."""
from cryptography.fernet import Fernet
from app.config import settings

_fernet = Fernet(settings.fernet_master_key.encode())


def encrypt(plaintext: str) -> bytes:
    return _fernet.encrypt(plaintext.encode())


def decrypt(ciphertext: bytes) -> str:
    return _fernet.decrypt(ciphertext).decode()
