"""Signed sanitization certificates.

A certificate attests what the gateway decided about one input file: content hashes of the input and of
the sanitized output, the verdict, counts by PII type, the exact rule set (hash of the detection and
verification source), content risks and regulation mapping. It is signed with Ed25519, so anyone with
the public key can verify it offline, and any change to any field invalidates the signature.

It never contains the file name, document text or PII values.
"""
import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from security import compliance, keys

SCHEMA = "pii-gateway/sanitization-certificate/v1"
_ROOT = Path(__file__).resolve().parents[1]
_RULE_FILES = ["detection/patterns.py", "detection/names.py", "detection/lexicon.py", "detection/__init__.py",
               "redaction/redactor.py", "redaction/verifier.py", "redaction/gate.py"]


def _canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def ruleset_hash() -> str:
    h = hashlib.sha256()
    for rel in _RULE_FILES:
        p = _ROOT / rel
        h.update(rel.encode())
        h.update(p.read_bytes() if p.exists() else b"")
    return h.hexdigest()


def issue(input_bytes: bytes, file_type: str, result, sanitized: Optional[str], risk) -> Dict[str, object]:
    """result: pipeline.PipelineResult; risk: security.inspector.ContentRisk (or None)."""
    s = result.summary()
    gate = result.gate.to_dict()
    cert = {
        "schema": SCHEMA,
        "certificate_id": str(uuid.uuid4()),
        "issued_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "issuer": {"product": "PII Sanitization Gateway", "key_id": keys.key_id()},
        "subject": {"input_sha256": sha256(input_bytes), "input_bytes": len(input_bytes), "file_type": file_type},
        "verdict": {"status": gate["status"], "reason": gate["reason"], "verification_passes": gate["verification_passes"],
                    "checks": gate["checks"], "redacted_count": gate["redacted_count"],
                    "residual_count": gate["residual_count"], "needs_review": gate["needs_review"],
                    "counts_by_type": gate["counts_by_type"]},
        "output": {"sanitized_text_sha256": sha256(sanitized.encode("utf-8")) if sanitized is not None else None},
        "policy": {"ruleset_sha256": ruleset_hash(), "detectors": s["engines"], "confidence_threshold": 0.5,
                   "max_verification_passes": 2, "fail_closed": True},
        "content_risk": {"level": risk.level, "ai_blocked": risk.ai_blocked, "kinds": risk.kinds()} if risk else None,
        "compliance": {"regulations": [r["id"] for r in compliance.summary(gate["counts_by_type"])],
                       "disclaimer": compliance.DISCLAIMER},
    }
    cert["signature"] = {"alg": "Ed25519", "key_id": keys.key_id(), "value": keys.sign(_canonical(cert))}
    return cert


def verify(cert: Dict, public_pem: Optional[bytes] = None, input_bytes: Optional[bytes] = None,
           sanitized: Optional[str] = None) -> Tuple[bool, List[str]]:
    """Check signature and, if given, that the file / sanitized text match the hashes. Returns (ok, notes)."""
    notes: List[str] = []
    try:
        body = {k: v for k, v in cert.items() if k != "signature"}
        sig = cert["signature"]
        if body.get("schema") != SCHEMA or sig.get("alg") != "Ed25519":
            return False, ["unknown certificate format"]
        pub = keys.load_public_pem(public_pem) if public_pem else keys.public_key()
        if sig.get("key_id") != keys.key_id(pub):
            return False, ["signed by a different key than the one supplied"]
        if not keys.verify(_canonical(body), sig.get("value", ""), pub):
            return False, ["signature is NOT valid: the certificate was altered or forged"]
        notes.append("signature valid")
    except Exception as e:
        return False, [f"certificate could not be read ({type(e).__name__})"]
    ok = True
    if input_bytes is not None:
        match = sha256(input_bytes) == body["subject"]["input_sha256"]
        notes.append("input file matches the certificate" if match else "input file does NOT match the certificate")
        ok &= match
    if sanitized is not None:
        expected = body["output"]["sanitized_text_sha256"]
        match = expected is not None and sha256(sanitized.encode("utf-8")) == expected
        notes.append("sanitized text matches the certificate" if match else "sanitized text does NOT match the certificate")
        ok &= match
    return ok, notes
