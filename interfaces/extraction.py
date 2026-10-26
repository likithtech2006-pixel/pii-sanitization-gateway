from typing import Protocol

from models.document import NormalizedDocument


class DocumentExtractor(Protocol):
    """
    Common interface for all document extraction modules.
    """

    def extract(self, file_path: str) -> NormalizedDocument:
        ...