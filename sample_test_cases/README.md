# Sample Test Cases: Inputs and Expected Outputs

Nine fictional documents that exercise the PII pipeline, with the output the pipeline
actually produced for each (recorded on 13 Oct 2026, Tesseract + spaCy `en_core_web_sm`).
**Every name, e-mail, number and ID in these files is invented.**

```
sample_test_cases/
├── inputs/                 the 9 test documents (upload these)
├── expected_output/        <name>.report.json + <name>.sanitized.txt for each case
├── make_test_cases.py      regenerates inputs/
└── check_test_cases.py     re-runs everything and compares with expected_output/
```

## How to test

**In the web app:** start it, upload a file from `inputs/`, and compare the result banner, the
six metric tiles and the *Sanitized text* tab with the tables below.

```bash
.venv/bin/streamlit run app/main.py
```

**From the command line:** this re-runs all nine cases and prints PASS / FAIL / KNOWN GAP.

```bash
.venv/bin/python sample_test_cases/check_test_cases.py
```

## Summary

App tiles: **Blocks** = Text blocks, **PII** = PII found, **Red.** = Redacted, **People**, **Review** = Needs review.

| # | File | What it tests | Expected status | Blocks | PII | Red. | People | Review |
|---|---|---|---|---|---|---|---|---|
| TC01 | `TC01_access_request.docx` | Basic DOCX: paragraphs, table, file author | **SAFE** (verified clean) | 19 | 9 | 9 | 3 | 0 |
| TC02 | `TC02_org_chart.pptx` | PPTX table, text box, speaker notes, properties | **SAFE** (verified clean) | 21 | 11 | 11 | 4 | 0 |
| TC03 | `TC03_hr_record.pdf` | Native PDF with 10 different PII types | **SAFE** (verified clean) | 3 | 10 | 10 | 1 | 0 |
| TC04 | `TC04_scanned_incident.pdf` | Scanned PDF (image only) → OCR | **SAFE** (verified clean) | 5 | 5 | 5 | 2 | 0 |
| TC05 | `TC05_no_pii_policy.docx` | Hard negatives: IDs, dates, versions, % | **SAFE** (verified clean) | 7 | 0 | 0 | 0 | 0 |
| TC06 | `TC06_name_variants.docx` | One person, many spellings → one tag | **SAFE** (verified clean) | 7 | 7 | 7 | 2 | 0 |
| TC07 | `TC07_corrupted.pdf` | Unreadable file → fail closed | **BLOCKED** (extraction failed) | 0 | 0 | 0 | 0 | 0 |
| TC08 | `TC08_empty.docx` | Document with no body text | **SAFE** (verified clean) | 1 | 0 | 0 | 0 | 0 |
| TC09 | `TC09_screenshot_in_docx.docx` | PII inside an embedded screenshot (OCR) | **SAFE** (verified clean) | 5 | 3 | 3 | 1 | 0 |

The *Seconds* tile varies by machine. TC04 and TC09 take a little longer because of OCR.

---

## TC01 · Access request (DOCX)

**Input:** five labelled lines (employee, e-mail, phone, employee ID, request), a 3-row approval
table with two more people, and the file's *author* property set to the employee's name.

**Expected:** SAFE · PERSON 4 · EMAIL 3 · PHONE 1 · EMPLOYEE_ID 1

```
[paragraph | index 1]        Employee: [PERSON_1]
[paragraph | index 2]        Email: [EMAIL_1]
[paragraph | index 3]        Phone: [PHONE_1]
[paragraph | index 4]        Employee ID: [EMPLOYEE_ID_1]
[paragraph | index 5]        Request: Access to the finance reporting system.
[table 0 | row 1 | col 1]    [PERSON_2]        [table 0 | row 1 | col 2]  [EMAIL_2]
[table 0 | row 2 | col 1]    [PERSON_3]        [table 0 | row 2 | col 2]  [EMAIL_3]
[metadata | field author]    [PERSON_1]
```

**Check:** the author property gets the **same** tag as the employee (`[PERSON_1]`); the request line
and the business-justification paragraph are unchanged.

## TC02 · Org chart (PPTX)

**Input:** a contacts table with three people, their e-mails and phones in three formats
(`+1 (555) 0114`, `+44 20 7946 0018`, `+91 98450 12345`), a text box, and speaker notes that mention one person again.

**Expected:** SAFE · PERSON 5 · EMAIL 3 · PHONE 3

```
[slide 1 | shape Table 2 | row 1 | col 1..3]   [PERSON_1]  [EMAIL_1]  [PHONE_1]
[slide 1 | shape Table 2 | row 2 | col 1..3]   [PERSON_2]  [EMAIL_2]  [PHONE_2]
[slide 1 | shape Table 2 | row 3 | col 1..3]   [PERSON_3]  [EMAIL_3]  [PHONE_3]
[slide 1 | shape TextBox 3]   Escalations go to the Chief Risk Officer within 24 hours (policy RSK-4488).
[slide notes | slide 1]       Presenter: mention that [PERSON_2] covers the APAC region.
[metadata | field last_modified_by]   [PERSON_4]
```

**Check:** the speaker notes reuse `[PERSON_2]`. Role titles ("Chief Risk Officer") and the policy ID
`RSK-4488` are **not** redacted. `[PERSON_4]` is a real name: python-pptx's default template stores
its author in *last modified by*. This shows that file properties are scanned too.

## TC03 · HR record (native-text PDF)

**Input:** a selectable-text PDF with name, staff ID, date of birth, SSN, PAN, passport, home address,
credit card (`4111 1111 1111 1111`, Luhn-valid test number), IBAN (standard example) and IP address.

**Expected:** SAFE · one each of PERSON, EMPLOYEE_ID, DOB, SSN, PAN, PASSPORT, ADDRESS, CREDIT_CARD, IBAN, IP_ADDRESS

```
Name: [PERSON_1]                    Staff ID: [EMPLOYEE_ID_1]
Date of birth: [DOB_1]              SSN: [SSN_1]
PAN: [PAN_1]                        Passport number: [PASSPORT_1]
Home address: [ADDRESS_1]           Corporate card: [CREDIT_CARD_1]
Salary account IBAN: [IBAN_1]       Laptop IP address: [IP_ADDRESS_1]
Onboarding checklist: complete security awareness training (section 4.2) by 30 June 2026.
Policy reference: GRP-POL-001, version 6.0.
```

**Check:** the last two lines are untouched. A business date, section number, policy ID and version are not PII.
In *Report & downloads → JSON*, values appear only masked (e.g. `"masked": "21*******99"`).

## TC04 · Scanned incident report (image-only PDF)

**Input:** one page that is a picture of text (no text layer), so the extractor has to OCR it.

**Expected:** SAFE · PERSON 2 · EMAIL 1 · PHONE 1 · EMPLOYEE_ID 1 · report shows `"ocr_used": "true"`

```
Reported by: [PERSON_1]
Contact: [EMAIL_1]
Mobile: [PHONE_1]
Affected user: [PERSON_2] ([EMPLOYEE_ID_1])
Summary: phishing e-mail reported and quarantined.
Ticket ISS-2026-0112 closed on 12 May 2026.
```

**Check:** the ticket ID and date survive. Without Tesseract installed this file would be **BLOCKED**
(`incomplete_extraction`). It is never passed as "SAFE because nothing was read".

## TC05 · No PII (hard negatives)

**Input:** a policy summary full of things that *look* like identifiers: `GRP-POL-001`, version `6.0`,
section `3.1`, `100%`, `RSK-4488`, `CTL-IAM-04`, `ISS-2026-0112`, `2025-2026`, dates.

**Expected:** SAFE · **0 findings** · sanitized text identical to the input

**Check:** nothing is redacted. This is the false-positive test.

## TC06 · Name variants (DOCX)

**Input:** one person written four ways (`Naomi K. Osadebe`, `N. Osadebe`, `Osadebe`, `Naomi Osadebe`)
plus a second person, `Rafael Ortega`.

**Expected:** SAFE · PERSON 5 · EMPLOYEE_ID 1 · EMAIL 1

```
Attendees: [PERSON_1] ([EMPLOYEE_ID_1]), [PERSON_2]
[PERSON_1] opened the meeting and summarised the vendor risk score.
[PERSON_1] asked Rafael to collect the SOC 2 report by Friday.
Action: [PERSON_1] to approve the exception once the report is received.
Contact for questions: [EMAIL_1]
```

**Check:** all four spellings of Naomi share **`[PERSON_1]`**.
⚠️ **Known gap:** the bare first name **"Rafael"** in line 3 is *not* redacted, although `Rafael Ortega`
is. The gate still says SAFE, because first-name-only mentions are not scanned for independently.

## TC07 · Corrupted file

**Input:** a file named `.pdf` that is not a valid PDF.

**Expected:** **BLOCKED — extraction failed. Nothing is released for this document.** · 0 blocks ·
yellow warning `ERROR: could not extract (FileDataError …)` · *Sanitized text* tab says "Withheld" ·
the AI-analysis button is disabled · no `.sanitized.txt` is written (only the report).

## TC08 · Empty document

**Input:** a DOCX with no body text.

**Expected:** SAFE · 1 block · 0 findings. The single block is the file's *comments* property
(`generated by python-docx`), so there is content to verify. The `no_content` block applies only when
**nothing at all** is extracted.

## TC09 · Screenshot inside a DOCX

**Input:** a paragraph, an embedded PNG "screenshot" listing two users with names and e-mails, and
another paragraph.

**Expected:** SAFE · PERSON 1 · EMAIL 2

```
[paragraph | index 2 | image image1.png | image OCR]
User Administration - Active Users
jsmith [PERSON_1] [EMAIL_1]
apatel AnitaPatel [EMAIL_2]
```

**Check:** text inside the image was OCR'd and both e-mails were redacted, with the source labelled `image OCR`.
⚠️ **Known gap:** OCR read "Anita Patel" as **"AnitaPatel"** (no space), and that merged token was not
detected. The usernames `jsmith` / `apatel` are also left. For screenshots, the redacted-file writer
replaces any image whose OCR text contained PII, but the sanitized *text* still shows the merged name.

---

## Known gaps found by these tests

| Case | What leaks | Why | Possible fix |
|---|---|---|---|
| TC06 | Bare first name `Rafael` | Name propagation covers distinctive surnames and some first names, but not this one | Propagate the first name of every confirmed person when it is capitalised and not a common word |
| TC09 | `AnitaPatel` (OCR merged two words) | Neither the name detector nor the safety net splits camel-case OCR tokens | Split merged CamelCase tokens before name matching; treat user lists in screenshots as PII by default |

`check_test_cases.py` reports these as **KNOWN GAP**, not FAIL. If a fix lands, remove the value from
`KNOWN_GAPS` in the script and refresh `expected_output/`:

```bash
.venv/bin/python pipeline.py sample_test_cases/inputs/* --out sample_test_cases/expected_output
```
