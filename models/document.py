from dataclasses import dataclass, field
from typing import List, Dict, Optional


@dataclass
class ContentBlock:
    """
    A single ordered piece of extracted document content.

    The source field preserves where the content came from,
    such as a PDF page, PPTX slide, or DOCX paragraph/table.
    """
    text: str
    source: str
    block_type: str = "text"
    metadata: Dict[str, str] = field(default_factory=dict)


@dataclass
class NormalizedDocument:
    """
    Common document representation shared by all extraction modules.
    """
    document_id: str
    source_type: str
    file_name: str
    content: List[ContentBlock] = field(default_factory=list)
    metadata: Dict[str, str] = field(default_factory=dict)

    def full_text(self) -> str:
        """Return all extracted text in document order."""
        return "\n".join(block.text for block in self.content)