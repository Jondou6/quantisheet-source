"""r36 v2 step 5 (safety): the estimating tools never seed or write the
price database without asking.

0.13.9's Estimate Error Check and the crew tools read the civil library
with heavy.library(), which fills an EMPTY price database with the
starter library the first time - without a word. Now:

  * reading (estimate, error check, crew hours, quote, materials,
    actuals, suggest) never creates the price database and leaves one
    that's there byte-for-byte the same;
  * the starter civil library goes in only when you say Yes to a clear
    question (safedb.civil_library(ask)); No leaves the database as it
    was;
  * the EXAMPLE crews go in only after a clear confirm (with how many
    records), a backup copy of the database is made first, and Cancel
    leaves it byte-for-byte the same;
  * starter templates, the supplier price import and Bid-Day "Use This
    Quote" never touch the price database (each asks first in the
    window).
Made-up data only; the database is a temporary one."""
import glob
import hashlib
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QDialog, QMessageBox              # noqa: E402

from app import (assemblies, estimate, estimate_lines as EL, heavy,  # noqa: E402,E501
                 pricedb, settings)
from app.estimating import (actuals, bidday, checks, crewhours, flow,  # noqa: E402,E501
                            items, materials, quotes, safedb, starters,
                            supplier_prices, templates)
from estimate_helpers import area, blank_doc                     # noqa: E402
from test_r36_bidday import _sheet                               # noqa: E402


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(assemblies, "LIBRARY_PATH",
                        str(tmp_path / "assemblies.json"))
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)
    os.makedirs(settings.DIR, exist_ok=True)
    from app import assembly_csv
    monkeypatch.setattr(assembly_csv, "_CACHE", {})


def _db():
    return pricedb.path()


def _bytes():
    """The price database's files (the db and any journal), as bytes."""
    p = _db()
    return {os.path.basename(f): open(f, "rb").read()
            for f in sorted(glob.glob(glob.escape(p) + "*"))}


def _seeded():
    heavy.library()                       # the 0.13.9 starter fill (test db)
    assert heavy.library()["crews"]
    return _bytes()


def _empty_db():
    with pricedb.connect():
        pass
    assert os.path.isfile(_db())
    return _bytes()


def _drawing():
    d = blank_doc()
    area(d, "Test slab", 20, 30)
    area(d, "Test site grading", 50, 40, x0=300)
    estimate.set_price(d, "Test slab", "area", "sq ft", unit_cost=3,
                       cost_type="Material", code="03 30 00")
    EL.add(d, [EL.new_line("Test permit", 1, "ls", sub=250)])
    job = heavy.blank()
    job["pay_items"] = [{"no": "10", "desc": "Test grading", "unit": "sq ft",
                         "owner_qty": "2000", "weight": "1"}]
    heavy.add_activity(job, "Test fine grade", unit="sq ft", crew="GRADE",
                       rate=500, pay_item="10", group="Test site grading")
    heavy.write(d, job)
    return d


def _read_everything(d):
    job, lib = flow.civil(d)
    items.collect(d, job, lib)
    items.collect(d)
    checks.run(d)
    checks.run(d, job=job, lib=lib)
    flow.run(d)
    quotes.compute(d)
    materials.order_list(d, (), job, lib)
    actuals.compare(d, job, lib)
    crewhours.by_pay_item(job, lib)
    starters.suggest_bindings(d, starters.estimate_templates()[1], job)
    safedb.read_civil_library()
    safedb.needs_seed()


# ---- reading only ---------------------------------------------------------

def test_reading_never_creates_the_price_database():
    d = _drawing()
    _read_everything(d)
    assert not os.path.exists(_db())
    assert _bytes() == {}


def test_reading_leaves_a_seeded_database_byte_identical():
    before = _seeded()
    d = _drawing()
    _read_everything(d)
    assert _bytes() == before


def test_reading_leaves_an_empty_database_byte_identical_and_unseeded():
    before = _empty_db()
    d = _drawing()
    _read_everything(d)
    assert _bytes() == before
    assert safedb.needs_seed()


# ---- seeding the starter civil library -------------------------------------

def test_civil_library_never_seeds_without_asking():
    before = _empty_db()
    lib = safedb.civil_library()                 # no question = no seed
    assert not lib["crews"] and not lib["labor"] and not lib["equipment"]
    assert _bytes() == before


def test_civil_library_no_leaves_the_database_byte_identical():
    for make in (_empty_db, lambda: {}):
        if os.path.exists(_db()):
            os.remove(_db())
        before = make()
        asked = []
        lib = safedb.civil_library(ask=lambda q: asked.append(q) or False)
        assert len(asked) == 1
        assert "starter civil library" in asked[0].lower()
        assert "price database" in asked[0].lower()
        assert not lib["crews"]
        assert _bytes() == before


def test_civil_library_yes_seeds_the_starter_library():
    _empty_db()
    lib = safedb.civil_library(ask=lambda q: True)
    assert lib["crews"]
    assert not safedb.needs_seed()


def test_civil_library_already_there_is_not_asked_again():
    before = _seeded()
    lib = safedb.civil_library(ask=lambda q: pytest.fail("asked"))
    assert lib["crews"] == heavy.library()["crews"]
    assert _bytes() == before


def test_flow_civil_and_error_check_never_seed():
    before = _empty_db()
    d = _drawing()
    job, lib = flow.civil(d)
    assert job is not None and not lib["crews"]
    checks.run(d, job=job, lib=lib)
    flow.run(d)
    assert _bytes() == before
    asked = []
    flow.civil(d, ask=lambda q: asked.append(q) or False)
    assert asked and _bytes() == before


# ---- EXAMPLE crews -------------------------------------------------------

def test_example_crews_cancel_leaves_the_database_byte_identical():
    for make in (_seeded, _empty_db):
        if os.path.exists(_db()):
            os.remove(_db())
        before = make()
        asked = []
        n = starters.install_crews(confirm=lambda q: asked.append(q) or False)
        assert n == 0
        assert len(asked) == 1 and "EX-" in asked[0]
        pack = starters.crew_pack()
        total = sum(len(pack[k]) for k in ("labor", "equipment", "crews"))
        assert str(total) in asked[0]
        assert _bytes() == before
        assert not glob.glob(os.path.join(settings.DIR, "backups", "*"))


def test_example_crews_no_database_cancel_creates_nothing():
    n = starters.install_crews(confirm=lambda q: False)
    assert n == 0 and not os.path.exists(_db())


def test_example_crews_need_a_confirm():
    with pytest.raises(TypeError):
        starters.install_crews()                    # noqa


def test_example_crews_yes_backs_the_database_up_first():
    before = _seeded()
    n = starters.install_crews(confirm=lambda q: True)
    assert n > 0
    assert "EX-GRADE" in heavy.library()["crews"]
    baks = glob.glob(os.path.join(settings.DIR, "backups", "*.db"))
    assert len(baks) == 1
    import sqlite3
    con = sqlite3.connect(baks[0])
    try:
        n_crews = con.execute("SELECT COUNT(*) FROM heavy_crews").fetchone()[0]
        ex = con.execute("SELECT COUNT(*) FROM heavy_crews WHERE code "
                         "LIKE 'EX-%'").fetchone()[0]
    finally:
        con.close()
    assert n_crews > 0 and ex == 0                 # the copy is from before
    assert before                                     # (it was there)


def test_example_crews_nothing_missing_asks_nothing():
    _seeded()
    starters.install_crews(confirm=lambda q: True)
    after = _bytes()
    assert starters.install_crews(confirm=lambda q: pytest.fail("asked")) == 0
    assert _bytes() == after


# ---- paths that must never touch the database ------------------------------

def _never_touches(fn):
    fn()
    assert not os.path.exists(_db()), "price database created"
    before = _seeded()
    fn()
    assert _bytes() == before


def test_starter_templates_never_touch_the_database(tmp_path):
    n = [0]

    def go():
        n[0] += 1
        starters.install(str(tmp_path / f"tpl{n[0]}"))
        starters.install()
    _never_touches(go)


def test_supplier_price_import_never_touches_the_database(tmp_path):
    src = tmp_path / "list.csv"
    src.write_text("SKU,Description,Unit,Price\nT1,Test pipe,LF,3.50\n",
                   encoding="utf-8")
    n = [0]

    def go():
        n[0] += 1
        supplier_prices.import_file(str(src), "Test Supply",
                                    str(tmp_path / f"out{n[0]}.json"))
    _never_touches(go)


def test_bid_day_use_this_quote_never_touches_the_database():
    def go():
        d = _drawing()
        bidday.save(d, _sheet())
        bidday.apply_quote(d, "Test earthwork")
        bidday.apply_quote(d, "Test earthwork", "Test Sub C")
        bidday.remove_quote(d, "Test earthwork")
    _never_touches(go)


def test_templates_apply_never_touches_the_database():
    def go():
        d = _drawing()
        t = starters.estimate_templates()[1]
        templates.apply(d, t, starters.suggest_bindings(d, t))
        starters.civil_fill(heavy.read(d))
    _never_touches(go)


def test_database_writes_go_through_the_host_connection(monkeypatch):
    """Our writes use pricedb.connect(write=True) - the host's path (its
    shared-database and offline rules)."""
    _seeded()
    seen = []
    real = pricedb.connect

    def spy(write=False):
        seen.append(write)
        return real(write)
    monkeypatch.setattr(pricedb, "connect", spy)
    starters.install_crews(confirm=lambda q: True)
    assert True in seen


# ---- the window asks first ------------------------------------------------

from test_gui import win, qapp                                   # noqa: E402,F401,E501
from app.estimating import ui                                    # noqa: E402


@pytest.fixture
def no_to_all(monkeypatch):
    asked = []

    def q(*a, **k):
        asked.append(" ".join(str(x) for x in a[1:3]))
        return QMessageBox.No
    monkeypatch.setattr(QMessageBox, "question", staticmethod(q))
    monkeypatch.setattr(QDialog, "exec", lambda self, *a: 0)
    ui._SEED_DECLINED.clear()
    return asked


def test_window_error_check_asks_before_seeding(win, qapp, no_to_all):
    before = _empty_db()
    d = win._view.doc
    job = heavy.blank()
    heavy.add_activity(job, "Test fine grade", unit="sq ft", crew="GRADE",
                       rate=500, qty=100)
    heavy.write(d, job)
    dlg = ui.open_tools(win, "check")
    dlg.page("check").run()
    assert len(no_to_all) == 1
    assert "starter civil library" in no_to_all[0].lower()
    dlg.page("check").run()                        # No is remembered
    dlg.page("crew").refresh()
    assert len(no_to_all) == 1
    assert _bytes() == before


def test_window_example_crews_cancel(win, qapp, no_to_all):
    before = _seeded()
    dlg = ui.open_tools(win, "templates")
    dlg.page("templates").add_crews()
    assert len(no_to_all) == 1 and "EX-" in no_to_all[0]
    assert _bytes() == before


def test_window_starter_templates_cancel(win, qapp, no_to_all):
    before = _seeded()
    dlg = ui.open_tools(win, "templates")
    dlg.page("templates").add_starters()
    assert len(no_to_all) == 1
    assert not os.path.isdir(templates.folder()) or \
        not os.listdir(templates.folder())
    assert _bytes() == before


def test_window_use_this_quote_asks_first(win, qapp, no_to_all):
    before = _seeded()
    d = win._view.doc
    bidday.save(d, _sheet())
    dlg = ui.open_tools(win, "bidday")
    pg = dlg.page("bidday")
    pg.refresh()
    pg.package.setCurrentText("Test earthwork")
    n0 = len(EL.read(d))
    pg.use_quote()
    assert len(no_to_all) == 1
    assert len(EL.read(d)) == n0
    assert _bytes() == before
