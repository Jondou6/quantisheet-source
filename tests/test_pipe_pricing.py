"""Pipe priced by diameter: cost book size tables, used by the civil
takeoff's trench assemblies (D = diameter)."""
import csv
import os

import pytest

from app import assemblies, costbook


def test_size_price_exact_between_and_outside():
    item = {"material": 11.0, "labor": 0.0, "sub": 0.0,
            "sizes": costbook._sizes({"8": 11, "12": {"material": 24,
                                                      "labor": 0.1}})}
    got, note = costbook.size_price(item, 8)
    assert got["material"] == 11 and note == ""
    got, note = costbook.size_price(item, 10)
    assert got["material"] == pytest.approx(17.5) and note == ""
    assert got["labor"] == pytest.approx(0.05)
    got, note = costbook.size_price(item, 30)
    assert got["material"] == 24 and "priced at 12 in" in note
    assert costbook.size_price({"material": 5}, 8)[0]["material"] == 5


def test_starter_book_prices_sewer_by_size():
    b = costbook.Book(costbook.load(os.path.join(
        os.path.dirname(costbook.__file__), "data", "costbooks",
        "QuantiSheet Starter 2026.json")).to_dict())
    it = b.get("A-33-GRAVSEWER-6-10.1")
    assert it["sizes"]["8"]["material"] == 11.0
    assert it["sizes"]["12"]["material"] > it["sizes"]["8"]["material"]
    lib = assemblies.library()
    base = lib["A-33-GRAVSEWER-6-10"] if "A-33-GRAVSEWER-6-10" in lib else \
        next(a for a in lib.values() if a.get("name", "").startswith(
            "Gravity sewer, PVC SDR-35, 6-10"))

    def pipe_cost(d):
        a = dict(base, props=dict(base.get("props") or {}, D=d))
        out, problems = assemblies.priced(a, b)
        part = next(p for p in out["parts"]
                    if str(p.get("code", "")).endswith(".1"))
        return part["cost"], problems
    c8, p8 = pipe_cost(8)
    c12, _ = pipe_cost(12)
    assert c12 / c8 == pytest.approx(it["sizes"]["12"]["material"] / 11.0,
                                     rel=1e-6)
    _c, p48 = pipe_cost(48)
    assert any("priced at 27 in" in p for p in p48)
    assert not any("in isn't in the price table" in p for p in p8)


def test_csv_with_sizes(tmp_path):
    p = tmp_path / "book.csv"
    with open(p, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Code", "Description", "Unit", "Material", "Size"])
        w.writerow(["P-1", "SDR-35 pipe", "LF", "9", "8"])
        w.writerow(["P-1", "SDR-35 pipe", "LF", "21", "12"])
        w.writerow(["X-1", "Manhole", "EA", "4000", ""])
    b = costbook.from_csv(str(p), "Mine")
    assert set(b.get("P-1")["sizes"]) == {"8", "12"}
    assert costbook.size_price(b.get("P-1"), 10)[0]["material"] == \
        pytest.approx(15)
    b2 = costbook.Book(b.to_dict())
    assert b2.get("P-1")["sizes"]["12"]["material"] == 21


def test_size_tables_survive_the_price_database(tmp_path, monkeypatch):
    from app import pricedb, settings
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {})
    os.makedirs(settings.DIR, exist_ok=True)
    b = costbook.Book({"name": "Sized", "items": {
        "P-1": {"unit": "lf", "material": 9,
                "sizes": {"8": 9, "12": 21}}}})
    pricedb.save_book(b.to_dict())
    got = costbook.load(costbook.DB + "Sized").get("P-1")
    assert got["sizes"]["12"]["material"] == 21
    pricedb.update_items("Sized", {"P-1": {"material": 10}})
    got = costbook.load(costbook.DB + "Sized").get("P-1")
    assert got["material"] == 10 and got["sizes"]["8"]["material"] == 9
