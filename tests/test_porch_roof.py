"""The porch's shed roof tucks under the house eave (Jon, Oct 20)."""
from app.genset import outdoor


def _plan(ridge="x", upper=False):
    p = {"roof": {"type": "gable", "pitch": 6, "overhang": 1.5,
                  "ridge_dir": ridge},
         "level": {"floor_elev": 0.0, "plate_height": 9.0}}
    if upper:
        p["upper"] = {}
    return p


def test_under_the_eave_at_two_in_twelve():
    lo, hi, note = outdoor.porch_roof(_plan(), 6.0)
    eave = 9.0 - 0.5 * 1.5                       # 8'-3"
    assert hi == 8.0 and hi < eave
    assert abs((hi - lo) / 6.5 * 12 - 2.0) < 0.1
    assert lo - outdoor.BEAM - outdoor.SLAB >= outdoor.CLEAR - 1e-6
    assert note == ""


def test_deep_porch_keeps_headroom_and_says_so():
    lo, hi, note = outdoor.porch_roof(_plan(), 10.0)
    assert lo - outdoor.BEAM - outdoor.SLAB >= outdoor.CLEAR - 1e-6
    assert "low-slope" in note


def test_gable_front_and_two_story_unchanged():
    assert outdoor.porch_roof(_plan("y"), 6.0) == (8.0, 9.5, "")
    assert outdoor.porch_roof(_plan(upper=True), 6.0) == (8.0, 9.5, "")
