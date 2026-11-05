import base64
import hashlib
import json
import time

import bcrypt
import jwt
from cryptography.fernet import Fernet

from .config import get_settings


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode()[:72], bcrypt.gensalt()).decode()


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode()[:72], hashed.encode())
    except ValueError:
        return False


def create_token(sub: int, kind: str = "session", ttl: int = 7 * 86400, extra: dict | None = None) -> str:
    payload = {"sub": str(sub), "kind": kind, "exp": int(time.time()) + ttl, **(extra or {})}
    return jwt.encode(payload, get_settings().app_secret_key, algorithm="HS256")


def decode_token(token: str, kind: str = "session") -> dict | None:
    try:
        data = jwt.decode(token, get_settings().app_secret_key, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    return data if data.get("kind") == kind else None


def _fernet() -> Fernet:
    key = get_settings().app_encryption_key
    if not key:  # Mode développement uniquement : clé dérivée du secret applicatif.
        key = base64.urlsafe_b64encode(hashlib.sha256(get_settings().app_secret_key.encode()).digest()).decode()
    return Fernet(key.encode())


def encrypt(text: str) -> str:
    return _fernet().encrypt(text.encode()).decode()


def decrypt(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()


def encrypt_json(obj: dict) -> str:
    return encrypt(json.dumps(obj))


def decrypt_json(token: str | None) -> dict:
    if not token:
        return {}
    try:
        return json.loads(decrypt(token))
    except Exception:
        return {}
