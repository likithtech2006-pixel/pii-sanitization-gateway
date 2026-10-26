"""Usage: python scripts/redact_samples.py [files...] [--out output] [--detector module:func]
Runs extract -> detect -> redact -> verify on each file (default: everything in samples/)
and writes <name>.report.json (+ <name>.sanitized.txt when SAFE) to the output folder.

Detector: --detector module:func, else detection.detect if the module exists, else the
redaction safety net as a stand-in (structured PII only - no names).
NOTE: output/ is gitignored. Reports contain no raw PII; still do not commit outputs."""
import argparse
import importlib
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from extraction import extract
from redaction import safety_net_scan, sanitize_and_verify
from redaction.output import write_outputs

SUPPORTED = {".pdf", ".pptx", ".docx"}


class FunctionDetector:
    """Wrap a detect(document) function as a PIIDetector."""

    def __init__(self, fn, name):
        self.fn, self.name = fn, name

    def detect(self, document):
        return list(self.fn(document))


def load_detector(spec):
    if spec:
        module, _, func = spec.partition(":")
        return FunctionDetector(getattr(importlib.import_module(module), func or "detect"), spec)
    try:
        module = importlib.import_module("detection")
        if callable(getattr(module, "detect", None)):
            return FunctionDetector(module.detect, "detection.detect")
    except ImportError:
        pass
    return FunctionDetector(safety_net_scan, "safety-net stand-in")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="*")
    parser.add_argument("--out", default="output")
    parser.add_argument("--detector", default=None)
    args = parser.parse_args()

    files = [Path(f) for f in args.files] or sorted(
        p for p in Path("samples").iterdir() if p.suffix.lower() in SUPPORTED)
    detector = load_detector(args.detector)
    print(f"detector: {detector.name}")

    for path in files:
        t0 = time.perf_counter()
        document = extract(str(path))
        findings = detector.detect(document)
        result = sanitize_and_verify(document, findings, detector)
        paths = write_outputs(result, args.out)
        seconds = time.perf_counter() - t0
        print(f"\n{path.name}: {result.status} ({result.reason}) in {seconds:.1f}s")
        print(f"  blocks={len(document.content)} findings={len(findings)} "
              f"redacted={result.redaction.redacted_count} remediated={result.remediated_count} "
              f"passes={result.passes} residual={len(result.residual_findings)}")
        print(f"  by type: {result.redaction.counts_by_type()}")
        for residual in (result.verification.safe_residuals() if result.verification else []):
            print(f"  residual: {residual['type']} at {residual['source']} ({residual['safe_reference']})")
        print("  -> " + ", ".join(paths.values()))


if __name__ == "__main__":
    main()
