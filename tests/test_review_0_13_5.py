"""0.13.4 review fixes (made-up data only): Import Roof Report (S1, S2, S3,
N1, N2, N3, N4, N11), a damaged estimate-layouts store is never
overwritten (S5), Project Center From Spec Book (S6), model_estimate
round_up (N5) and Generate Set ranges in Model Estimate (N10)."""
import json
import os
import types

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import roof_report                                      # noqa: E402

FULL = """Example Roof Report - Report 00000 (sample, not a real property)
Predominant Pitch = 7/12
Total Area (All Pitches) = 3,120 sq ft
Ridges = 72 ft (6 Ridges)
Hips = 96 ft 7 in (4 Hips)
Valleys = 22 ft (2 Valleys)
Rakes = 96 ft (8 Rakes)
Eaves/Starter = 152 ft 3 in (12 Eaves)
"""
AREA_AND_PITCH = """Example Roof Report - Report 00001 (sample)
Predominant Pitch = 5/12
Total Area (All Pitches) = 1,950 sq ft
"""


def _vals(text):
    r = roof_report.parse(text)
    return {k: v for k, v in r.items() if k in roof_report.NAMES}


# ---- S3: a combined line is not a hip or a ridge ----------------------------

def test_hip_and_ridge_cap_line_is_not_hips_or_ridges():
    r = roof_report.parse("Hip and Ridge Cap = 120 ft")
    assert "hip" in r["missing"] and "ridge" in r["missing"]
    # before the real lines, it doesn't replace them
    r = roof_report.parse("Hip and Ridge Cap = 120 ft\nHips = 96 ft\n"
                          "Ridges = 72 ft\n")
    assert r["hip"] == 96 and r["ridge"] == 72
    for t in ("Ridges and Hips = 168 ft", "Hips & Ridges = 168 ft",
              "Hips/Ridges = 168 ft", "Hips + Ridges = 168 ft"):
        assert _vals(t) == {}, t
    assert roof_report.parse("Hips = 96 ft")["hip"] == 96


def test_drip_edge_total_is_still_not_rakes_or_eaves():
    r = roof_report.parse("Drip Edge (Eaves + Rakes) = 410 ft (20 Lengths)\n"
                          "Structure 1  Drip Edge (Eaves + Rakes) = 410 ft")
    assert "rake" in r["missing"] and "eave" in r["missing"]


# ---- N1: more formats -----------------------------------------------------

@pytest.mark.parametrize("text,field,value", [
    ("Predominant Pitch = 6:12", "pitch", 6),
    ("Predominant Pitch = 6 in 12", "pitch", 6),
    ("Pitch = 6/12", "pitch", 6),
    ("Pitch: 8:12", "pitch", 8),
    ("Ridges = 72 LF", "ridge", 72),
    ("Valleys = 38 lf", "valley", 38),
    ("Total Area = 2,480.5 sq ft", "sloped_sf", 2480.5),
    ("Valleys = 1,072.5 ft", "valley", 1072.5),
    ("Total Roof Area = 31.2 squares", "sloped_sf", 3120),
    ("Roof Area: 24 Squares", "sloped_sf", 2400),
    ("Structure 1  Ridges = 72 ft", "ridge", 72),
    ("Building A\tHips = 40 ft 6 in", "hip", 40.5),
    ("Rakes ........ 150 ft", "rake", 150),
])
def test_more_report_formats(text, field, value):
    assert _vals(text) == {field: value}


def test_utf16_text_report(tmp_path):
    for enc in ("utf-16", "utf-16-le", "utf-16-be", "utf-8-sig"):
        p = tmp_path / f"report {enc}.txt"
        raw = FULL.encode(enc)
        if enc == "utf-16-le":
            raw = b"\xff\xfe" + raw
        elif enc == "utf-16-be":
            raw = b"\xfe\xff" + raw
        p.write_bytes(raw)
        got = roof_report.import_file(str(p))
        assert got["missing"] == [], enc
        assert got["sloped_sf"] == 3120 and got["eave"] == 152.25, enc


# ---- N2: value sanity -------------------------------------------------------

def test_negative_and_bad_inches_are_not_found():
    assert "ridge" in roof_report.parse("Ridges = -72 ft")["missing"]
    assert "ridge" in roof_report.parse("Ridges = −72 ft")["missing"]
    assert "ridge" in roof_report.parse("Ridges = 72 ft 18 in")["missing"]
    assert "ridge" in roof_report.parse("Ridges = 72 ft 12 in")["missing"]
    assert roof_report.parse("Ridges = 72 ft 11 in")["ridge"] == 72.92
    assert roof_report.parse("Hips = 96 ft 7 in")["hip"] == 96.58


# ---- N3: size and page caps -------------------------------------------------

def test_text_file_over_50_mb_is_refused_unread(tmp_path, monkeypatch):
    p = tmp_path / "huge report.txt"
    with open(p, "wb") as f:                 # sparse: 60 MB, nothing written
        f.truncate(60 * 1024 * 1024)
    opened = []
    real_open = open

    def spy(path, *a, **k):
        if str(path) == str(p):
            opened.append(path)
        return real_open(path, *a, **k)
    monkeypatch.setattr("builtins.open", spy)
    with pytest.raises(roof_report.RoofReportError) as e:
        roof_report.import_file(str(p))
    assert "too large" in str(e.value) and "50 MB" in str(e.value)
    assert opened == []


def _pdf(path, pages, **save):
    fitz = pytest.importorskip("fitz")
    d = fitz.open()
    for text in pages:
        pg = d.new_page()
        y = 72
        for line in text.splitlines():
            pg.insert_text((72, y), line, fontsize=10)
            y += 14
    d.save(str(path), **save)
    d.close()
    return str(path)


def test_pdf_reads_at_most_max_pages(tmp_path, monkeypatch):
    monkeypatch.setattr(roof_report, "MAX_PAGES", 2)
    p = _pdf(tmp_path / "long report.pdf",
             ["Example cover page", "Ridges = 72 ft",
              "Valleys = 38 ft"])
    got = roof_report.import_file(p)
    assert got["ridge"] == 72 and "valley" in got["missing"]
    assert any("first 2 of 3 pages" in n for n in got["notes"])


def test_caps_are_50_mb_and_200_pages():
    assert roof_report.MAX_TEXT_BYTES == 50 * 1024 * 1024
    assert roof_report.MAX_PAGES == 200


# ---- N4: password-protected PDF ---------------------------------------------

def test_password_protected_pdf_plain_message(tmp_path):
    fitz = pytest.importorskip("fitz")
    p = _pdf(tmp_path / "locked report.pdf", [FULL],
             encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="example-user",
             owner_pw="example-owner")
    with pytest.raises(roof_report.RoofReportError) as e:
        roof_report.import_file(p)
    assert str(e.value) == ("This PDF is password-protected; open it, save "
                            "an unprotected copy, then import it.")


# ---- the Roofing tab: S1, S2, N2 (decimals), N3/N4 notes, N11 ---------------

@pytest.fixture
def roofing():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from app.calculators_ui import CalculatorDialog
    d = CalculatorDialog(None, None, 2)
    yield d.roofing
    d.close()


def _txt(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_second_report_clears_what_it_lacks(roofing, tmp_path):
    rf = roofing
    rf.import_report(_txt(tmp_path, "a.txt", FULL))
    assert rf.hip.value() == 96.58           # 2 decimals: 96 ft 7 in
    assert rf.valley.value() == 22 and rf.rake.value() == 96
    assert rf.eave.value() == 152.25 and rf.ridge.value() == 72
    rf.import_report(_txt(tmp_path, "b.txt", AREA_AND_PITCH))
    assert rf.sloped.value() == 1950 and rf.pitch.value() == 5
    for w in (rf.ridge, rf.hip, rf.valley, rf.rake, rf.eave):
        assert w.value() == 0
    note = rf.report_note.text()
    assert "Read: Roof area, Pitch" in note
    assert "cleared to 0" in note
    for name in ("Ridges", "Hips", "Valleys", "Rakes", "Eaves"):
        assert name in note.split("cleared to 0")[1]


def test_out_of_range_values_are_left_alone_and_named(roofing, tmp_path):
    rf = roofing
    rf.import_report(_txt(tmp_path, "a.txt", FULL))
    assert rf.pitch.value() == 7
    pitch_max = rf.pitch.maximum()
    assert pitch_max <= 12                   # 12:12 is the hard cap
    steep = pitch_max + 6
    rf.import_report(_txt(tmp_path, "steep.txt",
                          f"Predominant Pitch = {steep:g}/12\n"
                          "Total Area = 20,000,000 sq ft\nRidges = 40 ft\n"))
    # review F10: a steep report's pitch is never the previous one's 7
    assert rf.pitch.value() == 0
    assert rf.sloped.value() == 3120         # left alone, named
    assert rf.ridge.value() == 40
    note = rf.report_note.text()
    assert f"Pitch out of range ({steep:g} in 12)" in note
    assert "pitch out of range - type it" in note
    assert "Roof area out of range (20,000,000 sq ft)" in note
    assert "Read: Ridges" in note
    # the out-of-range notes stand out (bold, red)
    head = note.split("cleared to 0")[0]
    assert head.count("<b>") == 2 and "color:#c00000" in head
    # out-of-range fields are not listed as cleared
    assert "Pitch" not in note.split("cleared to 0")[1]


def test_trademark_line_after_an_import(roofing, tmp_path):
    rf = roofing
    rf.import_report(_txt(tmp_path, "ev.txt",
                          "Example EagleView-style report (made up)\n" + FULL))
    assert ("EagleView is a trademark of EagleView Technologies, Inc.; "
            "QuantiSheet is not affiliated.") in rf.report_note.text()
    rf.import_report(_txt(tmp_path, "other.txt", FULL))
    assert "not affiliated" in rf.report_note.text()
    assert "EagleView" not in rf.report_note.text()


def test_tab_notes_for_big_and_locked_files(roofing, tmp_path):
    rf = roofing
    rf.import_report(_txt(tmp_path, "a.txt", FULL))
    p = tmp_path / "huge.txt"
    with open(p, "wb") as f:
        f.truncate(60 * 1024 * 1024)
    assert rf.import_report(str(p)) is None
    assert "too large" in rf.report_note.text()
    assert rf.sloped.value() == 3120         # nothing changed
    fitz = pytest.importorskip("fitz")
    locked = _pdf(tmp_path / "locked.pdf", [FULL],
                  encryption=fitz.PDF_ENCRYPT_AES_256,
                  user_pw="example-user", owner_pw="example-owner")
    assert rf.import_report(locked) is None
    assert rf.report_note.text().startswith(
        "This PDF is password-protected")


# ---- S5: a damaged estimate-layouts store -----------------------------------

@pytest.fixture
def layouts_doc(tmp_path, monkeypatch):
    fitz = pytest.importorskip("fitz")
    from app import assemblies, settings
    monkeypatch.setattr(assemblies, "LIBRARY_PATH",
                        str(tmp_path / "assemblies.json"))
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)
    d = fitz.open()
    d.new_page(width=612, height=792)
    yield d
    d.close()


def _damaged(doc):
    """A store with 2 layouts and 1 tag, then 5 bytes cut off the end."""
    from app import embfiles, estimate_layouts as L
    L.save_layout(doc, L.new_layout("Example A"))
    L.save_layout(doc, L.new_layout("Example B"))
    L.set_tag(doc, "example-line-1", "Phase 1")
    good = bytes(embfiles.get(doc, L.FILE))
    assert json.loads(good)["tags"] == {"example-line-1": "Phase 1"}
    bad = good[:-5]
    embfiles.put(doc, L.FILE, bad, "QuantiSheet estimate layouts")
    return bad


def test_damaged_store_is_never_overwritten(layouts_doc):
    from app import embfiles, estimate_layouts as L
    doc = layouts_doc
    bad = _damaged(doc)
    store = L.read_store(doc)
    assert store["damaged"] is True and store["layouts"] == []
    assert L.is_damaged(doc)
    for write in (lambda: L.set_tag(doc, "example-line-2", "Phase 2"),
                  lambda: L.save_layout(doc, L.new_layout("Example C")),
                  lambda: L.set_current(doc, "Example A"),
                  lambda: L.delete_layout(doc, "Example A"),
                  lambda: L.write_store(doc, L._blank())):
        with pytest.raises(L.LayoutStoreDamaged) as e:
            write()
        assert isinstance(e.value, L.LayoutError)
        assert "can't be read" in str(e.value)
        assert bytes(embfiles.get(doc, L.FILE)) == bad
    # the bytes are still in the saved PDF
    import fitz
    again = fitz.open(stream=doc.tobytes(), filetype="pdf")
    assert bytes(embfiles.get(again, L.FILE)) == bad
    again.close()


def test_not_a_json_object_counts_as_damaged(layouts_doc):
    from app import embfiles, estimate_layouts as L
    doc = layouts_doc
    embfiles.put(doc, L.FILE, b"[1, 2, 3]", "QuantiSheet estimate layouts")
    with pytest.raises(L.LayoutStoreDamaged):
        L.set_tag(doc, "example-line-1", "Phase 1")
    assert bytes(embfiles.get(doc, L.FILE)) == b"[1, 2, 3]"


def test_keep_a_damaged_copy_then_start_fresh(layouts_doc):
    import datetime
    from app import embfiles, estimate_layouts as L
    doc = layouts_doc
    bad = _damaged(doc)
    when = datetime.datetime(2026, 1, 2, 3, 4, 5)
    name = L.keep_damaged_copy(doc, when)
    assert name == "quantisheet_estimate_layouts.damaged-20260102-030405.json"
    assert bytes(embfiles.get(doc, name)) == bad
    assert L.FILE not in embfiles.names(doc)
    assert not L.is_damaged(doc)
    L.set_tag(doc, "example-line-2", "Phase 2")
    assert L.tags(doc) == {"example-line-2": "Phase 2"}
    assert bytes(embfiles.get(doc, name)) == bad
    # nothing damaged: nothing to keep
    assert L.keep_damaged_copy(doc) is None


def test_healthy_store_still_saves(layouts_doc):
    from app import estimate_layouts as L
    doc = layouts_doc
    assert not L.is_damaged(doc)
    L.save_layout(doc, L.new_layout("Example A"))
    L.set_tag(doc, "example-line-1", "Phase 1")
    assert [x["name"] for x in L.read_store(doc)["layouts"]] == ["Example A"]
    assert "damaged" not in L.read_store(doc)


def test_layouts_dialog_shows_the_damaged_message(layouts_doc):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from app import embfiles, estimate_layouts as L
    from app.estimate_ui import LayoutsDialog
    doc = layouts_doc
    bad = _damaged(doc)
    dlg = LayoutsDialog(doc)
    dlg.name.setText("Example C")
    assert dlg.save_current() is None
    assert "can't be read" in dlg.msg.text()
    assert bytes(embfiles.get(doc, L.FILE)) == bad
    dlg.close()


# ---- S6: Project Center From Spec Book --------------------------------------

def test_from_spec_book_runs_and_restores_the_cursor(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    pytest.importorskip("fitz")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from app.pm import center
    seen = []
    monkeypatch.setattr(center.QMessageBox, "information",
                        lambda *a, **k: seen.append(("info", a[2])))
    monkeypatch.setattr(center.QMessageBox, "warning",
                        lambda *a, **k: seen.append(("warn", a[2])))
    page = types.SimpleNamespace(
        store=types.SimpleNamespace(folder=str(tmp_path)))
    pdf = _pdf(tmp_path / "example spec book.pdf",
               ["EXAMPLE PROJECT MANUAL (made up)\nTable of contents"])
    got = center.ToolPage.from_spec_book(page, path=pdf, accept=lambda p: p)
    assert got == []
    assert seen and seen[-1][0] == "info"
    assert "No submittal articles found" in seen[-1][1]
    assert QApplication.overrideCursor() is None
    # a file that can't be read: a warning, and the cursor still restored
    junk = tmp_path / "not a pdf.pdf"
    junk.write_bytes(b"not a pdf at all")
    assert center.ToolPage.from_spec_book(page, path=str(junk),
                                          accept=lambda p: p) == []
    assert seen[-1][0] == "warn" and "Couldn't read" in seen[-1][1]
    assert QApplication.overrideCursor() is None


# ---- N5 / N10: Model Estimate -----------------------------------------------

def test_round_up_works():
    from app import model_estimate as M
    assert M.round_up(2.1) == 3 and M.round_up(4) == 4


def test_model_estimate_warns_outside_generate_set_ranges():
    from app import model_estimate as M
    inp = M.inputs("Single-family house", 50000, 60)
    w = " ".join(inp["warnings"])
    assert "400 to 8,000 SF" in w and "50,000 SF" in w
    assert "1 to 2 stories" in w and "has 60" in w
    res = M.price_quantities(inp)
    assert res["lines"] == [] and "1 to 2 stories" in res["error"]
    assert any("Outside the usual size" in n for n in res["notes"])
    # a house inside the range: no warnings
    assert M.inputs("Single-family house", 1600, 1)["warnings"] == []
    assert M.inputs("Single-family house", 2400, 2)["warnings"] == []
    # each type's own range
    big = M.inputs("Warehouse / industrial", 5000000)
    assert any("3,000 to 200,000 SF" in x for x in big["warnings"])
    assert M.inputs("Strip retail (multi-tenant)", 20000)["warnings"] == []
    assert M.inputs("Restaurant (stand-alone)", 4500)["warnings"] == []
    assert M.inputs("Small commercial", 100)["warnings"]
    # a type only your history knows has no Generate Set range
    assert M.inputs("Example Car Wash", 3000)["warnings"] == []
