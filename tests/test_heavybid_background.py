"""Export to HeavyBid runs the civil takeoff off the window's thread (on
its own copy of the PDF), then finishes the export."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from test_gui import win, qapp                                # noqa: E402,F401


def test_takeoff_runs_in_background_then_exports(win, tmp_path, monkeypatch):
    from app import annotate, bg, civiltakeoff, heavy, main_window
    from test_civil_export import _result
    monkeypatch.setattr(annotate, "read_scales",
                        lambda d: {0: {"ppu": 10.0, "unit": "ft"}})
    monkeypatch.setattr(heavy, "civil_pages", lambda d: [0])
    monkeypatch.setattr(heavy, "pipe_plan_pages", lambda d, p=None: [0])
    seen = {}

    def fake_takeoff(doc, pages, scales):
        seen["doc"] = doc
        return _result()
    monkeypatch.setattr(civiltakeoff, "takeoff", fake_takeoff)
    jobs = []
    monkeypatch.setattr(bg, "run", lambda fn, ok, err, owner:
                        jobs.append((fn, ok, err)))
    monkeypatch.setattr(main_window.QMessageBox, "information",
                        lambda *a, **k: 0)
    folder = str(tmp_path / "hb")
    assert win.export_heavybid(folder=folder, soil="B") is None
    assert len(jobs) == 1 and win._hb_progress is not None
    fn, ok, _err = jobs[0]
    r = fn()                                    # the worker thread's part
    assert seen["doc"] is not win._view.doc     # its own copy
    ok(r)                                       # back on the window
    assert win._hb_progress is None
    names = os.listdir(folder)
    assert any("iditem" in n.lower() for n in names), names


def test_no_scales_answers_at_once(win, monkeypatch):
    from app import annotate, bg, heavy, main_window
    monkeypatch.setattr(annotate, "read_scales", lambda d: {})
    monkeypatch.setattr(heavy, "civil_pages", lambda d: (_ for _ in ()).throw(
        AssertionError("read every title block")))
    jobs, said = [], []
    monkeypatch.setattr(bg, "run", lambda *a: jobs.append(a))
    monkeypatch.setattr(main_window.QMessageBox, "information",
                        lambda *a, **k: said.append(a[2]))
    assert win.export_heavybid(folder="x", soil="B") is None
    assert not jobs and "scale" in said[0]
