"""Review round 3 (v35b): crash/data fixes, 3b items and nits."""
import os
import types

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication                       # noqa: E402

from app import forms, revisions, settings, sheets               # noqa: E402
from app.collab import relaycore as rc                           # noqa: E402
from app.pm import bidforms, bidletters, schedule, schema        # noqa: E402
from app.pm.store import ProjectStore                            # noqa: E402


@pytest.fixture
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {"author": "Pat Morgan"})


def test_cell_colors_grey_stays_grey_and_keeps_alpha(qapp, monkeypatch):
    from PySide6.QtGui import QColor
    from app import theme
    monkeypatch.setattr(theme, "is_dark", lambda: True)
    bg, _fg = theme.cell_colors("#e0e0e0")
    assert bg.saturationF() < 0.02                     # not pink/red
    bg, _ = theme.cell_colors(QColor(255, 220, 220, 128).name(
        QColor.HexArgb))
    assert abs(bg.alphaF() - 128 / 255) < 0.01


def test_directory_debounces_big_lists(qapp, monkeypatch, tmp_path):
    from app import subdir, subdir_ui
    monkeypatch.setattr(subdir, "load", lambda: [])
    w = subdir_ui.DirectoryWidget()
    calls = []
    w.refresh = lambda *a: calls.append(1)
    w.contacts = [{}] * (w.DEBOUNCE_OVER + 1)
    for ch in "volt":
        w._typed(ch)
    assert calls == [] and w._typing.isActive()
    w.contacts = []
    w._typed("x")
    assert calls == [1]


def test_fix_numbers_keeps_real_sheet_numbers():
    rows = [{"page": i, "number": n, "title": "", "label": ""}
            for i, n in enumerate(["A-101", "A-101", "A-101", "A-102",
                                   "ACC778", "ACC778", "ACC778"])]
    out = sheets.fix_numbers(rows)
    assert [r["number"] for r in out][:3] == ["A-101"] * 3
    assert all(r["number"] != "ACC778" for r in out)


def test_xfdf_shared_plain_names_stay_together(tmp_path):
    from app import xfdf
    doc = fitz.open()
    doc.new_page()
    p = tmp_path / "m.xfdf"
    p.write_text(
        '<?xml version="1.0"?><xfdf xmlns="http://ns.adobe.com/xfdf/">'
        '<annots>'
        '<square page="0" rect="10,10,50,50" name="M1"/>'
        '<freetext page="0" rect="10,60,50,80" name="M1"/>'
        '<square page="0" rect="100,10,150,50"/>'
        '<square page="0" rect="200,10,250,50"/>'
        '</annots></xfdf>', encoding="utf-8")
    marks = xfdf.import_marks(doc, str(p))
    sizes = sorted(len(m[2]["annots"]) for m in marks)
    assert sizes == [1, 1, 2]


def test_long_text_flows_onto_new_pages(tmp_path):
    from app import rfilog
    doc = fitz.open()
    doc.new_page()
    long = " ".join(f"word{i}" for i in range(4000))
    rfilog.add(doc, "RFI", title="Long one", question=long + " ENDQ")
    out = tmp_path / "log.pdf"
    rfilog.export_pdf(doc, str(out))
    text = "".join(pg.get_text() for pg in fitz.open(str(out)))
    assert "ENDQ" in text
    letter = tmp_path / "l.pdf"
    bidletters.write_pdf(str(letter), "Dear Sir,\n" + long + " ENDL")
    d = fitz.open(str(letter))
    assert d.page_count > 1 and "ENDL" in "".join(p.get_text() for p in d)


def test_flow_text_breaks_pages():
    doc = fitz.open()
    pg = doc.new_page()
    pg2, y = forms.flow_text(pg, 36, 300, 700, "x " * 2000, 9,
                             lambda: (doc.new_page(), 36), 760)
    assert doc.page_count > 1 and pg2.number == doc.page_count - 1


def test_revision_quantity_groups_with_bar_and_open_count(monkeypatch):
    before = {"items": {}, "quantities": {"Wall|2x6|ft": 10.0}}
    after = {"items": {}, "quantities": {"Wall|2x6|ft": 12.0}}
    q = revisions.changes(before, after)["quantities"][0]
    assert (q["group"], q["unit"]) == ("Wall|2x6", "ft")
    refs = [{"p": i} for i in range(2000)]
    data = {"revisions": [{"no": 1, "label": "A1", "date": "2026-01-01",
                           "flagged": 2500, "flagged_refs": refs,
                           "before": {"total": 0}}]}
    monkeypatch.setattr(revisions, "read", lambda d: data)
    monkeypatch.setattr(revisions, "flagged_refs",
                        lambda d: [{"p": i} for i in range(2500)])
    rows = revisions.log_rows(None, {"total": 0})
    assert rows[0]["open"] == 2500


def test_export_xlsx_prices_once(tmp_path, monkeypatch):
    calls = []
    snap = {"total": 100.0, "items": {}, "quantities": {}}
    monkeypatch.setattr(revisions, "snapshot",
                        lambda d: (calls.append(1), snap)[1])
    revs = [{"no": i, "label": f"R{i}", "date": "2026-01-01",
             "before": snap} for i in range(1, 6)]
    monkeypatch.setattr(revisions, "read", lambda d: {"revisions": revs})
    monkeypatch.setattr(revisions, "flagged_refs", lambda d: [])
    revisions.export_xlsx(None, str(tmp_path / "r.xlsx"))
    assert len(calls) == 1


def test_denied_edit_keeps_typed_values(tmp_path, monkeypatch):
    s = ProjectStore(str(tmp_path / "p"))
    s.data["hub"] = {"project": "J", "key": "k", "url": "ws://x"}
    s.save_record("rfi", {"subject": "Mine", "question": "typed text"})

    class Sess:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def call(self, op, **a):
            if op == "rec.put":
                return {"denied": "Viewers can't add RFIs."}
            return {"records": [], "seq": 0}
    monkeypatch.setattr(s, "client",
                        lambda: types.SimpleNamespace(session=Sess))
    res = s.sync()
    assert res["denied"] == 1
    rej = s.data["rejected"][0]
    assert rej["values"]["question"] == "typed text"
    assert "question" in s.last_denied and "Viewers" in s.last_denied


def test_report_bid_amount_with_dollar_sign(tmp_path):
    from app.pm import report
    s = ProjectStore(str(tmp_path / "p"))
    rec = {"bidders": [{"amount": "$1,200"}, {"amount": "950"}]}
    assert report.cell(s, "bidpkg", rec, "_low") == "$950"


def test_ball_in_court_is_text():
    rec = {"status": "Open", "to": ["Ann Arch", "Sam Sub"]}
    assert schema.ball_in_court("rfi", rec) == "Ann Arch; Sam Sub"
    assert schema.ball_in_court("rfi", {"status": "Closed"}) == ""


def test_old_xls_is_refused_clearly(tmp_path):
    p = tmp_path / "bidders.xls"
    p.write_bytes(b"\xd0\xcf\x11\xe0" + b"\0" * 100)
    with pytest.raises(ValueError, match="xlsx"):
        bidforms.import_rows(str(p))


def test_holiday_formats():
    import datetime as dt
    cal = schedule.Calendar(dt.date(2026, 7, 1),
                            ["7/3/2026", "2026-12-25", "12/31/26", "junk"])
    assert not cal.is_work(dt.date(2026, 7, 3))
    assert not cal.is_work(dt.date(2026, 12, 25))
    assert not cal.is_work(dt.date(2026, 12, 31))


def test_guard_prunes_expired_lockouts():
    t = [0.0]
    g = rc.Guard(tries=1, clock=lambda: t[0])
    for i in range(10001):
        g.fail(f"10.{i // 65536}.{i // 256 % 256}.{i % 256}")
    t[0] += g.lockout + 1
    g.fail("1.2.3.4")
    assert len(g.locked) == 1


def test_batch_slip_stop_and_failure_leave_nothing_open(tmp_path,
                                                        monkeypatch):
    from app import overlay, sets
    from test_sets import _files
    pa, pm, pr = _files(tmp_path)
    s = sets.new(str(tmp_path / "Job.pdfset"), [pa, pm])
    rep = sets.batch_slip(s, [pr], "Add 1", progress=lambda *a: True)
    assert rep["stopped"] and rep["files"] == [] and \
        not rep.get("new_sheets")
    opened = []
    real_open = fitz.open

    def tracking(*a, **k):
        d = real_open(*a, **k)
        opened.append(d)
        return d
    monkeypatch.setattr(sets.fitz, "open", tracking)

    def boom(*a, **k):
        raise RuntimeError("bad page")
    monkeypatch.setattr(overlay, "slip_sheet", boom)
    with pytest.raises(RuntimeError):
        sets.batch_slip(s, [pr], "Add 1")
    files = [d for d in opened if d.name]      # file handles matter
    assert files and all(d.is_closed for d in files)


def test_project_names_that_share_a_folder_are_refused(tmp_path):
    from app.collab import hub as hubmod
    H = hubmod.Hub(str(tmp_path / "hub"))
    H.call("proj.open", {"project": "Job/A", "password": "pw123456"}, {},
           True)
    with pytest.raises(hubmod.HubError, match="name like that"):
        H.call("proj.open", {"project": "Job?A", "password": "pw123456"},
               {}, True)
    H.call("proj.open", {"project": "job/a", "password": "pw123456"}, {},
           True)
