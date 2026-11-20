"""Bid day and hold days (Nov 19): kept with the bid-submittal checklist;
Estimate Error Check warns about a quote that runs out before the bid has
to hold. Made-up names and dates."""
import datetime
import os
import sys

import fitz
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import bidsubmittal as bs  # noqa: E402
from app.estimating import bidday, bidgate, checks  # noqa: E402

T = datetime.date(2026, 11, 20)


@pytest.fixture
def doc(tmp_path, monkeypatch):
    from app import settings
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)
    d = fitz.open()
    d.new_page()
    return d


def test_hold_until_and_contents_lines(doc):
    st = bs.blank()
    assert bs.hold_until(st) is None
    st.update(bid_date="2026-12-08", hold_days=90)
    st = bs.write(doc, st)
    assert bs.read(doc)["hold_days"] == 90
    assert bs.hold_until(st) == datetime.date(2027, 3, 8)
    ls = bs.lines(st)
    assert "Bid day: 2026-12-08" in ls
    assert "Bid holds for 90 days (to 2027-03-08)" in ls
    bad = bs._clean({"bid_date": "next week", "hold_days": "lots"})
    assert bad["bid_date"] == "" and bad["hold_days"] == 0


def test_quote_shorter_than_the_hold_is_flagged(doc):
    sheet = bidday.new_sheet("Paint", [{"id": "1", "desc": "Walls",
                                        "unit": "ls", "qty": "1"}],
                             [{"name": "Acme Painting", "prices": {"1": "900"},
                               "valid_until": "2027-01-07"}])
    bidday.save(doc, sheet)
    bidday.apply_quote(doc, "Paint")
    assert not [f for f in bidgate.stale(doc, today=T)
                if f["rule"] == "quote_short_hold"]
    bs.write(doc, dict(bs.blank(), bid_date="2026-12-08", hold_days=90))
    found = [f for f in bidgate.stale(doc, today=T)
             if f["rule"] == "quote_short_hold"]
    assert len(found) == 1 and "2027-03-08" in found[0]["message"]
    assert found[0]["severity"] == "warning"
    assert "quote_short_hold" in checks.RULES and \
        "quote_short_hold" in checks.HOW_TO
    # a quote that already ran out is "expired", not both
    late = T + datetime.timedelta(days=60)
    rules = [f["rule"] for f in bidgate.stale(doc, today=late)]
    assert "quote_expired" in rules and "quote_short_hold" not in rules
    job = {"activities": [{"name": "Base", "quotes": [
        {"vendor": "Rock Co", "kind": "material", "use": True,
         "valid_until": "2027-01-01"}]}]}
    assert any("Rock Co" in f["item"] for f in bidgate.stale(doc, job, T)
               if f["rule"] == "quote_short_hold")


try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from test_gui import win, qapp  # noqa: F401,E402
except Exception:                                         # noqa: BLE001
    pass


def test_checklist_window_keeps_bid_day_and_hold(win, tmp_path):
    d = fitz.open()
    d.new_page()
    p = tmp_path / "job.pdf"
    d.save(p)
    d.close()
    assert win.open_path(str(p))
    from app.bidsubmittal_ui import SubmittalDialog
    sd = SubmittalDialog(win._view.doc, win, ask_anyway=lambda t: True)
    sd.bid_date.setText("2026-12-08")
    sd.hold.setValue(60)
    assert sd.go() is True
    st = bs.read(win._view.doc)
    assert st["bid_date"] == "2026-12-08" and st["hold_days"] == 60
    sd2 = SubmittalDialog(win._view.doc, win)
    assert sd2.hold.value() == 60 and sd2.bid_date.text() == "2026-12-08"


def test_competition_on_the_board_and_in_go_no_go(tmp_path, monkeypatch):
    from app import bidboard as B, settings
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)
    o = B.clean({"project": "Example Park Restroom", "bidders": "12 bidders",
                 "plan_holders": "30", "prebid_mandatory": "mandatory"})
    assert (o["bidders"], o["plan_holders"], o["prebid_mandatory"]) == \
        ("12", "30", "Yes")
    assert B.competition_answer(o) == "No"
    assert B.competition_answer(dict(o, bidders="")) == "No"   # 30/2 = 15
    assert B.competition_answer(dict(o, bidders="", plan_holders="12")) \
        == "Partly"
    assert B.competition_answer(dict(o, bidders="3")) == "Yes"
    assert B.competition_answer({"bidders": "", "plan_holders": ""}) == ""
    assert B.clean({"project": "x", "prebid_mandatory": "maybe"})[
        "prebid_mandatory"] == ""
    assert "competition" in dict(B.FACTORS)
    # left blank it doesn't move the score
    sc = B.go_score({"scope": "Yes", "location": "Partly",
                     "workload": "No"})
    assert sc["score"] == 59.1
    assert B.go_score({"scope": "Yes", "competition": "No"})["score"] == \
        round(1000 * 25 / 35) / 10


def test_go_window_starts_competition_from_the_board(win, tmp_path,
                                                      monkeypatch):
    from app import bidboard as B, settings
    from app.bidboard_ui import GoDialog
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)
    o = B.save(B.clean({"project": "Example Lift Station", "bidders": "6",
                        "prebid_mandatory": "Yes"}))
    dlg = GoDialog(o, win, items=[o])
    assert dlg.box["competition"].currentText() == "Partly"


SPEC = ["INSTRUCTIONS TO BIDDERS. Each bid shall be accompanied by a bid "
        "bond in an amount equal to five percent (5%) of the bid. No bidder "
        "may withdraw a bid within ninety (90) days after the actual date "
        "of opening. A MANDATORY pre-bid conference will be held on "
        "November 30, 2026 at the site.",
        "This project is subject to the Davis-Bacon Act. The DBE "
        "participation goal for this contract is 8%. The Owner will retain "
        "5% of each progress payment. The Contractor shall substantially "
        "complete the work within 180 calendar days. Liquidated damages "
        "will be assessed as set in the Agreement.",
        "ADDITIVE ALTERNATE NO. 1: canopy. DEDUCTIVE ALTERNATE NO. 2: "
        "paving. Alternate No. 1 is repeated here."]


def _spec(path):
    d = fitz.open()
    for t in SPEC:
        pg = d.new_page()
        pg.insert_textbox(fitz.Rect(54, 54, 558, 738), t, fontsize=10)
    d.save(path)
    d.close()


def test_bid_terms_found_with_pages(tmp_path):
    from app import bidterms
    p = tmp_path / "spec.pdf"
    _spec(str(p))
    got = {f["key"]: (f["value"], f["page"])
           for f in bidterms.find(fitz.open(str(p)))}
    assert got["bid_bond"] == ("5% of the bid", 0)
    assert got["hold_days"] == ("90 days", 0)
    assert got["prebid"][0].startswith("mandatory, November 30, 2026")
    assert got["prevailing_wage"][1] == 1 and got["liquidated"][1] == 1
    assert got["goals"][0] == "DBE 8%" and got["retainage"][0] == "5%"
    assert got["contract_time"][0] == "180 days"
    assert got["alternates"] == ("2 (No. 1, 2)", 2)
    assert bidterms.hold_days(bidterms.find(fitz.open(str(p)))) == 90
    blank = fitz.open()
    blank.new_page().insert_text((72, 72), "GENERAL NOTES", fontsize=10)
    assert bidterms.find(blank) == []


def test_bid_terms_window_puts_hold_days_in_the_checklist(win, tmp_path):
    p = tmp_path / "spec.pdf"
    _spec(str(p))
    assert win.open_path(str(p))
    dlg = win.bid_terms(show=False)
    assert dlg.table.rowCount() == 9
    dlg.go([f["key"] for f in dlg.found].index("prevailing_wage"))
    assert win._view.page == 1
    assert dlg.use_hold() == 90
    assert bs.read(win._view.doc)["hold_days"] == 90
