"""Fixes from the 0.12.4 release review (Oct 17): B1 starter rates no
longer re-price saved estimates, H1 billing money never reads a typo as
$0, H2 e-sign never drops or mangles typed answers, H3 civil estimate
rates flag text and blanks instead of pricing them at $0."""
import base64
import copy
import os
from decimal import Decimal

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import esign, heavy, money, settings                  # noqa: E402
from test_gui import qapp, win                                 # noqa: E402,F401

HERE = os.path.dirname(os.path.abspath(__file__))
OLD_STARTER = os.path.join(HERE, "heavy_starter_old_samples.json")


@pytest.fixture(autouse=True)
def _cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {"author": "Pat Morgan",
                                             "email": "jon@example.com"})
    os.makedirs(settings.DIR, exist_ok=True)


# ------------------------------------------------- B1: no silent re-price
def _sewer_job():
    job = heavy.blank()
    job["activities"].append({"name": "8in sewer", "qty": 1000, "unit": "LF",
                              "crew": "PIPE", "rate": 20, "per": "hour"})
    return job


def test_new_starter_does_not_reprice_a_saved_estimate(monkeypatch):
    """0.12.3 seeded the price database with the old sample rates and Jon
    edited LAB. Opening the same job after the upgrade must show the same
    total until someone accepts the new rates."""
    new_starter = heavy.STARTER
    monkeypatch.setattr(heavy, "STARTER", OLD_STARTER)
    lib = heavy.library()                                    # old install
    heavy.save_items("labor", [dict(lib["labor"]["LAB"], base=19.00)])
    lib = heavy.library()
    assert heavy.totals(_sewer_job(), lib)["total"] == Decimal("23771.55")
    monkeypatch.setattr(heavy, "STARTER", new_starter)      # upgrade and
    # 0.12.4 rewrote rates once per run; resetting its flag is a relaunch
    # (the fixed code has no such flag, so this is a no-op there)
    monkeypatch.setattr(heavy, "_REFRESHED", False, raising=False)
    lib = heavy.library()
    assert lib["equipment"]["EXC-20"]["own_hr"] == 48
    assert heavy.totals(_sewer_job(), lib)["total"] == Decimal("23771.55")
    # the newer rates are offered, not applied
    ups = heavy.starter_updates()
    assert sum(len(v) for v in ups.values()) > 0
    assert "LAB" not in {r["code"] for r in ups.get("labor", [])}
    # only an explicit accept changes the library (Jon's LAB edit stays)
    n = heavy.apply_starter_updates()
    assert n == sum(len(v) for v in ups.values())
    lib = heavy.library()
    assert lib["equipment"]["EXC-20"]["own_hr"] == 68.47
    assert lib["labor"]["LAB"]["base"] == 19.0
    assert heavy.starter_updates() == {}


def test_starter_check_is_safe_when_the_shared_database_is_read_only(
        monkeypatch):
    """Shared price database offline (local read-only copy): opening the
    Civil Estimate must not try to write (0.12.4 raised PriceDBError)."""
    from app import pricedb
    new_starter = heavy.STARTER
    monkeypatch.setattr(heavy, "STARTER", OLD_STARTER)
    heavy.library()
    monkeypatch.setattr(heavy, "STARTER", new_starter)
    monkeypatch.setattr(heavy, "_REFRESHED", False, raising=False)
    real = pricedb.connect

    def ro(write=False):
        if write:
            raise pricedb.PriceDBError("shared price database is offline")
        return real()
    monkeypatch.setattr(pricedb, "connect", ro)
    lib = heavy.library()                              # no write, no raise
    assert lib["equipment"]["EXC-20"]["own_hr"] == 48
    assert heavy.starter_updates()                     # still offered
    with pytest.raises(pricedb.PriceDBError):
        heavy.apply_starter_updates()


def test_civil_window_offers_new_rates_in_one_line_and_flags_typos(
        qapp, monkeypatch):
    """One non-modal line names how many rates changed; nothing changes
    until Use new rates. A typo in a rate cell isn't saved as $0."""
    from PySide6.QtWidgets import QMessageBox, QWidget
    from app.heavy_ui import HeavyDialog
    boxes = []
    for name in ("information", "warning", "question", "critical"):
        monkeypatch.setattr(QMessageBox, name,
                            lambda *a, **k: boxes.append(a))
    new_starter = heavy.STARTER
    monkeypatch.setattr(heavy, "STARTER", OLD_STARTER)
    heavy.library()
    monkeypatch.setattr(heavy, "STARTER", new_starter)
    holder = QWidget()
    dlg = HeavyDialog(holder, 0)
    n = sum(len(v) for v in heavy.starter_updates().values())
    assert not dlg.rates_bar.isHidden()
    assert dlg.rates_note.text().startswith(f"{n} starter rates")
    assert dlg.lib["equipment"]["EXC-20"]["own_hr"] == 48
    dlg.use_new_rates()
    assert dlg.rates_bar.isHidden()
    assert dlg.lib["equipment"]["EXC-20"]["own_hr"] == 68.47
    r = sorted(dlg.lib["labor"]).index("LAB")
    dlg._edit_labor(r, 2, "twenty")                  # base column
    assert heavy.library()["labor"]["LAB"]["base"] != 0
    assert "twenty" in dlg.problems.text()
    dlg._edit_labor(r, 2, "")                        # cleared: not $0 either
    assert heavy.library()["labor"]["LAB"]["base"] != 0
    assert "blank" in dlg.problems.text()
    r = sorted(dlg.lib["equipment"]).index("EXC-20")
    dlg._edit_equipment(r, dlg.EKEYS.index("own_hr"), "")
    assert heavy.library()["equipment"]["EXC-20"]["own_hr"] == 68.47
    assert boxes == []


# ------------------------------------------- H1: billing never reads $0
@pytest.mark.parametrize("bad", ["abc", "12,5OO", "1.2.3"])
def test_num_unreadable_is_none_not_zero(bad):
    assert money._num(bad) is None


def test_num_reads_money_and_accounting_negatives():
    assert money._num("$1,234.50") == 1234.5
    assert money._num("(500)") == -500.0
    assert money._num("($1,250.00)") == -1250.0
    assert money._num("") == 0.0 and money._num(None) == 0.0
    assert money._num("(-500)") is None              # which sign? flag it


def _contract():
    d = fitz.open()
    d.new_page()
    money.set_sov(d, [{"desc": "Sitework", "scheduled": 10000}])
    return d


def test_pay_app_cell_typo_is_refused_not_dropped(qapp, win, tmp_path,
                                                  monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    said = []
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a, **k: said.append(a[2]))
    d = _contract()
    path = str(tmp_path / "j.pdf")
    d.save(path)
    win.open_path(path)
    dlg = win.billing()
    dlg._app_new("2026-01-31")
    dlg.app.item(0, 4).setText("12,5OO")          # "This period" work
    qapp.processEvents()
    assert any("12,5OO" in t for t in said)


def test_billing_entries_refuse_unreadable_money():
    d = _contract()
    with pytest.raises(money.BillingError, match="12,5OO"):
        money.set_sov(d, [{"desc": "Sitework", "scheduled": "12,5OO"}])
    with pytest.raises(money.BillingError, match="abc"):
        money.new_change(d, "Extra rock", amount="abc")
    cid = money.new_change(d, "Extra rock", amount="$1,000")
    with pytest.raises(money.BillingError, match="abc"):
        money.update_change(d, cid, cost="abc")
    assert money.update_change(d, cid, cost="$1,000")["cost"] == 1000
    no = money.new_pay_app(d, "2026-01-31")
    with pytest.raises(money.BillingError, match="1.2.3"):
        money.set_progress(d, no, "1", work="1.2.3")
    with pytest.raises(money.BillingError, match="abc"):
        money.waiver(d, "conditional_progress", "2026-01-31", "abc")
    assert money.sov(d)[0]["scheduled"] == 10000


def test_pay_app_shows_a_stored_unreadable_amount():
    d = _contract()
    no = money.new_pay_app(d, "2026-01-31")
    data = money.read(d)
    data["payapps"][0]["lines"]["1"] = {"work": "12,5OO", "stored": 0}
    money.write(d, data)
    v = money.compute(d, no)
    assert any("12,5OO" in w for w in v["warnings"])
    with pytest.raises(money.BillingError, match="can't be read"):
        money.certify(d, no)                 # never freeze it at $0


def test_table_total_counts_unreadable_cells(qapp):
    from app.pm.widgets import LinesEdit
    w = LinesEdit([("crew", "Crew", "text"), ("hours", "Hours", "number")])
    w.set_value([{"crew": "A", "hours": 1500}, {"crew": "B", "hours": 20},
                 {"crew": "C", "hours": "12,5OO"},
                 {"crew": "D", "hours": "(500)"}])
    t = w.total.text()
    assert "1,020" in t                 # 1500 + 20 - 500
    assert "1 can't be read" in t


# --------------------------------------- H2: e-sign keeps every answer
LONG = ("Example Builders LLC, 1234 Long Industrial Parkway, Suite 500,"
        " Myrtle Beach SC")
UNI = "José Núñez – Ωmega Ł ✓"
PNG = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 12), 0)
PNG.clear_with(40)
SIG = base64.b64encode(PNG.tobytes("png")).decode()


def _envelope(tmp_path, answers, rect=(72, 100, 252, 118)):
    path = str(tmp_path / "SC-9.pdf")
    d = fitz.open()
    d.new_page()
    d.save(path)
    d.close()
    fields = [{"id": f"f{i}", "page": 0, "rect": [rect[0], rect[1] + 40 * i,
                                                  rect[2], rect[3] + 40 * i],
               "kind": "text", "signer": 0} for i in range(len(answers))]
    env = {"id": "ENV-1", "provider": "hub", "path": path, "title": "SC-9",
           "sha256": esign.file_sha(path), "created": "2026-10-17T15:00",
           "fields": fields, "status": "sent"}
    st = {"status": "completed", "events": [],
          "signers": [{"name": "Lee Volt", "email": "lee@volt.example",
                       "values": {f"f{i}": {"kind": "text", "text": t}
                                  for i, t in enumerate(answers)}}]}
    return env, st, fields


def test_long_and_unicode_answers_are_stamped_intact(tmp_path, monkeypatch):
    monkeypatch.setattr(esign, "remember", lambda env: None)
    env, st, fields = _envelope(tmp_path, ["Jon Doe", LONG, UNI])
    out = esign.finish(env, st=st, seal=False)
    page = fitz.open(out)[0]
    got = [" ".join(page.get_textbox(fitz.Rect(f["rect"]) +
                                     (-2, -2, 2, 2)).split())
           for f in fields]
    assert got[0] == "Jon Doe"
    assert got[1] == LONG
    assert got[2] == UNI


def test_refuses_to_complete_when_an_answer_cannot_fit(tmp_path,
                                                       monkeypatch):
    monkeypatch.setattr(esign, "remember", lambda env: None)
    env, st, _f = _envelope(tmp_path, [LONG * 6], rect=(72, 100, 112, 106))
    with pytest.raises(esign.ESignError, match="Lee Volt"):
        esign.finish(env, st=st, seal=False)
    assert env["status"] != "completed"
    assert not os.path.exists(esign._signed_name(env["path"]))


# --------------------------- H3: civil estimate flags text / blank rates
def test_text_or_blank_rate_is_flagged_not_priced_at_zero():
    lib = heavy.library()
    assert heavy.crew_rate(lib["crews"]["PIPE"], lib)["total"] == \
        Decimal("508.75")
    bad = copy.deepcopy(lib)
    bad["labor"]["LAB"]["base"] = "twenty"         # text in a number field
    bad["equipment"]["EXC-20"]["own_hr"] = ""      # blank rate
    cr = heavy.crew_rate(bad["crews"]["PIPE"], bad)
    flagged = " ".join(cr["unreadable"])
    assert "LAB" in flagged and "twenty" in flagged and "EXC-20" in flagged
    job = _sewer_job()
    t = heavy.totals(job, bad)
    assert any("twenty" in p and "EXC-20" in p for p in t["problems"])


def test_unreadable_material_cost_is_flagged():
    lib = heavy.library()
    job = heavy.blank()
    job["activities"].append({"name": "8in PVC", "qty": 1000, "unit": "LF",
                              "materials": [{"desc": "8in PVC", "qty_per": 1,
                                             "cost": "8.5O"}]})
    c = heavy.activity_cost(job["activities"][0], lib, job)
    assert "8.5O" in c["problem"]
    good = dict(job["activities"][0], materials=[{"desc": "8in PVC",
                                                  "qty_per": 1,
                                                  "cost": "8.50"}])
    c = heavy.activity_cost(good, lib, job)
    assert c["problem"] == "" and c["material"] == Decimal("8500.00")
    quoted = dict(good, quotes=[{"id": "q1", "use": True, "kind": "sub",
                                 "per": "LS", "price": "4,5OO"}])
    assert "4,5OO" in heavy.activity_cost(quoted, lib, job)["problem"]
