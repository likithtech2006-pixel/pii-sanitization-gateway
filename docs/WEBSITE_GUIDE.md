# PII Sanitization Gateway: Complete Website and System Guide

This file describes the whole project (what it does, how it is built, what every screen shows, and
how the code fits together) so that a person or another AI model can understand and work on it
**without opening the website or reading every source file**. Everything here was checked against
the code on 14 October 2026.

---

## 1. One-paragraph summary

The **PII Sanitization Gateway** is a local web app (Python + Streamlit) built for the
**Optiv Security VIT Internship Recruitment 2026, Case Study 2: Text Analysis and PII Detection**.
The fictional client, **Cadence** (a global financial services firm), lets employees use an AI
document-analysis agent, but its policy forbids personal data (PII) from reaching AI models. The app
takes a **PDF, DOCX or PPTX** file, extracts all text (including **OCR** for scanned pages and
screenshots), **detects PII**, replaces each value with a **typed, consistent placeholder** such as
`[PERSON_1]` or `[EMAIL_2]`, **re-scans** the result with a second, independent checker, and only then
marks the document **SAFE**. Anything it cannot verify is **BLOCKED** ("fail closed"). Only SAFE,
sanitized text can be downloaded or sent to the optional AI analysis step.

---

## 2. How to run it

| Item | Value |
|---|---|
| Language / runtime | Python 3.10+ (developed on 3.14), virtual environment in `.venv/` |
| Web framework | Streamlit 1.65 |
| Start command | `.venv/bin/streamlit run app/main.py` (from the project root) |
| URL | `http://localhost:8501` (default port) |
| External tools | **Tesseract** OCR binary (`brew install tesseract`); optional LibreOffice for EMF/WMF pictures |
| Install | `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt` (includes the spaCy model) |
| Tests | `.venv/bin/python -m pytest -q tests` → 247 passed, 3 skipped |
| Sample checks | `.venv/bin/python sample_test_cases/check_test_cases.py` → ALL PASS (2 known gaps) |
| CLI (no UI) | `.venv/bin/python pipeline.py <files> --out output [--redacted-files] [--analyze]` |

**Important:** after editing any Python file or `.streamlit/config.toml`, **restart** Streamlit
(Ctrl+C, then run again). The running server caches imported modules such as `app/ui.py`, so a
browser refresh alone often shows old code.

### Configuration

`.streamlit/config.toml`:

```toml
[theme.light]   # default look: white / light grey with orange accent
primaryColor = "#F36F21"; backgroundColor = "#F5F7FB"; secondaryBackgroundColor = "#EAEFF6"; textColor = "#0B1F3A"
[theme.dark]
primaryColor = "#F36F21"; backgroundColor = "#060D1A"; secondaryBackgroundColor = "#0F1F38"; textColor = "#E7EDF6"
[browser]
gatherUsageStats = false
```

Because both `[theme.light]` and `[theme.dark]` exist, Streamlit's **⋮ menu** offers *System / Light /
Dark*. The custom design follows whichever is active (see §8.3).

Environment variables:

| Variable | Effect |
|---|---|
| `ANTHROPIC_API_KEY` | If set, the AI-analysis tab uses Claude (sends **sanitized text only**); otherwise an offline local brief |
| `ANTHROPIC_MODEL` | Claude model id (default `claude-sonnet-5-5`) |
| `TESSERACT_CMD` | Path to Tesseract (Windows) |
| `OCR_WORKERS` | Parallel OCR processes (default: CPU count, max 8) |
| `PII_SPACY_MODEL` | spaCy model (default `en_core_web_sm`) |
| `PII_DISABLE_NER=1` | Rules-only name detection |

`.claude/launch.json` has two dev-server entries (`streamlit` on 8501 and `streamlit-8502` on 8502).
They are used by the Claude Code desktop app for previews and are not needed to run the app.

---

## 3. Repository map

```
OptivCaseStudy-main/
├── app/
│   ├── main.py            Streamlit page: layout, upload handling, tabs, downloads (≈180 lines)
│   └── ui.py              Design system: CSS tokens, animations, JS motion engine, HTML components (≈990 lines)
├── pipeline.py            process() = extract → detect → redact → verify; CLI; run_pipeline() for evaluation
├── extraction/            PDF/DOCX/PPTX extractors, OCR, figure re-OCR, file properties
│   ├── __init__.py        extract(file, filename) → NormalizedDocument (dispatch by extension, never raises)
│   ├── pdf_extractor.py   PyMuPDF text layer; OCR for scanned pages; small figure text re-read at 600 dpi
│   ├── docx_extractor.py  paragraphs, tables, headers/footers, text boxes, footnotes, comments, screenshots (OCR)
│   ├── pptx_extractor.py  shapes, groups, tables, speaker notes, pictures (OCR)
│   ├── ocr.py             Tesseract wrapper (parallel), is_available()
│   ├── figures.py, images.py, metadata.py, internal.py   helpers
├── detection/             PII detector
│   ├── __init__.py        PIIDetectorImpl.detect(doc), detect_text(str), info()
│   ├── patterns.py        35 regex/checksum recognizers (Luhn, Verhoeff, IBAN mod-97, SSN rules…)
│   ├── names.py           document-level person detection (NER + context + propagation)
│   └── lexicon.py         ~700 multicultural given names
├── redaction/
│   ├── redactor.py        span-exact, typed, consistent placeholders
│   ├── verifier.py        second-pass verifier + independent regex "safety net"
│   ├── gate.py            sanitize_and_verify() → GateResult (SAFE / BLOCKED + reason)
│   ├── output.py          sanitized_text(), report(), write_outputs()
│   └── file_writer.py     redacted copy in the original format (PDF/DOCX/PPTX), verified before kept
├── ai_layer/__init__.py   analyze(gate, question) — only SAFE input, egress guard, local or Claude provider
├── models/                document.py (ContentBlock, NormalizedDocument), pii.py (PIIFinding)
├── interfaces/            Protocol classes for extractor / detector / redactor / verifier
├── evaluation/            metrics, ground-truth tools, regex baseline, report generator
├── tests/                 pytest suite (fake data only)
├── sample_test_cases/     9 fictional test documents + expected outputs + checker (see §10)
├── scripts/               redact_samples.py, dump_json.py
├── docs/                  detection.md, redaction.md, evaluation.md, WEBSITE_GUIDE.md (this file)
├── presentation/          interview deck (.pptx), speaker notes, demo files, screenshots
├── samples/               real Cadence files go here (git-ignored, currently empty)
├── .streamlit/config.toml light + dark themes
└── requirements.txt
```

---

## 4. End-to-end processing flow

```
 Upload (PDF / DOCX / PPTX)
        │
        ▼
 1. EXTRACT  extraction.extract()
    text layer, tables, notes, text boxes, file properties; OCR for scans/screenshots
    → NormalizedDocument with ordered ContentBlocks, each tagged with its SOURCE
      e.g. "page 3", "table 0 | row 1 | col 2", "slide 2 | shape Table 2 | row 1 | col 1",
           "slide notes | slide 1 | paragraph 0", "metadata | field author",
           "paragraph | index 2 | image image1.png | image OCR"
        │
        ▼
 2. DETECT   detection.PIIDetectorImpl().detect(doc) → list[PIIFinding]
    a) 35 structured recognizers (regex + validators)
    b) person names across the whole document (evidence + propagation)
        │
        ▼
 3. REDACT   redaction.redactor (inside sanitize_and_verify)
    exact spans replaced right-to-left on a copy → [TYPE_n] placeholders
    redact if validated OR confidence ≥ 0.5; lower → "skipped" / needs_review
        │
        ▼
 4. VERIFY   second scan = team detector + independent regex safety net
    residuals found → redact them → rescan (max 2 scans total)
        │
        ▼
 5. GATE     SAFE (verified_clean | verified_after_remediation)
             BLOCKED (extraction_failed | incomplete_extraction | no_content |
                      residual_pii | verification_error)
        │
        ├── SAFE → sanitized text, JSON report, optional redacted file, optional AI analysis
        └── BLOCKED → report only; nothing released; AI button disabled
```

### 4.1 Extraction details
- **PDF**: native text via PyMuPDF. Pages without a text layer are rendered and OCR'd with
  Tesseract (in parallel). Low-confidence regions such as small figure text are re-OCR'd at 600 dpi.
- **DOCX**: body paragraphs, tables (cell coordinates kept), headers/footers, text boxes, footnotes,
  endnotes, comments, file properties, and **OCR of embedded screenshots**.
- **PPTX**: every shape including groups and tables, speaker notes, pictures (OCR), properties.
- Extraction **never raises**: problems become warnings in `doc.metadata["warnings"]`, and errors
  set `metadata["status"]="error"`. Unsupported extensions produce an `ERROR: unsupported file type` warning.

### 4.2 Detection details
**Structured recognizers** (`detection/patterns.py`):

| Type | Rule |
|---|---|
| EMAIL | standard plus OCR-damaged variants (space around `@`, lost `@`, truncated TLD) |
| PHONE | `+CC …`, North-American, labelled (`Tel:`, `Mobile`), OCR fragments split across table columns |
| SSN | `ddd-dd-dddd` with SSA validity rules; labelled variants; "SSN ending 4821" |
| PAN, AADHAAR (Verhoeff), NATIONAL_ID (UK NINO, PESEL/TIN labelled), PASSPORT | format + checksum/label |
| CREDIT_CARD (Luhn), IBAN (mod-97), BANK_ACCOUNT, FINANCIAL | validated or labelled |
| DOB | only when labelled (`DOB`, `date of birth`, `born`); business dates are not PII |
| ADDRESS | street + suffix (+ unit, city, state, ZIP), `City, ST 12345`, UK postcode, Indian PIN |
| IP_ADDRESS | IPv4 with valid octets |
| EMPLOYEE_ID | `EMP-41077`, `MER-IN-4471`, `DIR-0058`, `CTR-`, `STF-`, labelled staff/badge ids |

Overlaps are resolved longest-first. Business IDs (`GRP-POL-001`, `ISS-2026-0112`, `RSK-4488`,
`CTL-IAM-04`) are deliberately **not** matched.

**Person names** (`detection/names.py`) are found document-wide from evidence, with confidence:
staff ID right after the name (0.95), e-mail corroboration (0.9), document property (0.9), context
cue such as "approved by" (0.85), table column/row label such as `Name` or `Owner` (0.85),
title + surname (0.85), role right after (0.8), known given name + surname (0.75), spaCy NER only (0.6).
Candidates are trimmed (OCR table noise) and rejected if they are business vocabulary. Every accepted
person is then **propagated**: all spellings (`Naomi K. Osadebe`, `N. Osadebe`, `Osadebe`, upper case,
OCR one-edit variants) share one `metadata["entity_key"]`, so they get **one placeholder**.

### 4.3 Redaction, verification and the gate
- Placeholders are **typed and consistent**: the same person or value always gets the same tag across
  the whole document (`[PERSON_1]` everywhere), so an AI can still reason about who did what.
- Redaction works on a **deep copy**, replacing exact character spans right-to-left so offsets stay valid.
- The **safety net** (`redaction/verifier.py`) is an independent, conservative regex scan (EMAIL, PHONE,
  SSN, CREDIT_CARD with Luhn, IBAN with mod-97, PAN, PASSPORT after "passport", labelled DOB, ADDRESS,
  IP_ADDRESS). It catches what the main detector missed.
- **Gate reasons:**

| Status | Reason | When |
|---|---|---|
| SAFE | `verified_clean` | first rescan found nothing |
| SAFE | `verified_after_remediation` | residuals found, redacted, rescan clean |
| BLOCKED | `extraction_failed` | extractor reported an error (corrupt/protected file) |
| BLOCKED | `incomplete_extraction` | content skipped (e.g. scanned page with Tesseract missing) |
| BLOCKED | `no_content` | no text at all, so nothing was verified |
| BLOCKED | `residual_pii` | PII still present after the last pass |
| BLOCKED | `verification_error` | detector crashed (only the exception type is recorded) |

### 4.4 Outputs
- **Sanitized text** (SAFE only): every block as `[source]\ntext`, separated by blank lines.
- **JSON report** (always): contains **no raw PII**, only masked values (`Ra********ma`) and
  per-run keyed hashes.
- **Redacted file** (optional, SAFE only): PDFs get true redaction boxes with pixels destroyed, and
  figures containing PII are removed. DOCX/PPTX get every XML text node, property and hyperlink rewritten,
  and screenshots with PII replaced. The written file is re-verified (scanned PDFs re-OCR'd at 400 dpi) or not kept.

### 4.5 AI layer (`ai_layer/__init__.py`)
`analyze(gate, question=None)`:
1. Accepts only a SAFE `GateResult`, otherwise raises `AnalysisBlocked`.
2. **Egress guard**: re-scans the outgoing text with the safety net; any hit blocks the call.
3. Provider **local** (default, offline): summary sentence, section headings, "must/shall" obligations,
   key terms, PII counts by type, and simple passage retrieval for a question.
   Provider **anthropic** (when `ANTHROPIC_API_KEY` is set): POSTs sanitized text to
   `https://api.anthropic.com/v1/messages`, with a system prompt telling the model to keep placeholders and never re-identify.

---

## 5. Data models

```python
@dataclass
class ContentBlock:            # models/document.py
    text: str
    source: str                # human-readable location, e.g. "table 0 | row 1 | col 2"
    block_type: str = "text"
    metadata: Dict[str, str]   # block_id, location, redacted_spans, ...

@dataclass
class NormalizedDocument:
    document_id: str; source_type: str  # "pdf" | "docx" | "pptx"
    file_name: str
    content: List[ContentBlock]
    metadata: Dict[str, str]   # parser, ocr_used, status, warnings, block_count, error

@dataclass
class PIIFinding:              # models/pii.py
    pii_type: str              # PERSON, EMAIL, PHONE, SSN, ...
    value: str; source: str
    confidence: float; detection_method: str   # e.g. "regex", "context_cue+ner", "email_match+given_name+table_column"
    start: Optional[int]; end: Optional[int]
    validated: bool = False
    metadata: Dict[str, str]   # block_id, entity_key, ...
    def masked_value(self): ...  # "ra*************om"
```

`pipeline.process(file, filename)` returns a **PipelineResult** with `.status`, `.gate` (a GateResult),
`.findings`, `.original`, `.timings`, and `.summary()`, a dict that is safe to log:

```
file_name, status, reason, blocks, findings, redacted, remediated, residual, needs_review,
counts_by_type, people, ocr_used, warnings, timings{extract, detect, redact_verify}, seconds, engines
```

The **JSON report** (`redaction.output.report(gate)`) has these fields:

```
document_id, file_name, status, reason, error, verification_passes, checks ["detector","safety_net"],
redacted_count, remediated_count, counts_by_type, placeholders{ "[PERSON_1]": {type, masked, value_hash, occurrences} },
skipped, needs_review, residual_count, residuals, source_type,
extraction{parser, ocr_used, status, block_count}, redacted_blocks
```

In the app, the downloaded report also contains `"pipeline": <summary()>`.

---

## 6. The website, screen by screen

The page is a single Streamlit app with a **left sidebar** and a **main column** (max width 1180 px).
There are two states: **landing** (no files uploaded) and **results** (one or more files uploaded).

### 6.1 Global chrome (always visible)
- **Top header (Streamlit's own):** right side has the **Deploy** button (Streamlit Community Cloud
  publishing; not recommended here because documents would leave the machine) and the **⋮ menu**
  with *System / Light / Dark* theme icons, *Rerun (R)*, *Clear cache (C)*, *Print*, *Record screen*
  and the Streamlit version. The header is transparent at the top of the page and becomes a frosted
  glass bar once you scroll.
- **Scroll progress bar:** a 3 px orange → amber → blue gradient line at the very top that fills as you scroll.
- **Background:** soft radial colour glows, a slowly drifting blurred "aurora", a faint 56 px grid,
  and an **interactive particle network** on a full-screen canvas (see §8.2).

### 6.2 Sidebar
- **Brand:** orange rounded-square logo with a shield icon (gently "breathing" glow), title
  **"PII Gateway"**, subtitle **"Extract · detect · redact · verify"**.
- **ENGINES** (status cards, each with a pulsing coloured dot):
  - **OCR**: "Tesseract ready" (green) or "Not installed: scans will be BLOCKED" (red)
  - **Names**: e.g. "spacy 3.8.16 / en_core_web_sm" (green)
  - **Structured**: "35 regex/checksum recognizers" (green)
  - **AI analysis**: "Offline local brief", or "Claude (API key set)" (blue)
- **OPTIONS** (native Streamlit checkboxes):
  - "Also create a redacted PDF/DOCX/PPTX". Help: same redactions inside a copy of the original;
    scanned PDFs are re-OCR'd to verify (takes minutes).
  - "Show original text in the comparison view". Help: original contains raw PII; shown only on this machine.

### 6.3 Landing state (no files yet), top to bottom
1. **Hero** (two columns)
   - Eyebrow pill: **"PRIVACY-FIRST DOCUMENT AI"** (orange, pulsing dot)
   - Title **"PII Sanitization Gateway"**: very large, gradient text with a moving shimmer, which
     "decrypts" from random characters on load.
   - Lead text: *"Upload PDF, DOCX or PPTX files. Personal data is detected, replaced with consistent
     placeholders such as `[PERSON_3]` and `[EMAIL_2]`, then re-scanned by an independent check. Only
     **SAFE** documents are released to downloads or AI analysis."*
   - Four chips with icons: **Runs 100% locally · Fails closed · Source-traceable · No raw PII in reports**
   - Scroll hint: animated mouse icon + "Drop a document below, or scroll to see how it works"
   - Right side artwork: a stack of three document sheets in 3D. On the front sheet a scan beam sweeps
     down and grey text lines turn into orange `[PERSON_1]`, `[EMAIL_1]`, `[PHONE_1]` chips (6 s loop).
     Two dashed orbit rings rotate with satellites, floating chips `[SSN_1]`, `[IBAN_1]` and
     `[EMPLOYEE_ID_1]` bob up and down, and an orange shield badge sends out ripples. The whole artwork
     tilts toward the mouse.
2. **Ticker**: two infinite rows sliding in opposite directions (pause on hover). Each chip shows a
   struck-through fictional value and its tag, e.g. ~~rahul@example.com~~ `[EMAIL]`, ~~EMP-1042~~
   `[EMPLOYEE_ID]`. Types shown: PERSON, EMAIL, PHONE, SSN, PAN, PASSPORT, IBAN, CREDIT_CARD,
   EMPLOYEE_ID, ADDRESS, DOB, IP_ADDRESS, AADHAAR, NATIONAL_ID, BANK_ACCOUNT.
3. **Uploader**: label **"DOCUMENTS"**, a native Streamlit file uploader (PDF/DOCX/PPTX, multiple files,
   200 MB per file) styled as a glass card with a **rotating orange gradient border**.
4. **"HOW IT WORKS: Five stages, one gate"** (sub: "Nothing reaches the AI before the privacy check passes.")
   Five cards connected by a gradient beam that **fills as you scroll**:
   01 **Extract**: "Text, tables, notes and file properties, with OCR for scans and screenshots."
   02 **Detect**: "35 regex and checksum recognizers plus NER and document context for names."
   03 **Redact**: "Typed, consistent placeholders keep the meaning but remove identities."
   04 **Verify**: "A second, independent scan. Anything left over is remediated or blocked."
   05 **Release**: "Only SAFE text reaches downloads or AI, after an egress re-check."
5. **"BUILT IN: Engineered for reliability"**: four stat cards whose numbers **count up while scrolling**:
   **35** Recognizers (Regex plus Luhn, Verhoeff, mod-97 and SSN rules) · **3** Formats (PDF, DOCX
   and PPTX, including scanned pages) · **2** Independent scans (Detector and safety net before
   anything is released) · **247** Automated tests (All passing, all on fake data).
6. **"DESIGN PRINCIPLES: Privacy you can explain"**: three bento cards:
   - **One person, one tag**: four spellings (`Naomi K. Osadebe`, `N. Osadebe`, `Osadebe`,
     `NAOMI OSADEBE`) each linked by an animated line to `[PERSON_1]`.
   - **Fails closed**: two lanes. Green packets pass through an orange gate ("SAFE → RELEASED");
     red packets stop and burst at the gate ("BLOCKED → WITHHELD").
   - **Traceable to the cell**: location pills `page 21`, `slide 3 | Table 2 | row 1 | col 2`,
     `table 0 | row 2 | col 1`, `metadata | field author`.
7. Note: "Nothing uploaded yet. Try the fictional files in `sample_test_cases/inputs/` or the three Cadence sample files."
8. **Footer**: "Optiv Case Study 2 · Text Analysis & PII Detection".

### 6.4 Results state (after upload)
The hero and uploader stay at the top. The landing sections (4–7) are replaced, **for each uploaded
file in order**, by:

1. Spinners while working: "Loading detection models…" (first time only, loads spaCy), then
   "Processing <file>… (scanned PDFs need OCR and can take a minute)". Results are cached per browser
   session by SHA-256 of the file plus the "redacted file" option, so switching tabs does not re-run the pipeline.
2. **Document header card**: coloured file-type badge (PDF red, DOCX blue, PPTX orange), file name,
   pills (`N text blocks`, `OCR used` / `native text`, `N people`), and a **verdict pill**:
   - **✓ SAFE** (green) + "verified clean · 9 PII occurrences replaced, verified by a second independent scan."
     The card has a rotating green border.
   - **✕ BLOCKED** (red) + "extraction failed · Nothing is released for this document."
     The card pulses with a red glow.
3. **Pipeline tracker**: five nodes **Extract → Detect → Redact → Verify → Release** on a track that
   fills green, with a light pulse travelling along it when SAFE. Each node shows real numbers:
   "19 blocks · 0.01s", "9 findings · 0.02s", "9 replaced", "1 scan pass · 0.02s", "released".
   When BLOCKED, the failing stage turns red with an ✕ and shakes (Extract for extraction problems,
   Verify for residual/verification errors), and later stages show a 🔒 "locked".
4. **Six metric cards** (numbers count up): **Text blocks**, **PII found** (amber), **Redacted**
   (orange), **People**, **Needs review** (yellow if > 0), **Seconds**.
5. A yellow **warning** box if extraction produced warnings (e.g. the corrupt-file error message).
6. **Five tabs** (pill-style bar, glowing orange underline that slides between tabs):
   - **Sanitized text**: a scrollable viewer (max 560 px) with a sticky header ("19 blocks · 9
     placeholders · Hover a tag to highlight every occurrence."). Each block shows its source in small
     monospace with a pin icon, then the text. Placeholders are coloured chips by type; hovering one
     highlights every identical tag; tags blur into focus as they scroll in. BLOCKED shows
     "Withheld: the document is BLOCKED."
   - **Findings**: animated horizontal bars of counts per type, then a table with columns
     *type · value (masked) · source · confidence · method · validated*, plus a "Residual findings
     after the last scan" table if any.
   - **Compare**: a "Redacted block" dropdown listing changed blocks by source. Two code panels:
     **Original** (shows "(hidden - enable it in the sidebar)" unless the sidebar option is on) and **Sanitized**.
   - **AI analysis**: optional question box (placeholder "e.g. Who approves risk acceptance for
     critical risks?") and the button **"Run analysis on sanitized text"** (disabled for BLOCKED, with
     the caption "Disabled: BLOCKED documents never reach the AI layer."). The output is a Markdown brief.
   - **Report & downloads**: collapsible JSON report (report + pipeline summary) and buttons
     **Sanitized text (.txt)** (SAFE only), **Report (.json)**, and **Redacted PDF/DOCX/PPTX** (if the
     sidebar option is on and the document is SAFE; otherwise an error reason or "No redacted file for a BLOCKED document.").
7. Footer at the very end.

### 6.5 Example: real output for the fictional demo file `TC01_access_request.docx`
Status **SAFE (verified_clean)**: 19 blocks, 9 findings, 9 redacted, 3 people, 0 needs review.
Counts: PERSON 4 · EMAIL 3 · PHONE 1 · EMPLOYEE_ID 1.
```
[paragraph | index 1]      Employee: [PERSON_1]
[paragraph | index 2]      Email: [EMAIL_1]
[paragraph | index 3]      Phone: [PHONE_1]
[paragraph | index 4]      Employee ID: [EMPLOYEE_ID_1]
[paragraph | index 5]      Request: Access to the finance reporting system.
[table 0 | row 1 | col 1]  [PERSON_2]     [table 0 | row 1 | col 2]  [EMAIL_2]
[metadata | field author]  [PERSON_1]
```

---

## 7. How `app/main.py` is organised

1. Imports. Adds the project root and `app/` to `sys.path`, then `import ui`.
2. `st.set_page_config(page_title="PII Sanitization Gateway", page_icon="🛡️", layout="wide")`, then `ui.inject()`.
3. Sidebar: `st.sidebar.html(ui.sidebar_brand([...engines]))`, then the two checkboxes (`make_file`, `show_original`).
4. Helpers: `_warm_up()` (cached spaCy load), `_run(name, data, want_file)` (session-cached
   `process()` plus optional `write_redacted_file`), and `_findings_table(result)` (DataFrame of masked findings).
5. `st.html(ui.hero())` → `st.file_uploader("Documents", type=["pdf","docx","pptx"], accept_multiple_files=True)`.
6. No uploads: `st.html(ui.landing())`, `st.html(ui.footer())`, `st.stop()`.
7. For each upload: `summary`, `report`, then `ui.doc_header`, `ui.stepper`, `ui.metrics`, the warning, and the 5 tabs.
8. `st.html(ui.footer())`.

**Rule:** all pipeline logic lives outside `app/`. `main.py` only calls `process()`, `report()`,
`sanitized_text()`, `analyze()` and `write_redacted_file()`. `ui.py` only builds HTML/CSS/JS strings.

---

## 8. Front-end design system (`app/ui.py`)

### 8.1 Structure of `ui.py`
| Part | What it is |
|---|---|
| `_ICONS` + `icon(name, size)` | Line icons (file, scan, redact, shield, send, lock, check, x, chip, pin, eyeoff, user, gate) rendered as `<i class="lux-ico lux-i-NAME">` and drawn with CSS `mask` data-URIs, because `st.html` strips `<svg>` |
| `_TOKENS` | CSS custom properties for **light** (`:root`) and **dark** (`:root[data-lux-theme="dark"]`) |
| `_CSS` | All styles and keyframes (classes prefixed `lux-`) |
| `_JS` | One `<script>` that installs the CSS and runs the motion engine (§8.2) |
| `inject()` | `st.html(script, unsafe_allow_javascript=True)` with the CSS embedded as a JSON string |
| Components | `sidebar_brand`, `hero`, `ticker`, `landing`, `doc_header`, `stepper`, `metrics`, `sanitized_view`, `type_bars`, `footer` (each returns an HTML string; all document values pass through `html.escape`) |

### 8.2 Motion and interaction catalogue
| Effect | Trigger | Implementation |
|---|---|---|
| Intro splash ("Initializing secure gateway", spinning orange/blue rings) | first load per browser session | JS adds `#lux-splash` (sessionStorage key `luxSplash`), fades out with a circular clip after ~1.4 s, removed at 2.6 s |
| Particle network | always | `<canvas id="lux-net">`, ≤120 points drifting, linked when < 130 px apart, repelled by the cursor, orange lines to the cursor within 220 px; pauses when the tab is hidden; colours follow the theme |
| Cursor glow | mouse move | 640 px radial gradient following the pointer with smoothing (lerp 0.12); hidden on touch devices |
| Inertial smooth scroll | mouse wheel over the main column | wheel events are intercepted and the scroll eases toward the target in a time-based way (same feel at any frame rate); skipped inside the data table, dropdowns, text areas, JSON, nested scrollers, or with Ctrl/Shift |
| Scroll progress bar + glass header | scroll | JS updates `scaleX` and toggles `.lux-scrolled` on the header |
| Scroll reveals (rise from blur) | element enters view | CSS **scroll-driven animations** `animation-timeline: view()`; fallback to a time-based fade where unsupported (e.g. Firefox) |
| Hero parallax | scroll 0–560 px | `animation-timeline: scroll(nearest)`: artwork rises and fades, copy drifts |
| Pipeline beam fill, stat count-up, heading wipe, placeholder "decrypt" | scroll | view-timeline animations on `.lux-flow::before`, `.lux-stat .lux-count`, `.lux-section .lux-h2`, `.lux-viewer .lux-tag` |
| Count-up numbers | on show / scroll | pure CSS: `@property --lux-num` (integer) animated to `--to`, printed with `counter()` (a screen-reader copy is in `.lux-sr`) |
| Text "decrypt" | element visible | `[data-scramble]` elements are scrambled with random glyphs and resolved left-to-right (IntersectionObserver + MutationObserver) |
| 3D tilt + glare | hover on `.lux-tiltcard` | JS sets `--rx/--ry` (about ±6–7°) and glare position `--gx/--gy`; the card lifts 8 px and scales 1.02 |
| Spotlight border | hover on `.lux-spot` | radial gradient follows `--mx/--my`, plus a masked 1 px gradient border |
| Hero artwork tilt | mouse near the hero | `.lux-tilt` rotates up to ±16°/±12° |
| Magnetic buttons | hover on main-area buttons | JS sets the `translate` property toward the cursor |
| Button shine | hover | skewed white gradient sweeps across; background turns orange |
| Rotating gradient border | uploader; SAFE/BLOCKED card | `conic-gradient(from var(--lux-angle))`, angle animated via `@property` |
| Ticker | always | duplicated rows translated −50% in a loop; paused on hover |
| Tag cross-highlight | hover a placeholder | JS adds `.lux-hl` to every chip with the same text |
| Pipeline stepper | results | nodes pop in with staggered delays, the track grows, a light packet loops; the failed node shakes |
| Pulses / pings / ripples / breathing glow | always | small CSS keyframes on dots, badge and logo |

Reveal animations use the individual CSS properties `translate` and `scale`, not `transform`, so they
do not cancel the hover `transform` effects on the same element.

**Accessibility:** `prefers-reduced-motion: reduce` disables all animation, the splash, the canvas
motion, smooth scrolling and tilt. Count-up numbers have screen-reader text. Decorative artwork is
`aria-hidden`.

**Responsive:** at ≤1100 px the metrics grid becomes 3 columns. At ≤900 px the hero stacks, stages
become 2 columns, stats 2 columns, bento 1 column, and orbits, floating chips and the beam are hidden.
At ≤560 px most grids are 2 columns. There is no horizontal scrolling at 390 px width.

### 8.3 Light / dark theming
- The user picks the theme in Streamlit's **⋮ menu**. A script checks the computed text colour of
  `[data-testid="stApp"]` every 400 ms: light text means dark theme. It sets
  `<html data-lux-theme="light|dark">` and refreshes the particle colours.
- **Light tokens** (default): background `#F5F7FB`, glass panels `rgba(255,255,255,.74)`, text navy
  `#0B1F3A`, muted `#55657D`, accents orange `#F36F21`, green `#0E9F6E`, red `#E5484D`, blue `#2F6FEB`,
  violet `#7C5CFF`, yellow `#B7791F`, teal `#0E9AA0`.
- **Dark tokens:** background `#060D1A`, panels `rgba(15,31,56,.62)`, text `#E7EDF6`, muted `#8FA0BA`,
  brighter accents (green `#2ED19A`, red `#FF5E62`, blue `#5B9DFF`…). The cursor glow uses the `screen` blend mode.
- **Placeholder colours by type:** PERSON orange · EMAIL blue · PHONE violet · EMPLOYEE_ID yellow ·
  ADDRESS/DOB teal · SSN/CREDIT_CARD/IBAN/PAN/PASSPORT/AADHAAR/NATIONAL_ID red · BANK_ACCOUNT violet ·
  IP_ADDRESS blue · others green.
- **Fonts:** system stack (`-apple-system, SF Pro, Inter, Segoe UI, Roboto…`), monospace
  `SF Mono, ui-monospace, Menlo, Consolas`. No web fonts are downloaded.

### 8.4 Gotchas for anyone editing the UI
1. **`st.html` sanitizes HTML (DOMPurify):** it removes `<style>` and `<svg>` tags. So the CSS is
   installed by the script (`<style id="lux-css">` in `<head>`), and icons are CSS masks.
2. **The sanitizer deletes the whole `<script>`** if its text contains `<` followed by a letter or `/`
   anywhere (including comments and strings). Keep the JS free of markup strings and build DOM with
   `createElement`. The embedded CSS JSON escapes `<` as `<`. A quick check is to search the
   rendered script for the regex `<[/\w]`; it must find nothing.
3. Inline `style="--var:…"`, `class` and `data-*` attributes survive sanitization; that is how
   components pass values (`--to`, `--w`, `--c`, `--i`).
4. Streamlit's scroll container is `section[data-testid="stMain"]`, not the window.
5. Restart the server after edits, because modules are cached.
6. Useful Streamlit test ids: `stApp`, `stMain`, `stMainBlockContainer`, `stSidebar`, `stHeader`,
   `stMainMenu`, `stAppDeployButton`, `stFileUploader`, `stFileUploaderDropzone`, `stTabs`,
   `stDataFrame`, `stHtml`, `stElementContainer`; tab parts `[data-baseweb="tab"]`, `tab-highlight`, `tab-panel`.

---

## 9. Security and privacy properties

| Property | How it is achieved |
|---|---|
| Local by default | Extraction, OCR, NER and the default analysis run on the machine; no CDNs or web fonts in the UI |
| Fail closed | Failed or partial extraction, no content, detector crash or residual PII → BLOCKED |
| Defence in depth | Detector → independent safety net → remediation loop → gate → egress guard before AI → re-verification of redacted files |
| No raw PII in reports/logs | Masked values and per-run keyed hashes only |
| Meaning preserved | Typed, consistent placeholders (`[PERSON_3] approved the exception raised by [PERSON_7]`) |
| Traceable | Every block and finding carries its page / slide / shape / table cell / picture / property |
| UI safety | Every document-derived string is HTML-escaped before rendering; original text is hidden unless the user enables it |
| Not a guarantee | SAFE means "two independent scans found no PII", not a mathematical proof |

The **Deploy** button would publish the app to a hosted service, so documents would leave the
machine. It is intentionally not used.

---

## 10. Testing and evaluation

- **Unit and end-to-end tests:** `tests/` (pytest, fake data only), **247 passed, 3 skipped**. They
  cover extraction (incl. OCR, corrupt files), detection (hard negatives, overlaps, table fragments),
  redaction, verification and gate reasons, the AI layer (blocked documents, egress guard) and the file writer.
- **Sample test cases** (`sample_test_cases/`, all fictional, outputs recorded from real runs):

| Case | Tests | Expected |
|---|---|---|
| TC01 access_request.docx | paragraphs, table, author property | SAFE · 9 PII · 3 people |
| TC02 org_chart.pptx | table, text box, notes, 3 phone formats | SAFE · 11 PII · 4 people |
| TC03 hr_record.pdf | 10 PII types in a native PDF | SAFE · 10 PII |
| TC04 scanned_incident.pdf | image-only page → OCR | SAFE · 5 PII · OCR used |
| TC05 no_pii_policy.docx | hard negatives (IDs, dates, versions) | SAFE · 0 PII |
| TC06 name_variants.docx | 4 spellings → one tag | SAFE · 7 PII |
| TC07 corrupted.pdf | unreadable file | BLOCKED · extraction_failed |
| TC08 empty.docx | no body text | SAFE · 0 PII (the file-property block counts as content) |
| TC09 screenshot_in_docx.docx | PII inside an embedded image | SAFE · 3 PII |

  **Known gaps** these cases expose: TC06 leaves the bare first name "Rafael" unredacted. In TC09, OCR
  merged "Anita Patel" into "AnitaPatel", which was not detected. The checker reports both as KNOWN GAP.
- **Evaluation on the three real Cadence files** (from `docs/evaluation.md`, the team's harness; the
  files are not in this repo copy): recall **99.5 %** (1002/1007; PPTX 100 %, DOCX 100 %, scanned PDF
  99.4 %), **0** residual PII values, **0** false-SAFE verdicts, structure retention **99.8–100 %**
  (brief target ≥ 80 %), context retention 98.3–100 %, traceability 99.6 %. Precision vs. gold: PPTX/DOCX
  100 %, PDF 86 %; the manual review found most PDF "false positives" were real PII missing from the
  automatically built gold. The gold labels still need a human spot-check.

---

## 11. Limitations

- OCR quality bounds recall on degraded scans. Vector pictures (EMF without LibreOffice, SVG) and
  handwriting are flagged for manual review.
- Ambiguous names (names that are also common words); first-name-only mentions are only caught for
  people confirmed elsewhere in the same document.
- Identifier patterns cover the US/UK/EU/Indian formats seen in testing; other locales need new patterns.
- English-only NER model.
- A security-first trade-off: business phone numbers, office addresses and staff IDs are redacted too.
- The UI's scroll-driven effects need a modern Chromium or Safari; other browsers get simpler time-based fades.

---

## 12. Related deliverables

- `presentation/Optiv_Case_Study_2_PII_Detection.pptx`: a 13-slide interview deck (10 core + closing + 2 appendix).
- `presentation/Optiv_Presentation_Speaker_Notes.txt`: per-slide notes and 12 interview Q&As.
- `presentation/demo/`, `presentation/screenshots/`: fictional demo files and real app screenshots used in the deck.
- `sample_test_cases/README.md`: detailed expected output for every test case.

---

## 13. Quick "how do I…" for future changes

| Task | Where |
|---|---|
| Change hero / landing / footer text | `app/ui.py` → `hero()`, `landing()`, `footer()` |
| Change colours | `app/ui.py` → `_TOKENS` (both light and dark blocks), plus `.streamlit/config.toml` for native widgets |
| Add an icon | add SVG path data to `_ICONS`, then use `icon("name", size)` |
| Add a placeholder colour | `TAG_COLORS` in `app/ui.py` |
| Change what happens per file | `app/main.py` loop after `st.file_uploader` |
| Add a PII pattern | `detection/patterns.py` (and a test in `tests/test_detection.py`) |
| Change the confidence threshold or number of scans | `redaction/gate.py` → `sanitize_and_verify(threshold=0.5, max_passes=2)` |
| Change AI behaviour | `ai_layer/__init__.py` (`_local`, `_anthropic`, `_SYSTEM`) |
| Turn off motion for testing | enable "Reduce motion" in the OS accessibility settings |

---

## 14. Glossary

- **PII**: personally identifiable information (names, e-mails, phones, government IDs, employee IDs…).
- **OCR**: optical character recognition; turns images of text into text (Tesseract).
- **NER**: named-entity recognition; a language model that labels spans such as PERSON (spaCy).
- **Placeholder / tag**: a typed token such as `[PERSON_1]` that replaces a value consistently.
- **Safety net**: the independent regex scanner used during verification and at egress.
- **Gate**: the decision step that marks a document SAFE or BLOCKED.
- **Egress guard**: a final scan of the outgoing text right before the AI call.
- **Fail closed**: when in doubt, block. Never release unverified content.
- **Block / ContentBlock**: one unit of extracted text with its source location.
