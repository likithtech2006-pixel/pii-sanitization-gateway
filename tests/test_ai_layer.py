"""Run from repo root:  pytest tests/test_ai_layer.py -v
The AI layer only ever sees sanitized text of SAFE documents (fake data only)."""
import pytest

import detection
from ai_layer import AnalysisBlocked, analyze, egress_check
from models.document import ContentBlock, NormalizedDocument
from redaction import sanitize_and_verify


def make(texts):
    blocks = [ContentBlock(t, f"page {i + 1}", metadata={"block_id": f"b{i}"}) for i, t in enumerate(texts)]
    return NormalizedDocument("d", "pdf", "policy.pdf", blocks)


TEXTS = ["1. Purpose and scope",
         "Risk acceptance for critical risks must be approved by the Board Risk Committee.",
         "Policy owner: Naomi K. Osadebe (EMP-41077), n.osadebe@example.com, +1 (212) 555-0147.",
         "2. Roles",
         "The risk owner shall review controls annually."]


@pytest.fixture
def safe_gate(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    doc = make(TEXTS)
    det = detection.PIIDetectorImpl()
    gate = sanitize_and_verify(doc, det.detect(doc), det)
    assert gate.is_safe
    return gate


def test_local_analysis_uses_only_sanitized_text(safe_gate):
    result = analyze(safe_gate, "Who approves risk acceptance for critical risks?")
    md = result.to_markdown()
    assert result.provider.startswith("local")
    for raw in ("Osadebe", "n.osadebe@example.com", "555-0147", "EMP-41077"):
        assert raw not in md
    assert "Board Risk Committee" in result.answer
    assert any("must be approved" in o for o in result.sections["Obligations and requirements (must / shall)"])
    assert "1. Purpose and scope" in result.sections["Structure (section headings)"]


def test_blocked_document_never_reaches_the_ai_layer():
    doc = make(["Reach jane.smith@example.com"])
    gate = sanitize_and_verify(doc, [], max_passes=1)      # nothing redacted -> residual -> BLOCKED
    assert not gate.is_safe
    with pytest.raises(AnalysisBlocked):
        analyze(gate)


def test_egress_guard_catches_leaks(safe_gate):
    assert egress_check("contact jane.smith@example.com") == ["EMAIL"]
    assert egress_check(safe_gate.released_text()) == []
    # a SAFE result whose text was tampered with afterwards is still stopped at the door
    safe_gate.document.content[0].text += " SSN 900-42-7781"
    with pytest.raises(AnalysisBlocked):
        analyze(safe_gate)


def test_unknown_provider(safe_gate):
    with pytest.raises(ValueError):
        analyze(safe_gate, provider="other")
