"""Send error reports automatically (Jon, Nov 25: "Send reports
automatically"; receiver on Cloudflare, private; switch on the Help menu).

Team (tester) copy only, and only when the tester turned it on with Help >
Send Error Reports Automatically - it starts off. When QuantiSheet saves a
crash report (crashreport.write), the report's first part - what happened,
the version, the Windows version and the error's code trace - is sent over
https to REPORT_URL. Never sent: the log, drawings, job files, file and
folder names, email addresses, prices. Paths, file names and money amounts
in the error text are replaced before it leaves (scrub). At most PER_DAY
reports a day. IT turns it off with DisableErrorReports (or OfflineMode).
A failure to send is silent: a report must never cause another error."""
import json
import logging
import re
import threading
import time
import urllib.request
from urllib.parse import urlparse

log = logging.getLogger("quantisheet")

REPORT_URL = "https://reports.quantisheet.com/v1/report"
REPORT_HOST = urlparse(REPORT_URL).hostname
S_ON = "error_reports_auto"
S_DAY = "error_reports_day"          # [YYYY-MM-DD, count]
PER_DAY = 5
MAX_CHARS = 40_000
LOG_MARK = "--- last lines of the log ---"
MENU_TEXT = "Send Error Reports Automatically"
EXPLAIN = (
    "When QuantiSheet hits an error or closes unexpectedly, it will send "
    "a short report to the QuantiSheet team by itself: what happened, the "
    "QuantiSheet and Windows versions, and where in the program the error "
    "was.\n\nNever sent: drawings, job files, file or folder names, "
    "prices, email addresses or the log.\n\nTurn it off here at any time.")

# code frames keep the program's own file (app\x.py); every other path,
# quoted file name and money amount is replaced
_FRAME = re.compile(r'File "[^"\n]*?[\\/]((?:app|quantisheet_\w+)[\\/]'
                    r'[^"\n]+)"')
_OTHER_FRAME = re.compile(r'File "[^"\n]*?[\\/]([^"\\/\n]+)"')
_PATH = re.compile(r"(?:[A-Za-z]:[\\/]|\\\\|/(?:Users|home|mnt)/)"
                   r"[^\n\"'<>|*?]*")
_FILE = re.compile(r"[^\s\"'\\/:]+\.(?:pdf|xlsx?|xlsm|csv|dwg|dxf|docx?|zip|"
                   r"json|txt|png|jpe?g|tiff?|qs\w*)\b", re.I)
_QUOTED_FILE = re.compile(r"(['\"])[^'\"\n]*\.(?:pdf|xlsx?|xlsm|csv|dwg|dxf|"
                          r"docx?|zip|json|txt|png|jpe?g|tiff?|qs\w*)\1",
                          re.I)
_MONEY = re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def scrub(text):
    """The report text with nothing of the user's in it."""
    keep = []

    def frame(m):
        keep.append(m.group(1).replace("\\", "/"))
        return f'File "\x00{len(keep) - 1}\x00"'
    t = _FRAME.sub(frame, text)
    t = _OTHER_FRAME.sub(frame, t)        # libraries: the file's name only
    t = _QUOTED_FILE.sub(r"\1[file]\1", t)
    t = _PATH.sub("[path]", t)
    t = _FILE.sub("[file]", t)
    t = _MONEY.sub("$[amount]", t)
    t = _EMAIL.sub("[email removed]", t)
    # an error message that named a file or folder goes altogether (words
    # of a file name with spaces would be left beside the marker)
    out = []
    for line in t.split("\n"):
        if ("[file]" in line or "[path]" in line) and \
                not line.lstrip().startswith("File "):
            line = line.split(": ", 1)[0] + \
                ": [message removed: it named a file]"
        out.append(line)
    t = "\n".join(out)
    return re.sub("\x00(\\d+)\x00", lambda m: keep[int(m.group(1))], t)


def body_of(report_text):
    """What is sent of a saved crash report: everything above the log."""
    head = report_text.split(LOG_MARK, 1)[0].rstrip()
    return scrub(head)[:MAX_CHARS]


def available():
    """The Help menu item exists: the team copy, a real receiver, and IT
    hasn't turned it off."""
    try:
        from . import policy, updatecheck
        return bool(REPORT_HOST) and ".invalid" not in REPORT_HOST and \
            updatecheck.team_build() and policy.allowed("errorreports")
    except Exception:                                     # noqa: BLE001
        return False


def is_on():
    from . import settings
    return settings.get(S_ON, False) is True


def set_on(on):
    from . import settings
    settings.set(S_ON, bool(on))


def _under_limit(today=None):
    from . import settings
    today = today or time.strftime("%Y-%m-%d")
    day = settings.get(S_DAY) or ["", 0]
    try:
        n = int(day[1]) if day[0] == today else 0
    except (TypeError, ValueError, IndexError):
        n = 0
    if n >= PER_DAY:
        return False
    settings.set(S_DAY, [today, n + 1])
    return True


def _post(payload, opener=None, timeout=20):
    from . import policy
    policy.check("errorreports", REPORT_URL)
    req = urllib.request.Request(
        REPORT_URL, data=json.dumps(payload).encode("utf-8"), method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("X-QuantiSheet-Report", "1")
    # Cloudflare refuses Python's default agent name (HTTP 403)
    req.add_header("User-Agent", "QuantiSheet/" + payload.get("version", ""))
    with (opener or urllib.request.urlopen)(req, timeout=timeout) as r:
        return r.status


def maybe_send(path, opener=None, wait=False):
    """Send the report at `path` if this copy may and the tester said so.
    Returns the thread (or the HTTP status with wait), None when nothing
    is sent. Never raises."""
    try:
        if not (available() and is_on()):
            return None
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
        from . import __version__
        payload = {"app": "quantisheet", "version": __version__,
                   "report": body_of(text)}
        if not payload["report"] or not _under_limit():
            return None

        def work():
            try:
                return _post(payload, opener)
            except Exception as e:                        # noqa: BLE001
                log.info("error report not sent: %s", type(e).__name__)
                return None
        if wait:
            return work()
        t = threading.Thread(target=work, daemon=True,
                             name="error-report")
        t.start()
        return t
    except Exception:                                     # noqa: BLE001
        return None


def install(win, menu, before=None):
    """Help > Send Error Reports Automatically (a tick; team copy only).
    Turning it on shows what is sent first."""
    if not available():
        return None
    from PySide6.QtGui import QAction
    from PySide6.QtWidgets import QMessageBox
    a = QAction(MENU_TEXT, win)
    a.setCheckable(True)
    a.setChecked(is_on())

    def toggled(on):
        if on:
            box = QMessageBox(QMessageBox.Question, MENU_TEXT, EXPLAIN,
                              QMessageBox.Ok | QMessageBox.Cancel, win)
            box.button(QMessageBox.Ok).setText("Turn On")
            if box.exec() != QMessageBox.Ok:
                a.blockSignals(True)
                a.setChecked(False)
                a.blockSignals(False)
                return
        set_on(on)
    a.toggled.connect(toggled)
    if before is not None:
        menu.insertAction(before, a)
    else:
        menu.addAction(a)
    return a
