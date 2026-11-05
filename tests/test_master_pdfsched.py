"""Master Schedule: a sub's update sent as a schedule printed to PDF
(P6 and MS Project layouts, like Jon's examples). Made-up data only."""
import datetime as dt
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz                                                       # noqa: E402

from app.pm.master import apply                                   # noqa: E402
from app.pm.master.formats import pdfsched                        # noqa: E402
from r39_master_fixtures import ACME, act, make_store             # noqa: E402

# column x of each heading on the made-up P6 printout
P6 = {"id": 30, "name": 110, "orig": 330, "rem": 380, "start": 430,
      "finish": 510}


def _p6_pdf(path, rows, data_date="05-Nov-26"):
    doc = fitz.open()
    pg = doc.new_page(width=1200, height=600)

    def put(x, y, t):
        pg.insert_text((x, y), t, fontsize=7)
    put(P6["id"], 40, "Activity ID")
    put(P6["name"], 40, "Activity Name")
    put(P6["orig"], 40, "Original")
    put(P6["rem"], 40, "Remaining")
    put(P6["start"], 40, "Start")
    put(P6["finish"], 40, "Finish")
    put(P6["orig"], 48, "Duration")
    put(P6["rem"], 48, "Duration")
    y = 70
    for r in rows:
        if r.get("band"):
            put(40, y, r["band"])                 # a WBS band: no ID
            put(P6["orig"], y, "30")
            put(P6["rem"], y, "20")
            put(P6["start"], y, "02-Nov-26 A")
            put(P6["finish"], y, "30-Nov-26")
        else:
            put(P6["id"], y, r["id"])
            put(P6["name"], y, r["name"])
            put(P6["orig"], y, str(r["orig"]))
            put(P6["rem"], y, str(r["rem"]))
            put(P6["start"], y, r["start"])
            put(P6["finish"], y, r["finish"])
            put(700, y, r["name"])                # the bar label: ignored
        y += 14
    put(900, 580, f"Data Date: {data_date}")
    doc.save(str(path))
    return str(path)


@pytest.fixture
def s(tmp_path, monkeypatch):
    return make_store(tmp_path, monkeypatch)


def test_p6_printout_is_read_and_matched(s, tmp_path):
    p = _p6_pdf(tmp_path / "acme.pdf", [
        {"band": "Electrical"},
        {"id": "A0002", "name": "Rough-in electrical", "orig": 5, "rem": 2,
         "start": "04-Nov-26 A", "finish": "09-Nov-26"},
        {"id": "A0005", "name": "Trim electrical", "orig": 3, "rem": 3,
         "start": "12-Nov-26", "finish": "16-Nov-26"}])
    sub = apply.receive(s, p, ACME, channel="manual")
    assert sub["format"] == "pdf"
    assert sub["status"] in ("Pending review", "Auto-accepted"), \
        sub.get("reasons")
    rows = {r["no"]: r["values"] for r in sub["rows"]}
    assert set(rows) == {"A0002", "A0005"}
    assert rows["A0002"]["percent"] == 60          # (5 - 2) / 5
    assert rows["A0002"]["actual_start"] == "2026-11-04"
    assert rows["A0005"]["duration"] == 3
    assert any("worked out from the original" in w["text"]
               for w in sub.get("warnings", []))
    assert act(s, "A0005")["duration"] == 3


def test_a_pdf_with_no_schedule_table_is_rejected(s, tmp_path):
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "Cover letter - see attached")
    p = str(tmp_path / "letter.pdf")
    doc.save(p)
    sub = apply.receive(s, p, ACME, channel="manual")
    assert sub["status"] == "Rejected"
    assert any("No schedule table" in r["text"] for r in sub["reasons"])


def _w(x, y, t):
    return (x, y - 4, x + 6 * len(t), y + 4, t, 0, 0, 0)


def test_ms_project_printout_layout_skips_summary_tasks():
    words = []
    for x, t in ((10, "ID"), (40, "Task"), (64, "Name"), (400, "Duration"),
                 (460, "Start"), (540, "Finish")):
        words.append(_w(x, 20, t))
    rows = [(1, 40, "Project", "380 days", "6/2/25", "6/16/26"),
            (2, 50, "Notice of Award", "1 day", "6/2/25", "6/2/25"),
            (3, 50, "Mobilize", "10 days?", "6/6/25", "6/15/25")]
    y = 40
    for i, x, name, dur, a, b in rows:
        words.append(_w(10, y, str(i)))
        for k, part in enumerate(name.split()):
            words.append(_w(x + 40 * k, y, part))
        for k, part in enumerate(dur.split()):
            words.append(_w(400 + 20 * k, y, part))
        words += [_w(460, y, "Mon"), _w(480, y, a), _w(540, y, "Tue"),
                  _w(560, y, b)]
        y += 12
    parsed = pdfsched.read_pages([words])
    assert parsed["layout"] == "msp"
    acts = pdfsched.activities(parsed)
    assert [r["id"] for r in acts] == ["2", "3"]       # 1 is a summary
    assert acts[1]["orig"] == 10 and acts[1]["finish"] == dt.date(2025, 6,
                                                                  15)


def test_p6_dates_and_wrapped_names():
    assert pdfsched.p6_date("16-Jun-25") == dt.date(2025, 6, 16)
    assert pdfsched.p6_date("05-Jan-26*") == dt.date(2026, 1, 5)
    assert pdfsched.msp_date("6/2/25") == dt.date(2025, 6, 2)
    words = [_w(10, 20, "Activity"), _w(60, 20, "ID"),
             _w(100, 20, "Activity"), _w(150, 20, "Name"),
             _w(300, 20, "Original"), _w(350, 20, "Remaining"),
             _w(400, 20, "Start"), _w(470, 20, "Finish"),
             _w(10, 40, "61"), _w(100, 40, "Material"), _w(150, 40,
                                                          "Delivery"),
             _w(300, 40, "120"), _w(350, 40, "42"),
             _w(400, 40, "23-Sep-25"), _w(450, 40, "A"),
             _w(470, 40, "19-Jan-26"),
             _w(100, 52, "Submittals"), _w(160, 52, "-"),
             _w(170, 52, "17"), _w(185, 52, "Weeks")]
    acts = pdfsched.activities(pdfsched.read_pages([words]))
    assert len(acts) == 1
    assert acts[0]["name"] == "Material Delivery Submittals - 17 Weeks"
    assert acts[0]["start_a"] and not acts[0]["finish_a"]


def test_an_mpp_file_is_rejected_with_how_to_save_it_as_xml(s, tmp_path):
    p = tmp_path / "acme.mpp"
    p.write_bytes(b"\xd0\xcf\x11\xe0" + b"\0" * 512)     # an OLE file
    sub = apply.receive(s, str(p), ACME, channel="manual")
    assert sub["status"] == "Rejected"
    assert any("Save As" in r["text"] and "XML" in r["text"]
               for r in sub["reasons"])


def test_approve_lines_preview_and_delay_log(s, tmp_path):
    """Approve only some activities' changes; before/after rows; an
    applied update that slips work goes to the Delay Log once."""
    from app.pm.master import extras, model
    p = _p6_pdf(tmp_path / "acme2.pdf", [
        {"id": "A0002", "name": "Rough-in electrical", "orig": 9, "rem": 6,
         "start": "04-Nov-26 A", "finish": "13-Nov-26"},
        {"id": "A0005", "name": "Trim electrical", "orig": 5, "rem": 5,
         "start": "16-Nov-26", "finish": "20-Nov-26"}])
    sub = apply.receive(s, p, ACME, channel="manual")
    assert sub["status"] == "Pending review"
    rows = extras.preview(s, sub)
    nos = {r["_no"] for r in rows}
    assert {"A0002", "A0005"} <= nos
    assert all(r["after"][1] >= r["before"][1] for r in rows)
    out = extras.approve_lines(s, sub["_id"], keep=["A0002"])
    if out["status"] == "Pending review":          # re-checked: again
        out = extras.approve_lines(s, sub["_id"], keep=["A0002"])
    assert out["status"] == "Approved", out.get("reasons")
    assert act(s, "A0002")["duration"] == 9
    assert act(s, "A0005")["duration"] == 3        # not ticked: kept
    rec = extras.to_delay_log(s, out["_id"])
    assert rec is not None and rec["status"] == "Open"
    assert any(a["id"] == "A0002" for a in rec["affected"])
    with pytest.raises(apply.ApplyRefused):
        extras.to_delay_log(s, out["_id"])          # only once
    assert model.label(out)


def test_p6_calendar_days_off_read_from_clndr_data():
    from app.pm.master.formats import xer
    data = ("(0||CalendarData()((0||DaysOfWeek()())(0||Exceptions()("
            "(0||0(d|46352)())(0||1(d|46353)()))))")
    assert xer.calendar_days_off(data) == {"2026-11-26", "2026-11-27"}
