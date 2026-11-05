"""Slip-sheet report, unmatched sheets first (v16).

sets.plan / sets.batch_slip already find the matches, the new sheets, the
revised pages with no readable sheet number and duplicate numbers - but
the Batch Slip dialog lists the problems last. This report puts what needs
a person at the top: NOT MATCHED pages, then duplicates, then new sheets,
then sheets that changed (takeoffs flagged), then slip sheeted with no
change, then sheets with no revision. Export to CSV or PDF.
Hook: BatchSlipDialog can fill its table from `rows(plan)` and show
`SlipReportDialog(self, rows(plan, report))` after the run."""
import os

import fitz
from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog,
                               QLabel, QTableWidget, QTableWidgetItem,
                               QVBoxLayout)

from . import safecell

ORDER = ["unmatched", "duplicate", "new", "changed", "slip", "no revision"]
STATUS = {"unmatched": "NOT MATCHED", "duplicate": "DUPLICATE",
          "new": "New sheet", "changed": "Changed", "slip": "Slip sheeted",
          "no revision": "No revision"}
COLORS = {"unmatched": "#fecaca", "duplicate": "#fed7aa",
          "new": "#dbeafe", "changed": "#fef08a"}
HEAD = ["Status", "Sheet", "Your file", "Revised file", "Action"]


def _b(p):
    return os.path.basename(p) if p else "—"


def _changed_sheets(report):
    """{sheet number: flagged count of its file} from the revision log of
    each slip-sheeted file."""
    from . import revisions
    out = {}
    for f in (report or {}).get("files", []):
        d = f.get("doc")
        own = d is None
        try:
            d = d or fitz.open(f["file"])
            revs = revisions.read(d)["revisions"]
            if revs:
                for n in revs[-1].get("sheets") or []:
                    out[n] = f.get("flagged", 0)
        except Exception:
            pass
        finally:
            if own and d is not None:
                d.close()
    return out


def rows(plan, report=None):
    """[{kind, status, sheet, mine, new, action}] in report order."""
    out = []
    for u in plan.get("unmatched", []):
        out.append({"kind": "unmatched", "sheet": "(no number)", "mine": "—",
                    "new": f"{_b(u['file'])} p.{u['page'] + 1}",
                    "action": "Not slip sheeted - no sheet number read. "
                              "Slip sheet by hand."})
    for d in plan.get("duplicates", []):
        out.append({"kind": "duplicate", "sheet": d["number"], "mine": "—",
                    "new": f"{_b(d['file'])} p.{d['page'] + 1}",
                    "action": "Skipped - number already used by another "
                              "revised page."})
    for r in plan.get("new_only", []):
        out.append({"kind": "new", "sheet": r["number"], "mine": "—",
                    "new": f"{_b(r['file'])} p.{r['page'] + 1}",
                    "action": "Added as a new sheet"})
    changed = _changed_sheets(report) if report else {}
    for m in plan.get("matches", []):
        ch = m["number"] in changed
        out.append({"kind": "changed" if ch else "slip",
                    "sheet": m["number"], "mine": _b(m["file"]),
                    "new": f"{_b(m['new_file'])} p.{m['new_page'] + 1}",
                    "action": (f"Slip sheeted - drawing changed, "
                               f"{changed[m['number']]} takeoff(s) flagged "
                               "in that file") if ch else "Slip sheeted"})
    for n in plan.get("unchanged", []):
        out.append({"kind": "no revision", "sheet": n, "mine": "", "new": "—",
                    "action": "No revised version"})
    out.sort(key=lambda r: ORDER.index(r["kind"]))       # stable
    for r in out:
        r["status"] = STATUS[r["kind"]]
    return out


def summary(rs):
    c = {k: sum(1 for r in rs if r["kind"] == k) for k in ORDER}
    parts = []
    if c["unmatched"]:
        parts.append(f"{c['unmatched']} revised page(s) NOT matched")
    if c["duplicate"]:
        parts.append(f"{c['duplicate']} duplicate(s) skipped")
    parts.append(f"{c['new']} new")
    if c["changed"]:
        parts.append(f"{c['changed']} changed")
    parts.append(f"{c['slip'] + c['changed']} slip sheeted")
    parts.append(f"{c['no revision']} with no revision")
    return ", ".join(parts)


def to_csv(rs, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = safecell.writer(f)
        w.writerow(HEAD)
        for r in rs:
            w.writerow([r["status"], r["sheet"], r["mine"], r["new"],
                        r["action"]])
    return path


def to_pdf(rs, path, label=""):
    doc = fitz.open()
    page, y = None, 0
    widths = [80, 70, 110, 120, 200]

    def new_page():
        p = doc.new_page(width=612, height=792)
        p.insert_text((36, 40), f"Slip sheet report {label}".strip(),
                      fontsize=14)
        p.insert_text((36, 58), summary(rs), fontsize=8)
        x = 36
        for h, w in zip(HEAD, widths):
            p.insert_text((x, 80), h, fontsize=8, fontname="hebo")
            x += w
        return p, 96
    page, y = new_page()
    for r in rs:
        if y > 760:
            page, y = new_page()
        if r["kind"] in COLORS:
            c = QColor(COLORS[r["kind"]])
            page.draw_rect(fitz.Rect(34, y - 9, 578, y + 3), color=None,
                           fill=(c.redF(), c.greenF(), c.blueF()))
        x = 36
        for v, w in zip([r["status"], r["sheet"], r["mine"], r["new"],
                         r["action"]], widths):
            page.insert_text((x, y), str(v)[:int(w / 4)], fontsize=7,
                             fontname="hebo" if r["kind"] == "unmatched"
                             else "helv")
            x += w
        y += 13
    doc.save(path)
    doc.close()
    return path


class SlipReportDialog(QDialog):
    def __init__(self, parent, rs, label=""):
        super().__init__(parent)
        self.rs, self.label = rs, label
        self.setWindowTitle("Slip Sheet Report")
        self.resize(820, 480)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(summary(rs)))
        self.table = QTableWidget(len(rs), len(HEAD))
        self.table.setHorizontalHeaderLabels(HEAD)
        bold = QFont()
        bold.setBold(True)
        for i, r in enumerate(rs):
            for j, v in enumerate([r["status"], r["sheet"], r["mine"],
                                   r["new"], r["action"]]):
                it = QTableWidgetItem(str(v))
                it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                if r["kind"] in COLORS:
                    it.setBackground(QBrush(QColor(COLORS[r["kind"]])))
                if r["kind"] == "unmatched":
                    it.setFont(bold)
                self.table.setItem(i, j, it)
        self.table.resizeColumnsToContents()
        lay.addWidget(self.table)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.addButton("Export CSV…", QDialogButtonBox.ActionRole) \
            .clicked.connect(lambda: self._export("csv"))
        bb.addButton("Export PDF…", QDialogButtonBox.ActionRole) \
            .clicked.connect(lambda: self._export("pdf"))
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _export(self, ext):
        from .reportname import report_file_name
        proj = os.path.splitext(os.path.basename(
            getattr(self.parent(), "_path", "") or ""))[0]
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Report",
            report_file_name("Slip Sheet Report", proj, ext=f".{ext}"),
            f"{ext.upper()} (*.{ext})")
        if path:
            (to_csv(self.rs, path) if ext == "csv"
             else to_pdf(self.rs, path, self.label))
