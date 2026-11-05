"""PM review NW-18: counting legend symbols over a set took minutes with
no sign of life; it now reports progress and can be cancelled."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import practice, tradetakeoff as tt                 # noqa: E402
from test_gui import win, qapp                               # noqa: E402,F401


def test_legend_count_shows_progress_and_cancels(win, tmp_path,
                                                 monkeypatch):
    p = practice.make(str(tmp_path / "practice.pdf"))
    assert win.open_path(p)
    dlg = win.trade_takeoff(show=False)
    seen = []
    real = tt.legend_counts

    def spy(doc, *a, **kw):
        prog = kw["progress"]
        seen.append(prog(0, 2, "DUPLEX RECEPTACLE"))  # True: keep going
        return real(doc, *a, **kw)
    monkeypatch.setattr(tt, "legend_counts", spy)
    dlg.legend.find()
    assert seen == [True]
    assert {f["name"] for f in dlg.legend.data} >= {"DUPLEX RECEPTACLE"}

    def cancel_first(doc, *a, **kw):
        stop = []

        def prog(k, n, name):
            if not stop:
                stop.append(1)
                return False                  # as if Cancel was pressed
            return True
        return real(doc, *a, **dict(kw, progress=prog))
    monkeypatch.setattr(tt, "legend_counts", cancel_first)
    dlg.legend.find()
    assert dlg.legend.data == []              # stopped before the first
    dlg.close()


def test_nw18_speed_each_sheet_read_once(tmp_path, monkeypatch):
    """NW-18 speed: the ring-shape and symbol-word fallbacks read a
    sheet's drawings / words once per count, not once per symbol."""
    import fitz
    d = fitz.open()
    pg = d.new_page()
    pg.insert_text((100, 100), "OS", fontsize=8)
    calls = []
    real = fitz.Page.get_drawings
    monkeypatch.setattr(fitz.Page, "get_drawings",
                        lambda self, *a, **k: calls.append(self.number)
                        or real(self, *a, **k))
    cache = {}
    for sig in ((0.5, 0.4, 0.4), (0.9, 0.3, 0.3), (0.5, 0.6, 0.6)):
        tt.fill_ring_hits(d[0], sig, cache=cache)
    assert calls == [0]
    tt.fill_ring_hits(d[0], (0.5, 0.4, 0.4))           # no cache: reads
    assert calls == [0, 0]
    words = {}
    for text in ("OS", "OS", "WP"):
        tt._text_symbol_counts(d, [(5, "Example " + text, text)], [], [],
                               None, None, words=words)
    assert list(words) == [0]
