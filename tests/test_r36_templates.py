"""r36 A2 + B2: estimate templates (your own reusable sets of items with
quantity formulas off takeoff groups) and pay-item / bid-item templates.
Saved as your own JSON files. Made-up items only."""
import json
import os
from decimal import Decimal

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import assemblies, estimate_lines as EL, heavy, settings   # noqa: E402
from app.estimating import _io, costlink, templates                 # noqa: E402
from estimate_helpers import area, blank_doc                        # noqa: E402

SLAB = {"name": "Test slab", "type": "area", "unit": "sq ft"}


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(assemblies, "LIBRARY_PATH",
                        str(tmp_path / "assemblies.json"))
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)


def _source_doc():
    d = blank_doc()
    area(d, "Test slab", 10, 32)
    costlink.link_item(d, {"desc": "Test sheets", "unit": "ea", "mat": 12},
                       SLAB, formula="ceil(qty / 32)")
    costlink.link_item(d, {"desc": "Test sealer", "unit": "sf",
                           "mat": "0.25"}, SLAB)
    EL.add(d, [EL.new_line("Test permit", 1, "ls", sub=300)])
    return d


def test_template_from_estimate_and_apply_to_another_job(tmp_path):
    tpl = templates.from_lines(_source_doc(), "Test slab package")
    assert tpl["kind"] == "estimate" and len(tpl["items"]) == 3
    assert templates.placeholders(tpl) == ["Test slab"]
    path = templates.save(tpl, str(tmp_path / "slab.json"))
    tpl2 = templates.load(path)
    assert tpl2 == tpl
    # a new job measures its own floor; bind the template's placeholder
    d = blank_doc()
    area(d, "Floor B", 10, 64)                       # 640 sq ft
    ids = templates.apply(d, tpl2, {"Test slab": ("Floor B", "area",
                                                  "sq ft")})
    rows = {r["desc"]: r for r in EL.priced(d)}
    assert len(ids) == 3
    assert rows["Test sheets"]["quantity"] == Decimal("20")
    assert rows["Test sealer"]["quantity"] == Decimal("640")
    assert rows["Test permit"]["quantity"] == Decimal("1")
    assert rows["Test permit"]["total"] == Decimal("300.00")
    assert all("Template: Test slab package" in r["source"]
               or r["source"] for r in rows.values())


def test_unbound_placeholder_gives_a_typed_zero_line():
    d = blank_doc()
    tpl = templates.from_lines(_source_doc(), "T")
    templates.apply(d, tpl, {})
    rows = EL.priced(d)
    linked = [r for r in rows if r["linked"]]
    assert not linked
    assert {r["desc"]: r["quantity"] for r in rows}["Test sheets"] == 0


def test_default_folder_is_the_apps_data_dir_and_list(tmp_path):
    tpl = templates.from_lines(_source_doc(), "My: slab/kit")
    p = templates.save(tpl)
    assert os.path.dirname(p) == os.path.join(settings.DIR,
                                              "estimate_templates")
    names = [t["name"] for t in templates.list_saved()]
    assert names == ["My: slab/kit"]


def test_bad_files_are_refused(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"kind": "nope", "items": []}))
    with pytest.raises(templates.TemplateError):
        templates.load(str(bad))
    bad.write_text(json.dumps({"kind": "estimate", "name": "x",
                               "items": [{"desc": "y", "formula": "qty+"}]}))
    with pytest.raises(templates.TemplateError):
        templates.load(str(bad))
    tpl = templates.from_lines(_source_doc(), "x")
    with pytest.raises(_io.PathError):                # never into app/
        templates.save(tpl, os.path.join(_io.APP_DIR, "data", "x.json"))


def test_pay_item_template_round_trip_into_a_civil_job(tmp_path):
    job = heavy.blank()
    job["pay_items"] = [{"no": "1", "desc": "Test mobilization",
                         "unit": "LS", "owner_qty": "1", "weight": "1"},
                        {"no": "2", "desc": "Test 8 in sewer",
                         "unit": "LF", "owner_qty": "500", "weight": "1.2"}]
    tpl = templates.from_pay_items(job, "Test sewer job")
    assert tpl["kind"] == "bid_items" and len(tpl["items"]) == 2
    p = templates.save(tpl, str(tmp_path / "sewer.json"))
    new = heavy.blank()
    new["pay_items"] = [{"no": "2", "desc": "already here", "unit": "LF",
                         "owner_qty": "7", "weight": "1"}]
    added = templates.apply_bid_items(new, templates.load(p))
    assert added == ["1"]                            # "2" kept as it was
    assert [x["no"] for x in new["pay_items"]] == ["2", "1"]
    assert new["pay_items"][0]["desc"] == "already here"
    with pytest.raises(templates.TemplateError):
        templates.apply(blank_doc(), tpl, {})       # wrong kind
