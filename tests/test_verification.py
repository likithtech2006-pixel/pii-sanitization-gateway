"""Run from repo root:  pytest tests/test_verification.py -v
Uses synthetic documents with fake PII only - no real files needed."""
import json

import pytest

from models.document import ContentBlock, NormalizedDocument
from models.pii import PIIFinding
from redaction import BLOCKED, SAFE, SecondPassVerifier, sanitize_and_verify, verify


# ---------- helpers (fake data only) ----------
def make_doc(*texts, status=None):
    blocks = [ContentBlock(text=t, source=f"page {i + 1}", metadata={"block_id": f"d1-b{i}"})
              for i, t in enumerate(texts)]
    md = {"status": status} if status else {}
    return NormalizedDocument(document_id="d1", source_type="pdf", file_name="fake.pdf", content=blocks, metadata=md)


def finding(pii_type, value, source="page 1", confidence=0.95, validated=True):
    return PIIFinding(pii_type=pii_type, value=value, source=source, confidence=confidence,
                      detection_method="test", validated=validated)


class FakeDetector:
    """Stands in for the team detector: flags every occurrence of known values."""

    def __init__(self, values, confidence=0.9):
        self.values = values  # value -> type
        self.confidence = confidence

    def detect(self, document):
        out = []
        for block in document.content:
            for value, pii_type in self.values.items():
                start = block.text.find(value)
                while start != -1:
                    out.append(PIIFinding(pii_type, value, block.source, self.confidence, "fake",
                                          start, start + len(value), True,
                                          {"block_id": block.metadata.get("block_id", "")}))
                    start = block.text.find(value, start + 1)
        return out


class StubbornDetector:
    """Always reports a residual that cannot be located, so remediation can never succeed."""

    def detect(self, document):
        return [PIIFinding("PERSON", "Ghost Person", "page 1", 0.99, "fake", validated=True)]


# ---------- verifier ----------
def test_clean_document_is_safe():
    result = verify(make_doc("Vendor onboarding workflow for Tier 1 suppliers."))
    assert result.is_safe and result.status == SAFE
    assert result.remaining_findings == []


def test_placeholders_are_not_reported():
    detector = FakeDetector({"PERSON_1": "PERSON", "[EMAIL_1]": "EMAIL"})
    result = SecondPassVerifier(detector).verify(make_doc("Approved by [PERSON_1] via [EMAIL_1]."))
    assert result.is_safe
    assert result.checks == ["detector", "safety_net"]


def test_detector_residual_blocks():
    detector = FakeDetector({"Jane Smith": "PERSON"})
    result = SecondPassVerifier(detector).verify(make_doc("Owner Jane Smith"))
    assert not result.is_safe and result.status == BLOCKED
    assert result.remaining_findings[0].pii_type == "PERSON"


class LowConfidenceDetector:
    def detect(self, document):
        return [PIIFinding("PERSON", "Jordan", "page 1", 0.2, "fake")]  # not validated


def test_low_confidence_detector_hit_is_not_residual():
    assert SecondPassVerifier(LowConfidenceDetector()).verify(make_doc("Jordan river")).is_safe


@pytest.mark.parametrize("text, pii_type", [
    ("Contact jane.smith@example.com", "EMAIL"),
    ("SSN 123-45-6789", "SSN"),
    ("Card 4111 1111 1111 1111", "CREDIT_CARD"),
    ("IBAN GB82 WEST 1234 5698 7654 32", "IBAN"),
    ("Call +1 555-010-9999", "PHONE"),
    ("Call (555) 010-1234", "PHONE"),
    ("Call +44 20 7946 0958", "PHONE"),
    ("Mobile +1 (555) 0100", "PHONE"),
    ("PAN ABCDE1234F", "PAN"),
    ("Host 192.168.10.5", "IP_ADDRESS"),
    # OCR damage seen in the scanned PDF (fake values)
    ("Mail j.doe @example.com today", "EMAIL"),
    ("Treat jdoe@exam cor", "EMAIL"),
    ("Owner CFO 555-0999", "PHONE"),
    ("Deputy\n7946 0001", "PHONE"),
    ("Contact (+1 212\nnext meeting", "PHONE"),
    ("Doe, Group, +1 (303) Roe", "PHONE"),
    ("record (EMP-1, passport XY1234567) closed", "PASSPORT"),
    ("showing SSN 900-12-3456 today", "SSN"),
    ("Jane Roe (EMP-1, DOB 14 July 1991)", "DOB"),
    ("born on 03/04/1988 in town", "DOB"),
    ("home address at 12 Maple Lane, Apartment 4C. Later", "ADDRESS"),
    ("lives at 22 Palm Crescent now", "ADDRESS"),
    ("moved to Springfield, IL 62701 last year", "ADDRESS"),
])
def test_safety_net_catches_structured_pii(text, pii_type):
    result = verify(make_doc(text))
    assert not result.is_safe
    assert [f.pii_type for f in result.remaining_findings] == [pii_type]
    assert result.remaining_findings[0].metadata["block_id"] == "d1-b0"


@pytest.mark.parametrize("text", [
    "Policy v6.0 dated 2026-09-16",
    "See section 4.2.1 and page 12 of 82",
    "Opportunity Number: OP-4545941",
    "Invalid card 4111 1111 1111 1112",
    "Version 1.2.300.4",
    "Fiscal year 2025 revenue grew 12.5%",
])
def test_safety_net_ignores_ordinary_content(text):
    assert verify(make_doc(text)).is_safe


def test_safety_net_does_not_duplicate_detector_hits():
    detector = FakeDetector({"jane@example.com": "EMAIL"})
    result = SecondPassVerifier(detector).verify(make_doc("Mail jane@example.com"))
    assert len(result.remaining_findings) == 1
    assert result.remaining_findings[0].detection_method == "fake"


def test_needs_at_least_one_check():
    with pytest.raises(ValueError):
        SecondPassVerifier(None, safety_net=False)


def test_safe_residuals_hide_raw_values():
    result = verify(make_doc("jane.smith@example.com 123-45-6789"))
    dumped = json.dumps(result.safe_residuals())
    assert "jane.smith@example.com" not in dumped and "123-45-6789" not in dumped


# ---------- gate ----------
def test_gate_safe_when_all_pii_redacted():
    doc = make_doc("Owner Jane Smith, jane@example.com")
    detector = FakeDetector({"Jane Smith": "PERSON", "jane@example.com": "EMAIL"})
    result = sanitize_and_verify(doc, detector.detect(doc), detector)
    assert result.status == SAFE and result.reason == "verified_clean"
    assert result.passes == 1 and result.remediated_count == 0
    assert result.released_text() == "Owner [PERSON_1], [EMAIL_1]"
    assert result.document.metadata["verification_status"] == SAFE


def test_gate_remediates_pii_missed_by_detector():
    doc = make_doc("Owner Jane Smith, backup jsmith@example.org")
    result = sanitize_and_verify(doc, [finding("PERSON", "Jane Smith")])
    assert result.status == SAFE and result.reason == "verified_after_remediation"
    assert result.passes == 2 and result.remediated_count == 1
    assert result.released_text() == "Owner [PERSON_1], backup [EMAIL_1]"


def test_gate_blocks_unremovable_residual():
    result = sanitize_and_verify(make_doc("Text"), [], StubbornDetector(), max_passes=3)
    assert result.status == BLOCKED and result.reason == "residual_pii"
    assert result.passes == 3
    assert result.released_text() is None
    assert result.document.metadata["verification_status"] == BLOCKED


def test_gate_single_pass_blocks_without_remediation():
    result = sanitize_and_verify(make_doc("Mail jane@example.com"), [], max_passes=1)
    assert result.status == BLOCKED and result.passes == 1 and result.remediated_count == 0


def test_gate_blocks_failed_extraction():
    result = sanitize_and_verify(make_doc(status="error"), [])
    assert result.status == BLOCKED and result.reason == "extraction_failed"
    assert result.released_text() is None


def test_gate_blocks_document_with_no_text():
    result = sanitize_and_verify(make_doc(), [])
    assert result.status == BLOCKED and result.reason == "no_content"


def test_gate_blocks_scanned_pages_without_ocr():
    doc = make_doc("Readable page")
    doc.metadata["warnings"] = "page 2: looks scanned but Tesseract is not installed"
    result = sanitize_and_verify(doc, [])
    assert result.status == BLOCKED and result.reason == "incomplete_extraction"


class BrokenDetector:
    def detect(self, document):
        raise RuntimeError("model crashed on jane@example.com")


def test_gate_fails_closed_when_detector_errors():
    result = sanitize_and_verify(make_doc("Owner text"), [], BrokenDetector())
    assert result.status == BLOCKED and result.reason == "verification_error"
    assert result.error == "RuntimeError" and result.released_text() is None
    assert "jane@example.com" not in json.dumps(result.to_dict())
    assert result.document.metadata["verification_status"] == BLOCKED


def test_gate_accepts_none_findings():
    assert sanitize_and_verify(make_doc("Plain text"), None).status == SAFE


def test_blocked_extraction_marks_document_metadata():
    assert sanitize_and_verify(make_doc(), []).document.metadata["verification_status"] == BLOCKED


def test_gate_does_not_modify_input():
    doc = make_doc("Owner Jane Smith")
    sanitize_and_verify(doc, [finding("PERSON", "Jane Smith")])
    assert doc.content[0].text == "Owner Jane Smith"


def test_gate_report_is_json_safe_and_has_no_raw_pii():
    doc = make_doc("Owner Jane Smith, jane@example.com", "Maybe Jordan")
    findings = [finding("PERSON", "Jane Smith"),
                finding("PERSON", "Jordan", source="page 2", confidence=0.2, validated=False)]
    report = sanitize_and_verify(doc, findings).to_dict()
    dumped = json.dumps(report)
    for raw in ("Jane Smith", "jane@example.com"):
        assert raw not in dumped
    assert report["status"] == SAFE
    assert report["counts_by_type"] == {"PERSON": 1, "EMAIL": 1}
    assert report["needs_review"] == 1


def test_gate_rejects_invalid_max_passes():
    with pytest.raises(ValueError):
        sanitize_and_verify(make_doc("x"), [], max_passes=0)
