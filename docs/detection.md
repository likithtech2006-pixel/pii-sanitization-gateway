# PII Detection

Module: `detection/` · Interface: `interfaces.detection.PIIDetector`

```python
from detection import detect, PIIDetectorImpl, detect_text, info
findings = detect(document)              # List[PIIFinding], block-relative offsets + block_id
detect_text("Contact jane@example.com")  # quick checks on a string
info()                                   # which engines are active
```

Detection runs fully locally. It has two layers that run over the **whole document**,
because a lot of evidence for a name lives somewhere else in the file (an e-mail address
on another slide, a column header, a document property).

## 1. Structured recognizers (`detection/patterns.py`)

Regular expressions plus validators. Precision comes from checksums and from requiring a
label where a value looks like an ordinary number or date.

| Type | Rule |
|---|---|
| EMAIL | standard; OCR damage (`n.osadebe @x.com`, `\|.brannstrom@x.com`, `thomas brown@x.com`, truncated `vist@cade`); tokens containing a known mail domain whose `@` was lost (`jobnsondpacmecorp.cor`) |
| PHONE | international `+CC …` incl. `+1 (555) 0114`; North-American; labelled (`Tel:`, `Mobile`); fragments of numbers split across table columns by OCR (`+44 20` … `7555 0129`), never swallowing a neighbouring date |
| SSN | `ddd-dd-dddd` with SSA validity rules; labelled with `.`/space separators (OCR); partial `SSN ending 4821` |
| PAN / AADHAAR / NATIONAL_ID / PASSPORT | Indian PAN (entity-type letter), Aadhaar (Verhoeff checksum), UK NINO, PESEL/TIN (labelled), passport (labelled, or `AA1234567`) |
| CREDIT_CARD / IBAN / BANK_ACCOUNT / FINANCIAL | Luhn; mod-97; labelled account numbers; `card ending 4421` |
| DOB | only when labelled (`DOB`, `date of birth`, `born`) – business dates are not PII |
| ADDRESS | street + suffix (+ unit, city, state, ZIP); `City, ST 12345`; UK postcode; labelled Indian PIN |
| IP_ADDRESS | IPv4 with valid octets (not `1.2.3.4`-style section numbers) |
| EMPLOYEE_ID | `EMP-41077`, `MER-IN-4471` (contractors), `DIR-0058` (directors), `CTR-`, `STF-`…; labelled staff/badge ids; OCR splits (`EMP-39 4`) |

Overlapping matches are resolved longest-first. Business identifiers such as `GRP-POL-001`,
`ISS-2026-0112`, `RSK-4488`, `CTL-IAM-04` are never matched (pinned by tests).

## 2. Person names (`detection/names.py`)

**Discovery** – candidates and their evidence (confidence):

| Evidence | Example | Confidence |
|---|---|---|
| staff id right after the name | `Naomi K. Osadebe (EMP-41077)` | 0.95 |
| e-mail corroboration | `Marguerite Vossberg` + `m.vossberg@…` anywhere in the file | 0.9 |
| document property | `author: [XY] Jane Example` | 0.9 |
| context cue before | `Led by …`, `Owner: …`, `approved by …`, `Dear …` | 0.85 |
| table column / row label | header `USERS`, `Name`, `Owner`; row label `Peer Reviewer`, `Author(s)` | 0.85 |
| title + surname | `Dear Ms Prieto-Ramos` | 0.85 |
| role right after | `…, Chief Risk Officer` | 0.8 |
| known given name + surname | `Amanda Singh` (lexicon of ~700 multicultural given names) | 0.75 |
| spaCy NER only | `Sneha M. Vaidyanathan` | 0.6 |

Candidates are cleaned before they are accepted:
* **Trimming** – OCR'd tables glue neighbouring cells onto names. Leading/trailing common
  words, a neighbour's initials or surname are cut: `High Yusuf O. Balogun` → `Yusuf O. Balogun`,
  `Environmental Risk Policy Yevgeni A. Sorokina` → `Yevgeni A. Sorokina`.
* **Rejection** – business vocabulary (`Risk Owner`, `Trigger Type`, `Vendor Created`), all-caps
  role lines, names followed by a legal-entity suffix (`Meridian Staffing Ltd`), and words that
  the same document also uses in lower case (a common word, not a name). Screenshot/figure OCR is
  excluded from that vocabulary because it is full of lower-case user names.

**Propagation** – every accepted person is searched for everywhere in all surface forms:
`Naomi K. Osadebe`, `Naomi Osadebe`, `N. Osadebe`, `N.K. Osadebe`, `NK Osadebe`, `Osadebe, Naomi`,
upper-case variants, a distinctive bare surname (`Osadebe`) or first name (`Rafael's`), and
OCR-damaged surnames one edit away after the right initials (`N. K Osadehe`). All forms share
`metadata["entity_key"]`, so the redactor gives them **one placeholder**.

NER never creates a name from screenshot OCR on its own (too noisy); the other evidence still applies.

## Without spaCy

`PII_DISABLE_NER=1` or a missing model switches to rules-only mode (`info()["ner"]` says so).
Cues, e-mail corroboration, tables, document properties and the given-name lexicon still work.
A different model can be set with `PII_SPACY_MODEL` (e.g. `en_core_web_lg`).

## Tests

```bash
pytest tests/test_detection.py tests/test_detection_cases.py -v
```
