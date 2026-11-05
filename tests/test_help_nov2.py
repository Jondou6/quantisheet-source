"""Nov 2: the Help Center, shortcuts and Welcome Tour cover the review and
takeoff tools added Nov 1 (reshape, select several, A/D, Origin, missed
counts, count library, Count by Label wildcards, zones, learned names)."""
from app import helpcenter, tour


def _tut(i):
    return next(t for t in helpcenter.T if t["id"] == i)


def _text(t):
    return " ".join([t["goal"]] + t["steps"] + t["tips"])


def test_new_tutorials_are_there():
    for i, words in (("fixtakeoff", ["Drag a corner", "Ctrl+click",
                                      "Move Selected to Item", "Origin",
                                      "AI, edited", "<b>A</b>"]),
                     ("missedcounts", ["Show Uncounted Copies",
                                       "Report Missed", "Count Library"]),
                     ("countlabel", ["P-#", "WH-*", "One item per tag"]),
                     ("aizones", ["Only Here", "Leave Out",
                                  "Item Names Learned"])):
        t = _tut(i)
        assert all(w in _text(t) for w in words), (i, words)
        assert len(t["steps"]) >= 3 and t["tips"]


def test_ai_takeoff_tutorial_is_current():
    s = _text(_tut("aitakeoff"))
    for w in ("Review Queue", "badge", "confidence", "never added twice",
              "bid check"):
        assert w in s, w


def test_scale_then_measure_order_kept():
    ids = [t["id"] for t in helpcenter.T]
    assert ids.index("measure") == ids.index("scale") + 1


def test_shortcuts_list_the_new_keys():
    keys = dict(helpcenter.SHORTCUTS)
    assert keys["Accept / deny a selected AI markup"] == "A / D"
    assert "Ctrl+click" in keys["Select several markups"]


def test_tour_mentions_them():
    titles = [s[1] for s in tour.STOPS]
    assert "Takeoff tools" in titles
    text = " ".join(s[2] for s in tour.STOPS)
    for w in ("Origin", "drag its corners", "Count Library", "zones",
              "<b>A</b>"):
        assert w in text, w
