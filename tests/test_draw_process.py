"""Stage 4: sheets drawn in a separate process so the window never waits.

MuPDF keeps Python's lock while drawing, so a thread froze the window as
much as drawing in it did (0.85 s gaps on the 309-sheet plant set).
"""
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz                                                    # noqa: E402
import pytest                                                  # noqa: E402

from app import render_worker                                  # noqa: E402

from test_gui import win, qapp                                 # noqa: E402,F401


@pytest.fixture
def drawer(monkeypatch):
    monkeypatch.setattr(render_worker, "ENABLED", True)
    render_worker._worker = None
    w = render_worker.get()
    yield w
    w.stop()
    render_worker._worker = None


def _wait(qapp, cond, secs=30):
    end = time.time() + secs
    while not cond() and time.time() < end:
        qapp.processEvents()
        time.sleep(0.02)
    return cond()


def test_the_process_draws_a_page(qapp, win, drawer):
    v = win._view
    got = {}
    sig = render_worker.page_sig(v.doc, 0)
    rid = drawer.render(v._path, 0, 1.0, None, True, sig,
                        lambda m: got.setdefault("m", m))
    assert rid is not None
    assert _wait(qapp, lambda: "m" in got)
    m = got["m"]
    assert m[0] == "img" and tuple(m[2]) == sig
    r = v.doc[0].rect
    assert abs(m[5] - r.width) <= 2 and abs(m[6] - r.height) <= 2


def test_pages_drawn_ahead_come_from_the_process_with_markups(qapp, win,
                                                             drawer):
    v = win._view
    assert v.doc.page_count >= 2
    # an unsaved markup on page 2 must still show on the drawn-ahead page
    p2 = v.doc[1]
    a = p2.add_rect_annot(fitz.Rect(20, 20, 220, 220))
    a.set_colors(stroke=(1, 0, 0), fill=(1, 0, 0))
    a.update()
    v._pf_forget()
    v.go_to(0)
    qapp.processEvents()
    v._prefetch()
    assert v._pf_pending, "nothing was asked of the drawing process"
    assert _wait(qapp, lambda: not v._pf_pending)
    keys = [k for k in v._prefetched if k[1] == 1]
    assert keys, "page 2 was not drawn ahead"
    qp = v._prefetched[keys[0]][0]
    img = qp.toImage()
    dpr = qp.devicePixelRatio() or 1
    zoom = keys[0][3]
    c = img.pixelColor(int(120 * zoom), int(120 * zoom))
    assert c.red() > 200 and c.green() < 80, c.name()   # the red markup
    del dpr


def test_unsaved_page_edits_are_drawn_in_the_window(qapp, win, drawer):
    v = win._view
    v.doc[1].insert_text((72, 300), "CHANGED BUT NOT SAVED", fontsize=20)
    v._pf_forget()
    v.go_to(0)
    qapp.processEvents()
    v._prefetch()
    _wait(qapp, lambda: not v._pf_pending)
    # the file on disk differs from the open page: nothing stale stored
    assert not [k for k in v._prefetched if k[1] == 1]


def test_sharp_tiles_come_from_the_process(qapp, win, drawer):
    v = win._view
    v.go_to(0)
    v.set_zoom(4.0)
    qapp.processEvents()
    assert not v._full                    # zoomed past the preview
    # what painting the top-left of the page asks for (the offscreen test
    # window is never painted by itself)
    key = (v._gen, round(v.zoom, 4))
    v._want = [key + (0, 0), key + (1, 0), key + (0, 1)]
    v._render_tiles()
    assert v._tile_pending, "tiles were not handed to the drawing process"
    ok = _wait(qapp, lambda: len(v._tiles) > 0 and not v._tile_pending)
    assert ok, dict(tiles=len(v._tiles), pending=len(v._tile_pending),
                    want=len(v._want), full=v._full, shown=v.isVisible(),
                    size=v._size, zoom=v.zoom, drawer=drawer.ok,
                    here=getattr(v, "_tiles_here", None), gen=v._gen,
                    timer=v._tile_timer.isActive())


def test_a_dead_process_falls_back_to_the_window(qapp, win, drawer):
    v = win._view
    assert drawer.start()
    drawer.proc.terminate()
    drawer.proc.join(5)
    assert drawer.render(v._path, 0, 1.0, None, True, None,
                         lambda m: None) is None
    assert not drawer.ok
    v._pf_forget()
    v.go_to(0)
    v._prefetch()                       # draws here instead, no error
    assert not v._pf_pending


def test_off_by_default_in_tests():
    assert os.environ.get("QUANTISHEET_DRAW_PROCESS") == "0"


def test_snap_lookup_is_built_off_the_window(qapp, win, drawer):
    """Sheet 215 of the plant set: 250,000 lines, 3.5 s of frozen window
    while snapping got ready. Now the lines are read in the drawing process
    and the lookup is built on a background thread."""
    v = win._view
    v.go_to(0)
    v.snap_enabled = True
    key = (id(v.doc), v.page, v.pg.rotation)
    v._snap_cache = None
    first = v.snap_index()                   # returns at once, no snapping
    assert getattr(v, "_snap_building", None) == key
    assert not first.segs
    assert _wait(qapp, lambda: v._snap_cache is not None and
                 v._snap_cache[0] == key)
    idx = v.snap_index()
    assert len(idx.segs) > 10                 # the sheet's lines are there
    import app.snap as snap
    local = snap.SnapIndex(snap.page_segments(v.pg),
                           clip=snap.page_clip(v.pg))
    assert len(idx.segs) == len(local.segs)   # same answer as in the window


def test_jumping_to_a_page_never_waits(qapp, win, drawer):
    """Typing 215 in the page box used to draw that sheet in the window
    (up to 1.2 s). Now the sheet shows blank at once and fills in."""
    v = win._view
    v._pf_forget()
    last = v.doc.page_count - 1
    v.go_to(0)
    qapp.processEvents()
    v._prefetched.clear()
    v._pf_pending.clear()
    v.go_to(last)
    v._render()                         # what the page change does
    assert v.rendered is None           # blank for now, no waiting
    assert v._pf_pending
    assert _wait(qapp, lambda: v.rendered is not None)
    assert v.page == last


def test_documents_panel_counts_pages_in_the_process(qapp, drawer,
                                                     tmp_path):
    """Opening a 134 MB set to count its pages froze the window for half a
    second; the drawing process counts them now."""
    import make_sample
    from app import docks
    for i in range(3):
        make_sample.make(str(tmp_path / f"sheet{i}.pdf"))
    (tmp_path / "broken.pdf").write_bytes(b"not a pdf")
    d = docks.DocumentsPanel(str(tmp_path))
    d.show()
    d.refresh()
    d._count_timer.start()

    def counts():
        out = {}
        for i in range(d.tree.topLevelItemCount()):
            it = d.tree.topLevelItem(i)
            out[it.text(0)] = it.text(1)
        return out
    assert _wait(qapp, lambda: all(v not in ("…", "") for v in
                                   counts().values()) and counts())
    c = counts()
    assert c["broken.pdf"] == "?"
    assert all(c[f"sheet{i}.pdf"].isdigit() for i in range(3)), c
    d.close()


def test_zoom_while_a_sheet_is_still_blank(qapp, win, drawer):
    """Review 0.12.12 S1: jump to a page the drawing process is still
    drawing, zoom straight away - it crashed on None.width()."""
    v = win._view
    v._pf_forget()
    last = v.doc.page_count - 1
    v._prefetched.clear()
    v.go_to(last)
    v._render()
    assert v.rendered is None                       # blank, on its way
    for z in (v.zoom * 1.25, v.zoom * 1.25 * 1.25, v.zoom / 2):
        v.set_zoom(z)                               # no exception
        qapp.processEvents()
    assert _wait(qapp, lambda: v.rendered is not None)


def test_a_new_drawing_process_starts_after_one_dies(qapp, win, drawer,
                                                     monkeypatch):
    """Review M1: one crash used to mean drawing in the window for the
    rest of the session."""
    monkeypatch.setattr(drawer, "RETRY_AFTER", 0.0)
    v = win._view
    assert drawer.start()
    first = drawer.proc.pid
    drawer.proc.terminate()
    drawer.proc.join(5)
    # no waiting for the pipe to report it (on Windows that can come late,
    # Nov 5): the next request notices the dead process and starts a new one
    qapp.processEvents()
    got = {}
    rid = drawer.render(v._path, 0, 1.0, None, True, None,
                        lambda m: got.setdefault("m", m))
    assert rid is not None and drawer.proc.pid != first, (
        rid, drawer.ok, drawer.failed, drawer._starts,
        drawer.proc is not None and drawer.proc.is_alive(),
        drawer.proc.pid if drawer.proc else None, first)
    assert _wait(qapp, lambda: "m" in got)
    assert got["m"][0] == "img"
    # a late "I'm gone" from the old process must not stop the new one
    drawer._deliver((drawer._gen - 1, None))
    assert drawer.ok


def test_refresh_drops_counts_in_flight(qapp, drawer, tmp_path):
    """Review N2: counts for the old listing held up the new one."""
    import make_sample
    from app import docks
    for i in range(6):
        make_sample.make(str(tmp_path / f"s{i}.pdf"))
    d = docks.DocumentsPanel(str(tmp_path))
    d.show()
    d.refresh()
    d._count_timer.start()
    qapp.processEvents()
    d.refresh()                                   # again, counts in flight
    assert not getattr(d, "_flying", {})
    d._count_timer.start()
    assert _wait(qapp, lambda: all(
        d.tree.topLevelItem(i).text(1).isdigit()
        for i in range(d.tree.topLevelItemCount())))
    d.close()


def test_cancelled_renders_are_not_drawn(qapp, win, drawer, tmp_path):
    """Grok M10: requests the window no longer wants are dropped, and the
    drawing process skips the ones it hasn't started."""
    d = fitz.open()
    for i in range(12):
        p = d.new_page(width=1224, height=792)
        for k in range(400):                          # some real work
            p.draw_line((k, 0), (1224 - k, 792), width=0.3)
    path = str(tmp_path / "twelve.pdf")
    d.save(path)
    got = []
    rids = []
    for pno in range(12):
        sig = render_worker.page_sig(d, pno)
        rids.append(drawer.render(path, pno, 2.0, None, True, sig,
                                  lambda m, pno=pno: got.append(pno)))
    drawer.forget_many(rids[1:11])            # only the first and last
    assert _wait(qapp, lambda: 11 in got and 0 in got)
    _wait(qapp, lambda: False, secs=1)
    assert sorted(got) == [0, 11]             # the others never came back
    with drawer._lock:
        assert not any(r in drawer._wait for r in rids)


def test_paging_away_drops_what_is_no_longer_wanted(qapp, win, drawer,
                                                    monkeypatch):
    v = win._view
    calls = []
    monkeypatch.setattr(drawer, "forget_many",
                        lambda rids: calls.append(list(rids)))
    v._pf_pending.clear()
    for pno in (3, 4, 5, 9, 10, 11):
        v._pf_pending[(id(v.doc), pno, 0, 1.0, 0)] = 1000 + pno
    v.page = 3
    if v.doc.page_count > 10:
        v.go_to(10)
        assert sorted(k[1] for k in v._pf_pending) == [9, 10, 11]
        assert sorted(calls[0]) == [1003, 1004, 1005]
    v._pf_pending.clear()
    v._pf_pending[(id(v.doc), 1, 0, 1.0, 0)] = 77
    v.stop_timers()                           # closing the tab
    assert not v._pf_pending and calls[-1] == [77]


def test_release_lets_go_of_a_file(qapp, drawer, tmp_path):
    """Chief's re-test, Nov 7 (F1): the drawing process kept the original
    open, so Windows refused Copy Back's replace ("Access denied")."""
    src = str(tmp_path / "Example.pdf")
    d = fitz.open()
    d.new_page()
    d.save(src)
    d.close()
    got = {}
    with fitz.open(src) as d:
        sig = render_worker.page_sig(d, 0)
    drawer.render(src, 0, 1.0, None, True, sig,
                  lambda m: got.setdefault("m", m))
    assert _wait(qapp, lambda: "m" in got)          # it has the file open
    assert render_worker.release(src, wait=10.0) is True
    new = str(tmp_path / "new.pdf")
    d = fitz.open()
    d.new_page().insert_text((72, 72), "replaced")
    d.save(new)
    d.close()
    os.replace(new, src)                 # refused on Windows before
    with fitz.open(src) as d:
        assert "replaced" in d[0].get_text()


def test_copy_back_with_the_drawing_process_running(qapp, drawer,
                                                    tmp_path, monkeypatch):
    """The whole of F1, without faking the replace: open, local copy, add
    a rectangle, Copy Back - the original gets the rectangle."""
    from app import settings
    from app.main_window import MainWindow
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "_cache", None)
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(
        lambda *a, **k: warned.append(a)))
    orig = str(tmp_path / "share" / "Example plan.pdf")
    os.makedirs(os.path.dirname(orig))
    d = fitz.open()
    d.new_page()
    d.new_page()
    d.save(orig)
    d.close()
    w = MainWindow()
    try:
        assert w.open_path(orig)
        got = {}
        sig = render_worker.page_sig(w._view.doc, 0)
        drawer.render(orig, 0, 1.0, None, True, sig,
                      lambda m: got.setdefault("m", m))
        assert _wait(qapp, lambda: "m" in got)      # the process has it
        local = w.work_on_local_copy()
        assert local and local != orig
        a = w._view.doc[0].add_rect_annot(fitz.Rect(50, 50, 200, 200))
        a.update()
        w._view.dirty = True
        assert w.copy_back_original() == orig, warned
        assert not warned
        with fitz.open(orig) as d:
            assert len(list(d[0].annots())) == 1
        assert not os.path.exists(orig + ".qscopy")
        assert "didn't happen" not in w.statusBar().currentMessage()
    finally:
        for i in range(w.tabs.count()):
            v = getattr(w.tabs.widget(i), "view", None)
            if v is not None:
                v.dirty = False
        w.close()
        w.deleteLater()
        qapp.processEvents()
