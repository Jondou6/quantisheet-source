"""Auto Count boost: any angle, size drift, text tags, and a review list."""
import math
import random

import fitz
import pytest

from app import autocount
from app import autocount as acb  # was autocount_boost (folded Nov 4)


def _sheet(n=50, rot=0.0, size=lambda i: 14, distract=True, tags=None, seed=3):
    random.seed(seed)
    d = fitz.open()
    pg = d.new_page(width=1728, height=1152)
    truth, used = [], set()

    def spot():
        while True:
            p = (random.randrange(80, 1620, 40), random.randrange(80, 1060, 40))
            if p not in used:
                used.add(p)
                return p

    def diffuser(x, y, s, a, x_lines=2):
        c = fitz.Point(x, y)
        m = fitz.Matrix(math.cos(a), math.sin(a), -math.sin(a), math.cos(a), 0, 0)
        k = [fitz.Point(dx, dy) * m + c for dx, dy in
             ((-s / 2, -s / 2), (s / 2, -s / 2), (s / 2, s / 2), (-s / 2, s / 2))]
        pg.draw_polyline(k + [k[0]], width=1)
        if x_lines >= 1:
            pg.draw_line(k[0], k[2], width=1)
        if x_lines >= 2:
            pg.draw_line(k[1], k[3], width=1)

    for i in range(n):
        x, y = spot()
        diffuser(x, y, size(i), math.radians(rot if i else 0))
        truth.append((x, y))
        if tags:
            pg.insert_text((x + 10, y + 3), tags[0], fontsize=7)
    if distract:
        for _ in range(30):
            x, y = spot()
            diffuser(x, y, 14, 0, x_lines=random.choice([0, 1]))
        if tags:
            for _ in range(20):
                x, y = spot()
                diffuser(x, y, 14, 0)
                pg.insert_text((x + 10, y + 3), tags[1], fontsize=7)
    return d, pg, truth


def _score(hits, truth, tol=10):
    cs = [((h["rect"][0] + h["rect"][2]) / 2, (h["rect"][1] + h["rect"][3]) / 2) for h in hits]
    tp = sum(1 for t in truth if any(abs(t[0] - a) < tol and abs(t[1] - b) < tol for a, b in cs))
    return tp / len(truth), tp / max(1, len(hits))


def _tpl(pg, truth, half=10):
    x, y = truth[0]
    return autocount.symbol_template(pg, fitz.Rect(x - half, y - half, x + half, y + half))


@pytest.mark.parametrize("rot", [30, 45])
def test_any_angle(rot):
    d, pg, truth = _sheet(rot=rot)
    base = autocount.find_symbols(d, _tpl(pg, truth))
    assert _score(base, truth)[0] < 0.2              # today's matcher misses these
    hits = acb.find(d, _tpl(pg, truth))
    rec, prec = _score(hits, truth)
    assert rec >= 0.95 and prec >= 0.95


def test_size_drift():
    rnd = random.Random(9)
    d, pg, truth = _sheet(size=lambda i: 14 if i == 0 else rnd.uniform(12.6, 15.4))
    hits = acb.find(d, _tpl(pg, truth))
    rec, prec = _score(hits, truth)
    assert rec >= 0.95 and prec >= 0.95


def test_text_tag_disambiguation():
    """'C' fixtures vs 'CE' fixtures: same symbol, different tag."""
    d, pg, truth = _sheet(n=25, tags=("C", "CE"), distract=True)
    hits = acb.find(d, _tpl(pg, truth), tag="C")
    rec, prec = _score(hits, truth)
    assert rec >= 0.95 and prec >= 0.95


def test_bands_and_review_marks():
    d, pg, truth = _sheet(n=20)
    hits = acb.find(d, _tpl(pg, truth))
    assert all(h["band"] in ("high", "review") for h in hits)
    accepted = hits[:5]
    marks = acb.review_marks(accepted, group="Diffuser")
    assert len(marks) == 5 and marks[0][1] == "add_count"
    assert marks[0][2]["measure"]["method"] == "auto count (reviewed)"


def test_review_dialog_accept_reject():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    d, pg, truth = _sheet(n=10, distract=False)
    hits = acb.find(d, _tpl(pg, truth))
    dlg = acb.CountReviewDialog(d, hits, group="Diffuser")
    assert len(dlg.accepted()) == sum(1 for h in hits if h["band"] == "high")
    dlg.set_all(False)
    assert dlg.accepted() == []
    dlg.toggle(0)
    assert len(dlg.accepted()) == 1
