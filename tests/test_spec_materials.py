"""Reading the project manual for what the drawings don't say: pipe and
duct materials, and pipe / duct insulation from the schedules."""
import pytest

PAGES = ["""SECTION 221116 - DOMESTIC WATER PIPING
PART 1 - GENERAL
1.1 SUMMARY
A. Section Includes:
1. Copper tube and fittings.
PART 3 - EXECUTION
3.1 PIPING APPLICATIONS
A. Flanges and unions may be used for aboveground piping joints.
B. Under-building-slab, domestic water piping, NPS 2 and smaller is to be the
following:
1. Annealed-temper copper tube, ASTM B88, Type K; wrought-copper fittings.
C. Aboveground domestic water piping, NPS 2 and smaller is to be the
following:
1. Drawn-temper copper tube, ASTM B88, Type L; solder-joint fittings.
DOMESTIC WATER PIPING 221116 - 5
END OF SECTION 221116
""", """SECTION 221316 - SANITARY WASTE AND VENT PIPING
PART 1 - GENERAL
1.1 SUMMARY
A. Section Includes:
1. PVC pipe and fittings.
2. Specialty pipe fittings.
END OF SECTION 221316
SECTION 220719 - PLUMBING PIPING INSULATION
PART 3 - EXECUTION
3.9 INDOOR PIPING INSULATION SCHEDULE
A. Domestic Cold Water:
1. NPS 1 and Smaller: Insulation is one of the following:
a. Glass-Fiber, Preformed Pipe Insulation, Type I: 1/2 inch thick.
2. NPS 1-1/4 and Larger: Insulation is one of the following:
a. Glass-Fiber, Preformed Pipe Insulation, Type I: 1 inch thick.
END OF SECTION 220719
""", """SECTION 233113 - METAL DUCTS
3.1 DUCT SCHEDULE
A. Fabricate ducts with galvanized sheet steel except as otherwise indicated.
END OF SECTION 233113
SECTION 230713 - DUCT INSULATION
3.8 INDOOR DUCT AND PLENUM INSULATION SCHEDULE
A. Concealed, round and flat-oval, supply-air duct insulation is the
following:
1. Glass-Fiber Blanket: 2.2 inches thick and 0.75 lb/cu. ft. density.
END OF SECTION 230713
"""]


def _spec():
    from app.spec_materials import Spec
    return Spec.from_pages(PAGES)


def test_pipe_material_by_system_size_and_location():
    sp = _spec()
    assert sp.pipe_material("CW", 0.5)[0].startswith("Drawn-temper copper")
    assert "Type K" in sp.pipe_material("CW", 0.5, under_slab=True)[0]
    assert sp.pipe_material("W", 3)[0] == "PVC pipe and fittings"
    assert sp.pipe_material("CW", 0.5)[1] == "221116"


def test_insulation_follows_the_schedule_by_size():
    sp = _spec()
    assert sp.pipe_insulation("CW", 0.75)[1] == 0.5
    assert sp.pipe_insulation("CW", 1.5)[1] == 1.0
    assert sp.pipe_insulation("W", 3) is None          # not insulated
    assert sp.duct_material()[0] == "galvanized sheet steel"
    assert sp.duct_insulation("round", "supply")[1] == 2.2


def test_spec_quantities_add_insulation_and_materials():
    from app import aitakeoff as ait

    def mark(group, value, meth):
        return (0, "add_line", {"measure": {"type": "length",
                                            "value": value, "group": group,
                                            "method": meth}})
    res = {"marks": [mark('1/2" CW', 100.0, "AI takeoff: pipe runs"),
                     mark('2" W', 50.0, "AI takeoff: pipe runs"),
                     mark('12" round', 30.0, "AI takeoff: ducts")],
           "quantities": [{"engine": "pipe drops", "name": '1/2" CW drops',
                           "qty": 14.0, "unit": "ft",
                           "status": "taken off"}],
           "review": []}
    n = ait.spec_quantities(res, _spec())
    assert n == 2
    q = [x for x in res["quantities"] if x["engine"] == "spec"]
    assert len(q) == 1 and q[0]["qty"] == 114.0
    assert q[0]["name"].endswith('0.5" thick')
    assert any(r["name"].startswith("Duct insulation") for r in
               res["review"])
    assert "copper" in res["materials"]['1/2" CW']
    assert "PVC" in res["materials"]['2" W']


EARTH = ["""SECTION 312000 - EARTH MOVING
3.7 EXCAVATION FOR UTILITY TRENCHES
B. Excavate trenches to uniform widths to provide the following clearance on
each side of pipe or conduit.
1. Clearance: 12 inches each side of pipe or conduit.
C. Trench Bottoms:
2. Excavate trenches 4 inches deeper than bottom of pipe and conduit
elevations to allow for bedding course.
END OF SECTION 312000
SECTION 333115 - SITE SANITARY SEWERAGE PIPING
3.2 INSTALLATION
A. Install piping with 36-inch minimum cover.
END OF SECTION 333115
"""]


def test_trench_rules_and_lines_for_review():
    from app import aitakeoff as ait
    from app.spec_materials import Spec
    sp = Spec.from_pages(EARTH)
    r = sp.trench_rules("sanitary")
    assert (r["cover_in"], r["clear_in"], r["bed_in"]) == (36, 12, 4)
    res = {"marks": [], "quantities": [], "review": [], "civil": {"pipes": [
        {"name": '6" PVC sanitary, depth unknown', "system": "sanitary",
         "size": 6, "length": 270.0, "existing": False, "runs": []}]}}
    ait.spec_quantities(res, sp)
    exc = next(x for x in res["review"]
               if x["name"] == 'Trench excavation - 6" PVC sanitary')
    # 270 LF x 2.5 ft x (36 + 6 + 4)/12 ft / 27
    assert exc["qty"] == round(270 * 2.5 * 46 / 12 / 27, 1)
    assert '36" minimum cover' in exc["why"]


def test_shades_follow_the_spec_locations():
    from app import aitakeoff as ait
    from app.spec_materials import Spec
    sp = Spec.from_pages(["""SECTION 122413 - ROLLER WINDOW SHADES
3.2 INSTALLATION
C. Roller Shade Locations: At exterior windows.
END OF SECTION 122413
"""])
    assert sp.shade_locations()[0] == "At exterior windows"

    def win(g):
        return (0, "add_count", {"measure": {"type": "count", "group": g,
                                             "method": "AI takeoff: schedules"}})
    res = {"marks": [win("Window A.1"), win("Window A.1"), win("Window B")],
           "quantities": [], "review": []}
    ait.spec_quantities(res, sp)
    q = {x["name"]: x["qty"] for x in res["quantities"]}
    assert q == {"Window shade at Window A.1": 2, "Window shade at Window B": 1}
