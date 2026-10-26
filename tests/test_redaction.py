"""Run from repo root:  pytest tests/test_redaction.py -v
Uses synthetic documents with fake PII only - no real files needed."""
import json

import pytest

from models.document import ContentBlock, NormalizedDocument
from models.pii import PIIFinding
from redaction import PLACEHOLDER_RE, PlaceholderRedactor, redact


# ---------- helpers (fake data only) ----------
def make_doc(*texts, sources=None):
    blocks = []
    for i, text in enumerate(texts):
        source = sources[i] if sources else f"paragraph {i}"
        blocks.append(ContentBlock(text=text, source=source, metadata={"block_id": f"d1-b{i}"}))
    return NormalizedDocument(document_id="d1", source_type="docx", file_name="fake.docx", content=blocks)


def finding(pii_type, value, source="paragraph 0", confidence=0.95, start=None, end=None,
            validated=True, block_id=None):
    md = {"block_id": block_id} if block_id else {}
    return PIIFinding(pii_type=pii_type, value=value, source=source, confidence=confidence,
                      detection_method="test", start=start, end=end, validated=validated, metadata=md)


# ---------- core behaviour ----------
def test_replaces_value_with_typed_placeholder():
    doc = make_doc("Email jane.smith@example.com for access.")
    result = redact(doc, [finding("EMAIL", "jane.smith@example.com", start=6, end=28)])
    assert result.document.content[0].text == "Email [EMAIL_1] for access."
    assert result.redacted_count == 1


def test_original_document_is_not_modified():
    doc = make_doc("Call +1 555-010-9999 today.")
    redact(doc, [finding("PHONE", "+1 555-010-9999")])
    assert doc.content[0].text == "Call +1 555-010-9999 today."


def test_same_value_gets_same_placeholder_across_blocks():
    doc = make_doc("Jane Smith owns the vendor.", "Escalate to Jane Smith.", "John Doe reviews.")
    findings = [finding("PERSON", "Jane Smith", source="paragraph 0"),
                finding("PERSON", "Jane Smith", source="paragraph 1"),
                finding("PERSON", "John Doe", source="paragraph 2")]
    texts = [b.text for b in redact(doc, findings).document.content]
    assert texts == ["[PERSON_1] owns the vendor.", "Escalate to [PERSON_1].", "[PERSON_2] reviews."]


def test_placeholders_numbered_in_document_order():
    doc = make_doc("John Doe and Jane Smith")
    # Findings arrive in reverse order; numbering still follows the text.
    findings = [finding("PERSON", "Jane Smith"), finding("PERSON", "John Doe")]
    assert redact(doc, findings).document.content[0].text == "[PERSON_1] and [PERSON_2]"


def test_multiple_findings_in_one_block_keep_offsets_valid():
    text = "Name: Jane Smith, SSN 123-45-6789, email jane@example.com"
    doc = make_doc(text)
    findings = [finding("PERSON", "Jane Smith", start=6, end=16),
                finding("SSN", "123-45-6789", start=22, end=33),
                finding("EMAIL", "jane@example.com", start=41, end=57)]
    assert redact(doc, findings).document.content[0].text == "Name: [PERSON_1], SSN [SSN_1], email [EMAIL_1]"


def test_context_around_pii_is_preserved():
    doc = make_doc("Approved by Jane Smith on 2026-09-16 for vendor onboarding.")
    out = redact(doc, [finding("PERSON", "Jane Smith")]).document.content[0].text
    assert out.startswith("Approved by ") and out.endswith(" on 2026-09-16 for vendor onboarding.")


# ---------- locating findings ----------
def test_wrong_offsets_fall_back_to_value_search():
    doc = make_doc("Contact jane@example.com")
    result = redact(doc, [finding("EMAIL", "jane@example.com", start=0, end=5)])
    assert result.document.content[0].text == "Contact [EMAIL_1]"


def test_block_id_takes_priority_over_source():
    doc = make_doc("Jane Smith", "Jane Smith", sources=["slide 1", "slide 1"])
    result = redact(doc, [finding("PERSON", "Jane Smith", source="slide 1", block_id="d1-b1", start=0, end=10)])
    assert [b.text for b in result.document.content] == ["Jane Smith", "[PERSON_1]"]


def test_missing_offsets_redact_every_occurrence_in_block():
    doc = make_doc("Jane Smith wrote to Jane Smith.")
    result = redact(doc, [finding("PERSON", "Jane Smith")])
    assert result.document.content[0].text == "[PERSON_1] wrote to [PERSON_1]."
    assert result.redacted_count == 2


def test_unknown_source_searches_all_blocks():
    doc = make_doc("intro", "Reach jane@example.com")
    result = redact(doc, [finding("EMAIL", "jane@example.com", source="unknown")])
    assert result.document.content[1].text == "Reach [EMAIL_1]"


def test_value_search_respects_word_boundaries():
    doc = make_doc("Al met Alan and Sal.")
    out = redact(doc, [finding("PERSON", "Al")]).document.content[0].text
    assert out == "[PERSON_1] met Alan and Sal."


def test_value_search_is_case_insensitive():
    doc = make_doc("JANE SMITH signed.")
    assert redact(doc, [finding("PERSON", "Jane Smith")]).document.content[0].text == "[PERSON_1] signed."


def test_overlapping_findings_are_merged():
    doc = make_doc("Contact Jane Smith-Brown now")
    findings = [finding("PERSON", "Jane Smith", start=8, end=18),
                finding("PERSON", "Jane Smith-Brown", start=8, end=24)]
    result = redact(doc, findings)
    assert result.document.content[0].text == "Contact [PERSON_1] now"
    assert result.redacted_count == 1


# ---------- selection / skipped ----------
def test_low_confidence_unvalidated_finding_is_skipped():
    doc = make_doc("Maybe Jordan")
    result = redact(doc, [finding("PERSON", "Jordan", confidence=0.2, validated=False)])
    assert result.document.content[0].text == "Maybe Jordan"
    assert result.skipped[0]["reason"] == "below_threshold"


def test_unvalidated_finding_above_threshold_is_redacted():
    doc = make_doc("Owner Jordan Lee")
    result = redact(doc, [finding("PERSON", "Jordan Lee", confidence=0.6, validated=False)])
    assert result.document.content[0].text == "Owner [PERSON_1]"


def test_threshold_is_configurable():
    doc = make_doc("Owner Jordan Lee")
    result = PlaceholderRedactor(threshold=0.9).redact(
        doc, [finding("PERSON", "Jordan Lee", confidence=0.6, validated=False)])
    assert result.redacted_count == 0


def test_finding_not_in_document_is_reported_as_not_located():
    doc = make_doc("Nothing sensitive here")
    result = redact(doc, [finding("EMAIL", "ghost@example.com")])
    assert result.skipped[0]["reason"] == "not_located"
    assert result.redacted_count == 0


def test_empty_value_is_skipped():
    result = redact(make_doc("text"), [finding("EMAIL", "")])
    assert result.skipped[0]["reason"] == "empty_value"


# ---------- safe reporting ----------
def test_result_never_contains_raw_values():
    doc = make_doc("Email jane.smith@example.com, phone +1 555-010-9999")
    findings = [finding("EMAIL", "jane.smith@example.com"), finding("PHONE", "+1 555-010-9999"),
                finding("SSN", "987-65-4321", confidence=0.1, validated=False)]
    result = redact(doc, findings)
    dumped = json.dumps({"map": result.placeholder_map, "skipped": result.skipped,
                         "text": [b.text for b in result.document.content]})
    for raw in ("jane.smith@example.com", "+1 555-010-9999", "987-65-4321"):
        assert raw not in dumped


def test_counts_by_type_and_metadata():
    doc = make_doc("Jane Smith, Jane Smith, jane@example.com")
    result = redact(doc, [finding("PERSON", "Jane Smith"), finding("EMAIL", "jane@example.com")])
    assert result.counts_by_type() == {"PERSON": 2, "EMAIL": 1}
    assert result.document.metadata["redacted_count"] == "3"
    assert result.document.content[0].metadata["redacted_spans"] == "3"


def test_pii_type_is_normalized_in_placeholder():
    doc = make_doc("Acct 00123456")
    out = redact(doc, [finding("account id", "00123456")]).document.content[0].text
    assert out == "Acct [ACCOUNT_ID_1]"
    assert PLACEHOLDER_RE.fullmatch("[ACCOUNT_ID_1]")


def test_source_and_block_metadata_are_kept():
    doc = make_doc("Jane Smith", sources=["slide 3 | shape Title 1 | paragraph 0"])
    block = redact(doc, [finding("PERSON", "Jane Smith", source="slide 3 | shape Title 1 | paragraph 0")]).document.content[0]
    assert block.source == "slide 3 | shape Title 1 | paragraph 0"
    assert block.metadata["block_id"] == "d1-b0"


@pytest.mark.parametrize("findings", [[], None])
def test_no_findings_returns_unchanged_copy(findings):
    doc = make_doc("Plain text")
    result = redact(doc, findings or [])
    assert result.document is not doc
    assert result.document.content[0].text == "Plain text"
    assert result.redacted_count == 0


def test_empty_document():
    doc = NormalizedDocument(document_id="d0", source_type="pdf", file_name="empty.pdf")
    result = redact(doc, [finding("EMAIL", "a@b.com")])
    assert result.redacted_count == 0 and result.skipped[0]["reason"] == "not_located"


# ---------- incremental passes ----------
def test_second_pass_continues_placeholder_numbering():
    redactor = PlaceholderRedactor()
    doc = make_doc("Jane Smith and John Doe met.")
    first = redactor.redact(doc, [finding("PERSON", "Jane Smith")])
    second = redactor.redact(first.document, [finding("PERSON", "John Doe")], previous=first)
    assert second.document.content[0].text == "[PERSON_1] and [PERSON_2] met."
    assert second.redacted_count == 2
    assert second.counts_by_type() == {"PERSON": 2}


def test_second_pass_reuses_placeholder_for_known_value():
    redactor = PlaceholderRedactor()
    doc = make_doc("Jane Smith wrote.", "Ask Jane Smith.")
    first = redactor.redact(doc, [finding("PERSON", "Jane Smith", source="paragraph 0")])
    second = redactor.redact(first.document, [finding("PERSON", "Jane Smith", source="paragraph 1")], previous=first)
    assert [b.text for b in second.document.content] == ["[PERSON_1] wrote.", "Ask [PERSON_1]."]
    assert second.placeholder_map["[PERSON_1]"]["occurrences"] == 2


# ---------- edge cases ----------
def test_value_with_surrounding_whitespace():
    doc = make_doc("Owner Jane Smith here")
    assert redact(doc, [finding("PERSON", "  Jane Smith ")]).document.content[0].text == "Owner [PERSON_1] here"


def test_value_split_by_line_break():
    doc = make_doc("Jane\nSmith wrote")
    assert redact(doc, [finding("PERSON", "Jane Smith")]).document.content[0].text == "[PERSON_1] wrote"


def test_unicode_values():
    doc = make_doc("Zoë Müller-Łukasz signed; ZOË MÜLLER-ŁUKASZ approved")
    out = redact(doc, [finding("PERSON", "Zoë Müller-Łukasz")]).document.content[0].text
    assert out == "[PERSON_1] signed; [PERSON_1] approved"


def test_regex_characters_in_value():
    doc = make_doc("id a+b(c)*d end")
    assert redact(doc, [finding("ID", "a+b(c)*d")]).document.content[0].text == "id [ID_1] end"


def test_duplicate_findings_count_once():
    doc = make_doc("Jane Smith")
    result = redact(doc, [finding("PERSON", "Jane Smith", start=0, end=10)] * 2)
    assert result.document.content[0].text == "[PERSON_1]" and result.redacted_count == 1


def test_adjacent_findings_stay_separate():
    doc = make_doc("JaneSmith")
    findings = [finding("PERSON", "Jane", start=0, end=4), finding("PERSON", "Smith", start=4, end=9)]
    assert redact(doc, findings).document.content[0].text == "[PERSON_1][PERSON_2]"


def test_missing_confidence_type_and_metadata_do_not_crash():
    doc = make_doc("Jane Smith")
    f = PIIFinding(pii_type=None, value="Jane Smith", source="paragraph 0", confidence=None,
                   detection_method="test", validated=True, metadata=None)
    assert redact(doc, [f]).document.content[0].text == "[PII_1]"
    f.validated = False
    assert redact(doc, [f]).skipped[0]["reason"] == "below_threshold"


def test_offsets_relative_to_full_text():
    doc = make_doc("Intro line", "Contact jane@example.com")
    full = doc.full_text()
    start = full.index("jane@example.com")
    result = redact(doc, [finding("EMAIL", "jane@example.com", source="", start=start, end=start + 16)])
    assert [b.text for b in result.document.content] == ["Intro line", "Contact [EMAIL_1]"]


def test_full_text_offsets_spanning_two_blocks():
    doc = make_doc("Signed by Jane", "Smith on Monday")
    full = doc.full_text()
    start = full.index("Jane")
    result = redact(doc, [finding("PERSON", "Jane Smith", source="", start=start, end=start + 10)])
    assert [b.text for b in result.document.content] == ["Signed by [PERSON_1]", "[PERSON_1] on Monday"]
