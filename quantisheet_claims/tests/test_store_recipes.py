"""Store round trip, backups, audit/frozen claims; recipes and units
(findings 20, 26, 27, 29, 30)."""
import dataclasses
import os

import pytest

from quantisheet_claims import model as m
from quantisheet_claims import store
from quantisheet_claims.interface import TakeoffItem
from quantisheet_claims.recipes import RecipeError, check_recipe, lines_for
from quantisheet_claims.revision import create_revision
from quantisheet_claims.settle import settle_claim
from .helpers import c8_claim, t1_claim


def test_round_trip_and_backups(claims_home):
    c = t1_claim(deductible=m.DeductibleSpec(per_peril=(
        m.PerilDeductible("wind", m.DeductibleSpec(kind="percent", bp=200)),)),
        rooms=(m.Room(id="R1", name="Kitchen", length_ft=m.Decimal("12.5")),),
        ale=m.AleCoverage(daily_cents=100, days=3, cap_cents=0))
    rev = create_revision(None, c, author="Jon", at="2026-10-20T12:00:00")
    for _ in range(12):
        p = store.save(c, [rev])
    back, revs = store.load(p)
    assert back == c and revs == [rev]
    assert settle_claim(back) == settle_claim(c)
    bdir = os.path.join(os.path.dirname(p), ".backup")
    assert len(os.listdir(bdir)) == 10


def test_bad_claim_file_number_refused(claims_home, tmp_path):
    p = store.save(c8_claim())
    txt = open(p, encoding="utf-8").read().replace('"qty_q4": 10000',
                                                   '"qty_q4": 1.5')
    open(p, "w", encoding="utf-8").write(txt)
    with pytest.raises(ValueError):
        store.load(p)


def test_claim_frozen_once_not_draft():
    c = m.edit(t1_claim(), "Jon", "submit", status="submitted")
    assert c.audit[-1].action == "submit"
    with pytest.raises(m.FrozenClaimError):
        m.edit(c, "Jon", "change insured", insured="X")
    with pytest.raises(dataclasses.FrozenInstanceError):
        c.insured = "X"


def test_finding30_unit_map():
    assert m.unit_from_text("sf") == "SF" and m.unit_from_text("ft") == "LF"
    assert m.unit_from_text("ea") == "EA" and m.unit_from_text("LS") == "LS"
    assert m.unit_from_text("mo") == "MO" and m.unit_from_text("bf") == "BF"
    assert m.unit_from_text("furlong") is None


WALL = TakeoffItem("Interior Wall", "1234.5000", "sf", "A-101", "#ff0000")


def test_recipes_make_lines_finding20_27():
    rs = (m.ClaimRecipe("Interior Wall", "SF", "DW-HANG-FIN",
                        "Drywall 1/2 in, hang + finish", "DRYWALL", 10_000, 1000,
                        m.UnitCost(material=95, labor=130)),
          m.ClaimRecipe("Interior Wall", "SF", "PAINT-2C", "Paint walls, 2 coats",
                        "PAINTING", 20_000, 0, m.UnitCost(labor=45)))
    a, b = lines_for(WALL, rs, structure_id="S1")
    assert a.qty_q4 == 12_345_000 and a.waste_bp == 1000 and a.rc == 277_763
    assert b.qty_q4 == 24_690_000 and b.rc == 111_105
    assert a.origin == "takeoff" and "A-101" in a.note


def test_unmatched_item_is_kept_for_review():
    (ln,) = lines_for(TakeoffItem("Mystery", "2.0000", "furlong", "1", ""), ())
    assert ln.item_code == "REVIEW" and ln.qty_q4 == 20_000
    assert "needs review" in ln.note and "unknown unit" in ln.note


def test_finding26_recipe_category_must_exist():
    with pytest.raises(RecipeError):
        check_recipe(m.ClaimRecipe("Floor", "SF", "LVP", category="FLR"))
    check_recipe(m.ClaimRecipe("Floor", "SF", "LVP", category="FLOORING"))
