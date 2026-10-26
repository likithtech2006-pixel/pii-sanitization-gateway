"""PDF -> blocks. Text pages use PyMuPDF directly. Pages with (almost) no
text are treated as scanned and OCR'd. Large embedded images on text pages
are OCR'd too. OCR runs in parallel (Tesseract is a separate process), and
blocks are still added in page order."""
import io
from concurrent.futures import ThreadPoolExecutor

try:
    import pymupdf
except ImportError:                                        # older PyMuPDF
    import fitz as pymupdf
from PIL import Image

from extraction import ocr
from extraction.figures import figure_regions, inside
from extraction.internal import Block
from extraction.metadata import add_metadata_blocks, pdf_properties

MIN_TEXT_CHARS = 20       # fewer characters than this => treat page as scanned
OCR_DPI = 300
MIN_IMG_SIDE = 150        # ignore tiny images (logos, bullets)
FIGURE_DPI = 600          # second OCR pass over figures / small text on scanned pages


def extract_pdf(path, doc_id, meta):
    doc = pymupdf.open(path)
    meta.parser = "pymupdf"
    if doc.needs_pass:
        raise ValueError("PDF is password protected")
    blocks, state = [], {"order": 0}

    def add(text, loc, md):
        if not text or not text.strip():
            return
        blocks.append(Block(f"{doc_id}-b{state['order']}", text.strip(), loc,
                            state["order"], md))
        state["order"] += 1

    # Pass 1: read native text and render scanned pages (PyMuPDF is not thread-safe).
    plan = []                                              # per page: ("text", blocks) | ("scan", image)
    for pno, page in enumerate(doc, 1):
        text_blocks = [b for b in page.get_text("blocks", sort=True)
                       if b[6] == 0 and b[4].strip()]
        n_chars = sum(len(b[4].strip()) for b in text_blocks)
        if n_chars >= MIN_TEXT_CHARS:
            plan.append((pno, "text", text_blocks, _embedded_images(doc, page, pno, meta)))
        elif ocr.is_available():
            pix = page.get_pixmap(dpi=OCR_DPI)
            img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
            plan.append((pno, "scan", img, []))
        else:
            meta.warnings.append(f"page {pno}: looks scanned but Tesseract is not installed")
            plan.append((pno, "skip", None, []))

    # Pass 2: OCR everything that needs it, in parallel.
    jobs = {}
    with ThreadPoolExecutor(max_workers=ocr.workers()) as pool:
        for pno, kind, payload, images in plan:
            if kind == "scan":
                jobs[(pno, None)] = pool.submit(ocr.ocr_image, payload, OCR_DPI)
            for xref, img, _rect in images:
                jobs[(pno, xref)] = pool.submit(ocr.ocr_image, img, 300)
        results = {}
        for key, future in jobs.items():
            try:
                results[key] = future.result()
            except Exception as e:                         # one bad page never kills the file
                results[key] = None
                meta.warnings.append(f"page {key[0]}: OCR failed ({type(e).__name__})")

    # Pass 2b: figures and small text on scanned pages get a second, high-resolution OCR pass.
    figure_jobs = []                                           # (pno, region, image)
    for pno, kind, payload, images in plan:
        paras = results.get((pno, None)) if kind == "scan" else None
        if not paras:
            continue
        page = doc[pno - 1]
        for region in figure_regions(paras, tuple(page.rect)):
            pix = page.get_pixmap(dpi=FIGURE_DPI, clip=pymupdf.Rect(region))
            figure_jobs.append((pno, region, Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")))
    figures = {}
    if figure_jobs:
        with ThreadPoolExecutor(max_workers=ocr.workers()) as pool:
            futures = [pool.submit(ocr.ocr_image, img, FIGURE_DPI) for _, _, img in figure_jobs]
            for (pno, region, _), future in zip(figure_jobs, futures):
                try:
                    figures.setdefault(pno, []).append((region, _shift(future.result(), region)))
                except Exception as e:
                    meta.warnings.append(f"page {pno}: figure OCR failed ({type(e).__name__})")

    # Pass 3: emit blocks in page order.
    for pno, kind, payload, images in plan:
        if kind == "text":
            for b in payload:
                add(b[4], {"type": "page", "page": pno},
                    {"bbox": [round(v, 1) for v in b[:4]], "ocr": False})
            for xref, _img, rect in images:
                for para in results.get((pno, xref)) or []:
                    add(para["text"], {"type": "page", "page": pno, "image_ocr": True},
                        {"bbox": list(rect) if rect else None, "ocr": True,
                         "ocr_conf": para["conf"], "image_xref": xref,
                         "note": "bbox is the whole image, not the word"})
                    meta.ocr_used = True
        elif kind == "scan":
            paras = results.get((pno, None))
            if paras is None:
                continue                                   # failure already recorded
            if not paras:
                meta.warnings.append(f"page {pno}: OCR found no text")
            page_figures = figures.get(pno, [])
            placed = set()
            for para in paras:
                region_no = next((i for i, (r, _) in enumerate(page_figures) if inside(para["bbox"], r)), None)
                if region_no is None:
                    add(para["text"], {"type": "page", "page": pno},
                        {"bbox": list(para["bbox"]), "ocr": True, "ocr_conf": para["conf"],
                         "word_boxes": para["words"]})
                elif region_no not in placed:              # figure text replaces the first-pass text
                    placed.add(region_no)
                    _add_figure(add, pno, region_no, page_figures[region_no])
                meta.ocr_used = True
            for i, fig in enumerate(page_figures):           # figure where the first pass read nothing
                if i not in placed:
                    _add_figure(add, pno, i, fig)

    add_metadata_blocks(add, pdf_properties(doc.metadata))
    doc.close()
    return blocks


def _shift(paragraphs, region):
    """OCR coordinates of a clipped render are relative to the clip; move them onto the page."""
    dx, dy = region[0], region[1]
    for p in paragraphs:
        x0, y0, x1, y1 = p["bbox"]
        p["bbox"] = (round(x0 + dx, 1), round(y0 + dy, 1), round(x1 + dx, 1), round(y1 + dy, 1))
        p["words"] = [[round(w[0] + dx, 1), round(w[1] + dy, 1), round(w[2] + dx, 1), round(w[3] + dy, 1), w[4]]
                      for w in p["words"]]
    return paragraphs


def _add_figure(add, pno, index, figure):
    region, paragraphs = figure
    for para in paragraphs:
        add(para["text"], {"type": "page", "page": pno, "figure": index + 1},
            {"bbox": list(para["bbox"]), "ocr": True, "ocr_conf": para["conf"],
             "word_boxes": para["words"], "figure_bbox": [round(v, 1) for v in region],
             "kind": "figure_ocr"})


def _embedded_images(doc, page, pno, meta):
    """Large images on a text page (screenshots, pasted tables...) -> [(xref, PIL image, rect)]."""
    if not ocr.is_available():
        return []
    out = []
    for img_info in page.get_images(full=True):
        try:
            xref = img_info[0]
            pix = pymupdf.Pixmap(doc, xref)
            if pix.width < MIN_IMG_SIDE or pix.height < MIN_IMG_SIDE:
                continue
            if pix.colorspace is None or pix.n - pix.alpha >= 4:   # CMYK etc.
                pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
            img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
            rects = page.get_image_rects(xref)
            out.append((xref, img, rects[0] if rects else None))
        except Exception as e:
            meta.warnings.append(f"page {pno}: embedded image OCR failed (image unreadable: {type(e).__name__})")
    return out
