"""PM review NW-02, NW-03, NW-12: the Daily Log list, man-hours and
search (made-up dailies)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.pm import schema                                      # noqa: E402
from app.pm.center import search_records                       # noqa: E402


def _dailies():
    out = []
    for n in range(1, 14):
        out.append({"_id": f"d{n}", "_no": f"DL-{n:04d}",
                    "date": f"2026-11-{n:02d}", "status": "Submitted",
                    "work": "Clear and grub" if n < 3 else "Site drainage",
                    "manpower": [{"company": "Example Sitework",
                                  "workers": 6, "hours": 8}],
                    "weather": {"conditions": "Clear"},
                    "photos": [{"name": f"EX_2026_{n:03d}.jpg"}]})
    out[3]["manpower"].append({"company": "Example Granite Concrete",
                               "workers": 2, "hours": 9})
    out[8]["manpower"].append({"company": "Example Granite Concrete",
                               "workers": 2, "hours": 9})
    out[5]["weather"] = {"conditions": "Rain", "precip": "0.6 in"}
    out[6]["delays"] = [{"cause": "Weather", "hours": 4,
                         "description": "Rain, site too wet"}]
    return out


def test_submitted_dailies_listed_and_counted():
    d = _dailies()
    assert schema.default_chip("daily") == "All"
    assert schema.nav_count("daily", d) == 13
    assert schema.default_chip("rfi") == "Open"     # others unchanged
    assert schema.nav_count("rfi", [{"status": "Closed"},
                                    {"status": "Open"}]) == 1


def test_man_hours_total():
    cols = [c for c in schema.field("daily", "manpower")["cols"]]
    rows = [{"company": "Red", "workers": "6", "hours": "8"},
            {"company": "GC", "workers": "2", "hours": "9"}]
    tot = {lb: v for lb, v, _b in schema.line_totals(cols, rows)}
    assert tot["Workers"] == 8 and tot["Man-hours"] == 66
    assert "Hours each" not in tot


def test_search_reads_tables_weather_and_photo_names():
    d = _dailies()
    assert [r["_no"] for r in search_records(d, "Granite")] == \
        ["DL-0004", "DL-0009"]
    rain = [r["_no"] for r in search_records(d, "Rain")]
    assert rain[:2] == ["DL-0006", "DL-0007"]       # real rain days first
    assert set(rain[2:]) <= {r["_no"] for r in d
                             if "drainage" in r["work"]}
    assert [r["_no"] for r in search_records(d, "EX_2026_005")] == \
        ["DL-0005"]
    assert len(search_records(d, "")) == 13
