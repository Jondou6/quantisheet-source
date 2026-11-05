"""Crash reports, kept on this PC only (0.12.24).

Every unhandled error writes a short report to <log folder>\\crashes\\
(crash-YYYYmmdd-HHMMSS-N.txt): version, Windows, what was happening, the
Python traceback and the last lines of the log. A hard crash (Python
itself stopped - the faulthandler record in crash.log) is found at the
next start and written up the same way. The newest reports go in the
support bundle (Help > Support Bundle for IT); nothing is ever sent
anywhere by this module.

Email addresses are removed, as in the support bundle. The user is told
once (not on every error) that a report was saved and where to find it.
"""
import datetime
import json
import logging
import os
import platform
import re
import threading
import time
import traceback

KEEP = 20                       # newest reports kept
LOG_TAIL = 80                   # log lines in each report
NOTICE_GAP = 120                # seconds between notices to the user
FATAL = re.compile(r"Fatal Python error|Windows fatal exception|"
                   r"Segmentation fault|access violation", re.I)
# Python's fault handler also writes a "Windows fatal exception: code
# 0x..." line for exceptions Windows raises and handles itself - a COM
# call refused while a screen reader or UI Automation asks the window
# something (0x8001010D), a debugger thread name (0x406D1388), a caught
# C++ exception (0xE06D7363). The program carries on after those; only
# error codes (0xC...) are crashes (GUI user test r42 F10).
_SEH = re.compile(r"Windows fatal exception: code (0x[0-9a-fA-F]+)")


def _fatal(text):
    """The first real crash in `text` (a re match) or None."""
    for m in FATAL.finditer(text):
        c = _SEH.match(text, m.start())
        if c and not c.group(1).lower().startswith("0xc"):
            continue
        return m
    return None


# the freeze recorder (freeze_watch.py): faulthandler's "Timeout (0:00:10)!"
# when the window stops answering, and its own line if it came back
_FROZE = re.compile(r"^Timeout \(\d+:\d\d:\d\d\)!", re.M)
_FROZE_FOR = re.compile(r"window frozen (\d+) s")
S_ASK_FREEZE = "offer_freeze_report"
last_kind = [None]          # "crash" or "freeze": what check_previous_run found


def _freeze(text):
    """The first freeze in `text` (a re match) or None."""
    return _FROZE.search(text)


EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_lock = threading.Lock()
_last_notice = [0.0]
_count = [0]

log = logging.getLogger("quantisheet")


def folder():
    from .main import log_folder
    return os.path.join(log_folder(), "crashes")


def _clean(text):
    return EMAIL.sub("[email removed]", text)


def _log_tail(n=LOG_TAIL):
    from .main import log_folder
    from . import settings
    p = os.path.join(log_folder(), settings.LOG_NAME)
    try:
        with open(p, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 200_000))
            lines = f.read().decode("utf-8", "replace").splitlines()
        return "\n".join(lines[-n:])
    except OSError:
        return "(no log)"


def _header(kind):
    from . import __version__
    try:
        from .diagnostics import windows
        win = windows()
        osline = (f"{win.get('edition') or platform.platform()} "
                  f"build {win.get('build', '')}"
                  f"{' (Remote Desktop)' if win.get('remote_session') else ''}")
    except Exception:                                     # noqa: BLE001
        osline = platform.platform()
    return (f"QuantiSheet crash report\n"
            f"What: {kind}\n"
            f"When: {datetime.datetime.now().isoformat(timespec='seconds')}\n"
            f"Version: {__version__}\n"
            f"Windows: {osline}\n"
            f"Thread: {threading.current_thread().name}\n")


def _prune(d):
    try:
        names = sorted(n for n in os.listdir(d) if n.startswith("crash-")
                       and n.endswith(".txt"))
        for n in names[:-KEEP]:
            os.remove(os.path.join(d, n))
    except OSError:
        pass


def write(kind, body):
    """Save one report; returns its path (None if it couldn't be
    written - a crash report must never cause another error)."""
    try:
        with _lock:
            d = folder()
            os.makedirs(d, exist_ok=True)
            _count[0] += 1
            name = (f"crash-{time.strftime('%Y%m%d-%H%M%S')}-"
                    f"{_count[0]}.txt")
            path = os.path.join(d, name)
            text = (_header(kind) + "\n" + body.rstrip() +
                    "\n\n--- last lines of the log ---\n" + _log_tail())
            with open(path, "w", encoding="utf-8") as f:
                f.write(_clean(text) + "\n")
            _prune(d)
            return path
    except Exception:                                     # noqa: BLE001
        return None


def from_exception(kind, value, tb):
    """The report for an unhandled error (sys.excepthook)."""
    body = "".join(traceback.format_exception(kind, value, tb))
    path = write(f"error: {kind.__name__}", body)
    if path:
        _notify(path)
    return path


def check_previous_run(crash_log):
    """At start-up: a hard crash recorded in crash.log since we last
    looked becomes a report. Returns its path or None. The offset already
    read is kept in crashes\\seen.json, so each crash is reported once.

    Nov 3: on a computer where seen.json couldn't be updated, the same old
    crash was reported at every start ("closed unexpectedly last time"
    each time a PDF was opened). Each crash reported is now also
    remembered by a fingerprint in the settings, and when neither place
    can be written nothing is reported - better quiet than the same
    notice again and again."""
    import hashlib
    try:
        size = os.path.getsize(crash_log)
    except OSError:
        return None
    d = folder()
    seen_p = os.path.join(d, "seen.json")
    try:
        with open(seen_p, encoding="utf-8") as f:
            seen = json.load(f)
    except (OSError, ValueError):
        seen = {}
    start = seen.get("offset", 0) if seen.get("file") == crash_log else 0
    if start > size:                     # crash.log was rotated
        start = 0
    saved = True
    try:
        os.makedirs(d, exist_ok=True)
        with open(seen_p, "w", encoding="utf-8") as f:
            json.dump({"file": crash_log, "offset": size}, f)
    except OSError:
        saved = False
    if size <= start:
        return None
    with open(crash_log, "rb") as f:
        f.seek(start)
        new = f.read(2_000_000).decode("utf-8", "replace")
    m = _fatal(new)
    kind = "crash"
    if not m:
        # Nov 3: a freeze last time (the window stopped answering for 10 s
        # or more) is offered for reporting too, unless turned off
        m = _freeze(new)
        kind = "freeze"
        try:
            from . import settings
            if settings.get(S_ASK_FREEZE, True) is False:
                m = None
        except Exception:                                 # noqa: BLE001
            pass
    last_kind[0] = None
    if not m or not seen:                # nothing, or the very first run
        return None
    key = hashlib.sha1(new[m.start():m.start() + 600].encode(
        "utf-8", "replace")).hexdigest()[:16]
    try:
        from . import settings
        done = [k for k in (settings.get("crash_reported") or [])
                if isinstance(k, str)]
        if key in done:
            return None                  # this one was reported already
        settings.set("crash_reported", (done + [key])[-30:])
        remembered = settings.get("crash_reported") or []
        saved = saved or key in remembered
    except Exception:                                     # noqa: BLE001
        pass
    if not saved:
        log.warning("crash.log has a crash, but where it was reported "
                    "can't be saved here - not shown, so it isn't shown "
                    "at every start")
        return None
    last_kind[0] = kind
    if kind == "freeze":
        return write("the window froze in the previous session",
                     new[max(0, m.start() - 2000):][:60_000])
    return write("hard crash in the previous session",
                 new[max(0, m.start() - 2000):][:60_000])


def reports(newest=10):
    """Paths of the newest reports, newest first."""
    d = folder()
    try:
        names = sorted((n for n in os.listdir(d) if n.startswith("crash-")
                        and n.endswith(".txt")), reverse=True)
    except OSError:
        return []
    return [os.path.join(d, n) for n in names[:newest]]


def freeze_seconds(path):
    """How long the window was frozen, from a freeze report (None if it
    never came back, or isn't known)."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            m = _FROZE_FOR.search(f.read())
        return int(m.group(1)) if m else None
    except OSError:
        return None


def _notify(path, previous=False, kind=None):
    """Tell the user once in a while - never a dialog per error."""
    now = time.monotonic()
    if now - _last_notice[0] < NOTICE_GAP:
        return
    _last_notice[0] = now
    try:
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication, QMessageBox
        app = QApplication.instance()
        if app is None:
            return

        def show():
            parent = app.activeWindow()
            box = QMessageBox(parent)
            box.setIcon(QMessageBox.Warning)
            box.setWindowTitle("QuantiSheet")
            froze = kind == "freeze"
            if froze:
                secs = freeze_seconds(path)
                box.setText("QuantiSheet stopped responding last time" +
                            (f" (for about {secs} seconds)." if secs else
                             "."))
                box.setInformativeText(
                    "Want to tell us what you were doing? A note helps us "
                    "fix it. A report was saved on this computer - nothing "
                    "is sent unless you click Report This and then Send.")
            else:
                box.setText("QuantiSheet closed unexpectedly last time."
                            if previous else
                            "QuantiSheet hit an error and kept going.")
                box.setInformativeText(
                    "A report was saved on this computer (nothing was "
                    "sent). Click Report This to email it to support with "
                    "a note.")
            box.setDetailedText(path)
            box.setStandardButtons(QMessageBox.Ok)
            rep = box.addButton("Report This…", QMessageBox.ActionRole)
            if froze:
                never = box.addButton("Don't Ask About Freezes",
                                      QMessageBox.RejectRole)

                def stop_asking():
                    try:
                        from . import settings
                        settings.set(S_ASK_FREEZE, False)
                    except Exception:                     # noqa: BLE001
                        pass
                never.clicked.connect(lambda: stop_asking())

            def report(p=path, prev=previous):
                w = next((x for x in [parent] + list(app.topLevelWidgets())
                          if x is not None and hasattr(x, "report_issue")),
                         None)
                if w is not None and hasattr(w, "report_issue"):
                    w.report_issue(
                        ("QuantiSheet stopped responding last time."
                         if froze else
                         "QuantiSheet closed unexpectedly last time."
                         if prev else "QuantiSheet showed an error.") +
                        " What I was doing: ")
            rep.clicked.connect(lambda: report())
            box.open()                    # not modal: work carries on
        QTimer.singleShot(0, show)
    except Exception:                                     # noqa: BLE001
        log.debug("crash notice not shown", exc_info=True)
