"""Build Schedule From Plans - the project type is read from the plans
and specs (with the evidence), the activities come from that type's
template, and the equipment named in the set is in the activity names.
The owner's report: a generator project got a building schedule with no
generator in it."""
import datetime as dt
import re

import pytest

from app.pm import autoschedule as au
from app.pm import schedule_types as st

# the building trades: the classic template's names, and the words
BUILDING_TRADES = {"Drywall hang, tape & finish", "Structure (framing / "
                   "masonry / steel)", "Roofing", "Flooring", "Slab on grade",
                   "Ceilings", "Painting", "Insulation", "Roof structure & "
                   "deck", "Exterior walls & finishes",
                   "Interior framing & partitions"}
TRADE_WORDS = ("drywall", "framing", "flooring")


def _rows(*pairs):
    return [{"number": n, "title": t} for n, t in pairs]


GEN_SHEETS = _rows(("E-001", "ELECTRICAL SITE PLAN"),
                   ("E-101", "GENERATOR PLAN"),
                   ("E-501", "ONE-LINE DIAGRAM"))
GEN_SECTIONS = [{"number": "26 32 13", "title": "ENGINE GENERATORS"},
                {"number": "26 36 00", "title": "TRANSFER SWITCHES"}]
GEN_TEXT = ["GENERATOR SCHEDULE",
            "GEN-1 500 KW DIESEL GENERATOR WITH SUB-BASE FUEL TANK",
            "ATS-1 800A 480V AUTOMATIC TRANSFER SWITCH"]


def _names(acts):
    return [a["name"] for a in acts]


def _has(names, *words):
    low = [n.lower() for n in names]
    return all(any(w.lower() in n for n in low) for w in words)


def _no_building_trades(names):
    """The building-trade activities in a list of names ([] = none)."""
    return [n for n in names if n in BUILDING_TRADES or
            any(w in n.lower() for w in TRADE_WORDS)]


# ------------------------------------------------------------- pure logic
def test_generator_job_is_scheduled_as_a_generator_job():
    sc = au.scope(GEN_SHEETS, sections=GEN_SECTIONS, texts=GEN_TEXT)
    assert sc["type"] == "standby_generator"
    ev = " ".join(sc["evidence"])
    assert "26 32 13" in ev and "E-101" in ev            # says why
    names = _names(au.plan(sc))
    assert _has(names, "procure gen-1", "generator pad", "set gen-1",
                "ats-1", "load bank", "startup", "cutover",
                "transfer test", "grounding", "training", "o&m")
    assert not _no_building_trades(names), _no_building_trades(names)
    assert "Substantial Completion" in names and "Final Completion" in names
    proc = next(n for n in names if n.startswith("Procure GEN-1"))
    assert "500 kW diesel generator" in proc and "assumed" in proc
    assert any("assumed" in n and "GEN-1" in n for n in sc["notes"])
    assert any("starting values" in n for n in sc["notes"])


def test_generator_lead_time_is_a_parameter_and_drives_the_schedule():
    sc = au.scope(GEN_SHEETS, sections=GEN_SECTIONS, texts=GEN_TEXT,
                  lead_weeks={"generator": 40})
    acts = {a["key"]: a for a in au.plan(sc)}
    assert acts["proc_gen"]["duration"] == 200           # 40 weeks
    assert "assumed" not in acts["proc_gen"]["name"]
    assert ("proc_gen", "FS", 0) in acts["set_gen"]["preds"]
    assert ("pad_cure", "FS", 0) in acts["set_gen"]["preds"]
    assert st.parse_lead_weeks("generator 36, ATS: 22 wk") == \
        {"generator": 36.0, "ats": 22.0}
    assert st.parse_lead_weeks("32") == {"*": 32.0}


def test_generator_detected_from_spec_sections_alone():
    sc = au.scope(sections=GEN_SECTIONS)
    assert sc["type"] == "standby_generator"
    names = _names(au.plan(sc))
    assert _has(names, "procure generator", "set generator", "load bank")
    assert not _no_building_trades(names)


def test_architectural_set_is_still_a_new_building():
    sc = au.scope(_rows(("A-101", "FLOOR PLAN"),
                        ("A-201", "EXTERIOR ELEVATIONS"),
                        ("M-101", "HVAC PLAN"), ("P-101", "PLUMBING PLAN"),
                        ("E-101", "POWER PLAN")), area_sf=3000)
    assert sc["type"] == "new_building"
    names = _names(au.plan(sc))
    assert _has(names, "drywall", "roofing", "structure")
    # same activities as the classic building template
    old = [t[0] for t in au.TEMPLATE]
    assert [a["key"] for a in au.plan(sc)] == \
        [k for k in old if k in {a["key"] for a in au.plan(sc)}]


def test_building_with_a_generator_stays_a_building_with_its_procurement():
    sc = au.scope(_rows(("A-101", "FLOOR PLAN"),
                        ("A-201", "EXTERIOR ELEVATIONS"),
                        ("A-301", "WALL SECTIONS"),
                        ("E-601", "GENERATOR DETAILS")),
                  sections=[{"number": "26 32 13",
                             "title": "Engine Generators"},
                            {"number": "09 29 00", "title": "Gypsum Board"}],
                  texts=["GEN-1 150 KW NATURAL GAS GENERATOR"],
                  area_sf=8000)
    assert sc["type"] == "new_building"
    acts = {a["key"]: a for a in au.plan(sc)}
    assert "drywall" in acts and "proc_x_generator" in acts
    assert "GEN-1" in acts["proc_x_generator"]["name"]
    assert ("proc_x_generator", "FS", 0) in acts["mep_trim"]["preds"]


def test_nothing_recognized_never_assumes_a_building():
    for sc in (au.scope(), au.scope(_rows(("X-1", "SHEET")))):
        assert sc["type"] == "unknown"
        assert any("pick the project type" in n for n in sc["notes"])
        names = _names(au.plan(sc))
        assert not _no_building_trades(names)
        assert "Substantial Completion" in names
    # the person picks the type: that template is used
    sc = au.retype(au.scope(), "standby_generator")
    assert sc["type"] == "standby_generator"
    assert _has(_names(au.plan(sc)), "set generator", "load bank")


def test_picking_new_building_by_hand_keeps_the_old_assumption():
    sc = au.retype(au.scope(), "new_building")
    assert {"architectural", "structural"} <= sc["flags"]
    assert _has(_names(au.plan(sc)), "drywall")


@pytest.mark.parametrize("kind, sheets, sections, texts, want, must", [
    ("hvac", _rows(("M-101", "MECHANICAL DEMOLITION PLAN"),
                   ("M-201", "MECHANICAL ROOF PLAN")), [],
     ["RTU REPLACEMENT", "RTU-1 15 TON ROOFTOP UNIT", "RTU-2 15 TON "
      "ROOFTOP UNIT", "CURB ADAPTER"], "hvac_replacement",
     ("procure rtu-1", "set rtu-1", "crane", "test & balance",
      "curb adapter")),
    ("reroof", _rows(("A-101", "EXISTING ROOF PLAN"),
                     ("A-102", "NEW ROOF PLAN")),
     [{"number": "07 01 50", "title": "Preparation for Reroofing"},
      {"number": "07 54 23", "title": "TPO Roofing"}], [], "reroof",
     ("tear-off", "membrane", "flashings")),
    ("site", _rows(("C-101", "EROSION CONTROL PLAN"),
                   ("C-201", "GRADING PLAN"), ("C-301", "UTILITY PLAN"),
                   ("C-401", "PAVING PLAN")),
     [{"number": "32 12 16", "title": "Asphalt Paving"}], [],
     "sitework_only", ("grading", "paving", "underground utilities")),
    ("lift", _rows(("C-101", "LIFT STATION SITE PLAN"),
                   ("M-101", "WET WELL PLAN AND SECTIONS")),
     [{"number": "33 32 13", "title": "Packaged Wastewater Pumping "
                                      "Stations"}],
     ["P-1 & P-2 SUBMERSIBLE PUMPS 25 HP", "FORCE MAIN"],
     "pump_or_lift_station", ("procure p-1", "wet well",
                              "drawdown", "force main")),
    ("wwtp", _rows(("M-101", "AERATION BASIN MECHANICAL")),
     [{"number": "46 51 00", "title": "Air Diffusers"}],
     ["WASTEWATER TREATMENT PLANT IMPROVEMENTS",
      "BL-1 75 HP AERATION BLOWER"], "treatment_plant",
     ("procure bl-1", "process startup", "plant operations")),
    ("service", _rows(("E-101", "ELECTRICAL SERVICE UPGRADE"),
                      ("E-501", "ONE-LINE DIAGRAM")),
     [{"number": "26 23 00", "title": "Low-Voltage Switchgear"}],
     ["SWGR-1 3000A 480V SWITCHGEAR", "COORDINATE WITH UTILITY"],
     "electrical_service", ("procure swgr-1", "set swgr-1", "utility",
                            "energize")),
    ("reno", _rows(("AD-101", "DEMOLITION PLAN"), ("A-101", "FLOOR PLAN")),
     [], ["TENANT IMPROVEMENT - SUITE 200"], "renovation",
     ("selective demolition", "drywall")),
])
def test_other_project_types(kind, sheets, sections, texts, want, must):
    sc = au.scope(sheets, sections=sections, texts=texts)
    assert sc["type"] == want, (kind, sc["detected"]["ranked"])
    assert sc["evidence"]
    names = _names(au.plan(sc))
    assert _has(names, *must), (kind, names)
    if want not in st.BUILDING_TYPES:
        assert not _no_building_trades(names), (kind, names)


def test_detect_scores_and_reasons():
    d = st.detect(GEN_SHEETS, GEN_SECTIONS)
    assert d["type"] == "standby_generator" and d["recognized"]
    assert d["ranked"][0][0] == "standby_generator"
    assert any("ENGINE GENERATORS" in w for w in d["why"]["standby_generator"])
    assert st.detect()["type"] == st.UNKNOWN


def test_equipment_tags_and_descriptions():
    eq = st.equipment(GEN_TEXT + ["E-101", "RTU-3 PACKAGED ROOFTOP UNIT 10 "
                                           "TON", "LIFT STATION PUMPS"],
                      _rows(("E-101", "GENERATOR PLAN")))
    by = {e["tag"]: e for e in eq if e["tag"]}
    assert by["GEN-1"]["kind"] == "generator"
    assert by["GEN-1"]["desc"] == "500 kW diesel generator"
    assert by["GEN-1"]["kw"] == 500 and by["GEN-1"]["long_lead"]
    assert by["ATS-1"]["kind"] == "ats"
    assert by["RTU-3"]["kind"] == "rtu" and "10 ton" in by["RTU-3"]["desc"]
    assert "E-101" not in by                       # a sheet, not equipment
    # "P-101" is a plumbing sheet, not pump P-101
    assert not st.equipment(["P-101 PLUMBING PLAN"])


def test_toc_lines_give_sections():
    secs = st.toc_sections(["TABLE OF CONTENTS",
                            "26 32 13  ENGINE GENERATORS",
                            "263600 - Transfer Switches ........ 4",
                            "Page 3 of 10"])
    assert [s["number"] for s in secs] == ["26 32 13", "26 36 00"]
    assert secs[0]["title"] == "ENGINE GENERATORS"


def test_generator_schedule_builds_and_fits(tmp_path):
    from app.pm.store import ProjectStore
    from app.pm import schedule
    s = ProjectStore(str(tmp_path / "p"))
    sc = au.scope(GEN_SHEETS, sections=GEN_SECTIONS, texts=GEN_TEXT)
    ct = au.contract_time([(4, "Substantial Completion shall be achieved "
                               "within 300 calendar days after the date of "
                               "the Notice to Proceed.")])
    res = au.build(s, sc, dt.date(2026, 11, 2), ct)
    cpm = schedule.compute(s, au.ntp_or_today(s))
    assert not cpm["problems"]
    names = [a["name"] for a in s.list("activity")]
    assert any("GEN-1" in n for n in names)
    assert res["fit"]["predicted_substantial"]
    text = " ".join(au.summary_text(ct, sc, res))
    assert "Standby generator" in text and "GEN-1" in text


# ------------------------------------------------------------- real PDFs
def _fitz():
    try:
        import fitz
    except ImportError:
        pytest.skip("PyMuPDF not installed")
    if not callable(getattr(fitz, "open", None)):
        pytest.skip("PyMuPDF is a stub here")
    return fitz


def _sheet_set(fitz, sheets, extra=()):
    d = fitz.open()
    for k, (num, title) in enumerate(sheets):
        p = d.new_page(width=2592, height=1728)
        p.insert_text((2356, 1484), "SHEET TITLE:", fontsize=10)
        p.insert_text((2360, 1512), title, fontsize=22)
        p.insert_text((2356, 1619), "SCALE", fontsize=10)
        p.insert_text((2380, 1680), num, fontsize=44)
        if k == 0:
            for i, ln in enumerate(extra):
                p.insert_text((200, 300 + 30 * i), ln, fontsize=14)
    return d


def _spec(fitz, lines):
    d = fitz.open()
    p = d.new_page()
    for i, ln in enumerate(lines):
        p.insert_text((72, 72 + 18 * i), ln, fontsize=10)
    return d


def test_generator_pdfs_read_as_generator_job():
    fitz = _fitz()
    plans = _sheet_set(fitz, [("E-001", "ELECTRICAL SITE PLAN"),
                              ("E-101", "GENERATOR PLAN"),
                              ("E-501", "ONE-LINE DIAGRAM")],
                       ["GENERATOR SCHEDULE",
                        "GEN-1 500 KW DIESEL GENERATOR",
                        "ATS-1 800A AUTOMATIC TRANSFER SWITCH"])
    spec = _spec(fitz, ["TABLE OF CONTENTS",
                        "26 32 13  ENGINE GENERATORS",
                        "26 36 00  TRANSFER SWITCHES",
                        "The Contractor shall fully complete all Work "
                        "within 180 calendar days."])
    info = au.read_job(plans, spec)
    assert info["type"] == "standby_generator", info["detected"]["ranked"]
    assert info["evidence"] and info["ct"]["final"]["days"] == 180
    names = _names(au.plan(info["scope"]))
    assert _has(names, "procure gen-1", "generator pad", "set gen-1",
                "ats-1", "load bank", "startup")
    assert not _no_building_trades(names)


def test_architectural_pdfs_still_a_building():
    fitz = _fitz()
    plans = _sheet_set(fitz, [("A-101", "FLOOR PLAN"),
                              ("A-201", "EXTERIOR ELEVATIONS"),
                              ("A-301", "WALL SECTIONS")])
    info = au.read_job(plans, None)
    assert info["type"] == "new_building"
    assert _has(_names(au.plan(info["scope"])), "drywall")


def test_unrecognized_pdfs_ask_for_the_type():
    fitz = _fitz()
    d = fitz.open()
    d.new_page().insert_text((72, 72), "Lorem ipsum", fontsize=10)
    info = au.read_job(d, None)
    assert info["type"] == "unknown"
    assert any("pick the project type" in n for n in info["scope"]["notes"])


# ---- a repairs-and-improvements set: the cover lists the work, and the
# generator is someone else's (the Oct 21 fire station set, made-up text)
REPAIR_COVER = [
    "REQUIRED REPAIRS AND IMPROVEMENTS TO STATION 9",
    "DESCRIPTION OF WORK",
    "1. REPAIR DAMAGED STUCCO AT THE FRONT ENTRANCE STEPS, INCLUDING SURFACE",
    "PREPARATION, PATCHING AND FINISH COATING.",
    "2. REMOVE RUST FROM ALL STAIR RAILINGS AND APPLY PRIMER AND FINISH",
    "PAINT COATINGS.",
    "Project No. 1234",
    "3. REPAIR NAIL POPS THROUGHOUT BUILDINGS A, B AND C, INCLUDING PATCHING.",
    "4. REMOVE EXISTING CAULKING FROM ALL WINDOWS AND INSTALL NEW SEALANT.",
    "5. PREPARE AND PAINT ALL WINDOW FRAMES FOLLOWING COMPLETION OF CAULKING",
    "REPLACEMENT.",
    "6. FURNISH AND INSTALL A WATER SOFTENER SYSTEM, INCLUDING STARTUP.",
    "7. POWER WASH THE ENTIRE EXTERIOR OF THE BUILDING.",
    "APPLICABLE CODES",
]
GEN_NOTE = ["TYP. SLAB @ GENERATOR ENCLOSURE",
            "GENERATOR PACKAGE [GENERATOR, FUEL TANK,",
            "ATS, WIRING, PATHWAYS, PAD] NOT INCLUDED IN",
            "THIS CONTRACT.",
            "PRICE WOOD ENCLOSURE SCOPE ONLY."]
REPAIR_SHEETS = [{"number": "A0.0", "title": "COVER PAGE"},
                 {"number": "AS1", "title": "SITE PLAN"},
                 {"number": "A1.1", "title": "PARTIAL FLOOR PLAN"},
                 {"number": "A2.0", "title": "EXTERIOR ELEVATIONS"},
                 {"number": "A3.0", "title": "ENLARGED ENCLOSURE"},
                 {"number": "A325", "title": "1 SHAPES, ANGLES, ASTM A 53 "
                  "GRADE B FY = 36 KSI; FASTENERS SHALL BE HIGH STRENGTH"}]


def test_scope_list_read_from_the_cover():
    items = st.scope_items(REPAIR_COVER)
    assert len(items) == 7
    assert items[0].endswith("FINISH COATING.")      # wrapped line joined
    assert st.item_name(items[0]) == \
        "Repair damaged stucco at the front entrance steps"
    assert st.item_name(items[2]) == \
        "Repair nail pops throughout buildings A, B and C"
    assert st.scope_items(["DESCRIPTION OF WORK", "2. NOT ONE"]) == []


def test_not_in_contract_note_and_scope_only():
    ex = st.exclusions(GEN_NOTE)
    assert ex[0]["text"].startswith("GENERATOR PACKAGE")
    assert {"generator", "ats", "fuel_tank"} <= set(ex[0]["kinds"])
    assert ex[1] == {"text": "PRICE WOOD ENCLOSURE SCOPE ONLY.",
                     "kinds": [], "only": True}
    assert st.exclusions(["N.I.C."]) == []          # a hatch label alone


def test_repair_job_is_a_renovation_built_from_its_list():
    sc = au.scope(REPAIR_SHEETS, texts=REPAIR_COVER + GEN_NOTE)
    assert sc["type"] == "renovation"
    # the A325 bolt line is no A sheet
    assert not any("A325" in e for e in sc["evidence"])
    gen = [e for e in sc["equipment"] if e["kind"] == "generator"]
    assert all(e.get("by_others") for e in gen)
    acts = au.plan(sc)
    names = [a["name"] for a in acts]
    by_key = {a["key"]: a for a in acts}
    assert "1. Repair damaged stucco at the front entrance steps" in names
    assert not any("Drywall hang" in n or "Flooring" == n for n in names)
    assert not any(re.search(r"(?i)procure.*generator|set .*generator", n)
                   for n in names)                 # not this contract
    assert any(n.startswith("Coordinate work by others: Generator package")
               for n in names)
    assert any(n.startswith("Wood enclosure (for the generator by others)")
               for n in names)
    preds = lambda k: {p[0] for p in by_key[k]["preds"]}     # noqa: E731
    assert "item4" in preds("item5")       # paint frames after caulking
    assert "item7" in preds("item4")       # power wash before exterior work
    assert "submittals" in preds("item6")  # the softener has to be bought
    assert "item2" in preds("item5")       # one paint crew, in list order
    text = "\n".join(au.summary_text(None, sc, {}))
    assert "Not in this contract (drawings): GENERATOR PACKAGE" in text
    assert "7 activities from the drawings' Description of Work" in text
    assert "assumed 5,000 SF" not in text


def test_generator_job_without_exclusion_still_a_generator_job():
    sc = au.scope([{"number": "E1.0", "title": "GENERATOR PLAN"},
                   {"number": "E2.0", "title": "ONE-LINE DIAGRAM"}],
                  texts=["GEN-1 500 KW DIESEL GENERATOR", "ATS-1 800A"])
    assert sc["type"] == "standby_generator"


def test_scanned_sheets_are_named_in_the_notes():
    fitz = _fitz()
    d = fitz.open()
    p = d.new_page()
    p.insert_text((72, 72), "SITE PLAN - STATION RENOVATION", fontsize=10)
    d.new_page()                                # a scanned sheet: no text
    info = au.read_job(d, None)
    assert info["scope"]["scanned"] == [2]
    assert any("1 page(s) are scanned images" in n and "p. 2)" in n
               for n in info["scope"]["notes"])
    again = au.retype(info["scope"], "renovation")
    assert any("scanned images" in n for n in again["notes"])


# ---- 0.12.32 review: detection, listed scope, exclusions (made-up sets)
HOUSE = _rows(("A-1", "FLOOR PLAN"), ("A-2", "EXTERIOR ELEVATIONS"),
              ("A-3", "BUILDING SECTIONS"), ("A-4", "ELECTRICAL PLAN"),
              ("S-1", "FOUNDATION PLAN"), ("S-2", "ROOF FRAMING PLAN"),
              ("M-1", "MECHANICAL PLAN"), ("P-1", "PLUMBING PLAN"))
BOILERPLATE = ["GENERAL NOTES",
               "1. VERIFY ALL EXISTING CONDITIONS (EXISTING WORK) BEFORE "
               "DEMOLITION.",
               "2. ALL WORK SHALL COMPLY WITH THE IRC."]


def test_new_house_with_existing_conditions_note_is_a_new_building():
    sc = au.scope(HOUSE, texts=BOILERPLATE, area_sf=2400)
    assert sc["type"] == "new_building", sc["detected"]["ranked"]
    assert not any("EXISTING" in w for w in sc["detected"]["why"]
                   ["renovation"])                # boilerplate: no points
    assert any("S-1" in w for w in sc["evidence"])  # the foundation plan
    keys = {a["key"] for a in au.plan(sc)}
    assert {"footings", "slab", "structure", "plumb_rough", "hvac_rough",
            "elec_rough"} <= keys
    # floor plans alone (no demolition, no renovation words): new building
    sc = au.scope(_rows(("A-1", "FLOOR PLAN"),
                        ("A-2", "EXTERIOR ELEVATIONS")), texts=BOILERPLATE)
    assert sc["type"] == "new_building", sc["detected"]["ranked"]
    # "NEW ... RESIDENCE" on the title block counts for a new building
    d = st.detect(texts=["NEW SINGLE FAMILY RESIDENCE FOR J. DOE"])
    assert d["scores"]["new_building"] > 0 and d["scores"]["renovation"] == 0
    assert st.detect(texts=["NEW WORK AT EXISTING BUILDING"])[
        "scores"]["new_building"] == 0


def test_existing_conditions_note_counts_with_a_demolition_sheet():
    sc = au.scope(_rows(("AD-1", "DEMOLITION PLAN"), ("A-1", "FLOOR PLAN"),
                        ("A-2", "EXTERIOR ELEVATIONS")), texts=BOILERPLATE)
    assert sc["type"] == "renovation"
    assert any("EXISTING CONDITIONS" in w for w in sc["evidence"])


def test_a_close_call_asks_for_the_type():
    sc = au.scope(texts=["LIFT STATION", "WASTEWATER TREATMENT PLANT"])
    det = sc["detected"]
    assert det["ambiguous"] and det["type"] == st.UNKNOWN
    assert set(det["candidates"]) == {"pump_or_lift_station",
                                      "treatment_plant"}
    assert sc["type"] == "unknown"                 # the dialog won't build
    note = next(n for n in sc["notes"] if "unclear" in n)
    assert "Pump / lift station" in note and "treatment" in note
    assert "pick the project type" in note.lower()
    assert any(e.startswith("Pump / lift station:") for e in sc["evidence"])
    assert not _no_building_trades(_names(au.plan(sc)))
    # under 10% apart is still a close call; a clear lead decides
    d = st.detect(texts=["LIFT STATION", "WET WELL", "WATER TREATMENT "
                         "PLANT"])
    assert d["type"] == "pump_or_lift_station" and not d["ambiguous"]
    sc = au.retype(sc, "treatment_plant")          # the person picks
    assert sc["type"] == "treatment_plant"


def test_plant_words_beat_its_civil_sheets():
    sc = au.scope(_rows(("C-101", "OVERALL SITE PLAN"),
                        ("C-102", "GRADING AND DRAINAGE PLAN"),
                        ("C-201", "YARD PIPING PLAN AND PROFILE"),
                        ("C-202", "STORM SEWER PLAN AND PROFILE"),
                        ("C-203", "WATER MAIN PLAN AND PROFILE"),
                        ("M-101", "DIGESTER NO. 1 PLAN"),
                        ("M-102", "DIGESTER SECTIONS"),
                        ("E-101", "MCC-1 ELEVATION"),
                        ("E-102", "PLC PANEL LAYOUT")))
    assert sc["type"] == "treatment_plant", sc["detected"]["ranked"]


def test_ofci_equipment_is_installed_not_procured():
    sc = au.scope(GEN_SHEETS, sections=GEN_SECTIONS, texts=GEN_TEXT + [
        "GENERAL NOTES",
        "3. GEN-1 IS OWNER FURNISHED, CONTRACTOR INSTALLED (OFCI)."])
    assert sc["type"] == "standby_generator"
    ex = [e for e in sc["exclusions"] if e.get("ofci")]
    assert ex and ex[0]["kinds"] == ["generator"]
    gen = next(e for e in sc["equipment"] if e["tag"] == "GEN-1")
    assert gen.get("ofci") and not gen.get("by_others")
    acts = {a["key"]: a for a in au.plan(sc)}
    names = _names(acts.values())
    assert not any(n.startswith("Procure GEN-1") for n in names)
    assert acts["proc_gen"]["name"].startswith("Owner delivers GEN-1")
    assert acts["proc_gen"]["duration"] == 0               # a milestone
    assert ("proc_gen", "FS", 0) in acts["set_gen"]["preds"]  # we set it
    assert acts["proc_ats"]["name"].startswith("Procure ATS-1")
    assert any(n.startswith("Owner-furnished, contractor-installed")
               for n in sc["notes"])
    assert not any("Not in this contract" in n for n in sc["notes"])
    # OFCI items with no equipment kind: delivery milestone + our install
    sc = au.scope(_rows(("A-101", "FLOOR PLAN"),
                        ("A-201", "EXTERIOR ELEVATIONS")),
                  texts=["F. KITCHEN EQUIPMENT IS OFCI."], area_sf=3000)
    acts = {a["key"]: a for a in au.plan(sc)}
    own = next(a for a in acts.values()
               if a["name"].startswith("Owner delivers kitchen equipment"))
    inst = next(a for a in acts.values()
                if a["name"] == "Install owner-furnished kitchen equipment "
                                "(OFCI)")
    assert own["duration"] == 0 and (own["key"], "FS", 0) in inst["preds"]
    assert st.exclusions(["OFCI OWNER FURNISHED CONTRACTOR INSTALLED"]) == []


NOTES_SHEET = ["GENERAL NOTES",
               "A. ALL WORK SHALL COMPLY WITH THE CODES.",
               "B. THE KITCHEN HOOD, WALK-IN COOLER,",
               "ICE MACHINE, SECURITY CAMERAS",
               "AND ACCESS CONTROL SYSTEM",
               "ARE NOT INCLUDED IN THIS",
               "CONTRACT.",
               "C. PATCH AND PAINT ALL WALLS.",
               "ABBREVIATIONS",
               "N.I.C. NOT IN CONTRACT",
               "OFOI OWNER FURNISHED OWNER INSTALLED",
               "FINISH COLORS: SELECTION BY OWNER.",
               "D. ALL PLUMBING FIXTURES AS MANDATED BY THE OWNER.",
               "E. BY OWNER.",
               "SEE SHEET A2.1 - SCOPE ONLY.",
               "G. ROOF TRUSSES DESIGNED BY OTHERS."]


def test_multi_line_lettered_not_included_note():
    ex = st.exclusions(NOTES_SHEET)
    assert [e["text"] for e in ex] == [
        "THE KITCHEN HOOD, WALK-IN COOLER, ICE MACHINE, SECURITY CAMERAS "
        "AND ACCESS CONTROL SYSTEM ARE NOT INCLUDED IN THIS CONTRACT."]
    # legends, "selection by owner", a bare "E. BY OWNER", a SCOPE ONLY
    # with no work in it and delegated design are no exclusions
    assert not any(st.exclusions([ln]) for ln in NOTES_SHEET[8:])


def test_one_coordination_row_per_excluded_kind_and_no_letter_names():
    cover = REPAIR_COVER + GEN_NOTE + [
        "B. GENERATOR BY OWNER.", "C. GENERATOR AND ATS NOT IN CONTRACT.",
        "D. SECURITY SYSTEM BY OTHERS."]
    sc = au.scope(REPAIR_SHEETS, texts=cover)
    assert sc["type"] == "renovation"
    names = _names(au.plan(sc))
    coord = [n for n in names if n.startswith("Coordinate work by others")]
    assert len([n for n in coord if re.search(r"(?i)generator", n)]) == 1
    assert "Coordinate work by others: Security system (not in this " \
        "contract)" in coord
    assert not any(re.fullmatch(r"(?:\d+\. )?[A-Z]\.?", n) or
                   re.search(r": [A-Z]\.? \(not", n) for n in names)


def test_listed_items_clause_first_synonyms_and_wash():
    lines = ["REPAIRS AND IMPROVEMENTS TO BUILDING 4", "SCOPE OF WORK",
             "1. POWER WASH ALL EXTERIOR WALLS.",
             "2. REMOVE FAILED JOINT SEALANT AT ALL EXTERIOR CONTROL "
             "JOINTS AND",
             "INSTALL NEW SEALANT.",
             "3. FOLLOWING COMPLETION OF CAULKING, PAINT ALL EXTERIOR WALLS "
             "WITH",
             "ELASTOMERIC COATING.",
             "4. AFTER THE COATING WORK, REPLACE ALL EXTERIOR WALL PACKS."]
    sc = au.scope(_rows(("A-101", "EXTERIOR ELEVATIONS")), texts=lines)
    assert sc["type"] == "renovation"
    acts = {a["key"]: a for a in au.plan(sc)}
    preds = lambda k: {p[0] for p in acts[k]["preds"]}     # noqa: E731
    assert acts["item3"]["name"] == \
        "3. Paint all exterior walls with elastomeric coating"
    assert st.item_trade(st.split_clause(
        "FOLLOWING COMPLETION OF CAULKING, PAINT ALL WALLS")[0]) == \
        "painting"
    assert "item2" in preds("item3")              # caulk = sealant
    # the wash: before the sealant, so the paint waits on it through the
    # sealant (the direct wash -> paint link is redundant, review T10)
    assert "item1" in preds("item2") and "item1" not in preds("item3")
    assert "item3" in preds("item4")              # coating = paint
    assert acts["item4"]["name"] == "4. Replace all exterior wall packs"


def test_listed_interior_items_follow_the_trade_order():
    lines = ["INTERIOR IMPROVEMENTS - SUITE 210", "DESCRIPTION OF WORK",
             "1. INSTALL NEW CARPET IN OFFICES 211-214.",
             "2. PAINT ALL OFFICE WALLS.",
             "3. HANG AND FINISH GYPSUM BOARD AT THE NEW CONFERENCE ROOM.",
             "4. REMOVE AND REPLACE DAMAGED ACOUSTICAL CEILING TILES.",
             "5. DEMOLISH EXISTING PARTITIONS AT ROOM 215.",
             "6. FRAME NEW PARTITIONS AT THE CONFERENCE ROOM.",
             "7. INSTALL NEW TOILET ACCESSORIES."]
    sc = au.scope(_rows(("A-101", "FLOOR PLAN"),
                        ("FP-101", "FIRE SPRINKLER PLAN")), texts=lines)
    assert sc["type"] == "renovation"
    acts = {a["key"]: a for a in au.plan(sc)}
    preds = lambda k: {p[0] for p in acts[k]["preds"]}     # noqa: E731
    assert "item5" in preds("item6")      # demo -> framing
    assert "item6" in preds("item3")      # framing -> drywall
    assert "item3" in preds("item4")      # drywall -> ceilings
    assert "item4" in preds("item2")      # ceilings -> paint
    assert "item2" in preds("item1")      # paint -> carpet
    assert "item1" in preds("item7")      # flooring -> specialties
    assert "fs_work" in acts              # FP sheets the list doesn't name
    # exterior items keep their own order (no link to interior drywall)
    sc = au.scope(REPAIR_SHEETS, texts=REPAIR_COVER)
    acts = {a["key"]: a for a in au.plan(sc)}
    assert "item3" not in {p[0] for p in acts["item2"]["preds"]}


def test_renovation_fit_out_has_mep_rough_ins_and_trim():
    sc = au.scope(_rows(("AD-101", "DEMOLITION PLAN"),
                        ("A-101", "FLOOR PLAN"), ("M-101", "HVAC PLAN"),
                        ("P-101", "PLUMBING PLAN"),
                        ("E-101", "LIGHTING PLAN"),
                        ("FP-101", "FIRE SPRINKLER PLAN")), area_sf=4000)
    assert sc["type"] == "renovation"
    keys = {a["key"] for a in au.plan(sc)}
    assert {"plumb_rough", "hvac_rough", "elec_rough", "fs_rough",
            "mep_trim", "hvac_trim", "fs_trim"} <= keys
    # no M / FP sheets: no HVAC or sprinkler rows
    sc = au.scope(_rows(("AD-101", "DEMOLITION PLAN"),
                        ("A-101", "FLOOR PLAN")), area_sf=4000)
    keys = {a["key"] for a in au.plan(sc)}
    assert not keys & {"hvac_rough", "hvac_trim", "fs_rough", "fs_trim"}


def test_prefilled_default_lead_times_stay_assumed():
    sc = au.scope(GEN_SHEETS, sections=GEN_SECTIONS, texts=GEN_TEXT)
    shown = st.format_lead_weeks(sc)          # what the dialog pre-fills
    assert shown == "generator 30, ats 20"
    sc = au.retype(dict(sc, lead_weeks=st.parse_lead_weeks(shown)),
                   "standby_generator", picked=False)
    acts = {a["key"]: a for a in au.plan(sc)}
    assert "assumed" in acts["proc_gen"]["name"]
    assert "assumed" in acts["proc_ats"]["name"]
    note = next(n for n in sc["notes"] if n.startswith("Lead times"))
    assert "GEN-1" in note and "ATS-1" in note
    sc = au.retype(dict(sc, lead_weeks={"generator": 36}),
                   "standby_generator", picked=False)
    acts = {a["key"]: a for a in au.plan(sc)}
    assert "assumed" not in acts["proc_gen"]["name"]
    assert "assumed" in acts["proc_ats"]["name"]


# ------------------------------------------- 0.12.35 review items 1, 12, 13
def _genset_sheets(brief):
    """A made-up Generate Set set read as Build From Plans reads it: its
    sheet list, its general and project notes, its room areas - no PDF."""
    from app.genset import layout, notes, sheets as gsheets
    plan = layout.make_plan(brief)
    rows = [{"number": sp.no, "title": sp.title.upper()}
            for sp in gsheets.specs_for(plan)]
    texts = list(notes.GENERAL) + list(notes.template_project_notes(plan))
    return plan, rows, texts, sum(r["area"] for r in plan["rooms"])


MEP_ROWS = {"plumb_rough", "hvac_rough", "elec_rough", "mep_trim"}


@pytest.mark.parametrize("brief", [
    {"building_type": "single_family", "gross_sf": 1600},
    {"building_type": "restaurant", "gross_sf": 4500}])
def test_review1_mep_design_by_others_keeps_the_mep_rows(brief):
    _plan, rows, texts, area = _genset_sheets(brief)
    assert any("design are by others" in t for t in texts)
    sc = au.scope(rows, area_sf=area, texts=texts)
    assert sc["type"] == "new_building"
    keys = {a["key"] for a in au.plan(sc)}
    assert MEP_ROWS <= keys, MEP_ROWS - keys
    assert au.MEP_MISSING_NOTE in sc["notes"]
    assert sc["notes"].count(au.MEP_MISSING_NOTE) == 1
    # the design note is no exclusion
    assert not any(n.startswith("Not in this contract") and "design" in n
                   for n in sc["notes"])


def test_review1_design_phrases_are_notes_work_phrases_exclude():
    for note in ("STRUCTURAL, MECHANICAL, ELECTRICAL, PLUMBING AND FIRE "
                 "PROTECTION DESIGN ARE BY OTHERS.",
                 "FIRE SPRINKLER SYSTEM: DESIGN-BUILD BY OTHERS.",
                 "HVAC ENGINEERING BY OTHERS.",
                 "FIRE ALARM - DELEGATED DESIGN BY OTHERS."):
        assert st.exclusions([note]) == [], note
    for note, trade in (("ELECTRICAL WORK BY OTHERS (N.I.C.)",
                         "electrical"),
                        ("ALL PLUMBING WORK IS NOT IN CONTRACT.",
                         "plumbing"),
                        ("MECHANICAL WORK EXCLUDED FROM THIS CONTRACT.",
                         "hvac")):
        ex = st.exclusions([note])
        assert ex and ex[0].get("trades") == [trade], note
    # a note about one item takes no whole trade out
    ex = st.exclusions(["ELECTRICAL CONNECTION TO THE OWNER'S OVEN BY "
                        "OTHERS."])
    assert not ex or not ex[0].get("trades")


def test_review1_electrical_work_by_others_still_drops_electrical():
    _plan, rows, texts, area = _genset_sheets(
        {"building_type": "single_family", "gross_sf": 1600})
    sc = au.scope(rows + [{"number": "E-101", "title": "POWER PLAN"}],
                  area_sf=area,
                  texts=texts + ["ELECTRICAL WORK BY OTHERS (N.I.C.)"])
    keys = {a["key"] for a in au.plan(sc)}
    assert "elec_rough" not in keys and "electrical" not in sc["flags"]
    assert {"plumb_rough", "hvac_rough"} <= keys


@pytest.mark.parametrize("lines", [
    ["OFCI: OWNER FURNISHED, CONTRACTOR INSTALLED"],
    ["OWNER FURNISHED, CONTRACTOR INSTALLED (OFCI)"],
    ["(OFCI) OWNER FURNISHED, CONTRACTOR INSTALLED"],
    ["OFCI: FURNISHED BY OWNER, INSTALLED BY CONTRACTOR"],
    ["ABBREVIATIONS", "AFF ABOVE FINISHED FLOOR", "OFCI",
     "OWNER FURNISHED, CONTRACTOR INSTALLED", "OFOI",
     "OWNER FURNISHED, OWNER INSTALLED", "NIC NOT IN CONTRACT"]])
def test_review12_ofci_legend_makes_no_rows(lines):
    sc = au.scope(_rows(("A-101", "FLOOR PLAN")), area_sf=3000, texts=lines)
    assert st.exclusions(lines) == []
    names = _names(au.plan(sc))
    assert not any("wner" in n for n in names), names


def test_review12_a_real_ofci_item_is_still_scheduled():
    lines = ["ABBREVIATIONS", "OFCI: OWNER FURNISHED, CONTRACTOR INSTALLED",
             "GENERAL NOTES", "1. INSTALL OWNER-FURNISHED RTU-1 (OFCI)."]
    sc = au.scope(_rows(("A-101", "FLOOR PLAN"), ("M-101", "HVAC PLAN")),
                  area_sf=3000, texts=lines)
    names = _names(au.plan(sc))
    assert any(n.startswith("Owner delivers") and "RTU-1" in n
               for n in names), names
    assert any(n.startswith("Install owner-furnished") and "RTU-1" in n
               for n in names), names


def _logic(acts):
    """(share of activities missing a predecessor or a successor, the
    redundant FS links, the duplicate predecessor pairs)."""
    succ = {a["key"]: 0 for a in acts}
    for a in acts:
        for p, _t, _l in a["preds"]:
            succ[p] += 1
    missing = {a["key"] for a in acts if not a["preds"] and
               a["key"] != "ntp"} | {k for k, n in succ.items()
                                     if not n and k != "fc"}
    by = {a["key"]: a for a in acts}

    def before(k, seen=()):
        out = set()
        for p, t, lag in by[k]["preds"]:
            if t == "FS" and lag >= 0 and p not in seen:
                out |= {p} | before(p, seen + (k,))
        return out
    redundant, dup = [], []
    for a in acts:
        ps = [p for p, _t, _l in a["preds"]]
        if len(set(ps)) != len(ps):
            dup.append(a["key"])
        fs = [p for p, t, lag in a["preds"] if t == "FS" and lag == 0]
        chain = [p for p, t, lag in a["preds"] if t == "FS" and lag >= 0]
        redundant += [(p, a["key"]) for p in fs for q in chain
                      if q != p and p in before(q)]
    return len(missing) / len(acts), redundant, dup


def _waits_on(by, k):
    """Every activity k waits on, directly or through others."""
    out, todo = set(), [k]
    while todo:
        for p, _t, _l in by[todo.pop()]["preds"]:
            if p not in out:
                out.add(p)
                todo.append(p)
    return out


FITOUT_SHEETS = _rows(("A-101", "FLOOR PLAN"), ("AD-101", "DEMOLITION PLAN"),
                      ("M-101", "HVAC PLAN"), ("P-101", "PLUMBING PLAN"),
                      ("E-101", "POWER PLAN"),
                      ("FP-101", "FIRE SPRINKLER PLAN"))


def test_review13_permits_inspections_and_clean_logic():
    house = au.scope(_rows(("A-101", "FLOOR PLAN"),
                           ("A-201", "EXTERIOR ELEVATIONS")), area_sf=1600,
                     texts=["NEW SINGLE-FAMILY RESIDENCE"])
    fitout = au.scope(FITOUT_SHEETS, area_sf=4000,
                      texts=["TENANT IMPROVEMENT - SUITE 200"])
    assert (house["type"], fitout["type"]) == ("new_building", "renovation")
    for sc, inspections in ((house, 3), (fitout, 2)):
        acts = au.plan(sc)
        by = {a["key"]: a for a in acts}
        names = _names(acts)
        # T2: a building permit before mobilizing, trade permits before
        # the rough-ins
        assert any("permit" in n.lower() for n in names)
        assert "permit" in {p for p, _t, _l in by["mobilize"]["preds"]}
        for k in ("plumb_rough", "hvac_rough", "elec_rough"):
            assert "trade_permits" in _waits_on(by, k), k
        # T3: footing / rough-in / final inspections (fit-out: 2)
        insp = [n for n in names if "nspection" in n]
        assert len(insp) >= inspections, insp
        # T10: no redundant FS link, no duplicate pair, logic <= 5%
        share, redundant, dup = _logic(acts)
        assert not redundant and not dup, (redundant, dup)
        assert share <= 0.05, share
    names = _names(au.plan(house))
    assert "Footing & foundation inspection" in names
    assert "Rough-in inspections" in names
    assert any(n.startswith("Final inspections") for n in names)


@pytest.mark.parametrize("ptype", [t for t in st.TYPES
                                   if t not in st.BUILDING_TYPES])
def test_review13_every_type_has_a_permit_and_full_logic(ptype):
    sc = au.retype(au.scope(FITOUT_SHEETS, area_sf=5000), ptype)
    acts = au.plan(sc)
    by = {a["key"]: a for a in acts}
    assert "permit" in by and "permit" in {
        p for p, _t, _l in by["mobilize"]["preds"]}
    share, redundant, dup = _logic(acts)
    assert share <= 0.05 and not redundant and not dup, (share, redundant,
                                                         dup)


def test_review13_clean_links_drops_redundant_and_duplicate_links():
    acts = {"a": {"preds": []},
            "b": {"preds": [("a", "FS", 0)]},
            "c": {"preds": [("a", "FS", 0), ("b", "FS", 0), ("b", "SS", 2)]},
            "d": {"preds": [("a", "SS", 3), ("c", "FS", 0)]}}
    au.clean_links(acts)
    assert acts["c"]["preds"] == [("b", "FS", 0)]     # a -> b -> c
    assert acts["d"]["preds"] == [("a", "SS", 3), ("c", "FS", 0)]


# ---- DCMA point 3: lags on <= 5% of the links (Oct 21) --------------------
FULL_SHEETS = _rows(("C-101", "SITE PLAN"),
                    ("C-201", "GRADING AND DRAINAGE PLAN"),
                    ("C-301", "UTILITY PLAN"), ("C-401", "PAVING PLAN"),
                    ("L-101", "LANDSCAPE PLAN"), ("S-101", "FOUNDATION PLAN"),
                    ("A-101", "FLOOR PLAN"),
                    ("A-201", "EXTERIOR ELEVATIONS"),
                    ("M-101", "HVAC PLAN"), ("P-101", "PLUMBING PLAN"),
                    ("E-101", "POWER PLAN"),
                    ("FP-101", "FIRE SPRINKLER PLAN"),
                    ("FA-101", "FIRE ALARM PLAN"),
                    ("T-101", "TECHNOLOGY PLAN"),
                    ("D-101", "DEMOLITION PLAN"))
FULL_DIVS = ["02", "03", "04", "05", "06", "07", "08", "09", "10", "11",
             "12", "14", "21", "22", "23", "26", "27", "28", "31", "32", "33"]
FULL_TEXT = ["SCADA INTEGRATION", "BYPASS PUMPING", "DECK REPAIR",
             "SHEET METAL COPING", "CURB ADAPTERS", "ROOFTOP UNIT RTU-1"]


def _scope_for(kind, area):
    if kind == "full":
        return au.scope(FULL_SHEETS, divisions=FULL_DIVS, area_sf=area,
                        texts=FULL_TEXT, takeoff=[
                            {"type": "length", "group": "8 in sewer",
                             "value": 2400}])
    if kind == "fitout":
        return au.scope(FITOUT_SHEETS, area_sf=area)
    return au.scope(_rows(("A-101", "FLOOR PLAN")), area_sf=area)


@pytest.mark.parametrize("ptype", list(st.TYPES))
@pytest.mark.parametrize("kind,area", [("full", 2000), ("full", 30000),
                                       ("fitout", 5000), ("plan", 1600)])
def test_generated_schedules_pass_the_dcma_leads_lags_and_logic_points(
        ptype, kind, area, tmp_path):
    """Every project type's draft, built and checked as the person would
    (schedule_check on the project's schedule): lags on <= 5% of the
    links and no more than 5% of the activities missing logic. A lag that
    stood for real work is that work now (a lead-in: layout, a mock-up, a
    cure) - started with its predecessor, followed by the next trade. And
    no leads (DCMA point 2): the HVAC swap's old unit comes out FF with the
    new one's delivery, not 2 days ahead of it."""
    from app.pm import schedule_check
    from app.pm.store import ProjectStore
    s = ProjectStore(str(tmp_path / "p"))
    sc = au.retype(_scope_for(kind, area), ptype)
    au.build(s, sc, dt.date(2026, 11, 2))
    res = schedule_check.check(s, today=dt.date(2026, 11, 2))
    items = {i["key"]: i for i in res["items"]}
    lags, logic = items["lags"], items["logic"]
    leads = items["leads"]
    assert leads["passed"] is True, (leads["metric"], leads["offenders"])
    assert lags["passed"] is True, (lags["metric"], lags["offenders"])
    assert logic["passed"] is True, (logic["metric"], logic["offenders"])
    # and the plan itself: every lead-in sits between its work and the
    # trade that follows (SS from one, FS into the other)
    acts = au.plan(sc)
    by = {a["key"]: a for a in acts}
    for a in acts:
        if a["key"] not in st.LEAD_INS:
            continue
        assert [t for _p, t, lag in a["preds"]] == ["SS"], a
        assert all(lag == 0 for _p, _t, lag in a["preds"]), a
        assert any((a["key"], "FS", 0) in b["preds"] for b in acts), a
    assert not any(lag > 0 for a in by.values()
                   for _p, _t, lag in a["preds"]), ptype
    # DCMA point 2 (leads): no negative lag anywhere either
    assert not [(a["key"], p, t, lag) for a in by.values()
                for p, t, lag in a["preds"] if lag < 0], ptype


# ---- acceptance T4 / T5 / T10 for every generated type (Oct 21) ----------
GENSET_JOBS = {
    # name: (Generate Set brief, extra sheets, extra drawing text)
    "house": ({"building_type": "single_family", "gross_sf": 1600}, (), ()),
    "retail_fitout": ({"building_type": "small_commercial",
                       "occupancy": "M", "gross_sf": 3000,
                       "work": "existing"},
                      (("AD-101", "DEMOLITION PLAN"),),
                      ("RETAIL TENANT FIT-OUT - EXISTING BUILDING",)),
    "warehouse": ({"building_type": "warehouse", "gross_sf": 40000,
                   "office_sf": 3000}, (), ()),
}
# the long-lead materials each set's own quantities show, with a row to
# install them in its type's template
GENSET_ITEMS = {"house": {"windows", "trusses", "roofing", "doors"},
                "retail_fitout": {"doors"},
                "warehouse": {"storefront", "overhead_doors", "joists",
                              "roofing", "doors"}}
KENAI_SHEETS = _rows(("G-001", "COVER SHEET"), ("C-101", "SITE PLAN"),
                     ("C-301", "YARD PIPING PLAN"),
                     ("D-101", "DEMOLITION PLAN"),
                     ("S-101", "AERATION BASIN STRUCTURAL PLAN"),
                     ("M-101", "PROCESS MECHANICAL PLAN"),
                     ("M-201", "BLOWER BUILDING PLAN"),
                     ("E-101", "ELECTRICAL SITE PLAN"),
                     ("E-501", "ONE-LINE DIAGRAM"),
                     ("I-101", "PROCESS AND INSTRUMENTATION DIAGRAM"),
                     ("A-101", "BLOWER BUILDING FLOOR PLAN"))
KENAI_TEXT = ["WASTEWATER TREATMENT PLANT IMPROVEMENTS",
              "BL-1 150 HP BLOWER", "BL-2 150 HP BLOWER",
              "MCC-1 480V MOTOR CONTROL CENTER", "P-1 RAS PUMP 500 GPM",
              "SCADA INTEGRATION", "BYPASS PUMPING"]


def _genset_job(name, tmp_path):
    """A made-up Generate Set set as Build From Plans reads it: the sheet
    list and notes, and its sidecar (<name>.genset.json and
    <name>.quantities.csv beside the PDF) through read_genset - no PDF."""
    import json
    from app.genset import quantities
    brief, extra_sheets, extra_text = GENSET_JOBS[name]
    plan, rows, texts, area = _genset_sheets(brief)
    pdf = tmp_path / f"{name}.pdf"
    (tmp_path / f"{name}.genset.json").write_text(json.dumps(plan),
                                                  encoding="utf-8")
    quantities.write_csv(plan, str(tmp_path / f"{name}.quantities.csv"))
    gs = au.read_genset(str(pdf))
    assert gs and gs["plan"] and gs["rows"]
    return au.scope(rows + _rows(*extra_sheets), area_sf=area,
                    texts=list(extra_text) + texts, genset=gs)


def _special_scopes():
    """The listed-scope renovation (a repairs list on the cover, the
    generator by others, a tagged RTU), a Kenai-like treatment plant and a
    reroof with its recover / RTU notes."""
    return {
        "listed_renovation": au.scope(
            REPAIR_SHEETS + _rows(("M-101", "HVAC PLAN"),
                                  ("E-101", "POWER PLAN"),
                                  ("P-101", "PLUMBING PLAN"),
                                  ("FP-101", "FIRE SPRINKLER PLAN")),
            texts=REPAIR_COVER + GEN_NOTE + ["ROOFTOP UNIT RTU-1 10 TON"]),
        "treatment_plant": au.scope(KENAI_SHEETS, divisions=[
            "02", "03", "26", "40", "43", "46"], texts=KENAI_TEXT),
        "reroof": au.retype(au.scope(
            _rows(("A-101", "ROOF PLAN"), ("A-501", "ROOF DETAILS")),
            area_sf=20000, texts=["RECOVER BOARD", "DECK REPAIR",
                                  "SHEET METAL COPING", "CURB ADAPTERS",
                                  "ROOFTOP UNIT RTU-1",
                                  "TEAR-OFF EXISTING ROOFING"]), "reroof"),
    }


def _is_lead(a):
    """A procurement / lead-time row (left out of the high-duration
    point, T10)."""
    n = a["name"].lower()
    return a["key"].startswith(("proc_", "deliver_", "own_")) or \
        "long lead" in n or "lead time" in n


def _qa(acts):
    """T10 on a plan: {missing %, fs %, high_duration %, loops,
    duplicates, redundant}. Missing logic counts dangling ends too (only
    FF / SF into an activity, only SS / SF out of it)."""
    share, redundant, dup = _logic(acts)
    by = {a["key"]: a for a in acts}
    out_types = {k: set() for k in by}
    for a in acts:
        for p, t, _l in a["preds"]:
            out_types[p].add(t)
    dangling = {k for k, a in by.items() if a["preds"] and not
                {t for _p, t, _l in a["preds"]} & {"FS", "SS"}} | \
        {k for k, ts in out_types.items() if ts and not ts & {"FS", "FF"}}
    links = [t for a in acts for _p, t, _l in a["preds"]]
    work = [a for a in acts if a["duration"] > 0 and not _is_lead(a)]
    state, loops = {}, []

    def visit(k):
        state[k] = 1
        for p, _t, _l in by[k]["preds"]:
            if state.get(p) == 1:
                loops.append((p, k))
            elif p not in state:
                visit(p)
        state[k] = 2
    for k in by:
        if k not in state:
            visit(k)
    return {"missing": 100.0 * (share + len(dangling) / len(acts)),
            "fs": 100.0 * links.count("FS") / len(links),
            "high_duration": 100.0 * sum(1 for a in work if a["duration"]
                                         > 44) / len(work),
            "loops": loops, "duplicates": dup, "redundant": redundant,
            "non_fs": [(a["key"], p, t) for a in acts
                       for p, t, _l in a["preds"] if t != "FS"]}


def _assert_qa(acts, label):
    q = _qa(acts)
    assert q["missing"] <= 5.0, (label, q)
    assert q["fs"] >= 90.0, (label, q["fs"], q["non_fs"])
    assert q["high_duration"] <= 5.0, (label, q)
    assert not q["loops"] and not q["duplicates"] and not q["redundant"], \
        (label, q)


def _assert_procurement_feeds_work(acts, label):
    """Every procurement row's delivery is a predecessor of the work that
    installs it (T4): a chain ends in an install row, not in the air."""
    proc = {a["key"] for a in acts if _is_lead(a) or a["key"].startswith(
        ("sub_", "appr_"))}
    for a in acts:
        if not a["key"].startswith(("proc_", "deliver_")):
            continue
        succ = [b["key"] for b in acts
                if a["key"] in {p for p, _t, _l in b["preds"]}]
        assert [k for k in succ if k not in proc], (label, a["key"], succ)


@pytest.mark.parametrize("job", list(GENSET_JOBS))
def test_t4_a_chain_per_long_lead_item_the_set_counts(job, tmp_path):
    sc = _genset_job(job, tmp_path)
    assert sc["type"] == ("renovation" if job == "retail_fitout" else
                          "new_building")
    acts = au.plan(sc)
    by = {a["key"]: a for a in acts}
    items = {it["item"]: it for it in st.set_items(sc)}
    chained = {k[len("deliver_"):] for k in by if k.startswith("deliver_")}
    assert chained == GENSET_ITEMS[job], (job, chained)
    preds = lambda k: {p for p, _t, _l in by[k]["preds"]}   # noqa: E731
    for item in chained:
        it = items[item]
        sub, appr, dlv = f"sub_{item}", f"appr_{item}", f"deliver_{item}"
        assert by[sub]["name"].startswith("Submit ")
        assert by[appr]["name"].startswith("Review & approve ")
        assert by[dlv]["name"].startswith("Fabricate & deliver ")
        assert "ntp" in preds(sub) and sub in preds(appr) and \
            appr in preds(dlv)
        assert dlv in preds(it["install"]), (item, it["install"])
        # sized from the set's own count, the lead time says it's assumed
        assert "genset:" in by[dlv]["basis"] and "assumed" in \
            by[dlv]["basis"], by[dlv]["basis"]
        assert by[dlv]["duration"] == st.SET_LEAD_WEEKS[item] * 5
        assert by[dlv]["source"] == "genset"
    if chained:                     # the generic row is the rest's now
        assert by["submittals"]["name"] == \
            "Submittals & procurement - other materials"
    _assert_procurement_feeds_work(acts, job)
    if job == "warehouse":          # the dock doors have their own row
        assert by["oh_doors"]["name"] == \
            "Overhead doors (6), dock levelers & seals"
        assert "genset:" in by["oh_doors"]["basis"]
        assert "oh_doors" in preds("driedin")
    # a lead time typed in the dialog replaces the assumed one
    item = sorted(chained)[0]
    sc2 = au.retype(dict(sc, lead_weeks=st.parse_lead_weeks(
        f"{item} 11")), sc["type"], picked=False)
    d = {a["key"]: a for a in au.plan(sc2)}[f"deliver_{item}"]
    assert d["duration"] == 55 and "assumed" not in d["name"], d


def test_t4_no_set_quantities_no_made_up_chains():
    """Without the set's (or a takeoff's) count there's no evidence of
    the item: the floor-area estimate makes no chain. A takeoff count
    does."""
    sc = au.scope(FULL_SHEETS, area_sf=8000, divisions=FULL_DIVS)
    assert not any(a["key"].startswith(("sub_", "deliver_"))
                   for a in au.plan(sc))
    sc = au.scope(FULL_SHEETS, area_sf=8000, divisions=FULL_DIVS,
                  takeoff=[{"type": "count", "group": "Doors - HM",
                            "value": 24},
                           {"type": "count", "group": "Overhead doors",
                            "value": 4}])
    by = {a["key"]: a for a in au.plan(sc)}
    assert "deliver_doors" in {p for p, _t, _l in by["doors"]["preds"]}
    assert "takeoff:" in by["deliver_doors"]["basis"]
    assert by["deliver_doors"]["source"] == "takeoff"
    assert "deliver_overhead_doors" in {
        p for p, _t, _l in by["oh_doors"]["preds"]}
    assert by["doors"]["basis"].startswith("24 EA")    # not the OH doors


@pytest.mark.parametrize("ptype", list(st.TYPES))
def test_t4_every_type_procurement_feeds_an_install_row(ptype, tmp_path):
    scopes = [au.retype(_scope_for(k, a), ptype) for k, a in (
        ("full", 2000), ("full", 30000), ("fitout", 5000), ("plan", 1600))]
    scopes += [au.retype(_genset_job("warehouse", tmp_path), ptype)]
    for sc in scopes:
        acts = au.plan(sc)
        _assert_procurement_feeds_work(acts, ptype)
        if ptype not in st.BUILDING_TYPES:    # their own procurement rows
            assert not any(a["key"].startswith("deliver_") for a in acts)


def _built_rows(sc, tmp_path, tag):
    from app.pm.store import ProjectStore
    s = ProjectStore(str(tmp_path / tag))
    au.build(s, sc, dt.date(2026, 11, 2))
    rows = [r for r in s.list("activity") if r.get("parent")]
    return s, [r for r in rows if float(r.get("duration") or 0) > 0]


def _sourced(rows):
    return [r for r in rows if re.search(
        r"^SOURCE: (?:genset|takeoff|estimate)$", r.get("notes") or "",
        re.M)]


@pytest.mark.parametrize("ptype", list(st.TYPES))
def test_t5_every_work_row_has_its_basis(ptype, tmp_path):
    for kind, area in (("full", 2000), ("fitout", 5000), ("plan", 1600)):
        sc = au.retype(_scope_for(kind, area), ptype)
        _s, rows = _built_rows(sc, tmp_path, f"{kind}{area}")
        assert rows
        missing = [r["name"] for r in rows
                   if not (r.get("notes") or "").startswith("BASIS: ") or
                   not r.get("basis")]
        assert not missing, (ptype, kind, missing)
        assert all(re.search(r"^SOURCE: \w+$", r["notes"], re.M)
                   for r in rows)
        # no area read: the area-sized rows say so
        if kind == "full":
            assert not [r for r in rows if r["source"] == "area_assumed"]


@pytest.mark.parametrize("job", list(GENSET_JOBS))
def test_t5_generate_set_rows_come_from_the_set(job, tmp_path):
    from app.pm import schedule_check
    sc = _genset_job(job, tmp_path)
    s, rows = _built_rows(sc, tmp_path, job)
    assert all((r.get("notes") or "").startswith("BASIS: ") for r in rows)
    got = _sourced(rows)
    assert len(got) / len(rows) >= 0.60, (job, len(got), len(rows), [
        (r["name"], r["source"]) for r in rows if r not in got])
    # the set's numbers, not the assumed 5,000 SF
    assert not [r for r in rows if r["source"] == "area_assumed"]
    # and the built schedule passes the DCMA logic and FS points (T10)
    items = {i["key"]: i for i in schedule_check.check(
        s, today=dt.date(2026, 11, 2))["items"]}
    for k in ("logic", "leads", "lags", "rel_types"):
        assert items[k]["passed"] is True, (job, k, items[k]["metric"])


@pytest.mark.parametrize("ptype", list(st.TYPES))
def test_t10_every_type_passes_the_qa_points(ptype, tmp_path):
    cases = {f"{k}{a}": au.retype(_scope_for(k, a), ptype) for k, a in (
        ("full", 2000), ("full", 30000), ("fitout", 5000), ("plan", 1600))}
    for job in GENSET_JOBS:
        (tmp_path / job).mkdir()
        cases[job] = au.retype(_genset_job(job, tmp_path / job), ptype)
    for label, sc in cases.items():
        _assert_qa(au.plan(sc), f"{ptype}/{label}")


@pytest.mark.parametrize("name", ["listed_renovation", "treatment_plant",
                                  "reroof"])
def test_t10_listed_renovation_plant_and_reroof(name):
    sc = _special_scopes()[name]
    assert sc["type"] == {"listed_renovation": "renovation"}.get(name, name)
    acts = au.plan(sc)
    _assert_qa(acts, name)
    by = {a["key"]: a for a in acts}
    if name == "listed_renovation":
        assert "item1" in by and "byoth1" in by
        # the coordination row isn't left open-ended
        assert "byoth1" in {p for p, _t, _l in by["punch"]["preds"]}
    if name == "reroof":
        # the first area opens up, then the inspection: no SS into it
        assert by["deck_insp"]["preds"] == [("tear1", "FS", 0)]
        assert ("tear1", "FS", 0) in by["tearoff"]["preds"]
        assert [x for x in _qa(acts)["non_fs"]] == [
            ("seam_test", "insul", "SS")]
    if name == "treatment_plant":
        assert ("mobilize", "FS", 0) in by["excav"]["preds"]
        assert [x for x in _qa(acts)["non_fs"]] == [
            ("grout", "equip", "SS")]


def test_t10_a_lead_in_left_out_passes_its_logic_through_as_fs():
    """A lead-in (SS from its work) that isn't scheduled: what came after
    it waits on the finish of the work it led into, never on its start."""
    sc = au.retype(_scope_for("full", 5000), "new_building")
    sc = dict(sc, flags=set(sc["flags"]) - {"architectural", "finishes",
                                            "utilities"})
    acts = au.plan(sc)
    assert not [x for x in _qa(acts)["non_fs"]
                if x[1] in ("structure", "grading")], _qa(acts)["non_fs"]


# ---- review 0.12.38 #4 / #5 / #9 (made-up data) ------------------------
def test_review38_station_and_plant_jobs_have_inspections():
    """A made-up station repair scope with electrical and mechanical items
    gets trade inspections and a final inspection (T3 had 0), each a
    hold point the work after it waits on."""
    sc = au.scope(_rows(("C-101", "SITE PLAN"), ("M-101", "MECHANICAL "
                                                 "PLAN"),
                        ("E-101", "ELECTRICAL PLAN")),
                  texts=["LIFT STATION NO. 3 REPAIRS",
                         "REPLACE PUMP P-1 AND DISCHARGE PIPING",
                         "REPLACE CONTROL PANEL AND CONDUIT"],
                  project_type="pump_or_lift_station")
    for s in (sc, au.retype(sc, "treatment_plant"),
              au.retype(sc, "hvac_replacement")):
        acts = au.plan(s)
        by = {a["key"]: a for a in acts}
        insp = [n for n in _names(acts) if "nspection" in n]
        assert len(insp) >= 2, (s["type"], insp)
        assert "Final inspection" in insp
        assert "final_insp" in {p for p, _t, _l in by["sc"]["preds"]}
        assert "punch" in {p for p, _t, _l in by["final_insp"]["preds"]}
        share, redundant, dup = _logic(acts)
        assert not redundant and not dup, (redundant, dup)
    by = {a["key"]: a for a in au.plan(sc)}
    assert by["elec_insp"]["name"] == "Electrical inspection"
    assert "elec_insp" in {p for p, _t, _l in by["startup"]["preds"]}
    assert "mech_insp" in by


def test_review38_electrical_by_others_drops_it_from_combined_names():
    sheets = _rows(("A-101", "FLOOR PLAN"), ("A-201", "EXTERIOR ELEVATIONS"),
                   ("E-101", "POWER PLAN"), ("P-101", "PLUMBING PLAN"),
                   ("M-101", "HVAC PLAN"))
    for ptype in ("new_building", "renovation"):
        sc = au.scope(sheets, area_sf=6000, project_type=ptype,
                      texts=["ELECTRICAL WORK BY OTHERS (N.I.C.)"])
        names = _names(au.plan(sc))
        assert not [n for n in names if "lectric" in n and
                    "oordinat" not in n], names
        assert "Trade permits - plumbing, mechanical" in names
        assert "Plumbing trim" in names
        if ptype == "new_building":
            assert "Under-slab plumbing" in names
    names = _names(au.plan(au.scope(sheets, area_sf=6000,
                                    project_type="new_building")))
    assert st.TRADE_PERMIT_NAME in names
    assert "Plumbing & electrical trim" in names


def test_review38_small_house_gets_roof_trusses_not_steel_joists():
    sheets = _rows(("A-101", "FLOOR PLAN"), ("A-201", "EXTERIOR ELEVATIONS"),
                   ("A-301", "ROOF PLAN"))
    roof = [{"group": "Roof", "type": "area", "unit": "SF", "value": 1700}]
    sc = au.scope(sheets, area_sf=1500, takeoff=roof,
                  project_type="new_building")
    names = " | ".join(_names(au.plan(sc)))
    assert "roof trusses" in names and "steel joists" not in names
    # the set names joists: joists, even on a small building
    sc = au.scope(sheets, area_sf=1500, takeoff=roof,
                  project_type="new_building",
                  texts=["STEEL JOIST SCHEDULE", "18K5 @ 5'-0\" O.C."])
    names = " | ".join(_names(au.plan(sc)))
    assert "steel joists" in names and "roof trusses" not in names
    # a 12,000 SF building with no wood or residence words: joists
    sc = au.scope(sheets, area_sf=12000, takeoff=roof,
                  project_type="new_building")
    assert "steel joists" in " | ".join(_names(au.plan(sc)))
