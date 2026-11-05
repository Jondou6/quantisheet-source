"""Booklet and N-up printing layouts (Pages > Booklet / N-up…).

The layout math is plain Python (no Qt, no PyMuPDF) so it can be tested on
its own; write() places the pages of a document on new sheets with
PyMuPDF's Page.show_pdf_page, so drawings stay vector. The open document
is never changed: the result is always a new file.

Booklet (saddle-stitched): the page count is padded with blank pages to
a multiple of 4, and each sheet carries four pages, two per side. For n
padded pages, sheet k (from 0) has
    front: n - 2k | 1 + 2k        back: 2 + 2k | n - 1 - 2k
so a 6-page set becomes 8 pages: 8|1, 2|7 on the first sheet and 6|3,
4|5 on the second. Folded and stapled, it reads 1 to 8.
"""
import math

MODES = ("booklet", "2up", "4up")
MODE_NAMES = {"booklet": "Booklet (fold and staple)",
              "2up": "2 pages per sheet",
              "4up": "4 pages per sheet"}

PAPER = {                      # points, portrait
    "auto": None,
    "letter": (612, 792),
    "legal": (612, 1008),
    "tabloid": (792, 1224),
    "a4": (595, 842),
    "a3": (842, 1191),
}
PAPER_NAMES = {"auto": "Automatic (from the pages)", "letter": "Letter",
               "legal": "Legal", "tabloid": "Tabloid (11×17)", "a4": "A4",
               "a3": "A3"}


def padded(n):
    """Page count of a booklet of `n` pages: up to a multiple of 4."""
    return max(4, int(math.ceil(n / 4.0)) * 4)


def booklet_order(n):
    """[(left, right)] for each printed side, front then back of each
    sheet, as 1-based page numbers of the padded booklet (6 pages:
    [(8, 1), (2, 7), (6, 3), (4, 5)])."""
    m = padded(n)
    out = []
    for k in range(m // 4):
        out.append((m - 2 * k, 1 + 2 * k))
        out.append((2 + 2 * k, m - 1 - 2 * k))
    return out


def booklet_sides(n):
    """booklet_order(n) with the padding pages (past `n`) as None."""
    return [tuple(p if p <= n else None for p in side)
            for side in booklet_order(n)]


def nup_sides(n, per):
    """[[page numbers]] for each sheet of an N-up set (1-based)."""
    return [list(range(i + 1, min(n, i + per) + 1))
            for i in range(0, n, per)]


def grid(per):
    """(columns, rows) for `per` pages per side."""
    return {1: (1, 1), 2: (2, 1), 4: (2, 2)}[per]


def cells(sheet, cols, rows, margin=0.0, gutter=0.0):
    """Cell rectangles (x0, y0, x1, y1) on a sheet (w, h), in reading
    order (left to right, top to bottom)."""
    w, h = sheet
    cw = (w - 2 * margin - (cols - 1) * gutter) / cols
    ch = (h - 2 * margin - (rows - 1) * gutter) / rows
    if cw <= 0 or ch <= 0:
        raise ValueError("the margin and gutter leave no room for pages")
    out = []
    for r in range(rows):
        for c in range(cols):
            x0 = margin + c * (cw + gutter)
            y0 = margin + r * (ch + gutter)
            out.append((x0, y0, x0 + cw, y0 + ch))
    return out


def fit(size, cell, align="center"):
    """The largest rectangle with the aspect ratio of `size` (w, h) that
    fits in `cell`. align: "center", or "right" / "left" to push it
    against that side of the cell (booklet pages meet at the fold)."""
    w, h = size
    x0, y0, x1, y1 = cell
    cw, ch = x1 - x0, y1 - y0
    if w <= 0 or h <= 0:
        return cell
    s = min(cw / w, ch / h)
    fw, fh = w * s, h * s
    if align == "right":
        left = x1 - fw
    elif align == "left":
        left = x0
    else:
        left = x0 + (cw - fw) / 2
    top = y0 + (ch - fh) / 2
    return (left, top, left + fw, top + fh)


def _landscape(size):
    w, h = size
    return (max(w, h), min(w, h))


def _portrait(size):
    w, h = size
    return (min(w, h), max(w, h))


def sheet_size(mode, page, paper="auto"):
    """The sheet (w, h) for `mode`, from the largest page (w, h)."""
    base = PAPER.get(paper)
    if mode == "booklet":
        if base is None:                       # two pages side by side
            return (2 * page[0], page[1])
        return _landscape(base)
    if mode == "2up":
        return _landscape(base or page)
    if base is None:                           # 4-up: same as a page
        return page
    return _portrait(base) if page[1] >= page[0] else _landscape(base)


def plan(sizes, mode="booklet", paper="auto", margin=None, gutter=None,
         creep=0.0, flip_back=False):
    """Where every page goes. `sizes`: [(w, h)] of the source pages as
    shown. Returns [{"size": (w, h), "items": [(page index, (x0, y0, x1,
    y1), rotate)]}], one per printed side, in printing order.

    margin / gutter: points (defaults: none for a booklet, 18 / 12 for
    N-up). creep: points each sheet, from the outside in, pulls the outer
    edge of its pages towards the fold (booklet only; 0 by default, the
    pages are made that much narrower, keeping their shape). flip_back:
    turn the back
    of every sheet upside down, for printers that flip on the short
    edge."""
    if mode not in MODES:
        raise ValueError(f"unknown layout {mode!r}")
    n = len(sizes)
    if n == 0:
        return []
    big = (max(w for w, _h in sizes), max(h for _w, h in sizes))
    if mode == "booklet":
        margin = 0.0 if margin is None else float(margin)
        gutter = 0.0 if gutter is None else float(gutter)
    else:
        margin = 18.0 if margin is None else float(margin)
        gutter = 12.0 if gutter is None else float(gutter)
    sheet = sheet_size(mode, big, paper)
    out = []
    if mode == "booklet":
        boxes = cells(sheet, 2, 1, margin, gutter)
        for side, pair in enumerate(booklet_sides(n)):
            back = side % 2 == 1
            k = side // 2                     # sheet number, outside in
            # creep: inner sheets stick out further once folded, so their
            # pages are drawn that much narrower from the outer edge (the
            # fold side stays put, the aspect ratio is kept)
            shift = max(0.0, float(creep or 0) * k)
            items = []
            for slot, pno in enumerate(pair):
                if pno is None:
                    continue
                x0, y0, x1, y1 = boxes[slot]
                if shift:
                    if slot == 0:
                        x0 = min(x1 - 1, x0 + shift)
                    else:
                        x1 = max(x0 + 1, x1 - shift)
                align = "right" if slot == 0 else "left"
                r = fit(sizes[pno - 1], (x0, y0, x1, y1), align)
                items.append((pno - 1, r, 0))
            if back and flip_back:
                items = [(p, _turn(r, sheet), 180) for p, r, _rot in items]
            out.append({"size": sheet, "items": items})
        return out
    per = 2 if mode == "2up" else 4
    cols, rows = grid(per)
    boxes = cells(sheet, cols, rows, margin, gutter)
    for pages in nup_sides(n, per):
        items = [(p - 1, fit(sizes[p - 1], boxes[i]), 0)
                 for i, p in enumerate(pages)]
        out.append({"size": sheet, "items": items})
    return out


def _turn(r, sheet):
    """`r` on a sheet turned 180 degrees."""
    w, h = sheet
    return (w - r[2], h - r[3], w - r[0], h - r[1])


def write(doc, path, mode="booklet", paper="auto", margin=None, gutter=None,
          creep=0.0, flip_back=False, markups=True):
    """Write `doc`'s pages, laid out by plan(), to a new PDF at `path`.
    markups: show the markups too (burned into a copy first; the open
    document is not changed). Returns the number of sheet sides."""
    import fitz
    from . import safeio
    src = doc
    own = False
    if markups and any(p.first_annot is not None for p in doc):
        try:
            src = fitz.open("pdf", doc.tobytes())
            own = True
            src.bake(annots=True, widgets=True)
        except Exception:                                 # noqa: BLE001
            if own:
                src.close()
            src, own = doc, False
    try:
        sizes = [(p.rect.width, p.rect.height) for p in src]
        sides = plan(sizes, mode, paper, margin, gutter, creep, flip_back)
        out = fitz.open()
        try:
            for side in sides:
                w, h = side["size"]
                pg = out.new_page(width=w, height=h)
                for pno, r, rot in side["items"]:
                    pg.show_pdf_page(fitz.Rect(r), src, pno,
                                     keep_proportion=True, rotate=rot)
            safeio.atomic_save(out, path, garbage=safeio.gc_level(out),
                               deflate=True)
        finally:
            out.close()
    finally:
        if own:
            src.close()
    return len(sides)
