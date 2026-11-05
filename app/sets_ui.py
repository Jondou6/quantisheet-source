"""Sets panel: every sheet of a multi-file drawing set in one list, and
Batch Slip Sheet."""
import logging
import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox,
                               QFileDialog, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QMessageBox, QProgressDialog,
                               QPushButton, QTableWidget, QTableWidgetItem,
                               QToolButton, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from . import icons, sets, settings


class SetsPanel(QWidget):
    open_sheet = Signal(str, int)          # file, page
    batch_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.set = None
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 4, 4, 4)
        row = QHBoxLayout()
        row.setSpacing(2)
        self.name = QLabel("No set open")
        self.name.setStyleSheet("font-weight: 600")
        row.addWidget(self.name, 1)
        for icon, tip, fn in (("new", "New set from PDF files…",
                               lambda: self.new_set()),
                              ("open", "Open a set…", lambda: self.open_set()),
                              ("page_add", "Add files to this set…",
                               lambda: self.add_files()),
                              ("rotate", "Re-read sheet numbers",
                               lambda: self.refresh(True)),
                              ("slipsheet", "Batch Slip Sheet: bring a "
                               "revision into every file of the set…",
                               self.batch_requested.emit),
                              ("export", "Drawing Log: every sheet's current "
                               "revision and the ones it replaced (CSV)…",
                               lambda: self.export_log())):
            b = QToolButton()
            b.setObjectName("IconButton")
            b.setIcon(icons.icon(icon))
            b.setToolTip(tip)
            b.clicked.connect(lambda _c=False, _f=fn: _f())
            row.addWidget(b)
        v.addLayout(row)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Find a sheet (number or title)")
        self.filter.textChanged.connect(lambda: self.fill())
        v.addWidget(self.filter)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemActivated.connect(self._go)
        self.tree.itemClicked.connect(self._go)
        v.addWidget(self.tree, 1)
        last = settings.get("current_set")
        if last and os.path.exists(last):
            try:
                self.use(sets.load(last))
            except Exception:
                logging.getLogger(__name__).debug("ignored error", exc_info=True)

    def use(self, s):
        self.set = s
        settings.set("current_set", s["path"])
        self.name.setText(f"{s['name']}  ·  {len(s['files'])} file(s)")
        self.fill()
        return s

    def fill(self):
        self.tree.clear()
        if not self.set:
            return 0
        q = self.filter.text().strip().lower()
        groups = {}
        n = 0
        for r in sets.sheets(self.set):
            text = f"{r['number'] or '(no number)'}  {r['title']}".strip()
            if q and q not in text.lower():
                continue
            g = groups.get(r["discipline"])
            if g is None:
                g = groups[r["discipline"]] = QTreeWidgetItem(
                    [r["discipline"]])
                self.tree.addTopLevelItem(g)
                g.setExpanded(True)
            it = QTreeWidgetItem([text])
            it.setToolTip(0, f"{os.path.basename(r['file'])}, page "
                             f"{r['page'] + 1}")
            it.setData(0, Qt.UserRole, (r["file"], r["page"]))
            g.addChild(it)
            n += 1
        return n

    def _go(self, item, _col=0):
        d = item.data(0, Qt.UserRole)
        if d:
            self.open_sheet.emit(d[0], d[1])

    def new_set(self, paths=None, dest=None):
        if paths is None:
            paths, _ = QFileDialog.getOpenFileNames(
                self, "Files in the Set", "", "PDF (*.pdf)")
        if not paths:
            return None
        if dest is None:
            dest, _ = QFileDialog.getSaveFileName(
                self, "Save Set As", os.path.join(
                    os.path.dirname(paths[0]), "Drawings" + sets.EXT),
                f"QuantiSheet set (*{sets.EXT})")
        if not dest:
            return None
        if not dest.endswith(sets.EXT):
            dest += sets.EXT
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            s = sets.new(dest, paths)
        finally:
            QApplication.restoreOverrideCursor()
        return self.use(s)

    def open_set(self, path=None):
        if path is None:
            path, _ = QFileDialog.getOpenFileName(
                self, "Open Set", "", f"QuantiSheet set (*{sets.EXT})")
        if not path:
            return None
        try:
            s = sets.load(path)
        except sets.SetError as e:          # Grok r5 #11: not silent
            QMessageBox.warning(self, "Open Set", str(e))
            return None
        sets.refresh(s)
        sets.save(s)
        return self.use(s)

    def add_files(self, paths=None):
        if not self.set:
            return self.new_set(paths)
        if paths is None:
            paths, _ = QFileDialog.getOpenFileNames(
                self, "Add Files", os.path.dirname(self.set["path"]),
                "PDF (*.pdf)")
        if not paths:
            return None
        sets.add_files(self.set, paths)
        return self.use(self.set)

    def refresh(self, force=False):
        if not self.set:
            return None
        if force:
            self.set["stamps"] = {}
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            sets.refresh(self.set)
            sets.save(self.set)
        finally:
            QApplication.restoreOverrideCursor()
        return self.use(self.set)


    def export_log(self, path=None):
        s = getattr(self, "set", None) or getattr(self, "s", None)
        if not s:
            return None
        if path is None:
            from PySide6.QtWidgets import QFileDialog
            path, _ = QFileDialog.getSaveFileName(
                self, "Drawing Log", "Drawing Log.csv", "CSV (*.csv)")
            if not path:
                return None
        return sets.drawing_log_csv(s, path)

class BatchSlipDialog(QDialog):
    """Pick the revised drawings, review the sheet matches, run."""

    def __init__(self, window, s):
        super().__init__(window)
        self.win, self.set = window, s
        self.setWindowTitle("Batch Slip Sheet")
        self.resize(860, 560)
        self.paths = []
        self.report = None
        v = QVBoxLayout(self)
        row = QHBoxLayout()
        self.label = QLineEdit()
        self.label.setPlaceholderText("Revision name, e.g. Addendum 2")
        row.addWidget(QLabel("Revision:"))
        row.addWidget(self.label, 1)
        b = QPushButton("Revised Drawings…")
        b.clicked.connect(lambda: self.pick())
        row.addWidget(b)
        v.addLayout(row)
        self.info = QLabel("Pick the revised PDF(s). Sheets are matched by "
                           "sheet number, whichever file they're in.")
        self.info.setWordWrap(True)
        v.addWidget(self.info)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Sheet", "In file",
                                              "Revised from", "Action"])
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch)
        self.table.verticalHeader().hide()
        v.addWidget(self.table, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.go = bb.addButton("Slip Sheet All", QDialogButtonBox.AcceptRole)
        self.go.setEnabled(False)
        bb.accepted.connect(lambda: self.run())
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def pick(self, paths=None):
        if paths is None:
            paths, _ = QFileDialog.getOpenFileNames(
                self, "Revised Drawings", "", "PDF (*.pdf)")
        if not paths:
            return None
        self.paths = list(paths)
        if not self.label.text().strip():
            self.label.setText(os.path.splitext(
                os.path.basename(paths[0]))[0])
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            p = sets.plan(self.set, self.paths)
        finally:
            QApplication.restoreOverrideCursor()
        from . import slipreport
        from PySide6.QtGui import QColor
        # what can't be matched comes first, in red
        srows = [r for r in slipreport.rows(p) if r["kind"] != "no revision"]
        self.table.setRowCount(len(srows))
        for r, row in enumerate(srows):
            bad = row["kind"] in ("unmatched", "duplicate")
            for c, val in enumerate((row["sheet"], row["mine"], row["new"],
                                     ("⚠ " if bad else "") + row["action"])):
                it = QTableWidgetItem(str(val))
                it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                if bad:
                    it.setForeground(QColor(185, 20, 20))
                self.table.setItem(r, c, it)
        warn = ""
        if p["unmatched"] or p["duplicates"]:
            warn = (f" ⚠ {len(p['unmatched'])} revised page(s) have no "
                    f"readable sheet number and {len(p['duplicates'])} "
                    "repeat a number: they will NOT be slip sheeted "
                    "(marked ⚠ above).")
        self.info.setText(
            f"{len(p['matches'])} sheet(s) will be slip sheeted in "
            f"{len({m['file'] for m in p['matches']})} file(s); "
            f"{len(p['new_only'])} new sheet(s) will be added; "
            f"{len(p['unchanged'])} sheet(s) have no revision. Each changed "
            "file is backed up first." + warn)
        self.go.setEnabled(bool(p["matches"] or p["new_only"]))
        self.plan = p
        return p

    def _busy_files(self):
        """Files of the plan that are open in a tab: unsaved ones block the
        run; saved ones are closed and reopened afterwards."""
        from .main_window import DocTab
        files = {os.path.normcase(m["file"]) for m in self.plan["matches"]}
        dirty, reopen = [], []
        for i in range(self.win.tabs.count()):
            t = self.win.tabs.widget(i)
            if isinstance(t, DocTab) and t.path and \
                    os.path.normcase(t.path) in files:
                (dirty if t.view.dirty else reopen).append((i, t.path))
        return dirty, reopen

    def run(self):
        label = self.label.text().strip() or "Revision"
        skipped = len(self.plan.get("unmatched", [])) + \
            len(self.plan.get("duplicates", []))
        if skipped and QMessageBox.question(
                self, "Batch Slip Sheet",
                f"{skipped} revised page(s) can't be matched to a sheet "
                "(no readable sheet number, or a repeated one) and will be "
                "left out. Slip sheet the rest anyway?") != QMessageBox.Yes:
            return None
        dirty, reopen = self._busy_files()
        if dirty:
            QMessageBox.warning(
                self, "Batch Slip Sheet", "Save these first:\n" +
                "\n".join(os.path.basename(p) for _, p in dirty))
            return None
        for i, _p in sorted(reopen, reverse=True):
            self.win.close_tab(i)
        dlg = QProgressDialog("Slip sheeting…", "Stop", 0, 1, self)
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumDuration(300)

        def progress(k, n, name):
            dlg.setMaximum(n)
            dlg.setValue(k)
            dlg.setLabelText(f"{name} ({k + 1} of {n})…")
            QApplication.processEvents()
            return dlg.wasCanceled()

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.report = sets.batch_slip(self.set, self.paths, label,
                                          progress=progress,
                                          allow_unmatched=True)
        finally:
            QApplication.restoreOverrideCursor()
            dlg.close()
            # the tabs closed above come back even if it failed or was
            # stopped, so the window matches the files (review 3b C7)
            for _i, p in reopen:
                self.win.open_path(p)
        rep = self.report
        flagged = sum(f["flagged"] for f in rep["files"])
        risk = sum(f["at_risk"] for f in rep["files"])
        QMessageBox.information(
            self, "Batch Slip Sheet",
            ("Stopped. " if rep.get("stopped") else "") +
            f"Slip sheeted {sum(f['sheets'] for f in rep['files'])} sheet(s) "
            f"in {len(rep['files'])} file(s); "
            f"{sum(f['changed'] for f in rep['files'])} changed. {flagged} "
            f"takeoff(s) flagged to re-measure (${risk:,.0f} of the bid). "
            + (f"{len(rep['new_sheets'])} new sheet(s) added as "
               f"\"{os.path.basename(rep['new_file'])}\". "
               if rep.get("new_sheets") else "")
            + (f"Originals backed up in \"{os.path.basename(rep['backup'])}\"."
               if rep.get("backup") else "")
            + (f" ⚠ {len(rep['unmatched']) + len(rep['duplicates'])} revised "
               "page(s) were left out (no or repeated sheet number) - slip "
               "sheet those by hand." if rep.get("unmatched") or
               rep.get("duplicates") else ""))
        try:                   # the full report, unmatched sheets first
            from . import slipreport
            dlg = slipreport.SlipReportDialog(
                self.win, slipreport.rows(self.plan, rep), label)
            self.win._slip_report = dlg
            dlg.show()
        except Exception:
            pass
        self.accept()
        return rep
