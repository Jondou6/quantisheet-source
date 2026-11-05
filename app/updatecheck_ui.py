"""The window side of the team-copy update check (logic: updatecheck.py).

install(win) - called once from MainWindow.__init__ - does nothing at all
unless updatecheck.team_build() (installed tester copy, not the Store /
public copy). Then it:
  * adds to Help: "Check for Updates Now..." and a checkable
    "Check for Updates Automatically" (the setting to turn it off);
  * 15 s after start, if due (once a day), checks in a background thread.
A newer version shows a small notice at the bottom of the window - it
never blocks work and never installs without being asked:
    Update now | Later | Skip this version
Update now (Nov 3, Jon: like normal software) downloads it with a progress
bar, checks its SHA-256, closes QuantiSheet the usual way (unsaved work is
asked about - saying Cancel keeps it open and the update waits), then the
setup installs by itself with a progress bar and QuantiSheet opens again
on the new version (updatecheck.QUIET_SWITCHES).

Nov 2 (Jon): until a newer version is installed or skipped, a small
"Update available" item stays in the status bar and a line on the Start
page (click either to check and see the offer again), and on the first
start after updating, What's New shows that version's notes once. All of
it is team copy only, like the rest of this file."""
import logging
import os
import threading

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QMessageBox,
                               QProgressBar, QPushButton, QVBoxLayout)

from . import updatecheck

log = logging.getLogger(__name__)
FIRST_CHECK_MS = 15000
WHATS_NEW_MS = 2500


class _Bridge(QObject):
    checked = Signal(str, object, bool)      # status, info, manual
    progress = Signal(int, int)
    downloaded = Signal(object, object, object)  # token, path, error


class UpdateNotice(QFrame):
    """Non-modal notice at the bottom of the window."""

    def __init__(self, win, info):
        super().__init__(win.centralWidget() or win)
        self.win, self.info = win, info
        self._token = None               # the running download, if any
        self.setObjectName("UpdateNotice")
        self.setStyleSheet(
            "#UpdateNotice { background: rgba(32,33,36,240); border-radius: "
            "8px; } #UpdateNotice QLabel { color: white; } #UpdateNotice "
            "QPushButton { padding: 3px 10px; }")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 8, 8, 8)
        self.title = QLabel()
        self.title.setTextFormat(Qt.PlainText)
        outer.addWidget(self.title)
        self.notes = QLabel()
        self.notes.setTextFormat(Qt.PlainText)     # manifest text: never HTML
        self.notes.setWordWrap(True)
        self.notes.setMaximumWidth(520)
        outer.addWidget(self.notes)
        self.bar = QProgressBar()
        self.bar.setVisible(False)
        outer.addWidget(self.bar)
        row = QHBoxLayout()
        outer.addLayout(row)
        self.b1, self.b2, self.b3 = (QPushButton(), QPushButton(),
                                     QPushButton())
        self._actions = [None, None, None]
        for i, b in enumerate((self.b1, self.b2, self.b3)):
            row.addWidget(b)
            b.clicked.connect(lambda _c=False, i=i: self._click(i))
        self.bridge = _Bridge()
        self.bridge.progress.connect(self._on_progress)
        self.bridge.downloaded.connect(self._on_downloaded)
        ready = updatecheck.ready_download(info)
        if ready:
            self._show_ready(ready)
        else:
            self._show_offer()
        win.installEventFilter(self)
        self.show()
        self.raise_()
        QTimer.singleShot(0, self._place)

    # -- layout ---------------------------------------------------------------
    def eventFilter(self, obj, ev):
        from PySide6.QtCore import QEvent
        if ev.type() == QEvent.Resize:
            QTimer.singleShot(0, self._place)
        return False

    def _place(self):
        try:
            host = self.parentWidget()
            self.adjustSize()
            self.move(max(0, (host.width() - self.width()) // 2),
                      max(0, host.height() - self.height() - 48))
        except RuntimeError:
            pass

    def _buttons(self, *specs):
        """Up to three (text, action) buttons; the rest are hidden."""
        self._actions = list(specs) + [None] * (3 - len(specs))
        for b, spec in zip((self.b1, self.b2, self.b3), self._actions):
            b.setVisible(spec is not None)
            if spec:
                b.setText(spec[0])
        self._place()

    def _click(self, i):
        spec = self._actions[i] if i < len(self._actions) else None
        if spec:
            spec[1]()

    # -- states ---------------------------------------------------------------
    def _show_offer(self):
        v = self.info["version"]
        from . import owncopy
        if owncopy.shared_copy():
            # only an administrator can update the shared copy: install
            # this person's own copy, which updates itself (Nov 3)
            self.title.setText(
                f"QuantiSheet {v} is available. This is the shared copy on "
                "this computer, which only an administrator can update. "
                "Install your own copy - no administrator needed, and it "
                "updates itself from then on.")
            self.notes.setText(self.info.get("notes") or "")
            self.notes.setVisible(bool(self.info.get("notes")))
            self._buttons(("Install my own copy", self._update_now),
                          ("Later", self.close_notice),
                          ("Skip this version", self._skip))
            return
        self.title.setText(f"QuantiSheet {v} is available (you have "
                           f"{updatecheck.current_version()}).")
        self.notes.setText(self.info.get("notes") or "")
        self.notes.setVisible(bool(self.info.get("notes")))
        self._buttons(("Update now", self._update_now),
                      ("Later", self.close_notice),
                      ("Skip this version", self._skip))

    def _show_ready(self, path):
        self._path = path
        self.bar.setVisible(False)
        self.title.setText(f"QuantiSheet {self.info['version']} is "
                           "downloaded and checked. Update now? QuantiSheet "
                           "closes, updates and opens again by itself.")
        self._buttons(("Update now", self._install),
                      ("Later", self.close_notice))

    def close_notice(self):
        self._token = None
        try:
            self.win.removeEventFilter(self)
        except RuntimeError:
            pass
        self.hide()
        self.deleteLater()
        if getattr(self.win, "_update_notice", None) is self:
            self.win._update_notice = None
        refresh_reminders(self.win)

    def _skip(self):
        updatecheck.skip(self.info["version"])
        self.close_notice()

    def _update_now(self):
        """One click: download, then install straight away."""
        self._auto_install = True
        self._download()

    def _download(self):
        token = self._token = object()   # a new download; older ones stop
        self.title.setText(f"Downloading QuantiSheet "
                           f"{self.info['version']}...")
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setVisible(True)
        self._buttons(("Cancel", self._cancel_download))
        info = self.info

        def work():
            try:
                path = updatecheck.download(
                    info, progress=lambda d, t: self.bridge.progress.emit(
                        d, t),
                    cancelled=lambda: self._token is not token)
                result = (path, None)
            except Exception as e:                        # noqa: BLE001
                result = (None, e)
            try:
                self.bridge.downloaded.emit(token, *result)
            except RuntimeError:
                pass                      # notice already closed
        threading.Thread(target=work, name="qs-update-download",
                         daemon=True).start()

    def _cancel_download(self):
        self._token = None
        self.bar.setVisible(False)
        self._show_offer()

    def _on_progress(self, done, total):
        if total:
            self.bar.setValue(int(done * 100 / total))

    def _on_downloaded(self, token, path, err):
        if token is not self._token:
            return                        # cancelled, or an older download
        self._token = None
        if path:
            self._show_ready(path)
            if getattr(self, "_auto_install", False):
                self._auto_install = False
                QTimer.singleShot(0, self._install)
            return
        self.bar.setVisible(False)
        if isinstance(err, updatecheck.HashMismatch):
            self.title.setText("The download didn't match the expected file "
                               "and was deleted. Nothing was installed.")
        else:
            self.title.setText("The update couldn't be downloaded. Check "
                               "the internet connection and try again.")
        log.info("update download failed: %s", err)
        self._buttons(("Try again", self._download),
                      ("Later", self.close_notice))

    def _install(self):
        """Close QuantiSheet (unsaved work is asked about), then run the
        setup quietly; it opens QuantiSheet again when it's done."""
        if not updatecheck.verify_file(self._path, self.info):
            try:
                os.remove(self._path)
            except OSError:
                pass
            self.title.setText("The downloaded update changed on disk "
                               "and was deleted. Nothing was installed.")
            self._buttons(("Download again", self._update_now),
                          ("Later", self.close_notice))
            return
        self.title.setText(f"Updating to QuantiSheet {self.info['version']}"
                           "... QuantiSheet closes and opens again by "
                           "itself.")
        self._buttons()
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()
        if not self.win.close():           # Cancel on unsaved work: wait
            self.title.setText(f"QuantiSheet {self.info['version']} is "
                               "ready. Click Update now when your work is "
                               "saved.")
            self._buttons(("Update now", self._install),
                          ("Later", self.close_notice))
            return
        try:
            updatecheck.launch_installer(self._path, self.info)
        except (updatecheck.HashMismatch, OSError) as e:
            log.info("update didn't start: %s", e)
            QMessageBox.information(
                None, "QuantiSheet",
                "The update couldn't be started. It's been checked and "
                f"saved here; run it yourself:\n\n{self._path}")
            try:
                os.startfile(os.path.dirname(self._path))  # noqa: S606
            except (AttributeError, OSError):
                pass
            return
        app = QApplication.instance()
        if app is not None:
            QTimer.singleShot(0, app.quit)  # out of the way of the setup


# ---- reminders: status bar and Start page (Nov 2) -----------------------------
def _chip(win):
    chip = getattr(win, "_update_chip", None)
    if chip is not None:
        return chip
    from PySide6.QtWidgets import QToolButton
    chip = QToolButton()
    chip.setObjectName("StatusChipButton")
    chip.setAutoRaise(True)
    chip.setToolTip("A newer QuantiSheet is ready to download - click to "
                    "see what's new and install it")
    chip.clicked.connect(lambda _c=False: _reminder_clicked(win))
    chip.setVisible(False)
    try:
        win.statusBar().addPermanentWidget(chip)
    except RuntimeError:
        return None
    win._update_chip = chip
    return chip


def refresh_reminders(win):
    """Show or hide the status-bar item and the Start page line from what
    is waiting (updatecheck.waiting). Returns the waiting version or None."""
    try:
        w = updatecheck.waiting()
    except Exception:                                     # noqa: BLE001
        w = None
    open_notice = getattr(win, "_update_notice", None) is not None
    chip = _chip(win)
    if chip is not None:
        try:
            if w:
                chip.setText("Update available" if _mode(win) == "store"
                             or not w["version"] else
                             f"Update available: {w['version']}")
            chip.setVisible(bool(w) and not open_notice)
        except RuntimeError:
            pass
    sp = getattr(win, "start_page", None)
    if sp is not None and hasattr(sp, "set_update"):
        try:
            store = _mode(win) == "store"
            sp.set_update(
                (f"An update for QuantiSheet is ready in the Microsoft "
                 "Store - click to open the Store and install it."
                 if store else
                 f"QuantiSheet {w['version']} is available - click to see "
                 "what's new and install it.") if w else None,
                lambda: _reminder_clicked(win))
        except RuntimeError:
            pass
    return w["version"] if w else None


def _mode(win):
    return getattr(win, "_update_mode", "team")


def _reminder_clicked(win):
    if _mode(win) == "store":
        from . import storeupdate
        storeupdate.open_store()
    else:
        run_check(win, manual=True)


# ---- the Store copy (Nov 2): ask the Store, the Store installs ------------
def _show_store(win, status, info, manual):
    if status == "available":
        updatecheck.remember(info)
        refresh_reminders(win)
        if manual:
            box = QMessageBox(win)
            box.setWindowTitle("QuantiSheet")
            box.setText("An update for QuantiSheet is ready in the Microsoft "
                        "Store. Open the Store to install it?")
            box.setStandardButtons(QMessageBox.Open | QMessageBox.Close)
            if box.exec() == QMessageBox.Open:
                from . import storeupdate
                storeupdate.open_store()
        return
    if status == "current":
        updatecheck.forget()
        refresh_reminders(win)
    if not manual:
        return
    text = {
        "current": "QuantiSheet is up to date.",
        "ineligible": "Update checks are turned off for this copy.",
    }.get(status, "The Microsoft Store couldn't be asked about updates "
                  "right now. The Store still updates QuantiSheet on its "
                  "own; you can also look in the Store's Library.")
    QMessageBox.information(win, "QuantiSheet", text)


def run_store_check(win, manual=False):
    bridge = getattr(win, "_store_bridge", None)
    if bridge is None:
        bridge = win._store_bridge = _Bridge(win)
        bridge.checked.connect(lambda s, i, m: _show_store(win, s, i, m))

    def work():
        from . import storeupdate
        status, info = storeupdate.check(manual=manual)
        try:
            bridge.checked.emit(status, info, manual)
        except RuntimeError:
            pass
    threading.Thread(target=work, name="qs-store-update-check",
                     daemon=True).start()


def show_whats_new(win, show=True):
    """Once, on the first start after an update: the notes the new version
    was offered with. Returns the dialog text, or None."""
    try:
        got = updatecheck.whats_new()
    except Exception:                                     # noqa: BLE001
        log.debug("what's new not read", exc_info=True)
        got = None
    refresh_reminders(win)
    if not got:
        return None
    notes = got["notes"].strip()
    text = (f"QuantiSheet is now version {got['version']}.\n\n"
            + (notes if notes else "Help > Help Center & Tutorials has "
               "the lessons for anything new."))
    if show:
        box = QMessageBox(win)
        box.setWindowTitle(f"What's new in QuantiSheet {got['version']}")
        box.setTextFormat(Qt.PlainText)         # manifest text: never HTML
        box.setText(text)
        box.setIcon(QMessageBox.Information)
        box.open()
        win._whats_new_box = box
    return text


# ---- wiring -------------------------------------------------------------------
def _show(win, status, info, manual):
    if status == "available":
        old = getattr(win, "_update_notice", None)
        if old is not None:
            try:
                old.close_notice()
            except RuntimeError:
                pass
        updatecheck.tidy(keep_version=info["version"])
        updatecheck.remember(info)
        win._update_notice = UpdateNotice(win, info)
        refresh_reminders(win)
        return
    if status == "current":
        updatecheck.forget()
        refresh_reminders(win)
    if not manual:
        return                            # automatic: silent unless newer
    text = {
        "current": "QuantiSheet is up to date.",
        "offline": "Couldn't reach the update server. Check the internet "
                   "connection and try again later.",
        "ineligible": "Update checks are turned off for this copy.",
    }.get(status, "The update information couldn't be checked. Try again "
                  "later.")
    QMessageBox.information(win, "QuantiSheet", text)


def run_check(win, manual=False):
    bridge = getattr(win, "_update_bridge", None)
    if bridge is None:
        bridge = win._update_bridge = _Bridge(win)
        bridge.checked.connect(lambda s, i, m: _show(win, s, i, m))

    def work():
        status, info = updatecheck.check(manual=manual)
        try:
            bridge.checked.emit(status, info, manual)
        except RuntimeError:
            pass                          # window already closed
    threading.Thread(target=work, name="qs-update-check",
                     daemon=True).start()


def add_menu(win, help_menu, check=None):
    from PySide6.QtGui import QAction
    check = check or run_check
    before = next((a for a in help_menu.actions()
                   if a.text().replace("&", "") == "About QuantiSheet"),
                  None)
    now = QAction("Check for Updates Now…", win)
    now.triggered.connect(lambda _c=False: check(win, manual=True))
    auto = QAction("Check for Updates Automatically", win)
    auto.setCheckable(True)
    auto.setChecked(updatecheck.enabled())
    auto.toggled.connect(updatecheck.set_enabled)
    back = QAction("Reinstall Previous Version…", win)
    back.triggered.connect(lambda _c=False: reinstall_previous(win))
    back.setStatusTip("Go back to the version you had before the last "
                      "update (its installer is kept on this PC).")
    for a in (now, auto, back):
        if before is not None:
            help_menu.insertAction(before, a)
        else:
            help_menu.addAction(a)
    if before is not None:
        help_menu.insertSeparator(before)
    help_menu.aboutToShow.connect(lambda: _label_previous(back))
    win._update_actions = (now, auto, back)
    return now, auto


def _label_previous(action):
    p = updatecheck.previous_installer()
    if p:
        v = os.path.basename(p)[len("QuantiSheet-Team-Setup-"):-4]
        action.setText(f"Reinstall Previous Version ({v})…")
    else:
        action.setText("Reinstall Previous Version…")
    action.setEnabled(bool(p))


PREVIOUS_WARNING = (
    "Go back to QuantiSheet {v}?\n\nIts installer runs now and replaces "
    "this version; your settings, price database and jobs stay. Job files "
    "you saved with this newer version open in {v} to look at, with saving "
    "turned off - that's the version check protecting what the older "
    "version can't read. Save your work and close QuantiSheet first.")


def reinstall_previous(win, ask=None, run=None):
    """Help > Reinstall Previous Version (review 2, Nov 4): run the kept
    installer of the version before this one, after saying what it does.
    Returns the installer path, or None."""
    p = updatecheck.previous_installer()
    if not p:
        QMessageBox.information(win, "Reinstall Previous Version",
                                "There's no earlier installer on this PC "
                                "(only one is kept after an update).")
        return None
    v = os.path.basename(p)[len("QuantiSheet-Team-Setup-"):-4]
    text = PREVIOUS_WARNING.format(v=v)
    ok = ask(text) if ask is not None else QMessageBox.question(
        win, "Reinstall Previous Version", text) == QMessageBox.Yes
    if not ok:
        return None
    if run is None:
        import subprocess
        run = lambda a: subprocess.Popen(a, close_fds=True)  # noqa: E731
    run([p])                         # the normal setup, not a quiet one
    return p


def install(win, help_menu=None):
    """Everything above, for the team copy (our signed check) or the Store
    copy (asks the Store; the Store installs). Returns True (team copy),
    "store" (Store copy) or False (the public copy, a source run)."""
    from . import storeupdate
    if updatecheck.team_build():
        mode = "team"
    elif storeupdate.store_copy():
        mode = "store"
    else:
        return False
    win._update_mode = mode
    menu = help_menu or getattr(win, "_help_menu", None)
    if menu is not None:
        add_menu(win, menu, run_check if mode == "team" else
                 run_store_check)
    refresh_reminders(win)
    if not os.environ.get("QUANTISHEET_SMOKE"):
        QTimer.singleShot(FIRST_CHECK_MS, lambda: _auto(win))
        QTimer.singleShot(WHATS_NEW_MS, lambda: show_whats_new(win))
    return True if mode == "team" else mode


def _auto(win):
    if _mode(win) == "store":
        from . import storeupdate
        ok, _why = storeupdate.eligible(manual=False)
        if ok and updatecheck.due():
            run_store_check(win, manual=False)
        return
    ok, _why = updatecheck.eligible(manual=False)
    if ok and updatecheck.due():
        run_check(win, manual=False)
