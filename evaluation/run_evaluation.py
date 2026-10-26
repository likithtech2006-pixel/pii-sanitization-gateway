"""Run the evaluation and write a JSON + Markdown report (no raw PII in either).

Examples
  python -m evaluation.run_evaluation --samples _work                      # baseline pipeline
  python -m evaluation.run_evaluation --samples _work --pipeline mypkg.run:run_pipeline
  python -m evaluation.run_evaluation --samples _work --previous reports/last.json

A pipeline is any callable  f(path) -> dict  returning
  findings            list of PIIFinding (dict/object)
  sanitized_units     list[str]   text of the redacted output
  original_units      list[str]   text of the extracted original
  verification_status "SAFE" / "UNSAFE" / ...
  blocks              list of {'text','location'} the extractor produced   (optional)
  doc                 NormalizedDocument for span lookup                   (optional)
"""
import argparse
import importlib
import json
import os
import sys
import time

from evaluation import adapters, baseline, dataset, metrics

DEFAULT_GOLD = os.path.join(os.path.dirname(__file__), "ground_truth", "local", "cadence_gold.json")
PDF_OCR_DEFAULT = os.path.join(os.path.dirname(__file__), "ground_truth", "local", "pdf_ocr")
FRACTIONS = ("recall", "precision", "f1", "traceability", "classification_accuracy")


def load_pipeline(spec, pdf_ocr_dir):
    if spec == "baseline":
        return lambda path: baseline.run(path, pdf_ocr_dir if path.lower().endswith(".pdf") else None)
    module, _, func = spec.partition(":")
    return getattr(importlib.import_module(module), func)


def pct(x):
    return "n/a" if x is None else "%.1f%%" % (100 * x)


def strip(result):
    return {k: v for k, v in result.items() if not k.startswith("_")}


def misses_masked(result):
    r = result["_result"]
    return {
        "missed_required": [{"type": i.type, "value": metrics.masked(i.value), "location": i.location,
                             "modality": i.modality} for i in r.missed_required],
        "false_positives": [{"type": f.type, "text": metrics.masked(f.text or ""), "location": f.location}
                            for f in r.false_positives],
    }


def evaluate_all(gt, samples_dir, pipeline, threshold=0.85, compare_structure=True, pdf_ocr_dir=None):
    results, details = [], {}
    for key in gt.keys():
        gold = gt.get(key)
        path = os.path.join(samples_dir, gold.source_name)
        if not os.path.exists(path):
            print("skip %s: %s not found" % (key, path), file=sys.stderr)
            continue
        t0 = time.perf_counter()
        out = pipeline(path)
        seconds = time.perf_counter() - t0
        findings = adapters.to_eval_findings(out["findings"], out.get("doc"))
        extracted = out.get("blocks") if compare_structure else None
        reference = None
        if extracted is not None:   # independent reference extraction of the same file
            ocr_dir = pdf_ocr_dir if path.lower().endswith(".pdf") else None
            reference = [{"text": t, "location": l} for l, t, _ in baseline.extract_units(path, ocr_dir)]
        res = metrics.evaluate_document(
            gold, findings, out.get("sanitized_units"), out.get("original_units"),
            out.get("verification_status"), reference, extracted, seconds, threshold)
        details[key] = misses_masked(res)
        results.append(res)
    return results, details


def compare(current, previous, tolerance=0.005):
    """Return a list of regressions: metrics that got worse than the previous run."""
    problems = []
    for name in ("recall", "precision", "traceability", "classification_accuracy"):
        a, b = current.get(name), previous.get(name)
        if a is not None and b is not None and a < b - tolerance:
            problems.append("%s fell from %s to %s" % (name, pct(b), pct(a)))
    cr = current.get("residual", {}).get("residual_value_count")
    pr = previous.get("residual", {}).get("residual_value_count")
    if cr is not None and pr is not None and cr > pr:
        problems.append("residual PII values rose from %d to %d" % (pr, cr))
    return problems


def markdown(summary, per_doc, details, problems, failures):
    L = ["# Evaluation report", "",
         "| Metric | Result |", "|---|---|",
         "| Recall (required PII found) | %s (%d/%d) |" % (pct(summary["recall"]), summary["tp"], summary["gold_required"]),
         "| Precision | %s |" % pct(summary["precision"]),
         "| False positives | %d |" % summary["fp"],
         "| Source traceability | %s |" % pct(summary["traceability"]),
         "| Type accuracy | %s |" % pct(summary["classification_accuracy"])]
    if "residual" in summary:
        r = summary["residual"]
        L += ["| Residual PII values left after redaction | %d (occurrences %d) |" % (r["residual_value_count"], r["residual_occurrences"]),
              "| Documents where verifier said SAFE but PII remained | %d |" % r["documents_false_safe"]]
    if summary.get("seconds"):
        L.append("| Total processing time | %.1f s |" % summary["seconds"])
    L += ["", "## Per document", "", "| Document | Recall | Precision | FP | Residual | Context kept | Structure | Seconds |", "|---|---|---|---|---|---|---|---|"]
    for r in per_doc:
        d = r["detection"]
        ctx = r.get("context", {}).get("retention")
        st = r.get("structure", {}).get("text_retention")
        L.append("| %s | %s | %s | %d | %s | %s | %s | %s |" % (
            r["document"], pct(d["recall"]), pct(d["precision"]), d["fp"],
            r.get("residual", {}).get("residual_value_count", "n/a"), pct(ctx), pct(st),
            "%.1f" % r["seconds"] if r.get("seconds") else "n/a"))
    L += ["", "## Recall by type", "", "| Type | Gold | Found | Recall |", "|---|---|---|---|"]
    for t, v in sorted(summary["by_type"].items()):
        L.append("| %s | %d | %d | %s |" % (t, v["gold"], v["tp"], pct(v["recall"])))
    L += ["", "## Recall by modality", "", "| Modality | Gold | Found | Recall |", "|---|---|---|---|"]
    for t, v in sorted(summary["by_modality"].items()):
        L.append("| %s | %d | %d | %s |" % (t, v["gold"], v["tp"], pct(v["recall"])))
    L += ["", "## Misses (values masked)", ""]
    for key, d in details.items():
        L.append("**%s** - %d missed required, %d false positives" % (key, len(d["missed_required"]), len(d["false_positives"])))
        for m in d["missed_required"][:15]:
            L.append("- missed %s `%s` at %s (%s)" % (m["type"], m["value"], m["location"], m["modality"]))
        for m in d["false_positives"][:10]:
            L.append("- false positive %s `%s` at %s" % (m["type"], m["text"], m["location"]))
        L.append("")
    L += ["## Regression check", ""] + (["- " + p for p in problems] if problems else ["No regression against the previous run."])
    if failures:
        L += ["", "## Threshold failures", ""] + ["- " + f for f in failures]
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gold", default=DEFAULT_GOLD)
    ap.add_argument("--samples", required=True, help="folder containing the sample documents")
    ap.add_argument("--pipeline", default="baseline")
    ap.add_argument("--pdf-ocr-dir", default=PDF_OCR_DEFAULT)
    ap.add_argument("--out", default="evaluation/reports")
    ap.add_argument("--previous", help="earlier results JSON for the regression check")
    ap.add_argument("--min-recall", type=float, default=None)
    ap.add_argument("--max-residual", type=int, default=None)
    a = ap.parse_args(argv)

    gt = dataset.load_ground_truth(a.gold)
    pipeline = load_pipeline(a.pipeline, a.pdf_ocr_dir)
    results, details = evaluate_all(gt, a.samples, pipeline, compare_structure=a.pipeline != "baseline",
                                    pdf_ocr_dir=a.pdf_ocr_dir)
    if not results:
        print("nothing evaluated", file=sys.stderr)
        return 2
    summary = metrics.aggregate(results)
    problems = []
    if a.previous and os.path.exists(a.previous):
        with open(a.previous, encoding="utf-8") as fh:
            problems = compare(summary, json.load(fh)["summary"])
    failures = []
    if a.min_recall is not None and (summary["recall"] or 0) < a.min_recall:
        failures.append("recall %s below required %s" % (pct(summary["recall"]), pct(a.min_recall)))
    if a.max_residual is not None and summary.get("residual", {}).get("residual_value_count", 0) > a.max_residual:
        failures.append("residual PII above allowed %d" % a.max_residual)

    os.makedirs(a.out, exist_ok=True)
    payload = {"summary": summary, "documents": [strip(r) for r in results], "details": details}
    with open(os.path.join(a.out, "last.json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1, default=str)
    md = markdown(summary, results, details, problems, failures)
    with open(os.path.join(a.out, "last.md"), "w", encoding="utf-8") as fh:
        fh.write(md)
    print(md)
    return 1 if (problems or failures) else 0


if __name__ == "__main__":
    sys.exit(main())
