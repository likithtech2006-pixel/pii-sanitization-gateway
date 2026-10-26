"""Downstream AI layer: the only door through which document content leaves the pipeline.

    from ai_layer import analyze
    analysis = analyze(gate_result)                    # brief of the sanitized document
    analysis = analyze(gate_result, "Who approves risk acceptance?")
    print(analysis.to_markdown())

Guarantees
  1. Only a SAFE GateResult is accepted; BLOCKED documents raise AnalysisBlocked.
  2. Egress guard: right before anything is sent, the outgoing text is scanned again
     with the independent safety net. Any hit blocks the call (defence in depth).
  3. Only sanitized text with placeholders ([PERSON_3], [EMAIL_2]) is ever used.
     Placeholder-to-value mappings never exist in clear text, so they cannot leak.

Providers
  local      (default) offline, deterministic brief: structure, headings, obligations
             ("must"/"shall" statements), key terms, PII placeholders, and simple
             passage retrieval for a question. Nothing leaves the machine.
  anthropic  used when ANTHROPIC_API_KEY is set (or provider="anthropic"):
             sends the sanitized text to Claude. Model from ANTHROPIC_MODEL.
"""
import json
import os
import re
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from models.document import ContentBlock, NormalizedDocument
from redaction import PLACEHOLDER_RE, GateResult, safety_net_scan

DEFAULT_MODEL = "claude-sonnet-5-5"
MAX_CHARS = 180_000

_STOP = set("""a an the and or of for to in on at by with from as is are be been was were this that these those
it its our your their his her they them we you he she i not no yes all any each every other such than then
there here which who whom whose what when where why how can could may might must shall should will would
do does did has have had into onto over under per via also only more most less least very within without
upon about after before between across through during against including include includes included
section page table figure appendix version group policy document""".split())


class AnalysisBlocked(Exception):
    """Raised when content may not leave the pipeline."""


@dataclass
class AnalysisResult:
    provider: str
    document: str
    summary: str
    sections: Dict[str, object] = field(default_factory=dict)
    question: Optional[str] = None
    answer: Optional[str] = None

    def to_markdown(self) -> str:
        lines = [f"# Analysis of {self.document}", "",
                 f"_Provider: {self.provider}. Input: sanitized text only (placeholders, no raw PII)._", "",
                 self.summary.strip(), ""]
        for title, value in self.sections.items():
            lines += [f"## {title}", ""]
            if isinstance(value, list):
                lines += [f"- {v}" for v in value] or ["- (none)"]
            elif isinstance(value, dict):
                lines += [f"- {k}: {v}" for k, v in value.items()] or ["- (none)"]
            else:
                lines.append(str(value))
            lines.append("")
        if self.question:
            lines += ["## Question", "", self.question, "", "## Answer", "", self.answer or "(no answer)", ""]
        return "\n".join(lines)


# ----------------------------------------------------------------- guards
def egress_check(text: str) -> List[str]:
    """Scan outgoing text with the independent safety net; returns PII types found."""
    doc = NormalizedDocument("egress", "text", "egress", [ContentBlock(text, "egress")])
    return sorted({f.pii_type for f in safety_net_scan(doc)})


def _released(gate: GateResult) -> str:
    if not isinstance(gate, GateResult) or not gate.is_safe:
        reason = getattr(gate, "reason", "not_verified")
        raise AnalysisBlocked(f"document is not SAFE ({reason}); nothing is sent downstream")
    if gate.document.metadata.get("prompt_injection") == "true":
        raise AnalysisBlocked("possible prompt injection found in the document; AI analysis is disabled for it")
    text = gate.released_text() or ""
    leaks = egress_check(text)
    if leaks:
        raise AnalysisBlocked(f"egress guard found {', '.join(leaks)} in the outgoing text; call blocked")
    return text


# ----------------------------------------------------------- local provider
_HEADING = re.compile(r"^(?:\d+(?:\.\d+)*\.?\s+)?[A-Z][^\n]{2,70}$")
_OBLIGATION = re.compile(r"\b(must|shall|is required to|are required to|may not|must not|is prohibited|are prohibited)\b", re.I)


def _slide_titles(blocks: List[ContentBlock]) -> List[str]:
    """First text block of each slide (decks rarely number their headings)."""
    seen, out = set(), []
    for b in blocks:
        m = re.match(r"slide (\d+)", b.source)
        if m and m.group(1) not in seen and "image OCR" not in b.source and len(b.text.split()) <= 12:
            seen.add(m.group(1))
            out.append(f"Slide {m.group(1)}: {b.text.strip()}")
    return out


def _headings(blocks: List[ContentBlock]) -> List[str]:
    if any(b.source.startswith("slide") for b in blocks):
        return _slide_titles(blocks)
    out = []
    for b in blocks:
        t = b.text.strip()
        if "\n" in t or len(t.split()) > 9 or t.endswith((".", ",", ";")) or PLACEHOLDER_RE.search(t):
            continue
        if re.match(r"^\d+(\.\d+)*\.?\s+[A-Z]", t) and _HEADING.match(t) \
                and not re.match(r"^\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)", t):
            out.append(t)
    seen, unique = set(), []
    for h in out:
        key = re.sub(r"^[\d.\s]+", "", h).lower()          # "1 Purpose" (contents) == "1. Purpose"
        if key not in seen:
            seen.add(key)
            unique.append(h)
    return unique[:30]


def _sentences(text: str) -> List[str]:
    flat = re.sub(r"\s+", " ", text)
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z\[])", flat) if 25 <= len(s.strip()) <= 400]


def _terms(text: str, n: int = 15) -> List[str]:
    words = re.findall(r"(?<![\w-])[A-Za-z][a-z]{3,}(?:-[a-z]+)*(?![\w-])", PLACEHOLDER_RE.sub(" ", text))
    counts = Counter(w.lower() for w in words if w.lower() not in _STOP)
    return [f"{w} ({c})" for w, c in counts.most_common(n)]


def _people(blocks: List[ContentBlock], limit: int = 12) -> List[str]:
    """Sanitized lines that mention a person placeholder: who owns, approves or is contacted for what."""
    out, seen = [], set()
    for b in blocks:
        if b.source.startswith("metadata") or "[PERSON_" not in b.text:
            continue
        line = re.sub(r"\s+", " ", b.text).strip()[:300]
        if line not in seen:
            seen.add(line)
            out.append(f"{line}  ({b.source})")
        if len(out) >= limit:
            break
    return out


def _retrieve(blocks: List[ContentBlock], question: str, k: int = 5) -> List[str]:
    q = {w.lower() for w in re.findall(r"[A-Za-z]{3,}", question)} - _STOP
    scored = []
    for b in blocks:
        words = {w.lower() for w in re.findall(r"[A-Za-z]{3,}", b.text)}
        score = len(q & words)
        if score:
            scored.append((score, len(b.text), b))
    scored.sort(key=lambda x: (-x[0], -x[1]))
    return [f"[{b.source}] {re.sub(chr(10), ' ', b.text)[:400]}" for _, _, b in scored[:k]]


def _local(gate: GateResult, text: str, question: Optional[str]) -> AnalysisResult:
    doc = gate.document
    blocks = doc.content
    pages = {re.match(r"(page|slide) (\d+)", b.source).group(0) for b in blocks if re.match(r"(page|slide) \d+", b.source)}
    counts = gate.redaction.counts_by_type()
    people = sum(1 for t in gate.redaction.placeholder_map if t.startswith("[PERSON_"))
    obligations = [s for s in _sentences(text) if _OBLIGATION.search(s)]
    summary = (f"{doc.file_name} ({doc.source_type.upper()}) was verified SAFE and contains "
               f"{len(blocks)} text blocks" + (f" across {len(pages)} pages/slides" if pages else "") +
               f". {gate.redaction.redacted_count} PII occurrences were replaced with placeholders, "
               f"covering {people} distinct people. Placeholders keep roles intact, so statements such as "
               f"who owns or approves something can still be analysed without identities.")
    sections: Dict[str, object] = {
        "Structure (section headings)": _headings(blocks),
        "Obligations and requirements (must / shall)": obligations[:12],
        "People and their roles (placeholders)": _people(blocks),
        "Key terms": _terms(text),
        "Personal data removed (by type)": {k: v for k, v in sorted(counts.items())},
    }
    answer = None
    if question:
        hits = _retrieve(blocks, question)
        answer = ("Most relevant passages (sanitized):\n\n" + "\n".join(f"- {h}" for h in hits)) if hits \
            else "No passage in the document matches the question."
    return AnalysisResult("local (offline)", doc.file_name, summary, sections, question, answer)


# ------------------------------------------------------- anthropic provider
_SYSTEM = ("You analyse business documents for a security team. Personal data in the text has been "
           "replaced with typed placeholders such as [PERSON_3] or [EMAIL_2]. Keep the placeholders "
           "exactly as written, never guess the real values, and never try to re-identify anyone.")


def _anthropic(gate: GateResult, text: str, question: Optional[str]) -> AnalysisResult:
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        raise AnalysisBlocked("ANTHROPIC_API_KEY is not set")
    model = os.getenv("ANTHROPIC_MODEL", DEFAULT_MODEL)
    task = question or ("Summarise this document in 5-8 bullet points, then list its key risks, "
                        "obligations and owners (by placeholder or role).")
    body = {
        "model": model, "max_tokens": 1500, "system": _SYSTEM,
        "messages": [{"role": "user", "content": f"<document name=\"{gate.document.file_name}\">\n"
                                                 f"{text[:MAX_CHARS]}\n</document>\n\n{task}"}],
    }
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise AnalysisBlocked(f"Anthropic API error {e.code}") from None
    except urllib.error.URLError as e:
        raise AnalysisBlocked(f"Anthropic API unreachable ({e.reason})") from None
    reply = "".join(part.get("text", "") for part in data.get("content", []) if part.get("type") == "text")
    if question:
        return AnalysisResult(f"anthropic ({model})", gate.document.file_name,
                              "Answer generated from the sanitized document.", {}, question, reply)
    return AnalysisResult(f"anthropic ({model})", gate.document.file_name, reply)


# ------------------------------------------------------------------- entry
def analyze(gate: GateResult, question: Optional[str] = None, provider: Optional[str] = None) -> AnalysisResult:
    """Analyse a SAFE document. Raises AnalysisBlocked for anything else."""
    text = _released(gate)
    provider = provider or ("anthropic" if os.getenv("ANTHROPIC_API_KEY") else "local")
    if provider == "anthropic":
        return _anthropic(gate, text, question)
    if provider == "local":
        return _local(gate, text, question)
    raise ValueError(f"unknown provider {provider!r} (use 'local' or 'anthropic')")
