"""Freeze recorder.

A timer on the window's thread re-arms a watchdog every second. If the
window stops responding for FREEZE_SECONDS, the watchdog (running on its
own thread) writes every thread's Python stack to crash.log - so a freeze
that ends with Windows closing the program still says what it was stuck
on. When the window comes back, the length of the freeze goes in
quantisheet.log.
"""
import datetime
import faulthandler
import logging
import time

from PySide6.QtCore import QObject, QTimer

FREEZE_SECONDS = 10
TICK_MS = 1000

log = logging.getLogger("quantisheet")


class FreezeWatch(QObject):
    def __init__(self, file, seconds=FREEZE_SECONDS, parent=None):
        super().__init__(parent)
        self.file = file
        self.seconds = seconds
        self.last = time.monotonic()
        self.freezes = []                 # (when, seconds) - for tests
        self.timer = QTimer(self)
        self.timer.setInterval(TICK_MS)
        self.timer.timeout.connect(self.tick)

    def start(self):
        self._arm()
        self.timer.start()
        return self

    def stop(self):
        self.timer.stop()
        try:
            faulthandler.cancel_dump_traceback_later()
        except Exception:                                  # noqa: BLE001
            pass

    def _arm(self):
        try:
            # re-arming replaces the previous countdown
            faulthandler.dump_traceback_later(self.seconds, repeat=False,
                                              file=self.file, exit=False)
        except Exception:                                  # noqa: BLE001
            log.debug("freeze watch not armed", exc_info=True)

    def tick(self):
        now = time.monotonic()
        gap = now - self.last
        self.last = now
        if gap >= self.seconds:
            self.freezes.append((datetime.datetime.now(), gap))
            log.warning("the window was frozen for %.0f s; what it was "
                        "doing is in crash.log", gap)
            try:
                ended = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self.file.write(f"--- above: window frozen {gap:.0f} s, "
                                f"ended {ended} ---\n")
                self.file.flush()
            except Exception:                              # noqa: BLE001
                pass
        self._arm()


def install(app, file, seconds=FREEZE_SECONDS):
    """Start watching; returns the watcher (kept alive by the app)."""
    if file is None:
        return None
    w = FreezeWatch(file, seconds, parent=app)
    return w.start()
