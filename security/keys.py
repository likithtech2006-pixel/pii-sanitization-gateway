"""Ed25519 signing key for certificates and the audit log.

The key lives in PII_GATEWAY_HOME (default ~/.pii_gateway, created with mode 0700) as
keys/signing_ed25519.pem with mode 0600. Set PII_GATEWAY_KEY_PASSPHRASE to keep the key
encrypted at rest. In a production deployment the key would sit in a KMS/HSM instead.
"""
import base64
import hashlib
import os
import threading
from functools import lru_cache
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

_LOCK = threading.Lock()


def home() -> Path:
    """Private data directory (owner-only)."""
    path = Path(os.getenv("PII_GATEWAY_HOME", str(Path.home() / ".pii_gateway"))).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def _key_path() -> Path:
    d = home() / "keys"
    d.mkdir(exist_ok=True)
    os.chmod(d, 0o700)
    return d / "signing_ed25519.pem"


def _passphrase():
    p = os.getenv("PII_GATEWAY_KEY_PASSPHRASE")
    return p.encode("utf-8") if p else None


@lru_cache(maxsize=4)
def _load(path_str: str) -> Ed25519PrivateKey:
    path = Path(path_str)
    with _LOCK:
        if not path.exists():
            key = Ed25519PrivateKey.generate()
            enc = (serialization.BestAvailableEncryption(_passphrase()) if _passphrase()
                   else serialization.NoEncryption())
            pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, enc)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)   # never world-readable
            with os.fdopen(fd, "wb") as f:
                f.write(pem)
        os.chmod(path, 0o600)
        return serialization.load_pem_private_key(path.read_bytes(), password=_passphrase())


def signing_key() -> Ed25519PrivateKey:
    return _load(str(_key_path()))


def public_key() -> Ed25519PublicKey:
    return signing_key().public_key()


def public_key_pem() -> bytes:
    return public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)


def key_id(pub: Ed25519PublicKey = None) -> str:
    raw = (pub or public_key()).public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return hashlib.sha256(raw).hexdigest()[:16]


def sign(data: bytes) -> str:
    return base64.b64encode(signing_key().sign(data)).decode("ascii")


def verify(data: bytes, signature_b64: str, pub: Ed25519PublicKey = None) -> bool:
    try:
        (pub or public_key()).verify(base64.b64decode(signature_b64), data)
        return True
    except Exception:
        return False


def load_public_pem(pem: bytes) -> Ed25519PublicKey:
    key = serialization.load_pem_public_key(pem)
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("not an Ed25519 public key")
    return key
