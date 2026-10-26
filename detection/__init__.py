"""PII detection module.

Public interface (implements interfaces.detection.PIIDetector):

    from detection import detect, PIIDetectorImpl
    findings = detect(document)                 # List[PIIFinding]
    detector = PIIDetectorImpl(); detector.detect(document)
    detect_text("Contact jane@example.com")     # quick checks on a string

Every finding carries the block it came from (source + metadata["block_id"])
and block-relative start/end offsets, so redaction is exact and traceable.
Person findings also carry metadata["entity_key"]: all spellings of the same
person ("Naomi K. Osadebe", "N. Osadebe", "Osadebe") share it, so they get the
same placeholder.

Detection runs fully locally. spaCy NER is used when installed
(model from env PII_SPACY_MODEL, default en_core_web_sm); without it the
rule-based name evidence (context cues, e-mail corroboration, table headers)
still runs and info()["ner"] reports "rules-only".
"""
import json
import os
import re
from typing import Dict, List, Tuple

from detection.names import NameDetector
from detection.patterns import RECOGNIZERS
from models.document import ContentBlock, NormalizedDocument
from models.pii import PIIFinding

PLACEHOLDER_RE = re.compile(r"\[[A-Z][A-Z0-9_]*_\d+\]")

_NLP = None
_NLP_STATUS = None


def _load_nlp():
    """Load spaCy once; return None (rules-only) if it is not available."""
    global _NLP, _NLP_STATUS
    if _NLP_STATUS is not None:
        return _NLP
    if os.getenv("PII_DISABLE_NER") == "1":
        _NLP_STATUS = "rules-only (disabled by PII_DISABLE_NER)"
        return None
    model = os.getenv("PII_SPACY_MODEL", "en_core_web_sm")
    try:
        import spacy
        _NLP = spacy.load(model, disable=["parser", "lemmatizer", "tagger", "attribute_ruler"])
        _NLP_STATUS = f"spacy {spacy.__version__} / {model}"
    except Exception as exc:  # spaCy or the model missing -> still works, rule-based names only
        _NLP = None
        _NLP_STATUS = f"rules-only ({type(exc).__name__}: install spaCy and {model} for NER)"
    return _NLP


def info() -> Dict[str, str]:
    """Which detection engines are active (shown in the UI and reports)."""
    _load_nlp()
    return {"structured": f"{len(RECOGNIZERS)} regex/checksum recognizers", "ner": _NLP_STATUS}


def _blank_placeholders(text: str) -> str:
    """Replace [EMAIL_1]-style placeholders with spaces of equal length (offsets stay valid)."""
    return PLACEHOLDER_RE.sub(lambda m: " " * len(m.group()), text)


def _location(block: ContentBlock) -> dict:
    try:
        return json.loads(block.metadata.get("location", "{}"))
    except ValueError:
        return {}


def _table_headers(blocks: List[ContentBlock]) -> Dict[int, str]:
    """Block index -> labels of its table cell: the column header (row 0) and the
    row label (column 0), e.g. "USERS" or "Peer Reviewer"."""
    column: Dict[Tuple, str] = {}
    row_label: Dict[Tuple, str] = {}
    cells = []
    for i, b in enumerate(blocks):
        loc = _location(b)
        if "row" not in loc or "col" not in loc:
            continue
        table = (loc.get("type"), loc.get("slide"), loc.get("shape"), loc.get("table"), loc.get("section"))
        r, c = int(loc["row"]), int(loc["col"])
        if r == 0:
            column[(table, c)] = b.text
        if c == 0:
            row_label[(table, r)] = b.text
        if r > 0 or c > 0:
            cells.append((i, table, r, c))
    out = {}
    for i, table, r, c in cells:
        labels = [column.get((table, c), "") if r > 0 else "", row_label.get((table, r), "") if c > 0 else ""]
        label = " | ".join(x for x in labels if x)
        if label:
            out[i] = label
    return out


def _resolve_overlaps(spans):
    """Keep the longest, then most confident, span where structured matches overlap."""
    kept = []
    for span in sorted(spans, key=lambda s: (-(s["end"] - s["start"]), -s["confidence"], s["start"])):
        if all(span["end"] <= k["start"] or k["end"] <= span["start"] for k in kept):
            kept.append(span)
    return sorted(kept, key=lambda s: s["start"])


def structured_spans(text: str) -> List[dict]:
    """Run every structured recognizer over one text; overlaps resolved."""
    spans = []
    for pii_type, pattern, confidence, check in RECOGNIZERS:
        group = "v" if "v" in pattern.groupindex else 0
        for m in pattern.finditer(text):
            raw = m.group(group)
            value = raw.strip().rstrip(".,;:")
            if not value or (check and not check(value)):
                continue
            start = m.start(group) + (len(raw) - len(raw.lstrip()))
            spans.append({"type": pii_type, "start": start, "end": start + len(value), "value": value,
                          "confidence": confidence, "method": "regex"})
    return _resolve_overlaps(spans)


def _add_domain_fragments(texts: List[str], structured: List[List[dict]], emails: List[str]) -> None:
    """OCR sometimes destroys the "@" of an address ("jobnsondpacmecorp.cor"). A token that
    contains the domain name of an address found elsewhere in the document is still an e-mail."""
    labels = set()
    for e in emails:
        domain = e.split("@")[-1].lower()
        label = domain.split(".")[0]
        if len(label) >= 5:
            labels.add(label)
    if not labels:
        return
    rx = re.compile(r"(?<!\S)\S*(?:" + "|".join(re.escape(l) for l in sorted(labels)) + r")\S*", re.I)
    for i, text in enumerate(texts):
        for m in rx.finditer(text):
            s, e = m.start(), m.end()
            value = m.group(0).rstrip(".,;:)")
            e = s + len(value)
            if "@" in value or len(value) < 8 or any(s < x["end"] and x["start"] < e for x in structured[i]):
                continue
            # needs a mangled local part before the domain and a dot after it - not just "Northwind"
            low = value.lower()
            pos = min(low.find(l) for l in labels if l in low)
            if pos < 2 or "." not in low[pos:]:
                continue
            # company web addresses are not personal data
            if re.match(r"(?i)(?:https?://|www\.)", value):
                continue
            structured[i].append({"type": "EMAIL", "start": s, "end": e, "value": value,
                                  "confidence": 0.7, "method": "regex_domain_fragment"})


class PIIDetectorImpl:
    """Hybrid detector: structured recognizers + document-level name detection."""

    def __init__(self, use_ner: bool = True):
        self.use_ner = use_ner

    def detect(self, document: NormalizedDocument) -> List[PIIFinding]:
        blocks = document.content
        texts = [_blank_placeholders(b.text) for b in blocks]

        structured = [structured_spans(t) for t in texts]
        emails = [s["value"].replace(" ", "") for spans in structured for s in spans if s["type"] == "EMAIL"]
        _add_domain_fragments(texts, structured, emails)

        headers = _table_headers(blocks)
        name_input = []
        for i, b in enumerate(blocks):
            loc = _location(b)
            name_input.append((i, texts[i], {
                "picture": bool(loc.get("image_ocr")) or b.metadata.get("kind") == "picture_ocr",
                "figure": b.metadata.get("kind") == "figure_ocr",
                "table_header": headers.get(i, ""),
                "metadata_field": loc.get("field") if loc.get("type") == "metadata" else None,
            }))
        names = NameDetector(_load_nlp() if self.use_ner else None).detect(name_input, emails)

        findings: List[PIIFinding] = []
        for i, b in enumerate(blocks):
            md_base = {"block_id": b.metadata.get("block_id", ""), "block_type": b.block_type}
            for s in structured[i]:
                findings.append(PIIFinding(
                    pii_type=s["type"], value=s["value"], source=b.source, confidence=s["confidence"],
                    detection_method=s["method"], start=s["start"], end=s["end"],
                    validated=s["confidence"] >= 0.9, metadata=dict(md_base)))
        taken = {i: [(s["start"], s["end"]) for s in spans] for i, spans in enumerate(structured)}
        for n in names:
            i = n["block"]
            if any(n["start"] < e and s < n["end"] for s, e in taken[i]):
                continue                                   # e-mail/phone/id already covers it
            b = blocks[i]
            md = {"block_id": b.metadata.get("block_id", ""), "block_type": b.block_type,
                  "entity_key": n["key"]}
            findings.append(PIIFinding(
                pii_type="PERSON", value=n["value"], source=b.source, confidence=n["confidence"],
                detection_method=n["method"], start=n["start"], end=n["end"],
                validated=n["confidence"] >= 0.85, metadata=md))
        return findings


_DEFAULT = PIIDetectorImpl()


def detect(document: NormalizedDocument) -> List[PIIFinding]:
    """Module-level entry point: detect(document) -> List[PIIFinding]."""
    return _DEFAULT.detect(document)


def detect_text(text: str) -> List[dict]:
    """Detect PII in a plain string (used by the evaluation test cases).
    Returns dicts with type, text, value, start, end, confidence."""
    doc = NormalizedDocument("text", "text", "text", [ContentBlock(text, "text", metadata={"block_id": "t0"})])
    return [{"type": f.pii_type, "text": f.value, "value": f.value, "start": f.start, "end": f.end,
             "confidence": f.confidence, "detection_method": f.detection_method}
            for f in detect(doc)]
