"""ADA from the drawings (0.12.26): counts fill the checker, measured sizes
are checked and clouded, and residential units are scoped (233.3)."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import ada_check as ac                                # noqa: E402
from app import ada_ref as ref                                 # noqa: E402
from app import ada_takeoff as at                              # noqa: E402


def test_every_element_rule_quotes_its_section():
    for words, label, op, val, cite in at.ELEMENTS:
        text = ref.find(cite)["text"]
        for v in (val if isinstance(val, tuple) else (val,)):
            assert f"{v} inch" in text, (label, cite, v)


@pytest.mark.parametrize("group,label", [
    ("Door Clear Width", "Door clear width"),
    ("Accessible Route", "Accessible route clear width"),
    ("Corridor Width", "Accessible route clear width"),
    ("Van Access Aisle", "Van access aisle"),
    ("Parking Stall Width", "Parking space width"),
    ("Toilet Stall Width", "Wheelchair compartment width"),
    ("Ambulatory Stall", "Ambulatory compartment width"),
    ("Grab Bar Height", "Grab bar height"),
    ("Counter Height", "Sales / service counter height"),
    ("Turning Space", "Turning space diameter"),
    ("Ramp Width", "Ramp clear width")])
def test_element_names(group, label):
    assert at.element_rule(group)[0] == label


def test_plain_names_are_not_elements():
    for g in ("Door", "Wall", "Corridor", "Baseboard", "Exit Door"):
        assert at.element_rule(g) is None, g


@pytest.mark.parametrize("group,field", [
    ("Parking", "parking"), ("Accessible Parking", "accessible_parking"),
    ("ADA Parking", "accessible_parking"), ("Van Parking", "van"),
    ("WC - Men", "water_closets"), ("Urinal - Men", "urinals"),
    ("Lav: Men", "lavatories"),
    ("Accessible Stall - Women", "wheelchair_compartments"),
    ("Ambulatory Stall - Women", "ambulatory_compartments"),
    ("Toilet Stall - Women", "compartments"), ("Seat", "seats"),
    ("Wheelchair Space", "wheelchair_spaces"), ("Entrance",
                                                "public_entrances"),
    ("Accessible Entrance", "accessible_entrances"),
    ("Drinking Fountain", "drinking_fountains"),
    ("Guest Room", "guest_rooms"), ("Dwelling Unit", "dwelling_units"),
    ("Toilet Room", None), ("Toilet Paper Holder", None)])
def test_count_names(group, field):
    assert at.count_field(group) == field


def _items():
    rows = [("Parking", 40), ("Accessible Parking", 1), ("Van Parking", 1),
            ("WC - Men", 2), ("Urinal - Men", 3), ("Lavatory - Men", 2),
            ("Toilet Stall - Women", 4), ("Accessible Stall - Women", 1),
            ("Ambulatory Stall - Women", 1), ("Seat", 300),
            ("Entrance", 2), ("Accessible Entrance", 1)]
    return [{"type": "count", "group": g, "value": v, "page": 0}
            for g, v in rows]


def test_counts_fill_the_checker():
    c = at.counts(None, _items())
    assert c["parking"] == [{"total": 42, "accessible": 2, "van": 1,
                             "name": "Parking, sheet 1"}]
    rooms = {r["name"]: r for r in c["toilet_rooms"]}
    assert rooms["Men"] == {"water_closets": 2, "urinals": 3,
                            "lavatories": 2, "name": "Men"}
    assert rooms["Women"]["compartments"] == 6
    assert c["public_entrances"] == 3 and c["accessible_entrances"] == 1
    fs = ac.check(dict(c, use="retail"))
    women = [f for f in fs if f.item.startswith("Women: ambulatory")]
    assert women and women[0].status == "ok"
    assert [f for f in fs if "accessible spaces" in f.item][0].status == \
        "ok"                                   # 42 spaces need 2


def test_measured_elements():
    items = [{"type": "length", "group": "Door Clear Width", "value": 2.5,
              "unit": "ft", "page": 1, "ref": "a"},
             {"type": "length", "group": "Grab Bar Height", "value": 34,
              "unit": "in", "page": 0, "ref": "b"},
             {"type": "length", "group": "Grab Bar Height", "value": 38,
              "unit": "in", "page": 0, "ref": "c"},
             {"type": "length", "group": "Wall", "value": 10, "unit": "ft",
              "page": 0, "ref": "d"}]
    fs = at.elements(None, items)
    assert [(f.status, f.provided, f.page, f.ref) for f in fs] == [
        ("short", 30.0, 1, "a"), ("ok", 34.0, 0, "b"),
        ("short", 38.0, 0, "c")]


def test_residential_units_and_parking():
    assert ac.residential_parking(43, 30) == 3     # 2 for units + 1 of 13
    assert ac.residential_parking(30, 30) == 2
    assert ac.residential_parking(20, 30) == ac.parking_required(20)
    fs = ac.check({"use": "residential", "dwelling_units": 30,
                   "parking": [{"total": 43}]})
    mob = [f for f in fs if "mobility features" in f.item][0]
    com = [f for f in fs if "communication features" in f.item][0]
    assert (mob.required, com.required) == (2, 1)
    assert "233.3.1.1" in mob.cite
    assert ac.check({"use": "residential", "dwelling_units": 12})


def test_on_a_real_drawing():
    fitz = pytest.importorskip("fitz")
    from app import annotate
    d = fitz.open()
    d.new_page(width=2592, height=1728)
    annotate.apply_op(d, annotate.new_op("set_scale", 0, ppu=4.5,
                                         unit="ft"))
    for i, (g, ft) in enumerate((("Door Clear Width", 2.5),
                                 ("Accessible Route", 4.0))):
        annotate.apply_op(d, annotate.new_op(
            "add_polyline", 0, pts=[[100, 200 + 40 * i],
                                    [100 + 4.5 * ft, 200 + 40 * i]],
            measure={"type": "length", "value": ft, "unit": "ft",
                     "group": g}))
    for i in range(3):
        annotate.apply_op(d, annotate.new_op(
            "add_count", 0, pt=[1500 + 30 * i, 1500], n=1,
            measure={"type": "count", "value": 1, "unit": "ea",
                     "group": "WC - Men"}))
    assert at.counts(d)["toilet_rooms"][0]["water_closets"] == 3
    fs = at.elements(d)
    assert sorted(f.status for f in fs) == ["ok", "short"]
    assert at.markup(d, fs) == 1
    clouds = [a for a in d[0].annots()
              if (a.info or {}).get("subject") == "ADA Check"]
    assert len(clouds) == 1 and "404.2.3" in clouds[0].info["content"]
