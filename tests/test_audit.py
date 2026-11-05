"""Measurement audit trail and takeoff search across jobs."""
import os

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import (annotate, assemblies, audit, autocount, pricedb,  # noqa
                 revisions, settings)
from test_gui import win, qapp                               # noqa: E402,F401
from test_planswift import _job, WALL                        # noqa: E402


@pytest.fixture(autouse=True)
def _own_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(assemblies, "LIBRARY_PATH",
                        str(tmp_path / "assemblies.json"))
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)
    pricedb.state.update(offline="", copied=0.0)


def test_every_measurement_says_who_how_and_at_what_scale():
    d = _job()
    rows = audit.trail(d)
    assert len(rows) == 4
    wall = next(r for r in rows if r["group"] == WALL)
    assert wall["method"] == "manual" and wall["author"]
    assert wall["taken"][:4].isdigit() and wall["revision"] == "Original"
    assert "18" in wall["scale"]
    # automatic counts carry their method and confidence
    marks = autocount.count_marks([{"page": 0, "rect": [10, 10, 20, 20],
                                    "score": 0.81}], "Outlet", d)
    for p, k, payload in marks:
        annotate.apply_op(d, annotate.new_op(k, p, **payload))
    out = next(r for r in audit.trail(d) if r["group"] == "Outlet")
    assert out["method"] == "auto count" and out["confidence"] == 0.81
    s = audit.summary(audit.trail(d))
    assert s["methods"]["manual"] == 4 and s["low_confidence"] == 1


def test_carried_takeoff_says_so():
    old = _job()
    new = fitz.open()
    new.new_page(width=old[0].rect.width, height=old[0].rect.height)
    res = [{"old": 0, "new": 0, "sheet": "", "align": overlay_id(),
            "changes": [], "changed_pct": 0}]
    marks, _ = revisions.carry_ops(old, new, res)
    for p, k, payload in marks:
        annotate.apply_op(new, annotate.new_op(k, p, **payload))
    rows = audit.trail(new)
    assert rows and all(r["method"] == "carried" for r in rows)


def overlay_id():
    from app import overlay
    return overlay.IDENTITY


def test_mirror_and_search_across_jobs(tmp_path):
    a, b = _job(), _job()
    fa, fb = str(tmp_path / "Clinic.pdf"), str(tmp_path / "School.pdf")
    assert audit.mirror(a, file=fa) == 4
    assert audit.mirror(b, job="School", file=fb) == 4
    assert audit.mirror(a, file=fa) == 4             # replaces, not adds
    found = audit.search("interior wall")
    assert {r["job"] for r in found} == {"Clinic", "School"}
    tot = audit.totals(found)
    (q, files), = tot.values()
    assert q == pytest.approx(80) and files == 2
    assert audit.search("nothing like this") == []
    out = audit.export_xlsx(audit.trail(a), str(tmp_path / "a.xlsx"))
    assert os.path.getsize(out) > 1000


def test_audit_window(qapp, win, tmp_path):
    d = _job()
    p = tmp_path / "job.pdf"
    d.save(str(p))
    win.open_path(str(p))
    dlg = win.measurement_audit(show=False)
    assert dlg.table.rowCount() == 4 and "4 measurement" in dlg.head.text()
    dlg.filter.setText("door")
    assert dlg.table.rowCount() == 2
    assert dlg.sync() == 4
    assert dlg.search("door") and dlg.results.rowCount() == 2
    assert dlg.export(str(tmp_path / "audit.xlsx"))
