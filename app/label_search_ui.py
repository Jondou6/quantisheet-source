"""Takeoff > Count by Label: find a tag or a tag family (wildcards), see
every hit first - grouped by what it matched, on the plan or in a
schedule / legend - untick the wrong ones, then count (Nov 1). The search
is label_search.py."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QDialog,
                               QDialogButtonBox, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QPushButton,
                               QRadioButton, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout)

from . import label_search

TITLE = "Count by Label"
ROLE = Qt.UserRole + 1


class LabelSearchDialog(QDialog):
    def __init__(self, view, parent=None, text=""):
        super().__init__(parent)
        self.view = view
        self.hits = []
        self.counted = 0
        self.setWindowTitle(TITLE)
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(QLabel("Text to find:"))
        self.text = QLineEdit(text)
        self.text.setPlaceholderText("EXIT   or   P-#   or   WH-*")
        self.text.returnPressed.connect(lambda: self.find())
        row.addWidget(self.text, 1)
        self.find_btn = QPushButton("Find")
        self.find_btn.clicked.connect(lambda: self.find())
        row.addWidget(self.find_btn)
        lay.addLayout(row)
        hint = QLabel("Wildcards: * any letters, ? one letter, # a number "
                      "(P-# finds P-1 … P-12). Nothing is counted until you "
                      "press Count.")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.plan_only = QCheckBox("Leave out the title block, schedules, "
                                   "legends and notes (listed, not ticked)")
        self.plan_only.setChecked(True)
        lay.addWidget(self.plan_only)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Found", "Page", "Where"])
        self.tree.itemDoubleClicked.connect(self._go)
        self.tree.itemChanged.connect(self._changed)
        lay.addWidget(self.tree, 1)
        how = QHBoxLayout()
        self.per_tag = QRadioButton("One item per tag")
        self.one = QRadioButton("All as one item:")
        self.one_name = QLineEdit()
        grp = QButtonGroup(self)
        grp.addButton(self.per_tag)
        grp.addButton(self.one)
        self.one.setChecked(True)
        how.addWidget(self.per_tag)
        how.addWidget(self.one)
        how.addWidget(self.one_name, 1)
        lay.addLayout(how)
        self.summary = QLabel("")
        lay.addWidget(self.summary)
        bb = QDialogButtonBox()
        self.count_btn = bb.addButton("Count", QDialogButtonBox.AcceptRole)
        self.count_btn.setEnabled(False)
        self.count_btn.clicked.connect(lambda: self.count())
        bb.addButton(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.resize(560, 560)
        self._filling = False

    # ---- find -------------------------------------------------------------
    def find(self, quiet=False):
        t = self.text.text().strip()
        if not t:
            return 0
        info = {}
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.hits = label_search.search(
                self.view.doc, t, plan_area_only=self.plan_only.isChecked(),
                info=info)
        except Exception as e:                            # noqa: BLE001
            QApplication.restoreOverrideCursor()
            if not quiet:
                QMessageBox.warning(self, TITLE, str(e))
            return 0
        QApplication.restoreOverrideCursor()
        groups = label_search.by_text(self.hits)
        wild = label_search.has_wildcard(t)
        self.per_tag.setChecked(wild and len(groups) > 1)
        self.one.setChecked(not self.per_tag.isChecked())
        if not self.one_name.text().strip() or not wild:
            self.one_name.setText(t if not wild else t.replace("#", "")
                                  .replace("*", "").replace("?", "")
                                  .strip("- ") or t)
        self._filling = True
        self.tree.clear()
        for name, hits in groups.items():
            top = QTreeWidgetItem([f"{name}  ({len(hits)})", "", ""])
            top.setFlags(top.flags() | Qt.ItemIsUserCheckable |
                         Qt.ItemIsAutoTristate)
            for h in hits:
                ch = QTreeWidgetItem([name, str(h["page"] + 1),
                                      "plan" if h["in_plan"] else
                                      "schedule / legend / notes"])
                ch.setFlags(ch.flags() | Qt.ItemIsUserCheckable)
                ch.setCheckState(0, Qt.Checked if h["in_plan"]
                                 else Qt.Unchecked)
                ch.setData(0, ROLE, h)
                top.addChild(ch)
            self.tree.addTopLevelItem(top)
        self._filling = False
        self._changed()
        if info.get("ocr_error") and not quiet:
            QMessageBox.information(self, TITLE, "Scanned pages weren't "
                                    "searched: " + info["ocr_error"])
        return len(self.hits)

    def ticked(self):
        """{matched text: [ticked hits]}."""
        out = {}
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            for j in range(top.childCount()):
                ch = top.child(j)
                if ch.checkState(0) == Qt.Checked:
                    h = ch.data(0, ROLE)
                    out.setdefault(h["text"], []).append(h)
        return out

    def _changed(self, *_a):
        if self._filling:
            return
        t = self.ticked()
        n = sum(len(v) for v in t.values())
        off = len(self.hits) - n
        self.summary.setText(f"{len(self.hits)} found - {n} ticked to count"
                             + (f", {off} left out" if off else "")
                             if self.hits else "Nothing found yet.")
        self.count_btn.setEnabled(n > 0)

    def _go(self, item, _col=0):
        h = item.data(0, ROLE)
        if h:
            self.view.go_to(h["page"])

    # ---- count ------------------------------------------------------------
    def count(self):
        groups = self.ticked()
        if not groups:
            return 0
        one = self.one_name.text().strip() if self.one.isChecked() else None
        if self.one.isChecked() and not one:
            one = self.text.text().strip()
        marks = label_search.count_marks(groups, self.view.doc, one_item=one)
        n = self.view.apply_marks(marks) if marks else 0
        self.counted = n
        self.view.status.emit(f"Counted {n} by label" if n else
                              "Nothing counted")
        self.accept()
        return n


def open_dialog(win, show=True, text=""):
    v = getattr(win, "_view", None)
    if not v:
        return None
    dlg = LabelSearchDialog(v, win, text=text)
    if show:
        dlg.exec()
    return dlg
