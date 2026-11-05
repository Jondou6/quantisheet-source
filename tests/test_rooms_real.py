"""Auto Takeoff Rooms on CAD-style drawings: hollow double-line walls of
mixed thickness, door gaps with jambs, text on walls, a hatched floor,
rooms named without an area tag (tools/accuracy_real.py)."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import accuracy_real                                         # noqa: E402


def test_rooms_on_cad_style_plans():
    res = accuracy_real.score(2, seed=7, verbose=False)
    assert res["within5"] >= 0.9 * res["rooms"], res
    assert res["median_err"] < 0.02, res
