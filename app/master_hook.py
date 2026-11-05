"""The one hook between QuantiSheet's main window and the Master Schedule
module (app/pm/master). Same shape as backoffice_hook.py: main_window.py
calls add_menu_item() once, after the Back Office item in the Module
menu (one import line + one call). The WHOLE body is guarded: any error
is logged and the menu build carries on unchanged.

Unlike Back Office this module runs in-process: everything it writes to
the project goes through the open ProjectStore (design option A), so the
CPM cache, undo, hub sync and the pending queue keep working. App setting
"master_schedule_module": false hides it."""
import logging
import os

from . import settings

log = logging.getLogger(__name__)
MENU_TEXT = "Master Schedule (Sub Updates)…"
_OPEN = []
_TIMERS = []
POLL_MS = 60_000


def enabled():
    return settings.get("master_schedule_module", True) is not False


def add_menu_item(window, menu):
    act = None
    try:
        if not enabled():
            return None
        act = menu.addAction(MENU_TEXT)
        act.triggered.connect(lambda *_: open_from_window(window))
        _start_background(window)
        return act
    except Exception:                                     # noqa: BLE001
        log.warning("Master Schedule menu item not added", exc_info=True)
        if act is not None:
            try:
                menu.removeAction(act)
            except Exception:                             # noqa: BLE001
                pass
        return None


def _start_background(window):
    """Design 3.2: the shared inbox is polled every 60 s while QuantiSheet
    has a project open (not only while the Master Schedule window is).
    A timer owned by the main window; its body is fully guarded."""
    if not hasattr(window, "isWidgetType"):
        return None
    from PySide6.QtCore import QTimer
    t = QTimer(window)
    t.setInterval(POLL_MS)
    t.timeout.connect(lambda: background_poll(window))
    t.start()
    _TIMERS.append(t)
    return t


def background_poll(window):
    """One background inbox check for the project the window's drawing
    sits in. Does nothing (and writes nothing) unless the module is on
    and that project's Master Schedule has an inbox folder set. Errors
    are logged, never raised into the main window."""
    try:
        if not enabled():
            return None
        store = store_for(window)
        if store is None:
            return None
        cur = store.setting("master_schedule") or {}
        if not cur.get("inbox") or cur.get("enabled") is False:
            return None
        from .pm.master import dropbox_inbox, intake
        if dropbox_inbox.is_remote(cur.get("inbox")):
            # Dropbox (Q3): the download runs on a worker thread; files it
            # brought in are taken from the local mirror on this tick or
            # the next, so the window never waits on the network
            dropbox_inbox.sync_in_background(store)
            return intake.scan(store, intake.state_for(store), sync=False)
        return intake.scan(store, intake.state_for(store))
    except Exception:                                     # noqa: BLE001
        log.warning("Master Schedule background inbox check failed",
                    exc_info=True)
        return None


def store_for(window):
    """The Project Center project the window's drawing sits in (its
    folder or the one above), or None."""
    path = getattr(window, "_path", None)
    if not path:
        return None
    from .pm.store import ProjectStore, open_store
    d = os.path.dirname(os.path.abspath(path))
    for folder in (d, os.path.dirname(d)):
        if ProjectStore.exists(folder):
            return open_store(folder)
    return None


def where_to_start(window, choose=None, pick=None, say=None):
    """No Project Center project for the open drawing (GUI user test r42
    F05: Master Schedule went straight to a bare folder picker). Offer to
    make a project in the drawing's folder, or pick an existing project.
    `choose()` -> "make" / "pick" / None and `pick()` -> folder are for
    tests. Returns a ProjectStore or None."""
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    from .pm.store import ProjectStore, open_store
    parent = window if hasattr(window, "isWidgetType") else None
    path = getattr(window, "_path", None)
    here = os.path.dirname(os.path.abspath(path)) if path else ""
    if choose is None:
        def choose():
            box = QMessageBox(parent)
            box.setWindowTitle("Master Schedule")
            box.setText("The Master Schedule belongs to a job's Project "
                        "Center project, and this drawing isn't in one "
                        "yet.")
            make = box.addButton(
                "Make a project in this drawing's folder",
                QMessageBox.AcceptRole) if here else None
            if here:
                box.setInformativeText(f"Folder: {here}")
            other = box.addButton("Pick an existing project folder…",
                                  QMessageBox.ActionRole)
            box.addButton(QMessageBox.Cancel)
            box.exec()
            c = box.clickedButton()
            return "make" if c is make and make is not None else \
                "pick" if c is other else None
    how = choose()
    if how == "make" and here:
        store = open_store(here)
        if not ProjectStore.exists(here):
            store.save()
        return store
    if how != "pick":
        return None
    folder = pick() if pick is not None else QFileDialog.getExistingDirectory(
        parent, "Master Schedule - pick the Project Center project folder")
    if not folder:
        return None
    if not ProjectStore.exists(folder):
        text = ("That folder has no Project Center project yet. Open it "
                "in Project > Project Center first, or choose 'Make a "
                "project' next time.")
        if say is not None:
            say(text)
        else:
            QMessageBox.information(parent, "Master Schedule", text)
        return None
    return open_store(folder)


def open_from_window(window):
    """Open the Master Schedule window for the project; when the drawing
    isn't in a project, offer to make one or pick one."""
    from PySide6.QtWidgets import QMessageBox
    try:
        store = store_for(window)
        if store is None:
            store = where_to_start(window)
            if store is None:
                return None
        from .pm.master.ui import MasterScheduleWindow
        w = MasterScheduleWindow(store,
                                 window if hasattr(window, "isWidgetType")
                                 else None)
        _OPEN.append(w)
        w.finished.connect(lambda *_: _OPEN.remove(w) if w in _OPEN
                           else None)
        from . import modern_ui     # opens full screen (Jon, 0.13.11)
        modern_ui.ensure_maximized(w)
        return w
    except Exception as e:                                # noqa: BLE001
        log.warning("could not open Master Schedule", exc_info=True)
        QMessageBox.warning(None, "Master Schedule",
                            f"Could not open Master Schedule:\n{e}")
        return None
