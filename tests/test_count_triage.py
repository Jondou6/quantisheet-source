import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import fitz
import pytest
from app import count_triage as ct


def hits():
    s = [0.97, 0.93, 0.88, 0.80, 0.75, 0.70, 0.65, 0.55]
    return [{"page": 0, "rect": [10 * i, 50, 10 * i + 8, 58], "score": v,
             "angle_hint": 90 if i in (3, 4, 5) else 0, "tag_ok": i != 6}
            for i, v in enumerate(s)]


def test_thresholds_default_and_auto_bands():
    t = ct.Triage(hits())
    assert (t.accept, t.reject) == (0.92, 0.60)
    p = t.progress()
    assert p == {"total": 8, "accepted": 2, "rejected": 1, "triaged": 3,
                 "remaining": 5}
    t.set_thresholds(0.85, 0.72)
    assert t.progress()["accepted"] == 3 and t.progress()["rejected"] == 3


def test_keys_y_n_and_arrows():
    t = ct.Triage(hits())
    first = t.current()
    assert first["score"] == 0.88
    t.key("Down"); assert t.current()["score"] == 0.80
    t.key("Up"); assert t.current()["score"] == 0.88
    t.key("Y")
    assert t.state[id(first)] == "accepted"
    assert t.current()["score"] == 0.80
    t.key("N")
    assert t.progress()["rejected"] == 2


def test_manual_choice_survives_threshold_change():
    t = ct.Triage(hits())
    h = t.current(); t.key("N")
    t.set_thresholds(0.5, 0.1)
    assert t.state[id(h)] == "rejected"


def test_why_line_is_real():
    w = ct.why(hits()[3])
    assert "match 0.80" in w and "rotated 90" in w and "p1" in w
    assert "no tag" in ct.why(hits()[6])


def test_three_similar_rejects_offer_second_symbol():
    t = ct.Triage(hits())
    t.set_thresholds(0.99, 0.0)
    for s in (0.80, 0.75, 0.70):
        while t.current()["score"] != s:
            t.key("Down")
        t.key("N")
    sug = t.second_symbol_suggestion()
    assert sug and len(sug["hits"]) == 3 and "second symbol" in sug["text"]


def test_commit_is_one_undo_step():
    from app import history, annotate
    doc = fitz.open(); doc.new_page()
    h = history.History(lambda: doc.tobytes())
    t = ct.Triage(hits())
    n = t.commit(doc, h, group="Lights")
    assert n == 2
    assert len([i for i in annotate.takeoff_items(doc) if i["type"] == "count"]) == 2
    assert h.can_undo()
    h.undo(doc)
    assert not h.can_undo()
    assert annotate.takeoff_items(doc) == []


def test_undo_limit_setting():
    from app import history
    h = history.History(lambda: b"x" * 10)
    ct.apply_undo_limit(h, 0)
    assert h.limit >= 10 ** 9
    ct.apply_undo_limit(h, 500)
    assert h.limit == 500


def test_dialog_keys_and_progress():
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    QApplication.instance() or QApplication([])
    d = ct.TriageDialog(ct.Triage(hits()))
    assert d.slider.value() == 92
    QTest.keyClick(d, Qt.Key_Y)
    assert "Accepted 3" in d.progress_label.text()
    assert d.bar.value() == 4 and d.bar.maximum() == 8
    assert "match" in d.why_label.text()
