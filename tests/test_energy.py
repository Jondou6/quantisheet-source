"""Energy Code (Module tab, 0.12.27): climate zone by county from the
DOE/PNNL guide, and the Code Library of your own code books."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import codelib, energy                              # noqa: E402
from test_gui import ANSWERS, win, qapp                 # noqa: E402,F401


def test_every_county_is_there():
    d = energy.data()["states"]
    assert len(d) == 51                                 # 50 states and DC
    assert sum(len(v) for v in d.values()) > 3100
    assert len(d["TX"]) == 254 and len(d["CA"]) == 58


@pytest.mark.parametrize("state,county,zone", [
    ("PA", "Philadelphia County", "4A"), ("Louisiana", "Orleans Parish",
                                          "2A"),
    ("AZ", "Maricopa", "2B"), ("MN", "Hennepin", "6A"),
    ("CA", "Los Angeles", "3B"), ("NY", "Kings", "4A"),
    ("FL", "Miami-Dade", "1A"), ("AK", "North Slope", "8"),
    ("MO", "Saint Louis", "4A"), ("OR", "Lane", "4C")])
def test_zones(state, county, zone):
    z = energy.zone(state, county)
    assert z and z["zone"] == zone, (state, county, z)


def test_changed_zones_say_what_they_were():
    z = energy.zone("NJ", "Mercer")
    assert (z["zone"], z["was"]) == ("4A", "5A")
    assert "was 5A before the 2021 IECC" in energy.describe(z)
    assert energy.zone("PA", "Nowhere") is None
    z = energy.zone("NM", "Taos")                 # the guide's own gap
    assert z["zone"] == "5" and "moisture" in z["note"]


PAGES = ["""CHAPTER 4 [RE] RESIDENTIAL ENERGY EFFICIENCY
SECTION R402
BUILDING THERMAL ENVELOPE
R402.1 General (Prescriptive). The building thermal envelope shall comply
with the requirements of Sections R402.1.1 through R402.1.5.
R402.1.2 Insulation and fenestration criteria. The building thermal
envelope shall meet the requirements of Table R402.1.3 based on the
climate zone specified in Chapter 3.
TABLE R402.1.3
INSULATION AND FENESTRATION REQUIREMENTS BY COMPONENT
CLIMATE ZONE FENESTRATION U-FACTOR CEILING R-VALUE
""", """R402.4 Air leakage (Mandatory). The building thermal envelope
shall be constructed to limit air leakage.
R402.4.1.2 Testing. The building or dwelling unit shall be tested and
verified as having an air leakage rate not exceeding 5.0 air changes per
hour in Climate Zones 0 through 2."""]


def test_code_book_index_and_search(tmp_path, monkeypatch):
    fitz = pytest.importorskip("fitz")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    secs = codelib.index_pages(PAGES)
    ids = [s["id"] for s in secs]
    assert ids == ["R402", "R402.1", "R402.1.2", "TABLE R402.1.3",
                   "R402.4", "R402.4.1.2"]
    src = tmp_path / "my iecc.pdf"
    d = fitz.open()
    for t in PAGES:
        d.new_page().insert_text((40, 40), t, fontsize=8)
    d.save(str(src))
    b = codelib.add_book(str(src), "2021 IECC")
    assert b["sections"] >= 5 and os.path.exists(b["pdf"])
    assert codelib.folder().startswith(str(tmp_path / "local"))
    hits = codelib.search("R402.4")
    assert [h[2]["id"] for h in hits][:2] == ["R402.4", "R402.4.1.2"]
    hits = codelib.search("air leakage testing")
    assert hits and hits[0][2]["id"] == "R402.4.1.2" and hits[0][2][
        "page"] == 2
    assert codelib.search("ceiling r-value")[0][2]["id"] == \
        "TABLE R402.1.3"
    assert codelib.remove_book("2021 IECC") and codelib.books() == []


def test_module_tab_has_energy_and_submittals(win, monkeypatch, tmp_path):
    # Submittal Log is on the Project tab and menu (Jon, Oct 20)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    for name in ("Climate Zone by County", "Code Library",
                 "Read the Energy Code Online", "Submittal Log"):
        a = win.command(name)
        assert a is not None and a.isEnabled(), name
    assert not [m for m in win._ribbon_missing
                if "Climate" in m or "Code Library" in m or
                "Submittal Log" in m]
    dlg = win.energy_code(0)
    dlg.climate.state.setCurrentIndex(dlg.climate.state.findData("MN"))
    dlg.climate.county.setCurrentText("Hennepin")
    assert "zone 6A" in dlg.climate.out.text()
    dlg.tabs.setCurrentIndex(1)
    assert dlg.library.book.count() == 1          # "All books" only
    dlg.close()


def test_rail_labels_fit(qapp):
    from PySide6.QtGui import QAction, QFont, QFontMetrics
    from app.modern_ui import RailButton
    a = QAction("Preflight / PDF/X…")
    b = RailButton(a)
    b.setFont(QFont(b.font().family(), 14))    # big Windows text size
    b.show()
    b._fit_label()
    assert QFontMetrics(b.font()).horizontalAdvance(b.text()) <= \
        RailButton.RAIL_TEXT_W or "font-size" in b.styleSheet()
    b.close()
