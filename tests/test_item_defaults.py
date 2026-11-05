"""v15: default depth / drop per item, auto labels MH-1, MH-2..."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz                                                   # noqa: E402
import pytest                                                 # noqa: E402
from app import annotate, item_defaults as idf                # noqa: E402
from test_gui import win, qapp                                # noqa: E402,F401


def _doc():
    d = fitz.open()
    d.new_page(width=600, height=400)
    annotate.apply_op(d, annotate.new_op("set_scale", 0, ppu=10, unit="ft"))
    return d


def test_prefix_guess():
    assert idf.prefix_for("Manhole") == "MH"
    assert idf.prefix_for("Catch Basin") == "CB"
    assert idf.prefix_for("Sewer Cleanout") == "SC"
    assert idf.prefix_for("Tree") == "TR"


def test_defaults_saved_in_the_pdf(tmp_path):
    d = _doc()
    idf.set_default(d, "Manhole", depth=8.5)
    idf.set_default(d, "Service", drop=4)
    p = str(tmp_path / "x.pdf")
    d.save(p)
    d2 = fitz.open(p)
    assert idf.defaults(d2)["Manhole"] == {"prefix": "MH", "depth": 8.5,
                                           "drop": 0.0}
    assert idf.defaults(d2)["Service"]["drop"] == 4.0


def test_counts_get_sequential_labels_and_default_depth():
    d = _doc()
    idf.set_default(d, "Manhole", depth=8.0)
    for x in (50, 120, 200):
        p = idf.decorate(d, 0, "add_count", {
            "pt": [x, 100], "n": 1,
            "measure": {"type": "count", "value": 1, "unit": "ea",
                        "group": "Manhole"}})
        annotate.apply_op(d, annotate.new_op("add_count", 0, **p))
    rows = idf.structures(d)
    assert [r["label"] for r in rows] == ["MH-1", "MH-2", "MH-3"]
    assert all(r["depth"] == 8.0 for r in rows)
    labels = [it["label"] for it in annotate.takeoff_items(d)]
    assert "MH-2" in labels
    # depth per structure can be overridden; numbering continues after max
    idf.set_depth(d, "MH-2", 11.5)
    assert {r["label"]: r["depth"] for r in idf.structures(d)}["MH-2"] == 11.5
    assert idf.next_label(d, "Manhole") == "MH-4"


def test_length_gets_drop_added_once_per_run():
    d = _doc()
    idf.set_default(d, "Service", drop=4.0)
    p = idf.decorate(d, 0, "add_polyline", {
        "pts": [[0, 0], [100, 0]],
        "measure": {"type": "length", "value": 10.0, "unit": "ft",
                    "group": "Service"}})
    assert p["measure"]["value"] == pytest.approx(14.0)
    p2 = idf.decorate(d, 0, "add_polyline", {
        "pts": [[0, 0], [100, 0]],
        "measure": {"type": "length", "value": 10.0, "unit": "ft",
                    "group": "Other"}})
    assert p2["measure"]["value"] == 10.0          # no default: untouched


def test_viewer_click_counts_are_labelled(win):
    idf.install(win)
    v = win._view
    idf.set_default(v.doc, "Manhole", depth=6.0)
    v.count_group = "Manhole"
    v.commit_click("count", fitz.Point(100, 100))
    v.commit_click("count", fitz.Point(160, 100))
    assert [r["label"] for r in idf.structures(v.doc)] == ["MH-1", "MH-2"]
