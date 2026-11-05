"""Auto Scale: the scale of every sheet in a set, ready to confirm.

For each page:
1. Text layer: the scale written in the title block / under the plan
   title (sheets.scan + takeoff.main_scale; standard scales only).
2. Scanned sheet (no text layer): the same, read from Tesseract OCR
   words rebuilt into lines (needs tesseract; skipped quietly if absent).
3. Cross-check against the drawing itself: every dimension string
   (24'-0") next to a straight line gives points-per-foot = line length /
   feet. If the median of those disagrees with the written scale by more
   than 3%, the sheet is flagged "check" (wrong scale, or the sheet was
   printed/scaled to fit).
4. No scale written: the dimension strings alone give a scale, snapped to
   the nearest standard one when within 2% - always "check", never
   trusted on its own.

Nothing is applied here: detect() returns rows for the review dialog;
apply() sets only the rows the estimator confirmed (default: rows that
are "ok" and have no scale yet).
"""
import logging
import re
import statistics

from app import annotate, takeoff

log = logging.getLogger(__name__)

AGREE_TOL = 0.03          # written scale vs dimensions
SNAP_TOL = 0.02           # dimensions-only scale snapped to a standard one
MIN_DIM_FT = 1.0
NTS = re.compile(r"\b(N\.?T\.?S\.?|NOT\s+TO\s+SCALE)\b", re.I)


def _ocr_text(page):
    """OCR'd page text as lines (top to bottom, left to right), or ''."""
    from app import ocr
    try:
        words = ocr.ocr_words(page)
    except Exception as e:                    # no tesseract, timeout...
        log.info("autoscale OCR skipped: %s", e)
        return ""
    words.sort(key=lambda w: ((w["rect"].y0 + w["rect"].y1) / 2, w["rect"].x0))
    lines, cur, cy, ch = [], [], None, 0
    for w in words:
        y = (w["rect"].y0 + w["rect"].y1) / 2
        h = max(1.0, w["rect"].height)
        if cy is not None and abs(y - cy) > 0.6 * max(h, ch):
            lines.append(cur)
            cur = []
        if not cur:
            cy, ch = y, h
        cur.append(w)
    if cur:
        lines.append(cur)
    return "\n".join(" ".join(w["text"] for w in sorted(ln, key=lambda w: w["rect"].x0))
                     for ln in lines)


def _segments(page):
    segs = []
    try:
        drawings = page.get_drawings()
    except Exception:
        return segs
    for d in drawings:
        for it in d.get("items", ()):
            if it[0] == "l":
                a, b = it[1], it[2]
                if abs(a - b) > 20:
                    segs.append((a, b))
    return segs


def dimension_scale(page):
    """{"ppu": median points per foot or None, "n": dims used, "values"}"""
    segs = _segments(page)
    vals = []
    if segs:
        for w in page.get_text("words"):
            got = takeoff.parse_length(w[4])
            if not got or got[1] != "ft" or got[0] < MIN_DIM_FT:
                continue
            if "'" not in w[4].translate(takeoff._QUOTES):
                continue
            ft = got[0]
            cx, cy = (w[0] + w[2]) / 2, (w[1] + w[3]) / 2
            best, bd = None, 1e9
            for a, b in segs:
                horiz = abs(a.y - b.y) < 1
                vert = abs(a.x - b.x) < 1
                if not (horiz or vert):
                    continue
                mx, my = (a.x + b.x) / 2, (a.y + b.y) / 2
                if horiz and not (min(a.x, b.x) - 5 <= cx <= max(a.x, b.x) + 5):
                    continue
                if vert and not (min(a.y, b.y) - 5 <= cy <= max(a.y, b.y) + 5):
                    continue
                dist = abs(my - cy) if horiz else abs(mx - cx)
                if dist < 25 and dist < bd:
                    best, bd = abs(a - b), dist
            if best:
                vals.append(best / ft)
    if len(vals) < 2:
        return {"ppu": None, "n": len(vals), "values": vals}
    # densest cluster (dimension strings pick up stray lines; the real
    # scale is the value most of them agree on)
    best = []
    for v in vals:
        close = [x for x in vals if abs(x / v - 1) <= AGREE_TOL]
        if len(close) > len(best):
            best = close
    need = 2 if len(vals) <= 3 else max(3, int(0.2 * len(vals)))
    if len(best) < need:
        return {"ppu": None, "n": len(best), "values": vals}
    return {"ppu": statistics.median(best), "n": len(best), "values": vals}


def _snap(ppu, unit="ft"):
    best = None
    for fam in takeoff.PRESETS.values():
        for label, (p, u) in fam:
            if u == unit and abs(p / ppu - 1) <= SNAP_TOL:
                if best is None or abs(p - ppu) < abs(best[1] - ppu):
                    best = (label, p)
    return best


def detect(doc, pages=None, use_ocr=True, progress=None):
    """One row per page: {page, label, ppu, unit, source ('text', 'ocr',
    'dimensions' or ''), existing (ppu already set or None), dims {ppu, n,
    agree}, status ('ok', 'check', 'none'), note}."""
    from app import sheets
    have = annotate.read_scales(doc)
    pages = list(pages if pages is not None else range(doc.page_count))
    rows = []
    for k, pno in enumerate(pages):
        if progress and progress(k, len(pages)) is False:
            break
        page = doc[pno]
        info = sheets.scan(doc, [pno], numbers=False)[0]
        sc, src, note = info["scale"], "text" if info["scale"] else "", ""
        has_text = bool(page.get_text().strip())
        if sc is None and not has_text and use_ocr:
            main = takeoff.main_scale(_ocr_text(page))
            if main and takeoff.is_standard(main[1], main[2]):
                sc, src = main, "ocr"
        if sc is None and info.get("odd"):
            note = f"odd scale written: {info['odd'][0]} - pick it if right"
        nts = sc is None and bool(NTS.search(page.get_text()))
        dims = dimension_scale(page) if has_text and not nts else {"ppu": None, "n": 0}
        if nts:
            note = "sheet says NTS (not to scale) - don't measure from it"
        agree = None
        if sc and dims["ppu"] and sc[2] == "ft":
            agree = abs(dims["ppu"] / sc[1] - 1) <= AGREE_TOL
        row = {"page": pno, "sheet": info.get("label", ""), "label": None,
               "ppu": None, "unit": "ft", "source": src,
               "existing": (have.get(pno) or {}).get("ppu"),
               "dims": {"ppu": dims["ppu"], "n": dims["n"], "agree": agree},
               "status": "none", "note": note}
        if sc:
            row.update(label=sc[0], ppu=sc[1], unit=sc[2])
            if agree is False:
                row["status"] = "check"
                row["note"] = (f"dimension strings say {dims['ppu']:.2f} pt/ft, "
                               f"not {sc[1]:.2f} - sheet may be printed to fit")
            elif src == "ocr" and not agree:
                row["status"] = "check"
                row["note"] = "read by OCR - spot-check it (OCR can misread 1/4 vs 1/2)"
            else:
                row["status"] = "ok"
        elif dims["ppu"]:
            snap = _snap(dims["ppu"])
            label, ppu = snap if snap else (takeoff.scale_text(dims["ppu"], "ft"),
                                            dims["ppu"])
            row.update(label=label, ppu=ppu, source="dimensions", status="check",
                       note=f"no scale written; {dims['n']} dimension strings agree")
        elif not row["note"]:
            row["note"] = "no scale found - set it by hand (Calibrate)"
        rows.append(row)
    return rows


def apply(doc, rows, confirmed=None):
    """Set the scale on confirmed pages (set of page indexes). Default:
    rows with status 'ok' and no existing scale. Returns pages set."""
    n = 0
    for r in rows:
        if not r.get("ppu"):
            continue
        ok = (r["page"] in confirmed) if confirmed is not None else \
            (r["status"] == "ok" and not r.get("existing"))
        if ok:
            if annotate.apply_op(doc, annotate.new_op(
                    "set_scale", r["page"], ppu=r["ppu"], unit=r["unit"],
                    name=r.get("label") or "")):
                n += 1
    return n


# ---------------------------------------------------------------- review UI
try:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QTableWidget,
                                   QTableWidgetItem, QVBoxLayout, QLabel)
except ImportError:
    QDialog = None

if QDialog is not None:
    class ScaleReviewDialog(QDialog):
        """Every sheet's found scale with a checkbox. 'ok' rows start
        checked (unless the page already has a scale), 'check' rows start
        unchecked and amber, 'none' rows can't be checked."""
        COLS = ["Use", "Page", "Sheet", "Scale", "From", "Dims check", "Note"]

        def __init__(self, rows, parent=None):
            super().__init__(parent)
            self.setWindowTitle("Auto Scale - confirm before use")
            self.rows = rows
            lay = QVBoxLayout(self)
            lay.addWidget(QLabel("Spot-check a page with a known dimension "
                                 "before taking off."))
            t = self.table = QTableWidget(len(rows), len(self.COLS))
            t.setHorizontalHeaderLabels(self.COLS)
            for i, r in enumerate(rows):
                use = QTableWidgetItem()
                if r.get("ppu"):
                    use.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                    use.setCheckState(Qt.Checked if r["status"] == "ok" and
                                      not r.get("existing") else Qt.Unchecked)
                else:
                    use.setFlags(Qt.ItemIsEnabled)
                d = r["dims"]
                dims = ("agrees" if d.get("agree") else "DISAGREES"
                        if d.get("agree") is False else f"{d.get('n', 0)} dims")
                vals = [str(r["page"] + 1), r.get("sheet", ""), r.get("label") or "-",
                        r.get("source") or "-", dims,
                        (f"(page already {r['existing']:.2f} pt/ft) " if r.get("existing") else "")
                        + r.get("note", "")]
                t.setItem(i, 0, use)
                for c, v in enumerate(vals, 1):
                    t.setItem(i, c, QTableWidgetItem(v))
                if r["status"] != "ok":
                    for c in range(len(self.COLS)):
                        t.item(i, c).setBackground(QColor("#fff3cd") if r["status"] == "check"
                                                   else QColor("#f8d7da"))
            lay.addWidget(t)
            bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            bb.accepted.connect(self.accept)
            bb.rejected.connect(self.reject)
            lay.addWidget(bb)
            self.resize(900, 500)

        def confirmed(self):
            return {self.rows[i]["page"] for i in range(self.table.rowCount())
                    if self.table.item(i, 0).checkState() == Qt.Checked}

    def run_dialog(parent, doc, pages=None):
        """Detect, show the review table, apply what was confirmed."""
        rows = detect(doc, pages)
        dlg = ScaleReviewDialog(rows, parent)
        if dlg.exec() != QDialog.Accepted:
            return 0
        return apply(doc, rows, dlg.confirmed())
