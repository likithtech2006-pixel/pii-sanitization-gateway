from typing import List, Protocol

from models.document import NormalizedDocument
from models.pii import PIIFinding


class PIIDetector(Protocol):
    """
    Common interface for PII detection.
    """

    def detect(self, document: NormalizedDocument) -> List[PIIFinding]:
        ...