"""Security gate: redact -> verify -> (remediate residuals) -> SAFE / BLOCKED.

This is the single call the pipeline/UI makes after detection:

    result = sanitize_and_verify(document, findings, detector)
    if result.is_safe:
        send_downstream(result.released_text())

Residual PII found by verification is redacted and the document is rescanned,
up to max_passes scans in total. If PII is still present after that, or the
document could not be extracted, the gate BLOCKS: nothing is released.
"""
from typing import Dict, List, Optional

from interfaces.detection import PIIDetector
from models.document import NormalizedDocument
from models.pii import PIIFinding
from redaction.redactor import DEFAULT_THRESHOLD, PlaceholderRedactionResult, PlaceholderRedactor
from redaction.verifier import BLOCKED, SAFE, SecondPassVerificationResult, SecondPassVerifier


class GateResult:
    """Outcome of the security gate. to_dict() contains no raw PII."""

    def __init__(self, document: NormalizedDocument, redaction: PlaceholderRedactionResult,
                 verification: Optional[SecondPassVerificationResult], passes: int,
                 remediated_count: int, reason: str, error: str = ""):
        self.document = document
        self.redaction = redaction
        self.verification = verification
        self.passes = passes
        self.remediated_count = remediated_count
        self.reason = reason
        self.error = error  # exception type only - messages may contain PII
        self.is_safe = verification is not None and verification.is_safe
        self.status = SAFE if self.is_safe else BLOCKED
        document.metadata["verification_status"] = self.status

    @property
    def residual_findings(self) -> List[PIIFinding]:
        return self.verification.remaining_findings if self.verification else []

    def released_text(self) -> Optional[str]:
        """Sanitized text for downstream AI use - only when verification passed."""
        return self.document.full_text() if self.is_safe else None

    def to_dict(self) -> Dict[str, object]:
        return {
            "document_id": self.document.document_id,
            "file_name": self.document.file_name,
            "status": self.status,
            "reason": self.reason,
            "error": self.error,
            "verification_passes": self.passes,
            "checks": self.verification.checks if self.verification else [],
            "redacted_count": self.redaction.redacted_count,
            "remediated_count": self.remediated_count,
            "counts_by_type": self.redaction.counts_by_type(),
            "placeholders": self.redaction.placeholder_map,
            "skipped": self.redaction.skipped,
            "needs_review": sum(1 for s in self.redaction.skipped if s["reason"] == "below_threshold"),
            "residual_count": len(self.residual_findings),
            "residuals": self.verification.safe_residuals() if self.verification else [],
        }


# Extraction warnings meaning some content was never read (e.g. scanned pages without OCR).
_INCOMPLETE_MARKERS = ("not installed", "ocr failed")


def _extraction_problem(document: NormalizedDocument) -> Optional[str]:
    """Reason to block before verification, or None."""
    if document.metadata.get("status") == "error":
        return "extraction_failed"
    warnings = document.metadata.get("warnings", "").lower()
    if any(marker in warnings for marker in _INCOMPLETE_MARKERS):
        return "incomplete_extraction"
    if not any(block.text.strip() for block in document.content):
        return "no_content"
    return None


def sanitize_and_verify(document: NormalizedDocument, findings: List[PIIFinding],
                        detector: Optional[PIIDetector] = None, max_passes: int = 2,
                        threshold: float = DEFAULT_THRESHOLD, safety_net: bool = True) -> GateResult:
    """Redact findings, then verify; remediate residuals up to max_passes scans."""
    if max_passes < 1:
        raise ValueError("max_passes must be at least 1")
    redactor = PlaceholderRedactor(threshold)
    redaction = redactor.redact(document, findings or [])

    # A failed or partial extraction yields little or no text, which would trivially "verify".
    blocked_reason = _extraction_problem(document)
    if blocked_reason:
        return GateResult(redaction.document, redaction, None, 0, 0, blocked_reason)

    verifier = SecondPassVerifier(detector, safety_net=safety_net, threshold=threshold)
    passes, remediated = 0, 0
    try:
        verification = verifier.verify(redaction.document)
        passes = 1
        while not verification.is_safe and passes < max_passes:
            before = redaction.redacted_count
            redaction = redactor.redact(redaction.document, verification.remaining_findings, previous=redaction)
            remediated += redaction.redacted_count - before
            verification = verifier.verify(redaction.document)
            passes += 1
    except Exception as exc:  # fail closed: an unverifiable document is never released
        return GateResult(redaction.document, redaction, None, passes, remediated,
                          "verification_error", type(exc).__name__)

    if verification.is_safe:
        reason = "verified_clean" if remediated == 0 else "verified_after_remediation"
    else:
        reason = "residual_pii"
    return GateResult(redaction.document, redaction, verification, passes, remediated, reason)
