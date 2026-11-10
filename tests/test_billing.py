"""Step 2 of the Venice modules: schedule of values, pay applications
(G702/G703), change orders PCO -> COR -> CO, lien waivers."""
import os

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import annotate, assemblies, money, proposal, settings  # noqa: E402
from test_gui import ANSWERS, win, qapp                    # noqa: E402,F401

DOOR = "Door - Hollow Metal Frame & Wood Door"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(assemblies, "LIBRARY_PATH",
                        str(tmp_path / "assemblies.json"))
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)


def _contract():
    d = fitz.open()
    d.new_page()
    money.set_info(d, 10, 10, project="Main St Clinic", owner="City",
                   contractor="Acme Builders")
    money.set_sov(d, [{"desc": "Sitework", "scheduled": 10000},
                      {"desc": "Concrete", "csi": "033000",
                       "scheduled": 50000},
                      {"desc": "Drywall", "scheduled": 40000}])
    return d


def _text(path):
    with fitz.open(path) as d:
        return "\n".join(p.get_text() for p in d), d.page_count


def test_pay_apps_retainage_change_orders_and_history(tmp_path):
    d = _contract()
    assert [l["item"] for l in money.sov(d)] == ["1", "2", "3"]
    assert money.sov(d)[1]["csi"] == "03 30 00"
    no = money.new_pay_app(d, "2026-01-31")
    money.set_progress(d, no, "1", work=10000)
    money.set_progress(d, no, "2", percent=20)
    money.set_progress(d, no, "3", stored=5000)
    v = money.compute(d, no)
    g = v["g702"]
    assert g["1"] == 100000 and g["2"] == 0 and g["3"] == 100000
    assert g["4"] == 25000 and g["5a"] == 2000 and g["5b"] == 500
    assert g["6"] == 22500 and g["7"] == 0 and g["8"] == 22500
    assert g["9"] == 77500
    with pytest.raises(money.BillingError):
        money.new_pay_app(d, "2026-02-28")         # draft still open
    money.certify(d, no)
    with pytest.raises(money.BillingError):
        money.set_progress(d, no, "1", work=1)
    with pytest.raises(money.BillingError):
        money.new_pay_app(d, "2026-01-15")         # before the last period
    with pytest.raises(money.BillingError):         # billed line re-valued
        money.set_sov(d, [{"desc": "Sitework", "scheduled": 9000},
                          {"desc": "Concrete", "scheduled": 50000},
                          {"desc": "Drywall", "scheduled": 40000}])

    # a change: PCO -> COR -> CO, then on the SOV
    cid = money.new_change(d, "Add door at corridor", amount=1150, days=2,
                           cost=1000, markup_pct=15, rfi="RFI-004")
    assert cid == "PCO-001"
    assert money.submit(d, cid)["cor_no"] == "COR-001"
    co = money.execute(d, cid, date="2026-02-10")
    assert co["co_no"] == "CO-001" and co["approved_amount"] == 1150
    assert money.sov(d)[-1]["item"] == "CO-001"
    with pytest.raises(money.BillingError):
        money.execute(d, cid)
    with pytest.raises(money.BillingError):
        money.reject(d, cid)
    with pytest.raises(money.BillingError):
        money.update_change(d, cid, amount=5)
    money.reject(d, money.new_change(d, "Owner idea", amount=500))

    # the certified application doesn't move
    assert money.compute(d, no)["g702"] == g

    no2 = money.new_pay_app(d, "2026-02-28")
    v2 = money.compute(d, no2)
    assert {r["item"]: r["stored"] for r in v2["rows"]}["3"] == 5000
    money.set_progress(d, no2, "2", work=15000)
    money.set_progress(d, no2, "3", work=20000, stored=0)
    money.set_progress(d, no2, "CO-001", percent=100)
    v2 = money.compute(d, no2)
    g2 = v2["g702"]
    assert g2["1"] == 100000 and g2["2"] == 1150 and g2["3"] == 101150
    assert g2["4"] == 56150 and g2["5"] == 5615 and g2["6"] == 50535
    assert g2["7"] == 22500 and g2["8"] == 28035 and g2["9"] == 50615
    assert v2["changes"]["this_add"] == 1150 and \
        v2["changes"]["prev_add"] == 0
    assert not v2["warnings"]
    money.set_progress(d, no2, "1", work=500)       # past 100%
    assert any("past 100%" in w for w in money.compute(d, no2)["warnings"])
    money.set_progress(d, no2, "1", work=0)

    # final retainage release
    money.set_retainage(d, no2, 0, 0)
    assert money.compute(d, no2)["g702"]["5"] == 0

    # saved in the PDF, and the documents render
    path = str(tmp_path / "job.pdf")
    d.save(path)
    d2 = fitz.open(path)
    assert money.compute(d2, no2)["g702"]["8"] == pytest.approx(56150 -
                                                               22500)
    pdf = money.pay_app_pdf(d2, no, str(tmp_path / "pa1.pdf"))
    text, pages = _text(pdf)
    assert pages >= 2 and "CONTINUATION SHEET" in text
    assert "$22,500.00" in text and "Main St Clinic" in text
    assert "Concrete" in text and "GRAND TOTALS" in text     # G703 cells
    xl = money.pay_app_xlsx(d2, no2, str(tmp_path / "pa2.xlsx"))
    assert os.path.getsize(xl) > 0
    text, _ = _text(money.change_pdf(d2, "CO-001", str(tmp_path / "co.pdf")))
    assert "CHANGE ORDER" in text and "$1,150.00" in text and \
        "$101,150.00" in text
    assert os.path.getsize(money.change_log_xlsx(
        d2, str(tmp_path / "log.xlsx"))) > 0
    rec = money.waiver(d2, "conditional_progress", "2026-01-31", 22500,
                       app_no=1)
    assert rec["claimant"] == "Acme Builders" and rec["payer"] == "City"
    text, _ = _text(money.waiver_pdf(d2, rec, str(tmp_path / "w.pdf")))
    assert "$22,500.00" in text and "statutory" in text
    with pytest.raises(money.BillingError):
        money.waiver(d2, "bogus", "2026-01-31", 1)


def test_change_executed_after_the_period_is_left_out():
    d = _contract()
    no = money.new_pay_app(d, "2026-01-31")
    cid = money.new_change(d, "Late change", amount=-2000)
    money.execute(d, cid, date="2026-02-05")
    v = money.compute(d, no)
    assert v["g702"]["2"] == 0 and len(v["rows"]) == 3
    money.certify(d, no)
    no2 = money.new_pay_app(d, "2026-02-28")
    v2 = money.compute(d, no2)
    assert v2["g702"]["2"] == -2000 and v2["changes"]["this_deduct"] == 2000


def _takeoff_job():
    d = fitz.open()
    d.new_page(width=2592, height=1728)
    op = annotate.new_op
    annotate.apply_op(d, op("set_scale", 0, ppu=18, unit="ft"))
    for x in (1500, 1600):
        annotate.apply_op(d, op("add_count", 0, pt=[x, 900], n=1,
                                measure={"type": "count", "value": 1,
                                         "unit": "ea", "group": DOOR}))
    annotate.apply_op(d, op("add_polygon", 0,
                            pts=[[100, 100], [100 + 18 * 20, 100],
                                 [100 + 18 * 20, 100 + 18 * 10],
                                 [100, 100 + 18 * 10]],
                            measure={"type": "area", "value": 200,
                                     "unit": "sq ft",
                                     "group": 'Slab on Grade - 4"'}))
    return d


def test_sov_from_estimate_matches_the_proposal_and_markup_pricing():
    d = _takeoff_job()
    bid = proposal.price(d, proposal.read(d))["total"]
    for by in ("trade", "assembly", "csi"):
        lines = money.from_estimate(d, by)
        assert sum(l["scheduled"] for l in lines) == pytest.approx(bid,
                                                                    abs=0.05)
    csi_lines = money.from_estimate(d, "csi")
    assert [l["csi"] for l in csi_lines] == ["03 00 00", "08 00 00"]
    door = [it for it in annotate.takeoff_items(d) if it["group"] == DOOR]
    cost, price, problems = money.price_markups(d, [door[0]["ref"]], 15)
    rows = {r["name"]: r for r in assemblies.rollup(d)[0]}
    assert not problems
    assert cost == pytest.approx(rows[DOOR]["total"] / 2, abs=0.01)
    assert price == pytest.approx(cost * 1.15, abs=0.01)


def test_billing_window(qapp, win, tmp_path, monkeypatch):
    from app.billing_ui import BillingDialog
    d = _takeoff_job()
    path = str(tmp_path / "j.pdf")
    d.save(path)
    win.open_path(path)
    v = win._view
    dlg = win.billing()
    assert isinstance(dlg, BillingDialog) and dlg.doc is v.doc
    monkeypatch.setattr(dlg, "_open_file", lambda p: None)
    dlg.info["project"].setText("Clinic")
    dlg.save_contract()
    assert money.read(v.doc)["info"]["project"] == "Clinic"
    assert dlg._sov_build("assembly")
    dlg.save_sov()
    assert len(money.sov(v.doc)) == 2
    no = dlg._app_new("2026-03-31")
    assert no == 1 and dlg.app.rowCount() == 3
    dlg.app.item(0, 7).setText("50")              # 50% complete
    qapp.processEvents()
    val = money.compute(v.doc, 1)
    # 50% of an odd-cent line is rounded to the cent (proposal prices are
    # whole cents per part since Nov 7), so within a hundredth of a percent
    assert val["rows"][0]["percent"] == pytest.approx(50, abs=0.01)
    assert "Current payment due" in dlg.g702.text()
    dlg._app_certify(confirm=False)
    assert money.pay_apps(v.doc)[0]["status"] == "certified"
    from PySide6.QtCore import Qt
    assert not dlg.app.item(0, 4).flags() & Qt.ItemIsEditable   # locked
    out = dlg._app_pdf(str(tmp_path / "pa.pdf"))
    assert os.path.exists(out)
    # a change from the selected takeoff markup
    door = [it for it in annotate.takeoff_items(v.doc)
            if it["group"] == DOOR][0]
    v.selected = {"ref": door["ref"], "rect": door["rect"],
                  "type": "Polygon"}             # as the viewer sets it
    from app import billing_ui

    class _Fake:
        def __init__(self, parent, change=None, refs=None, cost=None):
            self.vals = {"title": "Extra door", "reason": "", "rfi": "",
                         "amount": round(cost * 1.15, 2), "days": 1,
                         "cost": cost, "markup_pct": 15, "refs": refs}

        def exec(self):
            from PySide6.QtWidgets import QDialog
            return QDialog.Accepted

        def values(self):
            return self.vals
    monkeypatch.setattr(billing_ui, "ChangeDialog", _Fake)
    assert win.change_from_markup()
    ch = money.changes(v.doc)
    assert len(ch) == 1 and ch[0]["refs"] == [door["ref"]] and ch[0]["cost"]
    dlg.cos.setCurrentCell(0, 0)
    dlg._co_execute(amount=ch[0]["amount"])
    assert money.changes(v.doc, "co")
    assert "CO-001" in [l["item"] for l in money.sov(v.doc)]
    out = dlg._waiver_pdf(str(tmp_path / "w.pdf"))
    assert os.path.exists(out)
    dlg.close()
