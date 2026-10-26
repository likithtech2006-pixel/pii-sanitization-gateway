"""Local OCR helpers (Tesseract). Nothing leaves the machine."""
import os
import shutil

import pytesseract
from PIL import Image, ImageOps

# Windows: set env var TESSERACT_CMD="C:\Program Files\Tesseract-OCR\tesseract.exe"
# We run several Tesseract processes in parallel; one thread each avoids oversubscribing the CPU.
os.environ.setdefault("OMP_THREAD_LIMIT", "1")

if os.getenv("TESSERACT_CMD"):
    pytesseract.pytesseract.tesseract_cmd = os.getenv("TESSERACT_CMD")


def workers() -> int:
    """Parallel OCR processes (env OCR_WORKERS, default: CPU count, max 8)."""
    try:
        n = int(os.getenv("OCR_WORKERS", "0"))
    except ValueError:
        n = 0
    return max(1, min(8, n or os.cpu_count() or 2))


def is_available() -> bool:
    cmd = pytesseract.pytesseract.tesseract_cmd
    return shutil.which(cmd) is not None or os.path.exists(cmd)


def preprocess(img: Image.Image) -> Image.Image:
    """Grayscale + auto-contrast. Cheap and noticeably improves scans."""
    return ImageOps.autocontrast(ImageOps.grayscale(img))


def ocr_image(img: Image.Image, dpi: int = 300, lang: str = "eng"):
    """OCR one PIL image.

    Returns a list of paragraph dicts:
      {"text": str, "bbox": (x0,y0,x1,y1) in PDF points, "conf": float,
       "words": [[x0,y0,x1,y1,"word"], ...]}
    Coordinates are scaled from pixels to PDF points (72 per inch) so Sanjay
    can draw redaction boxes directly on the PDF page.
    """
    scale = 72.0 / dpi
    data = pytesseract.image_to_data(
        preprocess(img), lang=lang, output_type=pytesseract.Output.DICT
    )
    paragraphs = {}  # (block, par) -> dict
    for i, word in enumerate(data["text"]):
        word = word.strip()
        try:
            conf = float(data["conf"][i])
        except ValueError:
            conf = -1
        if not word or conf < 0:
            continue
        key = (data["block_num"][i], data["par_num"][i])
        x0, y0 = data["left"][i] * scale, data["top"][i] * scale
        x1 = x0 + data["width"][i] * scale
        y1 = y0 + data["height"][i] * scale
        p = paragraphs.setdefault(key, {"lines": {}, "words": [], "confs": []})
        p["lines"].setdefault(data["line_num"][i], []).append(word)
        p["words"].append([round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1), word])
        p["confs"].append(conf)

    out = []
    for key in sorted(paragraphs):
        p = paragraphs[key]
        text = "\n".join(" ".join(p["lines"][ln]) for ln in sorted(p["lines"]))
        ws = p["words"]
        bbox = (min(w[0] for w in ws), min(w[1] for w in ws),
                max(w[2] for w in ws), max(w[3] for w in ws))
        out.append({"text": text, "bbox": tuple(round(v, 1) for v in bbox),
                    "conf": round(sum(p["confs"]) / len(p["confs"]), 1),
                    "words": ws})
    return out