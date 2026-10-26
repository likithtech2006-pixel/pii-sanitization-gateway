"""Second-pass verification of sanitized documents.

The sanitized document is scanned again before anything is released:
  1. with the team PII detector (same framework that produced the findings), and
  2. with an independent regex safety net for high-risk structured PII,
so verification does not rely only on the detector that may have missed
something in the first place.

Placeholders inserted by the redactor ([EMAIL_1], ...) are ignored.
"""
import re
from typing import Callable, Dict, List, Optional, Pattern, Tuple

from interfaces.detection import PIIDetector
from interfaces.verification import VerificationResult
from models.document import NormalizedDocument
from models.pii import PIIFinding
from redaction.redactor import DEFAULT_THRESHOLD, PLACEHOLDER_RE

SAFE = "SAFE"
BLOCKED = "BLOCKED"

_BARE_PLACEHOLDER_RE = re.compile(r"\[?[A-Z][A-Z0-9_]*_\d+\]?")


def _luhn_ok(value: str) -> bool:
    digits = [int(c) for c in value if c.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _iban_ok(value: str) -> bool:
    compact = value.replace(" ", "").upper()
    rearranged = compact[4:] + compact[:4]
    try:
        return int("".join(str(int(c, 36)) for c in rearranged)) % 97 == 1
    except ValueError:
        return False


def _ipv4_ok(value: str) -> bool:
    return all(0 <= int(part) <= 255 for part in value.split("."))


def _not_year_pair(value: str) -> bool:
    """Reject '2025 2026'-style year ranges matched by the split-number pattern."""
    return not all(re.fullmatch(r"(?:19|20)\d\d", part) for part in value.split())


# (type, pattern, confidence, extra check). Patterns are deliberately
# conservative: a safety-net hit blocks the document, so false positives
# here cost more than in the main detector. A pattern with a named group "v"
# reports only that group (the rest is required context, e.g. "passport").
SAFETY_NET: List[Tuple[str, Pattern, float, Optional[Callable[[str], bool]]]] = [
    ("EMAIL", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), 0.99, None),
    # OCR damage: a space before/after "@", or an address cut off before its TLD.
    ("EMAIL", re.compile(r"\b[A-Za-z0-9._%+-]+ ?@ ?[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), 0.9, None),
    ("EMAIL", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9-]{3,}\b"), 0.8, None),
    # SSN/ITIN shape; 9xx is kept on purpose (ITINs and test SSNs are still PII).
    ("SSN", re.compile(r"\b(?!000)\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b"), 0.95, None),
    ("CREDIT_CARD", re.compile(r"\b(?:\d[ -]?){12,18}\d\b"), 0.95, _luhn_ok),
    ("IBAN", re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?\b"), 0.95, _iban_ok),
    # International (+CC ...) or North-American style with separators.
    ("PHONE", re.compile(r"(?<![\w+])(?:\+\d{1,3}[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}\b"), 0.9, None),
    # +CC followed by digit groups; the first group may be bracketed: +1 (555) 0100.
    ("PHONE", re.compile(r"(?<![\w+])\+\d{1,3}[ .-]?(?:\(\d{2,5}\)|\d{2,5})(?:[ .-]?\d{2,5}){1,3}\b"), 0.85, None),
    # Phone fragments: OCR of table columns splits numbers across lines,
    # e.g. "+1 (303)" ... "555-0999" or "+44 20" ... "7946 0001".
    # Dangling prefix: "+1 (303)" anywhere, or a bare "+44" followed by digits/dash/line end.
    ("PHONE", re.compile(r"(?<![\w+])\+\d{1,3}(?: ?\(\d{2,4}\)|(?=[ \t]+[\d\u2014\u2013-]|[ \t]*$))", re.M), 0.8, None),
    ("PHONE", re.compile(r"(?<![\w.-])\d{3}-\d{4}(?![\w-])"), 0.8, None),
    # Standalone "7946 0001" / "20 7946 0001" - not part of a longer digit run like a card number.
    ("PHONE", re.compile(r"(?<![\w.-])(?<!\d )(?<!\d\. )(?:\d{1,3} )?\d{4} \d{4}(?![\w.-])(?! \d)(?! ?[AaPp]\.?[Mm]\b)"), 0.75, _not_year_pair),
    ("PAN", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"), 0.9, None),
    # Date of birth only when labelled as such - ordinary dates are not PII.
    ("DOB", re.compile(r"\b(?:DOB|D\.O\.B\.?|date of birth|born(?: on)?)[ :,]*(?P<v>"
                       r"\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}|\d{4}-\d{2}-\d{2}|"
                       r"\d{1,2} [A-Z][a-z]+ \d{4}|[A-Z][a-z]+ \d{1,2},? \d{4})", re.I), 0.9, None),
    # Street address: number + name + street suffix, plus optional unit.
    ("ADDRESS", re.compile(r"\b\d{1,5} (?:[A-Z][a-z]+ ){1,3}(?:Street|St|Avenue|Ave|Road|Rd|Lane|Ln|Drive|Dr|"
                           r"Boulevard|Blvd|Way|Court|Ct|Place|Pl|Terrace|Close|Crescent|Cres|Parkway|Pkwy|Circle|Cir|Square|Sq|Highway|Hwy|Row|Grove)\b\.?"
                           r"(?:,? (?:Apartment|Apt|Suite|Unit|Flat) ?[A-Z0-9]{1,5}\b)?"), 0.85, None),
    # US "City, ST 12345" tail of an address.
    ("ADDRESS", re.compile(r"\b[A-Z][a-z]+(?: [A-Z][a-z]+)?, [A-Z]{2} \d{5}(?:-\d{4})?\b"), 0.85, None),
    ("PASSPORT", re.compile(r"\bpassport(?: (?:no\.?|number|#))?[ :#]*(?P<v>[A-Z0-9]{6,9})\b", re.I), 0.9,
     lambda v: any(c.isdigit() for c in v)),
    ("IP_ADDRESS", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), 0.85, _ipv4_ok),
]


def _is_placeholder_artifact(value: str) -> bool:
    """True when a detector flagged our own placeholder (e.g. 'PERSON_1')."""
    rest = PLACEHOLDER_RE.sub("", value)
    rest = _BARE_PLACEHOLDER_RE.sub("", rest)
    return not any(ch.isalnum() for ch in rest)


class SecondPassVerificationResult(VerificationResult):
    """VerificationResult plus status and audit-safe residual details.

    status:  SAFE or BLOCKED
    checks:  which scans ran ("detector", "safety_net")
    """

    def __init__(self, is_safe: bool, remaining_findings: List[PIIFinding], checks: List[str]):
        super().__init__(is_safe, remaining_findings)
        self.status = SAFE if is_safe else BLOCKED
        self.checks = checks

    def safe_residuals(self) -> List[Dict[str, object]]:
        """Residual findings without raw values, for the UI and logs."""
        return [{
            "type": f.pii_type,
            "source": f.source,
            "safe_reference": f.masked_value(),
            "detection_method": f.detection_method,
            "confidence": f.confidence,
        } for f in self.remaining_findings]


class SecondPassVerifier:
    """Verifier implementation (see interfaces.verification.Verifier).

    detector:   the team PIIDetector; optional so verification can run before
                the detector is available, but at least one check must be enabled.
    safety_net: run the independent regex checks as well.
    threshold:  detector findings count as residual when validated or at least
                this confident - the same rule the redactor uses.
    """

    def __init__(self, detector: Optional[PIIDetector] = None, safety_net: bool = True,
                 threshold: float = DEFAULT_THRESHOLD):
        if detector is None and not safety_net:
            raise ValueError("verification needs a detector, the safety net, or both")
        self.detector = detector
        self.safety_net = safety_net
        self.threshold = threshold

    def verify(self, document: NormalizedDocument) -> SecondPassVerificationResult:
        residual: List[PIIFinding] = []
        checks: List[str] = []
        if self.detector is not None:
            checks.append("detector")
            for f in self.detector.detect(document):
                if not f.value or _is_placeholder_artifact(f.value):
                    continue
                if f.validated or f.confidence >= self.threshold:
                    residual.append(f)
        if self.safety_net:
            checks.append("safety_net")
            residual.extend(safety_net_scan(document, residual))
        return SecondPassVerificationResult(not residual, residual, checks)


def safety_net_scan(document: NormalizedDocument, already: Optional[List[PIIFinding]] = None) -> List[PIIFinding]:
    """Run only the regex safety net. Findings carry block_id and exact offsets.

    already: findings to skip (same block source and overlapping span).
    """
    found: List[PIIFinding] = []
    # Spans already reported by the detector, so the same leak is not listed twice.
    taken: Dict[str, List[Tuple[int, int]]] = {}
    for f in already or []:
        if f.start is not None and f.end is not None:
            taken.setdefault(f.source, []).append((f.start, f.end))

    for block in document.content:
        # Blank out placeholders (same length) so offsets stay valid.
        text = PLACEHOLDER_RE.sub(lambda m: " " * len(m.group()), block.text)
        spans = list(taken.get(block.source, []))
        for pii_type, pattern, confidence, check in SAFETY_NET:
            for m in pattern.finditer(text):
                group = "v" if "v" in pattern.groupindex else 0
                value = m.group(group).strip()
                start = m.start(group) + (len(m.group(group)) - len(m.group(group).lstrip()))
                end = start + len(value)
                if check and not check(value):
                    continue
                if any(start < e and s < end for s, e in spans):
                    continue
                spans.append((start, end))
                md = {"verification": "safety_net"}
                if block.metadata.get("block_id"):
                    md["block_id"] = block.metadata["block_id"]
                found.append(PIIFinding(pii_type=pii_type, value=value, source=block.source,
                                        confidence=confidence, detection_method="safety_net",
                                        start=start, end=end, validated=True, metadata=md))
    return found


def verify(document: NormalizedDocument, detector: Optional[PIIDetector] = None) -> SecondPassVerificationResult:
    """Convenience entry point: verify(output) -> VerificationResult."""
    return SecondPassVerifier(detector).verify(document)
