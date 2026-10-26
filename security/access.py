"""Optional passphrase gate for the web app.

Enable it by setting PII_GATEWAY_PASSPHRASE_HASH to a value produced by:

    .venv/bin/python -m security.access

Hashes use scrypt (n=2**15, r=8, p=1) with a random salt; comparison is constant-time. Failed attempts
are rate-limited per client with exponential lockout. For multi-user production use, put the app behind
an SSO-enforcing reverse proxy instead (see SECURITY.md).
"""
import base64
import getpass
import hashlib
import hmac
import os
import secrets
import threading
import time
from typing import Dict, Tuple

_N, _R, _P = 2 ** 15, 8, 1
_FAILS: Dict[str, Tuple[int, float]] = {}      # client -> (failures, locked_until)
_LOCK = threading.Lock()


def enabled() -> bool:
    return bool(os.getenv("PII_GATEWAY_PASSPHRASE_HASH"))


def hash_passphrase(passphrase: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(passphrase.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, maxmem=64 * 1024 * 1024, dklen=32)
    return "scrypt${}${}${}${}${}".format(_N, _R, _P, base64.b64encode(salt).decode(), base64.b64encode(dk).decode())


def _check(passphrase: str, stored: str) -> bool:
    try:
        alg, n, r, p, salt, dk = stored.split("$")
        if alg != "scrypt":
            return False
        got = hashlib.scrypt(passphrase.encode("utf-8"), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
                             maxmem=64 * 1024 * 1024, dklen=32)
        return hmac.compare_digest(got, base64.b64decode(dk))
    except Exception:
        return False


def locked_for(client: str) -> int:
    with _LOCK:
        _, until = _FAILS.get(client, (0, 0.0))
    return max(0, int(until - time.time()))


def attempt(client: str, passphrase: str) -> bool:
    if locked_for(client):
        return False
    ok = _check(passphrase, os.getenv("PII_GATEWAY_PASSPHRASE_HASH", ""))
    with _LOCK:
        if ok:
            _FAILS.pop(client, None)
        else:
            fails = _FAILS.get(client, (0, 0.0))[0] + 1
            delay = 0 if fails < 3 else min(900, 2 ** (fails - 2) * 15)     # 30 s, 60 s, ... capped at 15 min
            _FAILS[client] = (fails, time.time() + delay)
    return ok


if __name__ == "__main__":
    first = getpass.getpass("New passphrase (min 12 characters): ")
    if len(first) < 12 or first != getpass.getpass("Repeat: "):
        raise SystemExit("Passphrases differ or are shorter than 12 characters.")
    print("Set this environment variable before starting the app:\n")
    print(f"export PII_GATEWAY_PASSPHRASE_HASH='{hash_passphrase(first)}'")
