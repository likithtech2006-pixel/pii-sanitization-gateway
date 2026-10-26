from typing import Protocol, List

from models.document import NormalizedDocument
from models.pii import PIIFinding


class RedactionResult:
    """
    Result returned after PII redaction.
    """

    def __init__(
        self,
        document: NormalizedDocument,
        redacted_count: int,
    ):
        self.document = document
        self.redacted_count = redacted_count


class Redactor(Protocol):
    """
    Common interface for PII redaction.
    """

    def redact(
        self,
        document: NormalizedDocument,
        findings: List[PIIFinding],
    ) -> RedactionResult:
        ...