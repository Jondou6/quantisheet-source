"""Nov 3 (#10): dead references - sheet index entries with no sheet, spec
references to drawings not in the set. Made-up sets."""
from app.ai import rfi_finder as R

PLANS = [(0, "G-001", "COVER SHEET",
          "SHEET INDEX\nG-001 COVER SHEET\nA-101 FLOOR PLAN\n"
          "A-201 ELEVATIONS\nA-501 DETAILS\n"),
         (1, "A-101", "FLOOR PLAN", "FLOOR PLAN"),
         (2, "A-201", "ELEVATIONS", "ELEVATIONS")]


def _q(found, word):
    return [f for f in found if word in f["question"]]


def test_index_entry_with_no_sheet():
    got = _q(R.checks(PLANS), "sheet index")
    assert [f["quote"] for f in got] == ["A-501"]
    assert got[0]["page"] == 0 and got[0]["doc"] == "plans"


def test_untrusted_index_is_skipped():
    plans = [(0, "G-001", "COVER", "DRAWING INDEX\nX-1 A\nX-2 B\nX-3 C\n"),
             (1, "A-101", "PLAN", ""), (2, "A-201", "ELEV", "")]
    assert not _q(R.checks(plans), "sheet index")


def test_spec_refers_to_missing_drawing():
    specs = [(5, "", "", "SECTION 08 11 13 - HOLLOW METAL DOORS\n"
              "Provide frames as shown on Drawing A-601 and Sheet A-101.\n")]
    got = _q(R.checks(PLANS, specs), "specifications refer to drawing")
    assert [f["quote"] for f in got] == ["Drawing A-601"]
    assert got[0]["doc"] == "specs"
