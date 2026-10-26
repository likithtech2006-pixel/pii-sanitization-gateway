"""Run from repo root:  pytest tests/test_pipeline.py -v
End-to-end: extract -> detect -> redact -> verify -> output, on DOCX/PPTX files
generated on the fly with fake PII only."""
import json

import pytest

from extraction import extract
from models.pii import PIIFinding
from redaction import BLOCKED, SAFE, safety_net_scan, sanitize_and_verify
from redaction.output import evaluation_record, report, sanitized_text, write_outputs

FAKE_PII = ["Jane Smith", "jane.smith@example.com", "+1 555-010-9999", "John Doe", "+1 (555) 0100"]


class FakeDetector:
    """Stand-in for the team detector: safety net for structured PII + known fake names."""

    NAMES = ("Jane Smith", "John Doe")

    def detect(self, document):
        findings = safety_net_scan(document)
        for block in document.content:
            for name in self.NAMES:
                start = block.text.find(name)
                if start != -1:
                    findings.append(PIIFinding("PERSON", name, block.source, 0.9, "fake_nlp",
                                               start, start + len(name), True,
                                               {"block_id": block.metadata["block_id"]}))
        return findings


# ---------- fixtures (fake data only) ----------
@pytest.fixture
def docx_file(tmp_path):
    from docx import Document
    d = Document()
    d.add_paragraph("Customer: Jane Smith, email jane.smith@example.com")
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text, t.cell(0, 1).text = "Name", "Phone"
    t.cell(1, 0).text, t.cell(1, 1).text = "John Doe", "+1 555-010-9999"
    d.sections[0].header.paragraphs[0].text = "Prepared for Jane Smith"
    path = tmp_path / "fake.docx"
    d.save(path)
    return path


@pytest.fixture
def pptx_file(tmp_path):
    from pptx import Presentation
    from pptx.util import Inches
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    slide.shapes.title.text = "Leadership"
    box = slide.shapes.add_textbox(Inches(1), Inches(2), Inches(6), Inches(2)).text_frame
    box.text = "John Doe"
    box.add_paragraph().text = "M +1 (555) 0100"
    box.add_paragraph().text = "jane.smith@example.com"
    path = tmp_path / "fake.pptx"
    prs.save(path)
    return path


def run(path, detector=None):
    detector = detector or FakeDetector()
    document = extract(str(path))
    findings = detector.detect(document)
    return document, findings, sanitize_and_verify(document, findings, detector)


# ---------- end-to-end ----------
@pytest.mark.parametrize("fixture", ["docx_file", "pptx_file"])
def test_end_to_end_is_safe_and_removes_all_fake_pii(fixture, request):
    document, findings, result = run(request.getfixturevalue(fixture))
    assert result.status == SAFE, result.to_dict()
    released = result.released_text()
    for raw in FAKE_PII:
        assert raw not in released
    assert "[PERSON_1]" in released


def test_docx_table_and_header_are_redacted_with_sources_kept(docx_file):
    document, _, result = run(docx_file)
    by_source = {b.source: b.text for b in result.document.content}
    original_sources = [b.source for b in document.content]
    assert [b.source for b in result.document.content] == original_sources
    table_cells = [t for s, t in by_source.items() if "table" in s and "header" not in s]
    assert "[PERSON_2]" in table_cells and "[PHONE_1]" in table_cells
    header = [t for s, t in by_source.items() if s.startswith("header")]
    assert header == ["Prepared for [PERSON_1]"]


def test_pptx_slide_traceability(pptx_file):
    _, _, result = run(pptx_file)
    redacted = [b for b in result.document.content if b.metadata.get("redacted_spans")]
    assert redacted and all(b.source.startswith("slide 1") for b in redacted)


def test_detector_miss_is_remediated_by_safety_net(docx_file):
    class NamesOnly(FakeDetector):
        def detect(self, document):
            return [f for f in super().detect(document) if f.pii_type == "PERSON"]

    _, _, result = run(docx_file, NamesOnly())
    assert result.status == SAFE and result.reason == "verified_after_remediation"
    assert result.remediated_count >= 2


# ---------- outputs ----------
def test_write_outputs_safe(docx_file, tmp_path):
    _, _, result = run(docx_file)
    paths = write_outputs(result, tmp_path / "out")
    text = open(paths["sanitized"], encoding="utf-8").read()
    data = json.load(open(paths["report"], encoding="utf-8"))
    assert text == sanitized_text(result) and text.startswith("[paragraph | index 0]")
    assert data["status"] == SAFE and data["source_type"] == "docx"
    assert data["extraction"]["parser"] == "python-docx"
    for raw in FAKE_PII:
        assert raw not in text and raw not in json.dumps(data)


def test_write_outputs_blocked_withholds_text(tmp_path):
    from docx import Document
    d = Document()
    d.add_paragraph("Reach jane.smith@example.com")
    path = tmp_path / "leak.docx"
    d.save(path)
    document = extract(str(path))
    result = sanitize_and_verify(document, [], max_passes=1)
    paths = write_outputs(result, tmp_path / "out")
    assert result.status == BLOCKED
    assert "sanitized" not in paths and sanitized_text(result) is None
    assert report(result)["residual_count"] == 1
    assert "jane.smith@example.com" not in open(paths["report"], encoding="utf-8").read()


def test_evaluation_record_shape(docx_file):
    document, findings, result = run(docx_file)
    record = evaluation_record(document, findings, result)
    assert record["verification_status"] == SAFE
    assert len(record["original_units"]) == len(record["sanitized_units"]) == len(document.content)
    assert record["blocks"][0]["location"] == {"type": "paragraph", "index": 0}
    assert record["doc"] is document


# ---------- with the real detector (detection module) ----------
def test_real_detector_end_to_end(docx_file):
    from pipeline import process
    result = process(str(docx_file))
    assert result.status == SAFE, result.summary()
    released = result.gate.released_text()
    for raw in FAKE_PII:
        assert raw not in released
    # the same person gets the same placeholder in the body, the table and the header
    jane = [b.text for b in result.gate.document.content if "Customer" in b.text or "Prepared for" in b.text]
    tokens = {t for text in jane for t in __import__("re").findall(r"\[PERSON_\d+\]", text)}
    assert len(tokens) == 1
    summary = json.dumps(result.summary())
    assert not any(raw in summary for raw in FAKE_PII)
    assert set(result.timings) == {"extract", "detect", "redact_verify", "inspect"}


def test_pipeline_cli_writes_outputs(docx_file, tmp_path):
    from pipeline import main
    code = main([str(docx_file), "--out", str(tmp_path / "out"), "--analyze"])
    assert code == 0
    names = sorted(p.name for p in (tmp_path / "out").iterdir())
    assert names == ["fake.analysis.md", "fake.report.json", "fake.sanitized.txt"]


def test_run_pipeline_matches_evaluation_contract(pptx_file):
    from pipeline import run_pipeline
    record = run_pipeline(pptx_file)
    assert record["verification_status"] == SAFE
    assert {"findings", "sanitized_units", "original_units", "blocks", "doc"} <= set(record)
