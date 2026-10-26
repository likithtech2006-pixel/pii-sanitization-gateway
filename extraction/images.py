"""Turn embedded picture bytes into a PIL image for OCR.

Raster formats (PNG, JPEG, GIF, BMP, TIFF) open directly. Windows vector
formats (EMF/WMF) are converted with LibreOffice when it is installed;
otherwise they are listed in the warnings as not scanned, so the report can
show that a human should look at them. Nothing leaves the machine.
"""
import io
import os
import shutil
import subprocess
import tempfile

from PIL import Image

Image.MAX_IMAGE_PIXELS = 120_000_000   # larger images raise DecompressionBombError instead of exhausting memory

MIN_SIDE = 100            # ignore icons, bullets and logos
_VECTOR = (".emf", ".wmf")


def _soffice():
    return shutil.which("soffice") or shutil.which("libreoffice")


def _convert_vector(blob, ext):
    """EMF/WMF -> PIL image via LibreOffice, or None."""
    exe = _soffice()
    if not exe:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "picture" + ext)
        with open(src, "wb") as fh:
            fh.write(blob)
        try:
            subprocess.run([exe, "--headless", "--convert-to", "png", "--outdir", tmp, src],
                           capture_output=True, timeout=120, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return None
        out = os.path.join(tmp, "picture.png")
        if not os.path.exists(out):
            return None
        with Image.open(out) as img:
            return img.convert("RGB")


def load_image(blob, name, meta=None):
    """PIL RGB image, or None when the picture cannot be read (a warning is recorded)."""
    ext = os.path.splitext(name)[1].lower()
    if ext in _VECTOR:
        img = _convert_vector(blob, ext)
        if img is None and meta is not None:
            meta.warnings.append(f"WARNING: picture {name} not scanned (vector image; install LibreOffice to OCR it)")
        return img
    if ext == ".svg":
        if meta is not None:
            meta.warnings.append(f"WARNING: picture {name} not scanned (SVG)")
        return None
    try:
        with Image.open(io.BytesIO(blob)) as img:
            return img.convert("RGB")
    except Exception:
        if meta is not None:
            meta.warnings.append(f"WARNING: picture {name} not scanned (unreadable image)")
        return None
