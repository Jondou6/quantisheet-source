"""Pre-bid Checklist window (Estimate > Pre-bid Checklist): three checks,
green or red, a one-page printout and the bid lock."""
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QDialog, QFileDialog, QHBoxLayout,
                               QInputDialog, QLabel, QMenu, QMessageBox,
                               QPushButton, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout)

from . import annotate, prebid
from .reportname import report_file_name
from .dmoney import c2 as _c2


def _report_path(doc, kind, ext):
    """Next to the PDF, named by the company rule (date first)."""
    name = doc.name or ""
    return os.path.join(os.path.dirname(name), report_file_name(
        kind, os.path.splitext(os.path.basename(name))[0], ext=ext))


GREEN, RED = QColor(20, 130, 50), QColor(185, 20, 20)


class PrebidDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.rep = None
        self.setWindowTitle("Pre-bid Checklist")
        self.resize(820, 620)
        v = QVBoxLayout(self)
        self.verdict = QLabel()
        f = self.verdict.font()
        f.setPointSizeF(f.pointSizeF() * 1.6)
        f.setBold(True)
        self.verdict.setFont(f)
        v.addWidget(self.verdict)
        self.lock_lbl = QLabel()
        self.lock_lbl.setWordWrap(True)
        v.addWidget(self.lock_lbl)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Item", "Sheet", "Status"])
        self.tree.setColumnWidth(0, 470)
        self.tree.itemDoubleClicked.connect(self._go)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        v.addWidget(self.tree, 1)
        hint = QLabel("Double-click to go to it. Right-click a markup or "
                      "cloud to mark it Priced, Excluded (with a reason) or "
                      "RFI; right-click a sheet to mark it reviewed.")
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        v.addWidget(hint)
        row = QHBoxLayout()
        b = QPushButton("Mark This Sheet Reviewed")
        b.clicked.connect(lambda: self.mark_page_reviewed())
        row.addWidget(b)
        b = QPushButton("Refresh")
        b.clicked.connect(lambda: self.refresh())
        row.addWidget(b)
        row.addStretch()
        rep_btn = QPushButton("Missed-Item Report…")
        rep_btn.setToolTip("Every open sheet, markup, cloud and spec gap - "
                           "Excel or PDF")
        rep_btn.clicked.connect(lambda: self.export_report())
        row.addWidget(rep_btn)
        self.print_btn = QPushButton("Print One Page…")
        self.print_btn.clicked.connect(lambda: self.print_page())
        row.addWidget(self.print_btn)
        self.unlock_btn = QPushButton("Unlock…")
        self.unlock_btn.clicked.connect(lambda: self.unlock())
        row.addWidget(self.unlock_btn)
        self.lock_btn = QPushButton("Lock Bid…")
        self.lock_btn.setObjectName("primary")
        self.lock_btn.clicked.connect(lambda: self.lock())
        row.addWidget(self.lock_btn)
        v.addLayout(row)
        self.refresh()

    @property
    def doc(self):
        v = getattr(self.win, "_view", None)
        return v.doc if v else None

    # ---------------------------------------------------------- list
    def refresh(self):
        doc = self.doc
        self.tree.clear()
        if doc is None:
            return None
        self.rep = rep = prebid.check(doc)
        c = rep.counts()
        self.verdict.setText("✔ Ready to lock" if rep.ok else
                             "✘ Not ready")
        self.verdict.setStyleSheet(f"color: {(GREEN if rep.ok else RED).name()}")
        groups = [
            ("Sheets reviewed", rep.unreviewed_sheets,
             c["sheets"] - c["unreviewed_sheets"], c["sheets"], "sheet"),
            ("Markups priced, excluded or RFI", rep.open_markups,
             c["markups"] - c["open_markups"], c["markups"], "markup"),
            ("Revision clouds accounted for", rep.unaccounted_clouds,
             c["clouds"] - c["unaccounted_clouds"], c["clouds"], "cloud")]
        for title, items, done, tot, kind in groups:
            top = QTreeWidgetItem([f"{'✔' if not items else '✘'}  {title}",
                                   "", f"{done} of {tot}"])
            top.setForeground(0, GREEN if not items else RED)
            f = top.font(0)
            f.setBold(True)
            top.setFont(0, f)
            self.tree.addTopLevelItem(top)
            for it in items:
                ch = QTreeWidgetItem([it["label"], it["sheet"],
                                      it.get("status", "")])
                ch.setData(0, Qt.UserRole, (kind, it))
                top.addChild(ch)
            top.setExpanded(bool(items) and len(items) <= 200)
        lk = prebid.lock_state(doc)
        if lk:
            self.lock_lbl.setText(
                f"Locked {lk['at'].replace('T', ' ')} by {lk['by']} at "
                f"${_c2(float(lk['total'])):,.2f}." +
                (" <b style='color:#b91414'>The takeoff has changed since "
                 "- unlock and lock again.</b>" if lk["stale"] else ""))
        else:
            self.lock_lbl.setText("Not locked.")
        self.lock_btn.setEnabled(rep.ok)
        self.unlock_btn.setEnabled(bool(lk))
        return rep

    def _go(self, item, _col=0):
        data = item.data(0, Qt.UserRole)
        if not data:
            return
        kind, it = data
        try:
            self.win._go_page(it["page"])
            if it.get("ref"):
                self.win._go_annot(it["page"], it["ref"])
        except Exception:
            pass

    def _annot(self, it):
        # keep the page alive while its annotation is used (PyMuPDF frees
        # an annotation's page when nothing refers to it)
        self._page = self.doc[it["page"]]
        found = annotate.find_annots(self._page, it["ref"])
        return found[0] if found else None

    def _menu(self, pos):
        item = self.tree.itemAt(pos)
        data = item.data(0, Qt.UserRole) if item else None
        if not data:
            return
        kind, it = data
        m = QMenu(self)
        if kind == "sheet":
            m.addAction("Mark reviewed",
                        lambda: self.set_reviewed(it["page"]))
        else:
            m.addAction("Priced", lambda: self.set_scope(it, "priced"))
            m.addAction("Link to Estimate Line…",
                        lambda: self.link(it))
            m.addAction("Excluded…", lambda: self.set_scope(it, "excluded"))
            m.addAction("Sent as an RFI", lambda: self.set_scope(it, "rfi"))
            m.addAction("Open", lambda: self.set_scope(it, "open"))
        m.exec(self.tree.viewport().mapToGlobal(pos))

    # ---------------------------------------------------------- changes
    def _changed(self):
        v = getattr(self.win, "_view", None)
        if v is not None:
            try:
                v.mark_dirty()
            except Exception:
                pass
        return self.refresh()

    def set_reviewed(self, pno, reviewed=True):
        prebid.set_reviewed(self.doc, pno, reviewed)
        return self._changed()

    def mark_page_reviewed(self):
        v = getattr(self.win, "_view", None)
        if v is None:
            return None
        return self.set_reviewed(int(getattr(v, "page", 0)))

    def set_scope(self, it, status, reason=None):
        a = self._annot(it)
        if a is None:
            return None
        if status == "excluded" and reason is None:
            reason, ok = QInputDialog.getText(
                self, "Excluded", "Why is it excluded? (e.g. By owner, "
                "NIC, by others)")
            if not ok:
                return None
        try:
            if status == "rfi":
                prebid.send_to_rfi(self.doc, it["page"], a)
            else:
                prebid.set_scope(self.doc, a, status, reason or "")
        except prebid.PrebidError as e:
            QMessageBox.warning(self, "Pre-bid Checklist", str(e))
            return None
        return self._changed()

    def link(self, it, line=None):
        """Price a markup by linking it to an estimate line or cost code."""
        a = self._annot(it)
        if a is None:
            return None
        est = prebid.estimate_lines(self.doc)
        if line is None:
            opts = sorted(est["lines"]) + sorted(est["codes"])
            if not opts:
                QMessageBox.information(self, "Link to Estimate",
                                        "The estimate has no lines yet.")
                return None
            line, ok = QInputDialog.getItem(self, "Link to Estimate",
                                            "Priced in:", opts, 0, True)
            if not ok or not line:
                return None
        if line in est["lines"]:
            prebid.link(self.doc, a, line_id=line)
        else:
            prebid.link(self.doc, a, cost_code=line)
        return self._changed()

    def export_report(self, path=None):
        doc = self.doc
        if doc is None:
            return None
        if path is None:
            path, _ = QFileDialog.getSaveFileName(
                self, "Missed-Item Report",
                _report_path(doc, "Missed Items", ".xlsx"),
                "Excel (*.xlsx);;PDF (*.pdf)")
        if not path:
            return None
        return prebid.export_report(doc, path, self.rep)

    # ---------------------------------------------------------- output
    def print_page(self, path=None):
        doc = self.doc
        if doc is None:
            return None
        if path is None:
            path, _ = QFileDialog.getSaveFileName(
                self, "Pre-bid Checklist",
                _report_path(doc, "Pre-bid Checklist", ".pdf"),
                "PDF (*.pdf)")
        if not path:
            return None
        return prebid.print_pdf(doc, path, self.rep)

    def _estimate_total(self):
        try:
            from . import assemblies
            rows, totals, _e = assemblies.rollup(self.doc)
            t = (totals or {}).get("total")
            return float(t if t is not None else sum(r["total"]
                                                     for r in rows))
        except Exception:
            return 0.0

    def lock(self, total=None):
        if total is None:
            total, ok = QInputDialog.getDouble(
                self, "Lock Bid", "Bid total $", self._estimate_total(), 0,
                1e12, 2)
            if not ok:
                return None
        try:
            lk = prebid.lock(self.doc, total)
        except prebid.PrebidError as e:
            QMessageBox.warning(self, "Pre-bid Checklist", str(e))
            return None
        self._changed()
        return lk

    def unlock(self, reason=None):
        if reason is None:
            reason, ok = QInputDialog.getText(self, "Unlock Bid",
                                              "Why are you unlocking it?")
            if not ok:
                return None
        try:
            prebid.unlock(self.doc, reason=reason)
        except prebid.PrebidError as e:
            QMessageBox.warning(self, "Pre-bid Checklist", str(e))
            return None
        self._changed()
        return True
