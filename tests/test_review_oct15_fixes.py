"""Regression tests for the Oct 15 code review (bg worker lifetime, Ollama
failure handling, takeoff geometry)."""
import http.client
import io
import json
import os
import threading
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz  # noqa: E402
import shiboken6  # noqa: E402
from PySide6.QtCore import QObject, QThreadPool  # noqa: E402
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


def _pump(qapp, secs=0.3):
    QThreadPool.globalInstance().waitForDone(5000)
    end = time.time() + secs
    while time.time() < end:
        qapp.processEvents()
        time.sleep(0.01)


# ---- bg: worker / signal lifetime ------------------------------------------

class _DeadSignal:
    def emit(self, *a):
        raise RuntimeError("Signal source has been deleted")


class _DeadSignals:
    done = _DeadSignal()
    failed = _DeadSignal()


@pytest.mark.parametrize("fail", [False, True])
def test_worker_survives_deleted_signal_source(fail):
    """The logged crash: emit() after the signal object was deleted must not
    escape the worker thread as an unhandled error."""
    def fn():
        if fail:
            raise review.AIError("Ollama error 500: token repeat limit")
        return 1
    job = bg._Job(fn)
    job.signals = _DeadSignals()
    job.run()                                  # must not raise


def test_owner_deleted_before_job_finishes(qapp):
    """Closing the dialog that started an AI job: no callback runs on the
    dead dialog and the job's bookkeeping is released (no leak)."""
    before = len(bg._jobs)
    go = threading.Event()
    got = []
    owner = QObject()
    bg.run(lambda: go.wait(5) and 1, got.append, got.append, owner)
    shiboken6.delete(owner)
    go.set()
    _pump(qapp)
    assert got == []
    assert len(bg._jobs) == before


def test_callback_error_is_contained(qapp, caplog):
    owner = QObject()

    def boom(_):
        raise RuntimeError("Internal C++ object already deleted")
    bg.run(lambda: 1, boom, boom, owner)
    _pump(qapp)                                # must not raise
    assert len([j for j in bg._jobs if j.parent() is owner]) == 0


def test_normal_paths_still_deliver(qapp):
    owner = QObject()
    got = []
    bg.run(lambda: 42, got.append, lambda m: got.append(("err", m)), owner)
    bg.run(lambda: 1 / 0, got.append, lambda m: got.append(("err", m)), owner)
    _pump(qapp)
    assert 42 in got and ("err", "division by zero") in got


# ---- Ollama failures degrade to AIError ------------------------------------

class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.mark.parametrize("body", [
    b'{"error": "model requires more system memory"}',   # 200 with error
    b"<html>proxy error</html>",                          # not JSON
    b'["unexpected"]',                                    # wrong shape
])
def test_ollama_bad_reply_is_aierror(monkeypatch, body):
    monkeypatch.setattr(review.urllib.request, "urlopen",
                        lambda *a, **k: _Resp(body))
    with pytest.raises(review.AIError):
        review._ollama("hi")


def test_ollama_dropped_connection_is_aierror(monkeypatch):
    def drop(*a, **k):
        raise http.client.IncompleteRead(b"partial")
    monkeypatch.setattr(review.urllib.request, "urlopen", drop)
    with pytest.raises(review.AIError):
        review._ollama("hi")


def test_ollama_good_reply(monkeypatch):
    monkeypatch.setattr(review.urllib.request, "urlopen",
                        lambda *a, **k: _Resp(json.dumps(
                            {"response": "ok"}).encode()))
    assert review._ollama("hi") == "ok"


# ---- takeoff math against known geometry -----------------------------------

P = fitz.Point


def test_quarter_inch_scale_rectangle():
    # 1/4" = 1'-0"  ->  18 pt per foot
    cal = takeoff.Calibration(P(0, 0), P(180, 0), 10, "ft")
    assert cal.points_per_unit == pytest.approx(18)
    assert takeoff.PRESETS["Architectural"][4][1] == (18.0, "ft")
    rect = [P(0, 0), P(180, 0), P(180, 360), P(0, 360)]     # 10 ft x 20 ft
    assert takeoff.area(cal, rect) == pytest.approx(200.0)
    assert takeoff.polygon_area(rect) / 18 ** 2 == pytest.approx(200.0)
    assert takeoff.path_length(rect + rect[:1]) / 18 == pytest.approx(60.0)
    # vertex order (clockwise vs counter-clockwise) doesn't change area
    assert takeoff.area(cal, rect[::-1]) == pytest.approx(200.0)


def test_diagonal_calibration_and_triangle():
    # 3-4-5 triangle: calibrate on the 5 ft hypotenuse drawn diagonally
    cal = takeoff.Calibration(P(0, 0), P(36, 48), 5, "ft")   # 60 pt = 5 ft
    assert takeoff.distance(cal, P(0, 0), P(36, 0)) == pytest.approx(3.0)
    assert takeoff.area(cal, [P(0, 0), P(36, 0), P(36, 48)]) == \
        pytest.approx(6.0)


def test_engineering_and_metric_scales():
    ppu, unit = takeoff._eng(20)                 # 1" = 20'
    assert unit == "ft" and 720 / ppu == pytest.approx(200.0)
    ppu, unit = takeoff._metric(100)             # 1:100, 100 mm paper = 10 m
    assert unit == "m" and (100 / 25.4 * 72) / ppu == pytest.approx(10.0)
    assert takeoff.convert(10, "m", "ft") == pytest.approx(32.8084, rel=1e-6)


def test_feet_inch_rounding():
    assert takeoff.fmt(12.5, "ft") == "12' 6\""
    assert takeoff.fmt(12.9999, "ft") == "13' 0\""
    assert takeoff.fmt(-2.5, "ft") == "-2' 6\""
    assert takeoff.parse_length("4'-6 1/2\"")[0] == pytest.approx(4 + 6.5 / 12)


def test_bad_calibration_rejected():
    with pytest.raises(ValueError):
        takeoff.Calibration(P(1, 1), P(1, 1), 10)
    with pytest.raises(ValueError):
        takeoff.Calibration(P(0, 0), P(10, 0), 0)
