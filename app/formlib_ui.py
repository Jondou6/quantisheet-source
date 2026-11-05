"""Form Library window (File > New From Form Library)."""
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout,
    QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton, QSplitter,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from . import formlib


class FormLibraryDialog(QDialog):
    """Pick a form; it opens as a new, untitled copy."""

    def __init__(self, parent=None, job_name=""):
        super().__init__(parent)
        self.setWindowTitle("Form Library")
        self.resize(1000, 640)
        self.chosen = None
        lay = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search forms")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda *_: self.refresh())
        lay.addWidget(self.search)
        split = QSplitter()
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Form", "Pages", "Fields"])
        self.tree.setColumnWidth(0, 360)
        self.tree.currentItemChanged.connect(self._show)
        self.tree.itemDoubleClicked.connect(lambda it, _c: self._open()
                                            if it.data(0, Qt.UserRole)
                                            else None)
        split.addWidget(self.tree)
        right = QWidget()
        rl = QVBoxLayout(right)
        self.preview = QLabel("")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumWidth(360)
        rl.addWidget(self.preview, 1)
        self.info = QLabel("")
        self.info.setWordWrap(True)
        rl.addWidget(self.info)
        self.clear = QCheckBox("Clear the filled-in fields (start blank)")
        rl.addWidget(self.clear)
        self.fill = QCheckBox(f"Fill project details from {job_name}"
                              if job_name else
                              "Fill company details (name, address, date)")
        self.fill.setChecked(True)
        rl.addWidget(self.fill)
        split.addWidget(right)
        split.setSizes([520, 440])
        lay.addWidget(split, 1)
        row = QHBoxLayout()
        for label, fn in (("Add Forms…", self._add),
                          ("Add a Folder…", self._add_folder),
                          ("Rename…", self._rename),
                          ("Move to Category…", self._move),
                          ("Remove", self._remove),
                          ("Open Library Folder", self._folder)):
            b = QPushButton(label)
            b.clicked.connect(lambda _c=False, _f=fn: _f())
            row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.open_btn = bb.addButton("Open a Copy", QDialogButtonBox.AcceptRole)
        self.open_btn.clicked.connect(self._open)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.refresh()

    # ---- list ----------------------------------------------------------------
    def refresh(self, select=None):
        words = self.search.text().lower().split()
        self.tree.clear()
        cats = {}
        first = None
        for e in formlib.entries():
            hay = f"{e['name']} {e['category']} {e.get('notes', '')}".lower()
            if words and not all(w in hay for w in words):
                continue
            top = cats.get(e["category"])
            if top is None:
                top = cats[e["category"]] = QTreeWidgetItem([e["category"]])
                f = top.font(0)
                f.setBold(True)
                top.setFont(0, f)
                self.tree.addTopLevelItem(top)
                top.setExpanded(True)
            it = QTreeWidgetItem([e["name"], str(e.get("pages", "")),
                                  str(e.get("fields") or "")])
            it.setData(0, Qt.UserRole, e["id"])
            if e.get("filled"):
                it.setToolTip(0, "Has filled-in fields from a past job")
            top.addChild(it)
            if first is None or e["id"] == select:
                first = it
        if first is not None:
            self.tree.setCurrentItem(first)
        else:
            self.preview.setText("No forms yet. Click Add Forms… or Add a "
                                 "Folder…")
            self.info.setText("")

    def current(self):
        it = self.tree.currentItem()
        eid = it.data(0, Qt.UserRole) if it else None
        if not eid:
            return None
        return next((e for e in formlib.entries() if e["id"] == eid), None)

    def _show(self, *_):
        e = self.current()
        if not e:
            self.preview.clear()
            self.info.setText("")
            return
        try:
            import fitz
            with fitz.open(formlib.path_of(e)) as d:
                pix = d[0].get_pixmap(dpi=50, annots=True)
                img = QImage(pix.samples, pix.width, pix.height, pix.stride,
                             QImage.Format_RGB888).copy()
            self.preview.setPixmap(QPixmap.fromImage(img).scaled(
                360, 470, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        except Exception:
            self.preview.setText("(no preview)")
        txt = (f"<b>{e['name']}</b><br>{e['category']} - {e['pages']} "
               f"page(s), {e['fields'] or 'no'} fillable field(s)")
        if not e.get("fields"):
            txt += ("<br>Not fillable: use Document > Prepare Form to add "
                    "fields, or type on it with Fill && Sign.")
        if e.get("filled"):
            txt += (f"<br><span style='color:#b06000'>{e['filled']} field(s) "
                    "still hold a past job's entries.</span>")
        if e.get("notes"):
            txt += f"<br><i>{e['notes']}</i>"
        self.info.setText(txt)
        self.clear.setChecked(bool(e.get("filled")))

    # ---- actions -------------------------------------------------------------
    def _open(self):
        e = self.current()
        if not e:
            return None
        self.chosen = (e, self.clear.isChecked(), self.fill.isChecked())
        self.accept()
        return self.chosen

    def _ask_category(self, default=""):
        cats = formlib.categories() or ["General"]
        text, ok = QInputDialog.getItem(self, "Category", "Category:", cats,
                                        max(0, cats.index(default))
                                        if default in cats else 0, True)
        return text.strip() if ok and text.strip() else None

    def _add(self, paths=None, category=None):
        if paths is None:
            paths, _ = QFileDialog.getOpenFileNames(
                self, "Add Forms", "", "Forms (*.pdf *.docx *.doc *.xlsx "
                "*.xls *.rtf *.odt *.ods)")
        if not paths:
            return []
        category = category or self._ask_category()
        if not category:
            return []
        added, bad = [], []
        for p in paths:
            try:
                added.append(formlib.add(p, category))
            except Exception as ex:
                bad.append(f"{os.path.basename(p)}: {ex}")
        if bad:
            QMessageBox.warning(self, "Add Forms", "\n".join(bad))
        self.refresh(added[-1]["id"] if added else None)
        return added

    def _add_folder(self, path=None):
        if path is None:
            path = QFileDialog.getExistingDirectory(self, "Add a Folder of "
                                                    "Forms")
        if not path:
            return []
        added = []
        for dp, _dn, fn in os.walk(path):
            rel = os.path.relpath(dp, path)
            cat = os.path.basename(path) if rel == "." else \
                rel.split(os.sep)[0]
            cat = cat.split(". ", 1)[-1] if cat[:1].isdigit() else cat
            for f in sorted(fn):
                ext = os.path.splitext(f)[1].lower()
                if ext == ".pdf" or ext in formlib.OFFICE:
                    try:
                        added.append(formlib.add(os.path.join(dp, f), cat))
                    except Exception:
                        continue
        self.refresh()
        QMessageBox.information(self, "Add a Folder",
                                f"Added {len(added)} form(s).")
        return added

    def _rename(self):
        e = self.current()
        if not e:
            return None
        name, ok = QInputDialog.getText(self, "Rename", "Name:",
                                        QLineEdit.Normal, e["name"])
        if ok and name.strip():
            formlib.update(e["id"], name=name.strip())
            self.refresh(e["id"])
        return name

    def _move(self):
        e = self.current()
        if not e:
            return None
        cat = self._ask_category(e["category"])
        if cat:
            formlib.update(e["id"], category=cat)
            self.refresh(e["id"])
        return cat

    def _remove(self):
        e = self.current()
        if not e:
            return
        if QMessageBox.question(self, "Remove", f"Remove {e['name']} from "
                                "the library?") == QMessageBox.Yes:
            formlib.remove(e["id"])
            self.refresh()

    def _folder(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(formlib.folder()))
