"""Master Schedule: the Excel update template (generate / read / HMAC)."""
import datetime as dt
import os

import openpyxl
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.pm.master import model                                 # noqa: E402
from app.pm.master.formats import excel                         # noqa: E402
from r39_master_fixtures import (ACME, BEST, CYCLE, act, fill,  # noqa: E402
                                 make_store)


def _tpl(s, tmp_path, company=ACME, name="acme.xlsx"):
    return excel.generate(s, company, str(tmp_path / name), cycle=CYCLE)


def test_template_layout(tmp_path, monkeypatch):
    s = make_store(tmp_path, monkeypatch)
    p = _tpl(s, tmp_path)
    wb = openpyxl.load_workbook(p)
    assert wb.sheetnames == ["Update", "New activities", "_qs"]
    assert wb["_qs"].sheet_state == "veryHidden"
    ws = wb["Update"]
    assert [c.value for c in ws[1]] == list(excel.UPDATE_COLS)
    nos = [r[0].value for r in ws.iter_rows(min_row=2)]
    # the sub's own rows, then shaded read-only context rows (immediate
    # predecessors / successors from other trades and the GC)
    assert nos[:2] == ["A0002", "A0005"]
    assert set(nos[2:]) == {"A0001", "A0004", "A0006"}
    assert ws.protection.sheet
    own = ws[2]
    edit = {excel.UPDATE_COLS[i] for i, c in enumerate(own)
            if not c.protection.locked}
    assert edit == set(excel.EDITABLE)
    ctx = ws[4]
    assert all(c.protection.locked for c in ctx)
    assert ws["K2"].value == 20
    assert ws["L2"].value.date() == dt.date(2026, 11, 4)
    # the issue is recorded for the three-way compare
    iss = model.config(s)["issued"]
    assert iss[-1]["company"] == ACME and iss[-1]["cycle"] == CYCLE


def test_round_trip_no_edits(tmp_path, monkeypatch):
    s = make_store(tmp_path, monkeypatch)
    p = _tpl(s, tmp_path)
    r = excel.read(s, p)
    assert r["errors"] == [] and r["warnings"] == []
    assert r["meta"]["company"] == ACME and r["meta"]["cycle"] == CYCLE
    own = [x for x in r["rows"] if not x["ctx"]]
    assert [x["no"] for x in own] == ["A0002", "A0005"]
    a2 = own[0]
    assert a2["key"] == act(s, "A0002")["_id"]
    assert a2["values"] == a2["base"]           # nothing changed
    assert r["new"] == []


def test_edits_text_and_serial_dates(tmp_path, monkeypatch):
    s = make_store(tmp_path, monkeypatch)
    p = _tpl(s, tmp_path)
    fill(p, {"A0002": {"% complete": 60, "Actual start": "11/04/2026",
                       "Note": "Level 2 done"},
             "A0005": {"Actual start": 46330}})       # Excel serial
    r = excel.read(s, p)
    own = {x["no"]: x for x in r["rows"]}
    assert own["A0002"]["values"]["percent"] == 60
    assert own["A0002"]["values"]["actual_start"] == "2026-11-04"
    assert own["A0002"]["values"]["note"] == "Level 2 done"
    assert own["A0005"]["values"]["actual_start"] == "2026-11-04"


def test_hmac_catches_edited_hidden_sheet(tmp_path, monkeypatch):
    s = make_store(tmp_path, monkeypatch)
    p = _tpl(s, tmp_path)
    wb = openpyxl.load_workbook(p)
    q = wb["_qs"]
    q["A2"].value = q["A2"].value.replace(ACME, BEST)
    wb.save(p)
    r = excel.read(s, p)
    assert any("changed" in e["text"] and "template" in e["text"].lower()
               for e in r["errors"])


def test_edited_activity_number_is_rejected(tmp_path, monkeypatch):
    s = make_store(tmp_path, monkeypatch)
    p = _tpl(s, tmp_path)
    wb = openpyxl.load_workbook(p)
    wb["Update"]["A3"].value = "A0003"         # swap to another trade's
    wb.save(p)
    r = excel.read(s, p)
    assert any(e["where"] == "Update!A3" for e in r["errors"])


def test_new_activities_sheet(tmp_path, monkeypatch):
    s = make_store(tmp_path, monkeypatch)
    p = _tpl(s, tmp_path)
    wb = openpyxl.load_workbook(p)
    assert [c.value for c in wb["New activities"][1]] == \
        list(excel.NEW_COLS)
    fill(p, new=[("Pull wire L1", 2, "A0002", "crew B"),
                 ("Pull wire L2", 2.5, "A0002", "")])
    r = excel.read(s, p)
    assert [(n["name"], n["duration"], n["parent_no"]) for n in r["new"]] \
        == [("Pull wire L1", 2, "A0002"), ("Pull wire L2", 2.5, "A0002")]


def test_not_xlsx_rejected(tmp_path, monkeypatch):
    s = make_store(tmp_path, monkeypatch)
    for name, data in (("x.xlsm", b"PK\x03\x04junk"), ("x.xls", b"\xd0\xcf"),
                       ("x.xlsx", b"not a zip at all")):
        p = tmp_path / name
        p.write_bytes(data)
        r = excel.read(s, str(p))
        assert r["errors"], name


def test_template_from_someone_elses_key(tmp_path, monkeypatch):
    s = make_store(tmp_path, monkeypatch)
    p = _tpl(s, tmp_path)
    other = make_store(tmp_path, monkeypatch, name="other")
    r = excel.read(other, p)
    assert r["errors"]                # other project: HMAC / project fail


def test_size_and_row_caps(tmp_path, monkeypatch):
    s = make_store(tmp_path, monkeypatch)
    p = _tpl(s, tmp_path)
    monkeypatch.setattr(excel, "MAX_BYTES", 100)
    r = excel.read(s, p)
    assert any("too big" in e["text"] for e in r["errors"])
