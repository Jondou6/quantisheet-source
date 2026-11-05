"""P1 features that were already built - checked against the brief's
acceptance (made-up data): assemblies from one measurement with a height
that updates every part (#3); the user's own CSV price book, nothing
preloaded (#4)."""
from app import assemblies, costbook


def test_one_wall_measure_many_items_and_height_updates_all():
    wall = {"name": "Example Partition", "measure": "length",
            "props": {"Height": 8},
            "parts": [
                {"name": "Studs", "unit": "ea", "qty": "length / 1.333 + 1"},
                {"name": "Board", "unit": "sq ft",
                 "qty": "length * height * 2"},
                {"name": "Tape", "unit": "ft", "qty": "board / 32 * 12"},
                {"name": "Paint", "unit": "sq ft", "qty": "board"}]}
    got = {p["name"]: p["qty"] for p in assemblies.compute(
        wall, {"length": 100.0})}
    assert round(got["Studs"]) == 76 and got["Board"] == 1600
    assert got["Paint"] == got["Board"] and got["Tape"] == 600
    wall["props"]["Height"] = 10
    got2 = {p["name"]: p["qty"] for p in assemblies.compute(
        wall, {"length": 100.0})}
    assert got2["Board"] == 2000 and got2["Paint"] == 2000
    assert got2["Tape"] == 750 and got2["Studs"] == got["Studs"]


def test_users_own_csv_price_book(tmp_path):
    p = tmp_path / "my prices.csv"
    p.write_text("Code,Description,Unit,Material,Labor,Sub\n"
                 "09 29 00,Example gypsum board,SF,0.55,0.02,\n"
                 "09 91 23,Example interior paint,SF,0.20,0.01,\n")
    book = costbook.from_csv(str(p), name="My Book 2026")
    assert book.name == "My Book 2026"
    assert book.get("09 29 00")["material"] == 0.55
    assert len(book.items) == 2              # only what the user gave
