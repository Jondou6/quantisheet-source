"""Nov 1: copies of a counted symbol that aren't counted yet, and a
missed copy boxed by a person used to look for more like it (in review,
out of the totals until accepted)."""
import pytest

fitz = pytest.importorskip("fitz")
pytest.importorskip("cv2")

from app import annotate, autocount, uncounted  # noqa: E402

SPOTS = [(100, 100), (300, 100), (500, 100), (100, 300), (300, 300),
         (500, 300)]


def _symbol(page, x, y):
    sh = page.new_shape()
    sh.draw_circle(fitz.Point(x, y), 8)
    sh.draw_line(fitz.Point(x - 8, y), fitz.Point(x + 8, y))
    sh.draw_line(fitz.Point(x, y - 8), fitz.Point(x, y + 8))
    sh.draw_rect(fitz.Rect(x + 9, y - 3, x + 13, y + 3))
    sh.finish(color=(0, 0, 0), width=1)
    sh.commit()


def _doc():
    d = fitz.open()
    pg = d.new_page(width=700, height=450)
    for x, y in SPOTS:
        _symbol(pg, x, y)
    return d


def _box(x, y):
    return fitz.Rect(x - 11, y - 11, x + 15, y + 11)


_N = [0]


def _count(d, hits, group="Outlet", review=False):
    for p, k, pl in uncounted.count_marks(hits, group, d, review=review):
        _N[0] += 1
        annotate.apply_op(d, {"kind": k, "page": p, "id": f"c{_N[0]}",
                              "payload": pl}, fresh=True)


@pytest.fixture(autouse=True)
def _picture_on(monkeypatch):
    monkeypatch.setattr(uncounted, "_picture_on", lambda: True)


def test_sample_is_kept_per_count_name():
    d = _doc()
    png = autocount.symbol_template(d[0], _box(*SPOTS[0]))
    assert uncounted.save_sample(d, "Outlet", png)
    assert uncounted.sample(d, "Outlet") == png
    assert uncounted.groups_with_samples(d) == ["Outlet"]
    assert uncounted.sample(d, "Other") is None


def test_uncounted_copies_are_the_ones_without_a_mark():
    d = _doc()
    png = autocount.symbol_template(d[0], _box(*SPOTS[0]))
    uncounted.save_sample(d, "Outlet", png)
    all_hits = autocount.find_symbols(d, png, 0.8, {0})
    assert len(all_hits) == len(SPOTS)
    # two of them counted
    first = sorted(all_hits, key=lambda h: (h["rect"][1], h["rect"][0]))[:2]
    _count(d, first)
    left = uncounted.uncounted(d, "Outlet", [0])
    assert len(left) == len(SPOTS) - 2
    for h in left:
        assert not any(fitz.Rect(h["rect"]).intersects(fitz.Rect(f["rect"]))
                       for f in first)


def test_no_sample_says_how_to_get_one():
    d = _doc()
    with pytest.raises(LookupError) as e:
        uncounted.uncounted(d, "Outlet", [0])
    assert "Count Symbol" in str(e.value)


def test_picture_switch_honoured(monkeypatch):
    d = _doc()
    monkeypatch.setattr(uncounted, "_picture_on", lambda: False)
    with pytest.raises(RuntimeError):
        uncounted.uncounted(d, "Outlet", [0], template=b"x")


def test_missed_example_finds_more_and_puts_them_in_review():
    d = _doc()
    png = autocount.symbol_template(d[0], _box(*SPOTS[0]))
    hits = autocount.find_symbols(d, png, 0.8, {0})
    _count(d, sorted(hits, key=lambda h: h["rect"][0])[:1], "Outlet")
    found = uncounted.from_example(d, 0, _box(*SPOTS[4]), "Outlet")
    assert len(found) == len(SPOTS) - 1
    assert uncounted.sample(d, "Outlet")               # kept for next time
    _count(d, found, "Outlet", review=True)
    its = [it for it in annotate.takeoff_items(d) if it["group"] == "Outlet"]
    assert sum(1 for it in its if it["pending"]) == len(SPOTS) - 1
    assert sum(1 for it in annotate.totals_items(d)
               if it["group"] == "Outlet") == 1        # only the counted one
    assert uncounted.uncounted(d, "Outlet", [0]) == []


def test_is_counted_next_to_or_on_the_symbol():
    r = [100, 100, 120, 120]
    above = fitz.Rect(100, 88, 110, 98)        # count_marks puts it here
    on = fitz.Rect(105, 105, 112, 112)         # a hand count click
    far = fitz.Rect(300, 300, 310, 310)
    assert uncounted.is_counted(r, [above])
    assert uncounted.is_counted(r, [on])
    assert not uncounted.is_counted(r, [far])
