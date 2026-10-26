"""Public interface of the extraction module:  extract(file) -> NormalizedDocument
Returns the team's shared models.document.NormalizedDocument.
Never raises. Problems go into doc.metadata["warnings"] / ["status"]."""
import json
import os
import tempfile
import uuid
from pathlib import Path

from models.document import NormalizedDocument, ContentBlock
from extraction.internal import ExtractionMetadata
from extraction.docx_extractor import extract_docx
from extraction.pptx_extractor import extract_pptx
from extraction.pdf_extractor import extract_pdf
from security import upload_guard

_DISPATCH = {".pdf": ("pdf", extract_pdf),
             ".pptx": ("pptx", extract_pptx),
             ".docx": ("docx", extract_docx)}


def _source_string(loc):
    """Human-readable location, e.g. 'page 3' or 'slide 5 | shape Title 1 | paragraph 0'."""
    t = loc.get("type", "unknown")
    parts = [f"{k} {v}" for k, v in loc.items() if k not in ("type", "image_ocr")]
    if t not in loc:
        parts.insert(0, t.replace("_", " "))
    if loc.get("image_ocr"):
        parts.append("image OCR")
    return " | ".join(parts)


def _to_str(v):
    return v if isinstance(v, str) else json.dumps(v)


def _block_type(loc, md):
    if md.get("ocr") is True:
        return "ocr_text"
    t = loc.get("type", "")
    if t == "slide_notes":
        return "notes"
    if "table" in t or "row" in loc:
        return "table_cell"
    return "text"


def _build(doc_id, source_type, filename, blocks, meta):
    content = []
    for b in blocks:
        md = {k: _to_str(v) for k, v in b.metadata.items() if v is not None}
        md["block_id"] = b.block_id                        # unique id for findings
        md["order"] = str(b.order)
        md["location"] = json.dumps(b.source_location)     # structured location (JSON)
        content.append(ContentBlock(text=b.text, source=_source_string(b.source_location),
                                    block_type=_block_type(b.source_location, b.metadata),
                                    metadata=md))
    errors = [w for w in meta.warnings if w.startswith("ERROR")]
    doc_md = {"parser": meta.parser, "ocr_used": str(meta.ocr_used).lower(),
              "status": "error" if errors else "ok",
              "warnings": " | ".join(meta.warnings),
              "block_count": str(len(content))}
    if errors:
        doc_md["error"] = errors[0]
    return NormalizedDocument(document_id=doc_id, source_type=source_type,
                              file_name=filename, content=content, metadata=doc_md)


def extract(file, filename=None) -> NormalizedDocument:
    """file: path (str/Path), raw bytes, or a file-like object (Streamlit upload).
    filename: needed for bytes/file-like so we know the extension."""
    doc_id = uuid.uuid4().hex[:8]
    meta = ExtractionMetadata()
    tmp_path = None
    try:
        if isinstance(file, (str, Path)):
            path = str(file)
            filename = filename or os.path.basename(path)
        else:                                   # bytes or file-like -> temp file
            filename = filename or getattr(file, "name", "upload")
            data = file if isinstance(file, bytes) else file.read()
            fd, tmp_path = tempfile.mkstemp(suffix=Path(filename).suffix.lower())
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            path = tmp_path

        ext = Path(filename).suffix.lower()
        if ext not in _DISPATCH:
            meta.warnings.append(f"ERROR: unsupported file type '{ext}' (use pdf, pptx, docx)")
            return _build(doc_id, ext.lstrip(".") or "unknown", filename, [], meta)

        source_type, fn = _DISPATCH[ext]
        problem = upload_guard.check(path, ext)          # validate before any parser touches the file
        if problem:
            meta.warnings.append(f"ERROR: rejected by upload guard: {problem}")
            return _build(doc_id, source_type, filename, [], meta)
        blocks = []
        try:
            blocks = fn(path, doc_id, meta)
        except Exception as e:                  # corrupt / protected file
            meta.warnings.append(f"ERROR: could not extract ({type(e).__name__}: {e})")
        if not blocks and not any(w.startswith("ERROR") for w in meta.warnings):
            meta.warnings.append("WARNING: no text found in document")
        return _build(doc_id, source_type, filename, blocks, meta)
    except Exception as e:                      # last-resort safety net
        meta.warnings.append(f"ERROR: {type(e).__name__}: {e}")
        return _build(doc_id, "unknown", filename or "unknown", [], meta)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)