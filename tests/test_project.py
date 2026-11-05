"""Step 3 of the Venice modules: drawing register, transmittals, addenda,
punch list and three-phase inspections."""
import os

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import annotate, doccontrol, qa, settings          # noqa: E402
from test_gui import ANSWERS, win, qapp                    # noqa: E402,F401


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)


def _set(path=None):
    d = fitz.open()
    for num, title in (("A-201", "BUILDING SECTIONS"),
                       ("S-101", "FOUNDATION PLAN"),
                       ("A-101", "FLOOR PLAN")):
        p = d.new_page(width=2592, height=1728)
        p.insert_text((2356, 1484), "SHEET TITLE:", fontsize=10)
        p.insert_text((2360, 1512), title, fontsize=22)
        p.insert_text((2380, 1680), num, fontsize=44)
    d.new_page(width=2592, height=1728)          # no title block
    if path:
        d.save(path)
    return d


def _text(path):
    with fitz.open(path) as d:
        return "\n".join(p.get_text() for p in d)


def test_register_revisions_transmittals_addenda(tmp_path):
    d = _set()
    found, missing = doccontrol.scan_register(d)
    assert found == 3 and missing == [3]
    reg = doccontrol.register(d)
    assert [r["number"] for r in reg] == ["S-101", "A-101", "A-201"]
    assert reg[1]["title"] == "FLOOR PLAN" and reg[1]["page"] == 2
    assert reg[0]["discipline"] == "Structural"
    assert doccontrol.discipline_of("FP-101") == "Fire Protection"
    doccontrol.set_sheet(d, "A-101", title="FIRST FLOOR PLAN")
    doccontrol.scan_register(d)                     # typed title kept
    assert doccontrol.register(d)[1]["title"] == "FIRST FLOOR PLAN"
    doccontrol.add_revision(d, ["A-101", "A-201"], "1", "2026-03-02",
                            "Addendum 1")
    doccontrol.add_revision(d, "A-101", "2", "2026-04-10", "ASI 3")
    a101 = doccontrol.register(d)[1]
    assert a101["rev"] == "2" and len(a101["revs"]) == 2
    with pytest.raises(doccontrol.DocControlError):
        doccontrol.add_revision(d, "Z-999", "1")
    with pytest.raises(doccontrol.DocControlError):
        doccontrol.add_revision(d, "A-101", " ")

    items = doccontrol.items_for_sheets(d, ["A-101", "a-201"])
    assert [(i["doc"], i["rev"]) for i in items] == [("A-101", "2"),
                                                     ("A-201", "1")]
    with pytest.raises(doccontrol.DocControlError):
        doccontrol.new_transmittal(d, "", items)
    with pytest.raises(doccontrol.DocControlError):
        doccontrol.new_transmittal(d, "Owner", [{"doc": " "}])
    tid = doccontrol.new_transmittal(d, "Smith Architects", items,
                                     "For approval", due="2026-01-01")
    assert tid == "TR-001"
    late = doccontrol.awaiting(d, today="2026-02-01")
    assert late[0][0]["id"] == tid and late[0][1] is True
    doccontrol.acknowledge(d, tid, "J. Smith", "2026-01-03")
    assert doccontrol.awaiting(d) == []

    aid = doccontrol.add_addendum(d, "Revised door hardware",
                                  "2026-03-02", "Hardware sets revised",
                                  ["A-101"], ["Acme", "Beta Builders"])
    doccontrol.ack_addendum(d, aid, "Acme")
    assert doccontrol.unacknowledged(d) == {aid: ["Beta Builders"]}

    # saved in the PDF; documents render
    path = str(tmp_path / "set.pdf")
    d.save(path)
    d2 = fitz.open(path)
    assert doccontrol.register(d2)[1]["rev"] == "2"
    t = _text(doccontrol.transmittal_pdf(d2, tid, str(tmp_path / "t.pdf"),
                                         "Clinic"))
    assert "Transmittal TR-001" in t and "Smith Architects" in t and \
        "A-201" in t and "J. Smith" in t
    t = _text(doccontrol.register_pdf(d2, str(tmp_path / "r.pdf")))
    assert "FIRST FLOOR PLAN" in t and "ASI 3" in t
    t = _text(doccontrol.addenda_pdf(d2, str(tmp_path / "a.pdf")))
    assert "NOT ACKNOWLEDGED" in t and "Beta Builders" in t
    assert os.path.getsize(doccontrol.register_xlsx(
        d2, str(tmp_path / "r.xlsx"))) > 0


def test_punch_list_with_markers_and_statuses(tmp_path):
    d = _set()
    doccontrol.scan_register(d)
    pid = qa.add_punch(d, "Patch drywall at outlet", "Room 204", "Drywall",
                       "Acme Drywall", "2026-01-10")
    with pytest.raises(qa.QAError):
        qa.add_punch(d, " ")
    ref = qa.pin(d, pid, 2, (500, 400))
    found = annotate.find_annots(d[2], ref)
    assert found and "Patch drywall" in found[0].info["content"]
    assert tuple(round(c, 2) for c in found[0].colors["stroke"]) == \
        qa.PIN_COLOR["open"]
    qa.set_status(d, pid, "ready", "fixed")
    a = annotate.find_annots(d[2], ref)[0]
    assert tuple(round(c, 2) for c in a.colors["stroke"]) == \
        qa.PIN_COLOR["ready"]
    assert "Ready for review" in a.info["content"]
    qa.set_status(d, pid, "open", "not sanded")          # rejected
    qa.set_status(d, pid, "closed")
    assert qa.get_punch(d, pid)["closed"]
    with pytest.raises(qa.QAError):
        qa.set_status(d, pid, "ready")                   # closed -> ready
    assert len(qa.get_punch(d, pid)["history"]) == 4
    p2 = qa.add_punch(d, "Missing cover plate", trade="Electrical",
                      due="2020-01-01")
    s = qa.summary(d)
    assert s["by_status"]["closed"] == 1 and s["overdue"] == 1
    assert s["open_by_trade"] == {"Electrical": 1}
    assert [p["id"] for p in qa.punch(d, open_only=True)] == [p2]
    t = _text(qa.punch_pdf(d, str(tmp_path / "p.pdf")))
    assert "Patch drywall" in t and "A-101" in t and "Closed" in t
    assert os.path.getsize(qa.punch_xlsx(d, str(tmp_path / "p.xlsx"))) > 0


def test_three_phase_inspection_feeds_the_punch_list(tmp_path):
    d = _set()
    iid = qa.new_inspection(d, "initial", "Metal stud framing", "Level 2",
                            "Framing", spec="09 22 16")
    assert len(qa.get_inspection(d, iid)["items"]) == \
        len(qa.TEMPLATES["initial"])
    with pytest.raises(qa.QAError):
        qa.new_inspection(d, "final", "x")
    with pytest.raises(qa.QAError):
        qa.close_inspection(d, iid)                  # unanswered checks
    n = len(qa.get_inspection(d, iid)["items"])
    for k in range(n):
        qa.answer(d, iid, k, "pass")
    qa.answer(d, iid, 1, "fail", "Studs 24\" o.c., need 16\"")
    qa.answer(d, iid, 3, "n/a")
    i = qa.close_inspection(d, iid, due="2026-05-01")
    assert i["status"] == "failed" and len(i["punch"]) == 1
    p = qa.get_punch(d, i["punch"][0])
    assert p["source"] == iid and p["trade"] == "Framing" and \
        "need 16" in p["description"] and p["priority"] == "high"
    with pytest.raises(qa.QAError):
        qa.answer(d, iid, 0, "fail")                  # closed
    nxt = qa.next_phase(d, iid)
    assert qa.get_inspection(d, nxt)["phase"] == "follow-up"
    ok = qa.new_inspection(d, "preparatory", "Roofing", checks=["A", "B"])
    qa.answer(d, ok, 0, "pass")
    qa.answer(d, ok, 1, "pass")
    assert qa.close_inspection(d, ok)["status"] == "passed"
    t = _text(qa.inspection_pdf(d, iid, str(tmp_path / "i.pdf")))
    assert "Initial Phase Inspection" in t and "FAIL" in t and \
        i["punch"][0] in t


def test_project_windows(qapp, win, tmp_path, monkeypatch):
    from app import project_ui
    path = str(tmp_path / "set.pdf")
    _set(path)
    win.open_path(path)
    v = win._view
    dc = win.doc_control(0)
    monkeypatch.setattr(dc, "_open_file", lambda p: None)
    dc.scan()
    assert dc.reg.rowCount() == 3
    dc.reg.selectRow(1)
    assert dc._selected_sheets() == ["A-101"]
    tid = dc.new_transmittal(values={
        "to": "Owner", "items": doccontrol.items_for_sheets(v.doc,
                                                            ["A-101"])})
    assert tid == "TR-001" and dc.trs.rowCount() == 1
    assert dc.new_addendum({"title": "Add 1", "bidders": ["Acme"]})
    assert dc.adds.item(0, 5).text() == "Acme"
    # double-click a sheet goes to its page
    got = []
    dc.go_to.connect(lambda p, r: got.append(p))
    dc._reg_go(dc.reg.item(1, 0))
    assert got == [2]

    q = win.quality(0)
    monkeypatch.setattr(q, "_open_file", lambda p: None)
    pid = q.new_punch({"description": "Touch up paint",
                       "trade": "Painting"}, link="pin")
    p = qa.get_punch(v.doc, pid)
    assert p["page"] == v.page and p["ref"]
    assert annotate.find_annots(v.doc[p["page"]], p["ref"])
    assert q.pl.rowCount() == 1
    q.pl.selectRow(0)
    q._pl_status("ready")
    assert qa.get_punch(v.doc, pid)["status"] == "ready"
    # attach to a selected markup instead
    v.do_op("add_rect", v.page, rect=[100, 100, 300, 200])
    a = list(v.pg.annots())[-1]
    v.select(a)
    pid2 = q.new_punch({"description": "Ceiling tile stained"},
                       link="selected")
    assert qa.get_punch(v.doc, pid2)["ref"] == annotate.ref(a)
    iid = q.new_inspection({"phase": "preparatory", "feature": "Doors",
                            "checks": ["Submittals approved", "Frames on site"]})
    assert iid and q.ins.rowCount() == 1
    dlg = project_ui.ChecklistDialog(q, v.doc, iid)
    dlg.set_result(0, "pass")
    dlg.set_result(1, "fail", "Wrong hand")
    assert dlg.close_inspection()["status"] == "failed"
    q.refresh()
    assert any("Wrong hand" in x["description"] for x in qa.punch(v.doc))
    out = str(tmp_path / "pl.pdf")
    ANSWERS["save"] = out
    assert q._pl_pdf() == out and os.path.exists(out)
    q.close()
    dc.close()
