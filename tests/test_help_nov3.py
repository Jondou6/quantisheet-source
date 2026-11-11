"""Nov 3: Help Center, What's New and the tour cover Select Text / Copy
as Table, Report an Issue and the Package Tracker."""
import json
import os

from app import helpcenter, tour


def _text(i):
    t = next(t for t in helpcenter.T if t["id"] == i)
    assert len(t["steps"]) >= 3 and t["tips"] and t["try"]
    return " ".join([t["goal"]] + t["steps"] + t["tips"])


def test_new_tutorials():
    for i, words in (("copytext", ["Select Text", "Ctrl+C", "Ctrl+A",
                                   "Copy as Table", "Ctrl+Shift+C", "OCR"]),
                     ("reportissue", ["Report an Issue", "Retake",
                                      "Attach this drawing", "Send",
                                      "Don't Ask About Freezes"]),
                     ("packages", ["Package Tracker", "Track", "LATE",
                                   "Change Carrier"])):
        s = _text(i)
        assert all(w in s for w in words), (i, words)


def test_shortcuts_and_tour():
    keys = dict(helpcenter.SHORTCUTS)
    assert keys["Select Text tool"] == "I"
    assert "Ctrl+Shift+C" in keys["Copy a schedule for Excel"]
    assert any("Select Text" in s[2] and "Package Tracker" in s[2]
               for s in tour.STOPS)


def test_whats_new_106():
    p = os.path.join(os.path.dirname(helpcenter.__file__), "data",
                     "whats_new.json")
    s = json.load(open(p, encoding="utf-8"))["1.0.6"]
    for w in ("Select Text", "Report an Issue", "Package Tracker", "pan"):
        assert w in s
    assert "Adobe" not in s and "Bluebeam" not in s


def test_whats_new_111():
    p = os.path.join(os.path.dirname(helpcenter.__file__), "data",
                     "whats_new.json")
    s = json.load(open(p, encoding="utf-8"))["1.1.1"]
    for w in ("opened it twice", "Quick bar", "Service tab", "Back Office",
              "Check for Updates Now", "Also new since 1.0.6"):
        assert w in s
    assert "Adobe" not in s and "Bluebeam" not in s
    from app import __version__
    assert __version__ == "1.1.3"


def test_whats_new_112():
    p = os.path.join(os.path.dirname(helpcenter.__file__), "data",
                     "whats_new.json")
    s = json.load(open(p, encoding="utf-8"))["1.1.2"]
    for w in ("PDF Management", "sales tax", "rounds the normal way",
              "takeoff line", "Stop Now", "have not yet been reviewed"):
        assert w in s
    for w in ("Adobe", "Acrobat", "Bluebeam", "P6", "Stirling", "Manual J"):
        assert w not in s
    root = os.path.dirname(os.path.dirname(helpcenter.__file__))
    notes = open(os.path.join(root, "docs", "TEAM_NOTES_1.1.2.txt"),
                 encoding="utf-8").read()
    assert notes.startswith("QuantiSheet 1.1.2\n")
    assert "quantisheet-source/tree/v1.1.2" in notes


def test_whats_new_113():
    p = os.path.join(os.path.dirname(helpcenter.__file__), "data",
                     "whats_new.json")
    s = json.load(open(p, encoding="utf-8"))["1.1.3"]
    for w in ("Auto Takeoff rooms", "pen by pen", "pay application",
              "still a draft to check"):
        assert w in s
    for w in ("Adobe", "Acrobat", "Bluebeam", "P6", "Stirling", "Manual J"):
        assert w not in s
    root = os.path.dirname(os.path.dirname(helpcenter.__file__))
    notes = open(os.path.join(root, "docs", "TEAM_NOTES_1.1.3.txt"),
                 encoding="utf-8").read()
    assert notes.startswith("QuantiSheet 1.1.3\n")
    assert "quantisheet-source/tree/v1.1.3" in notes
