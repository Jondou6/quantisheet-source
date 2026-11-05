"""Chief's v18-v22 wired in: personal invites and follow-ups sent only from
the Bids@ mailbox, the addendum "what changed" draft, sub proposal PDFs and
plug suggestions in Bid Leveling, and the Civil > Export to HeavyBid."""
import datetime as dt
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz                                                   # noqa: E402
import pytest                                                 # noqa: E402

from app import mail                                          # noqa: E402
from app.pm import actions                                    # noqa: E402
from test_gui import win, qapp                                # noqa: E402,F401


class Store:
    connected = False
    name = "Shelter Cove"
    data = {"number": "3059", "owner": "Aiken County"}

    def email_of(self, who):
        return ""

    def attachment_path(self, a):
        raise OSError("no file")



@pytest.fixture(autouse=True)
def _example_sender(monkeypatch):
    """The real company mailbox lives in a private data file; tests use an
    example one."""
    from app import bid_followup as invite_boost   # folded Nov 4
    monkeypatch.setattr(invite_boost, "DEFAULT_SENDER",
                        {"name": "Example Builders",
                         "email": "Bids@builder.example"})

@pytest.fixture
def outbox(monkeypatch, tmp_path):
    from app import settings
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {})
    box = []
    monkeypatch.setattr(mail, "OUTBOX", box)
    return box


def test_send_as_never_falls_back_to_your_own_mailbox(monkeypatch):
    monkeypatch.setattr(mail, "OUTBOX", None)
    monkeypatch.setattr(mail, "outlook_available", lambda: False)
    with pytest.raises(mail.MailError, match="Nothing was sent"):
        mail.send(["sub@dig.example"], "ITB", "hi",
                  send_as="Bids@builder.example")

    class Acc:
        def __init__(self, a):
            self.SmtpAddress = a
    accs = [Acc("jon@builder.example"),
            Acc("bids@builder.example")]
    assert mail.outlook_account(accs, "Bids@Builder.example") \
        is accs[1]
    assert mail.outlook_account(accs[:1], "bids@builder.example") \
        is None


def test_invite_is_personal_and_from_bids(outbox):
    pkg = {"title": "Site Utilities", "trades": "33 30 00 sewer",
           "due": "2026-11-20", "due_time": "2:00 PM", "status": "Draft",
           "bidders": [{"company": "Dig Co", "contact": "Steve Rogers",
                        "email": "est@dig.example"}]}
    ctx = actions.Ctx(Store())
    r = actions.bid_invite(ctx, pkg)
    (m,) = outbox
    assert m["send_as"] == "Bids@builder.example"
    assert m["subject"].startswith("ITB: Shelter Cove - Site Utilities")
    assert m["body"].startswith("Hi Steve,") and "Job #3059" in m["body"]
    assert m["html"] is None              # no link: plain text + documents
    assert r["bidders"][0]["invited"]


def test_followups_due_go_out_once(outbox):
    inv = (dt.date.today() - dt.timedelta(days=4)).isoformat()
    pkg = {"title": "Site Utilities", "status": "Open",
           "due": (dt.date.today() + dt.timedelta(days=20)).isoformat(),
           "bidders": [{"company": "Dig Co", "contact": "Steve",
                        "email": "est@dig.example", "invited": inv,
                        "token": ""},
                       {"company": "Pipe Pros", "email": "bid@pipe.example",
                        "invited": inv, "status": "Won't Bid"}]}
    ctx = actions.Ctx(Store())
    ctx.ask = lambda title, opts: opts[0]
    r = actions.bid_followups(ctx, pkg)
    assert len(outbox) == 1 and outbox[0]["subject"].startswith(
        "Did this reach you?")
    assert outbox[0]["send_as"] == "Bids@builder.example"
    assert r["bidders"][0]["followups"] == ["not_opened"]
    assert actions.bid_followups(ctx, r) is None      # nothing due again
    assert len(outbox) == 1


def test_addendum_draft_from_the_revised_pdf(monkeypatch, tmp_path):
    from app import addendum_summary as asum
    cur = fitz.open()
    cur.new_page()
    new = tmp_path / "ADD2.pdf"
    d = fitz.open()
    d.new_page()
    d.save(str(new))
    monkeypatch.setattr(asum, "summarize", lambda a, b: {
        "changed": [{"sheet": "C-301", "pct": 12.0, "areas": 2,
                     "takeoffs": {"8\" sewer": 1}}],
        "added": ["C-305"], "removed": [], "unchanged": ["C-302"]})
    ctx = actions.Ctx(Store(), takeoff_doc=lambda: cur)
    txt = actions._addendum_draft(ctx, {"title": "Site Utilities",
                                        "trades": "sewer"}, str(new), "2")
    assert txt.startswith("Addendum 2") and "C-301" in txt
    assert actions._addendum_draft(ctx, {}, None, "2") == ""


def test_heavybid_export_from_civil(win, tmp_path):
    from test_civil_export import _result
    out = win.export_heavybid(folder=str(tmp_path / "hb"), soil="B",
                              result=_result(), ask=False)
    for k in ("biditems", "activities", "resources"):
        assert os.path.isfile(out[k]) and out[k].endswith(".xlsx")
    assert out["check"]["ok"]


def test_sub_proposals_and_plug_suggestions(qapp, monkeypatch, tmp_path):
    from app import leveling_ui, proposal_level
    props = {
        "a.pdf": {"bidder": "Dig Co", "total": 12000.0, "unread": [],
                  "lines": [{"desc": "8 in PVC sewer", "unit": "LF",
                             "qty": 100, "price": 50.0, "amount": 5000.0},
                            {"desc": "Manhole", "unit": "EA", "qty": 2,
                             "price": 3500.0, "amount": 7000.0}]},
        "b.pdf": {"bidder": "Pipe Pros", "total": 5500.0, "unread": [],
                  "lines": [{"desc": "8 in PVC sewer", "unit": "LF",
                             "qty": 100, "price": 55.0, "amount": 5500.0}]}}
    monkeypatch.setattr(proposal_level, "parse", lambda p: props[
        os.path.basename(p)])
    monkeypatch.setattr(leveling_ui.QMessageBox, "information",
                        lambda *a, **k: None)
    dlg = leveling_ui.LevelingDialog()
    res = dlg.use_proposals([str(tmp_path / "a.pdf"),
                             str(tmp_path / "b.pdf")])
    assert res and len(res["results"]) == 2
    monkeypatch.setattr(proposal_level, "suggest_plugs", lambda res: [
        {"bidder": "Pipe Pros", "item": "Manhole", "unit": "EA", "qty": 2,
         "unit_price": 3400.0, "amount": 6800.0, "source": "past bids"}])
    sug = dlg.suggest_plugs(accept=True)
    assert sug and dlg.plugs[-1]["item"] == "Manhole" and \
        dlg.plugs[-1]["amount"] == 6800.0
