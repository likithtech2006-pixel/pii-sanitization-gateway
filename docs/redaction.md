# Redaction & Verification (Security Gate)

Owner: Sanjay · Module: `redaction/` · Branch: `feature/redaction`

The last stage of the pipeline. It removes detected PII, rescans the sanitized
result, and decides whether the document may go to the downstream AI layer.

```
extract() → NormalizedDocument → detect() → PIIFinding[]
        → redact → verify (2nd scan) → [remediate residuals → rescan] → SAFE / BLOCKED
```

Nothing is released unless the final scan finds no PII within the detection scope.

## How to use it

```python
from redaction import sanitize_and_verify

result = sanitize_and_verify(document, findings, detector)   # detector: anything with .detect(doc)
result.status            # "SAFE" or "BLOCKED"
result.reason            # why (see table below)
result.released_text()   # sanitized text, or None when BLOCKED - only this goes downstream
result.to_dict()         # report for the UI / logs - contains no raw PII
```

Lower-level pieces, if you need them:

| Call | Returns |
|---|---|
| `redact(document, findings)` | `PlaceholderRedactionResult` (sanitized copy, `redacted_count`, `placeholder_map`, `skipped`, `counts_by_type()`) |
| `verify(document, detector=None)` | `SecondPassVerificationResult` (`is_safe`, `status`, `remaining_findings`, `safe_residuals()`) |
| `safety_net_scan(document)` | `PIIFinding[]` from the independent regex checks only |
| `redaction.output.write_outputs(result, dir)` | writes `<name>.report.json`, plus `<name>.sanitized.txt` only when SAFE |
| `redaction.output.evaluation_record(original, findings, result)` | dict in the evaluation module's pipeline contract |

Run the whole chain on the files in `samples/` (outputs go to the gitignored `output/`):

```bash
python scripts/redact_samples.py                 # uses the team detector (detection.detect)
python scripts/redact_samples.py --detector mypkg.mod:detect
```

The scanned PDF needs Tesseract (`brew install tesseract`). Without it, the PDF is BLOCKED rather than wrongly passed.

## Design decisions (and why)

**Typed, consistent placeholders.** `Jane Smith emailed John Doe` becomes
`[PERSON_1] emailed [PERSON_2]`. The same value always gets the same token, across
blocks and across passes, so the downstream LLM keeps who-did-what context without
the identity. A generic `[REDACTED]` would destroy that meaning. When the detector links
spellings of one person (`metadata["entity_key"]`: `Naomi K. Osadebe`, `N. Osadebe`,
`Osadebe`), they all get the same token.

**Span-based, never in place.** Redaction works on a deep copy and replaces exact
character spans right-to-left, so offsets stay valid and surrounding text is untouched.
Overlapping findings are merged and the longest one names the placeholder. Source
location (`page 3`, `slide 2 | shape …`, `table 0 | row 1 | col 1`) and block ids are kept
on every block, so each redaction is traceable.

**Robust finding location.** A finding is matched to its block by `metadata["block_id"]`,
then by `source`, then by searching for the value. Offsets may be block-relative or relative to
`full_text()`, including spans that cross a block boundary. Matching ignores case and
treats any whitespace or newline as equal, which matters for OCR text.

**Selection policy.** A finding is redacted when it is `validated` or its confidence is at least
0.5. Lower-confidence findings are not silently dropped: they are listed in `skipped` and counted
as `needs_review` in the report.

**Verification is a second, partly independent scan.** The sanitized document is
rescanned with (1) the team detector and (2) an independent regex safety net. If the
detector missed something, the safety net still catches it. Residuals are redacted and
the document is rescanned, up to 2 scans by default. If anything is still found after that,
the document is BLOCKED.

**Fail closed.** The gate never releases a document it could not verify:

| Status | Reason | When |
|---|---|---|
| SAFE | `verified_clean` | first rescan found nothing |
| SAFE | `verified_after_remediation` | residuals found, redacted, rescan clean |
| BLOCKED | `residual_pii` | PII still present after the last pass |
| BLOCKED | `extraction_failed` | extractor reported an error |
| BLOCKED | `incomplete_extraction` | pages skipped (e.g. scanned page, Tesseract missing) |
| BLOCKED | `no_content` | nothing extracted, so nothing was verified |
| BLOCKED | `verification_error` | detector crashed (only the exception type is recorded) |

**No raw PII in reports.** Reports and logs hold only masked values (`Ja******th`) and
keyed hashes. The hash key is random per run, so hashes of short values such as phone
numbers cannot be reversed with a lookup table.

## Safety-net checks

These are conservative on purpose, because a safety-net hit blocks or changes the output.

| Type | Rule |
|---|---|
| EMAIL | standard address; OCR variants (space around `@`, truncated before TLD) |
| PHONE | `+CC` international, `(555) 010-1234`, `+1 (555) 0100`; OCR fragments of split table cells (`+1 (303)` … `555-0999`, `7946 0001`) |
| SSN | `ddd-dd-dddd` (9xx kept: ITINs and test SSNs are still PII) |
| CREDIT_CARD | 13–19 digits **and** a valid Luhn checksum |
| IBAN | country + check digits **and** a valid mod-97 checksum |
| PAN | Indian PAN `AAAAA9999A` |
| PASSPORT | only right after the word "passport" |
| DOB | only when labelled `DOB` / `date of birth` / `born` |
| ADDRESS | `123 Name Street/Lane/…[, Apt 4C]`, `City, ST 12345` |
| IP_ADDRESS | IPv4 with every octet ≤ 255 |

Negative tests make sure ordinary content is **not** flagged: dates, years and year ranges,
versions, section numbers, percentages, issue/policy IDs (`ISS-2026-0112`, `POL-0042`) and
invalid card numbers.

## Redacted copies in the original format

`redaction/file_writer.py` writes the same redactions into a copy of the original file
(`python pipeline.py FILE --redacted-files`, or the checkbox in the app):

| Format | How |
|---|---|
| PDF | Black boxes labelled with the placeholder. Scanned pages use the OCR word boxes and the page-image pixels under each box are destroyed (`apply_redactions`), so nothing can be recovered by removing an overlay. A figure/screenshot that contained PII is removed as a whole. Properties are rewritten and XMP metadata is dropped. |
| DOCX / PPTX | Every text node of every XML part is rewritten (body, tables, headers, footers, text boxes, notes, comments, document properties, hyperlink targets). A value split over several runs is merged into the first run, so formatting is kept. Screenshots whose OCR text contained PII are replaced by a neutral image. |

Fail closed again: only SAFE documents are written, every redacted value must be absent from
the written file, and a redacted scanned PDF is re-OCR'd at 400 dpi; anything still readable
(small text in figures is often missed by the first OCR) is blacked out and the page is checked
again until a pass finds nothing. If that does not converge, no file is written.

## Results on the supplied files

With the team detector (`detection/`) connected:

| File | Blocks | Redacted | Outcome |
|---|---|---|---|
| Organizational Pack (PPTX) | 409 | 124 (56 person, 34 email, 34 phone) – 17 people | SAFE, clean on first rescan |
| TPRM Training (DOCX, incl. 34 screenshots OCR'd) | 1793 | 50 (49 person, 1 email) – 21 people | SAFE after remediation (1 OCR fragment caught by the safety net) |
| Risk Management Policy (PDF, 35 scanned pages) | 1026 | 979 (416 person, 192 employee id, 174 email, 175 phone, SSN, PAN, passport, DOB, address…) – 62 people | SAFE, clean on first rescan |

Independent evaluation (`docs/evaluation.md`): 0 residual PII values in any sanitized output and
the verifier's verdict agrees with the independent residual check on all three files.

What the real files taught us, now covered by tests:

- An un-OCR'd scanned PDF extracted to 0 blocks with status `ok` and would have "verified"
  as SAFE. This is now BLOCKED.
- PPTX phone numbers in the `+1 (555) 0100` format were missed at first (34 leaks). This is now caught.
- OCR of table columns splits phone numbers across lines. Each fragment is now redacted.
- Tiny text in figures (a user-list screenshot with names and e-mails) is not read by page OCR.
  The extractor now re-OCRs such regions at 600 dpi, and the PDF writer verifies its output with OCR.
- Names are spelled many ways in one file (`Naomi K. Osadebe`, `N. Osadebe`, `Osadebe`, OCR
  `Osadehe`); they now share one placeholder through the detector's `entity_key`.

## Limitations / next steps

- SAFE means "no PII found by two independent scans", not a mathematical guarantee. Text the
  extractors cannot read (vector EMF/SVG pictures without LibreOffice, handwriting) is reported in
  the warnings; review those documents manually.
- The safety net and the detector also redact business phone numbers and office addresses. We
  accept this over-redaction as the security-first trade-off.
- Regex patterns cover US/UK/EU/IN formats seen in the test set. Other locales need patterns added.
- First-name-only and surname-only mentions are redacted only for people confirmed elsewhere in
  the same document.

## Tests

```bash
pytest tests/test_redaction.py tests/test_verification.py tests/test_pipeline.py tests/test_file_writer.py -v
```

These tests use fake PII only, from synthetic documents and from DOCX/PPTX files generated on the fly
and run through the real extractor.
