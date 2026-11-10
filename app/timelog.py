"""Automatic time log per job (Nov 3, Jon approved Chief's list, #4): how
long someone actively works on each job, per sheet, split into takeoff
(a measuring or counting tool in use) and review / estimating (anything
else). It pauses when nobody has touched the mouse or keyboard for
IDLE_SECONDS, when QuantiSheet isn't the active window, or with no
drawing open. Kept on this computer (timelog.json in the data folder);
Tools > Time Log shows it and exports CSV. Not payroll time.
"""
import csv
import datetime
import json
import os
import threading
import time
from .dmoney import c2 as _c2

TICK_SECONDS = 10
IDLE_SECONDS = 120
S_ON = "time_log_on"
TAKEOFF_PREFIX = ("measure_", "count", "symbol", "auto_area", "trace_",
                  "calibrate")
_lock = threading.Lock()


def path():
    from . import settings
    return os.path.join(settings.DIR, "timelog.json")


def load():
    try:
        with open(path(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save(data):
    from . import safeio
    os.makedirs(os.path.dirname(path()), exist_ok=True)
    safeio.atomic_write(path(), json.dumps(data, indent=1))


def kind_of(tool):
    return "takeoff" if tool and str(tool).startswith(TAKEOFF_PREFIX) \
        else "review"


def add(data, job, sheet, kind, seconds, day=None):
    """Add `seconds` to job > day > sheet > kind (in place)."""
    day = day or datetime.date.today().isoformat()
    j = data.setdefault(job, {"name": os.path.basename(job) or job,
                              "days": {}})
    s = j["days"].setdefault(day, {}).setdefault(sheet, {})
    s[kind] = round(s.get(kind, 0) + seconds, 1)
    return data


def rows(data=None):
    """[{job, name, day, sheet, takeoff_min, review_min, total_min}]."""
    data = load() if data is None else data
    out = []
    for job, j in sorted(data.items()):
        for day, sheets in sorted((j.get("days") or {}).items()):
            for sheet, k in sorted(sheets.items()):
                t, r = k.get("takeoff", 0) / 60, k.get("review", 0) / 60
                out.append({"job": job, "name": j.get("name", ""),
                            "day": day, "sheet": sheet,
                            "takeoff_min": _c2(t),
                            "review_min": _c2(r),
                            "total_min": _c2(t + r)})
    return out


def totals(data=None):
    """{job name: {"takeoff_min", "review_min", "total_min"}}."""
    out = {}
    for r in rows(data):
        t = out.setdefault(r["name"], {"takeoff_min": 0.0,
                                       "review_min": 0.0, "total_min": 0.0})
        for k in t:
            t[k] = _c2(t[k] + r[k])
    return out


def export_csv(target, data=None):
    with open(target, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Job", "File", "Day", "Sheet", "Takeoff (min)",
                    "Review / estimating (min)", "Total (min)"])
        for r in rows(data):
            w.writerow([r["name"], r["job"], r["day"], r["sheet"],
                        r["takeoff_min"], r["review_min"], r["total_min"]])
    return target


def enabled():
    try:
        from . import settings
        return settings.get(S_ON, True) is not False
    except Exception:                                     # noqa: BLE001
        return True


class TimeLogger:
    """Counts active time for a main window. tick() is called every
    TICK_SECONDS by a timer; touch() on every mouse / key event."""

    def __init__(self, win, clock=time.monotonic):
        self.win = win
        self.clock = clock
        self.last_input = clock()
        self.data = load()
        self.dirty = 0
        self._sheets = {}

    def touch(self):
        self.last_input = self.clock()

    def where(self):
        """(job key, sheet label, kind) or None when nothing counts."""
        w = self.win
        v = getattr(w, "_view", None)
        if v is None or getattr(v, "doc", None) is None:
            return None
        job = getattr(w, "_path", None) or getattr(v, "_path", None)
        if not job:
            return None
        key = (id(v.doc), v.page)
        sheet = self._sheets.get(key)
        if sheet is None:                 # read once per page, not per tick
            sheet = f"Page {v.page + 1}"
            try:
                from . import sheets
                n, _t = sheets.sheet_info(sheets.page_words(v.pg),
                                          v.pg.rect.width, v.pg.rect.height)
                if n:
                    sheet = n
            except Exception:                             # noqa: BLE001
                pass
            self._sheets[key] = sheet
        return job, sheet, kind_of(getattr(v, "tool", None))

    def tick(self, seconds=TICK_SECONDS, active=None):
        if not enabled():
            return False
        if self.clock() - self.last_input > IDLE_SECONDS:
            return False                      # idle: paused
        if active is None:
            try:
                active = self.win.isActiveWindow()
            except Exception:                             # noqa: BLE001
                active = False
        if not active:
            return False
        at = self.where()
        if at is None:
            return False
        with _lock:
            add(self.data, *at, seconds)
            self.dirty += 1
            if self.dirty >= 6:              # about once a minute
                self.flush()
        return True

    def flush(self):
        if self.dirty:
            try:
                save(self.data)
            except OSError:
                pass
            self.dirty = 0


def install(app, win):
    """Start counting for `win` (an app-wide filter sees the input)."""
    from PySide6.QtCore import QEvent, QObject, QTimer
    logger = TimeLogger(win)

    class _Filter(QObject):
        KINDS = {QEvent.MouseButtonPress, QEvent.KeyPress, QEvent.Wheel,
                 QEvent.MouseMove}

        def eventFilter(self, obj, ev):           # noqa: N802
            if ev.type() in self.KINDS:
                logger.touch()
            return False
    f = _Filter(app)
    app.installEventFilter(f)
    t = QTimer(app)
    t.setInterval(TICK_SECONDS * 1000)
    t.timeout.connect(lambda: logger.tick())
    t.start()
    app.aboutToQuit.connect(logger.flush)
    win._timelog = logger
    win._timelog_parts = (f, t)
    return logger
