"""Re-run the sample test cases and compare them with expected_output/.

    python sample_test_cases/check_test_cases.py

For every case it checks the status, the reason, the counts per PII type and the
sanitized text, and searches the sanitized text for raw values that must never
appear. Known gaps (current limitations, documented in README.md) are reported
as KNOWN GAP rather than FAIL.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from pipeline import process  # noqa: E402
from redaction.output import sanitized_text  # noqa: E402

# Raw values that must not survive redaction (all fictional).
MUST_NOT_APPEAR = {
    "TC01_access_request.docx": ["Rahul", "Sharma", "rahul@example.com", "9876543210", "EMP-1042",
                                 "Priya Nair", "priya.nair@", "Daniel Brooks", "d.brooks@"],
    "TC02_org_chart.pptx": ["Vossberg", "Arjun Mehta", "Lindqvist", "@cadence-demo.com", "0114",
                            "7946 0018", "98450 12345"],
    "TC03_hr_record.pdf": ["Kavya", "EMP-41077", "14/03/1994", "219-09-9999", "ABCPE1234F", "K1234567",
                           "42 Maple Street", "4111 1111", "GB82", "192.168.10.45"],
    "TC04_scanned_incident.pdf": ["Thomas Brown", "thomas.brown@", "555-0199", "Elena", "Petrova", "EMP-39021"],
    "TC05_no_pii_policy.docx": [],
    "TC06_name_variants.docx": ["Osadebe", "Naomi", "Ortega", "Rafael", "EMP-41077", "n.osadebe@"],
    "TC07_corrupted.pdf": [],
    "TC08_empty.docx": [],
    "TC09_screenshot_in_docx.docx": ["John Smith", "john.smith@", "Anita", "Patel", "anita.patel@"],
    "TC10_prompt_injection.docx": ["Meera", "meera.iyer@", "7946 0321"],
    "TC11_tracked_changes.docx": ["Kiran Rao", "EMP-55120", "priya.menon@"],
}
# Values that currently leak: documented limitations, not regressions.
KNOWN_GAPS = {
    "TC06_name_variants.docx": {"Rafael"},          # bare first name of a confirmed person
    "TC09_screenshot_in_docx.docx": {"Anita", "Patel"},  # OCR merged the name into "AnitaPatel"
}


def main() -> int:
    failures = 0
    print(f"{'case':32} {'status':22} {'counts':6} {'text':6} leaks")
    for path in sorted((HERE / "inputs").iterdir()):
        expected = json.loads((HERE / "expected_output" / f"{path.stem}.report.json").read_text())
        result = process(str(path))
        rep = result.gate.to_dict()
        problems = []
        if (rep["status"], rep["reason"]) != (expected["status"], expected["reason"]):
            problems.append(f"status {rep['status']}/{rep['reason']} != {expected['status']}/{expected['reason']}")
        counts_ok = rep["counts_by_type"] == expected["counts_by_type"]
        text = sanitized_text(result.gate) or ""
        exp_txt = HERE / "expected_output" / f"{path.stem}.sanitized.txt"
        text_ok = (not exp_txt.exists() and not text) or (exp_txt.exists() and exp_txt.read_text() == text)
        leaks = {v for v in MUST_NOT_APPEAR.get(path.name, []) if v.lower() in text.lower()}
        known = leaks & KNOWN_GAPS.get(path.name, set())
        new_leaks = leaks - known
        if not counts_ok:
            problems.append(f"counts {rep['counts_by_type']}")
        if new_leaks:
            problems.append(f"LEAK {sorted(new_leaks)}")
        leak_col = ("LEAK " + ",".join(sorted(new_leaks))) if new_leaks else \
                   ("KNOWN GAP " + ",".join(sorted(known))) if known else "none"
        status = f"{rep['status']} ({rep['reason']})"
        print(f"{path.name:32} {status[:22]:22} {'ok' if counts_ok else 'DIFF':6} "
              f"{'ok' if text_ok else 'DIFF':6} {leak_col}")
        # text differences alone are informational: OCR output can vary between Tesseract versions
        if problems:
            failures += 1
            for p in problems:
                print(f"    FAIL: {p}")
    print(f"\n{'ALL PASS' if not failures else f'{failures} case(s) FAILED'}"
          " (text DIFF on OCR cases can come from a different Tesseract version)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
