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
    assert __version__ == "1.1.29"


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


def test_whats_new_114():
    p = os.path.join(os.path.dirname(helpcenter.__file__), "data",
                     "whats_new.json")
    s = json.load(open(p, encoding="utf-8"))["1.1.4"]
    for w in ("Exclusions side by side", "ONLY ONE", "License expires",
              "Show Source", "word for word", "nothing leaves the computer",
              "still a draft to check"):
        assert w in s
    for w in ("Adobe", "Acrobat", "Bluebeam", "P6", "Stirling", "Manual J",
              "Autodesk", "Forma"):
        assert w not in s
    root = os.path.dirname(os.path.dirname(helpcenter.__file__))
    notes = open(os.path.join(root, "docs", "TEAM_NOTES_1.1.4.txt"),
                 encoding="utf-8").read()
    assert notes.startswith("QuantiSheet 1.1.4\n")
    assert "quantisheet-source/tree/v1.1.4" in notes


def test_whats_new_115():
    p = os.path.join(os.path.dirname(helpcenter.__file__), "data",
                     "whats_new.json")
    s = json.load(open(p, encoding="utf-8"))["1.1.5"]
    for w in ("Variance", "HIGH or LOW", "A blank is not $0.00",
              "no estimate", "to the cent", "Scope item",
              "Project-wide lines", "update it so bidders see",
              "Bid Board", "Go / No-Go", "Fill From the Job and Sign",
              "never kept or filled", "not a certificate signature",
              "encrypted for your Windows account"):
        assert w in s
    for w in ("Adobe", "Acrobat", "Bluebeam", "P6", "Stirling", "Manual J",
              "Autodesk", "Forma"):
        assert w not in s
    root = os.path.dirname(os.path.dirname(helpcenter.__file__))
    notes = open(os.path.join(root, "docs", "TEAM_NOTES_1.1.5.txt"),
                 encoding="utf-8").read()
    assert notes.startswith("QuantiSheet 1.1.5\n")
    assert "quantisheet-source/tree/v1.1.5" in notes


def test_whats_new_1120():
    p = os.path.join(os.path.dirname(helpcenter.__file__), "data",
                     "whats_new.json")
    s = json.load(open(p, encoding="utf-8"))["1.1.20"]
    for w in ("Watch Plan Folder", "Open Plan Set in QuantiSheet",
              "Bid Submittal Checklist"):
        assert w in s
    for bad in ("Repro", "Adobe", "Bluebeam", "Planswift", "HMB"):
        assert bad not in s
    root = os.path.dirname(os.path.dirname(helpcenter.__file__))
    notes = open(os.path.join(root, "docs", "TEAM_NOTES_1.1.20.txt"),
                 encoding="utf-8").read()
    assert notes.startswith("QuantiSheet 1.1.20\n")
    assert "quantisheet-source/tree/v1.1.20" in notes


def test_whats_new_1119():
    p = os.path.join(os.path.dirname(helpcenter.__file__), "data",
                     "whats_new.json")
    s = json.load(open(p, encoding="utf-8"))["1.1.19"]
    assert "Rotate All" in s and "blank" in s
    root = os.path.dirname(os.path.dirname(helpcenter.__file__))
    notes = open(os.path.join(root, "docs", "TEAM_NOTES_1.1.19.txt"),
                 encoding="utf-8").read()
    assert notes.startswith("QuantiSheet 1.1.19\n")
    assert "quantisheet-source/tree/v1.1.19" in notes


def test_whats_new_1118():
    p = os.path.join(os.path.dirname(helpcenter.__file__), "data",
                     "whats_new.json")
    s = json.load(open(p, encoding="utf-8"))["1.1.18"]
    for w in ("Fillable forms", "work out their own totals",
              "Video Tutorials"):
        assert w in s
    for bad in ("Adobe", "Acrobat", "Bluebeam", "Planswift", "HMB",
                "Harbor", "Metro"):
        assert bad not in s
    root = os.path.dirname(os.path.dirname(helpcenter.__file__))
    notes = open(os.path.join(root, "docs", "TEAM_NOTES_1.1.18.txt"),
                 encoding="utf-8").read()
    assert notes.startswith("QuantiSheet 1.1.18\n")
    assert "quantisheet-source/tree/v1.1.18" in notes


def test_whats_new_1117():
    p = os.path.join(os.path.dirname(helpcenter.__file__), "data",
                     "whats_new.json")
    s = json.load(open(p, encoding="utf-8"))["1.1.17"]
    for w in ("Compare with Earlier Set", "Revision Log", "Bid Board",
              "four times faster", "click into a field"):
        assert w in s
    for bad in ("Adobe", "Bluebeam", "Planswift", "HMB", "Harbor", "Metro"):
        assert bad not in s
    root = os.path.dirname(os.path.dirname(helpcenter.__file__))
    notes = open(os.path.join(root, "docs", "TEAM_NOTES_1.1.17.txt"),
                 encoding="utf-8").read()
    assert notes.startswith("QuantiSheet 1.1.17\n")
    assert "quantisheet-source/tree/v1.1.17" in notes


def test_whats_new_1116():
    p = os.path.join(os.path.dirname(helpcenter.__file__), "data",
                     "whats_new.json")
    s = json.load(open(p, encoding="utf-8"))["1.1.16"]
    for w in ("made searchable first", "1/8", "in the estimate once"):
        assert w in s
    for bad in ("Adobe", "Bluebeam", "Planswift", "HMB", "Harbor", "Metro"):
        assert bad not in s
    root = os.path.dirname(os.path.dirname(helpcenter.__file__))
    notes = open(os.path.join(root, "docs", "TEAM_NOTES_1.1.16.txt"),
                 encoding="utf-8").read()
    assert notes.startswith("QuantiSheet 1.1.16\n")
    assert "quantisheet-source/tree/v1.1.16" in notes


def test_whats_new_1115():
    p = os.path.join(os.path.dirname(helpcenter.__file__), "data",
                     "whats_new.json")
    s = json.load(open(p, encoding="utf-8"))["1.1.15"]
    for w in ("work notes", "scanned floor plans", "Export Bid Package",
              "Estimate panel follows"):
        assert w in s
    for bad in ("Adobe", "Bluebeam", "Planswift", "HMB", "Harbor", "Metro"):
        assert bad not in s
    root = os.path.dirname(os.path.dirname(helpcenter.__file__))
    notes = open(os.path.join(root, "docs", "TEAM_NOTES_1.1.15.txt"),
                 encoding="utf-8").read()
    assert notes.startswith("QuantiSheet 1.1.15\n")
    assert "quantisheet-source/tree/v1.1.15" in notes


def test_whats_new_1114():
    p = os.path.join(os.path.dirname(helpcenter.__file__), "data",
                     "whats_new.json")
    s = json.load(open(p, encoding="utf-8"))["1.1.14"]
    for w in ("barbed wire", "twice as fast"):
        assert w in s
    root = os.path.dirname(os.path.dirname(helpcenter.__file__))
    notes = open(os.path.join(root, "docs", "TEAM_NOTES_1.1.14.txt"),
                 encoding="utf-8").read()
    assert notes.startswith("QuantiSheet 1.1.14\n")
    assert "quantisheet-source/tree/v1.1.14" in notes


def test_whats_new_1113():
    p = os.path.join(os.path.dirname(helpcenter.__file__), "data",
                     "whats_new.json")
    s = json.load(open(p, encoding="utf-8"))["1.1.13"]
    for w in ("marked TYP", "Gate Openings", "Add to Estimate"):
        assert w in s
    root = os.path.dirname(os.path.dirname(helpcenter.__file__))
    notes = open(os.path.join(root, "docs", "TEAM_NOTES_1.1.13.txt"),
                 encoding="utf-8").read()
    assert notes.startswith("QuantiSheet 1.1.13\n")
    assert "quantisheet-source/tree/v1.1.13" in notes


def test_whats_new_1112():
    p = os.path.join(os.path.dirname(helpcenter.__file__), "data",
                     "whats_new.json")
    s = json.load(open(p, encoding="utf-8"))["1.1.12"]
    for w in ("Keep a Copy and Start Fresh", "Check for Updates"):
        assert w in s
    root = os.path.dirname(os.path.dirname(helpcenter.__file__))
    notes = open(os.path.join(root, "docs", "TEAM_NOTES_1.1.12.txt"),
                 encoding="utf-8").read()
    assert notes.startswith("QuantiSheet 1.1.12\n")
    assert "quantisheet-source/tree/v1.1.12" in notes


def test_whats_new_1111():
    p = os.path.join(os.path.dirname(helpcenter.__file__), "data",
                     "whats_new.json")
    s = json.load(open(p, encoding="utf-8"))["1.1.11"]
    for w in ("feeder tags", "One-line diagram", "marked TYP"):
        assert w in s
    root = os.path.dirname(os.path.dirname(helpcenter.__file__))
    notes = open(os.path.join(root, "docs", "TEAM_NOTES_1.1.11.txt"),
                 encoding="utf-8").read()
    assert notes.startswith("QuantiSheet 1.1.11\n")
    assert "quantisheet-source/tree/v1.1.11" in notes


def test_whats_new_1110():
    p = os.path.join(os.path.dirname(helpcenter.__file__), "data",
                     "whats_new.json")
    s = json.load(open(p, encoding="utf-8"))["1.1.10"]
    for w in ("Microsoft Store copy", "No update is waiting",
              "updates come through the Store"):
        assert w in s
    root = os.path.dirname(os.path.dirname(helpcenter.__file__))
    notes = open(os.path.join(root, "docs", "TEAM_NOTES_1.1.10.txt"),
                 encoding="utf-8").read()
    assert notes.startswith("QuantiSheet 1.1.10\n")
    assert "quantisheet-source/tree/v1.1.10" in notes


def test_whats_new_119():
    p = os.path.join(os.path.dirname(helpcenter.__file__), "data",
                     "whats_new.json")
    s = json.load(open(p, encoding="utf-8"))["1.1.9"]
    for w in ("symbol's drawn shape", "duct number in a circle",
              "lighter than the walls'", "keeps its floor"):
        assert w in s
    for w in ("Adobe", "Acrobat", "Bluebeam", "P6", "Stirling", "Manual J",
              "Autodesk", "Forma", "HMB", "Harbor", "Metro", "Planswift"):
        assert w not in s
    root = os.path.dirname(os.path.dirname(helpcenter.__file__))
    notes = open(os.path.join(root, "docs", "TEAM_NOTES_1.1.9.txt"),
                 encoding="utf-8").read()
    assert notes.startswith("QuantiSheet 1.1.9\n")
    assert "quantisheet-source/tree/v1.1.9" in notes


def test_whats_new_118():
    p = os.path.join(os.path.dirname(helpcenter.__file__), "data",
                     "whats_new.json")
    s = json.load(open(p, encoding="utf-8"))["1.1.8"]
    for w in ("scanned plans", "two face lines", "partitions are kept",
              "without a warning", "casework or shelving"):
        assert w in s
    for w in ("Adobe", "Acrobat", "Bluebeam", "P6", "Stirling", "Manual J",
              "Autodesk", "Forma", "HMB", "Harbor", "Metro", "Planswift"):
        assert w not in s
    root = os.path.dirname(os.path.dirname(helpcenter.__file__))
    notes = open(os.path.join(root, "docs", "TEAM_NOTES_1.1.8.txt"),
                 encoding="utf-8").read()
    assert notes.startswith("QuantiSheet 1.1.8\n")
    assert "quantisheet-source/tree/v1.1.8" in notes


def test_whats_new_117():
    p = os.path.join(os.path.dirname(helpcenter.__file__), "data",
                     "whats_new.json")
    s = json.load(open(p, encoding="utf-8"))["1.1.7"]
    for w in ("Work Notes Takeoff", "summary table", "keyed notes",
              "measured as drawn", "Choose Specification",
              "is not applied", "Nothing is added to your takeoff"):
        assert w in s
    for w in ("Adobe", "Acrobat", "Bluebeam", "P6", "Stirling", "Manual J",
              "Autodesk", "Forma", "HMB", "Harbor", "Metro", "Planswift",
              "PlanSwift"):
        assert w not in s
    root = os.path.dirname(os.path.dirname(helpcenter.__file__))
    notes = open(os.path.join(root, "docs", "TEAM_NOTES_1.1.7.txt"),
                 encoding="utf-8").read()
    assert notes.startswith("QuantiSheet 1.1.7\n")
    assert "quantisheet-source/tree/v1.1.7" in notes


def test_whats_new_116():
    p = os.path.join(os.path.dirname(helpcenter.__file__), "data",
                     "whats_new.json")
    s = json.load(open(p, encoding="utf-8"))["1.1.6"]
    for w in ("drawn solid on wall layers", "stall's door", "Auto Area",
              "2'-6", "quicker on dense sheets"):
        assert w in s
    for w in ("Adobe", "Acrobat", "Bluebeam", "P6", "Stirling", "Manual J",
              "Autodesk", "Forma", "HMB", "Harbor"):
        assert w not in s
    root = os.path.dirname(os.path.dirname(helpcenter.__file__))
    notes = open(os.path.join(root, "docs", "TEAM_NOTES_1.1.6.txt"),
                 encoding="utf-8").read()
    assert notes.startswith("QuantiSheet 1.1.6\n")
    assert "quantisheet-source/tree/v1.1.6" in notes


def test_whats_new_1121():
    p = os.path.join(os.path.dirname(helpcenter.__file__), "data",
                     "whats_new.json")
    s = json.load(open(p, encoding="utf-8"))["1.1.21"]
    for w in ("Make Searchable", "graphic scale", "stations",
              "Wood Sheathing Helper", "NEW SSMH"):
        assert w in s
    for bad in ("Repro", "Adobe", "Acrobat", "Bluebeam", "Planswift", "HMB",
                "Harbor", "Metro", "Dillon", "AECOM"):
        assert bad not in s
    root = os.path.dirname(os.path.dirname(helpcenter.__file__))
    notes = open(os.path.join(root, "docs", "TEAM_NOTES_1.1.21.txt"),
                 encoding="utf-8").read()
    assert notes.startswith("QuantiSheet 1.1.21\n")
    assert "quantisheet-source/tree/v1.1.21" in notes


def test_whats_new_1122():
    p = os.path.join(os.path.dirname(helpcenter.__file__), "data",
                     "whats_new.json")
    s = json.load(open(p, encoding="utf-8"))["1.1.22"]
    for w in ("Reduced Size PDF", "Find Bid Terms",
              "Competition is manageable", "must hold"):
        assert w in s
    for bad in ("Repro", "Adobe", "Acrobat", "Bluebeam", "Planswift", "HMB",
                "PlanHub", "Harbor", "Metro"):
        assert bad not in s
    root = os.path.dirname(os.path.dirname(helpcenter.__file__))
    notes = open(os.path.join(root, "docs", "TEAM_NOTES_1.1.22.txt"),
                 encoding="utf-8").read()
    assert notes.startswith("QuantiSheet 1.1.22\n")


def test_whats_new_1123():
    p = os.path.join(os.path.dirname(helpcenter.__file__), "data",
                     "whats_new.json")
    s = json.load(open(p, encoding="utf-8"))["1.1.23"]
    for w in ("Rebar", "Beam / Header", "Column / Post", "Footing Size",
              "preliminary", "Metal Studs", "Structural Steel"):
        assert w in s
    for bad in ("Repro", "Adobe", "Acrobat", "Bluebeam", "Planswift", "HMB",
                "Calcs.com", "ClearCalcs", "Harbor", "Metro"):
        assert bad not in s
    root = os.path.dirname(os.path.dirname(helpcenter.__file__))
    notes = open(os.path.join(root, "docs", "TEAM_NOTES_1.1.23.txt"),
                 encoding="utf-8").read()
    assert notes.startswith("QuantiSheet 1.1.23\n")


def test_whats_new_1124():
    p = os.path.join(os.path.dirname(helpcenter.__file__), "data",
                     "whats_new.json")
    s = json.load(open(p, encoding="utf-8"))["1.1.24"]
    for w in ("Add to Estimate", "Manufacturers in Specs",
              "Manhole rehabilitation"):
        assert w in s
    for bad in ("Repro", "Adobe", "Acrobat", "Bluebeam", "Planswift", "HMB",
                "PlanHub", "Calcs.com", "Dillon", "AECOM", "Harbor", "Metro"):
        assert bad not in s
    root = os.path.dirname(os.path.dirname(helpcenter.__file__))
    notes = open(os.path.join(root, "docs", "TEAM_NOTES_1.1.24.txt"),
                 encoding="utf-8").read()
    assert notes.startswith("QuantiSheet 1.1.24\n")


def test_whats_new_1125():
    p = os.path.join(os.path.dirname(helpcenter.__file__), "data",
                     "whats_new.json")
    s = json.load(open(p, encoding="utf-8"))["1.1.25"]
    for w in ("Project Analysis", "Earthwork", "Drywall", "Paint",
              "not found", "newest addendum"):
        assert w in s
    for bad in ("Repro", "Adobe", "Acrobat", "Bluebeam", "Planswift", "HMB",
                "PlanHub", "Calcs.com", "Dillon", "AECOM", "Harbor", "Metro"):
        assert bad not in s
    root = os.path.dirname(os.path.dirname(helpcenter.__file__))
    notes = open(os.path.join(root, "docs", "TEAM_NOTES_1.1.25.txt"),
                 encoding="utf-8").read()
    assert notes.startswith("QuantiSheet 1.1.25\n")


def test_whats_new_1126():
    p = os.path.join(os.path.dirname(helpcenter.__file__), "data",
                     "whats_new.json")
    s = json.load(open(p, encoding="utf-8"))["1.1.26"]
    for w in ("Project Analysis", "Local AI", "Send to Bid Board",
              "Fill From Specs", "Only empty fields"):
        assert w in s
    for bad in ("Repro", "Adobe", "Acrobat", "Bluebeam", "Planswift", "HMB",
                "PlanHub", "Calcs.com", "Dillon", "AECOM", "Harbor", "Metro"):
        assert bad not in s
    root = os.path.dirname(os.path.dirname(helpcenter.__file__))
    notes = open(os.path.join(root, "docs", "TEAM_NOTES_1.1.26.txt"),
                 encoding="utf-8").read()
    assert notes.startswith("QuantiSheet 1.1.26\n")


def test_whats_new_1127():
    p = os.path.join(os.path.dirname(helpcenter.__file__), "data",
                     "whats_new.json")
    s = json.load(open(p, encoding="utf-8"))["1.1.27"]
    for w in ("3D Model Quantities", "IFC", "Ask the Project",
              "Draft Daily Log", "Check Submittal", "Risk Flags"):
        assert w in s
    for bad in ("Repro", "Adobe", "Acrobat", "Bluebeam", "Planswift", "HMB",
                "PlanHub", "Calcs.com", "Dillon", "AECOM", "Harbor", "Metro"):
        assert bad not in s
    root = os.path.dirname(os.path.dirname(helpcenter.__file__))
    notes = open(os.path.join(root, "docs", "TEAM_NOTES_1.1.27.txt"),
                 encoding="utf-8").read()
    assert notes.startswith("QuantiSheet 1.1.27\n")


def test_whats_new_1128():
    p = os.path.join(os.path.dirname(helpcenter.__file__), "data",
                     "whats_new.json")
    s = json.load(open(p, encoding="utf-8"))["1.1.28"]
    for w in ("password-protected", "Remove Security",
              "Signature Requests", "your own time"):
        assert w in s
    for bad in ("Repro", "Adobe", "Acrobat", "Bluebeam", "Planswift", "HMB",
                "PlanHub", "Calcs.com", "Dillon", "AECOM", "Harbor", "Metro"):
        assert bad not in s
    root = os.path.dirname(os.path.dirname(helpcenter.__file__))
    notes = open(os.path.join(root, "docs", "TEAM_NOTES_1.1.28.txt"),
                 encoding="utf-8").read()
    assert notes.startswith("QuantiSheet 1.1.28\n")


def test_whats_new_1129():
    p = os.path.join(os.path.dirname(helpcenter.__file__), "data",
                     "whats_new.json")
    s = json.load(open(p, encoding="utf-8"))["1.1.29"]
    for w in ("Features and How-To Guide", "read-only", "Auto Scale",
              "close up", "counted once", "QuantiSheet red", "charcoal"):
        assert w in s
    for bad in ("Repro", "Adobe", "Acrobat", "Bluebeam", "Planswift", "HMB",
                "PlanHub", "Calcs.com", "Dillon", "AECOM", "Harbor", "Metro"):
        assert bad not in s
    root = os.path.dirname(os.path.dirname(helpcenter.__file__))
    notes = open(os.path.join(root, "docs", "TEAM_NOTES_1.1.29.txt"),
                 encoding="utf-8").read()
    assert notes.startswith("QuantiSheet 1.1.29\n")
