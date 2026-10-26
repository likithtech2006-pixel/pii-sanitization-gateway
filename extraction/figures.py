"""Find figure regions on a scanned page so they can be OCR'd again at high resolution.

Screenshots and diagrams pasted into a document use much smaller (and often grey)
text than the body. At the page OCR resolution Tesseract reads such regions badly
or not at all - e.g. a user-list screenshot full of names and e-mail addresses.
The page OCR tells us where that happens: paragraphs with low confidence or tiny
glyphs. figure_regions() turns those into rectangles; the extractor re-renders
them at FIGURE_DPI and OCRs them again.
"""
from typing import List, Tuple

GOOD_CONF = 75.0        # paragraph confidence considered reliable
SMALL_TEXT_PT = 3.6     # median word height below this = tiny text (figure)
MIN_AREA_PT2 = 1500.0   # ignore specks, rules and bullets

Box = Tuple[float, float, float, float]   # x0, y0, x1, y1 in PDF points


def _median_height(words) -> float:
    hs = sorted(w[3] - w[1] for w in words) or [0]
    return hs[len(hs) // 2]


def _weak(para) -> bool:
    return para["conf"] < GOOD_CONF or _median_height(para["words"]) < SMALL_TEXT_PT


def _merge(boxes: List[Box], gap: float) -> List[Box]:
    boxes = [list(b) for b in boxes]
    changed = True
    while changed:
        changed = False
        out = []
        for b in boxes:
            for o in out:
                if b[0] <= o[2] + gap and o[0] <= b[2] + gap and b[1] <= o[3] + gap and o[1] <= b[3] + gap:
                    o[0], o[1], o[2], o[3] = min(o[0], b[0]), min(o[1], b[1]), max(o[2], b[2]), max(o[3], b[3])
                    changed = True
                    break
            else:
                out.append(b)
        boxes = out
    return [tuple(b) for b in boxes]


def figure_regions(paragraphs, page_rect: Box, margin: float = 20.0, reach: float = 150.0) -> List[Box]:
    """Rectangles (PDF points) worth a high-resolution second OCR pass.

    Seeds are paragraphs read with low confidence or with tiny glyphs. Seeds close to each
    other are merged, then each region grows vertically up to the nearest confidently read
    text above and below (the figure's caption and the body text around it), so rows of the
    figure that the first pass did not read at all are covered too."""
    weak = [p for p in paragraphs if _weak(p)]
    strong = [p["bbox"] for p in paragraphs if not _weak(p)]
    if not weak:
        return []
    regions = _merge([tuple(p["bbox"]) for p in weak], 25.0)
    out = []
    for x0, y0, x1, y1 in regions:
        x0, x1 = max(page_rect[0], x0 - margin), min(page_rect[2], x1 + margin)
        above = [b[3] for b in strong if b[3] <= y0 + 1 and b[0] < x1 and x0 < b[2]]
        below = [b[1] for b in strong if b[1] >= y1 - 1 and b[0] < x1 and x0 < b[2]]
        top = max([y0 - reach] + above)
        bottom = min([y1 + reach] + below)
        out.append((x0, max(page_rect[1], top), x1, min(page_rect[3], bottom)))
    return [b for b in _merge(out, 5.0) if (b[2] - b[0]) * (b[3] - b[1]) >= MIN_AREA_PT2]


def inside(bbox, region: Box, tolerance: float = 0.6) -> bool:
    """True when most of bbox lies inside region."""
    x0, y0, x1, y1 = bbox
    ix = max(0.0, min(x1, region[2]) - max(x0, region[0]))
    iy = max(0.0, min(y1, region[3]) - max(y0, region[1]))
    area = max(1e-6, (x1 - x0) * (y1 - y0))
    return ix * iy / area >= tolerance
