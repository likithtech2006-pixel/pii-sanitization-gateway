"""Span-based placeholder redaction.

Every selected finding is replaced in its source block with a typed placeholder
such as [EMAIL_1] or [PERSON_2]. The same value - or the same entity, when the
detector links spellings through metadata["entity_key"] - always maps to the
same placeholder, so the sanitized text keeps its meaning ("[PERSON_1] emailed
[PERSON_2]") without exposing the PII itself.

The input document is never modified; a sanitized deep copy is returned.
Raw PII values are never stored in the result - only masked values and keyed
hashes - so the result is safe to show in the UI or write to logs.
"""
import copy
import hashlib
import hmac
import re
import secrets
from typing import Dict, List, Optional, Tuple

from interfaces.redaction import RedactionResult
from models.document import NormalizedDocument
from models.pii import PIIFinding

DEFAULT_THRESHOLD = 0.5

# Matches placeholders produced by this module, e.g. [EMAIL_1], [ACCOUNT_ID_12].
PLACEHOLDER_RE = re.compile(r"\[[A-Z][A-Z0-9_]*_\d+\]")


class PlaceholderRedactionResult(RedactionResult):
    """RedactionResult plus audit-safe details for the UI, metrics and verifier.

    placeholder_map: placeholder -> {type, masked, value_hash, occurrences}
    skipped:         findings that were not redacted, with the reason
    registry:        (type, value_hash) -> placeholder; lets a later pass keep numbering
    vault:           placeholder -> original value, kept in memory only so a user can see real
                     names in AI answers on their own screen (security/vault.py). Never serialized:
                     to_dict(), reports and certificates do not include it.
    """

    def __init__(
        self,
        document: NormalizedDocument,
        redacted_count: int,
        placeholder_map: Optional[Dict[str, Dict[str, object]]] = None,
        skipped: Optional[List[Dict[str, object]]] = None,
        registry: Optional[Dict[Tuple[str, str], str]] = None,
        vault: Optional[Dict[str, str]] = None,
    ):
        super().__init__(document, redacted_count)
        self.placeholder_map = placeholder_map or {}
        self.skipped = skipped or []
        self.registry = registry or {}
        self.vault = vault or {}

    def __repr__(self) -> str:  # never print vault values
        return f"<PlaceholderRedactionResult redacted={self.redacted_count} placeholders={len(self.placeholder_map)}>"

    def counts_by_type(self) -> Dict[str, int]:
        """Number of redacted occurrences per PII type."""
        counts: Dict[str, int] = {}
        for entry in self.placeholder_map.values():
            counts[entry["type"]] = counts.get(entry["type"], 0) + entry["occurrences"]
        return counts


def _normalize_type(pii_type: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", (pii_type or "PII").upper()).strip("_") or "PII"


def _normalize_value(value: str) -> str:
    """Key used to give repeated values the same placeholder."""
    return " ".join(value.split()).casefold()


def _same_text(a: str, b: str) -> bool:
    """Equal after collapsing whitespace (OCR and detectors differ on spaces/newlines)."""
    return " ".join(a.split()) == " ".join(b.split())


def _find_occurrences(text: str, value: str) -> List[Tuple[int, int]]:
    """All occurrences of value in text that do not sit inside a larger word.

    Case-insensitive, and any run of whitespace in value matches any run of
    whitespace in text, so "Jane Smith" also matches "JANE\nSMITH".
    """
    tokens = value.split()
    if not tokens:
        return []
    pattern = r"\s+".join(re.escape(token) for token in tokens)
    if re.match(r"\w", tokens[0]):
        pattern = r"(?<!\w)" + pattern
    if re.search(r"\w$", tokens[-1]):
        pattern += r"(?!\w)"
    return [m.span() for m in re.finditer(pattern, text, re.IGNORECASE)]


class PlaceholderRedactor:
    """Redactor implementation (see interfaces.redaction.Redactor).

    threshold: findings that are not validated are still redacted when their
    confidence is at least this value. Security-first: anything plausible is
    removed rather than silently passed downstream.
    """

    def __init__(self, threshold: float = DEFAULT_THRESHOLD):
        self.threshold = threshold
        # Per-instance key so hashes cannot be looked up in precomputed tables.
        self._hash_key = secrets.token_bytes(16)

    def _value_hash(self, value: str) -> str:
        digest = hmac.new(self._hash_key, _normalize_value(value).encode("utf-8"), hashlib.sha256)
        return digest.hexdigest()[:12]

    def _should_redact(self, finding: PIIFinding) -> bool:
        return bool(finding.validated) or (finding.confidence or 0.0) >= self.threshold

    def _candidate_blocks(self, document: NormalizedDocument, finding: PIIFinding) -> List[int]:
        """Blocks a finding can belong to: block_id match, then source match, then all."""
        block_id = (finding.metadata or {}).get("block_id")
        if block_id:
            matches = [i for i, b in enumerate(document.content) if b.metadata.get("block_id") == block_id]
            if matches:
                return matches
        if finding.source:
            matches = [i for i, b in enumerate(document.content) if b.source == finding.source]
            if matches:
                return matches
        return list(range(len(document.content)))

    def _locate(self, document: NormalizedDocument, finding: PIIFinding) -> List[Tuple[int, int, int]]:
        """(block_index, start, end) spans for a finding.

        Order: offsets relative to a candidate block, then offsets relative to
        document.full_text() (a detector may scan the whole text), then every
        occurrence of the value in the candidate blocks.
        """
        candidates = self._candidate_blocks(document, finding)
        start, end = finding.start, finding.end
        if start is not None and end is not None:
            for i in candidates:
                text = document.content[i].text
                if 0 <= start < end <= len(text) and _same_text(text[start:end], finding.value):
                    return [(i, start, end)]
            spans = self._full_text_spans(document, start, end, finding.value)
            if spans:
                return spans
        spans = []
        for i in candidates:
            spans.extend((i, s, e) for s, e in _find_occurrences(document.content[i].text, finding.value))
        return spans

    @staticmethod
    def _full_text_spans(document: NormalizedDocument, start: int, end: int,
                         value: str) -> List[Tuple[int, int, int]]:
        """Map offsets in full_text() onto block spans; may cover several blocks."""
        full = document.full_text()
        if not (0 <= start < end <= len(full)) or not _same_text(full[start:end], value):
            return []
        spans, offset = [], 0
        for i, block in enumerate(document.content):
            block_end = offset + len(block.text)
            s, e = max(start, offset), min(end, block_end)
            if s < e and full[s:e].strip():
                spans.append((i, s - offset, e - offset))
            offset = block_end + 1  # full_text() joins blocks with "\n"
        return spans

    def redact(self, document: NormalizedDocument, findings: List[PIIFinding],
               previous: Optional[PlaceholderRedactionResult] = None) -> PlaceholderRedactionResult:
        """Redact findings in a copy of document.

        previous: result of an earlier pass over the same document (e.g. when
        verification found residual PII). Placeholders and counts continue from
        it, so [PERSON_1] keeps meaning the same person.
        """
        sanitized = copy.deepcopy(document)
        skipped: List[Dict[str, object]] = []
        # (block_index, start, end, pii_type, value, identity)
        located: List[Tuple[int, int, int, str, str, str]] = []

        for index, finding in enumerate(findings):
            reason = None
            if not finding.value or not finding.value.strip():
                reason = "empty_value"
            elif not self._should_redact(finding):
                reason = "below_threshold"
            else:
                spans = self._locate(sanitized, finding)
                if not spans:
                    reason = "not_located"
                pii_type = _normalize_type(finding.pii_type)
                # Detectors may tie several spellings to one entity ("Naomi K. Osadebe",
                # "N. Osadebe") via metadata["entity_key"]; they then share a placeholder.
                identity = (finding.metadata or {}).get("entity_key") or finding.value
                located.extend((b, s, e, pii_type, finding.value, identity) for b, s, e in spans)
            if reason:
                skipped.append({
                    "finding_index": index,
                    "type": _normalize_type(finding.pii_type),
                    "source": finding.source,
                    "safe_reference": finding.masked_value() if finding.value else "",
                    "reason": reason,
                })

        # Assign placeholders in document order so [PERSON_1] is the first person mentioned.
        located.sort(key=lambda span: (span[0], span[1], -(span[2] - span[1])))
        placeholders: Dict[Tuple[str, str], str] = dict(previous.registry) if previous else {}
        placeholder_map: Dict[str, Dict[str, object]] = copy.deepcopy(previous.placeholder_map) if previous else {}
        vault: Dict[str, str] = dict(previous.vault) if previous else {}
        counters: Dict[str, int] = {}
        for token in placeholders.values():
            pii_type, number = token[1:-1].rsplit("_", 1)
            counters[pii_type] = max(counters.get(pii_type, 0), int(number))
        spans_by_block: Dict[int, List[Tuple[int, int, str]]] = {}

        for block_index, start, end, pii_type, value, identity in located:
            key = (pii_type, self._value_hash(identity))
            if key not in placeholders:
                counters[pii_type] = counters.get(pii_type, 0) + 1
                token = f"[{pii_type}_{counters[pii_type]}]"
                placeholders[key] = token
                vault[token] = value
                placeholder_map[token] = {
                    "type": pii_type,
                    "masked": PIIFinding(pii_type, value, "", 0.0, "").masked_value(),
                    "value_hash": self._value_hash(identity),
                    "occurrences": 0,
                }
            spans_by_block.setdefault(block_index, []).append((start, end, placeholders[key]))

        redacted_count = 0
        for block_index, spans in spans_by_block.items():
            merged = self._merge_overlaps(spans)
            block = sanitized.content[block_index]
            text = block.text
            for start, end, token in reversed(merged):  # right-to-left keeps earlier offsets valid
                text = text[:start] + token + text[end:]
                placeholder_map[token]["occurrences"] += 1
            block.text = text
            block.metadata["redacted_spans"] = str(int(block.metadata.get("redacted_spans", "0")) + len(merged))
            redacted_count += len(merged)

        # Drop placeholders whose only spans were absorbed by an overlapping, longer span.
        placeholder_map = {t: v for t, v in placeholder_map.items() if v["occurrences"] > 0}
        vault = {t: v for t, v in vault.items() if t in placeholder_map}

        if previous:
            redacted_count += previous.redacted_count
            skipped = previous.skipped + skipped
        sanitized.metadata["redaction_status"] = "redacted"
        sanitized.metadata["redacted_count"] = str(redacted_count)
        return PlaceholderRedactionResult(sanitized, redacted_count, placeholder_map, skipped, placeholders, vault)

    @staticmethod
    def _merge_overlaps(spans: List[Tuple[int, int, str]]) -> List[Tuple[int, int, str]]:
        """Merge overlapping spans; the longest original span names the merged one."""
        merged: List[List[object]] = []  # [start, end, token, longest_len]
        for start, end, token in sorted(spans):
            if merged and start < merged[-1][1]:
                current = merged[-1]
                if end - start > current[3]:
                    current[2], current[3] = token, end - start
                current[1] = max(current[1], end)
            else:
                merged.append([start, end, token, end - start])
        return [(s, e, t) for s, e, t, _ in merged]


def redact(document: NormalizedDocument, findings: List[PIIFinding],
           threshold: float = DEFAULT_THRESHOLD) -> PlaceholderRedactionResult:
    """Convenience entry point: redact(document, findings) -> RedactionResult."""
    return PlaceholderRedactor(threshold).redact(document, findings)
