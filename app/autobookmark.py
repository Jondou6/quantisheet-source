"""Auto Bookmark: link every detail callout to the detail it points at.

A plan sheet calls out details with a bubble: detail number over sheet
number ("3" over "A-501", or "3/A-501" on one line). For each callout:
- the sheet number must be a real sheet in the set (sheets.scan), and not
  the page's own number (its title block / its own detail titles);
- on the target sheet the detail's title bubble (same number over the
  same sheet number) gives the exact spot, so a click lands on the detail,
  not just the page (the PlanSwift 1.0.22 fix: "jump to the section
  actually called out");
- loose references ("SEE A-501") become page-level links with lower
  confidence.
apply() writes clickable PDF links over each callout and a "Details"
bookmark tree, replacing what an earlier run made. Nothing leaves the PC.
"""
import re

import fitz

from . import sheets
from .dmoney import c2 as _c2

PRECHECK = 0.7
DETAIL_NO = re.compile(r"^[A-Z]?\d{1,3}[A-Z]?$")
ONE_LINE = re.compile(r"^([A-Z]?\d{1,3}[A-Z]?)/([A-Z]{1,3}[-.]?\d{1,3}(?:\.\d{1,2})?[A-Z]?)$")
TREE = "Details"


def _n(s):
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def embedded_links(doc):
    """How many page-to-page links the PDF already has."""
    return sum(1 for p in doc for l in p.get_links() if l.get("kind") == fitz.LINK_GOTO)


def _above(words, w):
    """The detail number written just above sheet-number word `w`."""
    h = max(1.0, w[3] - w[1])
    cx = (w[0] + w[2]) / 2
    best = None
    for o in words:
        if o is w or not DETAIL_NO.match(o[4].upper()):
            continue
        ocx = (o[0] + o[2]) / 2
        gap = w[1] - o[3]
        if abs(ocx - cx) <= max(w[2] - w[0], 8) * 0.6 and -2 <= gap <= 1.6 * h:
            if best is None or gap < best[0]:
                best = (gap, o)
    return best[1] if best else None


def _detail_spot(words, detail, sheet_no):
    """Where detail `detail` is titled on its sheet: (point, exact?)."""
    sn = _n(sheet_no)
    loose = None
    for w in words:
        if _n(w[4]) == sn:
            o = _above(words, w)
            if o is not None and _n(o[4]) == _n(detail):
                r = fitz.Rect(o[:4]) | fitz.Rect(w[:4])
                return (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2, True
        m = ONE_LINE.match(w[4].upper())
        if m and _n(m.group(1)) == _n(detail) and _n(m.group(2)) == sn:
            return (w[0] + w[2]) / 2, (w[1] + w[3]) / 2, True
        if loose is None and _n(w[4]) == _n(detail):
            loose = ((w[0] + w[2]) / 2, (w[1] + w[3]) / 2, False)
    return loose


def find_links(doc, pages=None):
    """[{kind 'detail'|'sheet', src_page, rect, detail, sheet, dst_page,
    dst_point, dst_found, confidence}] - nothing changed yet."""
    rows = sheets.scan(doc, numbers=doc.page_count > 2)
    by_no = {_n(r["number"]): r["page"] for r in rows if r.get("number")}
    own = {r["page"]: _n(r["number"]) for r in rows}
    words = {i: [tuple(w[:5]) for w in doc[i].get_text("words")] for i in range(doc.page_count)}
    out = []
    for p in (pages if pages is not None else range(doc.page_count)):
        ws = words[p]
        used = set()
        for w in ws:
            t = w[4].upper()
            m = ONE_LINE.match(t)
            if m:
                det, sn, rect = m.group(1), m.group(2), fitz.Rect(w[:4])
            elif _n(t) in by_no:
                sn = t
                o = _above(ws, w)
                det = o[4] if o is not None else None
                rect = fitz.Rect(w[:4]) | fitz.Rect(o[:4]) if o is not None else fitz.Rect(w[:4])
            else:
                continue
            dst = by_no.get(_n(sn))
            if dst is None or dst == p or own.get(p) == _n(sn):
                continue
            key = (round(rect.x0), round(rect.y0))
            if key in used:
                continue
            used.add(key)
            if det:
                spot = _detail_spot(words[dst], det, sn)
                conf = 0.9 if spot and spot[2] else 0.75 if spot else 0.55
                out.append({"kind": "detail", "src_page": p, "rect": list(rect),
                            "detail": det, "sheet": sn, "dst_page": dst,
                            "dst_point": list(spot[:2]) if spot else None,
                            "dst_found": bool(spot and spot[2]), "confidence": conf})
            else:
                out.append({"kind": "sheet", "src_page": p, "rect": list(rect),
                            "detail": None, "sheet": sn, "dst_page": dst,
                            "dst_point": None, "dst_found": False, "confidence": 0.6})
    return out


def _same(a, b, tol=1.5):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def apply(doc, links):
    """Clickable links + a 'Details' bookmark tree. Re-running replaces
    links at the same spots and the old tree. Returns links written."""
    n = 0
    by_page = {}
    for l in links:
        by_page.setdefault(l["src_page"], []).append(l)
    for p, ls in by_page.items():
        page = doc[p]
        rects = [fitz.Rect(l["rect"]) + (-4, -4, 4, 4) for l in ls]
        lk = page.first_link
        stale = []
        while lk:
            if lk.dest.kind == fitz.LINK_GOTO and any(_same(lk.rect, r) for r in rects):
                stale.append(lk)
            lk = lk.next
        for old in stale:
            page.delete_link({"xref": old.xref, "from": old.rect, "kind": fitz.LINK_GOTO})
    for l in links:
        page = doc[l["src_page"]]
        r = fitz.Rect(l["rect"]) + (-4, -4, 4, 4)
        link = {"kind": fitz.LINK_GOTO, "from": r, "page": l["dst_page"]}
        if l.get("dst_point"):
            link["to"] = fitz.Point(max(0, l["dst_point"][0] - 150),
                                    max(0, l["dst_point"][1] - 150))
            link["zoom"] = 0
        page.insert_link(link)
        n += 1
    toc, skip, kept = doc.get_toc(simple=False), False, []
    for e in toc:
        if e[0] == 1:
            skip = e[1] == TREE
        if not skip:
            kept.append(e)
    det = sorted({(l["sheet"], l["detail"], l["dst_page"], tuple(l["dst_point"] or (0, 0)))
                  for l in links if l["kind"] == "detail"})
    if det:
        entries = [[1, TREE, det[0][2] + 1]]
        for sn, d, pg, pt in det:
            entries.append([2, f"{d}/{sn}", pg + 1,
                            {"kind": fitz.LINK_GOTO, "page": pg,
                             "to": fitz.Point(*pt), "zoom": 0}])
        doc.set_toc(kept + entries)
    return n


# ---------------------------------------------------------------- review UI
try:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel, QTableWidget,
                                   QTableWidgetItem, QVBoxLayout)
except ImportError:
    QDialog = None

if QDialog is not None:
    class LinkReviewDialog(QDialog):
        COLS = ["Use", "From page", "Callout", "To sheet", "Lands on", "Conf."]

        def __init__(self, links, parent=None, embedded=0):
            super().__init__(parent)
            self.links = links
            self.setWindowTitle("Auto Bookmark - review links")
            lay = QVBoxLayout(self)
            msg = f"{len(links)} callouts found."
            if embedded:
                msg += f" The PDF already has {embedded} page links."
            lay.addWidget(QLabel(msg))
            t = self.table = QTableWidget(len(links), len(self.COLS))
            t.setHorizontalHeaderLabels(self.COLS)
            for i, l in enumerate(links):
                use = QTableWidgetItem()
                use.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                use.setCheckState(Qt.Checked if l["confidence"] >= PRECHECK else Qt.Unchecked)
                t.setItem(i, 0, use)
                vals = [str(l["src_page"] + 1),
                        f"{l['detail']}/{l['sheet']}" if l["detail"] else l["sheet"],
                        f"page {l['dst_page'] + 1}",
                        "the detail" if l["dst_found"] else "the page",
                        f"{_c2(l['confidence']):.2f}"]
                for c, v in enumerate(vals, 1):
                    t.setItem(i, c, QTableWidgetItem(v))
                if l["confidence"] < PRECHECK:
                    for c in range(len(self.COLS)):
                        t.item(i, c).setBackground(QColor("#fff3cd"))
            lay.addWidget(t)
            bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            bb.accepted.connect(self.accept)
            bb.rejected.connect(self.reject)
            lay.addWidget(bb)
            self.resize(760, 480)

        def accepted(self):
            return [self.links[i] for i in range(self.table.rowCount())
                    if self.table.item(i, 0).checkState() == Qt.Checked]

    def run_dialog(parent, doc):
        links = find_links(doc)
        dlg = LinkReviewDialog(links, parent, embedded_links(doc))
        if dlg.exec() != QDialog.Accepted:
            return 0
        return apply(doc, dlg.accepted())
