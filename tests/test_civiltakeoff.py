"""Civil / wastewater takeoff (review R6): pipe LF by size within 2% of a
hand takeoff, manholes counted exactly, depths from RIM/INV, profiles
left out, trench assemblies priced by depth."""
import importlib.util
import os

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import annotate, assemblies, civiltakeoff as ct      # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _tool():
    spec = importlib.util.spec_from_file_location(
        "civil_real", os.path.join(ROOT, "tools", "civil_real.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.mark.parametrize("seed", [3, 5, 8, 11])
def test_plan_and_profile_against_hand_takeoff(seed):
    out, doc, res = _tool().score(seed, verbose=False)
    for size, err in out["lf_err"].items():
        assert err <= 0.02, (seed, size, out)
    assert out["manholes_found"] == out["manholes_truth"], out
    assert out["depths_right"] == out["manholes_truth"], out
    assert out["existing"] == ['6" DIP water (existing)']


def test_profile_is_found_and_left_out():
    doc, truth = _tool().make(3)
    zones = ct.profile_zones(doc[0])
    assert len(zones) == 1 and zones[0].y0 > 900


@pytest.mark.parametrize("text, size, mat, system, slope, length", [
    ('8" PVC SDR-35', 8, "PVC", "sanitary", None, None),
    ('245 LF 8" PVC @ 0.50%', 8, "PVC", "sanitary", 0.5, 245),
    ('12" RCP', 12, "RCP", "storm", None, None),
    ('4" PVC FM', 4, "PVC", "force main", None, None),
    ('6" DIP WATER MAIN', 6, "DIP", "water", None, None),
    ("L=312' 10\" PVC SDR-26 S=0.0028", 10, "PVC", "sanitary", 0.28, 312),
])
def test_pipe_labels(text, size, mat, system, slope, length):
    p = ct.parse_pipe_label(text)
    assert p["size"] == size and p["material"] == mat
    assert p["system"] == system
    assert (p["slope"] is None) == (slope is None)
    if slope:
        assert p["slope"] == pytest.approx(slope)
    assert p["length"] == length
    assert ct.parse_pipe_label("SCALE 1\" = 40'") is None
    assert ct.parse_pipe_label('EX. 8" VCP SAN')["existing"]


def test_structure_tags_and_inverts():
    doc = fitz.open()
    pg = doc.new_page(width=1000, height=800)
    pg.insert_text((100, 100), "SSMH #3", fontsize=8)
    pg.insert_text((100, 110), "RIM=104.50", fontsize=6)
    pg.insert_text((100, 119), 'INV IN (W) 8"=96.20', fontsize=6)
    pg.insert_text((100, 128), "INV OUT (E) 8\"=96.10", fontsize=6)
    pg.insert_text((400, 300), "CO-2", fontsize=8)
    pg.insert_text((600, 300), "EX. MH-7", fontsize=8)
    pg.insert_text((600, 500), "MH 4' DIA", fontsize=8)
    st = {s["id"]: s for s in ct.structures(pg)}
    assert set(st) == {"MH-3", "CO-2", "MH-7"}
    assert st["MH-3"]["depth"] == pytest.approx(8.4)
    assert st["MH-7"]["existing"] and st["CO-2"]["kind"] == "cleanout"


def test_assemblies_and_pricing():
    out, doc, res = _tool().score(3, verbose=False)
    lib = ct.assemblies_for(res)
    pipe = [a for n, a in lib.items() if n.startswith('8" PVC sanitary')]
    assert pipe and pipe[0]["props"]["D"] == 8
    assert 4 <= pipe[0]["props"]["H"] <= 14
    mh = [a for n, a in lib.items() if n.startswith("Sanitary manhole")]
    assert mh and sum(1 for _ in mh) >= 1
    n = ct.apply(doc, res)
    assert n > 0
    rows, totals, errors = assemblies.rollup(doc, book=None)
    names = {r["name"] for r in rows}
    assert any(x.startswith('8" PVC sanitary') for x in names), names
    r8 = next(r for r in rows if r["name"].startswith('8" PVC sanitary'))
    parts = {p["name"]: p for p in r8["parts"]}
    assert parts["Trench excavation"]["qty"] > 0
    assert parts["Bedding stone, 6 in below pipe to springline"]["qty"] > 0
    mrow = next(r for r in rows if r["name"].startswith("Sanitary manhole"))
    assert mrow["quantity"] == out["manholes_truth"] or mrow["items"] >= 1
    items = annotate.takeoff_items(doc)
    assert sum(1 for i in items if i["type"] == "count") == \
        out["manholes_truth"]


def test_catalog_has_civil_assemblies():
    lib = assemblies.library()
    for name in ("Gravity sewer, PVC SDR-35, trenched",
                 "Gravity sewer, PVC SDR-35, 10-14 ft deep",
                 "Force main, PVC C900, trenched",
                 'Sanitary manhole, 48" precast, by depth',
                 "Trench pavement restoration",
                 "Trench dewatering, wellpoints",
                 "Pump station, 8 ft precast wet well"):
        assert name in lib, name
    a = lib["Gravity sewer, PVC SDR-35, trenched"]
    parts = {p["name"]: p for p in assemblies.compute(
        a, {"length": 100})}
    # 100 LF of 8" at 8 ft: (8/12+2) x 8.5 x 100 / 27 = 83.95 CY
    assert parts["Trench excavation"]["qty"] == pytest.approx(83.95, abs=0.1)
    assert parts["Trench box / shoring, over 5 ft deep"]["qty"] == 100


def test_civil_tab_in_window(qapp, win, tmp_path):
    doc, truth = _tool().make(3)
    annotate.apply_op(doc, annotate.new_op("set_scale", 0,
                                           ppu=_tool().PPU, unit="ft",
                                           name="1\" = 40'"))
    path = str(tmp_path / "civil.pdf")
    doc.save(path)
    win.open_path(path)
    dlg = win.trade_takeoff(show=False)
    assert dlg.tabs.tabText(0).replace("&&", "&") == "Civil & Utilities"
    data = dlg.civil.find()
    assert data and any(d[0] == "pipe" for d in data)
    assert dlg.civil.add() > 0
    groups = {i["group"] for i in annotate.takeoff_items(win._view.doc)}
    assert any(g.startswith('8" PVC sanitary') for g in groups)


from test_gui import win, qapp                     # noqa: E402,F401


# ------------------------------------------------- real-set label styles
@pytest.mark.parametrize("text,name,length,existing", [
    ('337 LF-6" SDR-26 PVC', '6" PVC sanitary', 337.0, False),
    ('216 LF-8" SDR-26 PVC', '8" PVC sanitary', 216.0, False),
    ('2" PW', '2" water', None, False),
    ('EXISTING 6" UNKNOWN WATER', '6" water', None, True),
    ('8" PVC ROOF DRAIN', '8" PVC storm', None, False),
    ('6" PVC RD', '6" PVC storm', None, False),
])
def test_real_set_labels(text, name, length, existing):
    p = ct.parse_pipe_label(text)
    assert p["name"] == name and p["length"] == length and \
        p["existing"] == existing


@pytest.mark.parametrize("text", ['3" PVC CONDUIT', '16"PINE',
                                  '2" ELEC CONDUIT'])
def test_not_pipe_labels(text):
    assert ct.parse_pipe_label(text) is None


def test_dashed_line_with_lettering_is_one_run():
    from app import tradetakeoff as tt
    segs = [(0, 0, 10, 0), (12, 0, 22, 0), (24, 0, 40, 0),
            (90, 0, 120, 0),                 # after "PRIVATE SS >>"
            (0, 5, 10, 25)]                  # something else
    text = [fitz.Rect(42, -4, 88, 4)]
    plain = ct.bridge_dashes(segs, 4)
    assert len(plain) == 2
    both = ct.bridge_dashes(segs, 4, texts=text, text_gap=60, probe=3)
    runs = tt.runs(segs + both)
    assert max(tt.poly_len(r) for r in runs) == pytest.approx(120)
    # no lettering in the gap: not bridged
    far = ct.bridge_dashes(segs, 4, texts=[fitz.Rect(42, 10, 88, 20)],
                           text_gap=60, probe=3)
    assert len(far) == 2


def test_label_with_leader_points_at_its_pipe():
    d = fitz.open()
    pg = d.new_page(width=800, height=600)
    sh = pg.new_shape()
    sh.draw_line((50, 300), (750, 300))             # the pipe
    sh.finish(width=1.0, color=(0, 0, 0))
    sh.draw_line((209, 104), (260, 104))            # leader: tick, then down
    sh.draw_line((260, 104), (300, 298))
    sh.finish(width=0.25, color=(0, 0, 0), closePath=False)
    sh.draw_line((50, 150), (750, 150))             # a curb nearer the text
    sh.finish(width=1.0, color=(0.5, 0.5, 0.5))
    sh.commit()
    pg.insert_text((100, 108), '337 LF-6" SDR-26 PVC', fontsize=10)
    labs = ct.pipe_labels(pg)
    assert labs
    ct._leaders(pg, labs)
    assert labs[0].get("leader") and abs(labs[0]["center"][1] - 298) < 2


def test_walk_along_a_shared_pen_stops_at_the_printed_length():
    """A storm label "49 LF" on a pen also used for curbs: the runs that
    carry on from it are taken only up to about its printed length."""
    lab = {"name": '18" RCP storm', "length": 49.0}
    per_ft = 3.6
    chain = [[(0.0, 0.0), (14 * per_ft, 0.0)]]
    x = 14 * per_ft
    for _ in range(20):                       # 20 x 20 ft carrying on
        chain.append([(x, 0.0), (x + 20 * per_ft, 0.0)])
        x += 20 * per_ft
    items = [(chain[0], lab)] + [(r, None) for r in chain[1:]]
    free = ct._connected(items, 2.0 * per_ft)
    assert len(free) == 21
    capped = ct._connected(items, 2.0 * per_ft,
                           budget=lambda l_: 2.0 * l_["length"] * per_ft)
    total = sum(r[-1][0] - r[0][0] for r, _ in capped) / per_ft
    assert 49 <= total <= 2.0 * 49


def test_label_without_material_joins_its_twin(monkeypatch):
    """"TIE 8" ROOF DRAIN" and "8" PVC ROOF DRAIN" come out as one pipe."""
    def fake(page, ppu, unit, structs=None, **_k):
        mk = lambda name, mat, ln: {
            "name": name, "size": 8.0, "material": mat, "system": "storm",
            "existing": False, "length": ln, "label_length": 0.0,
            "runs": [{"pts": [(0, 0), (1, 0)], "length": ln,
                      "label": name, "depth": None}],
            "bands": {"unknown": ln}, "style_name": "x", "slope": None,
            "labels": 0, "suggested": True}
        return [mk('8" storm', "", 132.0), mk('8" PVC storm', "PVC", 57.0)]
    monkeypatch.setattr(ct, "pipe_systems", fake)
    monkeypatch.setattr(ct, "structures", lambda page: [])
    d = fitz.open()
    d.new_page()
    res = ct.takeoff(d, [0], {0: (3.6, "ft")})
    assert [(p["name"], round(p["length"])) for p in res["pipes"]] == \
        [('8" PVC storm', 189)]


# ------------------------------------------- treatment-plant piping plans
@pytest.mark.parametrize("text,name,system", [
    ('8" TWAS, CL: 15.00', '8" TWAS', "process"),
    ('6" PDG,', '6" PDG', "plant drain"),
    ('12" NPW, CL: 14.50', '12" NPW', "water"),
    ('CONNECTION OF 24" ML PIPE', '24" ML', "process"),
    ('36" PTE', '36" PTE', "process"),
])
def test_plant_service_codes(text, name, system):
    p = ct.parse_pipe_label(text)
    assert p["name"] == name and p["system"] == system


def test_plant_fittings_are_not_pipe():
    for t in ('6" 90° BEND', '30" x 24" REDUCER', '1" HYPO'):
        assert ct.parse_pipe_label(t) is None


def _grp(name, size, mat, system, guessed, length):
    return {"name": name, "size": size, "material": mat, "system": system,
            "guessed": guessed, "existing": False, "runs": [{"length": 1}],
            "length": length, "label_length": 0.0, "pages": [0],
            "bands": {None: length}}


def test_plant_set_bare_pipe_is_not_called_water_or_sewer():
    pipes = {'24" DIP water': _grp('24" DIP water', 24, "DIP", "water",
                                   True, 100.0),
             '18" PVC sanitary': _grp('18" PVC sanitary', 18, "PVC",
                                      "sanitary", True, 50.0),
             '8" PDG': _grp('8" PDG', 8, "", "plant drain", False, 30.0),
             '6" DIP water': _grp('6" DIP water', 6, "DIP", "water",
                                  False, 20.0)}       # said WATER
    ct._plant_names(pipes)
    assert set(pipes) == {'24" DIP', '18" PVC', '8" PDG', '6" DIP water'}
    assert pipes['24" DIP']["length"] == 100.0


def test_site_plan_names_unchanged():
    pipes = {'8" PVC sanitary': _grp('8" PVC sanitary', 8, "PVC",
                                     "sanitary", True, 10.0)}
    ct._plant_names(pipes)
    assert set(pipes) == {'8" PVC sanitary'}


def _g(name, existing, runs):
    return {"name": name + (" (existing)" if existing else ""), "size": 24,
            "material": "DIP", "system": "", "existing": existing,
            "length": sum(r["length"] for r in runs), "label_length": 0.0,
            "labels": set(), "runs": runs}


def test_grey_pipe_is_existing_when_new_pipe_is_black():
    out = {('24" DIP', False): _g('24" DIP', False, [
        {"length": 100.0, "screened": True},
        {"length": 40.0, "screened": False}]),
        ('36" ML', False): _g('36" ML', False, [
            {"length": 300.0, "screened": False}])}
    ct._screened_is_existing(out)
    assert out[('24" DIP', False)]["length"] == 40.0
    ex = out[('24" DIP', True)]
    assert ex["existing"] and ex["length"] == 100.0
    assert ex["name"] == '24" DIP (existing)'


def test_all_grey_sheet_is_left_alone():
    out = {('8" PVC', False): _g('8" PVC', False, [
        {"length": 50.0, "screened": True}])}
    ct._screened_is_existing(out)
    assert list(out) == [('8" PVC', False)]


def test_screened_colours():
    assert ct._screened(((0.6, 0.6, 0.6), 1.5, None))
    assert not ct._screened(((0.0, 0.0, 0.0), 1.5, None))
    assert not ct._screened(((0.4, 0.4, 0.4), 1.5, None))      # dark grey
    assert not ct._screened(((1.0, 0.0, 0.0), 1.5, None))      # red
    assert not ct._screened((None, 1.0, None))


class _Page:
    number = 14

    def __init__(self, texts):
        self.texts = texts


def test_unnumbered_plant_structures(monkeypatch):
    texts = ["5' Ø MANHOLE RIM: 23.50", "EX MANHOLE No. 9 FUTURE RIM: 23.25",
             '12" PLUG VALVE CL 6.42', "FIRE HYDRANT, SEE DETAIL W14/CD03",
             '30" PV w/ VALVE BOX', "SPLITTER BOX No. 2", "CLEANOUT"]
    rects = [fitz.Rect(10, 10 + 20 * i, 200, 20 + 20 * i)
             for i in range(len(texts))]
    monkeypatch.setattr(ct, "lines", lambda page: list(zip(texts, rects)))
    tags = ct.structure_tags(_Page(texts))
    got = sorted((t["kind"], t["id"], t["existing"]) for t in tags)
    assert got == [("cleanout", "CO p15-4", False),
                   ("hydrant", "FH p15-3", False),
                   ("manhole", "MH-9", True),
                   ("manhole 60", "MH p15-1", False),
                   ("valve", '12" Plug Valve p15-2', False)]
    assert sum(1 for t in tags if t.get("unnumbered")) == 4


def test_grey_pipe_with_a_length_callout_stays_new():
    """'314 LF OF 8" PDG @ -0.40% SLOPE' drawn in a light-grey hairline is
    new pipe: existing pipe doesn't get lengths and slopes."""
    out = {('8" PDG', False): _g('8" PDG', False, [
        {"length": 308.0, "screened": True, "designed": True},
        {"length": 89.0, "screened": False}])}
    ct._screened_is_existing(out)
    assert list(out) == [('8" PDG', False)]
    assert out[('8" PDG', False)]["length"] == 397.0


def test_depth_from_centerline_callouts(monkeypatch):
    texts = ['8" TWAS, CL: 15.00', "CL: 17.50", "SLOPE 0.40%"]
    rects = [fitz.Rect(100, 95, 160, 105), fitz.Rect(300, 95, 340, 105),
             fitz.Rect(500, 95, 540, 105)]
    monkeypatch.setattr(ct, "lines", lambda page: list(zip(texts, rects)))
    cls = ct.centerlines(None)
    assert [el for _c, el in cls] == [15.0, 17.5]
    run = [(90, 100), (360, 100)]
    # grade 23.25, CL avg 16.25, 8" pipe: invert 16.25 - 0.33 = 15.92
    assert ct._cl_depth(run, cls, 23.25, 8, 20) == pytest.approx(7.33)
    assert ct._cl_depth([(900, 900), (950, 900)], cls, 23.25, 8, 20) is None


def test_finished_grade_is_the_middle_rim():
    s = [{"rim": 23.5}, {"rim": 23.25}, {"rim": None}, {"rim": 30.0}]
    assert ct.finished_grade(s) == 23.5
    assert ct.finished_grade([{"rim": None}]) is None


def test_five_foot_manholes_get_the_60_inch_assembly(monkeypatch):
    texts = ["5' Ø MANHOLE RIM: 23.50", "4' Ø MANHOLE", "EX MH 5 (5' Ø)"]
    rects = [fitz.Rect(10, 10 + 30 * i, 200, 20 + 30 * i)
             for i in range(len(texts))]
    monkeypatch.setattr(ct, "lines", lambda page: list(zip(texts, rects)))
    kinds = [(t["kind"], t["existing"]) for t in ct.structure_tags(_Page(
        texts))]
    assert kinds == [("manhole 60", False), ("manhole", False),
                     ("manhole 60", True)]
    lib = assemblies.library()
    name = 'Sanitary manhole, 60" precast, by depth'
    assert name in lib
    res = {"pipes": [], "structures": [
        {"id": "MH p15-1", "kind": "manhole 60", "existing": False,
         "depth": 7.0}]}
    got = ct.assemblies_for(res, lib)
    a = next(v for k, v in got.items() if k.startswith(name))
    assert a["props"]["H"] == 7.0
    parts = {p["name"]: p for p in assemblies.compute(a, {"count": 1})}
    assert any("10 x 10" in n for n in parts)
