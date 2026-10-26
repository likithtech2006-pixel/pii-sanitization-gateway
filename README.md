# Secure Document Sanitization Pipeline

**Live demo:** https://pii-sanitization-gateway.streamlit.app (public instance; use the built-in fictional samples only)  ·
**Project site:** see the Vercel link in the repository description  ·
**Security model:** [SECURITY.md](SECURITY.md)

**Optiv Case Study 2.** Remove personal data (PII) from PDF, DOCX and PPTX files *before*
they are used with generative-AI tools, and prove that nothing was left behind.

The Cadence sample pack itself asks that its contents not be uploaded to generative-AI tools
(Organizational Pack, slide 9). This pipeline makes that possible safely. It extracts every piece
of text, including OCR of scanned pages, figures, screenshots and file properties. It detects PII,
replaces it with consistent placeholders, re-scans the result with an independent checker, and
releases the document only if that check is clean.

```
                ┌────────────┐   ┌────────────┐   ┌────────────┐   ┌──────────────────┐
  PDF/DOCX/PPTX │ extraction │──▶│ detection  │──▶│ redaction  │──▶│ verification     │──▶ SAFE ──▶ sanitized text / redacted file
                │ text, OCR, │   │ regex +    │   │ typed,     │   │ detector + indep.│          └─▶ AI layer (egress guard)
                │ figures,   │   │ NER + doc- │   │ consistent │   │ safety net;      │
                │ properties │   │ level names│   │ placeholder│   │ remediate, rescan│──▶ BLOCKED ─▶ report only
                └────────────┘   └────────────┘   └────────────┘   └──────────────────┘
```

Everything runs locally. Nothing leaves the machine unless you enable the Claude analysis with
an API key, and even then only the sanitized text of a SAFE document is sent.

## Results on the three Cadence files

| File | What is inside | Outcome | PII redacted | Time* |
|---|---|---|---|---|
| Organizational Pack (PPTX, 9 slides) | org charts, RACI tables, directory | **SAFE** – verified clean | 124 (17 people, 34 e-mails, 34 phones) | ~2 s |
| TPRM Training (DOCX, 85 pages) | config tables, user groups, 34 screenshots, file properties | **SAFE** | 50 (21 people incl. names inside screenshots and file properties) | ~15 s |
| Risk Management Policy (PDF, 35 **scanned** pages) | OCR only; tables, figures, a user-list screenshot, narrative case study | **SAFE** – verified clean | 979 (62 people, 192 staff ids, 174 e-mails, 175 phones, SSN, PAN, passport, DOB, home address…) | ~90 s |

\*2-core machine; OCR runs in parallel, so more cores are faster.

Independent evaluation against the ground truth (`docs/evaluation.md`):

| Metric | Result |
|---|---|
| Recall (required PII found) | **99.5 %** – PPTX 100 %, DOCX 100 %, PDF 99.4 % |
| Residual PII left in the sanitized output | **0** on all three files |
| Verifier said SAFE while PII remained | **0** |
| Source traceability (page / slide / table cell) | 99.6 % |
| Context kept (non-PII words surviving) | 98–100 % |
| Structure kept (pages / slides / tables) | 99.8–100 % |

The few remaining "misses" are boundary differences: the PII itself is redacted, but the span
differs from the gold label, for example a name split across two OCR blocks. The "false
positives" were reviewed by hand. Almost all of them are real PII that the regex-built gold does
not list: people without an e-mail address, the ten users in a screenshot, and fragments of phone
numbers that OCR split across table columns.

## Quick start

Requirements: Python 3.10+, the [Tesseract](https://github.com/tesseract-ocr/tesseract) OCR
binary, and optionally LibreOffice (only needed to OCR EMF/WMF pictures inside Office files).

```bash
# 1. Tesseract:  macOS: brew install tesseract   Ubuntu: sudo apt install tesseract-ocr
#    Windows: install from UB Mannheim, then set TESSERACT_CMD="C:\Program Files\Tesseract-OCR\tesseract.exe"
python -m venv .venv && source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt                             # includes the spaCy English model

# 2. Put the sample files in samples/ (git-ignored), then:
streamlit run app/main.py                                   # web UI
python pipeline.py                                          # CLI on everything in samples/
python pipeline.py samples/Cadence_Group_Risk_Management_Policy__v6.0.pdf --redacted-files --analyze
python -m pytest -q tests                                   # ~250 tests, fake data only
```

CLI outputs go to `output/` (git-ignored):

| File | When | Content |
|---|---|---|
| `<name>.report.json` | always | status, reason, counts per type, masked placeholder map, residuals – **no raw PII** |
| `<name>.sanitized.txt` | SAFE only | sanitized text, every block labelled with its source (`[page 21]`, `[slide 3 \| shape …]`) |
| `<name>.redacted.pdf/.docx/.pptx` | SAFE + `--redacted-files` | the original file with the same redactions, verified before it is kept |
| `<name>.analysis.md` | SAFE + `--analyze` | AI-layer brief of the sanitized document |

The exit code is 1 if any document was BLOCKED.

## The web app

`streamlit run app/main.py` – upload one or more files, then see:

* SAFE / BLOCKED with the reason, and metrics (blocks, PII found, redacted, people, needs review, time);
* findings per type with **masked** values, source location, confidence and detection method;
* the sanitized text, and a before/after view per redacted block (original text hidden unless you turn it on);
* the AI analysis of the sanitized text, with an optional question;
* downloads: sanitized text, JSON report, and the redacted file in its original format.

## How it works

| Stage | Module | Highlights |
|---|---|---|
| Extraction | `extraction/` | PDF text layer, or OCR for scanned pages (parallel Tesseract). Figures and small text are found from low-confidence OCR and re-read at 600 dpi. DOCX body, tables, headers/footers, **text boxes**, footnotes, comments and **screenshots** (OCR). PPTX shapes, groups, tables, notes and pictures. **File properties** (author, last modified by…) for all formats. Never raises: problems become warnings. |
| Detection | `detection/` | 35 regex/checksum recognizers (Luhn, IBAN, Verhoeff, SSN rules, OCR-tolerant e-mails/phones, staff ids) plus document-level person detection: spaCy NER, context cues, e-mail corroboration, table headers, a given-name lexicon, trimming of OCR column noise, and propagation of every spelling of a person. See [`docs/detection.md`](docs/detection.md). |
| Redaction | `redaction/redactor.py` | Exact span replacement with typed, consistent placeholders – one placeholder per *person*, not per spelling. Works on a copy; source location and block id kept on every block. |
| Verification gate | `redaction/gate.py`, `verifier.py` | Second scan with the detector **and** an independent regex safety net; residuals are redacted and rescanned; anything left → BLOCKED. Failed or partial extraction (e.g. no Tesseract for a scanned page) → BLOCKED, never "SAFE because nothing was read". See [`docs/redaction.md`](docs/redaction.md). |
| Redacted files | `redaction/file_writer.py` | PDF: true redaction boxes (pixels destroyed) using OCR word geometry, whole figures removed if they held PII, then verified by a 400 dpi OCR pass. DOCX/PPTX: every XML text node, property and link rewritten; screenshots with PII replaced. |
| AI layer | `ai_layer/` | Accepts only SAFE results; **egress guard** re-scans the outgoing text. Offline brief by default (structure, must/shall obligations, key terms, PII summary, passage retrieval for a question); Claude when `ANTHROPIC_API_KEY` is set. |
| Evaluation | `evaluation/` | Recall/precision per type and modality, residual-PII search, verifier consistency, traceability, context and structure retention, timing, regression check. See [`docs/evaluation.md`](docs/evaluation.md). |

### Security principles

* **Local by default** – OCR, NER and analysis run on the machine.
* **Fail closed** – unreadable or partially read documents, detector crashes and residual PII all block release.
* **Defence in depth** – detector, independent safety net, remediation loop, egress guard before the AI layer, and file re-verification.
* **No raw PII in reports or logs** – masked values (`Na*****be`) and per-run keyed hashes only.
* **Meaning is kept** – `[PERSON_3] approved the exception raised by [PERSON_7]` still supports analysis.
* **Traceable** – every finding and redaction points to its page, slide, shape, table cell, picture or property.

## Configuration

| Variable | Effect |
|---|---|
| `TESSERACT_CMD` | path to the Tesseract binary (Windows) |
| `OCR_WORKERS` | parallel OCR processes (default: CPU count, max 8) |
| `PII_SPACY_MODEL` | spaCy model (default `en_core_web_sm`; `en_core_web_lg` is more accurate) |
| `PII_DISABLE_NER=1` | rules-only name detection |
| `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` | enable Claude in the AI layer (sanitized text only) |

## Project layout

```
app/main.py              Streamlit UI
pipeline.py              process(), run_pipeline() (evaluation contract), CLI
extraction/              PDF/DOCX/PPTX extractors, OCR, figure detection, file properties
detection/               structured recognizers, person names, given-name lexicon
redaction/               redactor, verifier + safety net, gate, outputs, redacted-file writer
ai_layer/                downstream analysis behind the SAFE gate and egress guard
evaluation/              metrics, ground-truth tools, baseline, report generator
interfaces/, models/     shared contracts (NormalizedDocument, PIIFinding, Protocols)
scripts/                 redact_samples.py, dump_json.py (debug)
tests/                   unit + end-to-end tests on generated fake documents
docs/                    detection.md, redaction.md, evaluation.md
samples/, output/        local only (git-ignored) – real documents and results never get committed
```

## Limitations

* SAFE means two independent scans found no PII. It is not a mathematical guarantee. Vector
  pictures that cannot be OCR'd (EMF without LibreOffice, SVG) and handwriting are listed in the
  warnings for manual review.
* OCR quality bounds recall on scanned documents. Heavily degraded text can hide a value from
  every scan. That's why the PDF writer removes whole figures that contained PII.
* Security-first trade-off: business phone numbers, office addresses and staff ids are redacted
  too.
* Patterns cover the US/UK/EU/Indian formats in the test set. Other locales need patterns added.
