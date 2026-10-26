"""Sanitized output and audit-safe reports for a GateResult.

Only the JSON report is written for a BLOCKED document - the sanitized text is
withheld because it still contains residual PII.
"""
import json
from pathlib import Path
from typing import Dict, List, Optional

from models.document import NormalizedDocument
from models.pii import PIIFinding
from redaction.gate import GateResult


def sanitized_text(result: GateResult) -> Optional[str]:
    """Sanitized document text with a source header per block; None unless SAFE."""
    if not result.is_safe:
        return None
    parts = [f"[{block.source}]\n{block.text}" for block in result.document.content]
    return "\n\n".join(parts)


def report(result: GateResult) -> Dict[str, object]:
    """Gate report plus safe extraction metadata. Contains no raw PII."""
    data = result.to_dict()
    md = result.document.metadata
    data["source_type"] = result.document.source_type
    data["extraction"] = {
        "parser": md.get("parser", ""),
        "ocr_used": md.get("ocr_used", ""),
        "status": md.get("status", ""),
        "block_count": len(result.document.content),
    }
    data["redacted_blocks"] = sum(1 for b in result.document.content if b.metadata.get("redacted_spans"))
    return data


def write_outputs(result: GateResult, out_dir) -> Dict[str, str]:
    """Write <name>.report.json and, when SAFE, <name>.sanitized.txt into out_dir."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = Path(result.document.file_name).stem or result.document.document_id
    paths = {}
    report_path = out / f"{stem}.report.json"
    report_path.write_text(json.dumps(report(result), indent=2), encoding="utf-8")
    paths["report"] = str(report_path)
    text = sanitized_text(result)
    if text is not None:
        text_path = out / f"{stem}.sanitized.txt"
        text_path.write_text(text, encoding="utf-8")
        paths["sanitized"] = str(text_path)
    return paths


def _block_location(block) -> object:
    raw = block.metadata.get("location")
    if raw:
        try:
            return json.loads(raw)
        except ValueError:
            pass
    return block.source


def evaluation_record(original: NormalizedDocument, findings: List[PIIFinding],
                      result: GateResult) -> Dict[str, object]:
    """Shape expected by the evaluation module's pipeline contract
    (findings, sanitized_units, original_units, verification_status, blocks, doc)."""
    return {
        "findings": findings,
        "original_units": [b.text for b in original.content],
        "sanitized_units": [b.text for b in result.document.content],
        "verification_status": result.status,
        "blocks": [{"text": b.text, "location": _block_location(b)} for b in original.content],
        "doc": original,
    }
