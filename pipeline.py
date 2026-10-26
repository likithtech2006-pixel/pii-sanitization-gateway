"""End-to-end pipeline: extract -> detect -> redact -> verify -> (release | block).

    from pipeline import process
    result = process("samples/policy.pdf")
    result.status                 # "SAFE" / "BLOCKED"
    result.gate.released_text()   # sanitized text, only when SAFE

Command line (outputs go to the gitignored output/ folder):

    python pipeline.py samples/*.pdf samples/*.docx samples/*.pptx
    python pipeline.py samples/policy.pdf --out output --analyze
    python pipeline.py samples/policy.pdf --redacted-files     # also policy.redacted.pdf

Evaluation contract (used by evaluation/run_evaluation.py):

    python -m evaluation.run_evaluation --samples samples --pipeline pipeline:run_pipeline
"""
import argparse
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

import detection
from extraction import extract
from interfaces.detection import PIIDetector
from models.document import NormalizedDocument
from models.pii import PIIFinding
from redaction import GateResult, sanitize_and_verify
from redaction.output import evaluation_record, write_outputs
from security import inspector

SUPPORTED = (".pdf", ".docx", ".pptx")


@dataclass
class PipelineResult:
    """Everything one run produced. summary() is safe to log (no raw PII)."""
    file_name: str
    original: NormalizedDocument
    findings: List[PIIFinding]
    gate: GateResult
    timings: Dict[str, float] = field(default_factory=dict)
    engines: Dict[str, str] = field(default_factory=dict)
    content_risk: Optional[inspector.ContentRisk] = None

    @property
    def status(self) -> str:
        return self.gate.status

    @property
    def seconds(self) -> float:
        return round(sum(self.timings.values()), 2)

    def summary(self) -> Dict[str, object]:
        report = self.gate.to_dict()
        return {
            "file_name": self.file_name,
            "status": self.status,
            "reason": self.gate.reason,
            "blocks": len(self.original.content),
            "findings": len(self.findings),
            "redacted": self.gate.redaction.redacted_count,
            "remediated": self.gate.remediated_count,
            "residual": len(self.gate.residual_findings),
            "needs_review": report["needs_review"],
            "counts_by_type": self.gate.redaction.counts_by_type(),
            "people": sum(1 for t in self.gate.redaction.placeholder_map if t.startswith("[PERSON_")),
            "ocr_used": self.original.metadata.get("ocr_used") == "true",
            "warnings": self.original.metadata.get("warnings", ""),
            "timings": self.timings,
            "seconds": self.seconds,
            "engines": self.engines,
            "content_risk": self.content_risk.level if self.content_risk else "none",
            "ai_blocked": bool(self.content_risk and self.content_risk.ai_blocked),
        }


def process(file, filename: Optional[str] = None, detector: Optional[PIIDetector] = None,
            on_stage: Optional[Callable[[str, Dict[str, object]], None]] = None) -> PipelineResult:
    """Run the whole chain on a path, bytes or a file-like upload.

    on_stage, if given, is called after each stage has finished ("extract", "detect", "verify")
    with counts only (no raw values), so a UI can report real progress.
    """
    detector = detector or detection.PIIDetectorImpl()
    timings = {}
    notify = on_stage or (lambda stage, info: None)
    if isinstance(file, (str, Path)):
        filename = filename or Path(file).name
        data = Path(file).read_bytes()
    else:
        data = file if isinstance(file, bytes) else file.read()
    ext = Path(filename or "").suffix.lower()

    t = time.perf_counter()
    document = extract(data, filename)
    timings["extract"] = round(time.perf_counter() - t, 2)
    notify("extract", {"blocks": len(document.content), "seconds": timings["extract"],
                       "ocr_used": document.metadata.get("ocr_used") == "true",
                       "status": document.metadata.get("status", "")})

    t = time.perf_counter()
    findings = detector.detect(document)
    timings["detect"] = round(time.perf_counter() - t, 2)
    notify("detect", {"findings": len(findings), "seconds": timings["detect"]})

    t = time.perf_counter()
    gate = sanitize_and_verify(document, findings, detector)
    timings["redact_verify"] = round(time.perf_counter() - t, 2)
    notify("verify", {"status": gate.status, "reason": gate.reason, "redacted": gate.redaction.redacted_count,
                      "passes": gate.passes, "seconds": timings["redact_verify"]})

    # Hidden content and prompt injection. A prompt-injection hit is stamped on the sanitized document,
    # and the AI layer refuses any document carrying that stamp (enforced at the AI boundary, not the UI).
    t = time.perf_counter()
    risk = inspector.inspect(data, ext, document) if document.metadata.get("status") != "error" else inspector.ContentRisk()
    if risk.ai_blocked:
        gate.document.metadata["prompt_injection"] = "true"
    timings["inspect"] = round(time.perf_counter() - t, 2)
    notify("inspect", {"level": risk.level, "ai_blocked": risk.ai_blocked, "findings": len(risk.findings)})

    return PipelineResult(document.file_name, document, findings, gate, timings, detection.info(), risk)


def run_pipeline(path) -> Dict[str, object]:
    """Pipeline callable in the shape evaluation/run_evaluation.py expects."""
    result = process(str(path))
    return evaluation_record(result.original, result.findings, result.gate)


def _print(result: PipelineResult, paths: Dict[str, str]):
    s = result.summary()
    print(f"\n{s['file_name']}: {s['status']} ({s['reason']}) in {s['seconds']}s  {s['timings']}")
    print(f"  blocks={s['blocks']} findings={s['findings']} redacted={s['redacted']} "
          f"remediated={s['remediated']} residual={s['residual']} needs_review={s['needs_review']} "
          f"people={s['people']}")
    print(f"  by type: {s['counts_by_type']}")
    if s["warnings"]:
        print(f"  warnings: {s['warnings']}")
    for residual in (result.gate.verification.safe_residuals() if result.gate.verification else []):
        print(f"  residual: {residual['type']} at {residual['source']} ({residual['safe_reference']})")
    print("  -> " + ", ".join(paths.values()))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Sanitize PDF/DOCX/PPTX files before AI use.")
    ap.add_argument("files", nargs="*", help="files to process (default: everything in samples/)")
    ap.add_argument("--out", default="output", help="output folder (default: output/)")
    ap.add_argument("--analyze", action="store_true",
                    help="run the downstream AI analysis on SAFE documents (local unless ANTHROPIC_API_KEY is set)")
    ap.add_argument("--redacted-files", action="store_true",
                    help="also write a redacted copy in the original format (PDF/DOCX/PPTX), verified before it is kept")
    a = ap.parse_args(argv)

    files = [Path(f) for f in a.files] or sorted(
        p for p in Path("samples").glob("*") if p.suffix.lower() in SUPPORTED)
    if not files:
        print("no input files (pass paths or put files in samples/)")
        return 2
    print(f"engines: {detection.info()}")
    exit_code = 0
    for path in files:
        result = process(str(path))
        paths = write_outputs(result.gate, a.out)
        _print(result, paths)
        if result.status != "SAFE":
            exit_code = 1
            continue
        if a.redacted_files:
            from redaction.file_writer import write_redacted_file
            target = Path(a.out) / f"{path.stem}.redacted{path.suffix.lower()}"
            outcome = write_redacted_file(str(path), result.original, result.gate, str(target))
            print(f"  redacted copy: {outcome.path if outcome.ok else outcome.reason}  {outcome.stats}")
            if not outcome.ok:
                exit_code = 1
        if a.analyze:
            from ai_layer import AnalysisBlocked, analyze
            try:
                analysis = analyze(result.gate)
            except AnalysisBlocked as e:
                print(f"  analysis blocked: {e}")
                continue
            out = Path(a.out) / (Path(result.file_name).stem + ".analysis.md")
            out.write_text(analysis.to_markdown(), encoding="utf-8")
            print(f"  analysis ({analysis.provider}) -> {out}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
