"""Small PDF helpers shared by the 1.1.1 modules. PyMuPDF only."""
from __future__ import annotations

import os

from .. import fileguard


def words(path) -> list[dict]:
    """Words from the PDF text layer: page, box, text. No .PRN, no
    company file."""
    import fitz
    fileguard.refuse_company_file(path)
    out = []
    with fitz.open(path) as doc:
        for i, page in enumerate(doc):
            for w in page.get_text("words") or []:
                text = str(w[4] or "").strip()
                if not text:
                    continue
                out.append({"page": i, "x0": w[0], "y0": w[1], "x1": w[2],
                            "y1": w[3], "t": text})
    return out


def page_text(path) -> str:
    import fitz
    fileguard.refuse_company_file(path)
    if not path or not os.path.isfile(path):
        return ""
    with fitz.open(path) as doc:
        return "\n".join(p.get_text() for p in doc)


def out_path(office, name: str) -> str:
    folder = office.output_folder()
    os.makedirs(folder, exist_ok=True)
    return fileguard.safe_path(folder, name)


def draw_header(office, page, title: str) -> int:
    """Company name and address from settings (never a baked-in name or
    logo file). Returns the y where the body starts."""
    c = office.company() or {}
    text(page, 54, 48, c.get("name") or "", 13, True)
    y = 64
    for ln in (c.get("address") or "").splitlines()[:3]:
        text(page, 54, y, ln, 8.5)
        y += 11
    logo = c.get("logo") or ""
    if logo and os.path.isfile(logo):
        import fitz
        try:
            page.insert_image(fitz.Rect(460, 32, 558, 78), filename=logo,
                              keep_proportion=True)
        except Exception:                                 # noqa: BLE001
            pass
    text(page, 54, max(y + 16, 108), title, 14, True)
    return max(y + 36, 128)


def text(page, x, y, value, size=9, bold=False) -> None:
    page.insert_text((x, y), str(value), fontsize=size,
                     fontname="hebo" if bold else "helv")


def strokes(page, box, data) -> None:
    """Draw signature strokes stored as integer thousandths (0-1000)
    inside `box` (a fitz.Rect)."""
    if not data:
        return
    w = box.x1 - box.x0
    h = box.y1 - box.y0
    for stroke in data:
        if len(stroke) < 2:
            continue
        pts = [(box.x0 + p[0] / 1000 * w, box.y0 + p[1] / 1000 * h)
               for p in stroke if len(p) >= 2]
        for a, b in zip(pts, pts[1:]):
            page.draw_line(a, b, width=1.1)
