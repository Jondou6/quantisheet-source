"""Civil sets (Nov 19): engineering scales and graphic-scale labels read
from sheet text the way OCR leaves it. Made-up text only."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import autoscale as a  # noqa: E402


def test_profile_scale_prefers_horizontal():
    t = "PROFILE\nSCALE: 1\" = 10' VERT.\nSCALE: 1 20' HORIZ.; VERT 100"
    assert a.civil_scale(t)[0] == '1" = 20\''
    assert a.civil_scale("SCALE: 1\"=40'")[2] == "ft"
    assert a.civil_scale("SHEET SCALE: AS SHOWN") is None


def test_graphic_scale_labels():
    g = a.graphic_scale
    assert g("PLAN\nSCALE:\n20'\n0\n20'\n40'\nGRAPHIC\nSCALE")[0] == '1" = 20\''
    assert g("SCALE:\n10?\nwe\n10?\n20?\nGRAPHIC SCALE")[0] == '1" = 10\''
    assert g("SCALE:\n5\n10\nGRAPHIC SCALE")[1] == 72.0 / 5
    assert g("SCALE:\nOw\nxo\n26\nGRAPHIC SCALE") is None
    assert g("SHEET SCALE: AS SHOWN\nno bar here") is None


def test_ocr_words_become_printed_lines():
    import fitz
    from app import acrobat
    w = [(fitz.Rect(10, 0, 30, 10), "130"), (fitz.Rect(33, 0, 45, 10), "LF"),
         (fitz.Rect(48, 0, 55, 10), '4"'), (fitz.Rect(58, 0, 75, 10), "PVC"),
         (fitz.Rect(10, 30, 40, 40), "FORCE"),
         (fitz.Rect(43, 30, 60, 40), "MAIN"),
         (fitz.Rect(300, 0, 330, 10), "far")]
    got = [t for _r, t in acrobat.ocr_lines(w)]
    assert got == ['130 LF 4" PVC', "FORCE MAIN", "far"]


def test_ocr_layer_reads_as_a_pipe_label():
    import fitz
    from app import acrobat, civiltakeoff as ct
    d = fitz.open()
    pg = d.new_page(width=792, height=612)
    words = [(fitz.Rect(100 + 30 * i, 200, 126 + 30 * i, 210), t)
             for i, t in enumerate(["130", "LF", '4"', "PVC", "FORCE",
                                    "MAIN"])]
    assert acrobat.add_words(pg, words) == 1
    labs = ct.pipe_labels(pg)
    assert labs and labs[0]["size"] == 4 and labs[0]["length"] == 130


def test_scale_read_by_position_not_text_order():
    # an OCR layer: the bar labels come out far from SCALE: in text order
    words = [(500, 300, 530, 310, "GRAPHIC"), (533, 300, 560, 310, "SCALE"),
             (480, 285, 492, 295, "20'"), (500, 285, 506, 295, "0"),
             (520, 285, 532, 295, "20'"), (545, 285, 557, 295, "40'"),
             (100, 100, 130, 110, "SCALE:"), (133, 100, 136, 110, "1"),
             (139, 100, 151, 110, "20'"), (154, 100, 184, 110, "HORIZ."),
             (700, 700, 720, 710, "10"), (723, 700, 735, 710, "LF")]
    civ, gra = a.scale_words(None, words)
    assert a.civil_scale(" ; ".join(civ))[0] == '1" = 20\''
    assert a.graphic_labels(" ".join(gra))[0] == '1" = 20\''
    assert a.graphic_labels("STA 2+00 10 LF") is None


def test_ocr_label_takes_its_size_from_the_line_type_tag():
    import fitz
    from app import civiltakeoff as ct
    R = fitz.Rect
    items = [("239 LF", R(100, 100, 135, 110), 10.4, (1, 0)),
             ("RJ PVC", R(165, 100, 200, 110), 10.4, (1, 0)),
             ("N6FM", R(400, 300, 425, 310), 10.1, (1, 0)),
             ("N6FM", R(600, 300, 625, 310), 10.1, (1, 0)),
             ("TIE TO E12FM", R(50, 400, 120, 410), 10.4, (1, 0)),
             ("85 LF", R(300, 500, 330, 510), 10.4, (1, 0))]
    got = ct.ocr_labels(items)
    assert len(got) == 1
    p = ct.parse_pipe_label(got[0][0])
    assert p["size"] == 6 and p["length"] == 239 and \
        p["system"] == "force main" and not p["existing"]
    # two new sizes on the sheet: no guess
    items.append(("N8FM", R(700, 300, 725, 310), 10.1, (1, 0)))
    assert ct.ocr_labels(items) == []


def test_joint_and_comma_lengths():
    from app import civiltakeoff as ct
    p = ct.parse_pipe_label('1,541 LF 6" RJ PVC FORCE MAIN')
    assert p["length"] == 1541 and p["material"] and p["size"] == 6
    assert ct.parse_pipe_label('8" MJ DIP W')["size"] == 8


def test_stations_chain_across_plan_and_profile_sheets():
    import fitz
    from app import civiltakeoff as ct
    d = fitz.open()
    for texts in (["STA 0+00", "STA 4+10", "1+00"],
                  ["STA 4+10", "STA 9+80"],
                  ["STA 9+80", "STA 15+41"],
                  ["0+00", "STA 0+20", "STA 2+39", "2+50"]):
        pg = d.new_page(width=792, height=612)
        for i, t in enumerate(texts):
            pg.insert_text((72, 72 + 20 * i), t, fontsize=10)
    runs = ct.station_runs(d, range(4))
    assert [(ps, lo, hi) for ps, lo, hi in runs] == \
        [([0, 1, 2], 0, 1541), ([3], 0, 239)]
    assert ct.fmt_station(1541) == "15+41"


def test_same_title_sheets_chain_over_a_reading_gap():
    import fitz
    from app import civiltakeoff as ct
    d = fitz.open()
    for texts in (["STA 0+00", "STA 4+10"], ["STA 4+71", "STA 5+65"],
                  ["10+00", "STA 10+54", "STA 15+41"]):
        pg = d.new_page(width=792, height=612)
        for i, t in enumerate(texts):
            pg.insert_text((72, 72 + 20 * i), t, fontsize=10)
    t = {i: "MAIN ST FORCE MAIN PLAN & PROFILE" for i in range(3)}
    assert ct.station_runs(d, range(3), t) == [([0, 1, 2], 0, 1541)]
    assert len(ct.station_runs(d, range(3))) == 2


def test_station_length_replaces_a_bad_trace(monkeypatch):
    import fitz
    from app import aitakeoff as ait, civiltakeoff as ct
    d = fitz.open()
    for texts in (["STA 0+00", "STA 4+10"], ["STA 4+10", "STA 9+00"]):
        pg = d.new_page(width=792, height=612)
        for i, t in enumerate(texts):
            pg.insert_text((72, 72 + 20 * i), t, fontsize=10)
    rows = {0: {"number": "C1", "title": "FORCE MAIN PLAN & PROFILE"},
            1: {"number": "C2", "title": "FORCE MAIN PLAN & PROFILE"}}
    new = [{"name": '6" PVC FM', "existing": False,
            "runs": [{"page": 0, "length": 2000.0, "pts": [], "depth": None},
                     {"page": 1, "length": 10.0, "pts": [], "depth": None}]}]
    res = {"quantities": [], "problems": []}
    left = ait._station_lengths(d, [0, 1], new, rows, res)
    assert left == []
    q = res["quantities"][0]
    assert q["qty"] == 900 and q["status"] == "check" and \
        q["csi"] == "33 34 00" and "0+00 to 9+00" in q["basis"]
    # a trace within 10% is kept as it is
    new[0]["runs"] = [{"page": 0, "length": 880.0, "pts": [], "depth": None}]
    res = {"quantities": [], "problems": []}
    assert ait._station_lengths(d, [0, 1], new, rows, res) == new
    assert res["quantities"] == []


def test_callout_in_plan_and_profile_is_one_structure():
    import fitz
    from app import civiltakeoff as ct
    d = fitz.open()
    pg = d.new_page(width=1224, height=792)
    pg.insert_text((100, 100), "STA 1+65:", fontsize=10)
    pg.insert_text((100, 113), "1-AIR RELEASE VALVE & MANHOLE", fontsize=10)
    pg.insert_text((700, 600), "STA 1+65 1-AIR RELEASE VALVE & MANHOLE",
                   fontsize=10, rotate=90)
    pg.insert_text((300, 400), "STA 0+20", fontsize=10)
    pg.insert_text((300, 413), "1-AIR RELEASE VALVE & MANHOLE", fontsize=10)
    pg.insert_text((900, 300), "NEW SSMH", fontsize=10)
    pg.insert_text((900, 313), "STA 15+41", fontsize=10)
    tags = ct.structure_tags(pg)
    got = sorted((t["kind"], t.get("station")) for t in tags)
    assert got == [("manhole", 20.0), ("manhole", 165.0),
                   ("manhole", 1541.0)]


def test_work_notes_skip_notes_with_nothing_to_count():
    from app import callouts as c
    for ls in (["INSTALL AT"], ["INSTALL", "AT STA 1+56"],
               ["INSTALL", "RJ PVC"], ["INSTALL", '6" RJ PVC FORCE MAIN']):
        assert c.parse(ls) == [], ls
    assert c.parse(["INSTALL FIRE HYDRANT"])[0]["qty"] == 1
    assert c.parse(["INSTALL", '1 - 6" PLUG VALVE'])[0]["what"] == \
        '6" PLUG VALVE'


def test_manhole_rehab_is_counted_work():
    import fitz
    from app import civiltakeoff as ct
    d = fitz.open()
    pg = d.new_page(width=1224, height=792)
    pg.insert_text((100, 100), "MANHOLE REHABILITATION", fontsize=10)
    pg.insert_text((100, 300), "EX MANHOLE No. 9 - INTERIOR COATING",
                   fontsize=10)
    pg.insert_text((600, 500), "EX MANHOLE No. 4", fontsize=10)
    tags = {t["id"]: (t["kind"], t["existing"]) for t in ct.structure_tags(pg)}
    assert tags["MHR-9"] == ("manhole rehab", False)
    assert tags["MH-4"] == ("manhole", True)
    rehab = [v for k, v in tags.items() if k.startswith("MHR p")]
    assert rehab == [("manhole rehab", False)]
    assert "rehabilitation" in ct._struct_base_name("manhole rehab")


def test_rehab_counted_from_a_site_plan():
    import fitz
    from app import aitakeoff as ait
    d = fitz.open()
    pg = d.new_page(width=1224, height=792)
    pg.insert_text((100, 100), "MANHOLE REHABILITATION", fontsize=10)
    rows = {0: {"number": "C2", "title": "PUMP STATION SITE PLAN"}}
    q = ait._rehab_counts(d, [0], rows)
    assert len(q) == 1 and q[0]["qty"] == 1 and q[0]["unit"] == "EA"
    assert q[0]["status"] == "check" and "C2" in q[0]["basis"]
    assert ait._rehab_counts(d, [], rows) == []
