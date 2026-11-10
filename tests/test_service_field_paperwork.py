"""QuantiSheet 1.2 phase 3 (Nov 5): the phone ticket round trip (fields
kept, as Acrobat Reader saves; flattened, as a phone's built-in viewer
may save), maintenance checklists with readings, the customer
leave-behind report and the plumbing certificates. Made-up data only."""
import fitz
import pytest

from app.service import (certificates, checklists, leave_behind, recommend,
                         ticket_pdf, workorder)
from r111_support import isolate, qapp, records, use_company  # noqa: F401


@pytest.fixture(autouse=True)
def svc_home(tmp_path, monkeypatch):
    use_company(monkeypatch)
    return isolate(tmp_path, monkeypatch)


def _pdf_text(path, page=0):
    with fitz.open(path) as d:
        return d[page].get_text()


def _pdf_fields(path, page=0):
    with fitz.open(path) as d:
        return {w.field_name: w.field_value for w in d[page].widgets() or []}


def _wo():
    rec, prop, eq = records()
    st = workorder.blank()
    workorder.set_rates(st, "100", "40")
    w = workorder.add(st, rec, property_id=prop, equipment_id=eq,
                      complaint="No heat", tech="A Tester", when="2026-11-02")
    return rec, eq, st, w


def _fill(src, dst, values, flatten=False, drop_meta=False):
    doc = fitz.open(src)
    page = doc[0]
    for w in list(page.widgets()):
        if w.field_name in values:
            v = values[w.field_name]
            if w.field_type == fitz.PDF_WIDGET_TYPE_CHECKBOX:
                w.field_value = w.on_state() if v else "Off"
            else:
                w.field_value = v
            w.update()
        del w                   # no widget may outlive its document
    del page
    if drop_meta:
        doc.set_metadata({})
    if flatten:
        doc.bake()
    doc.save(dst)
    doc.close()
    return dst


VALUES = {"t_date": "2026-11-03", "t_tech1": "A Tester", "t_hours1": "1.5",
          "t_tech2": "B Tester", "t_hours2": "0.5", "t_qty1": "2",
          "t_part1": "Test flame sensor", "t_work": "Cleaned the flame "
          "sensor, checked the burners.", "t_signed": "Test Smith",
          "t_complete": True}


def test_ticket_round_trip_with_fields_and_twice(tmp_path):
    _rec, _eq, st, w = _wo()
    out = ticket_pdf.make(st, w, str(tmp_path / "t.pdf"))
    assert f"QS-{out['token']}" in _pdf_text(out["path"])
    back = _fill(out["path"], str(tmp_path / "back.pdf"), VALUES)
    ret = ticket_pdf.read(st, back)
    assert ret["how"] == "fields" and ret["wo_id"] == w
    assert ret["values"]["t_complete"] is True
    got = ticket_pdf.apply(st, ret)
    wo = workorder.get(st, w)
    assert [(t["tech"], t["hours"], t["date"]) for t in wo["time"]] == \
        [("A Tester", "1.50", "2026-11-03"), ("B Tester", "0.50",
                                              "2026-11-03")]
    assert wo["parts"][0]["desc"] == "Test flame sensor" and \
        wo["parts"][0]["price_needed"]
    assert "Cleaned the flame sensor" in wo["notes"]
    assert wo["signed_by"] == "Test Smith"
    # back again, same: nothing added
    assert ticket_pdf.apply(st, ticket_pdf.read(st, back))["same"]
    assert len(wo["time"]) == 2
    # back again, different (a second tech's copy): the office decides
    other = _fill(out["path"], str(tmp_path / "b2.pdf"),
                  dict(VALUES, t_hours1="2", t_tech2="", t_hours2=""))
    ret2 = ticket_pdf.read(st, other)
    with pytest.raises(ticket_pdf.TicketConflict) as e:
        ticket_pdf.apply(st, ret2)
    assert "t_hours1" in e.value.diff
    ticket_pdf.apply(st, ret2, replace=True)
    assert [(t["tech"], t["hours"]) for t in wo["time"]] == \
        [("A Tester", "2.00")]
    assert len(wo["parts"]) == 1                    # replaced, not doubled


def test_flattened_ticket_is_read_from_its_boxes(tmp_path):
    _rec, _eq, st, w = _wo()
    out = ticket_pdf.make(st, w, str(tmp_path / "t.pdf"))
    flat = _fill(out["path"], str(tmp_path / "flat.pdf"), VALUES,
                 flatten=True, drop_meta=True)
    assert not _pdf_fields(flat)
    ret = ticket_pdf.read(st, flat)
    assert ret["how"] == "flattened"
    assert ret["values"]["t_hours1"] == "1.5"
    assert ret["values"]["t_part1"] == "Test flame sensor"
    assert "Work complete" in ret["unread"]         # a check box: asked
    assert "flattened" in ret["note"]
    ticket_pdf.apply(st, ret)
    assert len(workorder.get(st, w)["time"]) == 2


def test_tickets_refuse_what_they_should(tmp_path):
    _rec, _eq, st, w = _wo()
    plain = fitz.open()
    plain.new_page().insert_text((72, 72), "Some other PDF")
    plain.save(str(tmp_path / "x.pdf"))
    plain.close()
    with pytest.raises(ticket_pdf.TicketError):
        ticket_pdf.read(st, str(tmp_path / "x.pdf"))
    out = ticket_pdf.make(st, w, str(tmp_path / "t.pdf"))
    bad = _fill(out["path"], str(tmp_path / "bad.pdf"),
                {"t_tech1": "A Tester", "t_hours1": "lots"})
    with pytest.raises(ticket_pdf.TicketError):
        ticket_pdf.apply(st, ticket_pdf.read(st, bad))
    assert workorder.get(st, w)["time"] == []       # nothing half-added
    other = workorder.blank()
    with pytest.raises(ticket_pdf.TicketError):
        ticket_pdf.read(other, out["path"])         # not this office's


def test_checklist_readings_trend_and_watch(tmp_path):
    _rec, eq, _st, _w = _wo()
    tp = checklists.templates()
    for it in tp["cooling"]["items"]:
        if it["key"] == "suction":
            it["low"], it["high"] = "100", "150"
    checklists.save_templates(tp)
    store = checklists.blank()
    checklists.record(store, "cooling", {"filter": "done", "suction": "118"},
                      equipment_id=eq, when="2026-04-01")
    checklists.record(store, "cooling", {"filter": "done", "suction": "95.5"},
                      equipment_id=eq, when="2026-10-01")
    pts = checklists.trend(store, eq, "suction")
    assert [(d, v) for d, v, _u, _w in pts] == [("2026-04-01", "118"),
                                                ("2026-10-01", "95.5")]
    assert pts[-1][3] == "check (low)"
    assert checklists.change_text(pts) == "down 22.5 psig since 2026-04-01"
    with pytest.raises(checklists.ChecklistError):
        checklists.record(store, "cooling", {"suction": "high"},
                          equipment_id=eq)
    with pytest.raises(checklists.ChecklistError):
        checklists.record(store, "cooling", {"filter": "maybe"},
                          equipment_id=eq)
    p = checklists.printable_pdf("heating", str(tmp_path / "c.pdf"))
    names = set(_pdf_fields(p))
    assert {"c_gas_in", "c_burners", "c_notes"} <= names


def test_leave_behind_has_work_readings_photos_and_recommendations(
        tmp_path):
    rec, eq, st, w = _wo()
    workorder.add_time(st, w, "A Tester", "1", when="2026-10-01")
    workorder.add_part(st, w, "Test igniter", "1", cost="20", price="45")
    workorder.set_notes(st, w, "Replaced the igniter.")
    cl = checklists.blank()
    checklists.record(cl, "heating", {"gas_in": "7.0"}, equipment_id=eq,
                      when="2026-04-01")
    checklists.record(cl, "heating", {"gas_in": "6.5", "burners": "done"},
                      equipment_id=eq, work_order_id=w, when="2026-10-01")
    rs = recommend.blank()
    recommend.add(rs, rec, eq, note="Replace the test blower motor soon",
                  price="420")
    path = leave_behind.pdf(st, w, str(tmp_path / "lb.pdf"),
                            checklist_store=cl, rec_store=rs)
    text = _pdf_text(path)
    for want in ("Service Visit Report", "Replaced the igniter",
                 "Test igniter", "Inlet gas pressure: 6.5",
                 "down 0.5 in. w.c. since 2026-04-01",
                 "Replace the test blower motor soon", "$420.00",
                 "Test Plumbing Co"):
        assert want in text, want
    assert "Cost" not in text and "Profit" not in text


def test_certificates_fill_from_the_ticket_and_go_in_the_library(tmp_path):
    from app import formlib
    _rec, _eq, st, w = _wo()
    wo = workorder.get(st, w)
    for kind in certificates.KINDS:
        p = certificates.pdf(kind, str(tmp_path / f"{kind}.pdf"), wo=wo)
        vals = _pdf_fields(p)
        assert vals["c_wo"] == wo["number"] and vals["c_tech"] == "A Tester"
        assert "not a code determination" in _pdf_text(p)
    assert "g_req_pressure" in _pdf_fields(str(tmp_path / "gas_test.pdf"))
    assert len(certificates.install_templates()) == 2
    assert certificates.install_templates() == []          # once
    names = {e["name"] for e in formlib.entries()
             if e["category"] == "Plumbing"}
    assert names == set(certificates.KINDS.values())


def test_windows(qapp, tmp_path):
    from app.estimating import service
    from app.service import checklists_ui, workorder_ui
    rec, eq, st, w = _wo()
    service.save(rec)
    workorder.save(st)
    win = workorder_ui.WorkOrderWindow()
    win.table.selectRow(0)
    out = win.ticket_clicked(path=str(tmp_path / "t.pdf"))
    back = _fill(out["path"], str(tmp_path / "back.pdf"), VALUES)
    got = win.readback_clicked(path=back, ask=lambda *a: True)
    assert len(got["added_time"]) == 2 and "need a price" in win.msg.text()
    win.table.selectRow(0)
    assert win.leave_clicked(path=str(tmp_path / "lb.pdf"))
    assert win.cert_clicked(kind="drain_camera",
                            path=str(tmp_path / "dc.pdf"))
    cw = win.checklist_clicked()
    assert cw.unit.currentData() == eq
    cw.template.setCurrentIndex(cw.template.findData("cooling"))
    row = [i["key"] for i in cw.items()].index("suction")
    cw.table.item(row, 1).setText("120")
    assert cw.save_clicked()
    assert "120" in cw.show_trend(row)
    cw.close()
    win.close()
