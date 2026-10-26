"""Append-only, hash-chained, signed audit log.

Each line is a JSON event with the hash of the previous line ("prev"), its own hash ("hash") and an
Ed25519 signature over that hash ("sig"). Editing, deleting or reordering any line breaks the chain,
and forging a line needs the signing key. Only whitelisted, non-identifying fields are recorded:
never file names, document text or PII values (documents are referenced by a content-hash prefix).
"""
import fcntl
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

from security import keys

ALLOWED_FIELDS = {"doc", "file_type", "status", "reason", "redacted", "findings", "risk", "provider",
                  "kind", "count", "outcome", "certificate_id", "client", "minutes", "ok", "detail"}
GENESIS = "0" * 64


def _path() -> Path:
    d = keys.home() / "audit"
    d.mkdir(exist_ok=True)
    os.chmod(d, 0o700)
    return d / "audit.jsonl"


def _canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _last_hash(path: Path) -> str:
    if not path.exists() or path.stat().st_size == 0:
        return GENESIS
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        pos = f.tell()
        buf = b""
        while pos > 0 and buf.count(b"\n") < 2:
            step = min(4096, pos)
            pos -= step
            f.seek(pos)
            buf = f.read(step) + buf
    line = buf.strip().split(b"\n")[-1]
    return json.loads(line)["hash"]


def _clean(fields: Dict) -> Dict:
    out = {}
    for k, v in fields.items():
        if k in ALLOWED_FIELDS and isinstance(v, (str, int, float, bool)) and v is not None:
            out[k] = v if not isinstance(v, str) else v[:120]
    return out


def log(event: str, **fields) -> None:
    """Record an event. Never raises into the caller: auditing problems must not break processing."""
    try:
        path = _path()
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                entry = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "event": event,
                         **_clean(fields), "prev": _last_hash(path)}
                digest = hashlib.sha256(_canonical(entry)).hexdigest()
                entry["hash"] = digest
                entry["sig"] = keys.sign(digest.encode("ascii"))
                f.write(json.dumps(entry, separators=(",", ":")) + "\n")
                f.flush()
                os.fsync(f.fileno())
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
        os.chmod(path, 0o600)
    except Exception:
        pass


def verify() -> Tuple[bool, int, str]:
    """(intact, number of events, problem description or '')."""
    path = _path()
    if not path.exists():
        return True, 0, ""
    prev, n = GENESIS, 0
    pub = keys.public_key()
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                return False, n, f"line {n} is not valid JSON"
            digest, sig = entry.pop("hash", None), entry.pop("sig", None)
            if entry.get("prev") != prev:
                return False, n, f"chain broken at line {n} (missing, reordered or inserted line)"
            if hashlib.sha256(_canonical(entry)).hexdigest() != digest:
                return False, n, f"line {n} was modified"
            if not keys.verify(digest.encode("ascii"), sig or "", pub):
                return False, n, f"line {n} has an invalid signature"
            prev = digest
    return True, n, ""


def recent(limit: int = 15) -> List[Dict]:
    path = _path()
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()[-limit:]
    out = []
    for line in reversed(lines):
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        out.append({k: v for k, v in e.items() if k not in ("sig", "prev")})
    return out
