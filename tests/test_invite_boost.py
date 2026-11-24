"""v18: personal bid invitations from the user's own mailbox (dry run)."""
import pytest
import email
import json

from app import bid_followup as ib  # was invite_boost (folded Nov 4)


PKG = {"title": "Yard Piping", "trades": "33 31 00 Sanitary sewer; utilities",
       "due": "2026-11-12", "due_time": "2:00 PM ET",
       "scope": "12-36 in DIP/PVC gravity and force main, manholes.",
       "prebid": "Oct 28, 10:00 AM ET at the plant (mandatory)",
       "rfi_due": "Nov 3, 5:00 PM ET", "specs": "33 05 00, 33 31 00",
       "requirements": "10% bid bond, Davis-Bacon wages, 12% DBE goal",
       "bidders": [
           {"company": "Acme Pipe", "contact": "Steve Rogers",
            "email": "steve@acme.test", "token": "tokA"},
           {"company": "Beta Util", "contact": "", "email": "bids@beta.test",
            "token": "tokB"},
           {"company": "Gone Co", "contact": "Al", "email": "al@gone.test",
            "status": "Won't Bid", "token": "tokC"},
           {"company": "No Mail", "contact": "Bo", "email": ""}]}
PROJECT = {"name": "Riverside WWTP Upgrades", "number": "2611",
           "owner": "City of Riverside"}
SENDER = {"name": "Jon Smith", "email": "jon@yourco.test",
          "signature": "Jon Smith | Chief Estimator\nYour Co | 555-0100"}
SHEETS = ["G-001", "C-101", "C-102", "C-103", "U-201", "U-202", "S-101",
          "A-101", "E-101"]



@pytest.fixture(autouse=True)
def _example_sender(monkeypatch):
    """The real company mailbox lives in a private data file; tests use an
    example one."""
    from app import bid_followup as invite_boost
    monkeypatch.setattr(invite_boost, "DEFAULT_SENDER",
                        {"name": "Example Builders",
                         "email": "Bids@builder.example"})

def test_first_name_subject_and_cta():
    m = ib.build_invite(PKG, PKG["bidders"][0], PROJECT, SENDER,
                        link="https://hub.test/bid.html?t=tokA",
                        sheets=SHEETS)
    assert m["to"] == ["steve@acme.test"]
    assert m["from"] == "Jon Smith <jon@yourco.test>"
    assert m["reply_to"] == "jon@yourco.test"
    assert m["subject"] == ("ITB: Riverside WWTP Upgrades - Yard Piping - "
                            "Bids due 2026-11-12 2:00 PM ET")
    assert m["text"].startswith("Hi Steve,")
    assert "View Files and Project Details" in m["html"]
    assert "https://hub.test/bid.html?t=tokA" in m["text"]
    for intent in ("yes", "unsure", "no"):
        assert f"t=tokA&amp;intent={intent}" in m["html"]
    assert "Sheets to start with: C-101 to C-103, U-201 to U-202" in m["text"]
    assert "Jon Smith | Chief Estimator" in m["text"]
    assert "10% bid bond" in m["text"] and "Pre-bid meeting" in m["text"]


def test_no_contact_name_falls_back_to_company_team():
    m = ib.build_invite(PKG, PKG["bidders"][1], PROJECT, SENDER)
    assert m["text"].startswith("Hi Beta Util team,")
    assert "reply to this email" in m["text"].lower()


def test_sheets_for_trade():
    assert ib.sheets_for_trade("Electrical", SHEETS) == ["E-101"]
    assert ib.sheets_for_trade("Earthwork and paving", SHEETS) == \
        ["C-101", "C-102", "C-103"]
    assert ib.ranges(["C-101", "C-102", "C-104", "U-201"]) == \
        "C-101 to C-102, C-104, U-201"


def test_invite_all_dry_run_one_email_each_never_sends(tmp_path, monkeypatch):
    from app import mail
    monkeypatch.setattr(mail, "send", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("real mail must not be sent")))
    box = ib.DryRunOutbox(str(tmp_path / "outbox"))
    res = ib.invite_all(PKG, PROJECT, SENDER, box,
                        link_for=lambda b: f"https://hub.test/bid.html?t={b['token']}",
                        sheets=SHEETS, today="2026-10-16")
    assert res["sent"] == 2 and res["skipped"] == {"Gone Co": "declined",
                                                   "No Mail": "no email"}
    emls = sorted((tmp_path / "outbox").glob("*.eml"))
    assert len(emls) == 2
    msg = email.message_from_bytes(emls[0].read_bytes())
    assert msg["To"] in ("steve@acme.test", "bids@beta.test")
    assert msg["X-QuantiSheet-Dry-Run"] == "yes"
    log = [json.loads(x) for x in (tmp_path / "outbox" / "log.jsonl")
           .read_text().splitlines()]
    assert [e["event"] for e in log] == ["dry-run", "dry-run"]
    b = PKG["bidders"][0]
    assert b["invited"] == "2026-10-16" and b["status"] == "Invited"
    assert b["events"][-1]["event"] == "sent"


def test_deliverability_log_and_bounce_resend(tmp_path):
    box = ib.DryRunOutbox(str(tmp_path / "ob"))
    pkg = json.loads(json.dumps(PKG))
    ib.invite_all(pkg, PROJECT, SENDER, box, today="2026-10-16")
    ib.record_bounce(pkg, "bids@beta.test", "550 no such user")
    beta = pkg["bidders"][1]
    assert beta["status"] == "Bounced"
    assert ib.bounce_queue(pkg) == [beta]
    beta["email"] = "estimating@beta.test"           # fixed inline
    res = ib.resend(pkg, beta, PROJECT, SENDER, box, today="2026-10-17")
    assert res and beta["status"] == "Invited"
    assert beta["email_history"] == ["bids@beta.test"]
    rows = ib.deliverability(pkg)
    assert {r["company"]: r["last"] for r in rows}["Beta Util"] == "sent"


def test_html_matches_preconsuite_style_layout():
    build_invite = ib.build_invite
    pkg = {"title": "BP1 - Demolition", "due": "May 20, 2026", "due_time": "2:00 PM"}
    b = {"company": "Keystone", "contact": "Mike Russo", "email": "m@k.example"}
    link = "https://relay.example/bid?t=abc"
    m = build_invite(pkg, b, {"name": "El Segundo WTP #3", "location": "El Segundo, CA"},
                     {"name": "Jon", "email": "j@x"}, link, ["C-101"])
    h = m["html"]
    order = ["Company Logo", "INVITATION TO BID", "El Segundo WTP #3: BP1 - Demolition",
             "El Segundo, CA", "Bids are due by:", "Will you be bidding?",
             ">Yes<", ">No<", ">Unsure<", "View Files and Project Details"]
    pos = [h.index(x) for x in order]
    assert pos == sorted(pos)
    assert "May 20, 2026 2:00 PM" in h
    for c in ("#28a745", "#d93a2b", "#F4C430", "#0b5cad"):
        assert c in h
    import re
    visible = re.sub(r'(href|src)="[^"]*"', "", h)
    assert "relay.example" not in visible
    import re as _re
    uns = _re.search(r'<a [^>]*>Unsure</a>', h).group(0)
    assert "background:#F4C430" in uns and "color:#1f1f1f" in uns
    assert "Hi Mike" not in h  # nothing extra above the buttons
    for v in ("yes", "unsure", "no"):
        assert f"{link}&intent={v}" in m["text"]
    assert "<script" not in h and "<style" not in h
    m2 = build_invite(pkg, b, {"name": "P"}, {"name": "J", "email": "j@x",
                      "logo_url": "https://cdn.example/logo.png"}, link)
    assert 'src="https://cdn.example/logo.png"' in m2["html"]
    assert "Company Logo" not in m2["html"]
    m3 = build_invite(pkg, b, {"name": "P"}, {"name": "J", "email": "j@x",
                      "company": "Example Builders",
                      "logo_url": "cid:logo", "logo_width": 260}, link)
    assert 'width="260"' in m3["html"] and 'alt="Example Builders"' in m3["html"]


def test_default_sender_is_company_bids_mailbox_and_overridable():
    pkg = {"title": "Yard Piping", "due": "Nov 12"}
    b = {"contact": "Mike Russo", "email": "m@k.example"}
    m = ib.build_invite(pkg, b, {"name": "P"}, {}, "https://r.example/x?t=1")
    assert ib.DEFAULT_SENDER == {"name": "Example Builders",
                                 "email": "Bids@builder.example"}
    assert m["from"] == "Example Builders <Bids@builder.example>"
    assert m["reply_to"] == "Bids@builder.example"
    m2 = ib.build_invite(pkg, b, {"name": "P"},
                         {"name": "Other Co", "email": "est@other.example"})
    assert m2["from"] == "Other Co <est@other.example>"
    m3 = ib.build_invite(pkg, b, {"name": "P"}, None)
    assert "Bids@builder.example" in m3["from"]
