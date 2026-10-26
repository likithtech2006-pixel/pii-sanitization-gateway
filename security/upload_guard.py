"""Validate an uploaded file before any parser touches it.

Checks: size limit, real file type by magic bytes (not the extension), password-protected or
legacy binary Office files, ZIP-bomb limits (entry count, total and per-entry expansion), unsafe
member names, required package parts, PDF encryption and page limit.

check() returns None when the file is acceptable, otherwise a short reason. The extractor turns
a rejection into an extraction error, so the gate BLOCKS the document (fail closed).
"""
import os
import zipfile
from typing import Optional

MAX_MB = int(os.getenv("PII_GATEWAY_MAX_UPLOAD_MB", "50"))
MAX_PAGES = int(os.getenv("PII_GATEWAY_MAX_PAGES", "500"))
ZIP_MAX_ENTRIES = 5000
ZIP_MAX_TOTAL = 400 * 1024 * 1024        # uncompressed bytes for a whole package
ZIP_MAX_RATIO = 200                       # per-entry compression ratio (entries > 64 KiB)
_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"   # encrypted OOXML and legacy .doc/.ppt use this container
_MAIN_PART = {".docx": "word/document.xml", ".pptx": "ppt/presentation.xml"}


def check(path: str, ext: str) -> Optional[str]:
    size = os.path.getsize(path)
    if size == 0:
        return "empty file"
    if size > MAX_MB * 1024 * 1024:
        return f"file larger than {MAX_MB} MB"
    with open(path, "rb") as f:
        head = f.read(1024)
    if ext == ".pdf":
        return _check_pdf(path, head)
    if ext in _MAIN_PART:
        return _check_ooxml(path, head, ext)
    return f"unsupported file type '{ext}'"


def _check_pdf(path: str, head: bytes) -> Optional[str]:
    if b"%PDF-" not in head:
        return "not a PDF file (content does not match the .pdf extension)"
    try:
        import pymupdf
    except ImportError:  # pragma: no cover
        import fitz as pymupdf
    try:
        doc = pymupdf.open(path)
    except Exception:
        return "PDF could not be opened"
    try:
        if doc.needs_pass or doc.is_encrypted:
            return "password-protected PDF (cannot be inspected, so it is not released)"
        if doc.page_count > MAX_PAGES:
            return f"PDF has more than {MAX_PAGES} pages"
    finally:
        doc.close()
    return None


def _check_ooxml(path: str, head: bytes, ext: str) -> Optional[str]:
    if head.startswith(_OLE):
        return "password-protected or legacy binary Office file (cannot be inspected)"
    if not head.startswith(b"PK\x03\x04"):
        return f"not a {ext[1:].upper()} file (content does not match the extension)"
    try:
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
            if len(infos) > ZIP_MAX_ENTRIES:
                return "too many parts in the package"
            total = 0
            for info in infos:
                name = info.filename
                if name.startswith(("/", "\\")) or ".." in name.replace("\\", "/").split("/") or ":" in name:
                    return "unsafe part name in the package"
                if info.flag_bits & 0x1:
                    return "encrypted part in the package"
                total += info.file_size
                if total > ZIP_MAX_TOTAL:
                    return "package expands beyond the size limit (possible ZIP bomb)"
                if info.file_size > 65536 and info.compress_size and info.file_size / info.compress_size > ZIP_MAX_RATIO:
                    return "part with an abnormal compression ratio (possible ZIP bomb)"
            names = set(z.namelist())
    except zipfile.BadZipFile:
        return "damaged package"
    if "[Content_Types].xml" not in names or _MAIN_PART[ext] not in names:
        return f"not a valid {ext[1:].upper()} package"
    return None
