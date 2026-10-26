"""Redaction and post-redaction verification module.

Public interface:
    redact(document, findings) -> RedactionResult
    verify(document, detector=None) -> VerificationResult
    sanitize_and_verify(document, findings, detector=None) -> GateResult (SAFE / BLOCKED)
"""
from redaction.gate import GateResult, sanitize_and_verify
from redaction.redactor import (
    DEFAULT_THRESHOLD,
    PLACEHOLDER_RE,
    PlaceholderRedactionResult,
    PlaceholderRedactor,
    redact,
)
from redaction.verifier import (
    BLOCKED,
    SAFE,
    SecondPassVerificationResult,
    SecondPassVerifier,
    safety_net_scan,
    verify,
)

__all__ = [
    "BLOCKED",
    "DEFAULT_THRESHOLD",
    "GateResult",
    "PLACEHOLDER_RE",
    "PlaceholderRedactionResult",
    "PlaceholderRedactor",
    "SAFE",
    "SecondPassVerificationResult",
    "SecondPassVerifier",
    "redact",
    "safety_net_scan",
    "sanitize_and_verify",
    "verify",
]
