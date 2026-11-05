"""Run slow work (AI calls, OCR) off the GUI thread so the window stays
responsive. Results come back on the GUI thread.

Lifetime rules (see the Oct 15 review and STRESS.md):
* the worker's signal object is owned by a GUI-thread parent and is only
  ever deleted on the GUI thread (deleteLater), after its worker finished,
  so a worker dropping the last Python reference can't free it off-thread;
* the job is handed to QThreadPool as a plain callable: a QRunnable with
  autoDelete off is never released by PySide, so every job used to leak;
* a failed emit (``Signal source has been deleted``) is logged, never raised
  out of the worker thread;
* the relay (receiver) is owned by the same GUI-thread parent, not by the
  owner, and has no connection to the owner: it always gets its one result,
  skips the callbacks if the owner (usually a dialog) has been destroyed,
  and then deletes itself (deleteLater, so never mid-dispatch);
* an exception raised by a callback is logged instead of escaping the slot.
"""
import logging
import threading

import shiboken6
from PySide6.QtCore import QObject, QThreadPool, Signal, Slot

log = logging.getLogger("quantisheet")

_jobs = set()       # relays waiting for their job to report back
_live = set()       # _Job objects (and their signals) until their thread ends
_lock = threading.Lock()
_keeper = None      # GUI-thread parent of the signal objects and relays


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(str)


class _Job:
    def __init__(self, fn):
        self.fn = fn
        self.finished = False
        self.signals = _Signals()

    def _emit(self, sig, value):
        try:
            sig.emit(value)
        except RuntimeError as e:          # receiver/source already gone
            log.warning("background job result dropped: %s", e)

    def run(self):
        try:
            try:
                result = self.fn()
            except Exception as e:
                log.info("background job failed: %s", e, exc_info=True)
                self._emit(self.signals.failed,
                           str(e) or e.__class__.__name__)
            else:
                self._emit(self.signals.done, result)
        finally:
            self.finished = True       # released later, on the GUI thread


def _signals_parent():
    global _keeper
    if _keeper is None or not shiboken6.isValid(_keeper):
        _keeper = QObject()
    return _keeper


def _prune():
    """GUI thread: free the signal objects of jobs whose threads are done."""
    with _lock:
        done = [j for j in _live if j.finished]
        _live.difference_update(done)
    for j in done:
        if shiboken6.isValid(j.signals):
            j.signals.deleteLater()


def run(fn, on_done, on_error, owner, pool=None):
    """Call fn() on a worker thread; then on_done(result) or on_error(msg)
    on the GUI thread. `owner` is a QObject living on the GUI thread; once
    it is destroyed the callbacks are skipped. `pool` is a QThreadPool to
    run on instead of the global one (a feature whose slow network jobs
    mustn't queue behind - or hold up - everything else)."""
    _prune()
    job = _Job(fn)
    job.signals.setParent(_signals_parent())
    relay = _Relay(owner, on_done, on_error)
    job.signals.done.connect(relay.done)
    job.signals.failed.connect(relay.failed)
    _jobs.add(relay)
    with _lock:
        _live.add(job)
    (pool if pool is not None else QThreadPool.globalInstance()).start(
        job.run)
    return relay


class _Relay(QObject):
    """Receiver living on the GUI thread, so signals queue onto it."""

    def __init__(self, owner, on_done, on_error):
        # owned by the GUI-thread keeper (not the owner, not Python), so it
        # is freed by deleteLater after its slot returns, never mid-dispatch
        super().__init__(_signals_parent())
        self._owner = owner
        self._done, self._error = on_done, on_error

    def _deliver(self, cb, value):
        _jobs.discard(self)
        owner = self._owner
        self._done = self._error = self._owner = None
        try:
            if cb is None or (owner is not None and
                              not shiboken6.isValid(owner)):
                return
            try:
                cb(value)
            except Exception:
                log.exception("background job callback failed")
        finally:
            if shiboken6.isValid(self):
                self.deleteLater()
            _prune()

    @Slot(object)
    def done(self, result):
        self._deliver(self._done, result)

    @Slot(str)
    def failed(self, msg):
        self._deliver(self._error, msg)
