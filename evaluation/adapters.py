"""Adapters that let the evaluation read whatever shape the team modules produce.

The two spec PDFs name some fields differently (blocks / content_blocks,
span / location). Everything here accepts dicts OR objects and tries each
known field name, so a rename in another module does not break evaluation.
"""
import re
from dataclasses import dataclass, field

from evaluation import taxonomy as T


def get_field(obj, *names, default=None):
    """Read the first available field from a dict or an object."""
    for name in names:
        if isinstance(obj, dict):
            if name in obj and obj[name] is not None:
                return obj[name]
        elif hasattr(obj, name):
            value = getattr(obj, name)
            if value is not None:
                return value
    return default


def parse_location(loc):
    """Turn a location into a dict of ints/strings such as {'page': 3}.

    Accepts a dict ({'page': 3, 'paragraph': 2}) or a string such as
    'page 3', 'Slide 2', 'p.3', 'slide=2', 'page_3_block_2', 'table 4 row 1'.
    Returns {} when nothing can be read.
    """
    if loc is None:
        return {}
    if isinstance(loc, dict):
        out = {}
        for key, value in loc.items():
            k = str(key).lower()
            if k in ("page", "slide", "paragraph", "table", "row", "cell", "block", "line"):
                try:
                    out[k] = int(value)
                except (TypeError, ValueError):
                    pass
            elif k in ("image", "header", "footer", "metadata", "notes", "shape"):
                out[k] = value
        return out
    text = str(loc)
    out = {}
    for key in ("page", "slide", "paragraph", "table", "row", "cell", "block", "line"):
        m = re.search(r"(?<![A-Za-z])%s[\s_:=.\-]*(\d+)" % key, text, flags=re.I)
        if m:
            out[key] = int(m.group(1))
    m = re.search(r"(?<![A-Za-z])p\.?\s*(\d+)\b", text, flags=re.I)
    if m and "page" not in out and "slide" not in out:
        out["page"] = int(m.group(1))
    return out


def locations_agree(gold_loc, finding_loc):
    """Compare ONLY page / slide numbers (they are unambiguous).

    Table and paragraph numbering differs between extractors (0- or 1-based),
    so those are not used to accept or reject a match.
    Returns True / False, or None when the finding has no page/slide to compare.
    """
    for key in ("page", "slide"):
        if key in gold_loc:
            if key not in finding_loc:
                return None
            return gold_loc[key] == finding_loc[key]
    return None


def blocks_of(doc):
    """Return the list of content blocks of a NormalizedDocument (either name)."""
    blocks = get_field(doc, "blocks", "content_blocks", "content", default=[])
    return list(blocks)


def block_text(block):
    return get_field(block, "text", "content", default="") or ""


def block_location(block):
    loc = parse_location(get_field(block, "source_location", "location", default=None))
    if not loc:  # models.document.ContentBlock keeps it as JSON in metadata, and as a source string
        meta = get_field(block, "metadata", default={}) or {}
        loc = parse_location(_json_or_none(meta.get("location"))) or parse_location(get_field(block, "source"))
    return loc


def _json_or_none(raw):
    import json
    try:
        return json.loads(raw) if raw else None
    except (TypeError, ValueError):
        return None


def block_index(doc):
    """block_id -> block, so a finding's (block_id, span) can be turned into text."""
    index = {}
    for i, block in enumerate(blocks_of(doc)):
        meta = get_field(block, "metadata", default={}) or {}
        block_id = get_field(block, "block_id", "id", default=None) or meta.get("block_id", i)
        index[block_id] = block
        index[str(block_id)] = block
    return index


@dataclass
class EvalFinding:
    """A finding reduced to what the evaluation needs."""
    type: str
    text: str
    location: dict
    confidence: float = None
    validation_status: str = ""
    detection_method: str = ""
    raw: object = field(default=None, repr=False)


def finding_text(finding, index=None):
    """Get the detected text: explicit field first, else cut it out of its block."""
    direct = get_field(finding, "text", "value", "matched_text", "raw_value", "match")
    if direct is not None:
        return str(direct)
    block_id = get_field(finding, "block_id")
    span = get_field(finding, "span")
    if index is None or block_id is None or span is None:
        return None
    block = index.get(block_id) or index.get(str(block_id))
    if block is None:
        return None
    if isinstance(span, dict):
        start, end = span.get("start"), span.get("end")
    else:
        start, end = span[0], span[1]
    return block_text(block)[int(start):int(end)]


def to_eval_finding(finding, index=None):
    """Convert one team PIIFinding (dict or object) to an EvalFinding."""
    location = parse_location(get_field(finding, "source_location", "location"))
    if not location and index is not None:
        # fall back to the location of the block the finding points to
        meta = get_field(finding, "metadata", default={}) or {}
        block_id = get_field(finding, "block_id", default=None) or meta.get("block_id")
        block = index.get(block_id) if block_id is not None else None
        if block is not None:
            location = block_location(block)
    if not location:  # models.pii.PIIFinding: "page 3", "slide 2 | shape ..."
        location = parse_location(get_field(finding, "source"))
    return EvalFinding(
        type=T.canonical_type(get_field(finding, "type", "pii_type", "entity_type")),
        text=finding_text(finding, index),
        location=location,
        confidence=get_field(finding, "confidence"),
        validation_status=str(get_field(finding, "validation_status", default="")).lower(),
        detection_method=str(get_field(finding, "detection_method", default="")).lower(),
        raw=finding,
    )


def to_eval_findings(findings, doc=None):
    index = block_index(doc) if doc is not None else None
    return [to_eval_finding(f, index) for f in findings]
