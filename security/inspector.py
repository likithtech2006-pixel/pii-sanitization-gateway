"""Hidden-content and prompt-injection inspection.

Finds content a human reviewer would not see but an AI (or a redacted-file reader) would:
  DOCX  tracked insertions/deletions, hidden (vanish) text, white or tiny text, comments,
        macros, external relationships
  PPTX  hidden slides, shapes placed off the slide, notes, macros, external relationships
  PDF   invisible text (render mode 3), fully transparent, white or tiny text, text outside the page,
        embedded files, JavaScript
and scans all extracted text for prompt-injection phrases.

Results are descriptions and locations only, never the hidden text itself. Prompt injection sets
ai_blocked: the AI layer refuses that document (fail closed).
"""
import re
import zipfile
from dataclasses import dataclass, field
from typing import Dict, List

from security import xmlsafe

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"

INJECTION_PATTERNS = [
    ("override_instructions", r"\b(ignore|disregard|forget|override)\b[^.\n]{0,40}\b(previous|prior|above|earlier|all|any|system)\b[^.\n]{0,20}\b(instructions?|prompts?|rules?|guidelines?)\b"),
    ("role_hijack", r"\byou are now\b|\bact as (an?|the)\b[^.\n]{0,40}\b(assistant|ai|model|system)\b|\bnew instructions?\s*:"),
    ("system_prompt_probe", r"\b(reveal|print|show|output|repeat|leak)\b[^.\n]{0,30}\b(system prompt|hidden prompt|your instructions)\b"),
    ("deanonymisation", r"\b(reveal|restore|reconstruct|output|print|identify|guess)\b[^.\n]{0,40}\b(original|real|unredacted|redacted|actual)\b[^.\n]{0,30}\b(names?|values?|data|identit(y|ies)|text|pii)\b"),
    ("disable_safety", r"\b(do not|don't|never)\s+(redact|sanitize|sanitise|mask|anonymi[sz]e)\b|\bbypass\b[^.\n]{0,30}\b(filter|guard|safety|redaction)\b"),
    ("chat_markup", r"<\|im_start\|>|<\|system\|>|\[INST\]|###\s*(system|instruction)s?\b|BEGIN SYSTEM PROMPT"),
    ("exfiltration", r"\b(send|post|upload|exfiltrate|forward)\b[^.\n]{0,40}\b(to|via)\b[^.\n]{0,20}(https?://|webhook|e-?mail address)"),
]
_INJ = [(name, re.compile(rx, re.IGNORECASE)) for name, rx in INJECTION_PATTERNS]


@dataclass
class RiskFinding:
    kind: str
    severity: str          # "high" | "review" | "info"
    location: str
    detail: str


@dataclass
class ContentRisk:
    findings: List[RiskFinding] = field(default_factory=list)

    @property
    def level(self) -> str:
        sev = {f.severity for f in self.findings}
        return "high" if "high" in sev else "review" if "review" in sev else "none"

    @property
    def ai_blocked(self) -> bool:
        return any(f.kind == "prompt_injection" for f in self.findings)

    def kinds(self) -> List[str]:
        return sorted({f.kind for f in self.findings})

    def to_dict(self) -> Dict[str, object]:
        return {"level": self.level, "ai_blocked": self.ai_blocked,
                "findings": [vars(f) for f in self.findings]}


def inspect(data: bytes, ext: str, document) -> ContentRisk:
    risk = ContentRisk()
    try:
        if ext == ".docx":
            _docx(data, risk)
        elif ext == ".pptx":
            _pptx(data, risk)
        elif ext == ".pdf":
            _pdf(data, risk)
    except Exception as e:  # inspection problems are reported, never fatal
        risk.findings.append(RiskFinding("inspection_incomplete", "review", "document",
                                         f"structure could not be fully inspected ({type(e).__name__})"))
    _injection(document, risk)
    return risk


# ------------------------------------------------------------------ prompt injection
def _injection(document, risk: ContentRisk) -> None:
    for block in getattr(document, "content", []) or []:
        for name, rx in _INJ:
            if rx.search(block.text or ""):
                risk.findings.append(RiskFinding("prompt_injection", "high", block.source,
                                                 f"instruction aimed at an AI model ({name.replace('_', ' ')})"))
                break


# ------------------------------------------------------------------ office packages
def _zip(data: bytes):
    import io
    return zipfile.ZipFile(io.BytesIO(data))


def _common_ooxml(z, risk: ContentRisk) -> None:
    names = z.namelist()
    if any(n.lower().endswith("vbaproject.bin") for n in names):
        risk.findings.append(RiskFinding("macros", "review", "package", "contains VBA macros (never executed here)"))
    external = 0
    for n in names:
        if n.endswith(".rels"):
            external += len(re.findall(rb'TargetMode="External"', z.read(n)))
    if external:
        risk.findings.append(RiskFinding("external_links", "info", "package",
                                         f"{external} external relationship(s): links, remote templates or images"))


def _docx(data: bytes, risk: ContentRisk) -> None:
    with _zip(data) as z:
        _common_ooxml(z, risk)
        parts = [n for n in z.namelist() if re.match(r"word/(document|header\d*|footer\d*|footnotes|endnotes)\.xml$", n)]
        dels = ins = vanish = white = tiny = 0
        for name in parts:
            root = xmlsafe.fromstring(z.read(name))
            dels += sum(1 for t in root.iter(_W + "delText") if (t.text or "").strip())
            ins += sum(1 for el in root.iter(_W + "ins") if "".join(t.text or "" for t in el.iter(_W + "t")).strip())
            for r in root.iter(_W + "r"):
                text = "".join(t.text or "" for t in r.iter(_W + "t")).strip()
                if not text:
                    continue
                rpr = r.find(_W + "rPr")
                if rpr is None:
                    continue
                if rpr.find(_W + "vanish") is not None:
                    vanish += 1
                color = rpr.find(_W + "color")
                if color is not None and (color.get(_W + "val") or "").upper() in ("FFFFFF", "FEFEFE"):
                    white += 1
                size = rpr.find(_W + "sz")
                try:
                    if size is not None and int(size.get(_W + "val")) <= 4:      # half-points: <= 2 pt
                        tiny += 1
                except (TypeError, ValueError):
                    pass
        if dels:
            risk.findings.append(RiskFinding("tracked_deletions", "review", "word/document.xml",
                                             f"{dels} tracked deletion(s) still stored in the file"))
        if ins:
            risk.findings.append(RiskFinding("tracked_insertions", "review", "word/document.xml",
                                             f"{ins} unaccepted tracked insertion(s)"))
        if vanish:
            risk.findings.append(RiskFinding("hidden_text", "review", "word/document.xml",
                                             f"{vanish} run(s) formatted as hidden text"))
        if white:
            risk.findings.append(RiskFinding("white_text", "review", "word/document.xml",
                                             f"{white} run(s) in white font colour"))
        if tiny:
            risk.findings.append(RiskFinding("tiny_text", "review", "word/document.xml",
                                             f"{tiny} run(s) at 2 pt or smaller"))
        if "word/comments.xml" in z.namelist():
            root = xmlsafe.fromstring(z.read("word/comments.xml"))
            n = sum(1 for _ in root.iter(_W + "comment"))
            if n:
                risk.findings.append(RiskFinding("comments", "info", "word/comments.xml", f"{n} reviewer comment(s)"))


def _pptx(data: bytes, risk: ContentRisk) -> None:
    with _zip(data) as z:
        _common_ooxml(z, risk)
        pres = xmlsafe.fromstring(z.read("ppt/presentation.xml"))
        size = pres.find(_P + "sldSz")
        cx = int(size.get("cx")) if size is not None else 12192000
        cy = int(size.get("cy")) if size is not None else 6858000
        hidden, offslide, notes = [], 0, 0
        for name in sorted(n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)):
            root = xmlsafe.fromstring(z.read(name))
            num = re.search(r"(\d+)", name.rsplit("/", 1)[1]).group(1)
            if root.get("show") == "0":
                hidden.append(num)
            for off in root.iter(_A + "off"):
                try:
                    x, y = int(off.get("x")), int(off.get("y"))
                except (TypeError, ValueError):
                    continue
                if x >= cx or y >= cy or x < -cx // 2 or y < -cy // 2:
                    offslide += 1
        notes = sum(1 for n in z.namelist() if re.match(r"ppt/notesSlides/notesSlide\d+\.xml$", n))
        if hidden:
            risk.findings.append(RiskFinding("hidden_slides", "review", "slides " + ", ".join(hidden),
                                             f"{len(hidden)} hidden slide(s)"))
        if offslide:
            risk.findings.append(RiskFinding("offslide_content", "review", "slides",
                                             f"{offslide} shape(s) positioned outside the visible slide"))
        if notes:
            risk.findings.append(RiskFinding("speaker_notes", "info", "notes", f"{notes} slide(s) with speaker notes"))


# ------------------------------------------------------------------ PDF
def _pdf(data: bytes, risk: ContentRisk) -> None:
    try:
        import pymupdf
    except ImportError:  # pragma: no cover
        import fitz as pymupdf
    doc = pymupdf.open(stream=data, filetype="pdf")
    try:
        invisible, transparent, white, tiny, offpage = {}, {}, {}, {}, {}
        for i, page in enumerate(doc):
            rect = page.rect
            try:
                spans = page.get_texttrace()
            except Exception:
                continue
            for s in spans:
                chars = len(s.get("chars", ()))
                if not chars:
                    continue
                if s.get("type") == 3:
                    invisible[i + 1] = invisible.get(i + 1, 0) + chars
                elif (s.get("opacity") or 1) == 0:
                    transparent[i + 1] = transparent.get(i + 1, 0) + chars
                elif tuple(round(c, 2) for c in (s.get("color") or ())[:3]) == (1.0, 1.0, 1.0):
                    white[i + 1] = white.get(i + 1, 0) + chars
                if (s.get("size") or 12) < 1.5:
                    tiny[i + 1] = tiny.get(i + 1, 0) + chars
                x0, y0, x1, y1 = s.get("bbox", (0, 0, 0, 0))
                if x1 < rect.x0 or x0 > rect.x1 or y1 < rect.y0 or y0 > rect.y1:
                    offpage[i + 1] = offpage.get(i + 1, 0) + chars
        for kind, found, what in (("invisible_text", invisible, "invisible text layer (render mode 3)"),
                                  ("transparent_text", transparent, "fully transparent text"),
                                  ("white_text", white, "white text"),
                                  ("tiny_text", tiny, "text smaller than 1.5 pt"),
                                  ("offpage_text", offpage, "text outside the visible page")):
            if found:
                pages = ", ".join(str(p) for p in sorted(found)[:12])
                # scanned PDFs often carry an invisible OCR layer; that is expected, so it is informational
                sev = "info" if kind == "invisible_text" else "review"
                risk.findings.append(RiskFinding(kind, sev, f"page {pages}", f"{sum(found.values())} characters of {what}"))
        if doc.embfile_count():
            risk.findings.append(RiskFinding("embedded_files", "review", "document",
                                             f"{doc.embfile_count()} embedded file(s) (not inspected)"))
        js = 0
        for x in range(1, doc.xref_length()):
            try:
                if "/JavaScript" in (doc.xref_object(x) or "") or "/JS " in (doc.xref_object(x) or ""):
                    js += 1
            except Exception:
                continue
        if js:
            risk.findings.append(RiskFinding("javascript", "review", "document", "contains PDF JavaScript (never executed here)"))
    finally:
        doc.close()
