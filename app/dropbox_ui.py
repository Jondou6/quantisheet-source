"""File > Open from Dropbox… / Save to Dropbox / Save to Dropbox As… /
Dropbox Settings… (the logic is in dropbox_sync.py).

Hook (main_window.py, _build_menus, after Save As…):
    from . import dropbox_ui
    dropbox_ui.add_actions(self, f)

Everything here starts from a user's command: no network use at start-up
and no polling. Network work runs in a thread behind a progress box with
Cancel. When IT turns Dropbox off (policy DisableDropbox / OfflineMode)
the commands are hidden, and refuse if reached another way.
"""
import logging
import os
import threading

from PySide6.QtCore import QEventLoop, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QComboBox,
                               QDialog, QDialogButtonBox, QFormLayout,
                               QHBoxLayout, QHeaderView, QInputDialog,
                               QLabel, QLineEdit, QMessageBox, QPushButton,
                               QProgressDialog, QRadioButton, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QFileDialog)

from . import dropbox_sync as dbx
from . import settings

log = logging.getLogger(__name__)

TITLE = "Dropbox"
OPEN_TEXT = "Open from Dropbox…"
SAVE_TEXT = "Save to Dropbox"
SAVE_AS_TEXT = "Save to Dropbox As…"
SETTINGS_TEXT = "Dropbox Settings…"
SIGNIN_WAIT_S = 600


# ---- menu ---------------------------------------------------------------------------
def add_actions(win, menu):
    """The four File menu commands. Hidden when IT turned Dropbox off.
    Returns {text: QAction}."""
    out = {}
    menu.addSeparator()
    for text, fn, needs_doc in (
            (OPEN_TEXT, open_from_dropbox, False),
            (SAVE_TEXT, save_to_dropbox, True),
            (SAVE_AS_TEXT, save_to_dropbox_as, False),
            (SETTINGS_TEXT, dropbox_settings, False)):
        a = QAction(text, win)
        a.triggered.connect(lambda _c=False, fn=fn: fn(win))
        menu.addAction(a)
        if needs_doc and isinstance(getattr(win, "_doc_actions", None),
                                    list):
            win._doc_actions.append(a)
        out[text] = a
    sep = menu.addSeparator()
    on = dbx.allowed()
    for a in list(out.values()) + [sep]:
        a.setVisible(on)
    if not on:
        for a in out.values():
            a.setEnabled(False)
    win._dropbox_actions = out
    return out


# ---- small helpers --------------------------------------------------------------------
def _say(parent, text, icon=QMessageBox.Information):
    box = QMessageBox(icon, TITLE, text, QMessageBox.Ok, parent)
    box.exec()


def _fail(parent, e):
    from . import policy
    if isinstance(e, (dbx.DropboxError, policy.Blocked)):
        msg = str(e)
    else:
        log.warning("Dropbox command failed", exc_info=True)
        msg = f"Something went wrong ({type(e).__name__}). Try again."
    _say(parent, msg, QMessageBox.Warning)


def _flash(win, text):
    f = getattr(win, "_flash", None)
    if callable(f):
        f(text, 8000)


def _mb(n):
    return f"{n / 1048576:.1f} MB"


def _blocked(parent):
    if dbx.allowed():
        return False
    from . import policy
    try:
        dbx.check_allowed()
    except policy.Blocked as e:
        _say(parent, str(e), QMessageBox.Warning)
    return True


def run(parent, label, fn, delay_ms=300):
    """fn(progress, cancel) in a thread behind a progress box (Cancel
    sets cancel()). Returns fn's result or raises its exception."""
    st = {"done": False, "result": None, "error": None, "cancel": False,
          "p": (0, 0)}

    def body():
        try:
            st["result"] = fn(lambda d, t: st.__setitem__("p", (d, t)),
                              lambda: st["cancel"])
        except BaseException as e:                        # noqa: BLE001
            st["error"] = e
        finally:
            st["done"] = True

    t = threading.Thread(target=body, daemon=True, name="dropbox")
    t.start()
    dlg = QProgressDialog(label, "Cancel", 0, 0, parent)
    dlg.setWindowTitle(TITLE)
    dlg.setWindowModality(Qt.WindowModal)
    dlg.setMinimumDuration(delay_ms)
    dlg.setAutoClose(False)
    dlg.setAutoReset(False)
    dlg.setValue(0)
    loop = QEventLoop()
    timer = QTimer()
    timer.setInterval(50)

    def tick():
        if dlg.wasCanceled() and not st["cancel"]:
            st["cancel"] = True
            dlg.setLabelText("Cancelling…")
        d, tot = st["p"]
        if tot > 0 and not st["cancel"]:
            dlg.setMaximum(1000)
            dlg.setValue(min(1000, int(1000 * d / tot)))
            dlg.setLabelText(f"{label}\n{_mb(d)} of {_mb(tot)}")
        elif dlg.maximum() == 0:
            dlg.setValue(0)
        if st["done"]:
            loop.quit()

    timer.timeout.connect(tick)
    timer.start()
    if not st["done"]:
        loop.exec()
    timer.stop()
    dlg.close()
    dlg.deleteLater()
    t.join(1)
    if st["error"] is not None:
        raise st["error"]
    return st["result"]


# ---- setup screen (no App key yet) ------------------------------------------------------
class SetupDialog(QDialog):
    """How to register the company's free Dropbox app, and a field for
    its App key."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Set Up Dropbox")
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        head = QLabel("<b>Connect QuantiSheet to Dropbox</b>")
        lay.addWidget(head)
        intro = QLabel(
            "QuantiSheet works with Dropbox through a small Dropbox app that "
            "your company registers once (it's free). Everyone then uses "
            "the same App key and signs in with their own Dropbox account.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        uri = dbx.redirect_uri()
        self.steps = QLabel(
            "<ol style='margin-left:-20px'>"
            f"<li>Go to <a href='{dbx.APPS_URL}'>dropbox.com/developers/"
            "apps</a> → <b>Create app</b> → <b>Scoped access</b> → "
            "<b>Full Dropbox</b>, and give it a name.</li>"
            "<li><b>Permissions</b> tab: tick <b>files.metadata.read</b>, "
            "<b>files.content.read</b> and <b>files.content.write</b>, "
            "then click <b>Submit</b>.</li>"
            "<li>Copy the <b>App key</b> (Settings tab) and paste it "
            "below.</li>"
            "<li>Settings tab, <b>OAuth 2 → Redirect URIs</b>: add exactly "
            f"<b>{uri}</b> and click Add. Leave <b>Allow public clients "
            "(Implicit Grant &amp; PKCE)</b> on Allow.</li></ol>")
        self.steps.setWordWrap(True)
        self.steps.setTextFormat(Qt.RichText)
        self.steps.setOpenExternalLinks(True)
        lay.addWidget(self.steps)
        row = QHBoxLayout()
        row.addWidget(QLabel("Redirect URI:"))
        uri_box = QLineEdit(uri)
        uri_box.setReadOnly(True)
        row.addWidget(uri_box, 1)
        copy = QPushButton("Copy")
        copy.clicked.connect(lambda _c=False: _copy(uri))
        row.addWidget(copy)
        lay.addLayout(row)
        form = QFormLayout()
        self.key = QLineEdit(dbx.app_key())
        self.key.setPlaceholderText("e.g. a1b2c3d4e5f6g7h")
        form.addRow("App key:", self.key)
        lay.addLayout(form)
        if dbx.app_key_from_policy():
            self.key.setReadOnly(True)
            pol = QLabel("Set by your IT department.")
            pol.setObjectName("StartTip")
            lay.addWidget(pol)
        note = QLabel("The App secret is <b>not</b> needed. Don't paste it "
                      "into QuantiSheet (or anywhere else).")
        note.setWordWrap(True)
        note.setObjectName("StartTip")
        lay.addWidget(note)
        self.error = QLabel("")
        self.error.setWordWrap(True)
        lay.addWidget(self.error)
        self.error.hide()
        bb = QDialogButtonBox(QDialogButtonBox.Save |
                              QDialogButtonBox.Cancel)
        web = bb.addButton("Open Dropbox Developers",
                           QDialogButtonBox.HelpRole)
        web.clicked.connect(lambda _c=False: _open_url(dbx.APPS_URL))
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _save(self):
        k = self.key.text().strip()
        if not dbx.valid_app_key(k):
            self.error.setText("That doesn't look like an App key (letters "
                               "and digits, from the app's Settings tab).")
            self.error.show()
            return
        if not dbx.app_key_from_policy():
            dbx.set_app_key(k)
        self.accept()


def setup_screen(parent):
    """Shows the setup screen; returns the App key, or "" if cancelled."""
    d = SetupDialog(parent)
    if not d.exec():
        return ""
    return dbx.app_key()


def _copy(text):
    cb = QGuiApplication.clipboard()
    if cb is not None:
        cb.setText(text)


def _open_url(url):
    QDesktopServices.openUrl(QUrl.fromEncoded(url.encode("ascii")))


# ---- sign-in ------------------------------------------------------------------------------
class _WaitDialog(QDialog):
    def __init__(self, parent, receiver):
        super().__init__(parent)
        self.receiver = receiver
        self.use_code = False
        self.setWindowTitle("Sign In to Dropbox")
        lay = QVBoxLayout(self)
        lab = QLabel("Your browser opened Dropbox. Sign in there and click "
                     "<b>Allow</b>; this box closes by itself.<br><br>"
                     "If the browser says the redirect URI isn't allowed, "
                     "add <b>" + receiver.redirect + "</b> in the Dropbox "
                     "app's Settings tab (Redirect URIs), or use a code "
                     "instead.")
        lab.setWordWrap(True)
        lay.addWidget(lab)
        bb = QDialogButtonBox(QDialogButtonBox.Cancel)
        code = bb.addButton("Use a Code Instead", QDialogButtonBox.ActionRole)
        code.clicked.connect(lambda _c=False: self._code())
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.timer = QTimer(self)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self._poll)
        self.timer.start()
        QTimer.singleShot(SIGNIN_WAIT_S * 1000, self.reject)

    def _poll(self):
        if self.receiver.done.is_set():
            self.timer.stop()
            self.accept()

    def _code(self):
        self.use_code = True
        self.reject()


def sign_in(parent, key):
    """Browser sign-in (PKCE, loopback redirect; Dropbox's copy-a-code page
    if the loopback port can't be used). Returns a signed-in Client, or
    None."""
    if QMessageBox.question(
            parent, TITLE,
            "QuantiSheet will open Dropbox in your web browser so you can "
            "sign in and allow access to your files. Continue?") != \
            QMessageBox.Yes:
        return None
    client = dbx.Client(key, tokens={})
    verifier, challenge = dbx.pkce_pair()
    state = dbx.new_state()
    rec = dbx.LoopbackReceiver(state)
    try:
        rec.start()
    except OSError:
        log.info("sign-in port %s not available; using a code", rec.port)
        rec = None
    if rec is None:
        return _sign_in_with_code(parent, client)
    redirect = rec.redirect
    try:
        _open_url(dbx.authorize_url(key, challenge, state, redirect))
        w = _WaitDialog(parent, rec)
        w.exec()
        code, err = rec.code, rec.error
    finally:
        rec.close()
    if w.use_code:
        return _sign_in_with_code(parent, client)
    if err:
        _say(parent, "Dropbox sign-in was cancelled.")
        return None
    if not code:
        return None
    return _finish(parent, client, code, verifier, redirect)


def _sign_in_with_code(parent, client):
    verifier, challenge = dbx.pkce_pair()
    _open_url(dbx.authorize_url(client.key, challenge))
    code, ok = QInputDialog.getText(
        parent, "Sign In to Dropbox",
        "Your browser opened Dropbox. Sign in, click Allow, then copy the "
        "code Dropbox shows and paste it here:",
        QLineEdit.EchoMode.Password)
    if not ok or not code.strip():
        return None
    return _finish(parent, client, code.strip(), verifier, None)


def _finish(parent, client, code, verifier, redirect):
    def work(_p, _c):
        client.exchange_code(code, verifier, redirect)
        try:
            client.current_account()
        except dbx.DropboxError:
            log.info("signed in; the account name wasn't read")
        return client
    try:
        run(parent, "Signing in to Dropbox…", work)
    except Exception as e:                                # noqa: BLE001
        _fail(parent, e)
        return None
    who = client.tokens.get("name") or "your account"
    _flash(parent, f"Signed in to Dropbox as {who}")
    return client


def ensure_client(win):
    """A signed-in Client, after the setup screen and the sign-in when
    needed; None if the user stopped (or IT turned Dropbox off)."""
    if _blocked(win):
        return None
    key = dbx.app_key()
    if not key:
        key = setup_screen(win)
        if not key:
            return None
    c = dbx.Client(key)
    if c.tokens.get("refresh_token"):
        return c
    return sign_in(win, key)


# ---- browsing Dropbox -----------------------------------------------------------------
class DropboxBrowser(QDialog):
    """Pick PDFs to open (mode "open") or a folder and name to save in
    (mode "folder")."""

    def __init__(self, parent, client, mode="open", start="", name=""):
        super().__init__(parent)
        self.client = client
        self.mode = mode
        self.folder = None
        self.selected = []
        self.target = ""
        self.setWindowTitle(OPEN_TEXT.rstrip("…") if mode == "open" else
                            "Save to Dropbox")
        self.resize(720, 480)
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.up = QPushButton("Up")
        self.up.clicked.connect(lambda _c=False: self._go_up())
        top.addWidget(self.up)
        self.where = QLabel("")
        top.addWidget(self.where, 1)
        if mode == "folder":
            new = QPushButton("New Folder…")
            new.clicked.connect(lambda _c=False: self._new_folder())
            top.addWidget(new)
        ref = QPushButton("Refresh")
        ref.clicked.connect(lambda _c=False: self.load(self.folder or ""))
        top.addWidget(ref)
        lay.addLayout(top)
        self.list = QTreeWidget()
        self.list.setHeaderLabels(["Name", "Modified", "Size"])
        self.list.setRootIsDecorated(False)
        self.list.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.list.setSelectionMode(
            QAbstractItemView.ExtendedSelection if mode == "open" else
            QAbstractItemView.SingleSelection)
        self.list.itemDoubleClicked.connect(self._double)
        lay.addWidget(self.list, 1)
        self.name = None
        if mode == "folder":
            form = QFormLayout()
            self.name = QLineEdit(name)
            form.addRow("File name:", self.name)
            lay.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.ok = bb.addButton("Open" if mode == "open" else "Save Here",
                               QDialogButtonBox.AcceptRole)
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._start = dbx.normalize(start)

    def exec(self):
        if not self.load(self._start) and self._start:
            if not self.load(""):
                return 0
        elif self.folder is None:
            return 0
        return super().exec()

    def load(self, folder):
        folder = dbx.normalize(folder)
        try:
            entries = run(self.parentWidget() if not self.isVisible()
                          else self, "Reading Dropbox…",
                          lambda _p, _c: self.client.list_folder(folder))
        except Exception as e:                            # noqa: BLE001
            _fail(self.parentWidget() if not self.isVisible() else self, e)
            return False
        self.folder = folder
        self.where.setText("Dropbox" + (folder.replace("/", "  ›  ")
                                        if folder else ""))
        self.up.setEnabled(bool(folder))
        self.list.clear()
        folders = sorted((e for e in entries if e.get(".tag") == "folder"),
                         key=lambda e: e.get("name", "").lower())
        files = sorted((e for e in entries if e.get(".tag") == "file" and
                        (self.mode != "open" or
                         e.get("name", "").lower().endswith(".pdf"))),
                       key=lambda e: e.get("name", "").lower())
        for e in folders + files:
            is_dir = e.get(".tag") == "folder"
            it = QTreeWidgetItem([
                ("📁 " if is_dir else "") + e.get("name", ""),
                (e.get("server_modified") or "").replace("T", " ")
                .rstrip("Z")[:16],
                "" if is_dir else _mb(int(e.get("size") or 0))])
            it.setData(0, Qt.UserRole, e)
            if not is_dir and self.mode == "folder":
                it.setFlags(it.flags() & ~Qt.ItemIsSelectable)
            self.list.addTopLevelItem(it)
        return True

    def _entry(self, it):
        return it.data(0, Qt.UserRole) if it is not None else None

    def _double(self, it, _col=0):
        e = self._entry(it)
        if not e:
            return
        if e.get(".tag") == "folder":
            self.load(e.get("path_display") or e.get("path_lower"))
        elif self.mode == "open":
            self.selected = [e.get("path_display") or e.get("path_lower")]
            self.accept()
        elif self.name is not None:
            self.name.setText(e.get("name", ""))

    def _go_up(self):
        self.load(dbx.parent(self.folder or ""))

    def _new_folder(self):
        name, ok = QInputDialog.getText(self, "New Folder", "Folder name:")
        name = (name or "").strip().strip("/")
        if not ok or not name:
            return
        path = dbx.join(self.folder or "", name)
        try:
            run(self, "Making the folder…",
                lambda _p, _c: self.client.create_folder(path))
        except Exception as e:                            # noqa: BLE001
            _fail(self, e)
            return
        self.load(path)

    def _accept(self):
        items = self.list.selectedItems()
        if self.mode == "open":
            ents = [self._entry(i) for i in items]
            dirs = [e for e in ents if e and e.get(".tag") == "folder"]
            if len(ents) == 1 and dirs:
                self.load(dirs[0].get("path_display"))
                return
            self.selected = [e.get("path_display") or e.get("path_lower")
                             for e in ents if e and e.get(".tag") == "file"]
            if not self.selected:
                _say(self, "Pick one or more PDFs (Ctrl+click for several).")
                return
            settings.set("dropbox_last_folder", self.folder or "")
            self.accept()
            return
        folder = self.folder or ""
        e = self._entry(items[0]) if items else None
        if e and e.get(".tag") == "folder":
            folder = e.get("path_display") or folder
        name = (self.name.text() if self.name else "").strip()
        if not name or "/" in name or "\\" in name:
            _say(self, "Type a file name (no / or \\).")
            return
        self.target = dbx.join(folder, name)
        settings.set("dropbox_last_folder", folder)
        self.accept()


def _start_folder():
    return dbx.normalize(settings.get("dropbox_last_folder") or
                         dbx.default_folder())


# ---- Open from Dropbox ------------------------------------------------------------------
def _tab_index(win, local):
    tabs = getattr(win, "tabs", None)
    if tabs is None:
        return None
    for i in range(tabs.count()):
        p = getattr(tabs.widget(i), "path", None)
        if p and os.path.normcase(os.path.abspath(p)) == \
                os.path.normcase(os.path.abspath(local)):
            return i
    return None


def open_from_dropbox(win):
    client = ensure_client(win)
    if client is None:
        return []
    b = DropboxBrowser(win, client, "open", _start_folder())
    if not b.exec():
        return []
    opened = []
    for path in b.selected:
        local = dbx.local_path_for(path)
        i = _tab_index(win, local)
        if i is not None:
            if QMessageBox.question(
                    win, TITLE, f"{dbx.basename(path)} is already open. Close "
                    "it and get the version in Dropbox?") != QMessageBox.Yes:
                win.tabs.setCurrentIndex(i)
                continue
            if not win.close_tab(i):
                continue
        try:
            run(win, f"Downloading {dbx.basename(path)}…",
                lambda p, c, path=path: dbx.fetch(client, path, p, c))
        except dbx.LocalChanges as e:
            box = QMessageBox(QMessageBox.Question, TITLE,
                              f"{e}\n\nOpen your copy, or replace it with "
                              "the version in Dropbox (your changes are "
                              "lost)?", parent=win)
            keep = box.addButton("Open My Copy", QMessageBox.AcceptRole)
            repl = box.addButton("Replace With Dropbox's",
                                 QMessageBox.DestructiveRole)
            box.addButton(QMessageBox.Cancel)
            box.exec()
            if box.clickedButton() is repl:
                try:
                    run(win, f"Downloading {dbx.basename(path)}…",
                        lambda p, c, path=path: dbx.fetch(
                            client, path, p, c, replace_local=True))
                except Exception as e2:                   # noqa: BLE001
                    _fail(win, e2)
                    continue
            elif box.clickedButton() is not keep:
                continue
        except dbx.Cancelled:
            continue
        except Exception as e:                            # noqa: BLE001
            _fail(win, e)
            continue
        if win.open_path(local):
            opened.append(local)
    if opened:
        _flash(win, f"Opened from Dropbox: {len(opened)} file(s)")
    return opened


# ---- Save to Dropbox ---------------------------------------------------------------------
def _save_open_doc(win):
    """Save the open drawing locally first. Returns its path or None."""
    if getattr(win, "_view", None) is None:
        return None
    if getattr(win._view, "dirty", False) or not win._path:
        if not win.save_file():
            return None
    return win._path


def _conflict_choice(parent, name, remote):
    who = ""
    if remote:
        when = (remote.get("server_modified") or "").replace("T", " ")
        who = f" (saved {when.rstrip('Z')[:16]} UTC)" if when else ""
    box = QMessageBox(QMessageBox.Warning, TITLE,
                      f"Someone changed {name} in Dropbox{who} since you "
                      "opened it. Nothing was overwritten.\n\nOverwrite "
                      "their version with yours, save yours as a copy next "
                      "to it, or cancel?", parent=parent)
    over = box.addButton("Overwrite", QMessageBox.DestructiveRole)
    copy = box.addButton("Save as a Copy", QMessageBox.AcceptRole)
    box.addButton(QMessageBox.Cancel)
    box.setDefaultButton(copy)
    box.exec()
    return {over: "overwrite", copy: "copy"}.get(box.clickedButton(),
                                                  "cancel")


def save_to_dropbox(win):
    """Save the open drawing back where it came from in Dropbox (or ask
    where, for a file not from Dropbox)."""
    if _blocked(win):
        return False
    if getattr(win, "_view", None) is None:
        _say(win, "Open a drawing first.")
        return False
    local = _save_open_doc(win)
    if not local:
        return False
    link = dbx.read_link(local)
    if not link:
        return save_to_dropbox_as(win, local=local)
    client = ensure_client(win)
    if client is None:
        return False
    name = dbx.basename(link["path"])
    over = None
    while True:
        try:
            meta, sent = run(win, f"Saving {name} to Dropbox…",
                             lambda p, c: dbx.resave(client, local, p, c,
                                                     overwrite_rev=over))
        except dbx.Conflict as e:
            if e.remote is None:
                over = None
                return _gone(win, client, local, link)
            choice = _conflict_choice(win, name, e.remote)
            if choice == "overwrite":
                over = e.remote.get("rev")
                continue
            if choice == "copy":
                path = dbx.join(dbx.parent(link["path"]), dbx.copy_name(
                    name, settings.author()))
                return _upload_new(win, client, local, path) is not None
            return False
        except dbx.NotFound:
            return _gone(win, client, local, link)
        except dbx.Cancelled:
            return False
        except Exception as e:                            # noqa: BLE001
            _fail(win, e)
            return False
        _flash(win, (f"Saved to Dropbox: {meta.get('path_display')}" if sent
                     else f"Dropbox already has this version of {name}"))
        return True


def _gone(win, client, local, link):
    box = QMessageBox(QMessageBox.Question, TITLE,
                      f"{dbx.basename(link['path'])} isn't in Dropbox any "
                      "more (it was moved, renamed or deleted). Save it "
                      "there again, or choose another folder?", parent=win)
    again = box.addButton("Save It There Again", QMessageBox.AcceptRole)
    other = box.addButton("Choose a Folder…", QMessageBox.ActionRole)
    box.addButton(QMessageBox.Cancel)
    box.exec()
    if box.clickedButton() is again:
        return _upload_new(win, client, local, link["path"]) is not None
    if box.clickedButton() is other:
        return save_to_dropbox_as(win, local=local, client=client)
    return False


def _upload_new(win, client, local, path):
    """Upload as a new Dropbox file (no silent overwrite: a name already
    there asks first). Returns the metadata, or None."""
    rev = None
    while True:
        try:
            meta = run(win, f"Saving {dbx.basename(path)} to Dropbox…",
                       lambda p, c: dbx.save_new(client, local, path, p, c,
                                                 replace_rev=rev))
        except dbx.Conflict:
            box = QMessageBox(QMessageBox.Question, TITLE,
                              f"{dbx.basename(path)} is already in that "
                              "Dropbox folder. Replace it, or choose another "
                              "name?", parent=win)
            repl = box.addButton("Replace", QMessageBox.DestructiveRole)
            other = box.addButton("Another Name…", QMessageBox.AcceptRole)
            box.addButton(QMessageBox.Cancel)
            box.exec()
            if box.clickedButton() is repl:
                try:
                    m = run(win, "Checking Dropbox…",
                            lambda _p, _c: client.get_metadata(path))
                except Exception as e:                    # noqa: BLE001
                    _fail(win, e)
                    return None
                if not m or m.get(".tag") != "file":
                    if m:
                        _say(win, "A folder has that name; choose another "
                             "name.")
                        rev = None
                        path = _ask_name(win, path)
                        if not path:
                            return None
                    continue
                rev = m.get("rev")
                continue
            if box.clickedButton() is other:
                rev = None
                path = _ask_name(win, path)
                if not path:
                    return None
                continue
            return None
        except dbx.Cancelled:
            return None
        except Exception as e:                            # noqa: BLE001
            _fail(win, e)
            return None
        _flash(win, f"Saved to Dropbox: {meta.get('path_display') or path}")
        return meta


def _ask_name(win, path):
    name, ok = QInputDialog.getText(
        win, TITLE, "New name:", QLineEdit.EchoMode.Normal,
        dbx.copy_name(dbx.basename(path), settings.author()))
    name = (name or "").strip()
    if not ok or not name or "/" in name or "\\" in name:
        return ""
    return dbx.join(dbx.parent(path), name)


def _choose_what(win):
    """What to upload: the open drawing, a file exported this session, or
    another file. Returns a local path or None."""
    from . import filedialogs
    doc_open = getattr(win, "_view", None) is not None
    cur = os.path.normcase(win._path) if doc_open and win._path else ""
    exports = [p for p in filedialogs.recent_saves()
               if os.path.normcase(p) != cur]
    if doc_open and not exports:
        return _save_open_doc(win)
    d = QDialog(win)
    d.setWindowTitle(SAVE_AS_TEXT.rstrip("…"))
    lay = QVBoxLayout(d)
    lay.addWidget(QLabel("What do you want to save to Dropbox?"))
    group = QButtonGroup(d)
    r_doc = QRadioButton("The open drawing" + (
        f" ({os.path.basename(win._path)})" if doc_open and win._path
        else ""))
    r_doc.setEnabled(doc_open)
    r_exp = QRadioButton("A file you saved or exported this session:")
    r_exp.setEnabled(bool(exports))
    combo = QComboBox()
    for p in exports:
        combo.addItem(os.path.basename(p), p)
        combo.setItemData(combo.count() - 1, p, Qt.ToolTipRole)
    combo.setEnabled(bool(exports))
    r_other = QRadioButton("Another file on this PC (report, Excel, CSV…)")
    for r in (r_doc, r_exp, r_other):
        group.addButton(r)
    (r_doc if doc_open else r_exp if exports else r_other).setChecked(True)
    lay.addWidget(r_doc)
    lay.addWidget(r_exp)
    lay.addWidget(combo)
    lay.addWidget(r_other)
    bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    bb.accepted.connect(d.accept)
    bb.rejected.connect(d.reject)
    lay.addWidget(bb)
    if not d.exec():
        return None
    if r_doc.isChecked():
        return _save_open_doc(win)
    if r_exp.isChecked():
        return combo.currentData()
    path, _ = QFileDialog.getOpenFileName(
        win, "File to Save to Dropbox", "",
        "Reports and data (*.pdf *.xlsx *.xls *.csv *.docx *.pptx *.html "
        "*.txt *.dxf *.kml *.geojson *.json *.png *.jpg);;All files (*)")
    return path or None


def save_to_dropbox_as(win, local=None, client=None):
    """Upload the open drawing or an exported file to a Dropbox folder the
    user picks (a name already there asks first)."""
    if _blocked(win):
        return False
    if local is None:
        local = _choose_what(win)
        if not local:
            return False
    if not os.path.isfile(local):
        _say(win, f"{local} isn't there any more.", QMessageBox.Warning)
        return False
    client = client or ensure_client(win)
    if client is None:
        return False
    link = dbx.read_link(local)
    start = dbx.parent(link["path"]) if link else _start_folder()
    b = DropboxBrowser(win, client, "folder", start, os.path.basename(local))
    if not b.exec() or not b.target:
        return False
    return _upload_new(win, client, local, b.target) is not None


# ---- Dropbox Settings… --------------------------------------------------------------------
class SettingsDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Dropbox Settings")
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        krow = QHBoxLayout()
        self.key = QLineEdit(dbx.app_key())
        self.key.setReadOnly(dbx.app_key_from_policy())
        krow.addWidget(self.key, 1)
        helpb = QPushButton("How to Get One…")
        helpb.clicked.connect(lambda _c=False: self._setup())
        krow.addWidget(helpb)
        form.addRow("App key:", krow)
        if dbx.app_key_from_policy():
            form.addRow("", QLabel("Set by your IT department."))
        urow = QHBoxLayout()
        uri = QLineEdit(dbx.redirect_uri())
        uri.setReadOnly(True)
        urow.addWidget(uri, 1)
        cp = QPushButton("Copy")
        cp.clicked.connect(lambda _c=False: _copy(dbx.redirect_uri()))
        urow.addWidget(cp)
        form.addRow("Redirect URI:", urow)
        arow = QHBoxLayout()
        self.account = QLabel("")
        self.account.setWordWrap(True)
        arow.addWidget(self.account, 1)
        self.sign = QPushButton("")
        self.sign.clicked.connect(lambda _c=False: self._sign())
        arow.addWidget(self.sign)
        form.addRow("Account:", arow)
        frow = QHBoxLayout()
        self.folder = QLineEdit(dbx.default_folder() or "/")
        frow.addWidget(self.folder, 1)
        pick = QPushButton("Choose…")
        pick.clicked.connect(lambda _c=False: self._pick())
        frow.addWidget(pick)
        form.addRow("Default folder:", frow)
        lay.addLayout(form)
        note = QLabel("The App secret is not needed. Files you open from "
                      "Dropbox are kept in " + dbx.work_root() + ".")
        note.setWordWrap(True)
        note.setObjectName("StartTip")
        lay.addWidget(note)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        bb.accepted.connect(self.accept)
        lay.addWidget(bb)
        self._refresh()

    def _refresh(self):
        t = dbx.load_tokens()
        if dbx.signed_in():
            who = t.get("name") or "a Dropbox account"
            mail = t.get("email")
            self.account.setText(f"Signed in as {who}" +
                                 (f" ({mail})" if mail else ""))
            self.sign.setText("Sign Out")
        else:
            self.account.setText("Not signed in")
            self.sign.setText("Sign In…")

    def _keep_key(self):
        k = self.key.text().strip()
        if dbx.app_key_from_policy() or k == dbx.app_key():
            return True
        if k and not dbx.valid_app_key(k):
            _say(self, "That doesn't look like an App key.",
                 QMessageBox.Warning)
            return False
        dbx.set_app_key(k)
        return True

    def _setup(self):
        if setup_screen(self):
            self.key.setText(dbx.app_key())
        self._refresh()

    def _sign(self):
        if _blocked(self):
            return
        if dbx.signed_in():
            c = dbx.Client()
            try:
                run(self, "Signing out of Dropbox…",
                    lambda _p, _c: c.revoke())
            except Exception as e:                        # noqa: BLE001
                _fail(self, e)
            else:
                _flash(self.win, "Signed out of Dropbox")
        else:
            if not self._keep_key():
                return
            key = dbx.app_key() or setup_screen(self)
            if key:
                sign_in(self, key)
        self._refresh()

    def _pick(self):
        if not self._keep_key():
            return
        c = ensure_client(self.win)
        if c is None:
            return
        b = DropboxBrowser(self, c, "folder", self.folder.text())
        if b.name is not None:
            b.name.setText("(this folder)")
            b.name.setEnabled(False)
        if b.exec():
            self.folder.setText(dbx.parent(b.target) or "/")

    def done(self, r):
        if self._keep_key():
            dbx.set_default_folder(self.folder.text())
            super().done(r)


def dropbox_settings(win):
    d = SettingsDialog(win)
    d.exec()
    return d
