from typing import List, Protocol

from models.document import NormalizedDocument
from models.pii import PIIFinding


class VerificationResult:
    """
    Result of the post-redaction security scan.
    """

    def __init__(
        self,
        is_safe: bool,
        remaining_findings: List[PIIFinding],
    ):
        self.is_safe = is_safe
        self.remaining_findings = remaining_findings


class Verifier(Protocol):
    """
    Common interface for post-redaction verification.
    """

    def verify(
        self,
        document: NormalizedDocument,
    ) -> VerificationResult:
        ...