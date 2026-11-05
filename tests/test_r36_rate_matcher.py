"""r36 v2 step 7 (G4.1, G4.2, G4.4): Match Rates - the unpriced takeoff
groups matched to items in YOUR cost books (read-only: the price
database is never made or changed), in this order: your saved matches,
cost code + a unit that converts, then the description. Only exact
matches are ticked; loose ones are shown unticked with the reason; the
rest are listed. Apply (preview first) prices the ticked groups in one
step; saved matches make the next job match on the first pass.
Made-up data only; the database is a temporary one."""
import glob
import json
import os
from decimal import Decimal

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import (assemblies, costbook, estimate, estimate_lines as EL,  # noqa
                 pricedb, settings)
from app.estimating import _io, boq, checks                        # noqa: E402
from estimate_helpers import area, blank_doc                       # noqa: E402

D = Decimal


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(assemblies, "LIBRARY_PATH",
                        str(tmp_path / "assemblies.json"))
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)
    os.makedirs(settings.DIR, exist_ok=True)


BOOK = {"name": "Test Rates", "effective": "2026-01-01", "items": {
    "09 29 00": {"desc": "Gypsum board 5/8 in", "unit": "sf",
                 "material": 0.60},
    "09 65 19": {"desc": "Resilient tile flooring", "unit": "sy",
                 "material": 27.00},
    "09 91 23": {"desc": "Paint walls", "unit": "sf", "material": 0.20,
                 "sub": 0.30},
    "06 10 00": {"desc": "Rough carpentry", "unit": "lf", "material": 2.0},
}}


def _save_book():
    pricedb.save_book(costbook.Book(BOOK).to_dict())      # test db only


def _db_bytes():
    p = pricedb.path()
    return {os.path.basename(f): open(f, "rb").read()
            for f in sorted(glob.glob(glob.escape(p) + "*"))}


def _line(d, name, ft, y=500):
    from app import annotate
    annotate.apply_op(d, annotate.new_op(
        "add_line", 0, pts=[[100, y], [100 + ft * 10, y]],
        measure={"type": "length", "value": ft, "unit": "ft", "group": name}))


def _doc():
    d = blank_doc()
    area(d, "Gypsum board 5/8 in", 10, 10)
    estimate.set_price(d, "Gypsum board 5/8 in", "area", "sq ft",
                       code="09 29 00")
    area(d, "Resilient tile flooring", 10, 10, x0=200)
    area(d, "Paint walls", 10, 10, x0=400)
    _line(d, "Carpentry, rough", 50)
    _line(d, "Gypsum board", 20, y=550)
    estimate.set_price(d, "Gypsum board", "length", "ft", code="09 29 00")
    _line(d, "Mystery item", 5, y=600)
    area(d, "Priced thing", 5, 5, x0=600)
    estimate.set_price(d, "Priced thing", "area", "sq ft", unit_cost=5,
                       cost_type="Material")
    return d


def _by(res):
    return {r["target"]["name"]: r for r in res["rows"]}


def test_match_order_ticks_and_counts():
    _save_book()
    d = _doc()
    res = boq.match(d, boq.read_books())
    by = _by(res)
    assert "Priced thing" not in by and res["already_priced"] == 1
    g = by["Gypsum board 5/8 in"]
    assert g["status"] == "exact" and g["ticked"] and "code" in g["how"]
    t = by["Resilient tile flooring"]
    assert t["status"] == "exact" and t["ticked"] and "description" in t[
        "how"]
    assert t["unit_cost"] == D("3.0000")           # 27 / sy = 3 / sq ft
    c = by["Carpentry, rough"]
    assert c["status"] == "fuzzy" and not c["ticked"] and c["reason"]
    assert c["item"]["code"] == "06 10 00"
    b = by["Gypsum board"]                          # code ok, unit isn't
    assert b["status"] == "none" and "sf" in b["reason"]
    assert by["Mystery item"]["status"] == "none"
    assert res["counts"] == {"exact": 3, "fuzzy": 1, "none": 2}


def test_reading_never_makes_or_changes_the_database():
    d = _doc()
    assert not os.path.exists(pricedb.path())
    assert boq.read_books() == {}
    res = boq.match(d, boq.read_books())
    assert res["counts"]["exact"] == 0
    assert not os.path.exists(pricedb.path())       # no file made by a read
    _save_book()
    before = _db_bytes()
    boq.match(d, boq.read_books())
    assert _db_bytes() == before


def test_apply_prices_ticked_groups_once_with_preview():
    _save_book()
    d = _doc()
    res = boq.match(d, boq.read_books())
    pv = boq.preview(d, res["rows"])
    names = [p["name"] for p in pv["rows"]]
    assert sorted(names) == ["Gypsum board 5/8 in", "Paint walls",
                             "Resilient tile flooring"]
    assert pv["total"] == D("60.00") + D("300.00") + D("50.00")
    out = boq.apply(d, res["rows"])
    assert out["priced"] == 2 and out["lines"] == 1
    tot = {g["name"]: g for g in estimate.lines(d)}
    assert round(tot["Resilient tile flooring"]["unit_cost"], 4) == 3.0
    assert tot["Gypsum board 5/8 in"]["unit_cost"] == pytest.approx(0.6)
    paint = [ln for ln in EL.priced(d) if ln["desc"] == "Paint walls"]
    assert len(paint) == 1 and paint[0]["linked"]
    # again: nothing doubles (they are priced now)
    res2 = boq.match(d, boq.read_books())
    assert res2["already_priced"] == 4
    assert boq.apply(d, res2["rows"]) == {"priced": 0, "lines": 0,
                                          "skipped": []}
    found = checks.run(d)
    assert not [f for f in found
                if f["rule"] in ("double_priced", "no_cost_type")]


def test_untick_and_tick_and_refusal():
    _save_book()
    d = _doc()
    res = boq.match(d, boq.read_books())
    by = _by(res)
    by["Resilient tile flooring"]["ticked"] = False
    by["Carpentry, rough"]["ticked"] = True         # the user ticks it
    by["Gypsum board"]["ticked"] = True             # no item: refused
    out = boq.apply(d, res["rows"])
    assert out["priced"] == 2                       # gyp 5/8 + carpentry
    assert [s["name"] for s in out["skipped"]] == ["Gypsum board"]
    g = {x["name"]: x for x in estimate.lines(d)}
    assert g["Resilient tile flooring"]["unit_cost"] == 0
    assert g["Carpentry, rough"]["unit_cost"] == pytest.approx(2.0)


def test_saved_matches_match_first_next_time(tmp_path):
    _save_book()
    d = _doc()
    res = boq.match(d, boq.read_books())
    by = _by(res)
    by["Carpentry, rough"]["ticked"] = True
    p = str(tmp_path / "my matches.json")
    n = boq.save_matches(boq.remember({}, res["rows"]), p)
    assert n == 4
    m = boq.load_matches(p)
    d2 = _doc()
    res2 = boq.match(d2, boq.read_books(), mapping=m)
    c = _by(res2)["Carpentry, rough"]
    assert c["status"] == "exact" and c["ticked"] and c["how"] == \
        "your saved match"
    assert res2["counts"]["fuzzy"] == 0
    # overwrite keeps a backup; a system folder is refused
    boq.save_matches(m, p)
    assert glob.glob(str(tmp_path / "*.bak*")) or glob.glob(
        os.path.join(settings.DIR, "backups", "*"))
    with pytest.raises(_io.PathError):
        boq.save_matches(m, os.path.join(os.path.dirname(_io.__file__),
                                         "x.json"))


def test_a_saved_match_to_a_missing_item_falls_back():
    _save_book()
    d = _doc()
    m = {"version": 1, "matches": {boq.match_key("Mystery item"): {
        "book": "Test Rates", "code": "99 99 99", "desc": "gone"}}}
    r = _by(boq.match(d, boq.read_books(), mapping=m))["Mystery item"]
    assert r["status"] == "none" and "99 99 99" in r["reason"]


def test_bad_matches_file_is_refused(tmp_path):
    p = tmp_path / "m.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(boq.MatchError):
        boq.load_matches(str(p))
