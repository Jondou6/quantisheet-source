"""Nov 2 scope list (Jon: "do them"): shared tool sets and metric sets,
the live legend, written-scale guard, side lengths and captions,
rise/drop, wall area, volume units, copy several times, adding to a
count, converting a measurement, column choices with hidden numbers,
grouping and Excel/XML export, the count library's colors, proposal
qualifications and schedule, and the Takeoff Standard checklist."""
import json
import os

import pytest

fitz = pytest.importorskip("fitz")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import (annotate, columns, legend, measure_extra,  # noqa: E402
                 measure_tools, proposal, scale_guard, settings, standard,
                 takeoff, toolchest)
from test_gui import ANSWERS, win, qapp  # noqa: E402,F401

P = fitz.Point
SQ = [P(100, 100), P(300, 100), P(300, 300), P(100, 300)]      # 20 x 20 ft


def _scaled(win):
    v = win._view
    assert v.calibrate(240.0, real=24, unit="ft", all_pages=False)  # 10/ft
    return v


def _items(v, **kw):
    return [it for it in annotate.takeoff_items(v.doc)
            if all(it.get(k) == x for k, x in kw.items())]


def _select_tag(v, tag):
    for a in annotate.iter_annots(v.pg):
        if annotate.tag_of(a) == tag and not annotate.is_label(v.doc, a):
            v.select(a)
            return a
    raise AssertionError(tag)


# ---- pure helpers ---------------------------------------------------------------------

def test_openings_and_wall_values():
    assert measure_extra.parse_openings("3x7 x2, 6x4") == pytest.approx(66)
    assert measure_extra.parse_openings("2 x 3'x7'") == pytest.approx(42)
    assert measure_extra.parse_openings("42") == pytest.approx(42)
    assert measure_extra.parse_openings("") == 0
    assert measure_extra.parse_openings("door") is None
    assert measure_extra.run_value(100, {"height": 9, "openings": 66}) == \
        ("area", pytest.approx(834))
    assert measure_extra.run_value(40, {"rise": -8}) == \
        ("length", pytest.approx(48))
    assert measure_extra.volume_in(54, "cu ft", "cu yd") == pytest.approx(2)
    assert measure_extra.volume_in(2, "cu yd", "cu m") is None
    assert measure_extra.to_units("area", 10.7639, "ft", {"to": "m"})[0] \
        == pytest.approx(1.0, rel=1e-4)


def test_captions_join_and_back():
    assert measure_extra.join("Base", "12' 0\"", "both") == "Base: 12' 0\""
    assert measure_extra.join("Base", "12' 0\"", "value") == "12' 0\""
    assert measure_extra.join("Base", "12' 0\"", "name") == "Base"
    assert measure_extra.recaption("Base: 12'", "Base", "value") == "12'"
    assert measure_extra.recaption("12'", "Base", "both") == "Base: 12'"
    assert measure_extra.recaption("Base", "Base", "both", "12'") == \
        "Base: 12'"


def test_scale_guard_reduced_print_and_pages():
    d = fitz.open()
    for _ in range(3):
        d.new_page(width=36 * 72, height=24 * 72)          # ARCH D
    small = d.new_page(width=17 * 72, height=11 * 72)      # ANSI B
    small.insert_text((72, 72), "HALF SIZE PRINT")
    assert scale_guard.sheet_name(d[0]) == "ARCH D (24x36)"
    assert scale_guard.check(d, 0, '1/4" = 1\'-0"') == []
    warn = scale_guard.check(d, 3, '1/4" = 1\'-0"')
    assert any("HALF SIZE" in w for w in warn)
    assert any("ANSI B" in w for w in warn)
    assert any("most of the set" in w for w in warn)
    assert scale_guard.pages_like(d, 0) == [0, 1, 2]
    assert scale_guard.parse_pages("1-2, 4", 4) == [0, 1, 3]
    assert scale_guard.parse_pages("3-", 4) == [2, 3]
    assert scale_guard.parse_pages("x", 4) is None


def test_tool_set_file_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(toolchest, "PATH", str(tmp_path / "tc.json"))
    chest = {"Drywall": [{"name": "GWB", "tool": "measure_wall",
                          "color": [1, 0, 0], "subject": "GWB",
                          "height": "9'", "unit_cost": 2.35,
                          "fields": {"Product": "Type X"},
                          "evil": "<script>"}]}
    path = str(tmp_path / "team.qstools")
    toolchest.export_sets(chest, ["Drywall"], path, statuses=["Lack of "
                                                              "information"],
                          columns=[{"name": "Product", "type": "text"}])
    got = toolchest.read_sets(path, known={"measure_wall"})
    t = got["sets"]["Drywall"][0]
    assert "evil" not in t and t["unit_cost"] == 2.35
    assert got["statuses"] == ["Lack of information"]
    assert toolchest.style_of(t)["fields"] == {"Product": "Type X",
                                               "Unit Cost": 2.35}
    mine = {"Drywall": [{"name": "old", "tool": "count"}], "Other": []}
    assert toolchest.merge(mine, got["sets"]) == ["Drywall"]
    assert mine["Drywall"][0]["name"] == "GWB"            # replaced
    bad = tmp_path / "bad.qstools"
    bad.write_text(json.dumps({"sets": {}}))
    with pytest.raises(toolchest.ToolSetError):
        toolchest.read_sets(str(bad))
    with pytest.raises(toolchest.ToolSetError):
        toolchest.read_sets(path, known={"count"})        # no known tools
    assert "Takeoff (Metric)" in toolchest.DEFAULT


def test_choice_hidden_numbers_and_wall_names():
    col = {"name": "Floor Finish", "type": "choice",
           "choices": ["Carpet = 4.50", "Tile = $9.25", "Bare"]}
    assert columns.choice_labels(col) == ["Carpet", "Tile", "Bare"]
    assert columns.choice_value(col, "Tile") == 9.25
    assert columns.choice_value(col, "Bare") is None

    class Doc:
        pass
    items = [{"page": 0, "ref": {"target": "a"}, "mtype": "area",
              "mvalue": 100.0, "fields": {"Floor Finish": "Carpet"},
              "extra": {}},
             {"page": 0, "ref": {"target": "w"}, "mtype": "area",
              "mvalue": 810.0, "fields": {}, "extra": {"height": 9}}]
    data = {"columns": [col, {"name": "Cost", "type": "formula",
                              "formula": "Value * Floor_Finish"},
                        {"name": "Wall", "type": "formula",
                         "formula": "Wall_Area / Height"}],
            "values": {}}
    vals = columns.values_for(Doc(), items, data)
    assert vals["a"]["Floor Finish"] == "Carpet"
    assert vals["a"]["Cost"] == "450.00"
    assert vals["w"]["Wall"] == "90.00"


def test_group_summary_and_exports(tmp_path):
    items = [{"page": 0, "ref": {"target": str(i)}, "type": "Area",
              "subject": s, "comment": "", "measure": f"{v:,.2f} sq ft",
              "author": "", "date": "", "status": "", "origin": "manual",
              "mtype": "area", "mvalue": v, "color": "#ff0000"}
             for i, (s, v) in enumerate([("Carpet", 100.0), ("Tile", 50.0),
                                         ("Carpet", 25.0)])]
    got = columns.group_summary(items, "Subject")
    assert got[0] == ("Carpet", 2, {"sq ft": 125.0})
    rows = columns.rows_for_export(items, ["Page", "Type", "Subject",
                                           "Comment", "Measurement",
                                           "Author", "Date", "Status",
                                           "Origin"], [], {})
    x = columns.write_xml(str(tmp_path / "m.xml"), rows)
    text = open(x, encoding="utf-8").read()
    assert text.count("<Markup>") == 3 and "<Subject>Tile</Subject>" in text
    pytest.importorskip("openpyxl")
    from openpyxl import load_workbook
    columns.write_xlsx(str(tmp_path / "m.xlsx"), rows)
    ws = load_workbook(str(tmp_path / "m.xlsx")).active
    assert ws["C2"].value == "Carpet" and ws.max_row == 4


# ---- in the program -----------------------------------------------------------------

def test_wall_area_tool_and_reshape(win, monkeypatch):
    v = _scaled(win)
    v.style["subject"] = "Drywall"
    monkeypatch.setattr(v, "ask_wall",
                        lambda current=None: {"height": 9, "openings": 21})
    assert v.commit_points("measure_wall", [P(100, 100), P(300, 100),
                                            P(300, 200)])          # 30 ft
    it = _items(v, group="Drywall")[0]
    assert it["type"] == "area" and it["unit"] == "sq ft"
    assert it["value"] == pytest.approx(30 * 9 - 21)
    assert it["extra"]["height"] == 9
    assert "wall" in it["label"] and "9'" in it["label"]
    # reshape: the length changes, height and openings stay
    a = _select_tag(v, it["tag"])
    assert v.apply_marks([(v.page, "set_vertices", {
        "target": it["tag"], "pts": [[100, 100], [400, 100], [400, 200]]})])
    it = _items(v, group="Drywall")[0]
    assert it["value"] == pytest.approx(40 * 9 - 21)
    assert a is not None


def test_rise_drop_and_back(win):
    v = _scaled(win)
    v.style["subject"] = "Conduit"
    assert v.commit_points("measure_polylength", [P(100, 100), P(300, 100)])
    it = _items(v, group="Conduit")[0]
    _select_tag(v, it["tag"])
    assert measure_tools.set_rise(v, 8)
    it = _items(v, group="Conduit")[0]
    assert it["value"] == pytest.approx(28) and it["type"] == "length"
    assert "rise/drop" in it["label"]
    _select_tag(v, it["tag"])
    assert measure_tools.set_wall(v, 10)                  # now a wall
    it = _items(v, group="Conduit")[0]
    assert it["type"] == "area" and it["value"] == pytest.approx(280)
    _select_tag(v, it["tag"])
    assert measure_tools.set_wall(v, 0)                   # a length again
    assert _items(v, group="Conduit")[0]["type"] == "length"
    win.undo()
    assert _items(v, group="Conduit")[0]["type"] == "area"


def test_volume_shown_in_cubic_yards(win):
    v = _scaled(win)
    ANSWERS["text"] = "1'-6\""
    v.style["subject"] = "Slab"
    assert v.commit_points("measure_volume", SQ)
    it = _items(v, group="Slab")[0]
    assert it["value"] == pytest.approx(600) and it["unit"] == "cu ft"
    _select_tag(v, it["tag"])
    assert measure_tools.show_volume_in(v, "cu yd")
    it = _items(v, group="Slab")[0]
    assert it["value"] == pytest.approx(600 / 27) and it["unit"] == "cu yd"


def test_convert_area_to_perimeter_and_back(win):
    v = _scaled(win)
    v.style["subject"] = "Room"
    assert v.commit_points("measure_area", SQ)
    it = _items(v, group="Room")[0]
    _select_tag(v, it["tag"])
    assert "length" in measure_tools.convert_choices(
        measure_tools.selected_measure(v))
    assert measure_tools.convert(v, "length") == 1
    it = _items(v, group="Room")[0]
    assert it["type"] == "length" and it["value"] == pytest.approx(80)
    _select_tag(v, it["tag"])
    assert measure_tools.convert(v, "area") == 1
    it = _items(v, group="Room")[0]
    assert it["type"] == "area" and it["value"] == pytest.approx(400)
    _select_tag(v, it["tag"])
    assert measure_tools.convert(v, "volume", depth=2) == 1
    assert _items(v, group="Room")[0]["value"] == pytest.approx(800)


def test_copy_several_times(win):
    v = _scaled(win)
    v.style["subject"] = "Stall"
    assert v.commit_points("measure_area", [P(100, 100), P(130, 100),
                                            P(130, 150), P(100, 150)])
    it = _items(v, group="Stall")[0]
    _select_tag(v, it["tag"])
    ghosts = measure_tools.preview(v, 3, 40, "Right")
    assert len(ghosts) == 3
    assert measure_tools.multiply(v, 3, 40, "Right") == 3
    stalls = _items(v, group="Stall")
    assert len(stalls) == 4 and v.ghosts == []
    assert all(s["value"] == pytest.approx(15) for s in stalls)
    xs = sorted(round(s["rect"][0]) for s in stalls)
    assert xs[1] - xs[0] == pytest.approx(40, abs=2)
    # counts copy too, numbered on
    v.count_group = "Outlet"
    v.set_tool("count")
    assert v.commit_click("count", P(500, 400))
    c = _items(v, group="Outlet")[0]
    for a in annotate.iter_annots(v.pg):
        if annotate.tag_of(a) == c["tag"] and not annotate.is_label(
                v.doc, a):
            v.select(a)
            break
    assert measure_tools.multiply(v, 2, 30, "Down") == 2
    assert len(_items(v, group="Outlet")) == 3


def test_add_more_to_a_count(win):
    v = _scaled(win)
    v.count_group = "Duplex"
    v.set_tool("count")
    assert v.commit_click("count", P(500, 400))
    v.set_tool(None)
    v.count_group = "Something else"
    v.resume_count("Duplex")
    assert v.tool == "count" and v.count_group == "Duplex"
    assert v.commit_click("count", P(540, 400))
    assert len(_items(v, group="Duplex")) == 2


def test_captions_whole_document_and_back(win):
    v = _scaled(win)
    v.style["subject"] = "Base"
    assert v.commit_points("measure_polylength", [P(100, 100), P(300, 100)])
    tag = _items(v, group="Base")[0]["tag"]

    def label():
        return [(a.info or {}).get("content") for a in
                annotate.iter_annots(v.pg) if annotate.tag_of(a) == tag and
                annotate.is_label(v.doc, a) and a.type[0] ==
                fitz.PDF_ANNOT_FREE_TEXT][0]
    assert label() == "Base: 20' 0\""
    win.set_captions("value")
    assert label() == "20' 0\""
    win.set_captions("name")
    assert label() == "Base"
    win.set_captions("both")
    assert label() == "Base: 20' 0\""


def test_side_lengths_on_screen(win):
    v = _scaled(win)
    assert v.commit_points("measure_area", SQ)
    a = [x for x in annotate.iter_annots(v.pg)
         if x.type[0] == fitz.PDF_ANNOT_POLYGON][0]
    sides = measure_tools.side_lengths(v, a)
    assert [t for _p, t in sides] == ["20' 0\""] * 4
    settings.set("side_lengths", "all")
    assert measure_tools.shapes_for_sides(v, "all")
    v.grab()                                        # paints without error


def test_metric_tool_on_a_feet_sheet(win):
    v = _scaled(win)
    item = dict(toolchest.DEFAULT["Takeoff (Metric)"][2])        # m2
    win.use_chest_tool(item)
    assert v.commit_points("measure_area", SQ)
    it = _items(v, group="Flooring")[0]
    assert it["unit"] == "sq m"
    assert it["value"] == pytest.approx(400 * 0.3048 ** 2, rel=1e-3)
    # a reshape keeps it in square metres
    assert v.apply_marks([(v.page, "set_vertices", {
        "target": it["tag"], "pts": [[100, 100], [500, 100], [500, 300],
                                     [100, 300]]})])
    it = _items(v, group="Flooring")[0]
    assert it["unit"] == "sq m"
    assert it["value"] == pytest.approx(800 * 0.3048 ** 2, rel=1e-3)


def test_tool_with_unit_cost_fills_columns(win):
    v = _scaled(win)
    item = {"name": "Carpet", "tool": "measure_area", "subject": "Carpet",
            "unit_cost": 4.5, "fields": {"Product": "Loop pile"}}
    win.use_chest_tool(item)
    names = [c["name"] for c in columns.read(v.doc)["columns"]]
    assert {"Unit Cost", "Product", "Total Cost"} <= set(names)
    assert v.commit_points("measure_area", SQ)
    win.markups.refresh()
    it = [x for x in win.markups.items if x["subject"] == "Carpet"][0]
    vals = win.markups.values[columns.key_of(it)]
    assert vals["Product"] == "Loop pile"
    assert vals["Total Cost"] == "1,800.00"                 # 400 x 4.50


def test_tool_chest_panel_sets_and_files(win, tmp_path):
    chest = win.chest
    assert chest.new_set("Team")
    item = {"name": "Base", "tool": "measure_polylength", "subject": "Base"}
    chest.add(item, "Team")
    assert chest.edit_tool("Team", 0, {"name": "Base 4in",
                                       "subject": "Base", "unit_cost": 1.2,
                                       "rise": "0"})
    assert chest.chest["Team"][0]["unit_cost"] == 1.2
    path = chest.export_dialog(["Team"], str(tmp_path / "t.qstools"))
    chest.chest.pop("Team")
    chest.refresh()
    assert win.open_path(path)                    # double-click: added
    assert chest.chest["Team"][0]["name"] == "Base 4in"
    assert chest.rename_set("Team", "Office")
    assert "Office" in chest.chest and "Team" not in chest.chest


def test_live_legend_all_pages_and_tool_set(win):
    v = _scaled(win)
    chest = {"Floors": [{"name": "Carpet", "tool": "measure_area",
                         "subject": "Carpet", "color": [0, 0.5, 0]},
                        {"name": "Tile", "tool": "measure_area",
                         "subject": "Tile", "color": [0, 0, 0.5]}]}
    opts = {"scope": "all", "live": True, "count": True, "sets": ["Floors"],
            "tools": legend.set_tools(chest, ["Floors"])}
    v.style["subject"] = "Carpet"
    assert v.commit_points("measure_area", SQ)
    assert v.add_legend(fitz.Rect(450, 50, 650, 100), opts=opts)

    def rows():
        for a in annotate.iter_annots(v.pg):
            if annotate.is_legend(v.doc, a):
                o = legend.opts_of(v.doc, a)
                return {r["name"]: r for r in legend.rows_for(v.doc, v.page,
                                                              o)}
    got = rows()
    assert set(got) == {"Carpet", "Tile"}
    assert got["Tile"]["n"] == 0
    assert got["Carpet"]["total"] == pytest.approx(400)
    # a new markup redraws the legend by itself, in the same undo step
    assert v.commit_points("measure_area", [P(400, 400), P(500, 400),
                                            P(500, 500), P(400, 500)])
    texts = " ".join((a.info or {}).get("content", "") for a in
                     annotate.iter_annots(v.pg) if annotate.is_label(
                         v.doc, a))
    assert "500.0 SQ FT" in texts and "(2)" in texts


def test_scale_preset_on_chosen_pages(win):
    v = win._view
    n = v.doc.page_count
    win.apply_scale_preset('1/8" = 1\'-0"', 9.0, "ft", all_pages=[0])
    sc = annotate.read_scales(v.doc)
    assert sc[0]["ppu"] == 9.0
    assert all(i not in sc or sc[i]["ppu"] != 9.0 for i in range(1, n))


def test_takeoff_standard(win):
    v = _scaled(win)
    rows = {r["key"]: r for r in standard.status(v.doc)}
    assert not rows["setup"]["done"] and rows["setup"]["auto"]
    v.style["subject"] = "Carpet"
    assert v.commit_points("measure_area", SQ)
    rows = {r["key"]: r for r in standard.status(v.doc)}
    assert rows["setup"]["done"] and rows["tools"]["done"]
    assert not rows["legends"]["done"]
    standard.tick(v.doc, "report")
    assert {r["key"]: r for r in standard.status(v.doc)}["report"]["done"]
    standard.set_own_steps(["Waste: add 10% to flooring"])
    own = [r for r in standard.status(v.doc) if r["key"] == "own0"]
    assert own and own[0]["title"] == "Waste"


def test_proposal_lists_takeoff_assumptions(win, monkeypatch):
    v = _scaled(win)
    v.style["subject"] = "Gyp"
    monkeypatch.setattr(v, "ask_wall",
                        lambda current=None: {"height": 9, "openings": 21})
    assert v.commit_points("measure_wall", [P(100, 100), P(300, 100)])
    v.style["subject"] = "Conduit"
    v.style["rise"] = 8
    assert v.commit_points("measure_polylength", [P(100, 300),
                                                  P(300, 300)])
    notes = proposal.takeoff_notes(v.doc)
    assert any("Gyp wall areas use a 9' 0\" wall height, less the "
               "openings" in n for n in notes)
    assert any("Conduit: 1 run(s) include 8' 0\" of rise/drop" in n
               for n in notes)
    data = proposal.read(v.doc)
    data["qualifications"] = "Normal working hours"
    out = proposal.make_pdf(v.doc, data, {"name": "Test Co"})
    text = "".join(p.get_text() for p in out)
    assert "Qualifications" in text and "Normal working hours" in text
    assert "rise/drop" in text


def test_count_library_keeps_a_color(win, tmp_path, monkeypatch):
    from app import count_library
    monkeypatch.setattr(count_library, "path",
                        lambda: str(tmp_path / "lib.json"))
    count_library.add("Smoke", b"\x89PNG fake", color=[0, 0.5, 1])
    assert count_library.colors() == {"Smoke": [0, 0.5, 1]}
    assert count_library.set_color("Smoke", [1, 0, 0])
    marks = count_library.review_marks(
        {"Smoke": [{"page": 0, "rect": [10, 10, 20, 20], "score": 0.9}]},
        win._view.doc)
    assert marks[0][2]["color"] == [1, 0, 0]
