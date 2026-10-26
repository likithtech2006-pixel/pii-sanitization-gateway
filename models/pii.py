from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class PIIFinding:
    """
    Represents a single detected PII instance.
    """

    pii_type: str
    value: str
    source: str

    confidence: float
    detection_method: str

    start: Optional[int] = None
    end: Optional[int] = None

    validated: bool = False
    metadata: Dict[str, str] = field(default_factory=dict)

    def masked_value(self) -> str:
        """Return a safe representation for logs or UI."""
        if len(self.value) <= 4:
            return "*" * len(self.value)

        return self.value[:2] + "*" * (len(self.value) - 4) + self.value[-2:]