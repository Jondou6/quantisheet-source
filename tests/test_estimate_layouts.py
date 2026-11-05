"""Saved estimate layouts: named views of the same estimate lines that
regroup and re-total them - and every one of them adds up to the same
grand total to the cent (direct cost + the job's markups + the location
adjustment). Made-up job and numbers."""
import csv
import json
import os
import random
from decimal import Decimal

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import (assemblies, dmoney, estimate_export as EX,      # noqa: E402
                 estimate_layouts as L, estimate_lines as EL, proposal,
                 settings)
from estimate_helpers import blank_doc                           # noqa: E402
from test_gui import win, qapp                                   # noqa: E402,F401


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(assemblies, "LIBRARY_PATH",
                        str(tmp_path / "assemblies.json"))
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)


def _location(monkeypatch, pct="3.1"):
    """A made-up location adjustment: +pct% on material, labor and
    equipment, in region 'Test Region'."""
    def adj(mat, lab, eqp, region):
        f = Decimal(pct) / 100
        out = {"mat": dmoney.cents(dmoney.D(mat) * f),
               "lab": dmoney.cents(dmoney.D(lab) * f),
               "eqp": dmoney.cents(dmoney.D(eqp) * f)}
        out["total"] = out["mat"] + out["lab"] + out["eqp"]
        return out
    monkeypatch.setattr(EL, "location_adjustment", adj)
    monkeypatch.setattr(EL, "job_region", lambda doc: "Test Region")


def _job(markups=True):
    """Lines with awkward cents in five divisions, every cost type, a
    mixed Mat + Lab line, an allowance, a sub line and an uncoded line;
    with the proposal's markups saved (tax, gc, overhead, profit, bond)."""
    d = blank_doc()
    EL.add(d, [
        EL.new_line("Test slab", "1013.5", "sf", code="03 31 13",
                    mat="2.4567", lab="0.8133"),
        EL.new_line("Test footing", 3, "cy", code="03 11 13",
                    mat="133.3333"),
        EL.new_line("Test gyp", 2417, "sf", code="09 29 10",
                    mat="0.3317", lab="0.4471"),
        EL.new_line("Test paint", 1, "ls", code="09 91 23",
                    cost_type="Subcontract", sub="4321.07"),
        EL.new_line("Test scaffold", 2, "mo", code="01 54 33",
                    eqp="333.333"),
        EL.new_line("Test electrical allowance", 1, "ls", code="26 00 00",
                    cost_type="Allowance", sub="12500"),
        EL.new_line("Test roofing sub", 1, "ls", code="07 54 23",
                    sub="18765.43"),
        EL.new_line("Test cleanup", 7, "hr", lab="47.19"),
    ])
    if markups:
        proposal.write(d, dict(proposal.defaults(d), tax=8.25, gc=2.5,
                               overhead=10, profit=7.5, contingency=1.75,
                               bond="auto"))
    return d


def _check(v, b):
    """The view adds up: groups + listed adjustments + not-shown =
    the estimate's grand total, to the cent."""
    groups = sum((g["subtotal"]["total"] for g in v["groups"]),
                 Decimal("0.00"))
    listed = sum((a for _l, a in v["adjustments"]), Decimal("0.00"))
    hidden = v["not_shown"][1] if v["not_shown"] else Decimal("0.00")
    assert groups + listed + hidden == b["total"]
    assert v["total"] == b["total"]
    for g in v["groups"]:
        assert sum((r["value"]["total"] for r in g["rows"]),
                   Decimal("0.00")) == g["subtotal"]["total"]


def test_the_estimate_is_direct_plus_markups_plus_location(monkeypatch):
    _location(monkeypatch)
    d = _job()
    b = L.base(d)
    s = EX.summary(d)
    assert b["direct"] == s["total"]                 # Export My Estimate's
    keys = [a["key"] for a in b["adjustments"]]
    assert keys == ["gc", "tax", "overhead", "profit", "contingency",
                    "bond", "location"]
    loc = next(a for a in b["adjustments"] if a["key"] == "location")
    assert loc["amount"] == s["location"][-1][1] - s["location"][0][1]
    tax = next(a for a in b["adjustments"] if a["key"] == "tax")
    assert tax["amount"] == dmoney.cents(s["types"]["Material"] *
                                         Decimal("0.0825"))
    assert b["total"] == b["direct"] + sum(a["amount"]
                                           for a in b["adjustments"])
    for a in b["adjustments"]:
        assert a["amount"] == a["amount"].quantize(Decimal("0.01"))


def test_no_markups_until_the_proposal_is_saved():
    d = _job(markups=False)
    b = L.base(d)
    assert b["adjustments"] == [] and b["total"] == EX.summary(d)["total"]


def test_every_built_in_layout_totals_to_the_cent(monkeypatch):
    _location(monkeypatch)
    d = _job()
    b = L.base(d)
    names = [x["name"] for x in L.builtins()]
    assert names == ["By CSI division", "By bid item / trade",
                     "By cost type", "Budget vs Sub vs Takeoff",
                     "Owner presentation"]
    for lay in L.builtins():
        v = L.view(d, lay, b)
        _check(v, b)
        # the screen / CSV rows end on the same grand total
        assert L.flat_rows(v)[-1] == ("total", "Grand total",
                                      {"total": dmoney.fmt(b["total"])})


@pytest.mark.parametrize("group_by", list(L.GROUP_BY))
@pytest.mark.parametrize("adjust", list(L.ADJUST))
@pytest.mark.parametrize("filters", [
    {}, {"div_from": "03", "div_to": "09"},
    {"cost_types": ["Material", "Subcontract"]},
    {"div_from": "07", "cost_types": ["Labor"]}])
def test_any_layout_of_yours_totals_to_the_cent(monkeypatch, group_by,
                                                adjust, filters):
    _location(monkeypatch)
    d = _job()
    b = L.base(d)
    lay = L.new_layout("Mine", group_by=group_by, adjustments=adjust,
                       filters=filters, sort="total_desc",
                       columns=list(L.COLUMNS))
    _check(L.view(d, lay, b), b)


def test_owner_presentation_folds_the_markups_into_the_divisions(
        monkeypatch):
    _location(monkeypatch)
    d = _job()
    b = L.base(d)
    v = L.view(d, L.find(d, "Owner presentation"), b)
    assert v["adjustments"] == [] and v["not_shown"] is None
    direct = {g["label"]: g["subtotal"]["total"] - g["subtotal"]["adds"]
              for g in v["groups"]}
    plain = {g["label"]: g["subtotal"]["total"] for g in
             L.view(d, L.find(d, "By CSI division"), b)["groups"]}
    assert direct == plain                       # same lines underneath
    assert all(g["subtotal"]["adds"] > 0 for g in v["groups"])
    rows = L.flat_rows(v)
    assert [k for k, _l, _c in rows] == ["subtotal"] * len(v["groups"]) + \
        ["total"]


def test_budget_vs_sub_vs_takeoff_columns():
    d = _job(markups=False)
    v = L.view(d, L.find(d, "Budget vs Sub vs Takeoff"))
    by = {g["label"]: g["subtotal"] for g in v["groups"]}
    elec = by["Division 26 - Electrical"]
    assert (elec["budget"], elec["subcontract"], elec["takeoff"]) == (
        Decimal("12500.00"), Decimal("0.00"), Decimal("0.00"))
    roof = by["Division 07 - Thermal and moisture protection"]
    assert roof["subcontract"] == Decimal("18765.43") and \
        roof["takeoff"] == 0
    fin = by["Division 09 - Finishes"]
    assert fin["subcontract"] == Decimal("4321.07")
    assert fin["takeoff"] == dmoney.cents(2417 * Decimal("0.3317")) + \
        dmoney.cents(2417 * Decimal("0.4471"))
    for s in by.values():
        assert s["budget"] + s["subcontract"] + s["takeoff"] == s["total"]


def test_by_cost_type_splits_a_mixed_line():
    d = _job(markups=False)
    v = L.view(d, L.find(d, "By cost type"))
    by = {g["label"]: g for g in v["groups"]}
    assert list(by)[:3] == ["Material", "Labor", "Equipment"]
    slab = [r["desc"] for g in ("Material", "Labor")
            for r in by[g]["rows"]]
    assert slab.count("Test slab") == 2
    s = EX.summary(d)
    for k, amt in s["types"].items():
        assert by[k]["subtotal"]["total"] == amt


def test_filters_keep_the_total_with_a_not_shown_line(monkeypatch):
    _location(monkeypatch)
    d = _job()
    b = L.base(d)
    lay = L.new_layout("Concrete only", filters={"div_from": "03",
                                                 "div_to": "03"})
    v = L.view(d, lay, b)
    assert [g["label"] for g in v["groups"]] == ["Division 03 - Concrete"]
    assert v["not_shown"][0] == L.NOT_SHOWN
    _check(v, b)


def test_layouts_are_saved_in_the_pdf_and_travel_with_it(tmp_path):
    import fitz
    d = _job(markups=False)
    lay = L.new_layout("Phase view", group_by="tag", columns=["total"])
    L.save_layout(d, lay)
    line = EX.collect(d)[0]
    L.set_tag(d, line["key"], "Phase 1")
    p = str(tmp_path / "job.pdf")
    d.save(p)
    d2 = fitz.open(p)
    assert [x["name"] for x in L.layouts(d2)][-1] == "Phase view"
    v = L.view(d2, L.find(d2, "Phase view"))
    assert [g["label"] for g in v["groups"]] == ["Phase 1", "(untagged)"]
    with pytest.raises(L.LayoutError):
        L.save_layout(d2, L.new_layout("By CSI division"))
    assert L.delete_layout(d2, "Phase view")
    assert L.find(d2, "Phase view") is None


def test_export_and_import_between_jobs(tmp_path):
    a = _job(markups=False)
    L.save_layout(a, L.new_layout("Trade summary", group_by="trade",
                                  detail=False, columns=["total"]))
    L.save_layout(a, L.new_layout("Subs", filters={"cost_types":
                                                   ["Subcontract"]}))
    path = L.export_file(str(tmp_path / "mine.json"),
                         [x for x in L.layouts(a) if not x.get("builtin")])
    data = json.loads(open(path, encoding="utf-8").read())
    assert data["kind"] == L.EXPORT_KIND and len(data["layouts"]) == 2
    b = blank_doc()
    assert L.import_file(b, path) == ["Trade summary", "Subs"]
    got = L.find(b, "Subs")
    assert got["filters"]["cost_types"] == ["Subcontract"]
    # a layout named like a built-in comes in under another name
    clash = str(tmp_path / "clash.json")
    L.export_file(clash, [L.new_layout("By cost type", columns=["total"])])
    assert L.import_file(b, clash) == ["By cost type (imported)"]
    bad = tmp_path / "bad.json"
    bad.write_text('{"hello": 1}', encoding="utf-8")
    with pytest.raises(L.LayoutError):
        L.import_file(b, str(bad))


def test_unknown_settings_fall_back_to_defaults():
    lay = L.normalize({"name": " x ", "group_by": "nope",
                       "columns": ["total", "bogus", "total"],
                       "filters": {"div_from": "3", "div_to": "99",
                                   "cost_types": ["Material", "Gold"]},
                       "adjustments": "??", "sort": "??"})
    assert lay["group_by"] == "division" and lay["columns"] == ["total"]
    assert lay["filters"] == {"div_from": "03", "div_to": "",
                              "cost_types": ["Material"]}
    assert lay["adjustments"] == "lines" and lay["sort"] == "code"


def test_allocate_shares_add_up_exactly():
    rnd = random.Random(7)
    for _ in range(300):
        n = rnd.randint(1, 12)
        w = [Decimal(rnd.randint(0, 100000)) / 100 for _ in range(n)]
        amt = Decimal(rnd.randint(-500000, 500000)) / 100
        got = L.allocate(amt, w)
        assert sum(got, Decimal("0.00")) == amt
        assert all(x == x.quantize(Decimal("0.01")) for x in got)


def test_saved_to_csv_excel_and_pdf(tmp_path, monkeypatch):
    import fitz
    import openpyxl
    _location(monkeypatch)
    d = _job()
    b = L.base(d)
    total = dmoney.fmt(b["total"])
    for name in L.BUILTIN_NAMES:
        v = L.view(d, L.find(d, name), b)
        p = EX.save_view_csv(d, str(tmp_path / "v.csv"), v)
        rows = list(csv.reader(open(p, encoding="utf-8-sig")))
        last = [r for r in rows if r and r[0] == "total"][0]
        assert last[1] == "Grand total" and last[-1] == str(b["total"])
        x = EX.save_view_xlsx(d, str(tmp_path / "v.xlsx"), v)
        ws = openpyxl.load_workbook(x).active
        vals = list(ws.iter_rows(values_only=True))
        grand = [r for r in vals if r and r[0] == "Grand total"][0]
        assert Decimal(str(grand[-1])) == b["total"]
        pdf = EX.save_view_pdf(d, str(tmp_path / "v.pdf"), v)
        text = "".join(pg.get_text() for pg in fitz.open(pdf))
        assert total in text and name in text


def test_export_dialog_layout_picker(win, tmp_path, monkeypatch):
    from app.estimate_ui import ExportEstimateDialog
    _location(monkeypatch, "0")
    doc = win._view.doc
    EL.add(doc, [EL.new_line("Test slab", 1000, "sf", code="03 31 13",
                             mat="2.50"),
                 EL.new_line("Test allowance", 1, "ls", code="26 00 00",
                             cost_type="Allowance", sub=500)])
    win.estimate.refresh()
    dlg = win.export_my_estimate(show=False)
    assert isinstance(dlg, ExportEstimateDialog)
    names = dlg.layout_names()
    assert names[0] == dlg.STANDARD and "Owner presentation" in names
    assert dlg.view is None and "$3,000.00" in dlg.total.text()
    v = dlg.set_layout("Budget vs Sub vs Takeoff")
    assert v is not None and not dlg.view_table.isHidden()
    rows = dlg.view_rows()
    assert rows[0][:2] == ["Division 03 - Concrete", "$0.00"]
    assert rows[-1][0] == "Grand total" and rows[-1][-1] == "$3,000.00"
    for fn, ext in ((dlg.save_pdf, "pdf"), (dlg.save_xlsx, "xlsx"),
                    (dlg.save_csv, "csv")):
        p = str(tmp_path / f"layout.{ext}")
        assert fn(p) == p and os.path.getsize(p) > 0
    rows = list(csv.reader(open(str(tmp_path / "layout.csv"),
                                encoding="utf-8-sig")))
    assert ["subtotal", "Division 26 - Electrical", "500.00", "0.00",
            "0.00", "500.00"] in rows
    dlg.set_layout(dlg.STANDARD)
    assert dlg.view is None and dlg.view_table.isHidden()


def test_layouts_dialog_make_save_tag_share(win, tmp_path):
    from app.estimate_ui import LayoutsDialog
    doc = win._view.doc
    EL.add(doc, [EL.new_line("Test slab", 10, "sf", code="03 31 13",
                             mat="2.50")])
    dlg = LayoutsDialog(doc, win)
    dlg.new()
    dlg.name.setText("By phase")
    dlg.group_by.setCurrentIndex(dlg.group_by.findData("tag"))
    for k, b in dlg.col_boxes.items():
        b.setChecked(k in ("qty", "total"))
    lay = dlg.save_current()
    assert lay["name"] == "By phase" and lay["columns"] == ["qty", "total"]
    assert L.find(doc, "By phase")["group_by"] == "tag"
    tags = dlg.tag_lines(show=False)
    tags.set_tag(0, "Phase 2")
    assert list(L.tags(doc).values()) == ["Phase 2"]
    v = L.view(doc, L.find(doc, "By phase"))
    assert [g["label"] for g in v["groups"]] == ["Phase 2"]
    # a built-in can't be overwritten or deleted
    dlg.refresh("By cost type")
    assert dlg.save_current() is None and "built-in" in dlg.msg.text()
    assert not dlg.delete_current()
    p = dlg.export_to(str(tmp_path / "layouts.json"))
    assert p and L.from_json(open(p, encoding="utf-8").read())[0][
        "name"] == "By phase"
    dlg.refresh("By phase")
    assert dlg.delete_current() and L.find(doc, "By phase") is None
    assert dlg.import_from(p) == ["By phase"]
    dlg.close()


def test_layouts_dialog_without_a_document(qapp):
    from app.estimate_ui import ExportEstimateDialog, LayoutsDialog
    dlg = LayoutsDialog(None)
    assert not dlg.save_btn.isEnabled() and dlg.save_current() is None
    assert dlg.list.count() == len(L.BUILTIN_NAMES)
    dlg.close()
    ex = ExportEstimateDialog(None)
    assert ex.set_layout("Owner presentation")["total"] == 0
    assert ex.save_csv() is None
    ex.close()
