"""Import Roof Report: roof numbers read from a measurement report the user
already has (made-up report text only)."""
import pytest

from app import roof_report

SAMPLE = """Example Roof Report - Report 00000 (sample, not a real property)
Total Roof Facets = 14
Predominant Pitch = 7/12
Drip Edge (Eaves + Rakes) = 410 ft (20 Lengths)
Total Area (All Pitches) = 3,120 sq ft
Ridges = 72 ft (6 Ridges)
Hips = 96 ft 6 in (4 Hips)
Valleys = 38 ft (3 Valleys)
Rakes† = 150 ft (8 Rakes)
Eaves/Starter‡ = 260 ft (12 Eaves)
"""


def test_parse_full_report():
    r = roof_report.parse(SAMPLE)
    assert r["sloped_sf"] == 3120
    assert r["pitch"] == 7
    assert r["ridge"] == 72 and r["hip"] == 96.5 and r["valley"] == 38
    # the Drip Edge (Eaves + Rakes) total is not mistaken for rakes / eaves
    assert r["rake"] == 150 and r["eave"] == 260
    assert r["missing"] == []


def test_parse_colons_line_breaks_and_missing():
    r = roof_report.parse("Roof Area: 1,800 sq ft\nPredominant Pitch\n6/12\n"
                          "Ridges:\n40 ft\n")
    assert r["sloped_sf"] == 1800 and r["pitch"] == 6 and r["ridge"] == 40
    assert set(r["missing"]) == {"hip", "valley", "rake", "eave"}
    assert roof_report.parse("nothing here")["missing"] == list(
        roof_report.NAMES)


def test_pdf_report_fills_the_roofing_tab(tmp_path):
    pytest.importorskip("PySide6")
    fitz = pytest.importorskip("fitz")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from app.calculators_ui import CalculatorDialog
    pdf = tmp_path / "sample report.pdf"
    d0 = fitz.open()
    pg = d0.new_page()
    y = 72
    for line in SAMPLE.replace("†", "").replace("‡", "").splitlines():
        pg.insert_text((72, y), line, fontsize=10)
        y += 14
    d0.save(str(pdf))
    d0.close()
    d = CalculatorDialog(None, None, 2)
    rf = d.roofing
    got = rf.import_report(str(pdf))
    assert got["sloped_sf"] == 3120
    assert rf.sloped.value() == 3120 and rf.pitch.value() == 7
    assert rf.eave.value() == 260 and rf.rake.value() == 150
    assert rf.hip.value() == 96.5
    assert "Read: Roof area" in rf.report_note.text()
    assert "squares" in rf.out.text()
    # a file with no roof numbers changes nothing
    txt = tmp_path / "other.txt"
    txt.write_text("hello")
    rf.import_report(str(txt))
    assert "No roof measurements" in rf.report_note.text()
    assert rf.sloped.value() == 3120
    d.close()
