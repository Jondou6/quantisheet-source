"""Count Several Symbols: box 2+ samples, name each, one run finds them
all, one review list per sample, no spot counted twice."""
import os

import fitz

from app import count_several as cs

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from test_gui import win, qapp                     # noqa: F401
except Exception:                  # no Qt here: the pure tests still run
    win = qapp = None


def H(page, x, y, score, size=14):
    return {"page": page, "rect": [x, y, x + size, y + size],
            "score": score, "band": "high" if score >= 0.9 else "review"}


# ---- pure ---------------------------------------------------------------------------------
def test_a_spot_matched_by_two_samples_is_kept_once_for_the_better():
    res = {"Toilet": [H(0, 100, 100, 0.97), H(0, 300, 100, 0.85),
                      H(1, 100, 100, 0.95)],
           "Sink": [H(0, 102, 101, 0.88),         # same spot as a toilet
                    H(0, 301, 99, 0.93),          # beats the weak toilet
                    H(0, 500, 500, 0.91),
                    H(2, 100, 100, 0.90)]}        # another page: no clash
    kept, dropped = cs.resolve_overlaps(res)
    assert [(h["page"], h["rect"][0]) for h in kept["Toilet"]] == \
        [(0, 100), (1, 100)]
    assert [(h["page"], h["rect"][0]) for h in kept["Sink"]] == \
        [(0, 301), (0, 500), (2, 100)]
    assert sorted((n, w) for _h, n, w in dropped) == \
        [("Sink", "Toilet"), ("Toilet", "Sink")]
    # same class twice in one place is the engine's business, not ours
    kept, dropped = cs.resolve_overlaps({"A": [H(0, 0, 0, .9),
                                               H(0, 2, 2, .8)]})
    assert len(kept["A"]) == 2 and not dropped


def test_same_spot_rule():
    assert cs.same_spot([0, 0, 10, 10], [4, 4, 14, 14])
    assert not cs.same_spot([0, 0, 10, 10], [6, 0, 16, 10])
    # a small symbol inside a big one's box: measured by the smaller
    assert not cs.same_spot([0, 0, 40, 40], [24, 24, 30, 30])


def test_pages_and_names():
    assert cs.parse_pages("1-3, 5", 10) == {0, 1, 2, 4}
    assert cs.parse_pages("3-1", 10) == {0, 1, 2}
    assert cs.parse_pages("7, 99", 8) == {6}
    assert cs.parse_pages("", 5) is None
    assert cs.parse_pages("a-b", 5) is None
    assert cs.unique_name("Chair", ["chair", "Desk"]) == "Chair (2)"
    assert cs.unique_name("", []) == "Symbol"


def test_find_all_shares_one_render_and_tags_classes():
    calls = []

    def finder(doc, tpl, pages=None, cache=None):
        calls.append((tpl, pages, id(cache)))
        cache.setdefault(0, "rendered once")
        return [H(0, 10, 10, 0.95)] if tpl == b"A" else \
            [H(0, 11, 11, 0.92), H(0, 200, 10, 0.95)]
    kept, dropped = cs.find_all(None, [{"name": "Chair", "template": b"A"},
                                       {"name": "Desk", "template": b"B"}],
                                pages={0}, finder=finder)
    assert len({c[2] for c in calls}) == 1          # one cache for all
    assert [c[1] for c in calls] == [{0}, {0}]
    assert [h["class"] for h in kept["Chair"]] == ["Chair"]
    assert [h["rect"][0] for h in kept["Desk"]] == [200]
    assert len(dropped) == 1


def test_plan_marks_one_group_per_class():
    acc = {"Chair": [H(0, 10, 10, .95), H(0, 50, 10, .95)],
           "Desk": [H(0, 200, 10, .93)], "Lamp": []}
    marks = cs.plan_marks(acc)
    groups = [m[2]["measure"]["group"] for m in marks]
    assert groups == ["Chair", "Chair", "Desk"]
    assert all(m[1] == "add_count" for m in marks)
    assert marks[0][2]["color"] != marks[2][2]["color"]
    assert [m[2]["n"] for m in marks] == [1, 2, 1]


# ---- on a real PDF ------------------------------------------------------------------------
# three plain symbols, each repeated: a circle with a cross ("Toilet"),
# a square with one diagonal ("Chair"), a triangle ("Exit sign")
PLACES = {"Toilet": [(80, 80), (80, 300), (420, 450), (650, 120)],
          "Chair": [(200, 80), (200, 220), (330, 300), (520, 450),
                    (650, 300)],
          "Exit sign": [(330, 80), (500, 220), (80, 480)]}
S = 16.0


def _draw(sh, kind, x, y):
    if kind == "Toilet":
        c = fitz.Point(x + S / 2, y + S / 2)
        sh.draw_circle(c, S / 2)
        sh.draw_line(fitz.Point(x + 3, y + S / 2), fitz.Point(x + S - 3,
                                                           y + S / 2))
        sh.draw_line(fitz.Point(x + S / 2, y + 3), fitz.Point(x + S / 2,
                                                           y + S - 3))
    elif kind == "Chair":
        sh.draw_rect(fitz.Rect(x, y, x + S, y + S))
        sh.draw_line(fitz.Point(x, y), fitz.Point(x + S, y + S))
    else:
        sh.draw_polyline([fitz.Point(x, y + S), fitz.Point(x + S / 2, y),
                          fitz.Point(x + S, y + S), fitz.Point(x, y + S)])
        sh.draw_line(fitz.Point(x + S / 2, y + 6), fitz.Point(x + S / 2,
                                                           y + S - 3))


def _pdf(pages=1):
    d = fitz.open()
    for _ in range(pages):
        page = d.new_page(width=792, height=612)
        sh = page.new_shape()
        for kind, spots in PLACES.items():
            for x, y in spots:
                _draw(sh, kind, x, y)
        sh.finish(color=(0, 0, 0), width=1.0)
        sh.commit()
    return d


def _sample_rect(kind):
    x, y = PLACES[kind][0]
    return fitz.Rect(x - 2, y - 2, x + S + 2, y + S + 2)


def test_three_symbols_in_one_run_on_a_pdf():
    from app import autocount
    d = _pdf(pages=2)
    samples = [{"name": k, "template": autocount.symbol_template(
        d[0], _sample_rect(k))} for k in PLACES]
    kept, dropped = cs.find_all(d, samples, pages={0})
    for k, spots in PLACES.items():
        assert len(kept[k]) == len(spots), (k, kept[k])
        assert {h["page"] for h in kept[k]} == {0}
    # every hit is on a different spot, whatever its class
    allhits = [h for hs in kept.values() for h in hs]
    for i, a in enumerate(allhits):
        for b in allhits[i + 1:]:
            assert not cs.same_spot(a["rect"], b["rect"])
    # the same symbol boxed twice under two names: counted once, not twice
    twice = [{"name": "Chair", "template": samples[1]["template"]},
             {"name": "Seat", "template": samples[1]["template"]}]
    kept, dropped = cs.find_all(d, twice, pages=None)
    assert len(kept["Chair"]) + len(kept["Seat"]) == \
        2 * len(PLACES["Chair"])                    # two pages
    assert len(dropped) == 2 * len(PLACES["Chair"])


def test_count_several_in_the_app(qapp, win, tmp_path, monkeypatch):
    from app import annotate, takeoff_assist_ui as tau
    path = str(tmp_path / "symbols.pdf")
    _pdf().save(path)
    win.open_path(path)
    v = win._view
    dlg = tau.count_several(win)
    assert v.tool == "symbol_sample"
    assert not dlg.find_btn.isEnabled()            # needs two samples
    # box three samples on the drawing (the rect tool calls back)
    for k in PLACES:
        assert v.commit_rect("symbol_sample", _sample_rect(k)) == 1
        dlg.table.item(len(dlg.samples) - 1, 1).setText(k)
    assert [s["name"] for s in dlg.samples] == list(PLACES)
    assert dlg.find_btn.isEnabled()
    # a duplicate name is made unique
    dlg.table.item(2, 1).setText("Chair")
    assert dlg.samples[2]["name"] == "Chair (2)"
    dlg.table.item(2, 1).setText("Exit sign")
    seen = {}

    def review(rd):
        seen["tabs"] = [rd.tabs.tabText(i) for i in range(rd.tabs.count())]
        rd._set_all(rd.lists["Chair"][0], True)
        rd._set_all(rd.lists["Toilet"][0], True)
        rd._set_all(rd.lists["Exit sign"][0], True)
        rd.set_checked("Exit sign", 0, False)        # reject one
        return 1
    monkeypatch.setattr(cs.ReviewDialog, "exec", review)
    n = dlg.run()
    assert n > 0
    assert len(seen["tabs"]) == 3 and seen["tabs"][0].startswith("Toilet")
    counts = {}
    for it in annotate.takeoff_items(v.doc):
        if it["type"] == "count":
            counts[it["group"]] = counts.get(it["group"], 0) + 1
    assert counts == {"Toilet": 4, "Chair": 5, "Exit sign": 2}
    assert v.tool != "symbol_sample"               # the box tool is put away
    win.undo()                                     # one undo step
    assert not [it for it in annotate.takeoff_items(v.doc)
                if it["type"] == "count"]
