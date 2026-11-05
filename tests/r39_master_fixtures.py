"""Shared made-up job for the r39 Master Schedule tests (no real data).

Data date / cycle Thursday 2026-11-05. Holidays: Thanksgiving.
  A0001 Mobilize                 GC    2d  done Nov 2-3
  A0002 Rough-in electrical      Acme  5d  started Nov 4, 20 %
  A0003 Rough-in plumbing        Best  3d  not started (1 day of float)
  A0004 Inspection               GC    1d  after A0002, A0003
  A0005 Trim electrical          Acme  3d  after A0004
  A0006 Substantial Completion   GC    0d  after A0005
"""
import os

from app import settings
from app.pm.store import ProjectStore

CYCLE = "2026-11-05"
ACME = "Acme Electric"
BEST = "Best Plumbing"


def make_store(tmp_path, monkeypatch, name="job"):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {"author": "Jon Test"})
    s = ProjectStore(str(tmp_path / name))
    s.set_setting("holidays", ["2026-11-26"])
    s.set_setting("data_date", CYCLE)
    s.save_record("member", {"name": "Ann Volt", "company": ACME,
                             "email": "ann@acme.example", "role":
                             "Subcontractor"})
    s.save_record("member", {"name": "Bo Pipe", "company": BEST,
                             "email": "bo@best.example", "role":
                             "Subcontractor"})
    add = lambda **r: s.save_record("activity", r)       # noqa: E731
    add(name="Mobilize", duration=2, start="2026-11-02",
        actual_start="2026-11-02", actual_finish="2026-11-03", percent=100,
        status="Complete")
    add(name="Rough-in electrical", duration=5, preds=[{"id": "A0001"}],
        owner_co=ACME, responsible="Ann Volt", actual_start="2026-11-04",
        percent=20, status="In Progress")
    add(name="Rough-in plumbing", duration=3, preds=[{"id": "A0001"}],
        owner_co=BEST, responsible="Bo Pipe")
    add(name="Inspection", duration=1,
        preds=[{"id": "A0002"}, {"id": "A0003"}])
    add(name="Trim electrical", duration=3, preds=[{"id": "A0004"}],
        owner_co=ACME, responsible="Ann Volt")
    add(name="Substantial Completion", duration=0, preds=[{"id": "A0005"}])
    s.flush()
    return s


def act(s, no):
    return next(a for a in s.list("activity") if a["_no"] == no)


def project_bytes(s):
    s.flush()
    with open(s.path, "rb") as f:
        return f.read()


def fill(path, edits=None, new=None, out=None):
    """Fill a generated template like a sub would: edits {activity no.:
    {column header: value}}, new [(name, duration, inside no., note)]."""
    import openpyxl
    wb = openpyxl.load_workbook(path)
    ws = wb["Update"]
    heads = [c.value for c in ws[1]]
    for row in ws.iter_rows(min_row=2):
        no = row[0].value
        for head, val in (edits or {}).get(no, {}).items():
            row[heads.index(head)].value = val
    if new:
        wn = wb["New activities"]
        r = 2
        for item in new:
            for k, v in enumerate(item, 1):
                wn.cell(row=r, column=k, value=v)
            r += 1
    out = out or path
    wb.save(out)
    return out


# ------------------------------------------------ MS Project XML / P6 XER
TEXT30 = 188744016            # MSPDI FieldID of Text30 (INFERRED constant)


def msp_xml(path, tasks, status_date=CYCLE, minutes_per_day=480,
            holidays=(), doctype=False, define_text30=True, tasks_el=True):
    """A made-up MS Project XML (MSPDI) file. tasks: dicts with uid, name,
    hours, pct, astart, afinish, text30, summary, milestone, preds."""
    from xml.sax.saxutils import escape as x
    out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>']
    if doctype:
        out.append('<!DOCTYPE Project [<!ENTITY a "aaaaaaaaaa">]>')
    out.append('<Project xmlns="http://schemas.microsoft.com/project">')
    out.append("<Name>Sub schedule</Name>")
    if status_date:
        out.append(f"<StatusDate>{status_date}T17:00:00</StatusDate>")
    out.append("<CalendarUID>1</CalendarUID>")
    out.append(f"<MinutesPerDay>{minutes_per_day}</MinutesPerDay>")
    if define_text30:
        out.append("<ExtendedAttributes><ExtendedAttribute>"
                   f"<FieldID>{TEXT30}</FieldID><FieldName>Text30</FieldName>"
                   "<Alias>Master ID</Alias></ExtendedAttribute>"
                   "</ExtendedAttributes>")
    out.append("<Calendars><Calendar><UID>1</UID><Name>Standard</Name>"
               "<IsBaseCalendar>1</IsBaseCalendar>")
    if holidays:
        out.append("<Exceptions>")
        for d in holidays:
            out.append(f"<Exception><TimePeriod><FromDate>{d}T00:00:00"
                       f"</FromDate><ToDate>{d}T23:59:00</ToDate>"
                       "</TimePeriod><DayWorking>0</DayWorking></Exception>")
        out.append("</Exceptions>")
    out.append("</Calendar></Calendars>")
    if tasks_el:
        out.append("<Tasks><Task><UID>0</UID><ID>0</ID><Name>Sub schedule"
                   "</Name><Summary>1</Summary></Task>")
        for t in tasks:
            out.append("<Task>")
            out.append(f"<UID>{t['uid']}</UID><ID>{t['uid']}</ID>"
                       f"<Name>{x(t.get('name', 'Task'))}</Name>")
            out.append(f"<Summary>{1 if t.get('summary') else 0}</Summary>")
            out.append(f"<Milestone>{1 if t.get('milestone') else 0}"
                       "</Milestone>")
            h = t.get("hours", 8)
            hh, mm = int(h), int(round((h - int(h)) * 60))
            out.append(f"<Duration>PT{hh}H{mm}M0S</Duration>")
            out.append(f"<PercentComplete>{t.get('pct', 0)}"
                       "</PercentComplete>")
            if t.get("astart"):
                out.append(f"<ActualStart>{t['astart']}T08:00:00"
                           "</ActualStart>")
            if t.get("afinish"):
                out.append(f"<ActualFinish>{t['afinish']}T17:00:00"
                           "</ActualFinish>")
            for p in t.get("preds") or ():
                out.append("<PredecessorLink><PredecessorUID>"
                           f"{p}</PredecessorUID><Type>1</Type>"
                           "</PredecessorLink>")
            if t.get("text30"):
                out.append(f"<ExtendedAttribute><FieldID>{TEXT30}</FieldID>"
                           f"<Value>{x(t['text30'])}</Value>"
                           "</ExtendedAttribute>")
            out.append("</Task>")
        out.append("</Tasks>")
    out.append("</Project>")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    return str(path)


def xer_text(path, tasks, data_date=CYCLE, code_type="QuantiSheet ID",
             header=True):
    """A made-up P6 XER. tasks: dicts with id, code, name, hours, pct,
    astart, afinish, actv (activity code value), wbs."""
    L = []
    if header:
        L.append("ERMHDR\t19.12\t2026-11-05\tProject\tadmin\tdbx\tProject "
                 "Management\tUSD")
    L += ["%T\tPROJECT", "%F\tproj_id\tproj_short_name\tlast_recalc_date",
          f"%R\t1\tSUBJOB\t{data_date} 17:00" if data_date else
          "%R\t1\tSUBJOB\t"]
    L += ["%T\tPROJWBS", "%F\twbs_id\tproj_id\twbs_name",
          "%R\t10\t1\tElectrical"]
    L += ["%T\tTASK", "%F\ttask_id\tproj_id\twbs_id\ttask_code\ttask_name"
          "\ttask_type\ttarget_drtn_hr_cnt\tphys_complete_pct"
          "\tact_start_date\tact_end_date\tstatus_code"]
    for t in tasks:
        L.append("\t".join(["%R", str(t["id"]), "1", "10", t["code"],
                            t.get("name", "Task"),
                            t.get("type", "TT_Task"),
                            str(t.get("hours", 8)), str(t.get("pct", 0)),
                            (t.get("astart") or "") and t["astart"] +
                            " 08:00",
                            (t.get("afinish") or "") and t["afinish"] +
                            " 17:00",
                            "TK_NotStart"]))
    codes = [t for t in tasks if t.get("actv")]
    if codes:
        L += ["%T\tACTVTYPE", "%F\tactv_code_type_id\tactv_code_type",
              f"%R\t500\t{code_type}"]
        L += ["%T\tACTVCODE", "%F\tactv_code_id\tactv_code_type_id"
              "\tshort_name\tactv_code_name"]
        for k, t in enumerate(codes):
            L.append(f"%R\t{900 + k}\t500\t{t['actv']}\t{t['actv']}")
        L += ["%T\tTASKACTV", "%F\ttask_id\tactv_code_type_id"
              "\tactv_code_id\tproj_id"]
        for k, t in enumerate(codes):
            L.append(f"%R\t{t['id']}\t500\t{900 + k}\t1")
    L.append("%E")
    with open(path, "w", encoding="cp1252", newline="\r\n") as f:
        f.write("\n".join(L) + "\n")
    return str(path)
