# Changelog

## Completed pipeline

### Added
- **`detection/`**: the PII detector the pipeline was missing. 35 regex/checksum recognizers,
  plus document-level person detection: spaCy NER, context cues, e-mail corroboration,
  table headers and row labels, file properties, a given-name lexicon, OCR-tolerant matching,
  and propagation of every spelling of a person under one `entity_key`.
- **`pipeline.py`**: `process()` (extract → detect → redact → verify), `run_pipeline()` for
  the evaluation harness, and a CLI with `--analyze` and `--redacted-files`.
- **`app/main.py`**: Streamlit UI (it was empty).
- **`ai_layer/`**: downstream analysis that accepts only SAFE documents and has an egress guard.
  Runs offline by default, or uses Claude when `ANTHROPIC_API_KEY` is set.
- **`redaction/file_writer.py`**: redacted copies in the original format (PDF/DOCX/PPTX),
  verified before they are kept; scanned PDFs are re-checked with OCR.
- **Extraction**
  - File properties (author, last modified by…) for all formats.
  - DOCX text boxes, footnotes, endnotes and comments.
  - OCR of DOCX screenshots; EMF/WMF pictures are converted via LibreOffice when present.
  - Figure / small-text regions on scanned pages are re-OCR'd at 600 dpi.
  - Parallel OCR: 35 scanned pages in ~80 s instead of ~12 min.
- **Tests**: `test_detection.py`, `test_ai_layer.py`, `test_file_writer.py`, real-detector
  end-to-end tests, and new extraction tests. ~250 tests in total.
- **Docs**: `README.md` (was empty), `docs/detection.md`, updated `docs/redaction.md` and
  `docs/evaluation.md`; `evaluation/tools/export_ocr.py` to rebuild the ground truth.

### Fixed
- `scripts/dump_json.py` used an old API (`doc.to_dict()`, `doc.blocks`) and crashed.
- **Evaluation adapter**: did not read the team's own models, so traceability showed 0 %.
- **Gold builder**: missed directory phone numbers without the `M` prefix.
- **E-mail normaliser**: did not tolerate an OCR `|.` prefix.
- **Redactor**: one placeholder per entity (`metadata["entity_key"]`), not one per spelling.
- **Safety net**: no longer reads "May 21. 2024 0431 PM" as a phone number.
- **PPTX pictures**: Tesseract missing now blocks only when a real picture was skipped, not
  for logos and icons.

### Results (three Cadence files)
All three are SAFE. Recall is 99.5 %, with 0 residual PII and 0 cases of the verifier saying
SAFE while PII remained. Details are in the README.
