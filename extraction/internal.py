"""Internal helper types used only inside the extraction module.
The extractors build these, and extract() converts them into the team's
shared models.document.NormalizedDocument / ContentBlock."""
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class Block:
    block_id: str
    text: str
    source_location: Dict[str, Any]
    order: int
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExtractionMetadata:
    ocr_used: bool = False
    parser: str = ""
    warnings: List[str] = field(default_factory=list)