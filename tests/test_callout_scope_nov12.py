"""Nov 12: scope a retrofit set states away from its work notes - the
summary table, sentences in the numbered notes, what a replacement
implies, and the specification's rules. Made-up data."""
import os

import fitz

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:                                     # the window tests' fixtures
    from test_gui import win, qapp                              # noqa: F401
except Exception:                                         # noqa: BLE001
    pass

from app import callout_scope as cs
from app import callouts as co

NOTE = '''1. ELECTRICAL CONTRACTOR SHALL FURNISH AND INSTALL A
100A, 480V, 3-PHASE MANUAL TRANSFER SWITCH (MTS) AS SPECIFIED. FURNISH AND
INSTALL 4#1, #8 GND IN A 1-1/2" ALUMINUM RIGID
CONDUIT FROM THE GENERATOR TO THE NEW MTS AND FURNISH AND INSTALL
3#3/0, #6 GND IN A 2" ALUMINUM RIGID CONDUIT FROM THE MTS TO THE ATS.'''
HEADS = ["STATION SIGNAGE", "MANUAL\nTRANSFER\nSWITCH", "GATE"]


def table_words():
    words = [(300, 10, 380, 24, "SUMMARY"), (385, 10, 440, 24, "TABLE")]
    for j, hd in enumerate(HEADS):
        for k, line in enumerate(hd.split("\n")):
            for q, wd in enumerate(line.split()):
                x = 180 + j * 100 + q * 34
                words.append((x, 60 + k * 12, x + 30, 70 + k * 12, wd))
    for i in range(5):
        y = 110 + i * 40
        words.append((120, y, 150, y + 10, f"C-{i + 1}"))
        words.append((40, y, 100, y + 10, "STATION"))
        for j in range(3):
            if j == 0 or (i + j) % 2 == 0:
                words.append((196 + j * 100, y, 204 + j * 100, y + 10, "X"))
    return words


def notes(sheet="C-2"):
    return co.read_blocks([
        (["INSTALL:", "1 - MANUAL TRANSFER", "SWITCH (MTS)"], (0, 0, 50, 30)),
        (["REMOVE AND REPLACE:", "EXISTING STATION SIGNAGE WITH",
          "NEW STATION SIGN"], (0, 50, 50, 80)),
        (["INSTALL:", "130 LF SITE FENCING", "AND GATE"], (0, 90, 50, 120)),
        (["REPLACE:", "ALL BARBED WIRE", "(APPROX. 80 LF)"],
         (0, 130, 50, 160))], sheet)


def test_summary_table_marks():
    m = cs.marks(table_words())
    assert ("C-1", "STATION SIGNAGE") in m and ("C-5", "GATE") in m
    assert ("C-2", "MANUAL TRANSFER SWITCH") in m
    assert ("C-2", "GATE") not in m
    assert len(m) == 5 + 2 + 3
    assert all("SUMMARY" not in h for _, h in m)       # the title is not a heading
    assert cs.marks([w for w in table_words() if w[4] != "X"]) == []


def test_table_adds_only_what_no_counted_note_covers():
    rows = notes("C-2")
    add = cs.from_table(rows, cs.marks(table_words()))
    got = {(r["sheet"], r["what"]) for r in add}
    # C-2's sign and switch have notes; other sheets have none here
    assert ("C-2", "STATION SIGNAGE") not in got
    assert ("C-2", "MANUAL TRANSFER SWITCH") not in got
    assert ("C-4", "MANUAL TRANSFER SWITCH") in got
    assert all(r["check"] == [cs.MATRIX] and r["qty"] == 1 for r in add)
    # a length of fence covers the table's FENCING mark, and a removal
    # note covers its DEMOLITION mark
    more = [("C-2", "SITE FENCING"), ("C-2", "BARBED WIRE"),
            ("C-2", "DEMOLITION"), ("C-2", "SAFETY RAILING")]
    rows2 = notes("C-2") + co.read_blocks(
        [(["REMOVE:", "OLD FLOATS"], (0, 0, 9, 9))], "C-2")
    assert [r["what"] for r in cs.from_table(rows2, more)] == [
        "SAFETY RAILING"]
    # a gate named only inside a length of fence is not a counted gate
    rows3 = notes("C-3")
    assert ("C-3", "GATE") in {(r["sheet"], r["what"])
                               for r in cs.from_table(rows3,
                                                      cs.marks(table_words()))}


def test_rating_and_feeders_from_sentences():
    assert cs.equipment(NOTE) == [("100A, 480V, 3 PHASE",
                                   "MANUAL TRANSFER SWITCH")]
    assert cs.feeders(NOTE) == [
        (4, "#1", "#8", '1-1/2"', "ALUMINUM RIGID CONDUIT"),
        (3, "#3/0", "#6", '2"', "ALUMINUM RIGID CONDUIT")]
    rows = notes("C-2")
    add = cs.from_sentences(rows, NOTE, "C-2")
    sw = next(r for r in rows if "SWITCH" in r["what"])
    assert sw["what"].startswith("100A, 480V, 3 PHASE MANUAL TRANSFER")
    assert sw["qty"] == 1 and cs.RATED in sw["check"]
    # no note for the switch on another sheet: the sentence adds it
    other = cs.from_sentences(notes("C-2"), NOTE, "C-9")
    assert [r["what"] for r in other if r["unit"] == "EA"] == [
        "100A, 480V, 3 PHASE MANUAL TRANSFER SWITCH"]
    runs = [(r["what"], r["per_run_ft"]) for r in add]
    assert ('1-1/2" ALUMINUM RIGID CONDUIT', 1) in runs
    assert ("#1 WIRE", 4) in runs and ("#3/0 WIRE", 3) in runs
    assert all(r["qty"] == 0 and cs.MEASURE in r["check"] for r in add)


def test_a_replacement_removes_the_old_one():
    rem = cs.removals(notes())
    assert [(r["action"], r["qty"], r["unit"], r["what"]) for r in rem] == [
        ("Remove", 1, "EA", "EXISTING STATION SIGNAGE")]
    assert cs.IMPLIED in rem[0]["check"]


def test_spec_facts_and_fence_parts():
    spec = ("Line Post Spacing: As indicated on Drawings, not exceeding 10 "
            "feet. Extension Arms: to accommodate 3 strands of barbed wire. "
            "Barbed Wire: 12 gage thick wire, 2 strands, 4 points. Handrail "
            "post spacing shall not exceed 8-foot centers.")
    facts = cs.spec_facts(spec)
    assert facts == {"post_spacing_ft": 10.0, "barbed_strands": 3}
    parts = cs.fence_parts(notes(), facts)
    assert [(r["qty"], r["unit"]) for r in parts] == [(14, "EA"),
                                                      (390, "LF")]
    assert all(r["check"][0].startswith(cs.BY_SPEC) for r in parts)
    assert "the length the note states (130 LF)" in parts[0]["check"][0]
    # no rule in the documents: nothing is made up
    assert cs.fence_parts(notes(), {}) == []
    assert cs.spec_facts("Posts at 8 feet or 10 feet. Line post spacing: "
                         "not exceeding 8 feet. Line post spacing: not "
                         "exceeding 10 feet.") == {}


def make_set(path):
    doc = fitz.open()
    g = doc.new_page(width=800, height=600)
    for x0, y0, x1, y1, t in table_words():
        g.insert_text((x0, y1), t, fontsize=6)
    for i in range(5):
        p = doc.new_page(width=800, height=600)
        p.insert_textbox((60, 60, 300, 120), "REMOVE AND REPLACE:\n"
                         "EXISTING STATION SIGNAGE WITH\nNEW STATION SIGN",
                         fontsize=9)
        if i == 1:
            p.insert_textbox((400, 60, 780, 200), NOTE, fontsize=8)
            p.insert_textbox((60, 300, 300, 340), "INSTALL:\n95 LF SITE "
                             "FENCING", fontsize=9)
    doc.save(path)
    doc.close()
    return path


def test_read_a_set(tmp_path):
    path = make_set(str(tmp_path / "set.pdf"))
    names = ["G-1", "C-1", "C-2", "C-3", "C-4", "C-5"]
    rows, facts = cs.read_set(
        path, "Line post spacing: not exceeding 10 feet.",
        sheet_of=lambda page: names[page.number])
    assert facts == {"post_spacing_ft": 10.0}
    signs = [r for r in rows if "SIGNAGE" in r["what"] and
             r["action"] == "Remove and replace"]
    assert len(signs) == 5
    assert not [r for r in rows if r.get("source") == "table" and
                "SIGNAGE" in r["what"]]
    sw = sorted(r["sheet"] for r in rows if "TRANSFER SWITCH" in r["what"])
    # the table marks C-2 and C-4; C-2's sentence puts the rating on
    # the same row instead of adding a second switch
    assert sw == ["C-2", "C-4"]
    assert [r["what"] for r in rows if "TRANSFER SWITCH" in r["what"]
            and r["sheet"] == "C-2"] == [
        "100A, 480V, 3 PHASE MANUAL TRANSFER SWITCH"]
    assert sum(1 for r in rows if r.get("source") == "implied") == 5
    posts = [r for r in rows if r["what"].startswith("FENCE POSTS")]
    assert [(r["qty"], r["sheet"]) for r in posts] == [(11, "C-2")]


def keyed_blocks():
    b = [(["NOTES BY SYMBOL"], (600, 100, 760, 112))]
    notes = ["PROVIDE NEW SERVICE CONDUCTORS. INSTALL PER CODE.",
             "METER LOCATION TO BE COORDINATED. NEW METER ENCLOSURE SHALL "
             "BE WEATHERPROOF.",
             "PROVIDE A MOLDED-CASE CIRCUIT BREAKER IN AN ENCLOSURE, MOUNTED "
             "AT THE EXISTING RACK. PROVIDE EXTERNALLY OPERABLE HANDLE.",
             "PROVIDE 60A PANELBOARD WITH 12-POLE SPACES. PROVIDE A 30A, "
             "1-POLE BREAKER, WHICH SHALL FEED THE PANEL. PROVIDE ADDITIONAL "
             "20A, 1-POLE SPARE BREAKERS FOR FUTURE LOADS.",
             "EXISTING CONTROL PANEL SHALL REMAIN.",
             "FEEDER TAP LENGTH SHALL NOT EXCEED 25 FEET.",
             "EXISTING RACK EQUIPMENT SHALL BE DEMOLISHED."]
    for i, t in enumerate(notes):
        b.append(([f"{i + 1}.", t], (600, 120 + 30 * i, 780, 145 + 30 * i)))
    # the symbols on the drawing
    for lines, at in ((["3"], 100), (["3"], 140), (["PANEL", "4"], 180),
                      (["7", "7", "7"], 220), (["2", "M"], 260),
                      (["3", "GEN-D", '2"C.'], 340),  # a schedule row
                      (["1", "E-3"], 300)):          # a detail bubble
        b.append((lines, (200, at, 230, at + 20)))
    return b


def test_notes_by_symbol():
    rows = cs.keyed(keyed_blocks(), "E-3")
    got = [(r["action"], r["qty"], r["what"]) for r in rows]
    assert got == [
        ("Install", 1, "SERVICE CONDUCTORS"),
        ("Install", 1, "METER ENCLOSURE"),
        ("Install", 2, "MOLDED-CASE CIRCUIT BREAKER IN AN ENCLOSURE"),
        ("Install", 1, "60A PANELBOARD WITH 12-POLE SPACES"),
        ("Install", 1, "30A, 1-POLE BREAKER"),
        ("Install", 1, "20A, 1-POLE SPARE BREAKERS"),
        ("Demolish", 3, "RACK EQUIPMENT")]
    by = {r["what"]: r for r in rows}
    # note 1's number is only in a detail bubble: not a symbol
    assert by["SERVICE CONDUCTORS"]["check"] == [cs.KEY_ONCE]
    assert by["RACK EQUIPMENT"]["check"] == [cs.KEYED]
    assert by["RACK EQUIPMENT"]["ref"] == "NOTE 7"
    assert cs.keyed([(["GENERAL NOTES:"], (0, 0, 9, 9)),
                     (["1.", "PROVIDE A PUMP."], (0, 20, 9, 29))]) == []


def test_bar_scale():
    words = [(100, 500, 106, 510, "0"), (169, 500, 181, 510, "10'"),
             (241, 500, 253, 510, "20'"), (120, 515, 220, 525, "SCALE"),
             (40, 40, 46, 50, "0"), (300, 300, 320, 310, "16'")]
    assert abs(cs.bar_ppf(words) - 7.2) < 0.01
    assert cs.bar_ppf([w for w in words if w[1] != 500 or
                       w[4] == "0"]) is None
    two = words + [(100, 700, 106, 710, "0"), (300, 700, 312, 710, "10'")]
    assert cs.bar_ppf(two) is None              # two bars that disagree


def test_fence_as_drawn():
    pens = [("EX-FENCELINE", 0.36, 720.0), ("EX-FENCELINE", 2.16, 360.0),
            ("EX-DRIVE", 2.16, 999.0), ("X-FENCE-TX", 0, 9.0)]
    assert cs.fence_lines(pens) == (360.0, 1080.0)
    assert cs.fence_lines([("PROP-FENCELINE", 0.36, 72.0),
                           ("EX-FENCELINE", 0.36, 144.0)]) == (72.0, 216.0)
    assert cs.fence_lines([("EX-FENCELINE", 0.36, 144.0)]) == (0.0, 144.0)
    # the whole fence drawn heavy: it is all new
    assert cs.fence_lines([("EX-FENCELINE", 2.16, 144.0)]) == (144.0, 144.0)
    assert cs.fence_lines([("WALLS", 1.0, 50.0)]) == (0.0, 0.0)
    rows = notes("C-2")                     # 130 LF fencing, 80 LF barbed
    got = cs.measured(rows, pens, 7.2, "C-2")
    assert [(r["qty"], r["unit"], r["what"]) for r in got] == [
        (50.0, "LF", "NEW FENCE LINE AS DRAWN"),
        (150.0, "LF", "WHOLE FENCE LINE AS DRAWN")]
    assert "130 LF install" in got[0]["check"][0]
    assert cs.measured(rows, pens, None, "C-2") == []     # no scale: no guess
    assert cs.measured(rows, pens, 7.2, "C-9") == []      # no fence note


def test_posts_use_the_line_as_drawn_when_there_is_one():
    facts = {"post_spacing_ft": 10.0, "barbed_strands": 3}
    rows = notes("C-2")
    pens = [("EX-FENCELINE", 0.36, 720.0), ("EX-FENCELINE", 2.16, 396.0)]
    rows += cs.measured(rows, pens, 7.2, "C-2")       # new line: 55 LF
    parts = cs.fence_parts(rows, facts)
    assert [(r["qty"], r["unit"]) for r in parts] == [(7, "EA"),
                                                      (165, "LF")]
    assert "the new line as drawn (55 LF)" in parts[0]["check"][0]
    # one fence note and no heavy line: the whole line is the run
    one = co.read_blocks([(["REMOVE AND REPLACE:", "105 LF SITE FENCING"],
                           (0, 0, 9, 9))], "C-3")
    one += cs.measured(one, [("EX-FENCELINE", 0.36, 648.0)], 7.2, "C-3")
    assert [r["qty"] for r in cs.fence_parts(one, facts)] == [10, 270]
    # a gate note on the sheet: the measured new line says so
    g = notes("C-2") + co.read_blocks(
        [(["REMOVE AND REPLACE:", "ACCESS GATE WITH", "16-FOOT WIDE GATE"],
          (0, 0, 9, 9))], "C-2")
    g += cs.measured(g, pens, 7.2, "C-2")
    cs.flag_gates(g)
    new = next(r for r in g if r["what"].startswith("NEW FENCE LINE"))
    assert cs.GATE_IN_LINE in new["check"]
    table = cs.sheet_table(g)
    assert table[0][:2] == ["Sheet", "From"]
    assert {row[1] for row in table[1:]} == {"Sheet note",
                                             "Measured on the sheet"}


def test_the_window(win, tmp_path):
    from app import callouts_ui, simple_menu
    names = [n for _t, _g, ns, _a in simple_menu.TREE for n in ns]
    assert "Work Notes Takeoff" in names
    assert win.command("Work Notes Takeoff") is not None
    path = make_set(str(tmp_path / "set.pdf"))
    spec = fitz.open()
    spec.new_page().insert_text((72, 72), "Line post spacing: not exceeding "
                                "10 feet.", fontsize=10)
    spec_path = str(tmp_path / "spec.pdf")
    spec.save(spec_path)
    spec.close()
    win.open_path(path)
    dlg = win.work_notes_takeoff(modal=False)
    assert isinstance(dlg, callouts_ui.WorkNotesDialog)
    assert dlg.export(str(tmp_path / "none.xlsx")) is None   # nothing read
    rows = dlg.read()
    assert rows and dlg.every.rowCount() == len(rows)
    assert dlg.totals.rowCount() >= 3
    assert "to check" in dlg.status.text()
    heads = [dlg.every.horizontalHeaderItem(j).text()
             for j in range(dlg.every.columnCount())]
    assert heads[:2] == ["Sheet", "From"]
    froms = {dlg.every.item(i, 1).text() for i in range(len(rows))}
    assert {"Sheet note", "Summary table", "Worked out"} <= froms
    # the feeder make-up has no length: it says so, not 0
    qty = {dlg.every.item(i, 4).text() for i in range(len(rows))}
    assert "measure" in qty and "0" not in qty
    assert not [r for r in rows if r["what"].startswith("FENCE POSTS")]
    dlg.choose_spec(spec_path)                  # reads again with the rule
    assert [r["qty"] for r in dlg.rows
            if r["what"].startswith("FENCE POSTS")] == [11]
    assert "posts at 10 ft" in dlg.status.text()
    i = next(k for k, r in enumerate(dlg.rows) if r.get("page") == 3)
    assert dlg._open(i, 0) == 3 and win._view.page == 3
    out = dlg.export(str(tmp_path / "w.xlsx"))
    import zipfile
    assert zipfile.is_zipfile(out)
    dlg.close()


def test_keyed_notes_counted_by_the_symbols_shape():
    hexa, circ = (12, 0, 20, 23), (0, 4, 19, 19)
    # note 3 twice and note 7 three times in hexagons; 1, 2, 3 and 4 also
    # stand in circles (duct numbers) and bare (a schedule)
    syms = ([(3, hexa)] * 2 + [(7, hexa)] * 3 + [(4, hexa), (2, hexa),
                                                 (6, hexa)] +
            [(1, circ), (2, circ), (3, circ), (4, circ)] * 2 +
            [(1, None)] * 5 + [(3, None)] * 4)
    assert cs.pick_symbols(syms, {1, 2, 3, 4, 5, 6, 7}) == {
        3: 2, 7: 3, 4: 1, 2: 1, 6: 1}
    rows = cs.keyed(keyed_blocks(), "E-3", symbols=syms)
    by = {r["what"]: r for r in rows}
    assert by["MOLDED-CASE CIRCUIT BREAKER IN AN ENCLOSURE"]["qty"] == 2
    assert by["RACK EQUIPMENT"]["qty"] == 3
    assert by["60A PANELBOARD WITH 12-POLE SPACES"]["qty"] == 1
    assert by["METER ENCLOSURE"]["check"] == [cs.IN_SYMBOL]
    # note 1 is in no hexagon: counted once, and said so
    assert by["SERVICE CONDUCTORS"]["check"] == [cs.KEY_ONCE]
    # no shape holds three of the notes' numbers: the plain count is used
    few = [(3, hexa), (7, hexa), (1, None)]
    assert cs.pick_symbols(few, {1, 3, 7}) is None
    assert [r["check"] for r in cs.keyed(keyed_blocks(), "E-3", symbols=few)
            if r["what"] == "RACK EQUIPMENT"] == [[cs.KEYED]]


def test_a_keyed_note_that_says_demolish():
    assert cs._note_items("DEMOLITION THE HATCHED EQUIPMENT.") == [
        ("Demolish", "HATCHED EQUIPMENT")]
    assert cs._note_items("Remove the existing disconnect.") == [
        ("Demolish", "EXISTING DISCONNECT")]
    assert cs._note_items("EXISTING UTILITY POLE.") == []


def test_feeder_tags_on_a_one_line_diagram():
    blocks = [(["UTIL-03P", '4 #2, #8G., 1 1/4"C.'], (0, 0, 9, 9)),
              (["UTIL-03P", '4 #2, #8G., 1 1/4"C.'], (0, 50, 9, 59)),
              (["PB-01P", '4 #2, #8G., 1 1/4"C.', "PB-02P",
                '3 #4, #10G., 1"C.'], (0, 90, 9, 99)),
              (["UTIL-01P", '4 #1/0, 2"C.'], (0, 120, 9, 129)),
              (["125A", "ATS"], (0, 150, 9, 159)),
              (["1", "GEN-D", '3/4"C.'], (0, 180, 9, 189))]
    tags = cs.feeder_tags(blocks)
    assert tags == {"UTIL-03P": (4, "#2", "#8", '1-1/4"'),
                    "PB-01P": (4, "#2", "#8", '1-1/4"'),
                    "PB-02P": (3, "#4", "#10", '1"'),
                    "UTIL-01P": (4, "#1/0", "", '2"')}
    rows = cs.from_feeder_tags(blocks, "E-3")
    assert len(rows) == 3 + 3 + 3 + 2
    one = [(r["what"], r["per_run_ft"]) for r in rows
           if r["ref"] == "FEEDER PB-02P"]
    assert one == [('1" CONDUIT', 1), ("#4 WIRE", 3), ("#10 GROUND WIRE", 1)]
    assert all(r["qty"] == 0 and r["unit"] == "LF" and
               r["check"] == [cs.ONE_LINE] for r in rows)
    # shown as 'measure', not 0
    assert {row[4] for row in cs.sheet_table(rows)[1:]} == {"measure"}


def test_a_symbol_marked_typical_says_so():
    b = keyed_blocks() + [(["3", "TYP"], (300, 400, 330, 420))]
    rows = cs.keyed(b, "E-4")
    by = {r["what"]: r for r in rows}
    brk = by["MOLDED-CASE CIRCUIT BREAKER IN AN ENCLOSURE"]
    assert cs.TYPICAL in brk["check"] and brk["qty"] == 3
    assert cs.TYPICAL not in by["RACK EQUIPMENT"]["check"]
    assert "One-line diagram" in cs.SOURCES.values()
