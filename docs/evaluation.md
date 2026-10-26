# Testing, Evaluation & Metrics (branch `feature/evaluation`)

Owner: Jyothiraditya. Everything here measures the pipeline from outside; it never edits another owner's module.
The structured detection cases now run against the team detector by default (`tests/test_detection_cases.py`).

## What it measures
| Metric | How |
|---|---|
| Coverage / recall | required gold PII items found / required gold items (every occurrence counts) |
| False positives | findings that match no gold item; hard-negative hits (policy ids, case numbers...) reported separately |
| Residual PII | independent text search of the sanitized output for every required value; also catches a verifier that says SAFE while PII remains (`FALSE_SAFE`) and surname-only leaks |
| Traceability | findings carrying a page/slide/table location; wrong-page findings are reported as `misplaced` |
| Context retention | share of non-PII words that survive redaction (detects over-redaction) |
| Structure retention | page/slide/table coverage and word retention against an independent reference extraction (brief: >= 80%) |
| Processing time | seconds per document |
Also: type accuracy, recall by PII type and by modality (native text, table, OCR text, OCR figure, embedded image, metadata).

## Layout
- `evaluation/dataset.py` ground-truth schema, loader, validator. `required:false` items are never false positives and never penalised if missed.
- `evaluation/metrics.py` all metrics. `adapters.py` accepts both spec variants (`blocks`/`content_blocks`, `span`/`location`). `normalize.py` matching rules (digits must match exactly; email domain/OCR-tolerant; person surname must agree).
- `evaluation/test_cases.py` + `tests/` fake-data unit tests (safe to commit).
- `evaluation/baseline.py` independent regex reference pipeline (lower bar and sanity check).
- `evaluation/run_evaluation.py` produces `reports/last.json` and `last.md` (values masked), compares with a previous run, and exits non-zero on regression.
- `evaluation/tools/build_ground_truth.py` regenerates the gold for the three sample files.

## Commands
```
python -m pytest -q tests
python -m evaluation.run_evaluation --samples samples --pipeline pipeline:run_pipeline --pdf-ocr-dir <ocr folder> \
       --previous evaluation/reports/last.json --min-recall 0.98 --max-residual 0
python -m evaluation.run_evaluation --samples samples          # regex baseline (lower bar)
EVAL_DETECTOR=module:function python -m pytest tests/test_detection_cases.py   # default: detection:detect_text
```
Pipeline callable: `f(path) -> {findings, sanitized_units, original_units, verification_status, blocks, doc?}`;
`pipeline.run_pipeline` is the team pipeline. The adapters read the team models directly
(`NormalizedDocument.content`, `ContentBlock.metadata["location"]`, `PIIFinding.source` / `metadata["block_id"]`).

## Building the ground truth
The gold JSON is git-ignored (it holds the samples' raw PII). Rebuild it locally:
```
G=evaluation/ground_truth/local
python -m evaluation.tools.export_ocr --pdf samples/<policy>.pdf --docx samples/<training>.docx --out $G/ocr
python -m evaluation.tools.build_ground_truth --pptx samples/<pack>.pptx --docx samples/<training>.docx \
       --pdf-name <policy>.pdf --ocr-dir $G/ocr/pdf --fig-ocr-dir $G/ocr/pdf --docx-img-ocr $G/ocr/docx \
       --manual $G/manual.json --out $G/cadence_gold.json
python -m evaluation.run_evaluation --samples samples --pipeline pipeline:run_pipeline --pdf-ocr-dir $G/ocr/pdf
```
`export_ocr` writes one `p-<n>.png.txt` per PDF page and one `<image>.txt` per DOCX screenshot
(see its docstring for the `manual.json` format).
`--manual` adds hand-verified items the regex harvest cannot find: for the DOCX, the user-group
names (they have no e-mail addresses to anchor the name registry), names in screenshots, and the
file-property authors of all three files.

## Latest results (team pipeline, three Cadence files)

| Metric | Result |
|---|---|
| Recall (required PII found) | 99.5 % (1002/1007) – PPTX 100 %, DOCX 100 %, PDF 99.4 % |
| Precision vs. gold | PPTX 100 %, DOCX 100 %, PDF 86 % (see below) |
| Residual PII values left after redaction | 0 |
| Verifier said SAFE while PII remained | 0 (CONSISTENT on all three) |
| Traceability | 99.6 % |
| Type accuracy | 100 % |
| Context retention / structure retention | 98.3–100 % / 99.8–100 % |
| Processing time | ~105 s for all three (PDF OCR ~87 s on 2 cores) |

The 5 remaining misses are span-boundary differences (the PII itself is redacted): a name split
across two OCR blocks (`(A. P.` / `Brightwell)`), two gold artifacts where the builder joined
two people (`Marchetti-Lang M. Achebe`), and a name merged with its neighbour in a figure.
The PDF "false positives" were reviewed by hand. They are real PII missing from the regex-built
gold: people without an e-mail address (`Bienvenido T. Salcedo`, `Eleanor R. Vasquez-Holt`), the
ten users in the Figure 9 screenshot, OCR variants (`N. K Osadehe`, `CalebA. Whitfield`), and fragments of
phone numbers that OCR split across table columns (`+44 20` … `7555 0129`).

Bugs fixed in the evaluation along the way: the adapter did not read the team's own models
(traceability showed 0 %); the gold builder missed `+1 (555) 0114` directory numbers without the
`M` prefix; e-mail normalisation now tolerates an OCR `|.` / `!.` prefix.

## Ground-truth caveats
Gold lives in `evaluation/ground_truth/local/` (git-ignored: it contains the sample documents' raw PII). It was built by regex/registry harvesting over clean OCR plus manual items, then audited against an independent detector. Names inside figures and DOCX screenshots are partly optional, and the gold still needs a human spot-check.
