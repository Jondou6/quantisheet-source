"""Nov 3 (#4): automatic time log per job and sheet. Made-up jobs."""
import os
from types import SimpleNamespace

import pytest

from app import timelog


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    from app import settings
    monkeypatch.setattr(settings, "DIR", str(tmp_path))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)
    return tmp_path


def _win(tool=None, page=0):
    v = SimpleNamespace(doc=object(), page=page, tool=tool, pg=None,
                        _path="C:/jobs/Office.pdf")
    return SimpleNamespace(_view=v, _path="C:/jobs/Office.pdf",
                           isActiveWindow=lambda: True)


def test_counts_active_time_and_pauses_when_idle(cfg):
    now = [1000.0]
    lg = timelog.TimeLogger(_win("measure_area"), clock=lambda: now[0])
    lg._sheets[(id(lg.win._view.doc), 0)] = "A-101"
    assert lg.tick(10)
    lg.win._view.tool = None
    assert lg.tick(10)
    now[0] += timelog.IDLE_SECONDS + 1          # nobody touched it
    assert not lg.tick(10)
    lg.touch()
    assert not lg.tick(10, active=False)        # another program in front
    lg.flush()
    r = timelog.rows()
    assert len(r) == 1 and r[0]["sheet"] == "A-101"
    assert r[0]["takeoff_min"] == pytest.approx(10 / 60, abs=0.01)
    assert r[0]["total_min"] == pytest.approx(20 / 60, abs=0.01)
    assert timelog.totals()["Office.pdf"]["total_min"] > 0


def test_no_drawing_or_switched_off(cfg):
    from app import settings
    lg = timelog.TimeLogger(SimpleNamespace(_view=None, _path=None,
                                            isActiveWindow=lambda: True))
    assert not lg.tick(10)
    settings.set(timelog.S_ON, False)
    lg2 = timelog.TimeLogger(_win())
    assert not lg2.tick(10)


def test_csv_and_kinds(cfg, tmp_path):
    d = timelog.add({}, "C:/a.pdf", "A-1", "takeoff", 600, "2026-11-03")
    timelog.add(d, "C:/a.pdf", "A-1", "review", 300, "2026-11-03")
    p = timelog.export_csv(str(tmp_path / "t.csv"), d)
    text = open(p, encoding="utf-8").read()
    assert "A-1" in text and "10.0" in text and "15.0" in text
    assert timelog.kind_of("count") == "takeoff"
    assert timelog.kind_of("add_cloud") == "review"


def test_window(cfg):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    timelog.save(timelog.add({}, "C:/a.pdf", "A-1", "takeoff", 600))
    from app import timelog_ui
    w = timelog_ui.TimeLogDialog()
    assert w.jobs.rowCount() == 1 and w.detail.rowCount() == 1
    w.on.setChecked(False)
    assert not timelog.enabled()
