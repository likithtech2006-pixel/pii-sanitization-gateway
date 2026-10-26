"""Run from repo root:  pytest tests/test_detection.py -v
Unit tests for the detection module. Every value is fake (example.com, 555 numbers,
900-series SSNs, invented names). Many cases come from failures seen on the
Cadence sample files (OCR damage, table layouts, names glued to neighbours)."""
import pytest

from detection import PIIDetectorImpl, detect, detect_text, structured_spans
from detection.patterns import aadhaar_ok, iban_ok, luhn_ok, phone_ok, ssn_ok
from models.document import ContentBlock, NormalizedDocument


def found(text, pii_type=None):
    return [(f["type"], f["text"]) for f in detect_text(text) if pii_type is None or f["type"] == pii_type]


def values(text, pii_type):
    return [v for t, v in found(text, pii_type)]


def doc(*texts, sources=None, locations=None):
    blocks = []
    for i, t in enumerate(texts):
        md = {"block_id": f"b{i}"}
        if locations:
            md["location"] = locations[i]
        blocks.append(ContentBlock(t, (sources or [f"page {i + 1}"] * len(texts))[i], metadata=md))
    return NormalizedDocument("d", "docx", "d.docx", blocks)


# ------------------------------------------------------------- validators
def test_validators():
    assert luhn_ok("4111 1111 1111 1111") and not luhn_ok("4111 1111 1111 1112")
    assert iban_ok("GB82 WEST 1234 5698 7654 32") and not iban_ok("GB82 WEST 1234 5698 7654 33")
    assert aadhaar_ok("2341 2341 2346") and not aadhaar_ok("2341 2341 2345")
    assert ssn_ok("900-42-7781") and not ssn_ok("000-12-3456") and not ssn_ok("123-00-4567")
    assert phone_ok("+44 20 7555 0163") and not phone_ok("2025 2026") and not phone_ok("12345")


# ------------------------------------------------------- structured types
@pytest.mark.parametrize("text,pii_type,value", [
    ("mail jane.doe@example.com now", "EMAIL", "jane.doe@example.com"),
    ("OCR: n.osadebe @example.com", "EMAIL", "n.osadebe @example.com"),
    ("CISO —_c.whitfield@example.com, Over", "EMAIL", "c.whitfield@example.com"),
    ("Brannstrom |.brannstrom@example.com", "EMAIL", "|.brannstrom@example.com"),
    ("Treat vist@cade cor", "EMAIL", "vist@cade"),
    ("Mobile +1 (555) 0114", "PHONE", "+1 (555) 0114"),
    ("Office +44 20 7555 0163 now", "PHONE", "+44 20 7555 0163"),
    ("Call (212) 555-0147.", "PHONE", "(212) 555-0147"),
    ("+1 (212) 555-0158 30/09/2026", "PHONE", "+1 (212) 555-0158"),      # the date is not swallowed
    ("Tel: 020 7946 0001", "PHONE", "020 7946 0001"),
    ("SSN 900-42-7781 exposed", "SSN", "900-42-7781"),
    ("SSN 900-42.7781 (OCR)", "SSN", "900-42.7781"),
    ("social security number (4821)", "SSN", "4821"),
    ("PAN AQBPR7741L on file", "PAN", "AQBPR7741L"),
    ("Aadhaar 2341 2341 2346", "AADHAAR", "2341 2341 2346"),
    ("passport TK4820913 seen", "PASSPORT", "TK4820913"),
    ("card 4111 1111 1111 1111", "CREDIT_CARD", "4111 1111 1111 1111"),
    ("IBAN GB82 WEST 1234 5698 7654 32", "IBAN", "GB82 WEST 1234 5698 7654 32"),
    ("card ending 4421 was used", "FINANCIAL", "4421"),
    ("DOB 14 July 1991", "DOB", "14 July 1991"),
    ("date of birth: 03/08/1996", "DOB", "03/08/1996"),
    ("lives at 12 Elm Court, Springfield, NJ 07081", "ADDRESS", "12 Elm Court, Springfield, NJ 07081"),
    ("from 10.20.30.40 at night", "IP_ADDRESS", "10.20.30.40"),
    ("Owner EMP-41077 (Head)", "EMPLOYEE_ID", "EMP-41077"),
    ("EMP-37655_ Chief", "EMPLOYEE_ID", "EMP-37655"),
    ("contractor MER-IN-4471 support", "EMPLOYEE_ID", "MER-IN-4471"),
    ("director (DIR-0058)", "EMPLOYEE_ID", "DIR-0058"),
])
def test_structured_positive(text, pii_type, value):
    assert value in values(text, pii_type), found(text)


@pytest.mark.parametrize("text", [
    "See GRP-POL-001, ISS-2026-0112, RSK-4488, CTL-IAM-04 and INC-2026-0417.",
    "Version 6.0 approved on 30/09/2026; review 2025 2026 cycle.",
    "Section 4.2.1 and 1.2.3.4 list the steps; 125% coverage.",
    "Invalid card 4111 1111 1111 1112 should not match.",
    "Review on 15 April 2026 by the committee.",
    "Risk Manage May 21. 2024 0431 PM",
    "Growth +1.5% and +2 days later.",
    "Northwind Ltd and Veritrace Services are vendors.",
])
def test_hard_negatives(text):
    assert found(text) == [], found(text)


def test_overlaps_keep_longest():
    spans = structured_spans("call +1 (212) 555-0147 today")
    assert [s["value"] for s in spans] == ["+1 (212) 555-0147"]


def test_phone_fragments_from_split_table_cells():
    text = "PRA/ FCA X, +44 20 Tobias\n7555 0129\nNED (Chair) +1 14 Mar 2021"
    phones = values(text, "PHONE")
    assert set(phones) >= {"+44 20", "7555 0129", "+1"}
    assert "+1 14" not in phones                       # the day of the next column's date is kept


# ------------------------------------------------------------------ names
@pytest.mark.parametrize("text,name", [
    ("Approved by Ravi Kumar Shetty yesterday", "Ravi Kumar Shetty"),
    ("Owner: R. Shetty", "R. Shetty"),
    ("Chair Anna B. Fontaine (EMP-40001)", "Anna B. Fontaine"),
    ("Contact Lena Okafor-Reed", "Lena Okafor-Reed"),
    ("Led by Marguerite Vossberg", "Marguerite Vossberg"),
    ("Bienvenido T. Salcedo (MER- +63 917 555 0119", "Bienvenido T. Salcedo"),
    ("Dear Ms Prieto-Ramos, thank you", "Prieto-Ramos"),
    ("Amanda Singh waoda.sngi@example.com User", "Amanda Singh"),
])
def test_person_positive(text, name):
    assert name in values(text, "PERSON"), found(text)


@pytest.mark.parametrize("text", [
    "The Chief Risk Officer and the Board Chair approve.",
    "Trigger Type: Vendor Created; Rule Type: Workflow Rule.",
    "Meridian Staffing Ltd delivered the service.",
    "Artificial Intelligence and Generative AI tools.",
])
def test_person_negative(text):
    assert values(text, "PERSON") == [], found(text)


def test_names_glued_to_table_columns_are_trimmed():
    d = doc("ISS-2026-0104 High Yusuf O. Balogun (EMP-41522) y.balogun@example.com",
            "Strategic & Reputational Yevgeni A. Sorokina (EMP-38066) y.sorokina@example.com",
            "the reputational risk is high for all")
    names = {f.value for f in detect(d) if f.pii_type == "PERSON"}
    assert {"Yusuf O. Balogun", "Yevgeni A. Sorokina"} <= names
    assert not any(n.startswith(("High", "Reputational")) for n in names)


def test_email_corroborates_line_names_and_all_spellings_share_one_entity():
    d = doc("Naomi K. Osadebe", "n.osadebe@example.com", "Owner N. Osadebe signed; Osadebe agreed.",
            "Later NK Osadebe and N. K Osadehe (OCR) replied.")
    people = [f for f in detect(d) if f.pii_type == "PERSON"]
    assert {f.value for f in people} >= {"Naomi K. Osadebe", "N. Osadebe", "Osadebe", "NK Osadebe", "N. K Osadehe"}
    assert len({f.metadata["entity_key"] for f in people}) == 1


def test_table_column_header_marks_names():
    import json
    d = doc("USERS", "Marisol Quenby\nJT Harrow\nDelia Fenwick", "Peer Reviewer", "Arjun Pellow",
            locations=[json.dumps({"type": "table", "table": 1, "row": 0, "col": 3}),
                       json.dumps({"type": "table", "table": 1, "row": 1, "col": 3}),
                       json.dumps({"type": "table", "table": 2, "row": 5, "col": 0}),
                       json.dumps({"type": "table", "table": 2, "row": 5, "col": 1})])
    names = {f.value for f in detect(d) if f.pii_type == "PERSON"}
    assert names >= {"Marisol Quenby", "JT Harrow", "Delia Fenwick", "Arjun Pellow"}


def test_document_property_author():
    import json
    d = doc("Body text.", "[XY] Rohan Ellery",
            locations=[json.dumps({"type": "paragraph", "index": 0}), json.dumps({"type": "metadata", "field": "author"})])
    assert [f.value for f in detect(d) if f.pii_type == "PERSON"] == ["Rohan Ellery"]


def test_findings_point_at_exact_block_spans():
    d = doc("Contact jane.doe@example.com", "Owner: Rafael E. Duarte (EMP-41310). Rafael's record.")
    for f in detect(d):
        block = next(b for b in d.content if b.metadata["block_id"] == f.metadata["block_id"])
        assert block.text[f.start:f.end] == f.value
        assert f.source == block.source


def test_placeholders_are_ignored_on_rescan():
    d = doc("[PERSON_1] emailed [EMAIL_2] about [PHONE_3]")
    assert detect(d) == []


def test_rules_only_mode_still_finds_cued_names():
    d = doc("Approved by Ravi Kumar Shetty", "Contact jane@example.com")
    findings = PIIDetectorImpl(use_ner=False).detect(d)
    assert {(f.pii_type, f.value) for f in findings} >= {("PERSON", "Ravi Kumar Shetty"), ("EMAIL", "jane@example.com")}
