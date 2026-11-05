"""Master Schedule: nothing is sent to subs - drafts only, opened for
review in Outlook by Jon's click."""
import os
import re

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import mail, settings                                  # noqa: E402
from app.pm.master import apply, drafts, intake, model          # noqa: E402
from app.pm.master.formats import excel                         # noqa: E402
from r39_master_fixtures import (ACME, BEST, CYCLE, act, fill,  # noqa: E402
                                 make_store)

PKG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(
    __file__))), "app", "pm", "master")


def test_open_draft_always_opens_for_review(tmp_path, monkeypatch):
    s = make_store(tmp_path, monkeypatch)
    settings._cache["mail_review"] = False          # global setting off
    got = []
    monkeypatch.setattr(mail, "send",
                        lambda *a, **k: got.append((a, k)) or "outlook")
    d = drafts.reminder(s, ACME, CYCLE)
    assert d["to"] == "ann@acme.example"
    drafts.open_draft(d)
    assert got[0][1]["display"] is True and d["opened"]


def test_whole_flow_sends_nothing(tmp_path, monkeypatch):
    s = make_store(tmp_path, monkeypatch)

    def no(*a, **k):
        raise AssertionError("mail.send called without Jon's click")
    monkeypatch.setattr(mail, "send", no)
    a5 = act(s, "A0005")
    a5["owner_co"] = BEST                     # a downstream trade
    s.save_record("activity", a5)
    inbox = tmp_path / "in"
    model.set_config(s, inbox=str(inbox))
    for c in (ACME, BEST):
        (inbox / c).mkdir(parents=True)
    intake.prepare_packets(s, CYCLE)
    p = excel.generate(s, ACME, str(tmp_path / "a.xlsx"), cycle=CYCLE)
    fill(p, {"A0002": {"% complete": 0}})
    sub = apply.receive(s, p, ACME)
    assert sub["status"] == "Pending review"
    done = apply.approve(s, sub["_id"], by="Jon")
    kinds = [d["kind"] for d in done["drafts"]]
    assert kinds == ["received", "accepted", "slip"]
    slip = done["drafts"][-1]
    assert slip["company"] == BEST and "A0005" in slip["body"]
    p2 = excel.generate(s, ACME, str(tmp_path / "b.xlsx"), cycle=CYCLE)
    fill(p2, {"A0002": {"% complete": 999}})
    rej = apply.receive(s, p2, ACME)
    assert rej["drafts"][-1]["kind"] == "rejected"
    assert "0 to 100" in rej["drafts"][-1]["body"]
    assert all(d["opened"] is None for x in model.submissions(s)
               for d in x["drafts"])


def test_no_network_or_send_code_in_module():
    bad = re.compile(r"\b(smtplib|socket|urllib|requests|http\.client|"
                     r"websockets|hubclient)\b|\.Send\(\)")
    hits, mail_uses = [], []
    for dp, _dn, fn in os.walk(PKG):
        for f in fn:
            if not f.endswith(".py"):
                continue
            src = open(os.path.join(dp, f), encoding="utf-8").read()
            if bad.search(src):
                hits.append(f)
            for m in re.finditer(r"mail_module\.send|mail\.send", src):
                mail_uses.append(f)
    assert hits == []
    assert mail_uses == ["drafts.py"]          # only open_draft()
