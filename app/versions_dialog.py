import time
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QMessageBox, QInputDialog
)
from . import versions as versions_mod


class VersionsDialog(QDialog):
    """Lists saved revisions.

    get_bytes() returns the current document; on_load(data) opens a
    revision in the editor. Loading no longer overwrites the PDF on disk
    (the original did, with no backup); the person saves when ready.
    """

    def __init__(self, path, get_bytes=None, on_load=None, parent=None):
        super().__init__(parent)
        self.path = path
        self.get_bytes = get_bytes
        self.on_load = on_load
        self.setWindowTitle("Version History")
        self.resize(520, 420)
        layout = QVBoxLayout(self)

        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda _: self._load())
        layout.addWidget(self.list)
        self._reload()

        btns = QHBoxLayout()
        save = QPushButton("Save Revision…")
        save.clicked.connect(self._save)
        save.setEnabled(get_bytes is not None)
        load = QPushButton("Open")
        load.clicked.connect(self._load)
        load.setEnabled(on_load is not None)
        branch = QPushButton("Branch…")
        branch.clicked.connect(self._branch)
        btns.addWidget(save)
        btns.addWidget(load)
        btns.addWidget(branch)
        layout.addLayout(btns)

        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        layout.addWidget(close)

    def _reload(self):
        self.list.clear()
        for r in reversed(versions_mod.list_revisions(self.path)):
            ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(r.get("ts", 0)))
            size = r.get("size", 0) / 1024
            it = QListWidgetItem(f"{ts}   {r.get('label')}   "
                                 f"[{r.get('branch')}]   {size:.0f} KB")
            it.setData(Qt.UserRole, r.get("id"))
            self.list.addItem(it)

    def _save(self):
        label, ok = QInputDialog.getText(self, "Revision", "Label:",
                                         text="manual")
        if ok:
            versions_mod.save_revision(self.path, self.get_bytes(),
                                       label=label or "manual")
            self._reload()

    def _selected(self):
        it = self.list.currentItem()
        return it.data(Qt.UserRole) if it else None

    def _load(self):
        rid = self._selected()
        if not rid:
            return
        try:
            data = versions_mod.load_revision(self.path, rid)
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "Versions", f"Could not open: {e}")
            return
        if data and self.on_load:
            self.on_load(data)
            self.accept()

    def _branch(self):
        rid = self._selected()
        if not rid:
            return
        name, ok = QInputDialog.getText(self, "Branch", "Branch name:")
        if ok and name:
            data = versions_mod.load_revision(self.path, rid)
            if data:
                versions_mod.save_revision(self.path, data, label="branch",
                                           branch=name)
                self._reload()
