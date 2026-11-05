"""Documents: the project's drawings, specs and files with every version
kept on the hub, check-out so two people don't overwrite each other, and
one click to open a sheet in QuantiSheet."""
import logging
import os
import threading
from datetime import datetime

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog, QFrame,
                               QHBoxLayout, QHeaderView, QInputDialog,
                               QLabel, QMenu, QMessageBox, QProgressBar,
                               QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from .. import icons
from .widgets import show_date

from ..oldnames import JOB_DIR_OLD as _JOB_DIR_OLD  # a job not opened yet
SKIP_DIRS = {".quantisheet", _JOB_DIR_OLD, "__pycache__", ".git"}


def _size(n):
    n = n or 0
    return f"{n / 1048576:.1f} MB" if n > 1048576 else \
        f"{max(1, n // 1024)} KB"


class _Sig(QObject):
    done = Signal(object, object)
    progress = Signal(int, int)


class DocumentsPage(QWidget):
    def __init__(self, center):
        super().__init__()
        self.center = center
        self.store = center.store
        self.files = []
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        head = QFrame()
        head.setObjectName("pcPageHead")
        h = QHBoxLayout(head)
        h.setContentsMargins(18, 14, 18, 12)
        ic = QLabel()
        ic.setPixmap(icons.icon("folder").pixmap(22, 22))
        h.addWidget(ic)
        t = QLabel("Documents")
        t.setObjectName("pcH1")
        h.addWidget(t)
        self.count = QLabel()
        self.count.setObjectName("muted")
        h.addWidget(self.count)
        h.addStretch()
        self.bar = QProgressBar()
        self.bar.setFixedWidth(180)
        self.bar.setVisible(False)
        h.addWidget(self.bar)
        up = QPushButton("Upload…")
        up.setObjectName("primary")
        up.setIcon(icons.icon("import"))
        up.clicked.connect(lambda _c=False: self.upload())
        h.addWidget(up)
        rf = QPushButton("Refresh")
        rf.setIcon(icons.icon("sync"))
        rf.clicked.connect(self.refresh)
        h.addWidget(rf)
        v.addWidget(head)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setObjectName("muted")
        self.note.setContentsMargins(18, 8, 18, 0)
        v.addWidget(self.note)
        self.table = QTableWidget(0, 7)
        self.table.setObjectName("pcList")
        self.table.setHorizontalHeaderLabels(
            ["Name", "Version", "Updated by", "Date", "Size",
             "Checked out", "Note"])
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(32)
        self.table.setShowGrid(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch)
        self.table.cellDoubleClicked.connect(lambda r, _c: self.open(r))
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        self.table.setAcceptDrops(True)
        v.addWidget(self.table, 1)
        self.setAcceptDrops(True)
        self.sig = _Sig()
        self.sig.done.connect(self._done)
        self.sig.progress.connect(self._progress)

    # ---------------------------------------------------------- listing
    def refresh(self):
        self.files = []
        if self.store.connected:
            self.note.setText("Every upload is kept as a new version. Check "
                              "a file out before you change it so nobody "
                              "else overwrites your work. (Check out covers "
                              "these files only; photos and attachments on "
                              "records are never locked.)")
            # the server call runs in the background, never on the GUI
            # thread (review 3 #4); a newer refresh wins
            self._gen = getattr(self, "_gen", 0) + 1
            gen = self._gen
            h = dict(self.store.data["hub"])
            client = self.store.client()

            def fetch():
                try:
                    return ("ok", client.call("proj.files",
                                              project=h["project"],
                                              key=h["key"]))
                except Exception as e:
                    return ("err", str(e))
            self._bg(fetch, lambda res: self._remote(gen, res))
        else:
            self.note.setText("These are the files in this project's "
                              "folder. Share the project (top right) to "
                              "keep every version on the server and let "
                              "others open them.")
            self._local()
        self._fill()

    def _remote(self, gen, res):
        if gen != getattr(self, "_gen", 0):
            return                            # an older refresh
        kind, r = res
        self.files = []
        if kind == "ok":
            try:
                for f in r["files"]:
                    last = f["versions"][-1]
                    self.files.append({"name": f["name"], "version":
                                       last["v"], "by": last["by"],
                                       "at": last["at"], "size":
                                       last["size"], "note": last["note"],
                                       "lock": f.get("lock"),
                                       "versions": f["versions"]})
            except Exception as e:
                kind, r = "err", str(e)
                self.files = []
        if kind != "ok":
            self.note.setText(f"Can't reach the project server ({r}). "
                              "Showing this PC's project folder.")
            self._local()
        self._fill()

    def _fill(self):
        self.table.setRowCount(len(self.files))
        for i, f in enumerate(self.files):
            lock = f.get("lock") or {}
            vals = [f["name"], f"v{f['version']}" if f.get("version") else
                    "", f.get("by", ""), show_date((f.get("at") or "")[:10]),
                    _size(f.get("size")), lock.get("user", ""),
                    f.get("note", "")]
            for c, val in enumerate(vals):
                it = QTableWidgetItem(val)
                if c == 0:
                    ext = os.path.splitext(f["name"])[1].lower()
                    it.setIcon(icons.icon("open" if ext == ".pdf" else
                                          "attach"))
                self.table.setItem(i, c, it)
        self.count.setText(str(len(self.files)))

    def _local(self):
        root = self.store.folder
        for dp, dns, fns in os.walk(root):
            dns[:] = [d for d in dns if d not in SKIP_DIRS and
                      not d.startswith(".")]
            for fn in fns:
                if fn.startswith((".", "~$")):
                    continue
                p = os.path.join(dp, fn)
                st = os.stat(p)
                self.files.append({
                    "name": os.path.relpath(p, root), "path": p,
                    "version": None, "by": "",
                    "at": datetime.fromtimestamp(st.st_mtime).isoformat(),
                    "size": st.st_size, "note": "", "lock": None})
        self.files.sort(key=lambda f: f["name"].lower())

    # ---------------------------------------------------------- actions
    def _cache(self, name, v):
        d = os.path.join(os.path.dirname(self.store.path), "docs", f"v{v}")
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, name)

    def open(self, row, version=None):
        if not 0 <= row < len(self.files):
            return
        f = self.files[row]
        if f.get("path"):
            return self._launch(f["path"])
        v = version or f["version"]
        dest = self._cache(f["name"], v)
        if os.path.exists(dest):
            return self._launch(dest)
        self._bg(lambda: self.store.client().download(
            self.store.data["hub"]["key"], self.store.data["hub"]["project"],
            f["name"], dest, version=v,
            progress=lambda a, b: self.sig.progress.emit(a, b)),
            lambda _r: self._launch(dest))

    def _launch(self, path):
        from .center import live_main
        mw = live_main(self.center)
        if path.lower().endswith(".pdf") and mw is not None:
            mw.open_path(path)
            mw.raise_()
            mw.activateWindow()
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def upload(self, paths=None):
        if not self.store.connected:
            QMessageBox.information(
                self, "Upload", "Share the project first (top right) - "
                "then uploads keep every version on the server. Until then"
                ", put files in the project folder.")
            return
        if not paths:
            paths, _ = QFileDialog.getOpenFileNames(self, "Upload files")
        if not paths:
            return
        note, ok = QInputDialog.getText(
            self, "Upload", "Note for this version (e.g. 'Addendum 2', "
            "'IFC set'):")
        if not ok:
            return
        h = self.store.data["hub"]
        current = {f["name"]: f for f in self.files}

        def work():
            out = []
            for p in paths:
                name = os.path.basename(p)
                base = current.get(name, {}).get("version")
                out.append(self.store.client().upload(
                    h["key"], h["project"], p, note=note,
                    base_version=base, force=True,
                    progress=lambda a, b: self.sig.progress.emit(a, b)))
            return out
        self._bg(work, lambda r: self.center.toast(
            f"Uploaded {len(r)} file(s)."))

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.upload([u.toLocalFile() for u in e.mimeData().urls()
                     if u.isLocalFile() and os.path.isfile(u.toLocalFile())])

    def _lock(self, row, on):
        f = self.files[row]
        h = self.store.data["hub"]
        try:
            self.store.client().call("proj.lock" if on else "proj.unlock",
                                     project=h["project"], key=h["key"],
                                     name=f["name"], user=self.store.me)
        except Exception as e:
            QMessageBox.warning(self, "Check out", str(e))
        self.refresh()

    def _checkin(self, row):
        f = self.files[row]
        path, _ = QFileDialog.getOpenFileName(
            self, f"New version of {f['name']}", self._cache(
                f["name"], f["version"]))
        if not path:
            return
        note, ok = QInputDialog.getText(self, "Check in", "What changed?")
        if not ok:
            return
        h = self.store.data["hub"]

        def work():
            r = self.store.client().upload(
                h["key"], h["project"], path, name=f["name"], note=note,
                base_version=f["version"])
            self.store.client().call("proj.unlock", project=h["project"],
                                     key=h["key"], name=f["name"],
                                     user=self.store.me)
            return r
        self._bg(work, lambda r: self.center.toast(
            f"{f['name']} is now v{r['version']}."))

    def _history(self, row):
        f = self.files[row]
        labels = [f"v{v['v']}  {show_date(v['at'][:10])}  {v['by']}  "
                  f"{v.get('note', '')}" for v in reversed(f["versions"])]
        pick, ok = QInputDialog.getItem(self, f["name"], "Open version:",
                                        labels, 0, False)
        if ok and pick:
            v = int(pick.split()[0][1:])
            self.open(row, v)

    def _menu(self, pos):
        row = self.table.rowAt(pos.y())
        if row < 0:
            return
        f = self.files[row]
        m = QMenu(self)
        m.addAction("Open", lambda: self.open(row))
        if self.store.connected and not f.get("path"):
            m.addAction("Open an older version…", lambda: self._history(row))
            lock = f.get("lock") or {}
            if not lock:
                m.addAction("Check out", lambda: self._lock(row, True))
            elif lock.get("user") == self.store.me:
                m.addAction("Check in new version…",
                            lambda: self._checkin(row))
                m.addAction("Undo check out", lambda: self._lock(row,
                                                                 False))
        m.exec(self.table.viewport().mapToGlobal(pos))

    # ---------------------------------------------------------- background
    def _bg(self, fn, then):
        self.bar.setVisible(True)
        self.bar.setRange(0, 0)

        def run():
            try:
                res = fn()
            except Exception as e:
                res = e
            try:
                self.sig.done.emit(res, then)
            except RuntimeError:          # the page was closed meanwhile
                logging.getLogger(__name__).info("result dropped",
                                                 exc_info=True)
        threading.Thread(target=run, daemon=True).start()

    def _progress(self, a, b):
        self.bar.setRange(0, max(b, 1))
        self.bar.setValue(a)

    def _done(self, res, then):
        self.bar.setVisible(False)
        if isinstance(res, Exception):
            QMessageBox.warning(self, "Documents", str(res))
            return
        then(res)
        self.refresh()
