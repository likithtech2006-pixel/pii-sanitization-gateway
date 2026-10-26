"""A deliberately simple, independent reference pipeline.

It exists for three reasons:
  * to sanity-check the ground truth (a regex detector should find the
    structured items; whatever it cannot find shows where the gold is hard),
  * to give the metrics something to measure before the team's modules exist,
  * to act as the lower bar the team's detector has to beat.

It is NOT the project's detector.  Units are (location, text, modality) tuples.
"""
import os
import re
import subprocess

from evaluation.tools import build_ground_truth as B

MASK = "[REDACTED]"


def extract_units(path, pdf_ocr_dir=None):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pptx":
        return B.pptx_units(path)
    if ext == ".docx":
        return B.docx_units(path)
    if ext == ".pdf":
        if pdf_ocr_dir:
            return B.ocr_units(pdf_ocr_dir, "ocr_text")
        out = subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True, text=True).stdout
        return [({"page": i + 1}, t, "native_text") for i, t in enumerate(out.split("\f")) if t.strip()]
    raise ValueError("unsupported file type: %s" % ext)


def detect_units(units):
    """Regex detection -> list of finding dicts in the pipeline contract shape."""
    findings = []
    for idx, (loc, text, _mod) in enumerate(units):
        flat = re.sub(r"[ \t]+", " ", text)
        for typ, val, _l, _m in B.harvest_structured([(loc, flat, "x")]):
            findings.append({"type": typ.rstrip("?"), "text": val, "block_id": idx,
                             "source_location": dict(loc), "confidence": 0.9,
                             "validation_status": "valid", "detection_method": "regex"})
    return findings


def redact_units(units, findings):
    """Replace each finding's text inside its block with a mask."""
    out = []
    by_block = {}
    for f in findings:
        by_block.setdefault(f["block_id"], []).append(f["text"])
    for idx, (loc, text, mod) in enumerate(units):
        for val in sorted(set(by_block.get(idx, [])), key=len, reverse=True):
            text = text.replace(val, MASK)
        out.append(text)
    return out


def run(path, pdf_ocr_dir=None):
    units = extract_units(path, pdf_ocr_dir)
    findings = detect_units(units)
    return {
        "units": units,
        "original_units": [t for _, t, _ in units],
        "findings": findings,
        "sanitized_units": redact_units(units, findings),
        "verification_status": "SAFE",
        "blocks": [{"text": t, "location": l} for l, t, _ in units],
    }
