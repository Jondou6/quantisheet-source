"""Send with QuantiLink (Home tab, Jon Nov 23): pick a job's RFIs,
submittals, daily logs or meeting minutes, send them to the office's
QuantiLink server, and get share links back to paste into an email.
The work is in quantilink.py (no Qt)."""
import threading

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QFormLayout, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QPlainTextEdit,
                               QPushButton, QSpinBox, QVBoxLayout)

from . import quantilink as ql


# ------------------------------------------------------------ connection
class ConnectionDialog(QDialog):
    """The office's QuantiLink server, its shared key, and the folder the
    files go to. When IT set the server and key, only the folder can be
    picked here."""

    def __init__(self, parent=None, opener=None):
        super().__init__(parent)
        self.opener = opener
        self.setWindowTitle("QuantiLink Connection")
        self.resize(520, 260)
        c = ql.connection()
        self.it = c["it"]
        v = QVBoxLayout(self)
        note = QLabel("The office's QuantiLink server and its shared access "
                      "key (made in QuantiLink under Account settings > "
                      "Desktop sync). The key is kept encrypted for this "
                      "Windows user." if not self.it else
                      "Your IT department set the QuantiLink server and "
                      "key for this PC.")
        note.setWordWrap(True)
        v.addWidget(note)
        f = QFormLayout()
        self.url = QLineEdit(c["url"])
        self.url.setPlaceholderText("https://files.yourcompany.com")
        self.key = QLineEdit(c["key"] if not self.it else "")
        self.key.setEchoMode(QLineEdit.Password)
        self.key.setPlaceholderText("qlt_..." if not self.it
                                    else "set by your IT department")
        self.url.setReadOnly(self.it)
        self.key.setReadOnly(self.it)
        f.addRow("Server", self.url)
        f.addRow("Access key", self.key)
        row = QHBoxLayout()
        self.space = QComboBox()
        if c["space"].get("id"):
            self.space.addItem(c["space"].get("name") or "folder",
                               c["space"])
        row.addWidget(self.space, 1)
        self.load_btn = QPushButton("Load Folders")
        self.load_btn.clicked.connect(lambda: self.load())
        row.addWidget(self.load_btn)
        f.addRow("Send to", row)
        v.addLayout(f)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        v.addWidget(self.status)
        bb = QDialogButtonBox(QDialogButtonBox.Save |
                              QDialogButtonBox.Cancel)
        bb.accepted.connect(self.save)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def client(self):
        c = ql.connection()
        url = c["url"] if self.it else self.url.text()
        key = c["key"] if self.it else self.key.text()
        return ql.Client(url, key, opener=self.opener)

    def load(self):
        """Ask the server which folders the key can send to."""
        try:
            spaces = self.client().spaces()
        except Exception as e:                            # noqa: BLE001
            self.status.setText(str(e))
            return []
        keep = self.space.currentData() or {}
        self.space.clear()
        for s in spaces:
            if s["role"].lower() in ("viewer", "view"):
                continue
            name = ("My Files" if s["personal"] else s["name"]) + (
                f"  ({s['role']})" if s["role"] else "")
            self.space.addItem(name, {"id": s["id"], "name": name})
            if s["id"] == keep.get("id"):
                self.space.setCurrentIndex(self.space.count() - 1)
        self.status.setText(f"Connected. {self.space.count()} folder(s) "
                            "you can send to." if self.space.count() else
                            "Connected, but this key can't add files to "
                            "any folder.")
        return spaces

    def save(self):
        try:
            if not self.it:
                ql.save_connection(url=self.url.text(), key=self.key.text())
            ql.save_connection(space=self.space.currentData() or {})
        except ql.QuantiLinkError as e:
            self.status.setText(str(e))
            return
        self.accept()


# ------------------------------------------------------------------ send
class SendDialog(QDialog):
    def __init__(self, parent=None, store=None, opener=None):
        super().__init__(parent)
        self.win = parent
        self.store = store
        self.opener = opener
        self.results = []
        self._job = None
        self.setWindowTitle("Send with QuantiLink")
        self.resize(720, 640)
        v = QVBoxLayout(self)
        top = QHBoxLayout()
        self.project = QLabel("")
        top.addWidget(self.project, 1)
        pick = QPushButton("Other Project…")
        pick.clicked.connect(self.pick_project)
        top.addWidget(pick)
        v.addLayout(top)
        f = QFormLayout()
        self.kind = QComboBox()
        for k, label in ql.KINDS.items():
            self.kind.addItem(label, k)
        self.kind.currentIndexChanged.connect(lambda _i: self.fill())
        f.addRow("Send", self.kind)
        v.addLayout(f)
        self.list = QListWidget()
        v.addWidget(self.list, 2)
        sel = QHBoxLayout()
        for text, on in (("Tick All", True), ("Clear", False)):
            b = QPushButton(text)
            b.clicked.connect(lambda _c=False, on=on: self.tick_all(on))
            sel.addWidget(b)
        sel.addStretch(1)
        self.attach = QCheckBox("Include attachments")
        self.attach.setChecked(True)
        sel.addWidget(self.attach)
        sel.addWidget(QLabel("Links work for"))
        self.days = QSpinBox()
        self.days.setRange(1, 365)
        self.days.setSuffix(" days")
        self.days.setValue(ql.connection()["days"])
        sel.addWidget(self.days)
        v.addLayout(sel)
        conn = QHBoxLayout()
        self.where = QLabel("")
        self.where.setWordWrap(True)
        conn.addWidget(self.where, 1)
        cb = QPushButton("Connection…")
        cb.clicked.connect(self.edit_connection)
        conn.addWidget(cb)
        v.addLayout(conn)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        v.addWidget(self.status)
        self.out = QPlainTextEdit()
        self.out.setReadOnly(True)
        self.out.setPlaceholderText("The share links appear here, ready to "
                                    "paste into an email.")
        v.addWidget(self.out, 1)
        bb = QDialogButtonBox()
        self.send_btn = bb.addButton("Send", QDialogButtonBox.AcceptRole)
        self.copy_btn = bb.addButton("Copy Links",
                                     QDialogButtonBox.ActionRole)
        self.copy_btn.setEnabled(False)
        bb.addButton(QDialogButtonBox.Close)
        self.send_btn.clicked.connect(lambda: self.send())
        self.copy_btn.clicked.connect(self.copy)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self._timer = QTimer(self)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self._poll)
        self.show_connection()
        self.fill()

    # ---- what to send
    def pick_project(self):
        if self.win is not None and hasattr(self.win, "_job_store"):
            st = self.win._job_store(pick=True, title="Send with QuantiLink")
            if st is not None:
                self.store = st
                self.fill()

    def fill(self):
        self.list.clear()
        if self.store is None:
            self.project.setText("<b>No project.</b> Open a drawing from a "
                                 "Project Center job, or pick one.")
            return
        self.project.setText(f"<b>Project:</b> {self.store.name}")
        kind = self.kind.currentData()
        recs = [r for r in self.store.list(kind)]
        recs.sort(key=lambda r: str(r.get("_no") or ""), reverse=True)
        for r in recs:
            text = ql.record_label(kind, r)
            st = r.get("status")
            if st:
                text += f"   [{st}]"
            it = QListWidgetItem(text)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Unchecked)
            it.setData(Qt.UserRole, r)
            self.list.addItem(it)
        if not recs:
            self.list.addItem(QListWidgetItem(
                f"No {self.kind.currentText().lower()} in this project."))

    def tick_all(self, on):
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.data(Qt.UserRole) is not None:
                it.setCheckState(Qt.Checked if on else Qt.Unchecked)

    def chosen(self):
        return [self.list.item(i).data(Qt.UserRole)
                for i in range(self.list.count())
                if self.list.item(i).data(Qt.UserRole) is not None and
                self.list.item(i).checkState() == Qt.Checked]

    # ---- connection
    def show_connection(self):
        c = ql.connection()
        if not c["url"] or not c["key"]:
            self.where.setText("QuantiLink isn't set up on this PC yet: "
                               "click Connection… and paste the office's "
                               "server and key.")
        elif not c["space"].get("id"):
            self.where.setText(f"QuantiLink: {c['url']} - pick the folder "
                               "to send to in Connection….")
        else:
            self.where.setText(f"QuantiLink: {c['url']}  ->  "
                               f"{c['space'].get('name')}")

    def edit_connection(self):
        d = ConnectionDialog(self, opener=self.opener)
        if d.exec():
            self.show_connection()

    # ---- send
    def send(self, wait=False):
        recs = self.chosen()
        if self.store is None or not recs:
            self.status.setText("Tick what to send first.")
            return None
        c = ql.connection()
        if not (c["url"] and c["key"] and c["space"].get("id")):
            self.status.setText("Set up the connection first "
                                "(Connection…).")
            return None
        try:
            client = ql.Client(c["url"], c["key"], opener=self.opener)
        except Exception as e:                            # noqa: BLE001
            self.status.setText(str(e))
            return None
        kind = self.kind.currentData()
        days = self.days.value()
        ql.save_connection(days=days)
        items = ql.gather(self.store, kind, recs, self.attach.isChecked())
        state = {"i": 0, "n": len(items), "name": "", "done": None}
        self._job = state

        def progress(i, n, name):
            state.update(i=i, n=n, name=name)

        def work():
            try:
                done = ql.send(client, c["space"]["id"], self.store.name,
                               kind, items, days, progress)
            except Exception as e:                        # noqa: BLE001
                done = [{"name": "", "error": str(e)}]
            ql.cleanup(items)
            state["done"] = done
        self.send_btn.setEnabled(False)
        self.status.setText(f"Sending {len(items)} file(s)…")
        if wait:
            work()
            self._finish()
            return self.results
        threading.Thread(target=work, daemon=True).start()
        self._timer.start()
        return None

    def _poll(self):
        st = self._job
        if st is None:
            self._timer.stop()
            return
        if st["done"] is None:
            self.status.setText(f"Sending {min(st['i'] + 1, st['n'])} of "
                                f"{st['n']}: {st['name']}")
            return
        self._timer.stop()
        self._finish()

    def _finish(self):
        st, self._job = self._job, None
        self.results = st["done"] if st else []
        days = self.days.value()
        ok = [r for r in self.results if r.get("link")]
        bad = [r for r in self.results if r.get("error")]
        text = ql.links_text(self.results, days)
        if bad:
            text += ("\n\n" if text else "") + "Not sent:\n" + "\n".join(
                f"{r['name']}: {r['error']}" for r in bad)
        self.out.setPlainText(text)
        self.copy_btn.setEnabled(bool(ok))
        self.send_btn.setEnabled(True)
        self.status.setText(f"Sent {len(ok)} file(s)" + (
            f"; {len(bad)} not sent." if bad else ". Copy the links into "
            "your email."))

    def copy(self):
        text = ql.links_text(self.results, self.days.value())
        if text:
            QGuiApplication.clipboard().setText(text)
            self.status.setText("Links copied.")


def project_name(win, doc=None):
    """The job's name when the drawing is in a Project Center job, else
    the drawing's file name."""
    import os
    try:
        st = win._job_store() if win is not None and \
            hasattr(win, "_job_store") else None
    except Exception:                                     # noqa: BLE001
        st = None
    if st is not None:
        return st.name
    name = os.path.basename(getattr(doc, "name", "") or "") if doc else ""
    return os.path.splitext(name)[0] or "QuantiSheet"


class LinkDialog(QDialog):
    """The share link for one sent file, with Copy."""

    def __init__(self, parent, result, days):
        super().__init__(parent)
        self.setWindowTitle("Sent with QuantiLink")
        self.resize(560, 200)
        v = QVBoxLayout(self)
        self.text = ql.links_text([result], days) if result.get("link") \
            else f"Not sent: {result.get('error')}"
        lab = QLabel(("Sent. Paste this into your email:" if
                      result.get("link") else "Couldn't send the file."))
        v.addWidget(lab)
        box = QPlainTextEdit(self.text)
        box.setReadOnly(True)
        v.addWidget(box)
        bb = QDialogButtonBox()
        if result.get("link"):
            cp = bb.addButton("Copy Link", QDialogButtonBox.ActionRole)
            cp.clicked.connect(lambda: QGuiApplication.clipboard().setText(
                self.text))
        bb.addButton(QDialogButtonBox.Close).clicked.connect(self.reject)
        v.addWidget(bb)


def send_saved_file(parent, save, folder, project, show=True, opener=None,
                    days=None):
    """Export windows (Jon, Nov 24: 'Export windows'): save(path) writes the
    export to a temp file, which goes to <project>/<folder> on QuantiLink;
    the link is shown with Copy. Returns the result dict, or None when
    nothing was sent (QuantiLink off, not set up, nothing saved)."""
    import os
    import shutil
    import tempfile
    from . import policy
    if not policy.allowed("quantilink"):
        return None
    c = ql.connection()
    if not (c["url"] and c["key"] and c["space"].get("id")):
        if not show:
            return None
        d = ConnectionDialog(parent, opener=opener)
        if not d.exec():
            return None
        c = ql.connection()
        if not (c["url"] and c["key"] and c["space"].get("id")):
            return None
    days = days or c["days"]
    tmp = tempfile.mkdtemp(prefix="quantisheet-")
    try:
        path = save(tmp)
        if not path or not os.path.isfile(path):
            return None
        try:
            QGuiApplication.setOverrideCursor(Qt.WaitCursor)
            client = ql.Client(c["url"], c["key"], opener=opener)
            res = ql.send_file(client, c["space"]["id"], project, folder,
                               path, days)
        except Exception as e:                            # noqa: BLE001
            res = {"name": os.path.basename(path), "error": str(e)}
        finally:
            QGuiApplication.restoreOverrideCursor()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if show:
        LinkDialog(parent, res, days).exec()
    return res


def add_send_button(layout, parent, choices, folder, project_fn,
                    before=None):
    """A 'Send with QuantiLink' button in an export window's button row
    (hidden when IT turned QuantiLink off). choices: [(label, save)] -
    one choice sends at once, several open a small menu (PDF / Excel)."""
    from PySide6.QtWidgets import QMenu
    from . import policy
    if not policy.allowed("quantilink"):
        return None
    b = QPushButton("Send with QuantiLink…")
    b.setToolTip("Save this export and send it to your office's QuantiLink "
                 "server, with a share link back for an email")

    def go(save):
        return send_saved_file(parent, save, folder, project_fn())
    if len(choices) == 1:
        b.clicked.connect(lambda: go(choices[0][1]))
    else:
        m = QMenu(b)
        for label, save in choices:
            m.addAction(label, lambda s=save: go(s))
        b.setMenu(m)
    if before is None:
        layout.addWidget(b)
    else:
        layout.insertWidget(before, b)
    return b


def open_send(win, store=None, show=True, opener=None):
    from . import policy
    if not policy.allowed("quantilink"):
        if show:
            QMessageBox.information(win, "Send with QuantiLink",
                                    "Your IT department turned QuantiLink "
                                    "off on this PC.")
        return None
    d = SendDialog(win, store, opener=opener)
    if show:
        d.setAttribute(Qt.WA_DeleteOnClose)
        d.show()
    return d
