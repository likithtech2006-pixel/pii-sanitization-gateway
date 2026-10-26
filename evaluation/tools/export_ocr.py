"""Export the OCR text that build_ground_truth.py needs, using the project's extractor.

    python -m evaluation.tools.export_ocr --pdf samples/<policy>.pdf --docx samples/<training>.docx \\
        --out evaluation/ground_truth/local/ocr

Writes  <out>/pdf/p-<n>.png.txt   one file per PDF page (page OCR incl. re-read figures)
        <out>/docx/<image>.txt    one file per DOCX screenshot
Then:
    python -m evaluation.tools.build_ground_truth ... --ocr-dir <out>/pdf --fig-ocr-dir <out>/pdf \\
        --docx-img-ocr <out>/docx [--manual evaluation/ground_truth/local/manual.json] --out ...

The output contains raw text from the sample documents, so it belongs in the git-ignored
evaluation/ground_truth/local/ folder. A manual.json with hand-verified extra items has the shape
    {"_people": ["Jane Example"],
     "docx": [{"type": "PERSON", "value": "Jane Example", "location": {"row": 2},
               "required": true, "modality": "table", "verification": "visual"}]}
and is kept local for the same reason.
"""
import argparse
import collections
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from extraction import extract  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--docx", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)

    pdf_dir, docx_dir = os.path.join(a.out, "pdf"), os.path.join(a.out, "docx")
    os.makedirs(pdf_dir, exist_ok=True)
    os.makedirs(docx_dir, exist_ok=True)

    pages = collections.defaultdict(list)
    for b in extract(a.pdf).content:
        loc = json.loads(b.metadata["location"])
        if "page" in loc:
            pages[loc["page"]].append(b.text)
    for page, texts in pages.items():
        with open(os.path.join(pdf_dir, f"p-{page}.png.txt"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(texts))

    images = collections.defaultdict(list)
    for b in extract(a.docx).content:
        loc = json.loads(b.metadata["location"])
        if loc.get("image_ocr") and loc.get("image"):
            images[loc["image"]].append(b.text)
    for name, texts in images.items():
        with open(os.path.join(docx_dir, f"{name}.txt"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(texts))
    print(f"{len(pages)} PDF pages -> {pdf_dir}; {len(images)} DOCX pictures -> {docx_dir}")


if __name__ == "__main__":
    main()
