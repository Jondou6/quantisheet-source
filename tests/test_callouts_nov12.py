"""Nov 12: quantities stated in words on a retrofit sheet ("INSTALL:
1 - 6-INCH PLUG VALVE"). Made-up notes and a made-up sheet."""
import fitz
import pytest

from app import callouts as co


def one(text):
    return co.parse(text.split(" / "))


def test_counted_items_under_a_heading():
    rows = one("INSTALL: / 1 - 6-INCH X 4-INCH TEE / 2 - 6-INCH PLUG VALVE"
               " / (DOWNSTREAM SIDE) / 1 - PIPE SUPPORT")
    assert [(r["action"], r["qty"], r["unit"], r["what"]) for r in rows] == [
        ("Install", 1, "EA", "6-INCH X 4-INCH TEE"),
        ("Install", 2, "EA", "6-INCH PLUG VALVE (DOWNSTREAM SIDE)"),
        ("Install", 1, "EA", "PIPE SUPPORT")]
    assert all(not r["check"] for r in rows)


def test_and_between_two_counted_items():
    rows = one("INSTALL: / 1 - 6-INCH X 4-INCH REDUCER / AND 1 - 4-INCH "
               "QUICK / CONNECT FITTING AND COVER")
    assert [r["what"] for r in rows] == [
        "6-INCH X 4-INCH REDUCER", "4-INCH QUICK CONNECT FITTING AND COVER"]


def test_a_size_is_not_a_count():
    rows = one("REMOVE AND REPLACE: / ACCESS GATE WITH / 16-FOOT WIDE GATE")
    assert [(r["qty"], r["unit"]) for r in rows] == [(1, "EA")]
    assert rows[0]["check"] == [co.NO_COUNT]
    tight = one("INSTALL: / 1-5 FOOT X 5 FOOT / HATCH GRATE")
    assert (tight[0]["qty"], tight[0]["what"]) == (1, "5 FOOT X 5 FOOT HATCH"
                                                   " GRATE")


def test_detail_reference_is_kept_apart():
    r = one("INSTALL: / 1 - 3 FOOT X 5 FOOT / HATCH GRATE / (SEE DETAIL 1 /"
            " SHEET D-1)")[0]
    assert r["what"] == "3 FOOT X 5 FOOT HATCH GRATE"
    assert r["ref"] == "DETAIL 1 SHEET D-1"


def test_lengths():
    r = one("REMOVE AND REPLACE: / 105 LF SITE FENCING / (SEE DETAIL 5.0)")[0]
    assert (r["action"], r["qty"], r["unit"], r["what"]) == (
        "Remove and replace", 105, "LF", "SITE FENCING")
    r = one("REPLACE: / ALL BARBED WIRE / (APPROX. 1,120 LF)")[0]
    assert (r["qty"], r["unit"], r["what"]) == (1120, "LF", "ALL BARBED WIRE")
    assert r["approx"] and co.APPROX in r["check"]
    r = one("REMOVE AND REPLACE: 150 / LF OF BARBED WIRE ALONG / NORTH SIDE")
    assert (r[0]["qty"], r[0]["what"]) == (150, "BARBED WIRE ALONG NORTH SIDE")


def test_two_actions_in_one_sentence():
    rows = one("REMOVE 24 LF AND INSTALL / 50 LF OF SITE FENCING / "
               "(SEE DETAIL 5.0)")
    assert [(r["action"], r["qty"], r["what"]) for r in rows] == [
        ("Remove", 24, "SITE FENCING"), ("Install", 50, "SITE FENCING")]
    rows = one("REMOVE 30 LF OF SITE / FENCING AND INSTALL / 50 LF OF SITE "
               "FENCING")
    assert [(r["action"], r["qty"], r["what"]) for r in rows] == [
        ("Remove", 30, "SITE FENCING"), ("Install", 50, "SITE FENCING")]


def test_count_in_words():
    r = one("REMOVE AND REPLACE TWO (2) / 4-INCH THREE WAY / PLUG VALVES")[0]
    assert (r["qty"], r["what"]) == (2, "4-INCH THREE WAY PLUG VALVES")


def test_not_a_work_note():
    assert one("EXISTING 1,437 LF 6-INCH / PVC FORCE MAIN") == []
    assert one("1. THE CONTRACTOR SHALL / INSTALL A SWITCH") == []
    assert co.parse(["INSTALL:"] + ["A LONG PARAGRAPH OF WORDS"] * 20) == []


def test_text_drawn_twice_is_marked():
    rows = one("INSTALL: / INSTALL: / 1 - HATCH / 1 - HATCH / GRATE / GRATE")
    assert rows and all(co.DOUBLED in r["check"] for r in rows)


def test_adding_up_across_sheets():
    rows = []
    for sheet, notes in (("C-1", ["INSTALL: / 1 - 3 FOOT X 5 FOOT / GRATE",
                                  "REMOVE AND REPLACE: / EXISTING SIGN",
                                  "REMOVE AND REPLACE: / EXISTING SIGN"]),
                         ("C-2", ["INSTALL: / 2 - 3-FOOT X 5-FOOT GRATES",
                                  "REMOVE AND REPLACE: / SIGN",
                                  "INSTALL: / 40 LF FENCE"]),
                         ("C-3", ["INSTALL: / 65.5 LF FENCE"])):
        blocks = [(n.split(" / "), (10.0, 20.0 * i, 90.0, 20.0 * i + 15))
                  for i, n in enumerate(notes)]
        rows += co.read_blocks(blocks, sheet)
    s = {(x["action"], x["what"], x["unit"]): x for x in co.summary(rows)}
    g = s[("Install", "3-FOOT X 5-FOOT GRATE", "EA")]
    assert (g["qty"], g["sheets"]) == (3, ["C-1", "C-2"])
    sign = s[("Remove and replace", "SIGN", "EA")]
    # the sign note is on C-1 twice: both counted, and said so
    assert (sign["qty"], sign["repeats"], sign["notes"]) == (3, 1, 3)
    assert co.REPEAT in sign["check"]
    assert s[("Install", "FENCE", "LF")]["qty"] == 105.5
    tot, each = co.table(rows)
    assert tot[0][:4] == ["Action", "Item", "Qty", "Unit"]
    assert len(each) == 1 + len(rows)


def test_a_second_heading_inside_a_note():
    rows = one("REMOVE OLD BYPASS / FITTING AND / INSTALL: / 1- 4-INCH QUICK"
               " / CONNECT FITTING")
    assert [(r["action"], r["qty"], r["what"]) for r in rows] == [
        ("Remove", 1, "OLD BYPASS FITTING"),
        ("Install", 1, "4-INCH QUICK CONNECT FITTING")]


def test_an_instruction_after_the_item_is_not_part_of_its_name():
    r = one("INSTALL: / 1 - 8-FOOT X 13-FOOT / HATCH GRATE / (SEE DETAIL 1)"
            " / CONTRACTOR TO FLUSH / DRAIN LINE")[0]
    assert r["what"] == "8-FOOT X 13-FOOT HATCH GRATE"
    assert r["note"] == "CONTRACTOR TO FLUSH DRAIN LINE"


def test_two_copies_on_top_of_each_other_are_read_once():
    blocks = [(["INSTALL:", "1-2-FOOT 4.5-FOOT HATCH", "GRATE"],
               (653, 1050, 791, 1092)),
              (["INSTALL:", "1 - 2-FOOT X 4.5-FOOT", "HATCH GRATE",
                "(SEE DETAIL 1)"], (633, 1050, 789, 1108)),
              (["INSTALL:", "1 - 2-FOOT X 4.5-FOOT", "HATCH GRATE"],
               (100, 300, 250, 350))]
    rows = co.read_blocks(blocks, "C-9")
    assert [r["what"] for r in rows] == ["2-FOOT X 4.5-FOOT HATCH GRATE"] * 2
    assert co.TWICE in rows[0]["check"] and co.REPEAT in rows[1]["check"]


def test_wordings_a_letter_apart_add_up_but_sizes_never_do():
    rows = []
    for i, w in enumerate(["EXISTING STATION SIGNAGE WITH NEW SIGN"] * 3 +
                          ["EIXSTING STATION SIGNAGE WITH NEW SIGN",
                           "STATION SIGNAGE WITH NEW SIGNS",
                           "2-FOOT X 2-FOOT GRATE", "2-FOOT X 3-FOOT GRATE"]):
        rows += co.read_blocks([(["INSTALL:", "1 - " + w],
                                 (0, 0, 50, 20))], f"C-{i}")
    s = {x["what"]: x for x in co.summary(rows)}
    assert s["STATION SIGNAGE WITH NEW SIGN"]["qty"] == 5
    assert s["STATION SIGNAGE WITH NEW SIGN"]["also"] == [
        "STATION SIGNAGE WITH NEW SIGNS"]
    assert s["2-FOOT X 2-FOOT GRATE"]["qty"] == 1
    assert s["2-FOOT X 3-FOOT GRATE"]["qty"] == 1


def test_quantity_printed_by_itself_takes_the_nearest_label():
    blocks = [(["LIMITS OF TREE", "CLEARING"], (100, 100, 180, 120)),
              (["APPROX. 50 SY"], (110, 126, 170, 136)),
              (["EXISTING WET WELL"], (400, 400, 480, 410))]
    r = co.read_blocks(blocks, "C-5")[0]
    assert (r["qty"], r["unit"], r["what"]) == (50, "SY",
                                                "LIMITS OF TREE CLEARING")
    assert co.LOOSE in r["check"] and r["approx"]


def sheet(path, rotate=0):
    doc = fitz.open()
    p = doc.new_page(width=800, height=600)
    p.insert_textbox((60, 60, 260, 130), "INSTALL:\n1 - 6-INCH PLUG VALVE\n"
                     "2 - PIPE SUPPORTS\n(SEE DETAIL 4)", fontsize=9)
    p.insert_textbox((400, 300, 640, 360), "REMOVE AND REPLACE:\n"
                     "85 LF SITE FENCING", fontsize=9)
    p.insert_textbox((400, 480, 700, 520), "EXISTING 900 LF 6-INCH\n"
                     "FORCE MAIN", fontsize=9)
    p.insert_text((700, 580), "C-4", fontsize=14)
    if rotate:
        p.set_rotation(rotate)
    doc.save(path)
    doc.close()
    return path


@pytest.mark.parametrize("rotate", [0, 90])
def test_read_a_sheet(tmp_path, rotate):
    path = sheet(str(tmp_path / "s.pdf"), rotate)
    rows = co.read_pdf(path, sheet_of=lambda page: "C-4")
    got = sorted((r["action"], r["qty"], r["unit"], r["what"]) for r in rows)
    assert got == [("Install", 1, "EA", "6-INCH PLUG VALVE"),
                   ("Install", 2, "EA", "PIPE SUPPORTS"),
                   ("Remove and replace", 85, "LF", "SITE FENCING")]
    assert {r["sheet"] for r in rows} == {"C-4"}
    assert all(r["ref"] == "DETAIL 4" for r in rows if r["unit"] == "EA")
    with fitz.open(path) as d:                 # the rect is where the note is
        r = next(x for x in rows if x["unit"] == "LF")
        box = fitz.Rect(r["rect"]) * ~d[0].rotation_matrix
        box.normalize()
        assert "FENCING" in d[0].get_text("text", clip=box + (-2, -2, 2, 2))
    out = co.export_xlsx(rows, str(tmp_path / "c.xlsx"))
    import zipfile
    assert zipfile.is_zipfile(out)
