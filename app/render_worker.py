"""The window's side of the drawing process (app/render_proc.py).

One drawing process for the whole program, started the first time it's
needed. Requests go down a pipe; a reader thread waits for replies (the
wait lets go of Python's lock) and hands each one to the window thread,
where its callback runs. If the process can't start, or dies, every
caller falls back to drawing in the window as before.
"""
import itertools
import logging
import multiprocessing
import os
import threading

from PySide6.QtCore import QObject, Signal

from . import render_proc

log = logging.getLogger("quantisheet")

# QUANTISHEET_DRAW_PROCESS=0 draws everything in the window (the tests do,
# apart from the ones about the drawing process)
ENABLED = os.environ.get("QUANTISHEET_DRAW_PROCESS", "1") != "0"


class _Relay(QObject):
    reply = Signal(object)


class RenderWorker:
    def __init__(self):
        self.proc = None
        self.conn = None
        self.ok = False
        self._ids = itertools.count(1)
        self._wait = {}               # rid -> callback (window thread)
        self._lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._relay = _Relay()
        self._relay.reply.connect(self._deliver)
        self._reader = None
        self.failed = False
        self._failed_at = 0.0
        self._starts = 0
        self._gen = 0             # which process replies come from

    # ---- life ---------------------------------------------------------------
    RETRY_AFTER = 20.0        # seconds before starting a new process
    MAX_STARTS = 4            # per session: a process that keeps dying stops

    def start(self):
        import time
        if self.ok or not ENABLED:
            return self.ok
        if self.failed:
            # it died (or never started): try again after a pause, a few
            # times per session, instead of drawing in the window for the
            # rest of the session (review 0.12.12 M1)
            if self._starts >= self.MAX_STARTS or \
                    time.monotonic() - self._failed_at < self.RETRY_AFTER:
                return False
            self.failed = False
            # self._ids keeps counting across restarts, so ids stay unique
            # (re-making the counter here could hand out a duplicate)
        self._starts += 1
        return self._start()

    def _start(self):
        try:
            ctx = multiprocessing.get_context("spawn")
            mine, theirs = ctx.Pipe()
            p = ctx.Process(target=render_proc._serve, args=(theirs,),
                            name="QuantiSheet-draw", daemon=True)
            p.start()
            theirs.close()
            self.proc, self.conn, self.ok = p, mine, True
            self._gen += 1
            self._reader = threading.Thread(target=self._read,
                                            args=(mine, self._gen),
                                            name="draw-replies", daemon=True)
            self._reader.start()
            log.info("drawing process started (pid %s)", p.pid)
        except Exception:                                 # noqa: BLE001
            log.warning("drawing process could not start; drawing in the "
                        "window instead", exc_info=True)
            import time
            self.failed = True
            self._failed_at = time.monotonic()
            self.ok = False
        return self.ok

    def stop(self):
        ok, self.ok = self.ok, False
        if not ok:
            return
        try:
            with self._send_lock:
                self.conn.send(("stop",))
        except Exception:                                 # noqa: BLE001
            pass
        try:
            self.proc.join(2)
            if self.proc.is_alive():
                self.proc.terminate()
        except Exception:                                 # noqa: BLE001
            pass

    def alive(self):
        if self.ok and (self.proc is None or not self.proc.is_alive()):
            self._died()                  # killed or crashed: stop using it
        return self.ok

    # ---- requests -----------------------------------------------------------
    def render(self, path, page, zoom, clip, thin, sig, callback):
        """Ask for the sheet (no markups) at `zoom`; `callback(reply)` runs
        on the window thread with ("img", ...) or ("err", ...) or None if
        the process went away. Returns the request id, or None when the
        caller should draw it itself."""
        if not path or not self.start() or not self.alive():
            return None
        rid = next(self._ids)
        with self._lock:
            self._wait[rid] = callback
        try:
            with self._send_lock:
                self.conn.send(("render", rid, path, page, zoom, clip,
                                bool(thin), sig))
        except Exception:                                 # noqa: BLE001
            with self._lock:
                self._wait.pop(rid, None)
            self._died()
            return None
        return rid

    def segments(self, path, page, sig, callback):
        """The drawing's lines on `page` (for snapping), read in the drawing
        process; `callback` gets ("segs", rid, sig, count, bytes)."""
        if not path or not self.start() or not self.alive():
            return None
        rid = next(self._ids)
        with self._lock:
            self._wait[rid] = callback
        try:
            with self._send_lock:
                self.conn.send(("segments", rid, path, page, sig))
        except Exception:                                 # noqa: BLE001
            with self._lock:
                self._wait.pop(rid, None)
            self._died()
            return None
        return rid

    def count(self, path, callback):
        """Page count of a PDF, opened in the drawing process (a 134 MB set
        took half a second in the window). `callback` gets
        ("count", rid, "12" | "?")."""
        return self._ask(("count", None, path), callback)

    def _ask(self, msg, callback):
        if not msg[-1] or not self.start() or not self.alive():
            return None                    # no file to ask about
        rid = next(self._ids)
        with self._lock:
            self._wait[rid] = callback
        try:
            with self._send_lock:
                self.conn.send((msg[0], rid) + tuple(msg[2:]))
        except Exception:                                 # noqa: BLE001
            with self._lock:
                self._wait.pop(rid, None)
            self._died()
            return None
        return rid

    def forget(self, rid):
        """The caller no longer wants this reply (tab closed, page left)."""
        self.forget_many([rid])

    def forget_many(self, rids):
        """Drop the replies and tell the process not to draw them if it
        hasn't started yet (Grok M10: paging 3 -> 11 used to draw all 8)."""
        rids = [r for r in rids if r is not None]
        if not rids:
            return
        with self._lock:
            for rid in rids:
                self._wait.pop(rid, None)
        if self.ok and self.conn is not None:
            try:
                with self._send_lock:
                    self.conn.send(("cancel", list(rids)))
            except Exception:                             # noqa: BLE001
                pass

    # ---- replies ------------------------------------------------------------
    def _read(self, conn, gen):
        while True:
            try:
                msg = conn.recv()
            except (EOFError, OSError):
                break
            try:
                self._relay.reply.emit((gen, msg))
            except RuntimeError:                  # program shutting down
                return
        try:
            self._relay.reply.emit((gen, None))   # this process is gone
        except RuntimeError:
            pass

    def _died(self):
        import time
        if self.ok:
            log.warning("drawing process stopped; drawing in the window, "
                        "a new one starts in %.0f s", self.RETRY_AFTER)
            self._failed_at = time.monotonic()
        elif not self.failed:
            self._failed_at = time.monotonic()
        self.ok = False
        self.failed = True
        try:
            if self.proc is not None and self.proc.is_alive():
                self.proc.terminate()
        except Exception:                                 # noqa: BLE001
            pass
        # everyone still waiting gets "gone" (they draw it themselves) -
        # later, on the window thread, never in the middle of a request
        # Only the requests waiting right now: one made after a restart
        # but before the timer fires must keep its real reply (Venice N-6)
        with self._lock:
            waiting, self._wait = self._wait, {}
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, lambda: self._flush(waiting))

    def _flush(self, waiting=None):
        if waiting is None:
            with self._lock:
                waiting, self._wait = self._wait, {}
        for cb in waiting.values():
            self._call(cb, None)

    def _deliver(self, item):
        gen, msg = item
        if msg is None:                           # a process went away
            if gen == self._gen and self.ok:      # the current one
                self._died()
            return                                # an old one: ignore
        with self._lock:
            cb = self._wait.pop(msg[1], None)
        if cb is not None:
            self._call(cb, msg)

    @staticmethod
    def _call(cb, msg):
        try:
            cb(msg)
        except Exception:                                 # noqa: BLE001
            log.exception("drawing reply handler failed")


_worker = None


def get():
    global _worker
    if _worker is None:
        _worker = RenderWorker()
        import atexit
        atexit.register(_worker.stop)
    return _worker


def page_sig(doc, pno):
    return render_proc.page_sig(doc, pno)
