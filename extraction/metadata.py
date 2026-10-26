"""Document properties (author, title, ...) as content blocks.

Office and PDF files carry properties such as the author's name. They are
personal data too, so they are extracted as ordinary blocks (block_type
"metadata") at the END of the document. That way detection, redaction and
verification treat them like any other text, and body block order is unchanged.

Software fields (creator / producer / application) are not extracted.
"""

# Fields that may hold free text or a person's name.
OFFICE_FIELDS = ("author", "last_modified_by", "title", "subject", "keywords",
                 "comments", "category")
PDF_FIELDS = ("author", "title", "subject", "keywords")

# Values written by libraries/tools, not by people.
_TOOL_VALUES = {"python-docx", "python-pptx", "powerpoint presentation", "untitled"}


def _keep(value) -> bool:
    return isinstance(value, str) and value.strip() and value.strip().lower() not in _TOOL_VALUES


def office_properties(core_properties):
    """[(field, value)] from a python-docx / python-pptx core_properties object."""
    out = []
    for name in OFFICE_FIELDS:
        value = getattr(core_properties, name, None)
        if _keep(value):
            out.append((name, value.strip()))
    return out


def pdf_properties(metadata):
    """[(field, value)] from a PyMuPDF document.metadata dict."""
    out = []
    for name in PDF_FIELDS:
        value = (metadata or {}).get(name)
        if _keep(value):
            out.append((name, value.strip()))
    return out


def add_metadata_blocks(add, fields):
    """Append one block per property using the extractor's add(text, loc, md)."""
    for name, value in fields:
        add(value, {"type": "metadata", "field": name}, {"kind": "metadata", "field": name})
