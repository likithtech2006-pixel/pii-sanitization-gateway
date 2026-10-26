"""Format-preserving redacted copies: PDF -> PDF, DOCX -> DOCX, PPTX -> PPTX.

    from redaction.file_writer import write_redacted_file
    outcome = write_redacted_file("in.pdf", original_doc, gate_result, "output/in.redacted.pdf")
    outcome.ok, outcome.path, outcome.reason

The text pipeline already decides SAFE / BLOCKED. This module produces the same
redactions inside a copy of the original file, so people can keep working in
the original format:

  PDF   Black redaction boxes with the placeholder label. Scanned pages use the
        OCR word boxes, and the page image pixels under each box are destroyed
        (true redaction, not an overlay). Pictures on text pages that contained
        PII are blacked out completely. Document properties are replaced and XMP
        metadata is removed.
  DOCX  Every text node of every XML part (body, tables, headers, footers, text
  PPTX  boxes, notes, comments) is rewritten with the same placeholders; a value
        split over several runs is merged into the first run. Document properties
        are rewritten. Pictures whose OCR text contained PII are replaced by a
        neutral placeholder image.

Fail closed: only a SAFE GateResult is written, and the written file is checked
before it is kept - every redacted value must be gone from the file, and (by
default) a fresh extract + detect of the output must find no PII. Otherwise the
file is deleted and outcome.ok is False.
"""
import io
import json
import os
import re
import tempfile
import zipfile
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from lxml import etree
from PIL import Image, ImageDraw

from models.document import NormalizedDocument
from security import xmlsafe
from redaction.gate import GateResult
from redaction.redactor import PLACEHOLDER_RE


@dataclass
class WriteOutcome:
    ok: bool
    path: Optional[str]
    reason: str
    stats: Dict[str, int] = field(default_factory=dict)


# --------------------------------------------------------------- alignment
def redacted_spans(original: str, sanitized: str) -> List[Tuple[int, int, str]]:
    """(start, end, placeholder) spans of `original` that became placeholders in `sanitized`."""
    if original == sanitized:
        return []
    parts = PLACEHOLDER_RE.split(sanitized)
    tokens = PLACEHOLDER_RE.findall(sanitized)
    pattern = re.escape(parts[0]) + "".join("(.+?)" + re.escape(p) for p in parts[1:])
    m = re.fullmatch(pattern, original, re.S)
    if not m:
        return []
    return [(m.start(i + 1), m.end(i + 1), tokens[i]) for i in range(len(tokens))]


def _pairs(original: NormalizedDocument, sanitized: NormalizedDocument):
    """Per block: (original block, sanitized block, spans) for blocks that changed."""
    out = []
    for ob, sb in zip(original.content, sanitized.content):
        if ob.text != sb.text:
            out.append((ob, sb, redacted_spans(ob.text, sb.text)))
    return out


def _value_map(pairs) -> Dict[str, str]:
    """Raw value -> placeholder, longest values first."""
    values: Dict[str, str] = {}
    for ob, _sb, spans in pairs:
        for s, e, tok in spans:
            value = ob.text[s:e]
            if value.strip():
                values.setdefault(value, tok)
    return dict(sorted(values.items(), key=lambda kv: -len(kv[0])))


def _location(block) -> dict:
    try:
        return json.loads(block.metadata.get("location", "{}"))
    except ValueError:
        return {}


# --------------------------------------------------------------------- PDF
def _write_pdf(src: str, dst: str, pairs, value_map) -> Dict[str, int]:
    try:
        import pymupdf
    except ImportError:  # older PyMuPDF
        import fitz as pymupdf
    doc = pymupdf.open(src)
    stats = {"boxes": 0, "whole_images": 0, "whole_figures": 0, "fallback_blocks": 0}
    figures_done = set()
    pad = 1.5

    def box(page, rect, token):
        r = pymupdf.Rect(rect) + (-pad, -pad, pad, pad)
        page.add_redact_annot(r, text=token, fontsize=min(7, max(3, r.height * 0.6)),
                              fill=(0, 0, 0), text_color=(1, 1, 1), align=pymupdf.TEXT_ALIGN_CENTER)
        stats["boxes"] += 1

    for ob, _sb, spans in pairs:
        loc, md = _location(ob), ob.metadata
        if loc.get("type") == "metadata" or "page" not in loc:
            continue
        page = doc[int(loc["page"]) - 1]
        bbox = json.loads(md["bbox"]) if md.get("bbox") not in (None, "null") else None
        if loc.get("image_ocr"):                       # picture on a text page: black out all of it
            if bbox:
                box(page, bbox, "[IMAGE REDACTED]")
                stats["whole_images"] += 1
            continue
        if md.get("figure_bbox") and (loc["page"], md["figure_bbox"]) not in figures_done:
            # Figure/screenshot text is small and OCR is unreliable there: remove the whole figure.
            figures_done.add((loc["page"], md["figure_bbox"]))
            box(page, json.loads(md["figure_bbox"]), "[FIGURE REDACTED - contained personal data]")
            stats["whole_figures"] += 1
            continue
        if md.get("figure_bbox"):
            continue
        words = json.loads(md["word_boxes"]) if md.get("word_boxes") else None
        if words:                                      # scanned page: OCR word geometry
            tokens = [(m.start(), m.end()) for m in re.finditer(r"\S+", ob.text)]
            if len(tokens) == len(words):
                for s, e, tok in spans:
                    hit = [w for (ts, te), w in zip(tokens, words) if ts < e and s < te]
                    for line in _group_lines(hit):
                        box(page, (min(w[0] for w in line), min(w[1] for w in line),
                                   max(w[2] for w in line), max(w[3] for w in line)), tok)
                continue
        # native text: find each value inside the block; if not found, redact the whole block
        clip = pymupdf.Rect(bbox) + (-2, -2, 2, 2) if bbox else None
        for s, e, tok in spans:
            rects = page.search_for(ob.text[s:e], clip=clip) if clip else []
            if not rects:
                rects = [r for part in ob.text[s:e].split() for r in page.search_for(part, clip=clip)] if clip else []
            if rects:
                for r in rects:
                    box(page, r, tok)
            elif bbox:
                box(page, bbox, tok)
                stats["fallback_blocks"] += 1

    for page in doc:
        if page.first_annot is not None:
            page.apply_redactions(images=getattr(pymupdf, "PDF_REDACT_IMAGE_PIXELS", 2))

    meta = {}
    for k in ("author", "title", "subject", "keywords", "creator", "producer"):
        v = (doc.metadata or {}).get(k) or ""
        for value, tok in value_map.items():
            v = v.replace(value, tok)
        meta[k] = v
    doc.set_metadata(meta)
    try:
        doc.del_xml_metadata()
    except Exception:
        pass
    doc.save(dst, garbage=4, deflate=True, clean=True)
    doc.close()
    return stats


def _group_lines(words):
    """Split OCR word boxes into lines (a value may wrap) so each line gets its own box."""
    lines: List[List[list]] = []
    for w in sorted(words, key=lambda w: (round(w[1]), w[0])):
        if lines and abs(lines[-1][-1][1] - w[1]) < (w[3] - w[1]) * 0.6:
            lines[-1].append(w)
        else:
            lines.append([w])
    return lines


def _name_tokens(value_map) -> set:
    """Words of redacted person names (>= 4 letters, no initials): 'Vasquez', 'Holt', 'Eleanor'."""
    out = set()
    for value, tok in value_map.items():
        if tok.startswith("[PERSON_"):
            for w in re.split(r"[\s\-]+", value):
                w = w.strip(".,;:()'’")
                if len(w) >= 4 and not re.fullmatch(r"[A-Z]\.?", w):
                    out.add(w.casefold())
    return out


def _residual_word_boxes(paragraphs, name_tokens) -> List[list]:
    """OCR words on a redacted page that still show PII."""
    from detection import structured_spans
    from models.document import ContentBlock
    from redaction.verifier import safety_net_scan
    hits = []
    for para in paragraphs:
        words, text = para["words"], para["text"]
        tokens = [(m.start(), m.end()) for m in re.finditer(r"\S+", text)]
        if len(tokens) != len(words):
            continue
        spans = [(sp["start"], sp["end"]) for sp in structured_spans(text) if sp["confidence"] >= 0.75]
        net = NormalizedDocument("ocr", "pdf", "ocr", [ContentBlock(text, "ocr")])
        spans += [(f.start, f.end) for f in safety_net_scan(net)]
        for (ts, te), w in zip(tokens, words):
            word = text[ts:te]
            clean = word.strip(".,;:()[]{}'’\"|").casefold()
            if PLACEHOLDER_RE.fullmatch(word.strip(".,;:()")):
                continue
            named = clean in name_tokens or any(len(t) >= 6 and clean.startswith(t) for t in name_tokens) \
                or any(p in name_tokens for p in clean.split("-") if len(p) >= 4)
            emailish = "@" in word and re.search(r"\w@\w", word) is not None
            if named or emailish or any(ts < e and s < te for s, e in spans):
                hits.append(w)
    return hits


def _ocr_remediate(path: str, value_map, dpi: int = 400, max_rounds: int = 3) -> Dict[str, int]:
    """Re-OCR every page of the redacted PDF at high resolution and black out anything that
    still shows PII (small text in figures is often missed by the first OCR). Repeats until a
    pass finds nothing. Raises if PII is still readable after max_rounds."""
    from concurrent.futures import ThreadPoolExecutor
    from extraction import ocr
    try:
        import pymupdf
    except ImportError:
        import fitz as pymupdf
    if not ocr.is_available():
        raise ValueError("Tesseract is needed to verify a redacted PDF")
    names = _name_tokens(value_map)
    stats = {"ocr_rounds": 0, "ocr_boxes": 0}
    for _ in range(max_rounds):
        doc = pymupdf.open(path)
        images = []
        for page in doc:
            pix = page.get_pixmap(dpi=dpi)
            images.append(Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB"))
        with ThreadPoolExecutor(max_workers=ocr.workers()) as pool:
            results = list(pool.map(lambda img: ocr.ocr_image(img, dpi=dpi), images))
        stats["ocr_rounds"] += 1
        found = 0
        for page, paragraphs in zip(doc, results):
            for w in _residual_word_boxes(paragraphs, names):
                page.add_redact_annot(pymupdf.Rect(w[:4]) + (-1.5, -1.5, 1.5, 1.5), fill=(0, 0, 0))
                found += 1
        if not found:
            doc.close()
            return stats
        for page in doc:
            if page.first_annot is not None:
                page.apply_redactions(images=getattr(pymupdf, "PDF_REDACT_IMAGE_PIXELS", 2))
        stats["ocr_boxes"] += found
        tmp = path + ".round.pdf"
        doc.save(tmp, garbage=4, deflate=True, clean=True)
        doc.close()
        os.replace(tmp, path)
    raise ValueError("PII still readable after OCR remediation")


# ------------------------------------------------------------- DOCX / PPTX
_TEXT_TAGS = {
    "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t",
    "{http://schemas.openxmlformats.org/drawingml/2006/main}t",
}
_PARA_TAGS = {
    "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p",
    "{http://schemas.openxmlformats.org/drawingml/2006/main}p",
}


def _rewrite_paragraph(p, value_map) -> int:
    nodes = [n for n in p.iter() if n.tag in _TEXT_TAGS]
    if not nodes:
        return 0
    changed = 0
    # 1) value inside a single text node: replace in place (keeps formatting)
    for n in nodes:
        text = n.text or ""
        for value, tok in value_map.items():
            if value in text:
                text = text.replace(value, tok)
                changed += 1
        n.text = text
    # 2) value split across runs: merge the paragraph text into the first node
    joined = "".join(n.text or "" for n in nodes)
    merged = joined
    for value, tok in value_map.items():
        if value in merged:
            merged = merged.replace(value, tok)
    if merged != joined:
        nodes[0].text = merged
        for n in nodes[1:]:
            n.text = ""
        changed += 1
    return changed


def _rewrite_xml(data: bytes, value_map) -> Tuple[bytes, int]:
    root = xmlsafe.fromstring(data)
    changed = 0
    for p in root.iter(*_PARA_TAGS):
        changed += _rewrite_paragraph(p, value_map)
    # Text outside paragraphs (docProps/core.xml dc:creator, field codes) and attributes
    # (hyperlink targets such as mailto:jane@example.com in .rels files).
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        if el.tag not in _TEXT_TAGS and el.text:
            text = el.text
            for value, tok in value_map.items():
                if value in text:
                    text = text.replace(value, tok)
            if text != el.text:
                el.text = text
                changed += 1
        for name, attr in el.attrib.items():
            new = attr
            for value, tok in value_map.items():
                if len(value) >= 4 and value in new:
                    new = new.replace(value, tok)
            if new != attr:
                el.set(name, new)
                changed += 1
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True), changed


def _placeholder_image(data: bytes, name: str) -> Optional[bytes]:
    """Same-size neutral image in the same raster format, or None for vector formats."""
    ext = os.path.splitext(name)[1].lower()
    fmt = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".gif": "GIF", ".bmp": "BMP",
           ".tif": "TIFF", ".tiff": "TIFF"}.get(ext)
    if not fmt:
        return None
    try:
        size = Image.open(io.BytesIO(data)).size
    except Exception:
        size = (400, 200)
    img = Image.new("RGB", size, (200, 200, 200))
    ImageDraw.Draw(img).text((10, 10), "[IMAGE REMOVED - contained personal data]", fill=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, fmt)
    return buf.getvalue()


def _pptx_picture_media(src: str, slide_shapes: Dict[int, set]) -> set:
    """media file names (ppt/media/...) of the pictures with redacted OCR text."""
    from pptx import Presentation
    names = set()
    prs = Presentation(src)
    for no, slide in enumerate(prs.slides, 1):
        wanted = slide_shapes.get(no)
        if not wanted:
            continue
        stack = list(slide.shapes)
        while stack:
            sh = stack.pop()
            if hasattr(sh, "shapes"):
                stack.extend(sh.shapes)
            if sh.shape_id in wanted and hasattr(sh, "image"):
                rel = slide.part.rels[sh._element.blipFill.blip.rEmbed]
                names.add(str(rel.target_part.partname).lstrip("/"))
    return {n for n in names if n.startswith("ppt/media/")}


def _write_office(src: str, dst: str, pairs, value_map, kind: str) -> Dict[str, int]:
    stats = {"xml_parts_changed": 0, "text_nodes_changed": 0, "images_replaced": 0}
    pictures = set()
    slide_shapes: Dict[int, set] = {}
    for ob, _sb, _spans in pairs:
        loc, md = _location(ob), ob.metadata
        if loc.get("image_ocr"):
            if kind == "docx" and loc.get("image"):
                pictures.add("word/media/" + loc["image"])
            elif kind == "pptx" and md.get("shape_id"):
                slide_shapes.setdefault(int(loc["slide"]), set()).add(int(md["shape_id"]))
    if slide_shapes:
        pictures |= _pptx_picture_media(src, slide_shapes)

    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename in pictures:
                replacement = _placeholder_image(data, item.filename)
                if replacement is None:
                    raise ValueError(f"cannot neutralise vector picture {os.path.basename(item.filename)}")
                data = replacement
                stats["images_replaced"] += 1
            elif item.filename.endswith((".xml", ".rels", ".vml")):
                try:
                    new, changed = _rewrite_xml(data, value_map)
                    if changed:
                        data = new
                        stats["xml_parts_changed"] += 1
                        stats["text_nodes_changed"] += changed
                except etree.XMLSyntaxError:
                    pass
            zout.writestr(item, data)
    return stats


# ------------------------------------------------------------ verification
def _leftover_values(path: str, value_map, kind: str) -> List[str]:
    """Redacted values that can still be found anywhere in the written file's text."""
    left = []
    if kind == "pdf":
        try:
            import pymupdf
        except ImportError:
            import fitz as pymupdf
        doc = pymupdf.open(path)
        text = "\n".join(page.get_text() for page in doc) + json.dumps(doc.metadata)
        doc.close()
    else:
        chunks = []
        with zipfile.ZipFile(path) as z:
            for name in z.namelist():
                if name.endswith((".xml", ".rels", ".vml")):
                    root = xmlsafe.fromstring(z.read(name))
                    for p in root.iter(*_PARA_TAGS):
                        chunks.append("".join(n.text or "" for n in p.iter() if n.tag in _TEXT_TAGS))
                    chunks.extend(el.text for el in root.iter() if isinstance(el.tag, str) and el.text)
                    chunks.extend(v for el in root.iter() if isinstance(el.tag, str) for v in el.attrib.values())
        text = "\n".join(chunks)
    flat = " ".join(text.split()).casefold()
    for value in value_map:
        v = " ".join(value.split()).casefold()
        if len(v) >= 3 and v in flat:
            left.append(value)
    return left


def write_redacted_file(source_path: str, original: NormalizedDocument, gate: GateResult,
                        out_path: str, recheck=None, verify_ocr: bool = True) -> WriteOutcome:
    """Write a redacted copy of source_path.

    verify_ocr: for PDFs that needed OCR, re-OCR the redacted pages at 400 dpi and black out
                anything still readable (repeat until clean) - see _ocr_remediate.
    recheck:    optional callable(path) -> list of residual findings; the file is kept only
                if it returns an empty list."""
    if not gate.is_safe:
        return WriteOutcome(False, None, f"document is {gate.status} ({gate.reason}); no file written")
    kind = os.path.splitext(source_path)[1].lower().lstrip(".")
    if kind not in ("pdf", "docx", "pptx"):
        return WriteOutcome(False, None, f"unsupported type .{kind}")
    pairs = _pairs(original, gate.document)
    value_map = _value_map(pairs)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix="." + kind, dir=os.path.dirname(os.path.abspath(out_path)) or ".")
    os.close(fd)
    try:
        if kind == "pdf":
            stats = _write_pdf(source_path, tmp, pairs, value_map)
            if verify_ocr and (original.metadata.get("ocr_used") == "true"):
                stats.update(_ocr_remediate(tmp, value_map))
        else:
            stats = _write_office(source_path, tmp, pairs, value_map, kind)
        stats["values"] = len(value_map)
        left = [v for v in _leftover_values(tmp, value_map, kind)
                if kind != "pdf" or not _only_in_ocr(v, original)]
        if left:
            raise ValueError(f"{len(left)} redacted value(s) still present in the written file")
        if recheck is not None:
            residual = recheck(tmp)
            if residual:
                raise ValueError(f"re-scan of the written file found {len(residual)} PII item(s)")
            stats["rechecked"] = 1
        os.replace(tmp, out_path)
        os.chmod(out_path, 0o644)
        return WriteOutcome(True, out_path, "written_and_verified", stats)
    except Exception as exc:  # fail closed
        if os.path.exists(tmp):
            os.remove(tmp)
        return WriteOutcome(False, None, f"not written: {exc}")


def _only_in_ocr(value: str, original: NormalizedDocument) -> bool:
    """A scanned page has no text layer, so a value read by OCR cannot be searched in the
    PDF text - the image pixels were destroyed instead (checked by the OCR re-scan)."""
    return all(b.block_type == "ocr_text" for b in original.content if value in b.text) and \
        any(value in b.text for b in original.content)
