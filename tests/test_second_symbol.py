import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import fitz
import pytest
from app import second_symbol as ss, count_triage as ct


def hits():
    s = [0.97, 0.88, 0.80, 0.78, 0.76, 0.66]
    return [{"page": 0 if i < 4 else 1, "rect": [20 * i + 10, 50, 20 * i + 26, 66],
             "score": v, "band": "high" if v >= 0.9 else "review",
             "angle_hint": 90 if i in (2, 3, 4) else 0}
            for i, v in enumerate(s)]


def suggestion():
    t = ct.Triage(hits(), 0.99, 0.0)
    for s in (0.80, 0.78, 0.76):
        while t.current()["score"] != s:
            t.key("Down")
        t.key("N")
    return t.second_symbol_suggestion()


def test_plan_uses_first_rejected_rect_and_new_group():
    sug = suggestion()
    p = ss.plan(sug, "Duplex Outlet")
    first = sug["hits"][0]
    assert p["page"] == first["page"] and p["rect"] == fitz.Rect(first["rect"])
    assert p["group"] == "Duplex Outlet (2nd symbol)"
    assert len(p["rects"]) == 3
    assert ss.plan(sug, "X", existing={"X (2nd symbol)"})["group"] == "X (2nd symbol 2)"
    assert ss.plan(None, "X") is None


class FakeView:
    def __init__(self):
        self.page, self.calls = 0, []

    def go_to(self, p):
        self.page = p

    def count_symbol(self, rect, group=None, all_pages=None, review=False):
        self.calls.append((self.page, fitz.Rect(rect), group, review))
        return 7


def test_train_goes_to_page_and_calls_count_symbol():
    sug = suggestion()
    v = FakeView()
    n = ss.train(v, ss.plan(sug, "Outlet"))
    page, rect, group, review = v.calls[0]
    assert n == 7 and review is True and group == "Outlet (2nd symbol)"
    assert page == sug["hits"][0]["page"] and rect == fitz.Rect(sug["hits"][0]["rect"])


def _dialog():
    from PySide6.QtWidgets import QApplication
    from app import autocount as autocount_boost
    QApplication.instance() or QApplication([])
    doc = fitz.open()
    doc.new_page(); doc.new_page()
    dlg = autocount_boost.CountReviewDialog(doc, hits(), "Outlet")
    t = ct.attach(dlg, 0.99, 0.0)
    return dlg, t


def test_wire_button_shows_only_with_suggestion_and_click_requests_training():
    from PySide6.QtCore import Qt
    dlg, t = _dialog()
    btn = ss.wire(dlg, "Outlet")
    assert btn.isHidden()
    for s in (0.80, 0.78, 0.76):
        row = [i for i, h in enumerate(dlg.hits) if h["score"] == s][0]
        dlg.list.setCurrentRow(row)
        assert dlg.triage_key("N")
    assert not btn.isHidden() and "second symbol" in btn.text().lower()
    btn.click()
    req = dlg.second_symbol_request
    assert req["group"] == "Outlet (2nd symbol)" and len(req["rects"]) == 3
    assert dlg.result() == 1          # review accepted first (group 1 kept)


def test_after_review_trains_only_when_requested():
    dlg, _ = _dialog()
    v = FakeView()
    assert ss.after_review(v, dlg) == 0 and not v.calls
    dlg.second_symbol_request = ss.plan(suggestion(), "Outlet")
    assert ss.after_review(v, dlg) == 7 and v.calls
    assert dlg.second_symbol_request is None


def test_undo_default_stays_200():
    from app import history
    assert history.History(lambda: b"x").limit == 200
