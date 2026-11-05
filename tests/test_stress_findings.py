"""Regressions found by the Oct 15 stress run (see STRESS.md)."""
import gc
import io
import json
import math
import os
import time
import weakref

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz  # noqa: E402
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QThreadPool  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app import bg, takeoff  # noqa: E402
from app.ai import review  # noqa: E402


@pytest.fixture(autouse=True)
def _fake_ai_requests_through_urlopen(monkeypatch):
    """AI requests go through review._opener() (no proxy, no redirects -
    threat model T-009); these tests fake urllib.request.urlopen, so the
    opener hands its requests to whatever urlopen is patched in - nothing
    reaches a real Ollama on the test PC."""
    from app.ai import review as _rv

    class _Op:
        def open(self, req, timeout=None):
            return _rv.urllib.request.urlopen(req, timeout=timeout)
    monkeypatch.setattr(_rv, "_opener", lambda: _Op())


@pytest.fixture
def qapp():
    return QApplication.instance() or QApplication([])


def _pump(qapp, secs=0.2):
    QThreadPool.globalInstance().waitForDone(5000)
    end = time.time() + secs
    while time.time() < end:
        qapp.processEvents()
        # deleteLater() runs when control returns to the event loop; there is
        # none in a test, so flush the deferred deletes by hand
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        time.sleep(0.01)


def _count(name):
    gc.collect()
    return sum(1 for o in gc.get_objects() if type(o).__name__ == name
               and type(o).__module__ == bg.__name__)


def test_finished_jobs_are_released(qapp):
    """Every job used to stay alive forever (QThreadPool kept a reference to
    a non-autodelete QRunnable)."""
    _pump(qapp)
    bg.run(lambda: 0, lambda r: None, lambda m: None, None)
    _pump(qapp)
    before = _count("_Signals")
    for _ in range(200):
        bg.run(lambda: 1, lambda r: None, lambda m: None, None)
    _pump(qapp)
    bg.run(lambda: 0, lambda r: None, lambda m: None, None)   # prunes
    _pump(qapp)
    assert _count("_Signals") - before < 5


def test_relays_do_not_pile_up_on_a_long_lived_owner(qapp):
    """A relay is a child of its owner; on the main window that meant one
    leaked QObject per AI call."""
    owner = QObject()
    got = []
    for i in range(50):
        bg.run(lambda i=i: i, got.append, got.append, owner)
    _pump(qapp)
    assert len(got) == 50
    _pump(qapp)
    assert owner.findChildren(bg._Relay) == []
    assert _count("_Relay") < 5


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.mark.parametrize("reply", [{"response": None}, {"response": 5},
                                   {"response": ["a"]}])
def test_non_text_response_is_a_clean_ai_error(monkeypatch, reply):
    monkeypatch.setattr(review.urllib.request, "urlopen",
                        lambda *a, **k: _Resp(json.dumps(reply).encode()))
    for fn in (review.redline_from_text, review.spec_from_text,
               review.summarize_text):
        with pytest.raises(review.AIError):
            fn("hello")
    with pytest.raises(review.AIError):
        review.translate_texts(["hi"], "French")


@pytest.mark.parametrize("real", [float("nan"), float("inf")])
def test_calibration_rejects_non_finite_distance(real):
    with pytest.raises(ValueError):
        takeoff.Calibration(fitz.Point(0, 0), fitz.Point(72, 0), real)


@pytest.mark.parametrize("v", [float("nan"), float("inf"), float("-inf")])
def test_fmt_non_finite_does_not_raise(v):
    s = takeoff.fmt(v, "ft")
    assert isinstance(s, str) and s


_CHURN = r'''
import gc, os, random, sys, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, sys.argv[1])
import shiboken6
from PySide6.QtCore import QCoreApplication, QObject, QThreadPool
from PySide6.QtWidgets import QApplication
app = QApplication([])
from app import bg
random.seed(7)
def fn(i=0):
    time.sleep(random.random() * 0.005)
    if i % 7 == 0:
        gc.collect()
    if i % 4 == 1:
        raise ValueError("boom")
    return i
for r in range(150):
    o = QObject()
    for i in range(20):
        bg.run(lambda i=i: fn(i), lambda v: None, lambda m: None,
               o if i % 5 else None)
    if r % 2:
        shiboken6.delete(o)
    else:
        del o
    QCoreApplication.processEvents()
QThreadPool.globalInstance().waitForDone(30000)
for _ in range(50):
    QCoreApplication.processEvents()
print("ok")
'''


def test_job_churn_with_owners_deleted_mid_flight_does_not_abort(tmp_path):
    """3,000 jobs, owners destroyed while their jobs run, GC on workers:
    the process must not abort (signal objects freed off the GUI thread)."""
    import subprocess
    import sys
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = tmp_path / "churn.py"
    script.write_text(_CHURN)
    p = subprocess.run([sys.executable, str(script), root], capture_output=True,
                       text=True, timeout=180)
    assert p.returncode == 0 and "ok" in p.stdout, p.stderr[-2000:]
