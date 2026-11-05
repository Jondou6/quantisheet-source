"""Fixes from Claude's Oct 16 review of the v2 code bundle."""
import os
from decimal import Decimal

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import heavy, settings                              # noqa: E402
from app.collab import relaycore                              # noqa: E402
from app.pm import bidforms                                   # noqa: E402
from test_gui import qapp                                     # noqa: E402,F401

D = Decimal


@pytest.fixture(autouse=True)
def _cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {"author": "Pat Morgan"})
    os.makedirs(settings.DIR, exist_ok=True)


# 1 - relay: a faked X-Forwarded-For can't pass for this computer
def test_forwarded_header_only_trusted_from_a_local_proxy(monkeypatch):
    f = relaycore.forwarded_ip
    assert f("203.0.113.7", "127.0.0.1") == "203.0.113.7"   # internet: ignored
    assert f("127.0.0.1", "127.0.0.1, 198.51.100.4") == "198.51.100.4"
    # 0.13.5: a private-network peer is believed only when it is named in
    # TRUSTED_PROXIES (Fly / Render set it); by default it is ignored
    monkeypatch.delenv("TRUSTED_PROXIES", raising=False)
    assert f("10.1.2.3", "8.8.8.8") == "10.1.2.3"
    monkeypatch.setenv("TRUSTED_PROXIES", "10.0.0.0/8")
    assert f("10.1.2.3", "8.8.8.8") == "8.8.8.8"             # Fly / Render
    monkeypatch.delenv("TRUSTED_PROXIES")
    assert f("127.0.0.1", "") == "127.0.0.1"
    assert not relaycore.is_loopback(f("198.51.100.9", "127.0.0.1"))


def test_server_copies_match():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for a, b in (("app/collab/relaycore.py", "server/relaycore.py"),
                 ("app/collab/hub.py", "server/hub.py")):
        assert open(os.path.join(root, a), "rb").read() == \
            open(os.path.join(root, b), "rb").read()


# 2 - an allowance left at 0 takes the bidder's price
def test_allowance_at_zero_uses_bidder_price():
    lines = [bidforms.L(1, "Rock excavation (allowance)", "Allowance", 0,
                        "CY"),
             bidforms.L(2, "Set allowance", "Allowance", 5000, "LS")]
    t = bidforms.totals(lines, {"0": "2,500", "1": "999"})
    assert t["base"] == 7500.0
    built_in = bidforms.BUILT_IN["Site utilities"]
    i = next(n for n, ln in enumerate(built_in) if ln["type"] == "Allowance")
    assert bidforms.line_total(built_in[i], "1200") == 1200.0


# 4 - indirects and markup stay in the bid with no activities on pay items
def test_spread_keeps_markup_without_assigned_activities():
    lib = heavy.library()
    job = heavy.blank()
    job["pay_items"] = [{"no": "1", "desc": "Mob", "unit": "LS",
                         "owner_qty": "1", "weight": "1"},
                        {"no": "2", "desc": "Pipe", "unit": "LF",
                         "owner_qty": "100", "weight": "1"}]
    job["indirects"] = [{"desc": "Overhead", "rate": "2000", "per": "LS"}]
    job["settings"]["markup_pct"] = 0
    s = heavy.spread(job, lib)
    assert sum(i["share"] for i in s["items"]) == D("2000.00")
    assert s["note"] and s["rounding"] == D("0.00")


# 5 - table totals include rows of 1,000 or more
def test_lines_total_counts_thousands(qapp):
    from app.pm.widgets import LinesEdit
    w = LinesEdit([("crew", "Crew", "text"), ("hours", "Hours", "number")])
    w.set_value([{"crew": "A", "hours": 1500}, {"crew": "B", "hours": 20}])
    assert "1,520" in w.total.text()


# 6 - Loaded Rate Builder opens when every current rate is 0
def test_loaded_rate_builder_with_zero_rates(qapp):
    from app.loaded_rate_ui import LoadedRateDialog
    dlg = LoadedRateDialog({"Carpenter": 0.0, "Laborer": 0.0})
    assert "Average trade rate" in dlg.summary.text()


# 7 - a date with no year, Feb 29
def test_date_without_year():
    import datetime as dt
    from app.pm.widgets import parse_date
    y = dt.date.today().year
    assert parse_date("10/15") == f"{y}-10-15"
    leap = y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)
    assert (parse_date("2/29") is not None) == leap


# 8 - no tempfile.mktemp left
def test_no_mktemp():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for dirpath, _d, files in os.walk(os.path.join(root, "app")):
        for f in files:
            if f.endswith(".py"):
                assert "mktemp(" not in open(os.path.join(dirpath, f),
                                             encoding="utf-8").read(), f


# 10 - award / regret letters don't pile up in .pm_letters
def test_letters_working_copies_removed(tmp_path):
    from app.pm import bidletters

    class Store:
        folder = str(tmp_path)
        name = "Job"
        me = "Jon"
        kept = []

        def setting(self, k):
            return None

        def attach(self, p):
            self.kept.append(open(p, "rb").read()[:4])
            return {"name": os.path.basename(p)}
    st = Store()
    rec = {"title": "Sewer", "_no": "BP-001",
           "bidders": [{"company": "A Co", "amount": 100},
                       {"company": "B Co", "amount": 120}]}
    refs = bidletters.make_letters(st, rec, rec["bidders"][0])
    assert len(refs) == 2 and st.kept == [b"%PDF", b"%PDF"]
    assert os.listdir(os.path.join(str(tmp_path), ".pm_letters")) == []
